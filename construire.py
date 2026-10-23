"""Construit les données du projet pour les grandes villes : télécharge, nettoie, agrège.

Écrit dans data/villes/ :
  ventes_propres.csv : une ligne par vente retenue (pour entraîner et évaluer le modèle)
  prix_communes.csv  : les statistiques par commune et par type de bien (pour l'API)

À lancer depuis la racine du projet : python construire.py
"""

import logging

import pandas as pd

from immo import DATA_DIR, charger, nettoyer, prix_par_commune, regrouper_communes, telecharger
from villes import VILLES, codes_du_departement, departements, regroupements

DOSSIER = DATA_DIR / "villes"
ANNEES = range(2021, 2026)

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


def main():
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    ventes = []
    for departement in departements():
        print(f"Département {departement} : {', '.join(nom for nom, (dep, _, _) in VILLES.items() if dep == departement)}")
        telecharger(departement, ANNEES, DOSSIER)
        brut = charger(departement, ANNEES, DOSSIER)
        brut = brut[brut["code_commune"].isin(codes_du_departement(departement))]
        ventes.append(nettoyer(brut, prix_m2_max=PRIX_M2_MAX, ecart_median=ECART_MEDIANE))

    ventes = pd.concat(ventes, ignore_index=True)
    ventes[COLONNES_VENTES].to_csv(DOSSIER / "ventes_propres.csv", index=False)

    prix = prix_par_commune(regrouper_communes(ventes, regroupements()))
    prix.to_csv(DOSSIER / "prix_communes.csv", index=False)

    print(f"\n{len(ventes)} ventes retenues, {len(prix)} lignes dans prix_communes.csv")
    print(f"Écrit dans {DOSSIER}")


if __name__ == "__main__":
    main()
