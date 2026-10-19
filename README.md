# estimateur-immo

Estime une fourchette de prix pour un bien (maison ou appartement) dans une commune, à partir des
ventes réellement enregistrées dans les **Demandes de valeurs foncières géolocalisées (DVF)**
publiées sur data.gouv.fr.

```powershell
python estimer.py --commune Reims --type Appartement --surface 65
```

```
Reims - Appartement, 65 m²
Fourchette estimée : 135 000 € à 207 000 €
Prix médian : 172 000 € (2 643 €/m²)
Basé sur 1829 ventes.
```

État actuel, testé sur le département de la Marne (51), ventes de 2025 :

| Fonctionnalité | Statut |
|---|---|
| Chargement du fichier DVF d'un département | fait |
| Nettoyage des ventes (maisons et appartements, prix au m²) | fait |
| Statistiques de prix par commune et par type de bien | fait |
| Outil en ligne de commande `estimer.py` | fait |
| Graphique des communes les plus chères | fait |
| API (FastAPI) réutilisant les mêmes fonctions | à venir |

![Communes les plus chères du département 51](docs/communes_les_plus_cheres.png)

## Le trajet des données

Tout part d'un fichier brut et se transforme en trois temps. Chaque flèche est une fonction
de `immo.py`.

```
 data/51.csv                tableau brut               ventes propres              statistiques
 (fichier DVF)              27 342 lignes              5 905 lignes                529 lignes
      │                          │                          │                          │
      │   charger("51")          │   nettoyer(df)           │   prix_par_commune(df)   │
      └────────────────────────► └────────────────────────► └────────────────────────► └──► data/prix_communes.csv
                                                                                                    │
                                                         estimer(...)  et  classer_communes(...) ◄──┘
                                                         (estimation d'un bien)   (classement des communes)
```

Le fichier d'origine `data/51.csv` n'est **jamais modifié**. Les fonctions travaillent sur des
copies en mémoire. Seuls `data/prix_communes.csv` et l'image du graphique sont écrits.

## Qui fait quoi, qui appelle qui

```
estimateur-immo/
├── data/                 fichiers de données, ignorés par Git
│   ├── 51.csv            entrée : le fichier DVF du département (téléchargé à la main)
│   └── prix_communes.csv sortie : les statistiques par commune (créé par explorer.py)
├── docs/
│   └── communes_les_plus_cheres.png   le graphique (créé par graphique.py)
│
├── immo.py               LA LOGIQUE : toutes les fonctions
├── explorer.py           script : explore les données et produit prix_communes.csv
├── estimer.py            script : l'outil en ligne de commande
├── graphique.py          script : trace le graphique
├── requirements.txt      les bibliothèques à installer
└── README.md
```

```
 explorer.py ───┐                        ┌──► data/51.csv              (lecture)
 estimer.py  ───┼── importent immo.py ───┤
 graphique.py ──┘                        └──► data/prix_communes.csv   (lecture)

 écritures : explorer.py  → data/prix_communes.csv
             graphique.py → docs/communes_les_plus_cheres.png
```

- **`immo.py` fait le travail.** Il contient les fonctions, et seulement elles. Il ne lit pas
  d'arguments de terminal et n'affiche rien par défaut. Le numéro de département, le chemin
  des données et les seuils sont des paramètres, jamais écrits en dur dans les calculs.
- **Les trois scripts sont des « façades ».** Chacun lit ses entrées (arguments du terminal,
  constantes), appelle les fonctions de `immo.py` et présente le résultat. Ils n'ont aucune
  logique de calcul propre.
- **Pourquoi cette séparation :** la logique est écrite une seule fois. Une API pourra l'appeler
  comme le fait déjà le terminal. Les erreurs de `estimer()` sont des `ValueError` : le terminal
  les affiche, une API pourra les transformer en réponse HTTP 4xx.

### Ordre d'utilisation

1. `python explorer.py` lit `data/51.csv`, nettoie, agrège et écrit `data/prix_communes.csv`.
   Il affiche aussi des diagnostics sur les données (taille, types de biens, cases vides).
