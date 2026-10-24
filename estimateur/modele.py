"""Modèle de prix au m² : séparation par année, référence, entraînement et mesure de l'erreur.

Comme donnees.py, ce module n'affiche rien : la commande evaluer l'appelle et présente les résultats.
"""

import math
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from .config import DOSSIER_VILLES, SURFACE_MAX, SURFACE_MIN
from .estimation import ParametreInvalide, chercher_ligne_avec_repli, estimer

# L'année de test : on entraîne sur les années d'avant, on teste sur celle-ci, comme en vrai
# (le modèle prédit l'avenir à partir du passé).
ANNEE_TEST = 2025

# Les colonnes qui sont des catégories (le reste est numérique). Un arbre de décision les
# traite comme des étiquettes, sans ordre : la commune 75110 n'est pas « plus grande » que 75101.
CATEGORIELLES = ("code_commune", "type_local")

# Les variables que chaque modèle a le droit d'utiliser. L'année de la vente en fait partie : les
# prix bougent, le modèle apprend à donner plus de poids aux années récentes, et à la prédiction on
# lui donne la dernière année connue.
VARIABLES_COMMUNE = ("code_commune", "type_local", "surface_reelle_bati", "annee")  # le formulaire actuel
VARIABLES_PIECES = VARIABLES_COMMUNE + ("nombre_pieces_principales", "surface_terrain")  # + pièces et terrain
VARIABLES_ADRESSE = ("type_local", "surface_reelle_bati", "annee", "latitude", "longitude")  # + position du bien
VARIABLES_COMPLET = VARIABLES_PIECES + ("latitude", "longitude")  # tout (plafond de ce qu'on sait faire)

# Le modèle entraîné est enregistré dans ce fichier, à côté des statistiques par commune.
FICHIER_MODELES = "modeles.joblib"

# Une adresse est rattachée à la commune de ses ventes voisines. On regarde les NB_VOISINS ventes les
# plus proches : l'adresse est acceptée si au moins VOTES_MIN d'entre elles sont dans la commune
# demandée (une adresse en bordure d'arrondissement a des voisins des deux côtés), et refusée si la
# vente la plus proche est à plus de DISTANCE_MAX_DEGRES (environ 1,5 km), c'est-à-dire hors des villes.
NB_VOISINS = 10
VOTES_MIN = 2
DISTANCE_MAX_DEGRES = 0.0135

# Un degré de longitude est plus court qu'un degré de latitude (de cos(latitude) : environ 0,69 à 46° N).
# On multiplie la longitude par ce facteur pour que les distances en « degrés » soient comparables.
COS_LATITUDE = 0.69

# Les surfaces refusées sont celles hors de ce que les ventes ont montré : entre ces deux centiles.
# Au-delà, les ventes sont trop rares pour que le modèle y soit fiable : à Lille, le prix au m² d'un
# appartement saute de 3 825 € (200 m²) à 4 314 € (250 m²) alors que les ventes ne le justifient pas.
CENTILES_SURFACE = (0.005, 0.995)


def charger_ventes(dossier=DOSSIER_VILLES):
    """Lit <dossier>/ventes_propres.csv, le fichier écrit par la commande construire."""
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


def zones_communes(ventes, regroupements=None):
    """Calcule, pour chaque commune, la zone (latitude et longitude min et max) de ses ventes.

    regroupements : comme pour donnees.regrouper_communes(), pour que « Paris » ait aussi sa zone.
    Renvoie {code_commune: (lat_min, lat_max, lon_min, lon_max)}.
    """
    zones = {}
    for code, groupe in ventes.dropna(subset=["latitude", "longitude"]).groupby("code_commune"):
        zones[code] = (groupe["latitude"].min(), groupe["latitude"].max(), groupe["longitude"].min(), groupe["longitude"].max())
    for code, (_, codes) in (regroupements or {}).items():
        morceaux = [zones[c] for c in codes if c in zones]
        if not morceaux:  # aucune vente dans les communes de ce regroupement : pas de zone
            continue
        zones[code] = (min(z[0] for z in morceaux), max(z[1] for z in morceaux), min(z[2] for z in morceaux), max(z[3] for z in morceaux))
    return zones


def _projeter(latitude, longitude):
    """Met une position en « degrés comparables » : la longitude est raccourcie par COS_LATITUDE."""
    return [latitude, longitude * COS_LATITUDE]


