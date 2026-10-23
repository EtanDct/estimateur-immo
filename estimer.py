"""Outil en ligne de commande : estime une fourchette de prix à partir des ventes DVF.

Exemple : python estimer.py --commune Lyon --type Appartement --surface 65
Avec l'adresse du bien (bien plus précis) : ajouter --latitude 45.76 --longitude 4.83
"""

import argparse
import sys

from immo import DATA_DIR, TYPES_DE_BIEN, charger_prix_communes
from modele import charger_modeles, estimer_prix

DOSSIER = DATA_DIR / "villes"  # là où construire.py et modeliser.py écrivent


def _euros(montant):
    """Formate un montant arrondi au millier, avec des espaces : 142 000 €."""
    return f"{round(montant, -3):,.0f}".replace(",", " ") + " €"


def _periode(resultat):
    """Écrit la période des ventes : « en 2024 » ou « de 2023 à 2025 »."""
    if resultat["annee_min"] == resultat["annee_max"]:
        return f"en {resultat['annee_min']}"
    return f"de {resultat['annee_min']} à {resultat['annee_max']}"


METHODES = {
    "adresse": "modèle tenant compte de l'adresse",
    "commune": "modèle de la commune",
    "mediane": "médiane des ventes de la commune",
}


def main():
    """Lit les arguments du terminal, appelle modele.estimer_prix() et affiche le résultat."""
    parser = argparse.ArgumentParser(description="Estime une fourchette de prix à partir des ventes réelles (DVF).")
    parser.add_argument("--commune", required=True, help="nom de la commune, par exemple Lyon")
    parser.add_argument("--type", dest="type_local", required=True, help=f"type de bien : {' ou '.join(TYPES_DE_BIEN)}")
    parser.add_argument("--surface", type=float, required=True, help="surface habitable en m²")
    parser.add_argument("--latitude", type=float, help="latitude de l'adresse du bien (avec --longitude)")
    parser.add_argument("--longitude", type=float, help="longitude de l'adresse du bien (avec --latitude)")
    args = parser.parse_args()

    try:
        resultat = estimer_prix(
            charger_prix_communes(DOSSIER), charger_modeles(DOSSIER),
            args.commune, args.type_local, args.surface, args.latitude, args.longitude,
        )
    except (ValueError, FileNotFoundError) as erreur:
        sys.exit(f"Erreur : {erreur}")  # message sur la sortie d'erreur, code de retour 1

    print(f"{resultat['commune']} - {resultat['type_local']}, {resultat['surface']:g} m²")
    print(f"Fourchette estimée : {_euros(resultat['prix_bas'])} à {_euros(resultat['prix_haut'])}")
    print(f"Prix médian : {_euros(resultat['prix_median'])} ({resultat['prix_m2_median']:,.0f} €/m²)".replace(",", " "))
    print(f"Méthode : {METHODES[resultat['methode']]}. Statistiques de la commune : {resultat['nombre_ventes']} ventes {_periode(resultat)}.")


if __name__ == "__main__":
    main()
