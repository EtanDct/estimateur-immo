"""Télécharge et prépare les données des dix villes : ventes propres et statistiques par commune.

Écrit dans data/villes/ :
  ventes_propres.csv : une ligne par vente retenue (pour entraîner et évaluer le modèle)
  prix_communes.csv  : les statistiques par commune et par type de bien (pour l'API)

Ensuite : python -m estimateur evaluer (mesure les modèles), puis python -m estimateur modeliser.
"""

import logging

import pandas as pd

from ..config import DOSSIER_VILLES
from ..donnees import charger, nettoyer, prix_par_commune, regrouper_communes, telecharger
from ..villes import VILLE_DE, VILLES, codes_du_departement, departements, regroupements

ANNEES = range(2021, 2026)

# Les statistiques par commune (médiane, quartiles) ne portent que sur les années récentes :
# les prix bougent, et une médiane sur cinq ans estime moins bien l'année suivante qu'une
# médiane sur la dernière année (voir la commande evaluer).
ANNEES_STATS = (2024, 2025)

# Les prix dépassent souvent 10 000 €/m² à Paris : le plafond absolu ne sert que de garde-fou,
# et l'écart à la médiane de la commune fait le tri.
PRIX_M2_MAX = 50_000
ECART_MEDIANE = 3

# Les colonnes gardées pour le modèle : ce que décrit la vente, et son prix.
COLONNES_VENTES = [
    "id_mutation", "date_mutation", "annee", "code_commune", "nom_commune", "type_local",
    "surface_reelle_bati", "nombre_pieces_principales", "surface_terrain", "latitude", "longitude",
    "valeur_fonciere", "prix_m2",
]


def ajouter_arguments(parser):
    """Cette commande n'a pas d'option."""


def executer(args):
    """Télécharge les fichiers DVF des villes, les nettoie et écrit les deux fichiers de sortie."""
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    ventes = []
    for departement in departements():
        villes = ", ".join(nom for nom, (dep, _, _) in VILLES.items() if dep == departement)
        print(f"Département {departement} : {villes}", flush=True)
        telecharger(departement, ANNEES, DOSSIER_VILLES)
        brut = charger(departement, ANNEES, DOSSIER_VILLES)
        brut = brut[brut["code_commune"].isin(codes_du_departement(departement))]
        ventes.append(nettoyer(brut, prix_m2_max=PRIX_M2_MAX, ecart_median=ECART_MEDIANE))

    ventes = pd.concat(ventes, ignore_index=True)
    ventes[COLONNES_VENTES].to_csv(DOSSIER_VILLES / "ventes_propres.csv", index=False)

    recentes = ventes[ventes["annee"].isin(ANNEES_STATS)]
    prix = prix_par_commune(regrouper_communes(recentes, regroupements()))
    prix["ville"] = prix["code_commune"].map(VILLE_DE)
    prix.to_csv(DOSSIER_VILLES / "prix_communes.csv", index=False)

    print(f"\n{len(ventes)} ventes retenues, {len(prix)} lignes dans prix_communes.csv")
    print(f"Écrit dans {DOSSIER_VILLES}")
