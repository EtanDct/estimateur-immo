"""API HTTP de l'estimateur : expose les fonctions de immo.py au site.

Ce module ne contient aucune logique métier : il reçoit les requêtes, appelle immo.py
et traduit les résultats et les erreurs en réponses HTTP.

À lancer depuis la racine du projet : python -m uvicorn api:app --reload
Documentation interactive : http://127.0.0.1:8000/docs

Variables d'environnement (facultatives) :
    CLES_API : les clés d'API acceptées, séparées par des virgules. Si elle est définie, toutes les
    routes sauf /health exigent l'en-tête X-API-Key (erreur 401 sinon). Sans elle, l'API est ouverte.
    ORIGINES_AUTORISEES : sites autorisés à appeler l'API depuis un navigateur (CORS),
    séparés par des virgules. Par défaut : le site et son serveur de développement local.
    LIMITE_ESTIMATION, LIMITE_DEFAUT : nombre de requêtes autorisées par visiteur (adresse IP),
    au format "30/minute". Au-delà, l'API répond 429.
    DOSSIER_DONNEES : le dossier qui contient prix_communes.csv et modeles.joblib (par défaut data/villes/).
"""

import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from immo import DATA_DIR, BienIntrouvable, ParametreInvalide, charger_prix_communes, noms_communes, zone_couverte
from modele import charger_modeles, estimer_prix

ORIGINES_PAR_DEFAUT = "https://www.tatane.me,https://tatane.me,http://localhost:4321"

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


def exiger_cle(x_api_key: str | None = Header(default=None)):
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
    dossier = Path(os.environ.get("DOSSIER_DONNEES", DATA_DIR / "villes"))
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
            **modeles["metriques"].get("resume", {}),
        }
    yield


app = FastAPI(
    title="Estimateur immobilier",
    description="Fourchette de prix d'un bien à partir des ventes réelles (DVF).",
    lifespan=demarrage,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def trop_de_requetes(request: Request, erreur: RateLimitExceeded):
    """Répond 429 au format des autres erreurs : {"detail": "message"}."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Trop de requêtes : réessayez dans une minute."},
        headers={"Retry-After": "60"},
    )


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


@app.get("/health")
@limiter.exempt  # sans limite : le contrôle de santé de Docker l'appelle toutes les 30 secondes
def health():
    """Vérifie que le service tourne."""
    return {"status": "ok"}


@app.get("/communes", dependencies=[Depends(exiger_cle)])
def communes(request: Request):
    """Liste les communes connues, pour l'autocomplétion du formulaire."""
    return request.app.state.communes


@app.get("/info", dependencies=[Depends(exiger_cle)])
def info(request: Request):
    """Indique la zone couverte : départements, années des ventes et nombre de communes."""
    return request.app.state.info


# def et non async def : estimer() est un calcul bloquant, FastAPI l'exécute alors à part
# pour ne pas figer le serveur pendant ce temps.
@app.get("/estimation", dependencies=[Depends(exiger_cle)])
@limiter.limit(LIMITE_ESTIMATION)
def estimation(
    request: Request, commune: str, type_local: str, surface: float,
    latitude: float | None = None, longitude: float | None = None,
):
    """Estime la fourchette de prix d'un bien. Erreur 404 : bien introuvable. Erreur 422 : paramètre invalide.

    latitude et longitude (facultatives, à donner ensemble) sont la position de l'adresse du bien :
    l'estimation est alors bien plus précise. Le champ methode de la réponse dit comment elle a été faite.
    """
    try:
        return estimer_prix(request.app.state.prix, request.app.state.modeles, commune, type_local, surface, latitude, longitude)
    except BienIntrouvable as erreur:
        raise HTTPException(status_code=404, detail=str(erreur)) from erreur
    except ParametreInvalide as erreur:
        raise HTTPException(status_code=422, detail=str(erreur)) from erreur
