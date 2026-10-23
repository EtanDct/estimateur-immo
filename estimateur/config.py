"""Chemins et réglages partagés par tout le projet."""

from pathlib import Path

# La racine du projet : le dossier qui contient estimateur/, data/ et docs/. Le chemin est calculé
# à partir de ce fichier : il marche quel que soit le dossier d'où on lance Python (un terminal,
# l'API, un conteneur).
RACINE = Path(__file__).resolve().parents[1]
DATA_DIR = RACINE / "data"
DOSSIER_VILLES = DATA_DIR / "villes"  # les données du projet : fichiers DVF, statistiques, modèles
DOCS_DIR = RACINE / "docs"

# Seuils par défaut du prix au m² (en €). En dessous : ventes symboliques ou entre proches
# (1 €, 90 €...). Au-dessus : erreurs de saisie (surface de 1 m²...). Ils sont réglables
# via les paramètres de nettoyer(), car 10 000 €/m² serait normal à Paris.
PRIX_M2_MIN = 300
PRIX_M2_MAX = 10_000

# En dessous de ce nombre de ventes, la médiane d'une commune n'est pas fiable.
VENTES_MIN = 10

# Les types de biens pris en compte (valeurs de la colonne type_local).
TYPES_DE_BIEN = ("Maison", "Appartement")

# Surfaces acceptées pour une estimation (en m²). 9 m² est la surface minimale d'un logement
# décent ; au-delà de 1 000 m², ce n'est plus un logement. Le modèle est plus strict : il refuse
# aussi les surfaces qu'il n'a jamais vues dans les ventes (voir modele.py).
SURFACE_MIN = 9
SURFACE_MAX = 1_000

# Longueur maximale d'un nom de commune ou de type de bien reçu en paramètre.
LONGUEUR_TEXTE_MAX = 100

# Les années chargées par défaut : assez de ventes par commune, sans mélanger des
# niveaux de prix trop éloignés dans le temps.
ANNEES = (2023, 2024, 2025)

# Codes lus comme du texte, pour ne pas perdre le 0 de "01" ni casser "2A"/"2B".
COLONNES_CODES = {"code_departement": str, "code_commune": str, "code_postal": str}
