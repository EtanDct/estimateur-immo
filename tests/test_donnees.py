"""Tests de donnees.py : charger, nettoyer et agréger les ventes."""

import gzip
import logging
import urllib.error

import pandas as pd
import pytest

from estimateur import donnees
from estimateur.donnees import (
    charger,
    charger_prix_communes,
    nettoyer,
    prix_par_commune,
    regrouper_communes,
    telecharger,
)


def vente(id_mutation, valeur=300_000, surface=100, type_local="Appartement", nature="Vente", commune="59350", annee=2025):
    """Une ligne de DVF : par défaut, une vente valide à 3 000 €/m²."""
    return {
        "id_mutation": id_mutation, "type_local": type_local, "nature_mutation": nature, "valeur_fonciere": valeur,
        "surface_reelle_bati": surface, "code_commune": commune, "annee": annee,
    }


def nettoyees(*lignes, **options):
    """Nettoie ces lignes et renvoie les id_mutation qui restent."""
    return list(nettoyer(pd.DataFrame(lignes), **options)["id_mutation"])


# --- nettoyer : une étape à la fois ---------------------------------------------------------------

def test_une_vente_valide_est_gardee_avec_son_prix_au_m2():
    resultat = nettoyer(pd.DataFrame([vente("a", valeur=300_000, surface=100)]))
    assert list(resultat["id_mutation"]) == ["a"]
    assert resultat.loc[0, "prix_m2"] == 3000


def test_etape_1_seuls_les_maisons_et_les_appartements_sont_gardes():
    gardees = nettoyees(
        vente("a"), vente("b", type_local="Maison"),
        vente("c", type_local="Dépendance"), vente("d", type_local="Local industriel. commercial ou assimilé"),
        vente("e", type_local=None),
    )
    assert gardees == ["a", "b"]


@pytest.mark.parametrize("nature", ["Echange", "Adjudication", "Vente en l'état futur d'achèvement", "Vente terrain à bâtir", "Expropriation"])
def test_etape_2_seules_les_ventes_classiques_sont_gardees(nature):
    assert nettoyees(vente("a"), vente("b", nature=nature)) == ["a"]


def test_etape_3_prix_et_surface_doivent_etre_strictement_positifs():
    gardees = nettoyees(
        vente("a"), vente("prix_nul", valeur=0), vente("prix_negatif", valeur=-5), vente("prix_vide", valeur=None),
        vente("surface_nulle", surface=0), vente("surface_vide", surface=None),
    )
    assert gardees == ["a"]


def test_etape_4_une_vente_de_deux_logements_est_retiree_en_entier():
    # Le prix total est répété sur chaque ligne : on ne sait pas quel prix revient à quel logement.
    gardees = nettoyees(vente("double"), vente("double"), vente("seule"))
    assert gardees == ["seule"]


def test_etape_4_une_maison_vendue_avec_un_garage_reste_une_vente_a_un_logement():
    # Le garage disparaît à l'étape 1, avant le comptage des lignes par vente.
    gardees = nettoyees(vente("a", type_local="Maison"), vente("a", type_local="Dépendance"))
    assert gardees == ["a"]


def test_etape_5_les_seuils_de_prix_au_m2_sont_inclus():
    gardees = nettoyees(
        vente("sous", valeur=29_900, surface=100),     # 299 €/m²
        vente("bas", valeur=30_000, surface=100),      # 300 €/m² : le seuil
        vente("haut", valeur=1_000_000, surface=100),  # 10 000 €/m² : le seuil
        vente("sur", valeur=1_000_100, surface=100),   # 10 001 €/m²
    )
    assert gardees == ["bas", "haut"]


def test_etape_5_les_seuils_se_reglent():
    gardees = nettoyees(vente("a", valeur=2_000_000, surface=100), prix_m2_max=50_000)
    assert gardees == ["a"]


def test_etape_6_une_vente_trop_eloignee_de_la_mediane_de_sa_commune_est_retiree():
    ventes = [vente(f"v{i}", valeur=300_000 + 1000 * i) for i in range(9)]  # autour de 3 000 €/m²
    ventes.append(vente("trop_chere", valeur=1_000_000))                    # 10 000 €/m², plus de 3 x la médiane
    ventes.append(vente("trop_bon_marche", valeur=90_000))                  # 900 €/m², moins de la médiane / 3
    assert "trop_chere" in nettoyees(*ventes)
    gardees = nettoyees(*ventes, ecart_median=3)
    assert "trop_chere" not in gardees and "trop_bon_marche" not in gardees
    assert len(gardees) == 9


def test_etape_6_la_mediane_est_celle_de_la_commune_et_du_type_de_bien():
    # 12 000 €/m² est normal à Paris, aberrant à Lille : chaque commune a sa propre médiane. Avec une
    # médiane commune aux deux (12 000 €/m²), les ventes de Lille à 3 000 €/m² seraient retirées.
    lille = [vente(f"l{i}", valeur=300_000) for i in range(4)]
    paris = [vente(f"p{i}", valeur=1_200_000, commune="75101") for i in range(6)]
    assert len(nettoyees(*lille, *paris, prix_m2_max=50_000, ecart_median=3)) == 10


def test_nettoyer_ne_modifie_pas_le_tableau_d_origine():
    brut = pd.DataFrame([vente("a"), vente("b", type_local="Dépendance")])
    nettoyer(brut)
    assert len(brut) == 2
    assert "prix_m2" not in brut.columns


def test_nettoyer_renumerote_les_lignes():
    resultat = nettoyer(pd.DataFrame([vente("a", type_local="Dépendance"), vente("b"), vente("c")]))
    assert list(resultat.index) == [0, 1]


