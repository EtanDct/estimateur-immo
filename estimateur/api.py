"""API HTTP de l'estimateur : expose les fonctions du paquet au site.

Ce module ne contient aucune logique métier : il reçoit les requêtes, appelle estimation.py et
modele.py et traduit les résultats et les erreurs en réponses HTTP.

À lancer depuis la racine du projet : python -m uvicorn estimateur.api:app --reload
Documentation interactive : http://127.0.0.1:8000/docs

Variables d'environnement (facultatives) :
    CLES_API : les clés d'API acceptées, séparées par des virgules. Si elle est définie, toutes les
    routes sauf /health exigent l'en-tête X-API-Key (erreur 401 sinon). Sans elle, l'API est ouverte.
    ORIGINES_AUTORISEES : sites autorisés à appeler l'API depuis un navigateur (CORS),
    séparés par des virgules. Par défaut : le site et son serveur de développement local.
    LIMITE_ESTIMATION, LIMITE_DEFAUT : nombre de requêtes autorisées par visiteur (adresse IP),
    au format "30/minute". Au-delà, l'API répond 429.
    DOSSIER_DONNEES : le dossier qui contient prix_communes.csv et modeles.joblib (par défaut data/villes/).
    ACTIVER_DOCS : si elle est définie (par exemple 1), les pages /docs et /redoc sont servies. Elles
    chargent leurs scripts depuis un CDN public : désactivées par défaut.
"""

import hmac
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from .config import DOSSIER_VILLES
from .donnees import charger_prix_communes
from .estimation import BienIntrouvable, ParametreInvalide, noms_communes, zone_couverte
from .modele import charger_modeles, estimer_prix

ORIGINES_PAR_DEFAUT = "https://www.tatane.me,https://tatane.me,http://localhost:4321"

# Durée pendant laquelle un navigateur peut garder la réponse de /communes et /info : ces données ne
# changent qu'à chaque nouvelle version des fichiers de données.
CACHE_STATIQUE = "public, max-age=3600"


class Estimation(BaseModel):
    """La réponse de /estimation."""

    commune: str
    type_local: Literal["Maison", "Appartement"]
    surface: float
    nombre_ventes: int
    annee_min: int
    annee_max: int
    prix_m2_median: int
    prix_bas: int
    prix_median: int
    prix_haut: int
    methode: Literal["adresse", "commune", "mediane"]
    repli: str | None = None


class Erreur(BaseModel):
    """Le format de toutes les erreurs."""

    detail: str


REPONSES_ERREUR = {
    401: {"model": Erreur, "description": "Clé d'API manquante ou invalide (si l'API exige une clé)."},
    404: {"model": Erreur, "description": "Commune inconnue, ou pas assez de ventes de ce type de bien."},
    422: {"model": Erreur, "description": "Paramètre invalide : surface, type de bien, adresse hors de la commune..."},
    429: {"model": Erreur, "description": "Trop de requêtes : voir l'en-tête Retry-After."},
}

# Limites par visiteur. /estimation, la seule route qui calcule, est la plus restreinte.
LIMITE_ESTIMATION = os.environ.get("LIMITE_ESTIMATION", "30/minute")
LIMITE_DEFAUT = os.environ.get("LIMITE_DEFAUT", "60/minute")


def _lire_cles():
    """Lit les clés d'API acceptées dans la variable d'environnement CLES_API (séparées par des virgules)."""
    return [cle.strip().encode() for cle in os.environ.get("CLES_API", "").split(",") if cle.strip()]


# Plusieurs clés à la fois : on peut en changer sans interruption (ajouter la nouvelle, mettre le
# site à jour, retirer l'ancienne). Une liste vide veut dire que l'API n'exige aucune clé.
CLES_API = _lire_cles()


def _cle_valide(cle):
    """Dit si la clé reçue fait partie des clés acceptées."""
    if not cle:
        return False
    recue = cle.encode()
    # compare_digest prend le même temps que les deux clés se ressemblent ou non, pour qu'on ne
    # puisse pas deviner une clé caractère par caractère en mesurant la durée de la réponse.
    # La liste [...] force la comparaison avec toutes les clés, sans s'arrêter à la première.
    return any([hmac.compare_digest(recue, attendue) for attendue in CLES_API])


def exiger_cle(x_api_key: Annotated[str | None, Header(description="Clé d'API, si l'API en exige une.")] = None):
    """Refuse (401) une requête sans clé valide dans X-API-Key, si des clés sont configurées."""
    if CLES_API and not _cle_valide(x_api_key):
        raise HTTPException(status_code=401, detail="Clé d'API manquante ou invalide.")


