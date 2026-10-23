"""Modèle de prix au m² : séparation par année, référence, entraînement et mesure de l'erreur.

Comme immo.py, ce module n'affiche rien : evaluer.py l'appelle et présente les résultats.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from immo import DATA_DIR

# L'année de test : on entraîne sur les années d'avant, on teste sur celle-ci, comme en vrai
# (le modèle prédit l'avenir à partir du passé).
ANNEE_TEST = 2025

# Les colonnes qui sont des catégories (le reste est numérique). Un arbre de décision les
# traite comme des étiquettes, sans ordre : la commune 75110 n'est pas « plus grande » que 75101.
CATEGORIELLES = ("code_commune", "type_local")

# Les variables que chaque modèle a le droit d'utiliser. A : ce que le formulaire demande déjà,
# plus l'année de la vente (les prix bougent : le modèle apprend à donner plus de poids aux années
# récentes, et à la prédiction on lui donne la dernière année connue).
# B : le formulaire demanderait aussi le nombre de pièces et la surface du terrain.
# C : B + la position exacte du bien, que le formulaire ne connaît pas (sert de plafond).
VARIABLES_A = ("code_commune", "type_local", "surface_reelle_bati", "annee")
VARIABLES_B = VARIABLES_A + ("nombre_pieces_principales", "surface_terrain")
VARIABLES_C = VARIABLES_B + ("latitude", "longitude")


def charger_ventes(dossier=DATA_DIR / "villes"):
    """Lit <dossier>/ventes_propres.csv, le fichier écrit par construire.py."""
    return pd.read_csv(dossier / "ventes_propres.csv", dtype={"code_commune": str}, low_memory=False)


def separer_par_annee(df, annee_test=ANNEE_TEST):
    """Sépare les ventes nettoyées en deux tableaux : (entrainement, test).

    Le test contient les ventes de annee_test, l'entraînement celles des années précédentes.
    Les années suivantes, s'il y en a, ne sont dans aucun des deux : elles n'existent pas encore
    au moment où le modèle est censé prédire.
    """
    entrainement = df[df["annee"] < annee_test]
    test = df[df["annee"] == annee_test]
    return entrainement, test


def predire_par_groupe(entrainement, test, quantile=0.5):
    """Référence : prédit le prix_m2 de chaque vente du test par un quantile mesuré sur l'entraînement.

    Le quantile (0,5 = la médiane) est celui des ventes de la même commune et du même type de
    bien, calculé sur l'entraînement seulement. C'est ce que fait l'outil en production.
    Pour un couple commune/type absent de l'entraînement, on prend le quantile du type de bien.
    Renvoie une série alignée sur test.
    """
    par_couple = entrainement.groupby(["code_commune", "type_local"])["prix_m2"].quantile(quantile)
    par_type = entrainement.groupby("type_local")["prix_m2"].quantile(quantile)
    cles = pd.MultiIndex.from_frame(test[["code_commune", "type_local"]])
    prevu = pd.Series(par_couple.reindex(cles).to_numpy(), index=test.index)
    return prevu.fillna(test["type_local"].map(par_type))


def predire_par_mediane(entrainement, test):
    """Référence : la médiane du prix_m2 de la commune et du type de bien, mesurée sur l'entraînement."""
    return predire_par_groupe(entrainement, test, 0.5)


def entrainer(entrainement, variables, quantile=0.5):
    """Entraîne un modèle de prix_m2 sur les ventes d'entraînement et le renvoie.

    variables : les colonnes que le modèle peut utiliser (voir VARIABLES_A, B et C).
    quantile : 0,5 prédit la médiane ; 0,25 et 0,75 prédisent les bornes d'une fourchette.
    Le modèle renvoyé contient aussi la préparation des données : model.predict(ventes) accepte
    directement un tableau de ventes (les colonnes en trop sont ignorées).
    """
    categorielles = [v for v in variables if v in CATEGORIELLES]
    numeriques = [v for v in variables if v not in CATEGORIELLES]

    # Les catégories deviennent des numéros (0, 1, 2...). Une catégorie inconnue au moment de
    # prédire (une commune absente de l'entraînement) devient une case vide, que le modèle
    # sait traiter. Les colonnes numériques passent telles quelles, cases vides comprises.
    preparation = ColumnTransformer([
        ("categories", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), categorielles),
        ("nombres", "passthrough", numeriques),
    ])
    regresseur = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        categorical_features=list(range(len(categorielles))),  # les catégories sont les premières colonnes
        max_iter=300,
        random_state=0,
    )
    return Pipeline([("preparation", preparation), ("regresseur", regresseur)]).fit(
        entrainement[list(variables)], entrainement["prix_m2"]
    )


def mesurer_erreur(reel, prevu, surface):
    """Mesure l'écart entre les prix au m² réels et prédits.

    Renvoie : l'erreur absolue moyenne en €/m² (mae_m2), l'erreur relative médiane en % (la moitié
    des biens est estimée à mieux que cela), et l'erreur absolue moyenne sur le prix total
    en € (mae_prix, qui tient compte de la surface).
    """
    ecart = (prevu - reel).abs()
    return {
        "mae_m2": ecart.mean(),
        "erreur_mediane_pct": (ecart / reel).median() * 100,
        "mae_prix": (ecart * surface).mean(),
    }


def mesurer_fourchette(reel, bas, haut):
    """Mesure une fourchette de prix : [bas, haut] pour chaque vente.

    Renvoie la couverture (le % de ventes dont le vrai prix est dans la fourchette) et la largeur
    médiane de la fourchette en % de son milieu. Entre les 25e et 75e centiles, une fourchette bien
    calibrée couvre 50 % des ventes : plus bas, elle est trop optimiste ; plus haut, trop large.
    """
    dedans = (reel >= bas) & (reel <= haut)
    largeur = (haut - bas) / ((haut + bas) / 2)
    return {"couverture_pct": dedans.mean() * 100, "largeur_pct": largeur.median() * 100}
