"""Logique du projet estimateur-immo : chargement, nettoyage, agrégation des ventes DVF et estimation.

Ce module ne lit aucun argument, n'affiche rien (ni print, ni input, ni sys.exit) et reçoit
tout en paramètres : il renvoie des valeurs ou lève des exceptions. Les scripts
(explorer.py, estimer.py, graphique.py) et plus tard une API décident de l'affichage.
"""

import logging
import unicodedata
from pathlib import Path

import pandas as pd

# Le journal du module : nettoyer() y note ce que retire chaque filtre. Rien ne s'affiche
# tant que le programme appelant n'active pas les messages (logging.basicConfig).
journal = logging.getLogger(__name__)

# Le dossier data/ à côté de ce fichier : le chemin marche quel que soit le dossier
# d'où on lance Python (un terminal, un script, plus tard une API).
DATA_DIR = Path(__file__).parent / "data"

# Seuils par défaut du prix au m² (en €). En dessous : ventes symboliques ou entre proches
# (1 €, 90 €...). Au-dessus : erreurs de saisie (surface de 1 m²...). Ils sont réglables
# via les paramètres de nettoyer(), car 10 000 €/m² serait normal à Paris.
PRIX_M2_MIN = 300
PRIX_M2_MAX = 10_000

# En dessous de ce nombre de ventes, la médiane d'une commune n'est pas fiable.
VENTES_MIN = 10

# Les types de biens pris en compte (valeurs de la colonne type_local).
TYPES_DE_BIEN = ("Maison", "Appartement")

# Les années chargées par défaut : assez de ventes par commune, sans mélanger des
# niveaux de prix trop éloignés dans le temps.
ANNEES = (2023, 2024, 2025)

# Codes lus comme du texte, pour ne pas perdre le 0 de "01" ni casser "2A"/"2B".
COLONNES_CODES = {"code_departement": str, "code_commune": str, "code_postal": str}


def charger(departement, annees=ANNEES, dossier=DATA_DIR):
    """Lit les fichiers <dossier>/<departement> <annee>.csv et les empile en un seul tableau brut.

    Rien n'est filtré. Une colonne annee indique de quel fichier vient chaque ligne.
    """
    # departement, annees et dossier sont des paramètres : jamais écrits en dur.
    tableaux = []
    for annee in annees:
        chemin = Path(dossier) / f"{departement} {annee}.csv"
        if not chemin.exists():
            raise FileNotFoundError(f"{chemin} est introuvable : placer le fichier DVF de {annee} dans {dossier}.")
        # low_memory=False : pandas lit tout le fichier d'un coup, ça supprime le DtypeWarning.
        tableau = pd.read_csv(chemin, dtype=COLONNES_CODES, low_memory=False)
        tableau["annee"] = annee
        tableaux.append(tableau)
    # Les id_mutation commencent par l'année ("2025-653539") : pas de collision entre fichiers.
    return pd.concat(tableaux, ignore_index=True)


def _noter(etape, avant, apres):
    """Note dans le journal combien de lignes une étape a retirées."""
    journal.info("%s : %d lignes retirées, il en reste %d", etape, avant - apres, apres)


def nettoyer(df, prix_m2_min=PRIX_M2_MIN, prix_m2_max=PRIX_M2_MAX):
    """Garde les ventes d'un seul logement (maison ou appartement) au prix au m² plausible.

    Renvoie un nouveau tableau avec une colonne prix_m2 en plus. Le tableau d'origine
    n'est pas modifié. Ce que retire chaque étape est noté dans le journal (niveau INFO).
    """
    journal.info("Départ : %d lignes", len(df))

    # 1. Que des maisons et des appartements : on retire terrains, dépendances, locaux pro
    #    et lignes sans type_local (isin = "est dans cette liste").
    avant = len(df)
    df = df[df["type_local"].isin(TYPES_DE_BIEN)]
    _noter("1. Maisons et appartements", avant, len(df))

    # 2. Que les ventes classiques : on retire les échanges, adjudications, ventes sur plan
    #    (VEFA) et ventes de terrain à bâtir, dont le prix n'est pas comparable.
    avant = len(df)
    df = df[df["nature_mutation"] == "Vente"]
    _noter("2. Nature de mutation = Vente", avant, len(df))

    # 3. Un prix et une surface strictement positifs. Une case vide (NaN) donne False
    #    dans une comparaison, donc les lignes vides sont retirées aussi. & = ET.
    avant = len(df)
    df = df[(df["valeur_fonciere"] > 0) & (df["surface_reelle_bati"] > 0)]
    _noter("3. Prix > 0 et surface > 0", avant, len(df))

    # 4. Une seule ligne de logement par vente. Une vente (id_mutation) peut avoir plusieurs
    #    lignes, mais valeur_fonciere répète le prix TOTAL sur chacune : avec 2 logements,
    #    on ne saurait pas quel prix revient à quel logement.
    #    transform("size") donne à chaque ligne le nombre de lignes de sa vente.
    #    On compte APRÈS les étapes 1 à 3 : une maison vendue avec un garage ou un terrain
    #    reste une vente à un seul logement.
    avant = len(df)
    lignes_par_vente = df.groupby("id_mutation")["id_mutation"].transform("size")
    df = df[lignes_par_vente == 1]
    _noter("4. Une seule ligne par vente", avant, len(df))

    # Le prix au m² : une nouvelle colonne, prix divisé par surface (les deux > 0 ici).
    df["prix_m2"] = df["valeur_fonciere"] / df["surface_reelle_bati"]

    # 5. Valeurs aberrantes : on garde les prix au m² entre les deux seuils (inclus).
    avant = len(df)
    df = df[df["prix_m2"].between(prix_m2_min, prix_m2_max)]
    _noter(f"5. Prix au m² entre {prix_m2_min} et {prix_m2_max}", avant, len(df))

    # Les filtres laissent des numéros de ligne "troués" : on renumérote de 0 à n-1.
    return df.reset_index(drop=True)


