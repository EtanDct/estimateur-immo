"""API HTTP de l'estimateur : expose les fonctions de immo.py au site.

Ce module ne contient aucune logique métier : il reçoit les requêtes, appelle immo.py
et traduit les résultats et les erreurs en réponses HTTP.

À lancer depuis la racine du projet : python -m uvicorn api:app --reload
Documentation interactive : http://127.0.0.1:8000/docs

Variables d'environnement (facultatives) :
    ORIGINES_AUTORISEES : sites autorisés à appeler l'API depuis un navigateur (CORS),
    séparés par des virgules. Par défaut : le site et son serveur de développement local.
    LIMITE_ESTIMATION, LIMITE_DEFAUT : nombre de requêtes autorisées par visiteur (adresse IP),
    au format "30/minute". Au-delà, l'API répond 429.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from immo import BienIntrouvable, ParametreInvalide, charger_prix_communes, estimer, noms_communes, zone_couverte

ORIGINES_PAR_DEFAUT = "https://www.tatane.me,https://tatane.me,http://localhost:4321"

# Limites par visiteur. /estimation, la seule route qui calcule, est la plus restreinte.
LIMITE_ESTIMATION = os.environ.get("LIMITE_ESTIMATION", "30/minute")
LIMITE_DEFAUT = os.environ.get("LIMITE_DEFAUT", "60/minute")

# Le visiteur est identifié par son adresse IP. Derrière Caddy, uvicorn la lit dans l'en-tête
# X-Forwarded-For (voir le Dockerfile) : sans cela, tous les visiteurs auraient l'IP de Caddy
# et se partageraient une seule limite. Les compteurs sont en mémoire : ils repartent de zéro
# au redémarrage.
limiter = Limiter(key_func=get_remote_address, default_limits=[LIMITE_DEFAUT])


def _origines_autorisees():
    """Lit la liste des origines CORS dans la variable d'environnement, ou prend celles par défaut."""
    brut = os.environ.get("ORIGINES_AUTORISEES", ORIGINES_PAR_DEFAUT)
    return [origine.strip() for origine in brut.split(",") if origine.strip()]


@asynccontextmanager
async def demarrage(app):
    """Au démarrage : lit prix_communes.csv une seule fois et prépare les réponses qui ne changent pas.

    Les requêtes lisent ensuite app.state : le fichier n'est jamais relu. S'il manque,
    le serveur refuse de démarrer avec un message clair, plutôt que d'échouer à la première requête.
    """
    prix = charger_prix_communes()
    app.state.prix = prix
    app.state.communes = noms_communes(prix)
    app.state.info = zone_couverte(prix)
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
app.add_middleware(CORSMiddleware, allow_origins=_origines_autorisees(), allow_methods=["GET"])


@app.get("/health")
@limiter.exempt  # sans limite : le contrôle de santé de Docker l'appelle toutes les 30 secondes
def health():
    """Vérifie que le service tourne."""
    return {"status": "ok"}


@app.get("/communes")
def communes(request: Request):
    """Liste les communes connues, pour l'autocomplétion du formulaire."""
    return request.app.state.communes


@app.get("/info")
def info(request: Request):
    """Indique la zone couverte : départements, années des ventes et nombre de communes."""
    return request.app.state.info


# def et non async def : estimer() est un calcul bloquant, FastAPI l'exécute alors à part
# pour ne pas figer le serveur pendant ce temps.
@app.get("/estimation")
@limiter.limit(LIMITE_ESTIMATION)
def estimation(request: Request, commune: str, type_local: str, surface: float):
    """Estime la fourchette de prix d'un bien. Erreur 404 : bien introuvable. Erreur 422 : paramètre invalide."""
    try:
        return estimer(request.app.state.prix, commune, type_local, surface)
    except BienIntrouvable as erreur:
        raise HTTPException(status_code=404, detail=str(erreur)) from erreur
    except ParametreInvalide as erreur:
        raise HTTPException(status_code=422, detail=str(erreur)) from erreur
