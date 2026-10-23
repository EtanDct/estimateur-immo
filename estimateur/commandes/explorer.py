"""Explore les fichiers DVF d'un département : taille, colonnes, types de biens, cases vides, nettoyage.

Exemple : python -m estimateur explorer 75 --annees 2025
Cette commande affiche des diagnostics et n'écrit aucun fichier.
"""

import logging

from ..config import ANNEES, DOSSIER_VILLES
from ..donnees import charger, nettoyer, prix_par_commune


def ajouter_arguments(parser):
    """Déclare les options de la commande."""
    parser.add_argument("departement", help="code du département, par exemple 75 ou 2A")
    parser.add_argument("--annees", type=int, nargs="+", default=list(ANNEES), help="années à charger (par défaut : %(default)s)")
    parser.add_argument("--dossier", default=str(DOSSIER_VILLES), help="dossier des fichiers « <département> <année>.csv »")


def executer(args):
    """Charge les fichiers, affiche des diagnostics sur le tableau brut, puis ce que retire chaque étape du nettoyage."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # affiche le journal de nettoyer()

    # --- Fichier brut ---
    df = charger(args.departement, args.annees, args.dossier)
    print(df.shape)
    print(df["annee"].value_counts().sort_index())  # lignes par année
    print(df.columns)    # la liste des noms de colonnes
    print(df.head())     # les 5 premières lignes

    # Répartition des types de biens (dropna=False : compte aussi les cases vides)
    print(df["type_local"].value_counts(dropna=False))

    # --- Lignes sans type_local ---
    sans_type = df[df["type_local"].isna()]  # filtre : on garde les lignes où type_local est vide
    print(len(sans_type))                                # combien de lignes
    print(sans_type["surface_terrain"].notna().sum())    # combien ont une surface de terrain
    print(sans_type["nature_culture"].notna().sum())     # combien ont une nature de culture

    # Les lignes sans nature_culture ni surface_terrain (& = ET)
    inclassables = sans_type[sans_type["nature_culture"].isna() & sans_type["surface_terrain"].isna()]
    print(len(inclassables))
    print(inclassables[["nature_mutation", "valeur_fonciere", "nombre_lots", "id_parcelle"]].head())

    # --- Lignes sans surface_reelle_bati, par type_local ---
    sans_surface = df[df["surface_reelle_bati"].isna()]
    print(sans_surface["type_local"].value_counts(dropna=False))

    print(df.isna().sum())  # nombre de valeurs manquantes par colonne

    # --- Nettoyage ---
    propre = nettoyer(df)
    print(propre.shape)
    print(propre[["nom_commune", "type_local", "valeur_fonciere", "surface_reelle_bati", "prix_m2"]].head())
    print(propre["prix_m2"].describe().round(0))

    # --- Prix par commune ---
    prix = prix_par_commune(propre)
    print(prix.shape)
    print(prix.head())
