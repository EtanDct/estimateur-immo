"""Point d'entrée en ligne de commande : python -m estimateur <commande> [options].

Chaque commande est un module de estimateur/commandes/ qui définit ajouter_arguments(parser) et
executer(args). Le module d'une commande n'est importé que si on la lance : estimer ne charge donc
pas matplotlib.
"""

import argparse
import sys
from importlib import import_module

COMMANDES = {
    "construire": "télécharge et prépare les données des dix villes",
    "evaluer": "compare les modèles à la référence sur la dernière année",
    "modeliser": "entraîne et enregistre les modèles finaux",
    "estimer": "estime la fourchette de prix d'un bien",
    "graphique": "trace le graphique des prix par ville",
    "explorer": "explore les fichiers DVF d'un département",
}


def _aide():
    """Écrit la liste des commandes."""
    lignes = [f"  {nom:<11} {description}" for nom, description in COMMANDES.items()]
    entete = "usage : python -m estimateur <commande> [options]   (ou : estimateur <commande>, après pip install -e .)"
    return f"{entete}\n\ncommandes :\n" + "\n".join(lignes)


def main(argv=None):
    """Lit la commande demandée, lui passe ses arguments et renvoie son code de retour."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(_aide())
        return 0
    commande = argv[0]
    if commande not in COMMANDES:
        sys.exit(f"Commande inconnue : {commande!r}\n\n{_aide()}")

    module = import_module(f"estimateur.commandes.{commande}")
    parser = argparse.ArgumentParser(prog=f"estimateur {commande}", description=COMMANDES[commande])
    module.ajouter_arguments(parser)
    code = module.executer(parser.parse_args(argv[1:]))
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
