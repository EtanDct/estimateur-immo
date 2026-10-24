"""Tests de modele.py : mesurer honnêtement, entraîner, enregistrer et estimer avec une adresse."""

import datetime
import re
import subprocess

import numpy as np
import pandas as pd
import pytest
from sklearn.neighbors import NearestNeighbors

from conftest import EN_MER, LILLE, LYON_1ER, LYON_3E, PARIS_1ER
from estimateur import modele
from estimateur.config import SURFACE_MAX, SURFACE_MIN
from estimateur.estimation import ParametreInvalide
from estimateur.modele import (
    NB_VOISINS,
    VARIABLES_COMMUNE,
    _verifier_adresse,
    charger_modeles,
    enregistrer_modeles,
    entrainer,
    entrainer_modeles,
    estimer_prix,
    mesurer_erreur,
    mesurer_fourchette,
    predire_par_groupe,
    separer_par_annee,
    tracabilite,
    zones_communes,
)
from estimateur.villes import regroupements

# --- la mesure : pas de triche ------------------------------------------------------------------

def test_separer_par_annee_ne_laisse_aucune_vente_de_test_dans_l_entrainement():
    ventes = pd.DataFrame({"annee": [2021, 2022, 2023, 2024, 2025, 2025, 2026]})
    entrainement, test = separer_par_annee(ventes, annee_test=2025)
    assert set(entrainement["annee"]) == {2021, 2022, 2023, 2024}
    assert set(test["annee"]) == {2025}
    assert 2026 not in set(entrainement["annee"]) | set(test["annee"])  # une année qui n'existe pas encore
    assert not set(entrainement.index) & set(test.index)


def test_predire_par_groupe_utilise_l_entrainement_seulement_et_se_replie_sur_le_type():
    entrainement = pd.DataFrame({
        "code_commune": ["A", "A", "A", "B"], "type_local": ["Maison"] * 4, "prix_m2": [100, 200, 300, 1000],
    })
    test = pd.DataFrame({"code_commune": ["A", "C"], "type_local": ["Maison", "Maison"], "prix_prive": [999_999, 999_999]})
    prevu = predire_par_groupe(entrainement, test)
    assert prevu.iloc[0] == 200                       # la médiane de la commune A
    assert prevu.iloc[1] == pd.Series([100, 200, 300, 1000]).median()  # commune C inconnue : médiane du type de bien
    assert list(prevu.index) == list(test.index)


def test_mesurer_erreur():
    reel = pd.Series([100.0, 200.0])
    prevu = pd.Series([110.0, 180.0])
    mesures = mesurer_erreur(reel, prevu, surface=pd.Series([10.0, 20.0]))
    assert mesures["mae_m2"] == 15
    assert mesures["erreur_mediane_pct"] == pytest.approx(10)
    assert mesures["mae_prix"] == 250  # (10 x 10 + 20 x 20) / 2


def test_mesurer_fourchette():
    reel = pd.Series([5.0, 15.0, 25.0])
    mesures = mesurer_fourchette(reel, bas=pd.Series([0.0, 10.0, 30.0]), haut=pd.Series([10.0, 20.0, 40.0]))
    assert mesures["couverture_pct"] == pytest.approx(200 / 3)  # les deux premières ventes sont dans leur fourchette
    assert mesures["largeur_pct"] == pytest.approx(100 * 10 / 15)  # médiane des largeurs relatives (2, 0,67 et 0,29)


def test_le_modele_apprend_la_structure_des_prix_et_sa_fourchette_est_calibree(ventes):
    entrainement, test = separer_par_annee(ventes)
    modele = entrainer(entrainement, VARIABLES_COMMUNE, 0.5)
    ecart_modele = (modele.predict(test) - test["prix_m2"]).abs().mean()
    ecart_constante = (entrainement["prix_m2"].median() - test["prix_m2"]).abs().mean()
    assert ecart_modele < 0.5 * ecart_constante

    bas = entrainer(entrainement, VARIABLES_COMMUNE, 0.25).predict(test)
    haut = entrainer(entrainement, VARIABLES_COMMUNE, 0.75).predict(test)
    couverture = mesurer_fourchette(test["prix_m2"], pd.Series(bas, index=test.index), pd.Series(haut, index=test.index))["couverture_pct"]
    assert 30 <= couverture <= 70  # une fourchette 25-75 couvre environ la moitié des ventes


def test_le_modele_sait_predire_une_commune_jamais_vue(ventes):
    modele = entrainer(ventes, VARIABLES_COMMUNE, 0.5)
    inconnue = pd.DataFrame([{"code_commune": "99999", "type_local": "Maison", "surface_reelle_bati": 100.0, "annee": 2025}])
    assert np.isfinite(modele.predict(inconnue)[0])


# --- les modèles finaux -------------------------------------------------------------------------

