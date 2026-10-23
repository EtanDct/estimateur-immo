"""Compare les modèles à la référence (médiane par commune) sur les ventes de la dernière année.

On entraîne sur les années d'avant et on teste sur la dernière : le modèle ne voit jamais le prix
des ventes qu'il doit estimer. Les données viennent de construire.py.

À lancer depuis la racine du projet : python evaluer.py
"""

import pandas as pd

from modele import (
    ANNEE_TEST, VARIABLES_A, VARIABLES_B, VARIABLES_C,
    charger_ventes, entrainer, mesurer_erreur, mesurer_fourchette,
    predire_par_groupe, separer_par_annee,
)
from villes import VILLE_DE

REFERENCE = "Référence : médiane de toutes les années"
REFERENCE_RECENTE = "Référence : médiane de la dernière année"
MODELE_A = "Modèle A : commune, type, surface, année"
MODELE_B = "Modèle B : A + pièces et terrain"
MODELE_C = "Modèle C : B + position exacte (plafond)"


def _par_groupe(entrainement, test):
    """Prédit (médiane, 25e centile, 75e centile) par la médiane de la commune et du type de bien."""
    return tuple(predire_par_groupe(entrainement, test, q) for q in (0.5, 0.25, 0.75))


def _par_modele(entrainement, test, variables):
    """Entraîne trois modèles (médiane, 25e et 75e centiles) et prédit le test."""
    return tuple(pd.Series(entrainer(entrainement, variables, q).predict(test), test.index) for q in (0.5, 0.25, 0.75))


def _erreur_mediane(test, prevu):
    """Renvoie l'erreur relative médiane (en %) d'une prédiction sur le test."""
    return mesurer_erreur(test["prix_m2"], prevu, test["surface_reelle_bati"])["erreur_mediane_pct"]


def main():
    ventes = charger_ventes()
    entrainement, test = separer_par_annee(ventes)
    derniere_annee = entrainement[entrainement["annee"] == entrainement["annee"].max()]
    print(f"Entraînement : {len(entrainement):,} ventes ({entrainement['annee'].min()} à {entrainement['annee'].max()})".replace(",", " "))
    print(f"Test         : {len(test):,} ventes ({ANNEE_TEST})\n".replace(",", " "))

    # Le modèle prédit pour l'année du test : on la lui donne comme variable "annee".
    predictions = {
        REFERENCE: _par_groupe(entrainement, test),
        REFERENCE_RECENTE: _par_groupe(derniere_annee, test),
    }
    for nom, variables in {MODELE_A: VARIABLES_A, MODELE_B: VARIABLES_B, MODELE_C: VARIABLES_C}.items():
        predictions[nom] = _par_modele(entrainement, test, variables)

    resultats = {}
    for nom, (mediane, bas, haut) in predictions.items():
        resultats[nom] = {
            **mesurer_erreur(test["prix_m2"], mediane, test["surface_reelle_bati"]),
            **mesurer_fourchette(test["prix_m2"], bas, haut),
        }
    tableau = pd.DataFrame(resultats).T
    tableau.columns = ["Erreur €/m²", "Erreur médiane %", "Erreur prix €", "Fourchette: couverture %", "Fourchette: largeur %"]
    print(tableau.round(1).to_string())

    # Par ville et par type de bien : un bon résultat global peut cacher un échec local.
    test = test.assign(ville=test["code_commune"].map(VILLE_DE))
    for critere in ("ville", "type_local"):
        lignes = {}
        for groupe, ventes_du_groupe in test.groupby(critere):
            idx = ventes_du_groupe.index
            lignes[groupe] = {
                "Ventes": len(idx),
                "Réf. récente %": _erreur_mediane(ventes_du_groupe, predictions[REFERENCE_RECENTE][0][idx]),
                "Modèle B %": _erreur_mediane(ventes_du_groupe, predictions[MODELE_B][0][idx]),
            }
        print(f"\nErreur médiane par {critere} (en %) :")
        print(pd.DataFrame(lignes).T.round(1).to_string())


if __name__ == "__main__":
    main()