2. `python estimer.py ...` et `python graphique.py` lisent ensuite `data/prix_communes.csv`.

## Les fonctions de `immo.py`

### `charger(departement)`

Lit `data/<departement>.csv` et renvoie le tableau brut, sans rien filtrer. Les codes de
département, de commune et postal sont lus comme du **texte** : sinon `01` deviendrait `1`, et
`2A`/`2B` (Corse) poseraient problème.

### `nettoyer(df, prix_m2_min=300, prix_m2_max=10000, verbose=False)`

Garde uniquement les ventes exploitables pour estimer un prix au m² et ajoute la colonne
`prix_m2`. Résultat sur le département 51 :

| # | Filtre | Pourquoi | Lignes retirées | Restantes |
|---|---|---|---:|---:|
| | Fichier brut | | | 27 342 |
| 1 | `type_local` = Maison ou Appartement | Les terrains, dépendances et locaux professionnels n'ont pas de surface de logement | 19 508 | 7 834 |
| 2 | `nature_mutation` = Vente | Échanges, adjudications et ventes sur plan n'ont pas un prix comparable | 58 | 7 776 |
| 3 | Prix > 0 et surface > 0 | Un prix ou une surface vide ou nul ne permet pas de calcul | 5 | 7 771 |
| 4 | Une seule ligne par vente | Voir ci-dessous | 1 813 | 5 958 |
| 5 | Prix au m² entre 300 et 10 000 € | Écarte les ventes symboliques (1 €) et les erreurs de saisie (180 000 €/m²) | 53 | 5 905 |

**Pourquoi « une seule ligne par vente » ?** Dans le fichier DVF, une vente (`id_mutation`)
occupe une ligne par parcelle ou par lot, et la colonne `valeur_fonciere` y répète le prix
**total**. Pour une vente de deux logements, on ne peut pas savoir quelle part du prix revient à
chacun. On ne garde donc que les ventes qui n'ont qu'un seul logement.

Le comptage se fait **après** le filtre sur les maisons et appartements : une maison vendue
avec un garage ou un terrain reste une vente à un seul logement.

**Limite connue :** parmi les ventes à plusieurs lignes, environ la moitié ne contiennent en
réalité qu'un seul logement, répété sur plusieurs parcelles. Elles sont écartées avec les
autres. C'est prudent, et il reste assez de données, mais ce n'est pas parfait.

### `prix_par_commune(df)`

Reçoit les ventes propres et renvoie une ligne par **commune et par type de bien** (une
médiane mêlant maisons et appartements n'aurait pas de sens). Colonnes :

| Colonne | Contenu |
|---|---|
| `code_commune` | Code INSEE, identifiant unique de la commune |
| `nom_commune` | Nom, pour l'affichage |
| `type_local` | `Maison` ou `Appartement` |
| `mediane` | Médiane du prix au m² |
| `quartile_1`, `quartile_3` | 1er et 3e quartile : 25 % des ventes sont en dessous du premier, 25 % au-dessus du second |
| `nombre_ventes` | Nombre de ventes sur lesquelles reposent ces chiffres |

Sur le département 51 : 529 lignes (489 maisons, 40 appartements).

### `charger_prix_communes()`

Relit `data/prix_communes.csv`. Si le fichier n'existe pas, lève une `FileNotFoundError` qui
indique comment le générer.

### `estimer(prix, commune, type_local, surface, ventes_min=10)`

Cherche la commune et le type de bien dans le tableau des statistiques et renvoie un
dictionnaire : `prix_bas` (surface × 1er quartile), `prix_median`, `prix_haut` (surface × 3e
quartile), `prix_m2_median`, `nombre_ventes`, `commune`, `type_local`, `surface`.

Le nom de la commune est comparé sans tenir compte de la casse, des accents ni des tirets :
`epernay`, `ÉPERNAY` et `Épernay` désignent la même commune, comme `chalons en champagne` et
`Châlons-en-Champagne`.

Erreurs, toutes levées en `ValueError` avec un message lisible :

| Cas | Message (extrait) |
|---|---|
| Surface nulle ou négative | La surface doit être positive |
| Type de bien autre que Maison ou Appartement | Type de bien inconnu |
| Nom de commune absent du tableau | Commune introuvable |
| Commune sans vente de ce type de bien | Aucune vente exploitable de maison à ... |
| Moins de 10 ventes | Seulement N vente(s) ... : il en faut au moins 10 |
| Plusieurs communes de même nom | Plusieurs communes s'appellent ... (codes ...) |

### `classer_communes(prix, type_local, ventes_min=10)`

Classe les communes d'un type de bien de la plus chère à la moins chère (médiane du prix au
m²), en ne gardant que celles qui comptent assez de ventes. Utilisée par `graphique.py`.

