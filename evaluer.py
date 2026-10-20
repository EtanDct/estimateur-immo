"""Compare le modèle à la référence (médiane par commune) sur les ventes de la dernière année.

À lancer depuis la racine du projet : python evaluer.py
"""

from immo import charger, nettoyer
from modele import ANNEE_TEST, entrainer, mesurer_erreur, predire_par_mediane, separer_par_annee

DEPARTEMENT = "51"
ANNEES = range(2021, 2026)  # toutes les années disponibles : le modèle a besoin d'historique


def main():
    propre = nettoyer(charger(DEPARTEMENT, annees=ANNEES))

    # PLAN:
    #


if __name__ == "__main__":
    main()