def _visiteur(request: Request):
    """Identifie le visiteur pour la limite de requêtes : son adresse IP.

    Derrière Caddy, uvicorn la lit dans l'en-tête X-Forwarded-For (voir le Dockerfile) : sans cela,
    tous les visiteurs auraient l'IP de Caddy et se partageraient une seule limite.
    Quand le serveur du site appelle l'API, l'IP vue est celle de Vercel, la même pour tous les
    visiteurs : le site transmet donc la vraie dans X-Visiteur-IP. Cet en-tête n'est cru que si la
    requête porte une clé valide ; sinon n'importe qui pourrait l'inventer pour échapper à la limite.
    """
    transmise = request.headers.get("x-visiteur-ip")
    if CLES_API and transmise and _cle_valide(request.headers.get("x-api-key")):
        return transmise[:64]
    return get_remote_address(request)


# Les compteurs de la limite sont en mémoire : ils repartent de zéro au redémarrage.
limiter = Limiter(key_func=_visiteur, default_limits=[LIMITE_DEFAUT])


def _origines_autorisees():
    """Lit la liste des origines CORS dans la variable d'environnement, ou prend celles par défaut."""
    brut = os.environ.get("ORIGINES_AUTORISEES", ORIGINES_PAR_DEFAUT)
    return [origine.strip() for origine in brut.split(",") if origine.strip()]


@asynccontextmanager
async def demarrage(app):
    """Au démarrage : lit les données une seule fois et prépare les réponses qui ne changent pas.

    Les requêtes lisent ensuite app.state : les fichiers ne sont jamais relus. Si prix_communes.csv
    manque, le serveur refuse de démarrer avec un message clair, plutôt que d'échouer à la première
    requête. Si modeles.joblib manque, il démarre quand même et répond avec les médianes seules
    (méthode "mediane") : le code peut être mis en ligne avant le fichier du modèle.
    """
    dossier = Path(os.environ.get("DOSSIER_DONNEES", DOSSIER_VILLES))
    prix = charger_prix_communes(dossier)
    modeles = charger_modeles(dossier)
    app.state.prix = prix
    app.state.modeles = modeles
    app.state.communes = noms_communes(prix)
    app.state.info = zone_couverte(prix)
    if modeles is not None:
        # Ce que le site affiche dans « Sous le capot » : de vraies mesures, lues avec le modèle.
        app.state.info["modele"] = {
            "methodes": ["adresse", "commune", "mediane"],
            "entrainement": list(modeles["annees"]),
            # Surfaces acceptées par type de bien, pour que le site les vérifie avant d'appeler.
            "surfaces": {type_local: list(bornes) for type_local, bornes in modeles.get("surfaces", {}).items()},
            **modeles["metriques"].get("resume", {}),
        }
    yield


