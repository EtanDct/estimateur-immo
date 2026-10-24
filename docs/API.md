# L'API : routes, clé, limites, Docker et mise en ligne

Complète la section « L'API » du [README](../README.md). Le détail du code est dans
[REFERENCE.md](REFERENCE.md).


`estimateur/api.py` expose les fonctions de `modele.py` et `estimation.py` en HTTP, pour le site. Elle ne contient
aucune logique métier : elle traduit les requêtes en appels et les résultats en réponses JSON.
`prix_communes.csv` et `modeles.joblib` sont lus **une seule fois**, au démarrage. Si
`prix_communes.csv` manque, le serveur refuse de démarrer avec un message clair ; si
`modeles.joblib` manque, il démarre et répond avec les médianes seules.

```powershell
python -m uvicorn estimateur.api:app --reload      # http://127.0.0.1:8000
$env:ACTIVER_DOCS = "1"                            # facultatif : sert aussi /docs et /redoc
```

Les pages `/docs` et `/redoc` chargent leurs scripts depuis un CDN public : elles sont désactivées
par défaut, et activées seulement si la variable `ACTIVER_DOCS` est définie. Le schéma OpenAPI
(`/openapi.json`) reste disponible : réponses 200, 401, 404, 422 et 429, paramètres décrits.

| Route | Réponse |
|---|---|
| `GET /health` (et `HEAD`) | `{"status": "ok"}` : vérifie que le service tourne |
| `GET /communes` | la liste des noms de communes connues (autocomplétion) |
| `GET /info` | la zone couverte, déduite des données : départements, villes, années, nombre de communes, et les mesures du modèle (erreur médiane de chaque méthode, mesurée sur 2025) |
| `GET /estimation?commune=Lyon&type_local=Appartement&surface=65` | le dictionnaire de `estimer_prix()`, avec les champs `methode` et `repli` ; montants en euros entiers |
| `GET /estimation?...&latitude=45.76&longitude=4.83` | idem, avec l'adresse du bien (méthode `adresse`) |

Erreurs de `/estimation`, au format `{"detail": "message"}` : **404** si le bien est introuvable
(commune inconnue, aucune vente de ce type, moins de 10 ventes), **422** si un paramètre est
invalide (surface, type de bien, commune ambiguë, latitude sans longitude, adresse hors de la
commune), **429** si la limite de requêtes est atteinte. Un paramètre manquant, non numérique ou
répété donne aussi un 422, avec le même format : une phrase en français dans `detail`.

Les réponses de `/communes` et `/info` portent `Cache-Control: public, max-age=3600` : ces données ne
changent qu'à chaque nouvelle version des fichiers. Le serveur n'annonce ni sa version (`Server`),
et Caddy ajoute `Strict-Transport-Security` et `X-Content-Type-Options: nosniff`.

Le **CORS** limite les appels depuis un navigateur aux sites listés dans la variable
d'environnement `ORIGINES_AUTORISEES` (séparés par des virgules). Par défaut :
`https://www.tatane.me`, `https://tatane.me` et `http://localhost:4321`. Ce n'est **pas** une
protection d'accès : `curl` ou un script ignorent le CORS, qui n'empêche que l'usage de l'API par
un autre site, depuis le navigateur de ses visiteurs.

## Clé d'API (facultative) : seul le serveur du site appelle l'API

**La clé est facultative** : tant que `CLES_API` n'est pas définie sur le serveur, l'API répond à tout le monde. Pour vérifier qu'elle est active, une requête sans clé doit recevoir un 401 : `curl -i "https://api.tatane.me/estimation?commune=Lyon&type_local=Appartement&surface=65"`.

Si la variable d'environnement `CLES_API` est définie (une ou plusieurs clés, séparées par des
virgules), toutes les routes sauf `/health` exigent l'en-tête `X-API-Key` : sans clé valide, l'API
répond **401** `{"detail": "Clé d'API manquante ou invalide."}`. Sans cette variable, l'API est
ouverte (développement local). La comparaison des clés se fait en temps constant, et plusieurs clés
peuvent coexister pour en changer sans interruption.

Une clé n'a de sens que si celui qui l'envoie est un serveur : écrite dans le code d'une page web,
elle serait lisible par tous les visiteurs. Le navigateur n'appelle donc **pas** l'API directement :

```
 navigateur ──POST──► tatane.me/api/estimation ──GET + X-API-Key + X-Visiteur-IP──► api.tatane.me
 (aucun secret)        (route serveur du site, la clé est un secret Vercel)          (Caddy, puis l'API)
```

- Le **site** garde la clé dans une variable d'environnement serveur, vérifie les paramètres reçus et
  les transmet. Il envoie aussi l'adresse IP de son visiteur dans `X-Visiteur-IP`.
- L'**API** ne croit cet en-tête que si la requête porte une clé valide, et l'utilise pour la limite
  de requêtes : sans cela, tous les visiteurs auraient l'adresse de Vercel et partageraient une seule
  limite. Une requête sans clé valide ne peut pas échapper à la limite en inventant cet en-tête.
- Le **CORS** n'est plus utile quand plus aucun navigateur n'appelle l'API : `ORIGINES_AUTORISEES`
  peut alors être vide.
- Ce que la clé ne protège pas : la route du site est publique, comme le site. L'abus se déplace
  vers elle, d'où une limite de requêtes à y mettre aussi. L'API, elle, n'est plus joignable
  directement.
