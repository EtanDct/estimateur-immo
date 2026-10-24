# estimateur-immo

[![CI](https://github.com/EtanDct/estimateur-immo/actions/workflows/ci.yml/badge.svg)](https://github.com/EtanDct/estimateur-immo/actions/workflows/ci.yml)

Estime une fourchette de prix pour un bien (maison ou appartement) dans l'une des dix plus grandes
villes de France, à partir des ventes réellement enregistrées dans les **Demandes de valeurs
foncières géolocalisées (DVF)** publiées sur data.gouv.fr. Les estimations viennent d'un modèle
de machine learning (scikit-learn) dont l'erreur est mesurée sur des ventes qu'il n'a jamais vues,
et comparée à une simple médiane par commune.

```powershell
python -m estimateur estimer --commune "Lyon 3e Arrondissement" --type Appartement --surface 65 --latitude 45.7578 --longitude 4.8520
```

```
Lyon 3e Arrondissement - Appartement, 65 m²
Fourchette estimée : 258 000 € à 319 000 €
Prix médian : 291 000 € (4 478 €/m²)
Méthode : modèle tenant compte de l'adresse. Statistiques de la commune : 2519 ventes de 2024 à 2025.
```

Une API HTTP (FastAPI) expose les mêmes fonctions : `https://api.tatane.me`.

Pour aller plus loin : [la référence du code](docs/REFERENCE.md) et [l'API : clé, limites, mise en ligne](docs/API.md).

## Ce que le modèle apporte

Entraînement sur les ventes de 2021 à 2024, test sur les **83 310 ventes de 2025** : le modèle ne
voit jamais le prix des ventes qu'il estime. L'erreur est celle du prix au m² ; la fourchette est
l'intervalle entre le 25e et le 75e centile, qui doit contenir 50 % des ventes réelles.

| Méthode | Erreur médiane | Erreur moyenne (€/m²) | Largeur de la fourchette | Part des ventes dans la fourchette |
|---|---:|---:|---:|---:|
| Médiane de la commune, toutes les années | 18,2 % | 1 359 | 36,5 % | 49,8 % |
| Médiane de la commune, dernière année (référence) | 17,4 % | 1 313 | 37,5 % | 50,9 % |
| Modèle « commune » : commune, type, surface, année | 16,5 % | 1 261 | 34,3 % | 50,4 % |
| Modèle « commune » + pièces et terrain | 16,2 % | 1 245 | 33,2 % | 50,4 % |
| **Modèle « adresse » : type, surface, année, position** | **13,9 %** | **1 129** | **28,3 %** | **50,1 %** |
| Modèle complet (plafond) | 13,7 % | 1 118 | 27,7 % | 49,9 % |

Ce que ces mesures montrent :

- **La position du bien est ce qui compte.** Avec l'adresse, l'erreur médiane passe de 17,4 % à
  13,9 % par rapport à la meilleure référence, et la fourchette se resserre de 25 % à couverture
  égale. Le nombre de pièces et la surface du terrain n'apportent presque rien : le formulaire ne
  les demande donc pas.
- **Les prix récents comptent.** Une médiane sur la dernière année estime mieux 2025 qu'une médiane
  sur quatre ans, et l'année est une variable du modèle.
- **Le gain varie selon la ville.** Avec l'adresse, l'erreur médiane de Toulouse passe de 22,2 % à
  13,3 % et celle de Lille de 19,8 % à 14,1 % ; celle de Paris, déjà régulière, de 13,7 % à 12,3 %.
- **Les fourchettes sont calibrées** : dans chaque méthode, environ la moitié des ventes réelles
  tombent dans l'intervalle annoncé.

![Prix au m² dans les 10 grandes villes](docs/villes_les_plus_cheres.png)

## Le trajet des données

```
 data/villes/75 2021.csv … 75 2025.csv     (un fichier DVF par département et par année,
 data/villes/13 2021.csv … 13 2025.csv      téléchargés par la commande construire : 10 départements)
              │
              │  construire   telecharger → charger → nettoyer → regrouper_communes → prix_par_commune
              ▼
 data/villes/ventes_propres.csv   (432 579 ventes, une ligne par vente)     data/villes/prix_communes.csv   (statistiques par commune)
              │                                                                          │
              │  evaluer    (mesure les modèles, écrit evaluation.json)                  │
              │  modeliser  (entraîne les modèles finaux)                                │
              ▼                                                                          │
 data/villes/modeles.joblib ───────────────────────────────────────────────┐            │
                                                                            ▼            ▼
                                                   estimer (terminal) · api (HTTP) · graphique
```

Les fichiers d'origine ne sont **jamais modifiés** : les fonctions travaillent sur des copies en
mémoire. `data/` est ignoré par Git.

## Installation et utilisation

Prérequis : Python 3.12 ou plus. Commandes pour PowerShell, depuis la racine du projet :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m estimateur construire
python -m estimateur evaluer
python -m estimateur modeliser
python -m estimateur estimer --commune Lyon --type Appartement --surface 65
```

Facultatif : `python -m pip install -e .` installe le paquet en mode développement et ajoute la
commande `estimateur` (équivalente à `python -m estimateur`).

Depuis du code Python, les fonctions s'utilisent directement :

```python
from estimateur.config import DOSSIER_VILLES
from estimateur.donnees import charger_prix_communes
from estimateur.modele import charger_modeles, estimer_prix

print(estimer_prix(charger_prix_communes(DOSSIER_VILLES), charger_modeles(DOSSIER_VILLES), "Lyon", "Appartement", 65))
```

## Les commandes

Toutes se lancent depuis la racine du projet avec `python -m estimateur <commande>`. Après
`python -m pip install -e .`, la commande `estimateur <commande>` fait la même chose.

```powershell
python -m estimateur                    # liste les commandes
python -m estimateur construire         # télécharge, nettoie, agrège : ventes_propres.csv et prix_communes.csv
python -m estimateur evaluer            # compare les modèles à la référence sur 2025 : evaluation.json
python -m estimateur modeliser          # entraîne les modèles finaux : modeles.joblib
python -m estimateur estimer --commune Lyon --type Appartement --surface 65
python -m estimateur estimer -h         # les options de chaque commande
python -m estimateur graphique          # docs/villes_les_plus_cheres.png
python -m estimateur explorer 75 --annees 2025
```

`estimer` accepte aussi `--latitude` et `--longitude`. En cas d'erreur, le message est affiché sur la
sortie d'erreur et le code de retour vaut 1, sans trace d'erreur Python.

`explorer` sert à examiner les fichiers DVF d'un département (taille, colonnes, types de biens, cases
vides) et à voir ce que retire chaque étape du nettoyage. Il n'écrit aucun fichier.

## Les données DVF

- Source : DVF géolocalisées sur data.gouv.fr, un fichier CSV par département et par année.
  `telecharger()` les récupère (environ 100 Mo compressés pour dix départements et cinq ans).
- Les dix villes : Paris, Marseille, Lyon, Toulouse, Nice, Nantes, Montpellier, Bordeaux, Lille et
  Rennes. **Strasbourg n'en fait pas partie** : l'Alsace-Moselle (57, 67, 68) n'est pas couverte par
  DVF. Rennes, onzième ville de France, la remplace.
- **Paris, Lyon et Marseille sont découpées en arrondissements** dans DVF (`Paris 10e Arrondissement`,
  code 75110). Le projet garde les arrondissements et ajoute la ville entière (`Paris`).
- Une ligne du fichier n'est **pas** une vente : c'est une parcelle ou un lot d'une vente. Une même
  vente peut occuper plusieurs lignes qui partagent le même `id_mutation`, et `valeur_fonciere`
  répète le prix total sur chacune.
- Colonnes utilisées : `id_mutation`, `date_mutation`, `nature_mutation`, `valeur_fonciere`,
  `code_commune`, `nom_commune`, `type_local`, `surface_reelle_bati`, `nombre_pieces_principales`,
  `surface_terrain`, `latitude`, `longitude`.

## Licence et source des données

**Code : licence MIT** (fichier [LICENSE](LICENSE)).

**Données : DVF géolocalisées**, dérivées des « Demandes de valeurs foncières » de la DGFiP et diffusées sur
[data.gouv.fr](https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees) sous
[Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence) (Etalab). Source : DGFiP,
jeu de données mis à jour le 21 octobre 2026, téléchargé le 23 octobre 2026. Les statistiques et les
modèles en sont dérivés ; les fichiers de ventes ne sont pas dans le dépôt. Ce projet n'est ni officiel
ni approuvé par la DGFiP.

## L'API

`estimateur/api.py` expose les fonctions de `modele.py` et `estimation.py` en HTTP, pour le site. Elle ne
contient aucune logique métier : elle traduit les requêtes en appels et les résultats en réponses JSON.

```powershell
python -m uvicorn estimateur.api:app --reload      # http://127.0.0.1:8000
```

| Route | Réponse |
|---|---|
| `GET /health` (et `HEAD`) | `{"status": "ok"}` : vérifie que le service tourne |
| `GET /communes` | la liste des noms de communes connues (autocomplétion) |
| `GET /info` | la zone couverte, déduite des données : départements, villes, années, nombre de communes, et le modèle : mesures (erreur médiane de chaque méthode, mesurée sur 2025), bornes de surface, date d'entraînement, commit et nombre de ventes |
| `GET /estimation?commune=Lyon&type_local=Appartement&surface=65` | le dictionnaire de `estimer_prix()`, avec les champs `methode` et `repli` ; montants en euros entiers |
| `GET /estimation?...&latitude=45.76&longitude=4.83` | idem, avec l'adresse du bien (méthode `adresse`) |

Erreurs de `/estimation`, au format `{"detail": "message"}` : **404** si le bien est introuvable
(commune inconnue, aucune vente de ce type, moins de 10 ventes), **422** si un paramètre est
invalide (surface, type de bien, commune ambiguë, latitude sans longitude, adresse hors de la
commune), **429** si la limite de requêtes est atteinte. Un paramètre manquant, non numérique ou
répété donne aussi un 422, avec le même format : une phrase en français dans `detail`.

- **Clé d'API facultative** (`CLES_API`, en-tête `X-API-Key`) : le navigateur n'appelle pas l'API
  directement, c'est la route serveur du site qui l'appelle avec la clé. Tant que la variable n'est pas
  définie sur le serveur, l'API est ouverte.
- **Limite de requêtes** par visiteur : 30 par minute sur `/estimation`, 60 sur `/communes` et `/info`,
  réponse **429** avec `Retry-After` au-delà. Les requêtes ne sont pas journalisées : elles contiennent
  la position des biens.
- **Docker** : l'image contient le code, pas les données, et tourne sans droits particuliers.

Le détail (CORS, clé et architecture, limites, Docker, mise en ligne, surveillance) est dans
[docs/API.md](docs/API.md).

## Choix de méthode

- **Médiane plutôt que moyenne.** Une seule vente aberrante (un bien d'exception, une erreur
  de saisie) déplace beaucoup la moyenne et très peu la médiane.
- **Une fourchette plutôt qu'un prix unique.** Les deux quartiles encadrent la moitié centrale
  des ventes ; le modèle prédit les mêmes quantiles.
- **Le nombre de ventes compte.** Une médiane sur quelques ventes n'est pas fiable : l'outil refuse
  une estimation sous 10 ventes de la commune et du type de bien.
- **Des filtres relatifs plutôt que fixes** pour les valeurs aberrantes (étape 6 du nettoyage),
  car les prix varient d'un facteur 3 entre les villes.
- **Des statistiques sur les années récentes.** Les prix bougent : sur 2025, une médiane de 2024 seule
  se trompe moins (17,4 %) qu'une médiane de 2021 à 2024 (18,2 %). `prix_communes.csv` porte donc
  sur 2024 et 2025.
- **Une adresse optionnelle.** Le formulaire minimal (commune, type, surface) reste utilisable ; l'adresse
  est ce qui améliore le plus l'estimation, pas le nombre de pièces.

## Limites

L'estimation est un **ordre de grandeur issu de ventes passées**, pas une expertise. Elle ne tient
pas compte de l'état du bien, de l'étage, de la présence d'un balcon ou d'un parking, ni des
rénovations. Les biens vendus en VEFA, ceux dont la vente comprend plusieurs logements et ceux
dont les lignes ne permettent pas d'isoler un prix sont exclus : les estimations décrivent le
marché des logements « classiques ». Les maisons sont rares dans les grandes villes (par exemple
745 ventes à Paris en cinq ans) : leurs estimations sont moins précises. L'Alsace-Moselle n'est
pas couverte par DVF.

## Structure du dépôt

```
estimateur-immo/
├── estimateur/              le paquet Python : tout le code
│   ├── config.py            chemins et constantes partagés (seuils, types de biens, dossiers)
│   ├── donnees.py           LES DONNÉES : télécharger, charger, nettoyer, agréger
│   ├── estimation.py        L'ESTIMATION PAR MÉDIANE : vérifier une demande, trouver la commune, erreurs
│   ├── modele.py            LE MODÈLE : séparation par année, référence, entraînement, mesures, estimation
│   ├── villes.py            la liste des dix villes, avec leurs codes de commune
│   ├── api.py               l'API HTTP (FastAPI) : appelle estimation.py et modele.py pour le site
│   ├── cli.py               le point d'entrée en ligne de commande : python -m estimateur <commande>
│   └── commandes/           une commande par module
│       ├── construire.py    télécharge et prépare les données
│       ├── evaluer.py       compare les modèles à la référence sur 2025
│       ├── modeliser.py     entraîne et enregistre les modèles finaux
│       ├── estimer.py       estime le prix d'un bien
│       ├── graphique.py     trace le graphique
│       └── explorer.py      explore les fichiers DVF d'un département (diagnostics)
├── tests/                   les tests pytest, sur des ventes factices (voir « Tests et intégration continue »)
├── .github/workflows/       l'intégration continue : style, tests, image Docker
├── data/                    données, ignorées par Git (sous-dossier villes/ : celles du projet)
├── docs/                    la référence du code (REFERENCE.md), l'API (API.md) et le graphique
│
├── pyproject.toml           métadonnées du projet et réglages de pytest et ruff, commande installable `estimateur`
├── requirements.txt         toutes les bibliothèques du projet (développement)
├── requirements-api.txt     seulement celles dont l'API a besoin (utilisé par le Dockerfile)
├── requirements-dev.txt     l'API, plus pytest et ruff (utilisé par la CI)
├── Dockerfile               l'image Docker de l'API (code seul, sans les données)
├── .dockerignore            liste blanche des fichiers envoyés à Docker
├── docker-compose.yml       lance l'API et Caddy (HTTPS) ensemble
├── Caddyfile                configuration de Caddy : domaine et redirection vers l'API
├── .env.example             modèle du fichier .env du serveur (clés d'API)
├── LICENSE                  licence MIT
└── README.md
```

Les modules `donnees.py`, `estimation.py` et `modele.py` font le travail ; les commandes et l'API sont des
façades qui lisent leurs entrées, appellent ces fonctions et présentent le résultat. L'explication, avec le
graphe des appels, est dans [docs/REFERENCE.md](docs/REFERENCE.md).

## Tests et intégration continue

```powershell
python -m pip install -r requirements-dev.txt   # l'API, plus pytest et ruff
ruff check .                                    # style, imports, erreurs courantes
pytest                                          # environ 180 tests, une minute
```

Les tests n'ont besoin d'aucune vraie donnée (`data/` n'est pas dans Git) : `tests/conftest.py`
fabrique 800 ventes factices aux prix connus d'avance, avec les vrais codes de commune (Lille,
Lyon 1er et 3e, Paris 1er et 2e), et entraîne de vrais modèles dessus.

Ce que vérifie chaque fichier de test est décrit dans [docs/REFERENCE.md](docs/REFERENCE.md#les-tests).

L'intégration continue (`.github/workflows/ci.yml`) tourne à chaque envoi sur `main` et à chaque pull
request, avec deux tâches :

1. **Style et tests** : `ruff check .` puis `pytest`, sur Python 3.15 comme l'image Docker.
2. **Image Docker** : construit l'image, la lance sur un fichier de statistiques minimal, attend
   qu'elle soit saine, vérifie une estimation, l'absence d'en-tête `Server` et que la requête n'est
   pas écrite dans les journaux (elle contient la position du bien).

Dependabot (`.github/dependabot.yml`) vérifie chaque lundi les bibliothèques Python et les actions
GitHub, et ouvre une pull request quand une version est sortie : la CI la teste, rien n'est fusionné
sans accord. `scikit-learn` en est exclu : `modeles.joblib` doit être relu par la version qui l'a écrit,
donc on change de version en réentraînant le modèle puis en renvoyant le fichier sur le serveur.

## Suite prévue

Déploiement automatique après des tests réussis, puis une explication en langage clair de chaque
estimation (un LLM met en mots les chiffres du modèle, sans jamais les produire ni les modifier).
