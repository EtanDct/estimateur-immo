# estimateur-immo

Estime le prix au m² d'un bien (maison ou appartement) dans une commune, à partir des ventes
réellement enregistrées dans les **Demandes de valeurs foncières géolocalisées (DVF)**
publiées sur data.gouv.fr.

État actuel, testé sur le département de la Marne (51), ventes de 2025 :

| Fonctionnalité | Statut |
|---|---|
| Chargement du fichier DVF d'un département | fait |
| Nettoyage des ventes (maisons et appartements, prix au m²) | fait |
| Statistiques de prix par commune et par type de bien | fait |
| Outil en ligne de commande `estimer.py` | à venir |
| Graphique des communes les plus chères | à venir |
| API (FastAPI) réutilisant les mêmes fonctions | à venir |

## Le trajet des données

Tout part d'un fichier brut et se transforme en trois temps. Chaque flèche est une fonction
de `immo.py`.

```
 data/51.csv                tableau brut               ventes propres              statistiques
 (fichier DVF)              27 342 lignes              5 905 lignes                529 lignes
      │                          │                          │                          │
      │   charger("51")          │   nettoyer(df)           │   prix_par_commune(df)   │
      └────────────────────────► └────────────────────────► └────────────────────────► └──► data/prix_communes.csv
```

Le fichier d'origine `data/51.csv` n'est **jamais modifié**. Les fonctions travaillent sur des
copies en mémoire, et seul `prix_communes.csv` est écrit.

## Qui fait quoi, qui appelle qui

```
estimateur-immo/
├── data/                 fichiers de données, ignorés par Git
│   ├── 51.csv            entrée : le fichier DVF du département (téléchargé à la main)
│   └── prix_communes.csv sortie : les statistiques par commune (créé par explorer.py)
│
├── immo.py               LA LOGIQUE : charger(), nettoyer(), prix_par_commune()
├── explorer.py           un script qui APPELLE immo.py pour explorer et produire le CSV
├── estimer.py            (à venir) un second script qui appellera immo.py
├── requirements.txt      les bibliothèques à installer
└── README.md
```

```
 explorer.py ──── importe et appelle ────►  immo.py ──── lit ────►  data/51.csv
      │
      └──────────────── écrit ───────────►  data/prix_communes.csv
```

- **`immo.py` fait le travail.** Il contient les fonctions, et seulement elles. Il ne lit pas
  d'arguments de terminal et n'affiche rien par défaut. Le numéro de département, le chemin
  des données et les seuils sont des paramètres, jamais écrits en dur dans les calculs.
- **`explorer.py` est un script de travail.** Il n'a aucune logique propre : il appelle les
  fonctions de `immo.py` et affiche des diagnostics pour comprendre les données.
- **`estimer.py` (à venir) sera une autre « façade »** sur les mêmes fonctions : elle lira les
  arguments du terminal, puis appellera `immo.py`. Plus tard, une API jouera le même rôle.

Cette séparation est le point central : la logique est écrite une seule fois, et plusieurs
interfaces (terminal, API) peuvent la réutiliser.

### Ce qui se passe quand on lance `python explorer.py`

1. `charger("51")` lit `data/51.csv` et renvoie le tableau brut `df`.
2. Le script affiche quelques diagnostics sur `df` (taille, types de biens, cases vides).
3. `nettoyer(df, verbose=True)` filtre les ventes et affiche ce que retire chaque étape. Il
   renvoie un nouveau tableau, `propre`.
4. `prix_par_commune(propre)` calcule les statistiques par commune et par type de bien.
5. Le résultat est écrit dans `data/prix_communes.csv`.

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

## Choix de méthode

- **Médiane plutôt que moyenne.** Une seule vente aberrante (un bien d'exception, une erreur
  de saisie) déplace beaucoup la moyenne et très peu la médiane.
- **Une fourchette plutôt qu'un prix unique.** Les deux quartiles encadrent la moitié centrale
  des ventes.
- **Le nombre de ventes compte.** Beaucoup de communes n'ont qu'une ou deux ventes : leur
  médiane n'est pas fiable. L'outil final refusera de donner une fourchette sous 10 ventes
  (77 couples commune/type de bien atteignent ce seuil sur le département 51).

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
python explorer.py
```

Depuis du code Python, les fonctions s'utilisent directement :

```python
from immo import charger, nettoyer, prix_par_commune

brut = charger("51")
propre = nettoyer(brut, verbose=True)
stats = prix_par_commune(propre)
```

## Suite prévue

`estimer.py`, un outil en ligne de commande qui répondra à une requête comme :

```powershell
python estimer.py --commune Reims --type Appartement --surface 65
```

en affichant une fourchette de prix fondée sur `data/prix_communes.csv`, avec une gestion des
erreurs (commune inconnue, casse du nom, moins de 10 ventes). Puis un graphique des communes les
plus chères, et une API qui réutilisera les fonctions de `immo.py`.
