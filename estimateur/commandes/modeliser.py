"""Entraîne les modèles finaux sur toutes les ventes et les enregistre pour l'API.

Lit data/villes/ventes_propres.csv (commande construire) et, s'il existe, evaluation.json (commande
evaluer). Écrit data/villes/modeles.joblib, avec la date et le commit du code qui l'a produit. Les modèles sont entraînés sur toutes les années, test
compris : les mesures de la commande evaluer, elles, viennent d'un modèle qui n'a pas vu l'année testée.
"""

import json

from ..config import DOSSIER_VILLES
from ..modele import charger_ventes, enregistrer_modeles, entrainer_modeles, tracabilite
from ..villes import regroupements


def ajouter_arguments(parser):
    """Cette commande n'a pas d'option."""


def executer(args):
    """Entraîne les modèles finaux et les écrit dans modeles.joblib."""
    chemin_mesures = DOSSIER_VILLES / "evaluation.json"
    mesures = json.loads(chemin_mesures.read_text(encoding="utf-8")) if chemin_mesures.exists() else {}

    ventes = charger_ventes(DOSSIER_VILLES)
    print(f"Entraînement sur {len(ventes):,} ventes ({ventes['annee'].min()} à {ventes['annee'].max()})...".replace(",", " "))
    modeles = entrainer_modeles(ventes, regroupements(), mesures)
    modeles["tracabilite"] = tracabilite()
    enregistrer_modeles(modeles, DOSSIER_VILLES)
    print(f"Entraîné le {modeles['tracabilite']['entraine_le']}, code au commit {modeles['tracabilite']['commit']}.")
    print(f"Modèles enregistrés dans {DOSSIER_VILLES / 'modeles.joblib'}")
