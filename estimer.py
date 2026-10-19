"""Outil en ligne de commande : estime une fourchette de prix à partir des ventes DVF.

Exemple : python estimer.py --commune Reims --type Appartement --surface 65
"""

import argparse
import sys

from immo import TYPES_DE_BIEN, charger_prix_communes, estimer


def _euros(montant):
    """Formate un montant arrondi au millier, avec des espaces : 142 000 €."""
    return f"{round(montant, -3):,.0f}".replace(",", " ") + " €"


def main():
    """Lit les arguments du terminal, appelle immo.estimer() et affiche le résultat."""
    parser = argparse.ArgumentParser(description="Estime une fourchette de prix à partir des ventes réelles (DVF).")
    parser.add_argument("--commune", required=True, help="nom de la commune, par exemple Reims")
    parser.add_argument("--type", dest="type_local", required=True, help=f"type de bien : {' ou '.join(TYPES_DE_BIEN)}")
    parser.add_argument("--surface", type=float, required=True, help="surface habitable en m²")
    args = parser.parse_args()

    try:
        resultat = estimer(charger_prix_communes(), args.commune, args.type_local, args.surface)
    except (ValueError, FileNotFoundError) as erreur:
        sys.exit(f"Erreur : {erreur}")  # message sur la sortie d'erreur, code de retour 1

    print(f"{resultat['commune']} - {resultat['type_local']}, {resultat['surface']:g} m²")
    print(f"Fourchette estimée : {_euros(resultat['prix_bas'])} à {_euros(resultat['prix_haut'])}")
    print(f"Prix médian : {_euros(resultat['prix_median'])} ({resultat['prix_m2_median']:,.0f} €/m²)".replace(",", " "))
    print(f"Basé sur {resultat['nombre_ventes']} ventes.")


if __name__ == "__main__":
    main()