- Sur le serveur, les clés sont dans un fichier `.env` à côté de `docker-compose.yml` (modèle :
  `.env.example`, jamais versionné, droits `600`). Générer une clé :
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Limite de requêtes

Pour éviter qu'un visiteur ne sature le serveur, chaque adresse IP est limitée (bibliothèque
`slowapi`) : **30 requêtes par minute** sur `/estimation`, **60 par minute** sur `/communes` et
`/info` (un compteur par route et par visiteur). `/health` n'est pas limitée : le contrôle de
santé de Docker l'appelle toutes les 30 secondes. Au-delà, l'API répond **429** avec
`{"detail": "Trop de requêtes : réessayez dans N s."}` et l'en-tête `Retry-After`, qui donne le
temps d'attente réel jusqu'à la fin de la fenêtre. La
réponse 429 porte aussi les en-têtes CORS, pour que le site puisse l'afficher, et déclare
`Retry-After` dans `Access-Control-Expose-Headers` : sans cela, le navigateur cache cet en-tête au
JavaScript du site.

- Les seuils se règlent avec les variables d'environnement `LIMITE_ESTIMATION` et `LIMITE_DEFAUT`
  (par exemple `30/minute`). Les compteurs sont en mémoire : ils repartent de zéro au redémarrage.
- Derrière Caddy, l'adresse du visiteur est lue dans l'en-tête `X-Forwarded-For` (options
  `--proxy-headers` et `--forwarded-allow-ips` du `Dockerfile`). Sans cela, tous les visiteurs
  partageraient l'adresse de Caddy, donc une seule limite. Falsifier cet en-tête ne contourne rien :
  Caddy le remplace par l'adresse réelle du client, et l'API n'est joignable que par Caddy.

## Dans Docker

L'image contient le paquet `estimateur/` (le code) et les bibliothèques de
`requirements-api.txt` (pandas, scikit-learn, FastAPI, uvicorn : environ 480 Mo). Elle ne contient
**pas** les données : `prix_communes.csv` et `modeles.joblib` sont montés au lancement, depuis le
dossier du serveur où ils ont été déposés. Le serveur tourne avec un utilisateur sans droits
(`appuser`), et un `HEALTHCHECK` interroge `/health`. Les requêtes ne sont **pas journalisées**
(`--no-access-log`) : elles contiennent la position des biens estimés, une donnée personnelle que
rien ne justifie de conserver.

```powershell
docker build -t estimateur-immo-api .
docker run -d --name estimateur-api -p 127.0.0.1:8000:8000 -v "${PWD}/data/villes:/app/data:ro" estimateur-immo-api
```

- `-v ...:/app/data:ro` monte le dossier des données en **lecture seule**. Sans lui, le conteneur
  refuse de démarrer et le dit.
- `-p 127.0.0.1:8000:8000` ne rend l'API accessible que depuis la machine elle-même. Sur un
  serveur, c'est le reverse proxy (Caddy) qui la publie en HTTPS : le port 8000 n'est jamais
  ouvert sur Internet.
- **En production**, `docker compose up -d --build` lance l'API et Caddy ensemble. Caddy est le
  seul conteneur qui publie des ports (80 et 443) : il obtient et renouvelle le certificat HTTPS
  de `api.tatane.me` et transmet les requêtes à l'API, qui n'est publiée nulle part. Les données
  sont lues dans `./data`, à côté de `docker-compose.yml`.
- `requirements-api.txt` est une liste minimale, épinglée. Après un changement de version dans
  `requirements.txt`, la régénérer dans un environnement vierge qui ne contient que `fastapi`,
  `uvicorn`, `slowapi`, `scikit-learn`, `pandas` et `numpy`.

## Mise en ligne

Le serveur est un VPS Linux qui fait tourner `docker compose`. Le dépôt y est cloné ; le fichier `.env`
et le dossier `data/` sont à côté de `docker-compose.yml`. Les commandes ci-dessous se lancent depuis ce
dossier.

- **Mettre à jour le code :** `git pull`, puis `docker compose up -d --build`.
- **Activer ou changer la clé d'API :** écrire `CLES_API=<clé>` dans `.env`, puis `docker compose up -d`
  (Compose recrée le conteneur avec la nouvelle variable). Pour une rotation sans interruption :
  `CLES_API=<nouvelle>,<ancienne>`, mettre la nouvelle dans le site, puis retirer l'ancienne. Ne rien
  écrire du secret dans le dépôt, les journaux ou une capture d'écran.
- **Mettre à jour les données ou le modèle :** copier `prix_communes.csv` et `modeles.joblib` dans `data/`
  avec `scp`, puis `docker compose restart api` (l'API ne lit les fichiers qu'au démarrage). Le fichier
  `modeles.joblib` est un fichier pickle : ne jamais charger un fichier dont on n'est pas l'auteur.
  `/info` indique quel modèle tourne : `modele.entraine_le` et `modele.commit`.

## Surveillance

Les requêtes ne sont pas journalisées (voir plus haut) : personne n'est prévenu si le serveur tombe. Un
moniteur de disponibilité externe, gratuit, peut interroger `GET /health` (ou `HEAD`) : cette route n'est
ni limitée ni protégée par la clé, et ne renvoie que `{"status": "ok"}`.
