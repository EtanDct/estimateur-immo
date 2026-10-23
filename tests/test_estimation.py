"""Tests de estimation.py : vérifier une demande et estimer par médiane."""

import pandas as pd
import pytest

from estimateur.estimation import (
    BienIntrouvable,
    ParametreInvalide,
    _normaliser,
    chercher_ligne,
    chercher_ligne_avec_repli,
    classer_communes,
    estimer,
    noms_communes,
    zone_couverte,
)


def statistiques(*lignes):
    """Un tableau de statistiques à la main : (code, nom, type, médiane, nombre de ventes[, ville])."""
    return pd.DataFrame([
        {
            "code_commune": code, "nom_commune": nom, "type_local": type_local, "mediane": mediane, "quartile_1": mediane - 500,
            "quartile_3": mediane + 500, "nombre_ventes": n, "annee_min": 2024, "annee_max": 2025, "ville": reste[0] if reste else None,
        }
        for code, nom, type_local, mediane, n, *reste in lignes
    ])


# --- les noms ------------------------------------------------------------------------------------

@pytest.mark.parametrize("ecrit, normalise", [
    ("Épernay", "epernay"),
    ("Saint-Martin-d'Ablois", "saint martin d ablois"),
    ("Saint-Martin-d’Ablois", "saint martin d ablois"),
    ("  Lyon   3e  Arrondissement ", "lyon 3e arrondissement"),
    ("Cœur", "coeur"),
    ("LILLE", "lille"),
])
def test_normaliser(ecrit, normalise):
    assert _normaliser(ecrit) == normalise


def test_noms_communes_est_trie_sans_tenir_compte_des_accents():
    prix = statistiques(("1", "Fontaine", "Maison", 1, 10), ("2", "Épernay", "Maison", 1, 10), ("3", "Fontaine", "Appartement", 1, 10))
    assert noms_communes(prix) == ["Épernay", "Fontaine"]


# --- chercher_ligne ------------------------------------------------------------------------------

def test_chercher_ligne_ignore_la_casse_les_accents_et_les_tirets(prix):
    ligne = chercher_ligne(prix, "lyon 3E arrondissement", "appartement", 60)
    assert ligne["nom_commune"] == "Lyon 3e Arrondissement"
    assert ligne["type_local"] == "Appartement"


@pytest.mark.parametrize("surface", [9, 60, 1000])
def test_chercher_ligne_accepte_les_surfaces_de_9_a_1000(prix, surface):
    assert chercher_ligne(prix, "Lille", "Maison", surface)["code_commune"] == "59350"


@pytest.mark.parametrize("surface", [0, -5, 8.99, 1000.01, float("nan"), float("inf"), float("-inf")])
def test_chercher_ligne_refuse_les_surfaces_hors_de_9_a_1000(prix, surface):
    with pytest.raises(ParametreInvalide, match="entre 9 et 1000"):
        chercher_ligne(prix, "Lille", "Maison", surface)


def test_chercher_ligne_refuse_un_type_de_bien_inconnu(prix):
    with pytest.raises(ParametreInvalide, match="Type de bien inconnu.*Maison, Appartement"):
        chercher_ligne(prix, "Lille", "Château", 100)


def test_chercher_ligne_refuse_une_commune_inconnue_avec_une_erreur_404(prix):
    with pytest.raises(BienIntrouvable, match="Commune introuvable"):
        chercher_ligne(prix, "Atlantide", "Maison", 100)


@pytest.mark.parametrize("texte", ["A" * 101, "Lille\x00", "Lille\n", "Lil\x1fle"])
def test_chercher_ligne_refuse_un_texte_trop_long_ou_avec_des_caracteres_de_controle(prix, texte):
    with pytest.raises(ParametreInvalide, match="trop long ou contient des caractères invalides"):
        chercher_ligne(prix, texte, "Maison", 100)
    with pytest.raises(ParametreInvalide, match="type_local"):
        chercher_ligne(prix, "Lille", texte, 100)


def test_chercher_ligne_refuse_une_commune_avec_moins_de_10_ventes(prix):
    with pytest.raises(BienIntrouvable, match=r"Seulement 2 vente\(s\) de maison à Paris 1er Arrondissement.*au moins 10"):
        chercher_ligne(prix, "Paris 1er Arrondissement", "Maison", 100)


def test_chercher_ligne_le_nombre_minimum_de_ventes_se_regle(prix):
    assert chercher_ligne(prix, "Paris 1er Arrondissement", "Maison", 100, ventes_min=2)["nombre_ventes"] == 2


def test_chercher_ligne_refuse_deux_communes_du_meme_nom():
    prix = statistiques(("1", "Saint-Denis", "Maison", 1, 10), ("2", "Saint-Denis", "Maison", 1, 10))
    with pytest.raises(ParametreInvalide, match="Plusieurs communes s'appellent Saint-Denis"):
        chercher_ligne(prix, "Saint-Denis", "Maison", 100)


def test_chercher_ligne_aucune_vente_de_ce_type_dans_la_commune():
    prix = statistiques(("1", "Lille", "Appartement", 1, 10))
    with pytest.raises(BienIntrouvable, match="Aucune vente exploitable de maison à Lille"):
        chercher_ligne(prix, "Lille", "Maison", 100)


