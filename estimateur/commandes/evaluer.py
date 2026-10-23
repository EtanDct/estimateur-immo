"""Compare les modèles à la référence (médiane par commune) sur les ventes de la dernière année.

On entraîne sur les années d'avant et on teste sur la dernière : le modèle ne voit jamais le prix
des ventes qu'il doit estimer. Les données viennent de la commande construire. Les mesures sont
aussi écrites dans data/villes/evaluation.json, pour la commande modeliser.
"""

import json

import pandas as pd

from ..config import DOSSIER_VILLES
from ..modele import (
    ANNEE_TEST,
    VARIABLES_ADRESSE,
    VARIABLES_COMMUNE,
    VARIABLES_COMPLET,
    VARIABLES_PIECES,
    charger_ventes,
    entrainer,
    mesurer_erreur,
    mesurer_fourchette,
    predire_par_groupe,
    separer_par_annee,
)
from ..villes import VILLE_DE

REFERENCE = "Référence : médiane de toutes les années"
REFERENCE_RECENTE = "Référence : médiane de la dernière année"
MODELE_COMMUNE = "Modèle commune : commune, type, surface, année"
MODELE_PIECES = "Modèle commune + pièces et terrain"
MODELE_ADRESSE = "Modèle adresse : type, surface, année, position"
MODELE_COMPLET = "Modèle complet : tout (plafond)"


def _par_groupe(entrainement, test):
    """Prédit (médiane, 25e centile, 75e centile) par la médiane de la commune et du type de bien."""
    return tuple(predire_par_groupe(entrainement, test, q) for q in (0.5, 0.25, 0.75))


def _par_modele(entrainement, test, variables):
    """Entraîne trois modèles (médiane, 25e et 75e centiles) et prédit le test."""
    return tuple(pd.Series(entrainer(entrainement, variables, q).predict(test), test.index) for q in (0.5, 0.25, 0.75))


def _erreur_mediane(test, prevu):
    """Renvoie l'erreur relative médiane (en %) d'une prédiction sur le test."""
    return mesurer_erreur(test["prix_m2"], prevu, test["surface_reelle_bati"])["erreur_mediane_pct"]


def ajouter_arguments(parser):
    """Cette commande n'a pas d'option."""


def executer(args):
    """Entraîne les modèles de comparaison, affiche les mesures et les écrit dans evaluation.json."""
    ventes = charger_ventes()
    entrainement, test = separer_par_annee(ventes)
    derniere_annee = entrainement[entrainement["annee"] == entrainement["annee"].max()]
    print(f"Entraînement : {len(entrainement):,} ventes ({entrainement['annee'].min()} à {entrainement['annee'].max()})".replace(",", " "))
    print(f"Test         : {len(test):,} ventes ({ANNEE_TEST})\n".replace(",", " "))

    predictions = {
        REFERENCE: _par_groupe(entrainement, test),
        REFERENCE_RECENTE: _par_groupe(derniere_annee, test),
    }
    for nom, variables in {
        MODELE_COMMUNE: VARIABLES_COMMUNE,
        MODELE_PIECES: VARIABLES_PIECES,
        MODELE_ADRESSE: VARIABLES_ADRESSE,
        MODELE_COMPLET: VARIABLES_COMPLET,
    }.items():
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
                "Commune %": _erreur_mediane(ventes_du_groupe, predictions[MODELE_COMMUNE][0][idx]),
                "Adresse %": _erreur_mediane(ventes_du_groupe, predictions[MODELE_ADRESSE][0][idx]),
            }
        print(f"\nErreur médiane par {critere} (en %) :")
        print(pd.DataFrame(lignes).T.round(1).to_string())

    arrondies = {nom: {cle: round(float(valeur), 1) for cle, valeur in mesures_du_modele.items()} for nom, mesures_du_modele in resultats.items()}
    mesures = {
        "entrainement": [int(entrainement["annee"].min()), int(entrainement["annee"].max())],
        "test": ANNEE_TEST,
        "ventes_test": len(test),
        "modeles": arrondies,
        # Le résumé que l'API affiche : l'erreur médiane (en %) de chaque méthode d'estimation.
        "resume": {
            "annee_testee": ANNEE_TEST,
            "ventes_testees": len(test),
            "erreur_mediane_pct": {
                "mediane": arrondies[REFERENCE_RECENTE]["erreur_mediane_pct"],
                "commune": arrondies[MODELE_COMMUNE]["erreur_mediane_pct"],
                "adresse": arrondies[MODELE_ADRESSE]["erreur_mediane_pct"],
            },
            "couverture_fourchette_pct": arrondies[MODELE_COMMUNE]["couverture_pct"],
        },
    }
    (DOSSIER_VILLES / "evaluation.json").write_text(json.dumps(mesures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMesures écrites dans {DOSSIER_VILLES / 'evaluation.json'}")