def entrainer_modeles(ventes, regroupements=None, metriques=None):
    """Entraîne les modèles finaux sur toutes les ventes et renvoie ce qu'il faut pour les utiliser.

    Deux modèles, chacun en trois exemplaires (25e centile, médiane, 75e centile) :
    « commune » (commune, type, surface, année) et « adresse » (type, surface, année, position).
    Le résultat garde aussi de quoi contrôler une demande : les surfaces observées par type de bien,
    et un index des positions des ventes pour retrouver la commune d'une adresse.
    metriques : les mesures de la commande evaluer, gardées avec les modèles pour être affichées.
    """
    annee = int(ventes["annee"].max())
    regroupements = regroupements or {}
    communes = sorted(ventes["code_commune"].unique())

    avec_position = ventes.dropna(subset=["latitude", "longitude"])
    index_des_communes = {code: i for i, code in enumerate(communes)}
    positions = np.array([_projeter(la, lo) for la, lo in zip(avec_position["latitude"], avec_position["longitude"], strict=True)])
    voisins = {
        "index": NearestNeighbors(n_neighbors=NB_VOISINS, algorithm="kd_tree").fit(positions),
        "etiquettes": avec_position["code_commune"].map(index_des_communes).to_numpy(dtype=np.int16),
    }

    noms = ventes.drop_duplicates("code_commune").set_index("code_commune")["nom_commune"].to_dict()
    noms.update({code: nom for code, (nom, _) in regroupements.items()})

    bas, haut = CENTILES_SURFACE
    surfaces = {
        type_local: (
            max(SURFACE_MIN, math.floor(groupe["surface_reelle_bati"].quantile(bas))),
            min(SURFACE_MAX, math.ceil(groupe["surface_reelle_bati"].quantile(haut))),
        )
        for type_local, groupe in ventes.groupby("type_local")
    }

    return {
        "commune": {q: entrainer(ventes, VARIABLES_COMMUNE, q) for q in (0.25, 0.5, 0.75)},
        "adresse": {q: entrainer(ventes, VARIABLES_ADRESSE, q) for q in (0.25, 0.5, 0.75)},
        "annee": annee,
        "annees": (int(ventes["annee"].min()), annee),
        "nombre_ventes": len(ventes),
        "communes": communes,
        "zones": zones_communes(ventes, regroupements),
        "voisins": voisins,
        "noms": noms,
        "enfants": {code: list(codes) for code, (_, codes) in regroupements.items()},
        "surfaces": surfaces,
        "metriques": metriques or {},
    }


def tracabilite():
    """Date du jour et commit du code qui entraîne : de quoi savoir plus tard d'où vient un fichier de modèles.

    Le commit est suivi de « +modifie » si des fichiers suivis par Git ont des modifications non
    enregistrées : le code qui a entraîné n'est alors pas exactement ce commit. Sans Git, il vaut None.
    """

    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=10, check=True).stdout.strip()

    try:
        commit = git("rev-parse", "--short=12", "HEAD")
        if git("status", "--porcelain", "--untracked-files=no"):
            commit += "+modifie"
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"entraine_le": date.today().isoformat(), "commit": commit}


def enregistrer_modeles(modeles, dossier=DOSSIER_VILLES):
    """Écrit les modèles dans <dossier>/modeles.joblib."""
    joblib.dump(modeles, Path(dossier) / FICHIER_MODELES, compress=3)


def charger_modeles(dossier=DOSSIER_VILLES):
    """Lit <dossier>/modeles.joblib. Renvoie None si le fichier n'existe pas.

    Le fichier est lu avec pickle (via joblib), qui peut exécuter du code : ne charger que
    un fichier produit par la commande modeliser et déposé par soi-même sur le serveur.
    """
    chemin = Path(dossier) / FICHIER_MODELES
    return joblib.load(chemin) if chemin.exists() else None


