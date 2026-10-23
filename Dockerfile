# Image de l'API. Elle contient le code (api.py, immo.py, modele.py) mais PAS les données :
# prix_communes.csv et modeles.joblib sont montés depuis le serveur au lancement (voir le README).
FROM python:3.15-slim

# Pas de fichiers .pyc, et les messages s'affichent tout de suite dans les logs du conteneur.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOSSIER_DONNEES=/app/data

WORKDIR /app

# Les dépendances d'abord : cette couche n'est reconstruite que si requirements-api.txt change.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY immo.py modele.py api.py ./

# Un utilisateur sans droits particuliers : le serveur ne tourne pas en root.
RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8000

# python -c plutôt que curl : l'image slim n'a pas curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

# 0.0.0.0 : le serveur écoute sur toutes les interfaces DU CONTENEUR. Ce qui est visible
# depuis l'extérieur se décide au lancement avec -p (voir le README).
# --proxy-headers et --forwarded-allow-ips "*" : l'adresse du visiteur est lue dans l'en-tête
# X-Forwarded-For que Caddy écrit, pour que la limite de requêtes s'applique à chaque visiteur
# et non à Caddy. Sans danger ici : seul Caddy peut joindre ce conteneur (aucun port publié),
# et il remplace toujours cet en-tête par l'adresse réelle du client.
# --no-access-log : les requêtes ne sont pas journalisées. Elles contiennent la position du bien
# estimé (latitude, longitude), une donnée personnelle qu'il n'y a aucune raison de conserver.
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
