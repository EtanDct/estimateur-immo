"""Les données : télécharger, charger, nettoyer et agréger les ventes DVF.

Ce module ne lit aucun argument et n'affiche rien (ni print, ni input, ni sys.exit) : il reçoit
tout en paramètres, renvoie des valeurs ou lève des exceptions. Les commandes (estimateur/commandes/)
et l'API (api.py) décident de l'affichage.
"""

import gzip
import logging
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

from .config import ANNEES, COLONNES_CODES, DOSSIER_VILLES, PRIX_M2_MAX, PRIX_M2_MIN, TYPES_DE_BIEN

# Le journal du module : nettoyer() y note ce que retire chaque filtre. Rien ne s'affiche
# tant que le programme appelant n'active pas les messages (logging.basicConfig).
journal = logging.getLogger(__name__)

# Les fichiers DVF géolocalisés, un par département et par année, publiés sur data.gouv.fr.
URL_DVF = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{departement}.csv.gz"


def telecharger(departement, annees=ANNEES, dossier=DOSSIER_VILLES):
    """Télécharge les fichiers DVF d'un département vers <dossier>/<departement> <annee>.csv.

    Un fichier déjà présent n'est pas retéléchargé. Renvoie la liste des fichiers écrits.
    Lève une FileNotFoundError si data.gouv.fr n'a pas le fichier : l'Alsace-Moselle (57, 67, 68)
    et Mayotte ne sont pas couvertes par DVF.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for annee in annees:
        chemin = dossier / f"{departement} {annee}.csv"
        if chemin.exists():
            continue
        url = URL_DVF.format(annee=annee, departement=departement)
        try:
            with urllib.request.urlopen(url, timeout=120) as reponse:
                contenu = gzip.decompress(reponse.read())
        except urllib.error.HTTPError as erreur:
            raise FileNotFoundError(
                f"{url} est introuvable (HTTP {erreur.code}) : ce département n'est peut-être pas couvert par DVF."
            ) from erreur
        # Écrit sous un nom provisoire puis renomme : un téléchargement interrompu ne laisse
        # jamais un fichier tronqué que charger() prendrait pour un fichier complet.
        provisoire = chemin.with_name(chemin.name + ".part")
        provisoire.write_bytes(contenu)
        provisoire.replace(chemin)
        journal.info("Téléchargé : %s (%.1f Mo)", chemin.name, len(contenu) / 1_000_000)
        ecrits.append(chemin)
    return ecrits


def charger(departement, annees=ANNEES, dossier=DOSSIER_VILLES):
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


def nettoyer(df, prix_m2_min=PRIX_M2_MIN, prix_m2_max=PRIX_M2_MAX, ecart_median=None):
    """Garde les ventes d'un seul logement (maison ou appartement) au prix au m² plausible.

    Renvoie un nouveau tableau avec une colonne prix_m2 en plus. Le tableau d'origine
    n'est pas modifié. Ce que retire chaque étape est noté dans le journal (niveau INFO).

    ecart_median : si renseigné (par exemple 3), retire aussi les ventes dont le prix au m² sort de
    l'intervalle [médiane / 3, médiane x 3] de leur commune et de leur type de bien. Des seuils
    fixes ne conviennent pas quand les prix varient beaucoup d'une ville à l'autre : 10 000 €/m²
    est une valeur aberrante dans la Marne, et un prix courant à Paris.
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

    # 6. Facultatif : un prix au m² proche de celui des autres ventes de la même commune.
    #    transform("median") donne à chaque ligne la médiane de son groupe (une commune, un type).
    if ecart_median is not None:
        avant = len(df)
        mediane = df.groupby(["code_commune", "type_local"])["prix_m2"].transform("median")
        df = df[df["prix_m2"].between(mediane / ecart_median, mediane * ecart_median)]
        _noter(f"6. Prix au m² à moins de x{ecart_median:g} de la médiane de la commune", avant, len(df))

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


def regrouper_communes(df, regroupements):
    """Ajoute les ventes de communes réunies sous un seul nom : Paris en entier, par exemple.

    regroupements : {code: (nom, [codes des communes à réunir])}. Pour chaque regroupement, les
    ventes de ces communes sont copiées avec le code et le nom du regroupement. Les ventes
    d'origine sont conservées : on obtient donc les arrondissements ET la ville.
    """
    reunies = []
    for code, (nom, codes) in regroupements.items():
        ventes = df[df["code_commune"].isin(codes)].copy()
        ventes["code_commune"] = code
        ventes["nom_commune"] = nom
        reunies.append(ventes)
    return pd.concat([df, *reunies], ignore_index=True)


def charger_prix_communes(dossier=DOSSIER_VILLES):
    """Lit <dossier>/prix_communes.csv, le fichier produit à partir de prix_par_commune()."""
    chemin = Path(dossier) / "prix_communes.csv"
    if not chemin.exists():
        raise FileNotFoundError(f"{chemin} est introuvable : lancer d'abord python -m estimateur construire.")
    return pd.read_csv(chemin, dtype={"code_commune": str})
