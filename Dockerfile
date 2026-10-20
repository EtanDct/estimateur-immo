# Image de l'API. Elle contient le code (api.py, immo.py) mais PAS les données :
# data/prix_communes.csv est monté depuis le serveur au lancement (voir le README).
FROM python:3.15-slim

# Pas de fichiers .pyc, et les messages s'affichent tout de suite dans les logs du conteneur.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Les dépendances d'abord : cette couche n'est reconstruite que si requirements-api.txt change.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY immo.py api.py ./

# Un utilisateur sans droits particuliers : le serveur ne tourne pas en root.
RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8000

# python -c plutôt que curl : l'image slim n'a pas curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

# 0.0.0.0 : le serveur écoute sur toutes les interfaces DU CONTENEUR. Ce qui est visible
# depuis l'extérieur se décide au lancement avec -p (voir le README).
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