def test_les_modeles_gardent_de_quoi_controler_une_demande(modeles, ventes):
    assert {"commune", "adresse", "annee", "annees", "communes", "zones", "voisins", "noms", "enfants", "surfaces", "metriques"} <= set(modeles)
    assert set(modeles["commune"]) == set(modeles["adresse"]) == {0.25, 0.5, 0.75}
    assert modeles["annee"] == 2025
    assert modeles["annees"] == (2021, 2025)
    assert modeles["communes"] == sorted(ventes["code_commune"].unique())
    assert modeles["enfants"]["75056"] == [f"751{n:02d}" for n in range(1, 21)]
    assert modeles["noms"]["75056"] == "Paris"


def test_les_bornes_de_surface_viennent_des_ventes(modeles):
    # Les ventes factices vont de 20 à 120 m² (appartements) et de 70 à 220 m² (maisons).
    bas, haut = modeles["surfaces"]["Appartement"]
    assert 20 <= bas <= 22 and 118 <= haut <= 120
    bas, haut = modeles["surfaces"]["Maison"]
    assert 70 <= bas <= 72 and 218 <= haut <= 220


def test_les_bornes_de_surface_restent_dans_les_bornes_generales(ventes):
    # 2 % de biens minuscules et 2 % de biens gigantesques : les centiles tombent hors de 9 à 1 000 m².
    bizarres = ventes.copy()
    appartements = bizarres.index[bizarres["type_local"] == "Appartement"]
    bizarres.loc[appartements[:10], "surface_reelle_bati"] = 2.0
    bizarres.loc[appartements[10:20], "surface_reelle_bati"] = 5000.0
    bas, haut = entrainer_modeles(bizarres, regroupements())["surfaces"]["Appartement"]
    assert (bas, haut) == (SURFACE_MIN, SURFACE_MAX)


def test_zones_communes_ignore_un_regroupement_sans_ventes(ventes):
    zones = zones_communes(ventes[ventes["code_commune"] == "59350"], regroupements())
    assert set(zones) == {"59350"}  # ni « Paris » ni « Lyon » : aucune de leurs communes n'a de vente ici


def test_zones_communes_regroupe_les_arrondissements_dans_la_ville(ventes):
    zones = zones_communes(ventes, regroupements())
    lat_min, lat_max, lon_min, lon_max = zones["69123"]
    assert lat_min == min(zones["69381"][0], zones["69383"][0]) and lat_max == max(zones["69381"][1], zones["69383"][1])
    assert lon_min == min(zones["69381"][2], zones["69383"][2]) and lon_max == max(zones["69381"][3], zones["69383"][3])


def test_les_modeles_enregistres_donnent_les_memes_predictions(tmp_path, modeles):
    enregistrer_modeles(modeles, tmp_path)
    relus = charger_modeles(tmp_path)
    demande = pd.DataFrame([{
        "code_commune": "59350", "type_local": "Maison", "surface_reelle_bati": 100.0, "annee": 2025, "latitude": 50.63, "longitude": 3.06,
    }])
    for nom in ("commune", "adresse"):
        for quantile in (0.25, 0.5, 0.75):
            assert relus[nom][quantile].predict(demande)[0] == modeles[nom][quantile].predict(demande)[0]
    assert relus["surfaces"] == modeles["surfaces"]


def test_les_modeles_gardent_le_nombre_de_ventes_d_entrainement(modeles, ventes):
    assert modeles["nombre_ventes"] == len(ventes)


def test_la_tracabilite_donne_la_date_du_jour_et_le_commit_du_code():
    resultat = tracabilite()
    assert datetime.date.fromisoformat(resultat["entraine_le"]) == datetime.date.today()
    # Dans une copie du dépôt : un identifiant de commit, éventuellement marqué comme modifié. Sans Git : None.
    assert resultat["commit"] is None or re.fullmatch(r"[0-9a-f]{12}(\+modifie)?", resultat["commit"])


def _git_simule(monkeypatch, commit, etat):
    """Remplace l'appel à git : rev-parse répond commit, status répond etat."""
    def faux(arguments, **_):
        return subprocess.CompletedProcess(arguments, 0, stdout=commit if "rev-parse" in arguments else etat)

    monkeypatch.setattr(modele.subprocess, "run", faux)


def test_la_tracabilite_marque_un_code_modifie(monkeypatch):
    _git_simule(monkeypatch, "0123456789ab", "")
    assert tracabilite()["commit"] == "0123456789ab"
    _git_simule(monkeypatch, "0123456789ab", " M estimateur/modele.py")
    assert tracabilite()["commit"] == "0123456789ab+modifie"