def test_nettoyer_note_dans_le_journal_ce_que_retire_chaque_etape(caplog):
    with caplog.at_level(logging.INFO, logger=donnees.journal.name):
        nettoyer(pd.DataFrame([vente("a"), vente("b", type_local="Dépendance")]))
    assert any("1. Maisons et appartements : 1 lignes retirées, il en reste 1" in message for message in caplog.messages)


# --- prix_par_commune, regrouper_communes ---------------------------------------------------------

def test_prix_par_commune_calcule_mediane_quartiles_et_annees():
    ventes = pd.DataFrame({
        "code_commune": "59350", "nom_commune": "Lille", "type_local": "Appartement",
        "prix_m2": [1000, 2000, 3000, 4000, 5000], "annee": [2024, 2024, 2025, 2025, 2025],
    })
    ligne = prix_par_commune(ventes).iloc[0]
    assert (ligne["mediane"], ligne["quartile_1"], ligne["quartile_3"]) == (3000, 2000, 4000)
    assert (ligne["nombre_ventes"], ligne["annee_min"], ligne["annee_max"]) == (5, 2024, 2025)


def test_prix_par_commune_a_une_ligne_par_commune_et_par_type():
    ventes = pd.DataFrame({
        "code_commune": ["59350", "59350", "69381"], "nom_commune": ["Lille", "Lille", "Lyon 1er Arrondissement"],
        "type_local": ["Appartement", "Maison", "Appartement"], "prix_m2": [3000, 3500, 5000], "annee": 2025,
    })
    assert len(prix_par_commune(ventes)) == 3


def test_regrouper_communes_ajoute_la_ville_sans_retirer_les_arrondissements():
    ventes = pd.DataFrame({
        "code_commune": ["69381", "69381", "69383", "59350"],
        "nom_commune": ["Lyon 1er Arrondissement", "Lyon 1er Arrondissement", "Lyon 3e Arrondissement", "Lille"],
        "prix_m2": [1, 2, 3, 4],
    })
    resultat = regrouper_communes(ventes, {"69123": ("Lyon", ["69381", "69383"])})
    assert len(resultat) == 4 + 3
    lyon = resultat[resultat["code_commune"] == "69123"]
    assert list(lyon["nom_commune"].unique()) == ["Lyon"]
    assert sorted(lyon["prix_m2"]) == [1, 2, 3]
    assert (resultat["code_commune"] == "69381").sum() == 2  # les arrondissements restent


# --- charger, telecharger, charger_prix_communes --------------------------------------------------

def ecrire_dvf(dossier, departement, annee, lignes):
    pd.DataFrame(lignes).to_csv(dossier / f"{departement} {annee}.csv", index=False)


def test_charger_empile_les_annees_et_garde_les_codes_en_texte(tmp_path):
    for annee in (2024, 2025):
        ecrire_dvf(tmp_path, "01", annee, [{"id_mutation": f"{annee}-1", "code_commune": "01001", "code_postal": "01400"}])
    tableau = charger("01", (2024, 2025), tmp_path)
    assert list(tableau["annee"]) == [2024, 2025]
    assert list(tableau["code_commune"]) == ["01001", "01001"]  # le 0 de tête est conservé
    assert tableau["code_postal"].iloc[0] == "01400"


def test_charger_signale_le_fichier_manquant(tmp_path):
    with pytest.raises(FileNotFoundError, match="2025"):
        charger("01", (2025,), tmp_path)


def test_telecharger_ne_retelecharge_pas_un_fichier_present(tmp_path, monkeypatch):
    (tmp_path / "75 2025.csv").write_text("deja la")
    monkeypatch.setattr(donnees.urllib.request, "urlopen", lambda *a, **k: pytest.fail("téléchargement inutile"))
    assert telecharger("75", (2025,), tmp_path) == []


class FausseReponse:
    """Ce que renvoie urlopen : un contenu lisible, utilisable avec « with »."""

    def __init__(self, contenu):
        self.contenu = contenu

    def __enter__(self):
        return self

    def __exit__(self, *erreur):
        return False

    def read(self):
        return self.contenu


def test_telecharger_ecrit_le_fichier_decompresse_sans_laisser_de_fichier_provisoire(tmp_path, monkeypatch):
    monkeypatch.setattr(donnees.urllib.request, "urlopen", lambda url, timeout: FausseReponse(gzip.compress(b"a,b\n1,2\n")))
    ecrits = telecharger("75", (2025,), tmp_path)
    assert [chemin.name for chemin in ecrits] == ["75 2025.csv"]
    assert (tmp_path / "75 2025.csv").read_bytes() == b"a,b\n1,2\n"
    assert not list(tmp_path.glob("*.part"))


def test_telecharger_explique_qu_un_departement_n_est_pas_couvert(tmp_path, monkeypatch):
    def introuvable(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(donnees.urllib.request, "urlopen", introuvable)
    with pytest.raises(FileNotFoundError, match="pas couvert par DVF"):
        telecharger("67", (2025,), tmp_path)
    assert not list(tmp_path.iterdir())


def test_charger_prix_communes_lit_les_codes_en_texte(tmp_path):
    pd.DataFrame({"code_commune": ["01001"], "nom_commune": ["L'Abergement"]}).to_csv(tmp_path / "prix_communes.csv", index=False)
    assert charger_prix_communes(tmp_path)["code_commune"].iloc[0] == "01001"


def test_charger_prix_communes_indique_la_commande_a_lancer(tmp_path):
    with pytest.raises(FileNotFoundError, match="construire"):
        charger_prix_communes(tmp_path)