app = FastAPI(
    title="Estimateur immobilier",
    description="Fourchette de prix d'un bien à partir des ventes réelles (DVF).",
    lifespan=demarrage,
    docs_url="/docs" if os.environ.get("ACTIVER_DOCS") else None,
    redoc_url="/redoc" if os.environ.get("ACTIVER_DOCS") else None,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def trop_de_requetes(request: Request, erreur: RateLimitExceeded):
    """Répond 429 au format des autres erreurs : {"detail": "message"}, avec le temps d'attente réel."""
    attente = 60  # valeur de secours si le calcul ci-dessous échoue : c'est la durée de la fenêtre
    try:
        limite, cles = request.state.view_rate_limit
        fin_de_fenetre, _ = limiter.limiter.get_window_stats(limite, *cles)
        attente = max(1, math.ceil(fin_de_fenetre - time.time()))
    except Exception:
        pass
    return JSONResponse(
        status_code=429,
        content={"detail": f"Trop de requêtes : réessayez dans {attente} s."},
        headers={"Retry-After": str(attente)},
    )


@app.exception_handler(RequestValidationError)
def parametre_invalide(request: Request, erreur: RequestValidationError):
    """Répond 422 au même format que les autres erreurs : une phrase en français dans "detail".

    FastAPI renverrait sinon une liste d'objets en anglais, différente des messages de l'estimation.
    """
    messages = []
    for probleme in erreur.errors():
        nom = ".".join(str(morceau) for morceau in probleme["loc"] if morceau != "query")
        if probleme["type"] == "missing":
            messages.append(f"Paramètre obligatoire manquant : {nom}.")
        elif "parsing" in probleme["type"] or probleme["type"] in ("float_type", "int_type"):
            messages.append(f"Le paramètre {nom} doit être un nombre.")
        else:
            messages.append(f"Paramètre invalide : {nom}.")
    return JSONResponse(status_code=422, content={"detail": " ".join(messages)})


def refuser_parametres_repetes(request: Request):
    """Refuse (422) un paramètre donné plusieurs fois (commune=Lille&commune=Lyon) : le sens serait ambigu."""
    noms = [nom for nom, _ in request.query_params.multi_items()]
    repetes = sorted({nom for nom in noms if noms.count(nom) > 1})
    if repetes:
        raise HTTPException(status_code=422, detail=f"Paramètre répété : {', '.join(repetes)}.")


# L'ordre compte : le dernier middleware ajouté est le premier à voir la requête. CORS passe donc
# en dernier, pour que même une réponse 429 porte ses en-têtes CORS (sinon le navigateur la
# présenterait au site comme une panne réseau, pas comme une limite atteinte).
app.add_middleware(SlowAPIMiddleware)

# Seul le site (et son serveur de développement) peut appeler l'API depuis un navigateur.
# Pas de "*", et l'API ne fait que lire : seule la méthode GET est ouverte.
# expose_headers : un navigateur ne montre au JavaScript que quelques en-têtes de réponse
# courants. Retry-After (la durée d'attente après un 429) doit être listé pour que le site
# puisse le lire.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origines_autorisees(),
    allow_methods=["GET"],
    expose_headers=["Retry-After"],
)


# HEAD en plus de GET : la plupart des outils de surveillance interrogent ainsi.
@app.api_route("/health", methods=["GET", "HEAD"])
@limiter.exempt  # sans limite : le contrôle de santé de Docker l'appelle toutes les 30 secondes
def health():
    """Vérifie que le service tourne."""
    return {"status": "ok"}


@app.api_route("/communes", methods=["GET", "HEAD"], dependencies=[Depends(exiger_cle)])
def communes(request: Request, response: Response) -> list[str]:
    """Liste les communes connues, pour l'autocomplétion du formulaire."""
    response.headers["Cache-Control"] = CACHE_STATIQUE
    return request.app.state.communes


@app.api_route("/info", methods=["GET", "HEAD"], dependencies=[Depends(exiger_cle)])
def info(request: Request, response: Response) -> dict:
    """Indique la zone couverte : départements, villes, années des ventes, nombre de communes et mesures du modèle."""
    response.headers["Cache-Control"] = CACHE_STATIQUE
    return request.app.state.info


# def et non async def : estimer() est un calcul bloquant, FastAPI l'exécute alors à part
# pour ne pas figer le serveur pendant ce temps.
@app.get(
    "/estimation",
    dependencies=[Depends(exiger_cle), Depends(refuser_parametres_repetes)],
    response_model=Estimation,
    responses=REPONSES_ERREUR,
)
@limiter.limit(LIMITE_ESTIMATION)
def estimation(
    request: Request,
    commune: Annotated[str, Query(description="Nom de la commune ou de l'arrondissement, par exemple Lyon ou Lyon 3e Arrondissement.")],
    type_local: Annotated[str, Query(description="Type de bien : Maison ou Appartement.")],
    surface: Annotated[float, Query(description="Surface habitable en m², entre 9 et 1000, et dans les bornes de son type de bien données par /info (modele.surfaces).")],
    latitude: Annotated[float | None, Query(description="Latitude de l'adresse du bien, avec longitude : estimation bien plus précise.")] = None,
    longitude: Annotated[float | None, Query(description="Longitude de l'adresse du bien, avec latitude.")] = None,
):
    """Estime la fourchette de prix d'un bien.

    Le champ methode de la réponse dit comment elle a été faite : adresse (position fournie), commune
    (modèle de la commune) ou mediane (statistiques de la commune). Le champ repli nomme la ville dont
    les statistiques remplacent celles d'une commune qui manque de ventes de ce type de bien.
    """
    try:
        return estimer_prix(request.app.state.prix, request.app.state.modeles, commune, type_local, surface, latitude, longitude)
    except BienIntrouvable as erreur:
        raise HTTPException(status_code=404, detail=str(erreur)) from erreur
    except ParametreInvalide as erreur:
        raise HTTPException(status_code=422, detail=str(erreur)) from erreur