@pytest.mark.parametrize("erreur", [FileNotFoundError("git"), subprocess.CalledProcessError(128, "git"), subprocess.TimeoutExpired("git", 10)])
def test_la_tracabilite_vaut_none_sans_git_utilisable(monkeypatch, erreur):
    def echoue(*_, **__):
        raise erreur

    monkeypatch.setattr(modele.subprocess, "run", echoue)
    assert tracabilite()["commit"] is None


def test_charger_modeles_renvoie_none_quand_le_fichier_n_existe_pas(tmp_path):
    assert charger_modeles(tmp_path) is None


# --- estimer_prix : quelle méthode, quelle fourchette --------------------------------------------

@pytest.mark.parametrize("commune", ["Lille", "Lyon 1er Arrondissement", "Paris 2e Arrondissement"])
@pytest.mark.parametrize("type_local", ["Appartement", "Maison"])
@pytest.mark.parametrize("position", [None, "centre"])
def test_la_fourchette_est_ordonnee_et_en_euros_entiers(prix, modeles, commune, type_local, position):
    centres = {"Lille": LILLE, "Lyon 1er Arrondissement": LYON_1ER, "Paris 2e Arrondissement": (48.868, 2.344)}
    latitude, longitude = centres[commune] if position else (None, None)
    surface = 100  # dans les bornes des deux types de bien
    resultat = estimer_prix(prix, modeles, commune, type_local, surface, latitude, longitude)
    assert resultat["prix_bas"] <= resultat["prix_median"] <= resultat["prix_haut"]
    assert all(isinstance(resultat[cle], int) for cle in ("prix_bas", "prix_median", "prix_haut", "prix_m2_median"))
    assert resultat["prix_median"] == pytest.approx(surface * resultat["prix_m2_median"], abs=surface / 2)
    assert resultat["methode"] == ("adresse" if position else "commune")
    assert resultat["repli"] is None


def test_le_prix_depend_de_la_commune(prix, modeles):
    paris = estimer_prix(prix, modeles, "Paris 2e Arrondissement", "Appartement", 60)
    lille = estimer_prix(prix, modeles, "Lille", "Appartement", 60)
    assert paris["prix_median"] > 2 * lille["prix_median"]  # 12 000 €/m² contre 3 300 dans les ventes factices


def test_une_ville_entiere_sans_adresse_est_estimee_par_la_mediane(prix, modeles):
    resultat = estimer_prix(prix, modeles, "Lyon", "Appartement", 60)
    assert resultat["methode"] == "mediane"


def test_une_ville_entiere_avec_une_adresse_de_la_ville_est_estimee_par_le_modele_d_adresse(prix, modeles):
    resultat = estimer_prix(prix, modeles, "Lyon", "Appartement", 60, *LYON_3E)
    assert resultat["methode"] == "adresse"


def test_le_repli_sur_la_ville_est_signale_et_utilise_les_medianes(prix, modeles):
    resultat = estimer_prix(prix, modeles, "Paris 1er Arrondissement", "Maison", 100)
    assert (resultat["methode"], resultat["repli"]) == ("mediane", "Paris")
    # Même avec une adresse valide, la commune manque de ventes : le modèle d'adresse n'est pas utilisé.
    avec_adresse = estimer_prix(prix, modeles, "Paris 1er Arrondissement", "Maison", 100, *PARIS_1ER)
    assert (avec_adresse["methode"], avec_adresse["repli"]) == ("mediane", "Paris")


def test_sans_modele_l_estimation_repose_sur_les_medianes(prix):
    resultat = estimer_prix(prix, None, "Lille", "Appartement", 60)
    assert resultat["methode"] == "mediane"
    assert resultat["prix_bas"] <= resultat["prix_median"] <= resultat["prix_haut"]
    assert estimer_prix(prix, None, "Lille", "Appartement", 60, *LILLE)["methode"] == "mediane"


# --- les surfaces refusées ----------------------------------------------------------------------

@pytest.mark.parametrize("type_local", ["Appartement", "Maison"])
def test_les_surfaces_hors_des_ventes_sont_refusees_bornes_incluses(prix, modeles, type_local):
    bas, haut = modeles["surfaces"][type_local]
    for surface in (bas, haut):
        assert estimer_prix(prix, modeles, "Lille", type_local, surface)["methode"] == "commune"
    for surface in (bas - 1, haut + 1):
        with pytest.raises(ParametreInvalide, match=f"entre {bas} et {haut} m² pour une estimation fiable"):
            estimer_prix(prix, modeles, "Lille", type_local, surface)


def test_le_message_de_surface_donne_la_valeur_recue_sans_notation_scientifique(prix, modeles):
    with pytest.raises(ParametreInvalide, match=r"\(reçu : 150\)"):
        estimer_prix(prix, modeles, "Lille", "Appartement", 150)


# --- les coordonnées -----------------------------------------------------------------------------