def prix_par_commune(df):
    """Calcule, par commune et par type de bien, les statistiques du prix au m².

    Reçoit le tableau déjà nettoyé (le résultat de nettoyer()). Renvoie un tableau avec une
    ligne par commune et par type_local, et les colonnes : code_commune, nom_commune,
    type_local, mediane, quartile_1, quartile_3 (du prix_m2), nombre_ventes, et annee_min /
    annee_max (la première et la dernière année des ventes prises en compte).
    """
    # Le code de commune identifie la commune de façon unique ; le nom sert à l'affichage.
    grouped = df.groupby(["code_commune", "nom_commune", "type_local"])

    # Chaque statistique : nom=(colonne, calcul). Un lambda pour les quartiles, car
    # quantile() prend un paramètre.
    stats = grouped.agg(
        mediane=("prix_m2", "median"),
        quartile_1=("prix_m2", lambda s: s.quantile(0.25)),
        quartile_3=("prix_m2", lambda s: s.quantile(0.75)),
        nombre_ventes=("prix_m2", "count"),
        annee_min=("annee", "min"),
        annee_max=("annee", "max"),
    ).reset_index()  # remet commune, nom et type en colonnes (ils étaient dans l'index)

    return stats


def charger_prix_communes(dossier=DATA_DIR):
    """Lit <dossier>/prix_communes.csv, le fichier produit à partir de prix_par_commune()."""
    chemin = Path(dossier) / "prix_communes.csv"
    if not chemin.exists():
        raise FileNotFoundError(f"{chemin} est introuvable : lancer d'abord python explorer.py pour le générer.")
    return pd.read_csv(chemin, dtype={"code_commune": str})


def _normaliser(texte):
    """Met un nom sous une forme comparable : minuscules, sans accents, sans tirets ni apostrophes.

    "Épernay" et "epernay" donnent la même chose, comme "Saint-Martin-d'Ablois" et
    "saint martin d ablois".
    """
    # NFD sépare chaque lettre accentuée en lettre + accent ; on jette les accents.
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c))
    simple = sans_accents.casefold().replace("œ", "oe").replace("æ", "ae")
    for separateur in ("-", "'", "’"):
        simple = simple.replace(separateur, " ")
    return " ".join(simple.split())  # split() + join : supprime les espaces en trop


def estimer(prix, commune, type_local, surface, ventes_min=VENTES_MIN):
    """Estime une fourchette de prix pour un bien, à partir des statistiques par commune.

    prix : le tableau produit par prix_par_commune() (ou lu par charger_prix_communes()).
    Renvoie un dictionnaire : commune, type_local, surface, nombre_ventes, annee_min,
    annee_max, prix_m2_median, et prix_bas / prix_median / prix_haut (surface x quartile_1,
    mediane, quartile_3).
    Lève une ValueError au message clair si la surface ou le type de bien est invalide, si
    la commune est introuvable, ou si elle compte moins de ventes_min ventes.
    """
    if surface <= 0:
        raise ValueError(f"La surface doit être positive (reçu : {surface:g}).")

    types = {_normaliser(t): t for t in TYPES_DE_BIEN}
    if _normaliser(type_local) not in types:
        raise ValueError(f"Type de bien inconnu : {type_local!r}. Valeurs possibles : {', '.join(TYPES_DE_BIEN)}.")
    type_local = types[_normaliser(type_local)]

    # On compare les noms sous forme normalisée, pour ignorer la casse et les accents.
    noms = prix["nom_commune"].map(_normaliser)
    de_la_commune = prix[noms == _normaliser(commune)]
    if de_la_commune.empty:
        raise ValueError(f"Commune introuvable : {commune!r} (nom mal écrit, ou aucune vente exploitable).")

    lignes = de_la_commune[de_la_commune["type_local"] == type_local]
    nom = de_la_commune["nom_commune"].iloc[0]
    if lignes.empty:
        raise ValueError(f"Aucune vente exploitable de {type_local.lower()} à {nom}.")
    if len(lignes) > 1:  # une ligne par commune et par type : plusieurs lignes = plusieurs communes
        codes = ", ".join(lignes["code_commune"])
        raise ValueError(f"Plusieurs communes s'appellent {nom} (codes {codes}).")

    ligne = lignes.iloc[0]
    if ligne["nombre_ventes"] < ventes_min:
        raise ValueError(
            f"Seulement {ligne['nombre_ventes']} vente(s) de {type_local.lower()} à {nom} : "
            f"il en faut au moins {ventes_min} pour une estimation fiable."
        )

    return {
        "commune": nom,
        "type_local": type_local,
        "surface": surface,
        "nombre_ventes": int(ligne["nombre_ventes"]),
        "annee_min": int(ligne["annee_min"]),
        "annee_max": int(ligne["annee_max"]),
        "prix_m2_median": float(ligne["mediane"]),
        "prix_bas": surface * float(ligne["quartile_1"]),
        "prix_median": surface * float(ligne["mediane"]),
        "prix_haut": surface * float(ligne["quartile_3"]),
    }


def classer_communes(prix, type_local, ventes_min=VENTES_MIN):
    """Classe les communes d'un type de bien de la plus chère à la moins chère.

    Le classement porte sur la médiane du prix au m². Seules les communes qui comptent au
    moins ventes_min ventes sont gardées, pour que le classement repose sur assez de ventes.
    """
    lignes = prix[(prix["type_local"] == type_local) & (prix["nombre_ventes"] >= ventes_min)]
    return lignes.sort_values("mediane", ascending=False).reset_index(drop=True)