## Les scripts

### `estimer.py`

```powershell
python estimer.py --commune Épernay --type Maison --surface 110
python estimer.py -h
```

Les trois arguments sont obligatoires. En cas d'erreur, le message est affiché sur la sortie
d'erreur et le code de retour vaut 1, sans trace d'erreur Python.

### `graphique.py`

Trace deux classements en barres horizontales, un pour les maisons (les 15 communes les plus
chères) et un pour les appartements, avec la médiane du prix au m² et le nombre de ventes. Seules
les communes d'au moins 10 ventes sont classées. L'image est écrite dans `docs/`.

## Choix de méthode

- **Médiane plutôt que moyenne.** Une seule vente aberrante (un bien d'exception, une erreur
  de saisie) déplace beaucoup la moyenne et très peu la médiane.
- **Une fourchette plutôt qu'un prix unique.** Les deux quartiles encadrent la moitié centrale
  des ventes.
- **Le nombre de ventes compte.** Beaucoup de communes n'ont qu'une ou deux ventes : leur
  médiane n'est pas fiable. L'outil refuse de donner une fourchette sous 10 ventes. Sur le
  département 51, 77 couples commune/type de bien atteignent ce seuil (69 pour les maisons, 8 pour
  les appartements).

## Limites

L'estimation est une **statistique descriptive** : la médiane et les quartiles des ventes passées
d'une commune, multipliés par la surface. Ce n'est pas un modèle prédictif. Elle ne tient pas compte
du nombre de pièces, de l'étage, de l'état du bien, du terrain, du quartier ni de l'évolution
récente des prix. Elle donne un ordre de grandeur, pas une évaluation.

## Les données

- Source : DVF géolocalisées, sur data.gouv.fr (un fichier CSV par département).
- Période du fichier utilisé : du 2 janvier au 31 décembre 2025.
- Une ligne du fichier n'est **pas** une vente : c'est une parcelle ou un lot d'une vente.
  Une même vente peut donc occuper plusieurs lignes qui partagent le même `id_mutation`.
- Colonnes utilisées : `id_mutation`, `nature_mutation`, `valeur_fonciere`, `code_commune`,
  `nom_commune`, `type_local`, `surface_reelle_bati`.
- Le dossier `data/` n'est pas versionné : les données sont volumineuses et se re-téléchargent.

## Installation et utilisation

Prérequis : Python 3.12 ou plus. Commandes pour PowerShell, depuis la racine du projet :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Placer ensuite le fichier DVF du département dans `data/<numéro>.csv` (par exemple
`data/51.csv`), puis :

```powershell
python explorer.py                 # produit data/prix_communes.csv
python estimer.py --commune Reims --type Appartement --surface 65
python graphique.py                # produit docs/communes_les_plus_cheres.png
```

Depuis du code Python, les fonctions s'utilisent directement :

```python
from immo import charger, nettoyer, prix_par_commune, estimer

propre = nettoyer(charger("51"), verbose=True)
stats = prix_par_commune(propre)
print(estimer(stats, "Reims", "Appartement", 65))
```

## Suite prévue

Une API (FastAPI) qui réutilisera les fonctions de `immo.py`, et la prise en charge de plusieurs
départements.
