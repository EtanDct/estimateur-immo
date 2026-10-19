"""Fonctions du projet estimateur-immo : charger, nettoyer (puis prix_par_commune, estimer)."""

from pathlib import Path

import pandas as pd

# Le dossier data/ à côté de ce fichier : le chemin marche quel que soit le dossier
# d'où on lance Python (un terminal, un script, plus tard une API).
DATA_DIR = Path(__file__).parent / "data"

# Seuils par défaut du prix au m² (en €). En dessous : ventes symboliques ou entre proches
# (1 €, 90 €...). Au-dessus : erreurs de saisie (surface de 1 m²...). Ils sont réglables
# via les paramètres de nettoyer(), car 10 000 €/m² serait normal à Paris.
PRIX_M2_MIN = 300
PRIX_M2_MAX = 10_000

# Codes lus comme du texte, pour ne pas perdre le 0 de "01" ni casser "2A"/"2B".
COLONNES_CODES = {"code_departement": str, "code_commune": str, "code_postal": str}


def charger(departement):
    """Lit data/<departement>.csv et renvoie le tableau brut (rien n'est filtré)."""
    # departement est un paramètre ("51", "01", "2A"...) : jamais écrit en dur.
    # low_memory=False : pandas lit tout le fichier d'un coup, ça supprime le DtypeWarning.
    return pd.read_csv(DATA_DIR / f"{departement}.csv", dtype=COLONNES_CODES, low_memory=False)


def _noter(verbose, etape, avant, apres):
    """Affiche combien de lignes une étape a retirées (seulement si verbose=True)."""
    if verbose:
        print(f"{etape} : {avant - apres} lignes retirées, il en reste {apres}")


def nettoyer(df, prix_m2_min=PRIX_M2_MIN, prix_m2_max=PRIX_M2_MAX, verbose=False):
    """Garde les ventes d'un seul logement (maison ou appartement) au prix au m² plausible.

    Renvoie un nouveau tableau avec une colonne prix_m2 en plus. Le tableau d'origine
    n'est pas modifié. Avec verbose=True, affiche ce que retire chaque étape.
    """
    if verbose:
        print(f"Départ : {len(df)} lignes")

    # 1. Que des maisons et des appartements : on retire terrains, dépendances, locaux pro
    #    et lignes sans type_local (isin = "est dans cette liste").
    avant = len(df)
    df = df[df["type_local"].isin(["Maison", "Appartement"])]
    _noter(verbose, "1. Maisons et appartements", avant, len(df))

    # 2. Que les ventes classiques : on retire les échanges, adjudications, ventes sur plan
    #    (VEFA) et ventes de terrain à bâtir, dont le prix n'est pas comparable.
    avant = len(df)
    df = df[df["nature_mutation"] == "Vente"]
    _noter(verbose, "2. Nature de mutation = Vente", avant, len(df))

    # 3. Un prix et une surface strictement positifs. Une case vide (NaN) donne False
    #    dans une comparaison, donc les lignes vides sont retirées aussi. & = ET.
    avant = len(df)
    df = df[(df["valeur_fonciere"] > 0) & (df["surface_reelle_bati"] > 0)]
    _noter(verbose, "3. Prix > 0 et surface > 0", avant, len(df))

    # 4. Une seule ligne de logement par vente. Une vente (id_mutation) peut avoir plusieurs
    #    lignes, mais valeur_fonciere répète le prix TOTAL sur chacune : avec 2 logements,
    #    on ne saurait pas quel prix revient à quel logement.
    #    transform("size") donne à chaque ligne le nombre de lignes de sa vente.
    #    On compte APRÈS les étapes 1 à 3 : une maison vendue avec un garage ou un terrain
    #    reste une vente à un seul logement.
    avant = len(df)
    lignes_par_vente = df.groupby("id_mutation")["id_mutation"].transform("size")
    df = df[lignes_par_vente == 1]
    _noter(verbose, "4. Une seule ligne par vente", avant, len(df))

    # 5. Le prix au m² : une nouvelle colonne, prix divisé par surface (les deux > 0 ici).
    df["prix_m2"] = df["valeur_fonciere"] / df["surface_reelle_bati"]

    # 6. Valeurs aberrantes : on garde les prix au m² entre les deux seuils (inclus).
    avant = len(df)
    df = df[df["prix_m2"].between(prix_m2_min, prix_m2_max)]
    _noter(verbose, f"6. Prix au m² entre {prix_m2_min} et {prix_m2_max}", avant, len(df))

    # Les filtres laissent des numéros de ligne "troués" : on renumérote de 0 à n-1.
    return df.reset_index(drop=True)