def test_une_seule_coordonnee_est_refusee(prix, modeles):
    for latitude, longitude in ((50.6, None), (None, 3.0)):
        with pytest.raises(ParametreInvalide, match="vont ensemble"):
            estimer_prix(prix, modeles, "Lille", "Appartement", 60, latitude, longitude)


@pytest.mark.parametrize("latitude, longitude", [(float("nan"), 3.0), (50.6, float("inf")), (float("-inf"), float("nan"))])
def test_des_coordonnees_qui_ne_sont_pas_des_nombres_sont_refusees(prix, modeles, latitude, longitude):
    with pytest.raises(ParametreInvalide, match="doivent être des nombres"):
        estimer_prix(prix, modeles, "Lille", "Appartement", 60, latitude, longitude)


@pytest.mark.parametrize("latitude, longitude", [(91, 3.0), (-91, 3.0), (50.6, 181), (50.6, -181), (200, 999)])
def test_des_coordonnees_hors_du_globe_sont_refusees(prix, modeles, latitude, longitude):
    with pytest.raises(ParametreInvalide, match="Coordonnées hors limites"):
        estimer_prix(prix, modeles, "Lille", "Appartement", 60, latitude, longitude)


# --- le rattachement d'une adresse à une commune ------------------------------------------------

def test_une_adresse_d_un_autre_arrondissement_est_refusee_avec_le_nom_de_celui_ou_elle_se_trouve(prix, modeles):
    with pytest.raises(ParametreInvalide, match="Cette adresse se trouve à Lyon 3e Arrondissement, pas à Lyon 1er Arrondissement"):
        estimer_prix(prix, modeles, "Lyon 1er Arrondissement", "Appartement", 60, *LYON_3E)


def test_une_adresse_d_une_autre_ville_est_refusee(prix, modeles):
    with pytest.raises(ParametreInvalide, match="Cette adresse se trouve à Lyon.*pas à Lille"):
        estimer_prix(prix, modeles, "Lille", "Appartement", 60, *LYON_1ER)
    with pytest.raises(ParametreInvalide, match="pas à Paris"):
        estimer_prix(prix, modeles, "Paris", "Appartement", 60, *LYON_1ER)


def test_une_adresse_de_la_ville_entiere_est_acceptee_dans_n_importe_lequel_de_ses_arrondissements(prix, modeles):
    for position in (LYON_1ER, LYON_3E):
        assert estimer_prix(prix, modeles, "Lyon", "Appartement", 60, *position)["methode"] == "adresse"
    assert estimer_prix(prix, modeles, "Paris", "Appartement", 60, *PARIS_1ER)["methode"] == "adresse"


def test_une_position_loin_de_toute_vente_est_hors_des_villes_couvertes(prix, modeles):
    with pytest.raises(ParametreInvalide, match="en dehors des villes couvertes"):
        estimer_prix(prix, modeles, "Lille", "Appartement", 60, *EN_MER)


def modeles_a_deux_communes(votes_pour_b):
    """Des modèles réduits à un index de 10 ventes : (10 - votes_pour_b) dans la commune A, le reste dans B."""
    positions = np.array([[0.0010 * i, 0.0] for i in range(10)])
    etiquettes = np.array([1] * votes_pour_b + [0] * (10 - votes_pour_b), dtype=np.int16)
    assert NB_VOISINS == 10
    return {
        "voisins": {"index": NearestNeighbors(n_neighbors=NB_VOISINS).fit(positions), "etiquettes": etiquettes},
        "communes": ["A", "B"], "noms": {"A": "Commune A", "B": "Commune B"}, "enfants": {}, "zones": {},
    }


def test_une_adresse_est_acceptee_si_deux_ventes_voisines_sont_dans_la_commune_demandee():
    modeles = modeles_a_deux_communes(votes_pour_b=2)
    _verifier_adresse(modeles, "B", "Commune B", 0.0, 0.0)  # aucune exception : 2 voisins sur 10, c'est assez
    _verifier_adresse(modeles, "A", "Commune A", 0.0, 0.0)


def test_une_adresse_est_refusee_si_une_seule_vente_voisine_est_dans_la_commune_demandee():
    modeles = modeles_a_deux_communes(votes_pour_b=1)
    with pytest.raises(ParametreInvalide, match="Cette adresse se trouve à Commune A, pas à Commune B"):
        _verifier_adresse(modeles, "B", "Commune B", 0.0, 0.0)


def test_un_ancien_fichier_de_modeles_sans_index_de_voisins_controle_par_zone(prix, modeles):
    ancien = {cle: valeur for cle, valeur in modeles.items() if cle != "voisins"}
    assert estimer_prix(prix, ancien, "Lille", "Appartement", 60, *LILLE)["methode"] == "adresse"
    with pytest.raises(ParametreInvalide, match="ne se trouve pas à Lille"):
        estimer_prix(prix, ancien, "Lille", "Appartement", 60, *LYON_1ER)
