# Référence du code

Ce document décrit le code en détail : les données, chaque fonction, le modèle, les tests. Le
[README](../README.md) donne la vue d'ensemble ; l'API, sa clé, ses limites et sa mise en ligne sont
dans [API.md](API.md).

## Qui appelle qui

```
 commandes/*  (terminal)  ─┐
 api.py       (HTTP)      ─┴──► modele.py ──► estimation.py ──► config.py
                                    │                ▲
                                    └──► donnees.py ─┘   villes.py
```

- **`donnees.py`, `estimation.py` et `modele.py` font le travail.** Ils contiennent les fonctions, et
  seulement elles. Ils ne lisent pas d'arguments de terminal et ne font ni `print`, ni `input`, ni
  `sys.exit` : ils reçoivent des paramètres et renvoient des valeurs ou lèvent des exceptions. Les
  départements, les années, les dossiers et les seuils sont des paramètres.
- **Les commandes et l'API sont des « façades ».** Chacune lit ses entrées (arguments du terminal,
  requête HTTP), appelle ces fonctions et présente le résultat. Elles n'ont aucune logique de calcul
  propre. Une commande est un module qui définit `ajouter_arguments(parser)` et `executer(args)` ;
  `cli.py` ne l'importe que si on la lance.
- **Pourquoi cette séparation :** la logique est écrite une seule fois, le terminal et l'API la
  partagent, et les erreurs sont des exceptions que chaque façade traduit à sa manière (un message
  dans le terminal, un code HTTP 404, 422 ou 429 pour l'API).
- **Pourquoi un paquet :** les modules s'importent avec des chemins stables (`from estimateur.modele
  import ...`), quel que soit le dossier d'où on lance Python. Les chemins viennent de `config.py` et
  ne dépendent jamais du dossier courant.

## Préparer les données (`donnees.py`)

### `telecharger(departement, annees=(2023, 2024, 2025), dossier=data/)`

Télécharge les fichiers DVF d'un département vers `<dossier>/<departement> <annee>.csv`. Un fichier
déjà présent n'est pas retéléchargé, et un téléchargement interrompu ne laisse jamais de fichier
tronqué (écriture sous un nom provisoire, puis renommage). Lève une `FileNotFoundError` si le
fichier n'existe pas sur data.gouv.fr.

### `charger(departement, annees=(2023, 2024, 2025), dossier=data/)`

Lit les fichiers `<dossier>/<departement> <annee>.csv` et les empile en un seul tableau brut,
sans rien filtrer. Une colonne `annee` indique de quel fichier vient chaque ligne. Les codes de
département, de commune et postal sont lus comme du **texte** : sinon `01` deviendrait `1`, et
`2A`/`2B` (Corse) poseraient problème.

### `nettoyer(df, prix_m2_min=300, prix_m2_max=10000, ecart_median=None)`

Garde les ventes d'un seul logement (maison ou appartement) au prix au m² plausible. Chaque étape
note dans le journal (`logging`, niveau INFO) combien de lignes elle retire :

1. **Maisons et appartements seulement** : on retire terrains, dépendances, locaux professionnels et
   lignes sans `type_local`.
2. **Ventes classiques** (`nature_mutation = "Vente"`) : on retire échanges, adjudications, ventes
   sur plan (VEFA) et ventes de terrain à bâtir, dont le prix n'est pas comparable.
3. **Prix et surface strictement positifs**.
4. **Une seule ligne de logement par vente** : avec deux logements dans la même vente, on ne saurait
   pas quel prix revient à quel logement. La règle s'applique après les étapes 1 à 3 : une maison
   vendue avec un garage ou un terrain reste une vente à un seul logement. Selon la ville, elle
   retire de l'ordre de 10 à 25 % des lignes restantes.
5. **Prix au m² entre `prix_m2_min` et `prix_m2_max`** : retire les ventes symboliques (1 €) et les
   erreurs de saisie.
6. **Facultatif, `ecart_median`** : retire aussi les ventes dont le prix au m² sort de l'intervalle
   [médiane / `ecart_median`, médiane × `ecart_median`] de leur commune et de leur type de bien.
   Des seuils fixes ne conviennent pas à des villes aux prix très différents : 10 000 €/m² est une
   valeur aberrante dans la Marne et un prix courant à Paris, où un plafond à 10 000 aurait retiré
   45 % des ventes. La commande `construire` utilise un plafond de garde-fou à 50 000 et un écart de 3.

Renvoie un nouveau tableau avec une colonne `prix_m2` en plus.

### `regrouper_communes(df, regroupements)`

Ajoute les ventes de plusieurs communes sous un seul nom : `Paris` en entier, à côté de ses vingt
arrondissements. Les ventes d'origine sont conservées.

### `prix_par_commune(df)`

Pour chaque commune et chaque type de bien : médiane, 1er et 3e quartile du prix au m², nombre de
ventes, première et dernière année. Les statistiques de la commande `construire` portent sur 2024 et 2025.

### `charger_prix_communes(dossier=data/)`

Relit `prix_communes.csv`. Si le fichier n'existe pas, lève une `FileNotFoundError` qui indique
comment le générer.

## Estimer par médiane (`estimation.py`)

### `chercher_ligne(...)` et `estimer(prix, commune, type_local, surface, ventes_min=10)`

`chercher_ligne` vérifie la demande et trouve la ligne de statistiques de la commune ;
`chercher_ligne_avec_repli` y ajoute un repli, et `estimer` en tire un dictionnaire : `prix_bas`
(surface × 1er quartile), `prix_median`, `prix_haut` (surface × 3e quartile, ces trois montants
arrondis à l'euro), `prix_m2_median`, `nombre_ventes`, `annee_min`, `annee_max`, `commune`,
`type_local`, `surface` et `repli`. C'est la méthode de repli du projet : médianes et quartiles, sans
modèle.

**Le repli sur la ville.** Une maison se vend rarement dans un arrondissement du centre de Paris :
16 des 110 combinaisons commune × type de bien ont moins de 10 ventes (des maisons dans 13
arrondissements de Paris, 3 de Lyon et Marseille 1er). Plutôt que de répondre « introuvable », on
prend alors les statistiques de la ville entière, et le champ `repli` nomme cette ville (`null`
sinon). Si la ville manque aussi de ventes, l'erreur reste.

Le nom de la commune est comparé sans tenir compte de la casse, des accents ni des tirets :
`epernay`, `ÉPERNAY` et `Épernay` désignent la même commune.

Erreurs, toutes des `ValueError` au message lisible. Deux sous-classes les distinguent :
`ParametreInvalide` (la requête est incorrecte) et `BienIntrouvable` (la requête est correcte, mais
les données ne permettent pas de répondre). L'API en tire le code HTTP.

| Cas | Exception | Code HTTP |
|---|---|---|
| Surface hors de 9 à 1 000 m² (ou `nan`, `inf`) | `ParametreInvalide` | 422 |
| Type de bien autre que Maison ou Appartement | `ParametreInvalide` | 422 |
| Nom de commune ou de type trop long (plus de 100 caractères) ou avec des caractères de contrôle | `ParametreInvalide` | 422 |
| Plusieurs communes de même nom | `ParametreInvalide` | 422 |
| Nom de commune absent du tableau | `BienIntrouvable` | 404 |
| Commune sans vente de ce type de bien | `BienIntrouvable` | 404 |
| Moins de 10 ventes (et la ville aussi, s'il y a une ville) | `BienIntrouvable` | 404 |

Les messages d'erreur répètent le texte reçu, tronqué à 60 caractères.

### `noms_communes(prix)`, `zone_couverte(prix)` et `classer_communes(prix, type_local)`

`noms_communes` renvoie les noms des communes, triés sans tenir compte des accents. `zone_couverte`
décrit ce que couvrent les données (départements, villes, années, nombre de communes) : tout est
déduit du tableau, rien n'est écrit en dur. `classer_communes` classe les communes d'un type de bien
par prix médian, en ne gardant que celles qui comptent assez de ventes.

## Le modèle (`modele.py`)

**Cible : le prix au m²**, plus stable d'un bien à l'autre que le prix total (on multiplie ensuite
par la surface). **Algorithme : `HistGradientBoostingRegressor`** (scikit-learn), des arbres de
décision enchaînés qui acceptent les cases vides et les catégories. Pour obtenir une fourchette, on
entraîne trois modèles par variante, avec la perte « quantile » : 25e centile, médiane, 75e centile.

Deux variantes sont déployées :

- **Modèle « commune »** (commune, type de bien, surface, année) : le formulaire de base.
- **Modèle « adresse »** (type de bien, surface, année, latitude, longitude) : si la requête fournit
  la position du bien. La commune n'est alors plus une variable, la position la remplace.

**Méthode utilisée pour une demande** (champ `methode` de la réponse) :

| Méthode | Quand |
|---|---|
| `adresse` | `latitude` et `longitude` fournies |
| `commune` | pas d'adresse, et une commune que le modèle connaît (un arrondissement, ou une ville sans arrondissements) |
| `mediane` | « Paris », « Lyon » ou « Marseille » en entier sans adresse (le modèle ne les connaît que par arrondissement), commune en repli sur sa ville (champ `repli`, l'adresse est alors ignorée), ou fichier du modèle absent |

**Contrôles de la demande.** Ils évitent des réponses d'apparence normale mais sans valeur :

- **La surface** doit rester dans ce que les ventes ont montré pour ce type de bien (entre le
  0,5e et le 99,5e centile : de 10 à 200 m² pour un appartement, de 27 à 300 m² pour une maison ; `/info`
  les donne dans `modele.surfaces`). Au-delà, les ventes sont trop rares : sans cette borne, le prix au m²
  d'un appartement lillois sautait de 3 825 € à 200 m² à 4 314 € à 250 m². Un arbre
  de décision ne sait pas extrapoler : au-delà, il répéterait le prix de la dernière feuille. Dans
  tous les cas, la surface doit aussi être comprise entre 9 et 1 000 m².
- **L'adresse** est rattachée à une commune par ses ventes voisines : on regarde les 10 ventes les
  plus proches (un index de positions enregistré avec les modèles). L'adresse est acceptée si au
  moins 2 d'entre elles sont dans la commune demandée (une adresse en bordure d'arrondissement a des
  voisins des deux côtés), et pour une ville entière si elles sont dans l'un de ses arrondissements.
  Sinon l'erreur dit où se trouve l'adresse (« Cette adresse se trouve à Lyon 3e Arrondissement, pas à
  Lyon 1er Arrondissement. »). Une position à plus de 1,5 km de toute vente (une mer, un autre pays)
  est « en dehors des villes couvertes ».
- **Les coordonnées** doivent être des nombres dans les limites du globe.
- **Une adresse imprécise.** L'API ne sait pas si les coordonnées viennent d'un numéro de rue ou du
  centre d'une rue entière : c'est au site de n'envoyer des coordonnées que pour un numéro de rue.

**Protocole d'évaluation** (commande `evaluer`) :

- **Séparation temporelle.** Entraînement sur 2021 à 2024, test sur 2025 : on prédit l'avenir à
  partir du passé, jamais l'inverse, et jamais un tirage au hasard qui mélangerait les années.
- **Pas de fuite de données.** Les médianes de la référence sont calculées sur l'entraînement
  seulement, et les modèles ne voient pas le prix de 2025.
- **Pas de réglage sur le jeu de test.** Les hyperparamètres sont ceux par défaut de scikit-learn,
  sauf 300 itérations : régler sur 2025 le rendrait trop optimiste.
- **Comparaison avec une référence forte.** La référence est la médiane de la dernière année, pas
  celle de toutes les années.
- **Des mesures par ville et par type de bien**, car un bon résultat global peut cacher un échec
  local.

Les mesures sont écrites dans `data/villes/evaluation.json`, gardées avec le modèle et affichées
par l'API (`/info`). Le modèle final (commande `modeliser`) est ensuite entraîné sur toutes les années,
2025 comprise.

Chaque fichier `modeles.joblib` garde aussi d'où il vient : la date d'entraînement et le commit du
code qui l'a produit (suivi de `+modifie` si des fichiers avaient des modifications non
enregistrées), écrits par la commande `modeliser`, et le nombre de ventes d'entraînement. L'API les
affiche dans `/info` (`modele.entraine_le`, `modele.commit`, `modele.nombre_ventes`) ; ils valent
`null` pour un fichier produit avant que ces champs existent.

## Les tests

| Fichier | Ce qu'il vérifie |
|---|---|
| `test_donnees.py` | chacune des six étapes de `nettoyer()` sur des lignes faites main, les statistiques par commune, le chargement et le téléchargement (sans réseau) |
| `test_estimation.py` | la validation d'une demande (surface, type, texte, caractères de contrôle), le repli sur la ville, l'arrondi à l'euro |
| `test_modele.py` | la mesure sans triche (séparation par année, référence, erreur, couverture de la fourchette), le modèle qui bat une valeur constante, les bornes de surface, le rattachement d'une adresse à sa commune, l'enregistrement des modèles |
| `test_api.py` | les statuts et les messages d'erreur, les champs que le site attend, la clé d'API, la limite par visiteur et `X-Visiteur-IP`, CORS, HEAD, la documentation désactivée, le schéma OpenAPI |
| `test_villes.py` | la liste des villes et la ligne de commande |

Pour vérifier que les tests servent à quelque chose, on peut casser le code exprès (accepter une clé
fausse, croire `X-Visiteur-IP` sans clé, garder les ventes de plusieurs logements, laisser passer une
surface hors bornes) : à chaque fois, au moins un test échoue.