def test_les_messages_d_erreur_tronquent_le_texte_recu(prix):
    with pytest.raises(BienIntrouvable) as erreur:
        chercher_ligne(prix, "B" * 90, "Maison", 100)
    assert "B" * 60 + "…" in str(erreur.value)
    assert "B" * 61 not in str(erreur.value)


def test_les_deux_erreurs_sont_des_value_error(prix):
    with pytest.raises(ValueError):
        chercher_ligne(prix, "Atlantide", "Maison", 100)
    with pytest.raises(ValueError):
        chercher_ligne(prix, "Lille", "Maison", 0)


# --- le repli sur la ville ----------------------------------------------------------------------

def test_sans_repli_quand_la_commune_a_assez_de_ventes(prix):
    ligne, repli = chercher_ligne_avec_repli(prix, "Lyon 3e Arrondissement", "Maison", 100)
    assert repli is None
    assert ligne["code_commune_demandee"] == "69383"


def test_repli_sur_la_ville_quand_la_commune_manque_de_ventes(prix):
    ligne, repli = chercher_ligne_avec_repli(prix, "Paris 1er Arrondissement", "Maison", 100)
    assert repli == "Paris"
    assert ligne["nom_commune"] == "Paris 1er Arrondissement"  # la commune demandée, pas la ville
    assert ligne["code_commune_demandee"] == "75101"
    assert ligne["code_commune"] == "75056"                    # mais les statistiques sont celles de la ville
    assert ligne["nombre_ventes"] >= 10


def test_pas_de_repli_pour_une_ville_sans_arrondissements(prix):
    prix = prix[~((prix["nom_commune"] == "Lille") & (prix["type_local"] == "Maison"))]
    with pytest.raises(BienIntrouvable):
        chercher_ligne_avec_repli(prix, "Lille", "Maison", 100)


def test_pas_de_repli_pour_une_commune_inconnue(prix):
    with pytest.raises(BienIntrouvable, match="Commune introuvable"):
        chercher_ligne_avec_repli(prix, "Atlantide", "Maison", 100)


def test_quand_la_ville_manque_aussi_de_ventes_l_erreur_d_origine_est_gardee():
    prix = statistiques(
        ("75101", "Paris 1er Arrondissement", "Maison", 1, 3, "Paris"),
        ("75056", "Paris", "Maison", 1, 5, "Paris"),
    )
    with pytest.raises(BienIntrouvable, match="Paris 1er Arrondissement"):
        chercher_ligne_avec_repli(prix, "Paris 1er Arrondissement", "Maison", 100)


def test_pas_de_repli_sans_colonne_ville():
    prix = statistiques(("75101", "Paris 1er Arrondissement", "Maison", 1, 3)).drop(columns="ville")
    with pytest.raises(BienIntrouvable):
        chercher_ligne_avec_repli(prix, "Paris 1er Arrondissement", "Maison", 100)


# --- estimer --------------------------------------------------------------------------------------

def test_estimer_multiplie_la_surface_par_les_quartiles_et_arrondit_a_l_euro():
    prix = statistiques(("59350", "Lille", "Appartement", 3000, 20))  # quartiles 2500 et 3500
    resultat = estimer(prix, "Lille", "Appartement", 50.5)
    assert resultat["prix_m2_median"] == 3000
    assert (resultat["prix_bas"], resultat["prix_median"], resultat["prix_haut"]) == (126250, 151500, 176750)
    assert all(isinstance(resultat[cle], int) for cle in ("prix_bas", "prix_median", "prix_haut", "prix_m2_median", "nombre_ventes"))
    assert (resultat["commune"], resultat["type_local"], resultat["surface"], resultat["repli"]) == ("Lille", "Appartement", 50.5, None)
    assert (resultat["annee_min"], resultat["annee_max"], resultat["nombre_ventes"]) == (2024, 2025, 20)


def test_estimer_indique_la_ville_de_repli(prix):
    resultat = estimer(prix, "Paris 1er Arrondissement", "Maison", 100)
    assert resultat["repli"] == "Paris"
    assert resultat["commune"] == "Paris 1er Arrondissement"
    assert resultat["prix_bas"] <= resultat["prix_median"] <= resultat["prix_haut"]


# --- zone couverte et classement -----------------------------------------------------------------

def test_zone_couverte_deduit_tout_du_tableau(prix):
    zone = zone_couverte(prix)
    assert zone["departements"] == ["59", "69", "75"]
    assert (zone["annee_min"], zone["annee_max"]) == (2024, 2025)
    assert zone["nombre_communes"] == prix["code_commune"].nunique()
    assert zone["villes"] == ["Lille", "Lyon", "Paris"]


@pytest.mark.parametrize("code, departement", [("51454", "51"), ("2A004", "2A"), ("97105", "971"), ("75101", "75")])
def test_zone_couverte_deduit_le_departement_du_code_de_commune(code, departement):
    prix = statistiques((code, "X", "Maison", 1, 10))
    assert zone_couverte(prix)["departements"] == [departement]


def test_classer_communes_va_de_la_plus_chere_a_la_moins_chere_et_ecarte_les_petits_echantillons():
    prix = statistiques(
        ("1", "Pas cher", "Maison", 1000, 50), ("2", "Cher", "Maison", 5000, 50),
        ("3", "Trop peu de ventes", "Maison", 9000, 9), ("4", "Autre type", "Appartement", 7000, 50),
    )
    assert list(classer_communes(prix, "Maison")["nom_commune"]) == ["Cher", "Pas cher"]