def _verifier_coordonnees(latitude, longitude):
    """Refuse des coordonnées qui ne sont pas des nombres, ou hors des limites du globe."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ParametreInvalide("La latitude et la longitude doivent être des nombres.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ParametreInvalide(
            "Coordonnées hors limites : la latitude doit être entre -90 et 90 et la longitude entre -180 et 180 "
            f"(reçu : {latitude:.6g}, {longitude:.6g})."
        )


def _verifier_adresse(modeles, code, nom, latitude, longitude):
    """Vérifie que la position se trouve bien dans la commune demandée (arrondissement compris).

    La commune d'une position est celle de ses ventes voisines (voir NB_VOISINS). Pour une ville
    découpée en arrondissements (« Paris »), les arrondissements comptent comme la ville.
    """
    voisins = modeles.get("voisins")
    if voisins is None:  # fichier de modèle d'une ancienne version : contrôle par zone, moins précis
        zone = modeles["zones"].get(code)
        marge = 0.03
        if zone and not (zone[0] - marge <= latitude <= zone[1] + marge and zone[2] - marge <= longitude <= zone[3] + marge):
            raise ParametreInvalide(f"Cette adresse ne se trouve pas à {nom}.")
        return

    distances, indices = voisins["index"].kneighbors([_projeter(latitude, longitude)])
    if distances[0][0] > DISTANCE_MAX_DEGRES:
        raise ParametreInvalide("Cette position est en dehors des villes couvertes.")
    codes_voisins = [modeles["communes"][i] for i in voisins["etiquettes"][indices[0]]]
    acceptes = {code, *modeles.get("enfants", {}).get(code, [])}
    if sum(c in acceptes for c in codes_voisins) >= VOTES_MIN:
        return
    ou = modeles.get("noms", {}).get(Counter(codes_voisins).most_common(1)[0][0], "une autre commune")
    raise ParametreInvalide(f"Cette adresse se trouve à {ou}, pas à {nom}.")


def _verifier_surface(modeles, type_local, surface):
    """Refuse une surface que le modèle n'a jamais vue dans les ventes de ce type de bien."""
    bornes = modeles.get("surfaces", {}).get(type_local)
    if bornes and not bornes[0] <= surface <= bornes[1]:
        bien = "un appartement" if type_local == "Appartement" else "une maison"
        raise ParametreInvalide(
            f"La surface d'{bien} doit être comprise entre {bornes[0]} et {bornes[1]} m² "
            f"pour une estimation fiable (reçu : {surface:.10g})."
        )


def estimer_prix(prix, modeles, commune, type_local, surface, latitude=None, longitude=None):
    """Estime une fourchette de prix avec le meilleur modèle disponible pour la demande.

    - latitude et longitude donnés (l'adresse du bien) : le modèle « adresse », méthode "adresse".
    - sinon, une commune que le modèle connaît : le modèle « commune », méthode "commune".
    - sinon (« Paris » en entier, une commune qui manque de ventes de ce type de bien, ou pas de
      modèle) : les médianes et quartiles de estimation.estimer(), méthode "mediane".
    Renvoie le même dictionnaire que estimation.estimer(), plus la clé methode. Les ventes comptées
    (nombre_ventes, annee_min, annee_max) sont celles des statistiques de la commune ; le champ repli
    nomme la ville dont les statistiques remplacent celles d'une commune qui manque de ventes.
    Lève les mêmes ValueError que estimation.estimer(), et ParametreInvalide si une seule des deux
    coordonnées est donnée, si elles sont invalides, si l'adresse n'est pas dans la commune ou si la
    surface sort de ce que les ventes ont montré.
    """
    if (latitude is None) != (longitude is None):
        raise ParametreInvalide("La latitude et la longitude vont ensemble : donner les deux ou aucune.")

    ligne, repli = chercher_ligne_avec_repli(prix, commune, type_local, surface)
    code = ligne["code_commune_demandee"]

    if latitude is not None:
        _verifier_coordonnees(latitude, longitude)
        if modeles is not None:
            _verifier_adresse(modeles, code, ligne["nom_commune"], latitude, longitude)

    # Sans modèle, ou si la commune manque de ventes (on se replie alors sur la médiane de la ville),
    # ou pour une ville entière sans adresse : les statistiques de la commune.
    if modeles is None or repli is not None or (latitude is None and code not in modeles["communes"]):
        return {**estimer(prix, commune, type_local, surface), "methode": "mediane"}

    _verifier_surface(modeles, ligne["type_local"], surface)
    methode = "adresse" if latitude is not None else "commune"
    demande = pd.DataFrame([{
        "code_commune": code, "type_local": ligne["type_local"], "surface_reelle_bati": surface,
        "annee": modeles["annee"], "latitude": latitude, "longitude": longitude,
    }])
    # Trois prédictions indépendantes peuvent se croiser (le 25e centile au-dessus de la médiane) :
    # on les remet dans l'ordre.
    bas, milieu, haut = sorted(float(modeles[methode][q].predict(demande)[0]) for q in (0.25, 0.5, 0.75))
    return {
        "commune": ligne["nom_commune"],
        "type_local": ligne["type_local"],
        "surface": surface,
        "nombre_ventes": int(ligne["nombre_ventes"]),
        "annee_min": int(ligne["annee_min"]),
        "annee_max": int(ligne["annee_max"]),
        "prix_m2_median": round(milieu),
        "prix_bas": round(surface * bas),
        "prix_median": round(surface * milieu),
        "prix_haut": round(surface * haut),
        "repli": None,
        "methode": methode,
    }
