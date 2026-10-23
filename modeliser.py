"""Entraîne les modèles finaux sur toutes les ventes et les enregistre pour l'API.

Lit data/villes/ventes_propres.csv (construire.py) et, s'il existe, evaluation.json (evaluer.py).
Écrit data/villes/modeles.joblib. Les modèles sont entraînés sur toutes les années, test compris :
les mesures de evaluer.py, elles, viennent d'un modèle qui n'a pas vu l'année testée.

À lancer depuis la racine du projet : python modeliser.py
"""

import json

from immo import DATA_DIR
from modele import charger_ventes, enregistrer_modeles, entrainer_modeles
from villes import regroupements

DOSSIER = DATA_DIR / "villes"


def main():
    chemin_mesures = DOSSIER / "evaluation.json"
    mesures = json.loads(chemin_mesures.read_text(encoding="utf-8")) if chemin_mesures.exists() else {}

    ventes = charger_ventes(DOSSIER)
    print(f"Entraînement sur {len(ventes):,} ventes ({ventes['annee'].min()} à {ventes['annee'].max()})...".replace(",", " "))
    modeles = entrainer_modeles(ventes, regroupements(), mesures)
    enregistrer_modeles(modeles, DOSSIER)
    print(f"Modèles enregistrés dans {DOSSIER / 'modeles.joblib'}")


if __name__ == "__main__":
    main()
