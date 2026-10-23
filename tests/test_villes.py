"""Tests de villes.py et de la ligne de commande."""

from importlib import import_module

import pytest

from estimateur import cli
from estimateur.villes import VILLE_DE, VILLES, codes_du_departement, departements, regroupements


def test_dix_villes_dans_dix_departements_sans_strasbourg():
    assert len(VILLES) == 10
    assert len(departements()) == 10
    assert "Strasbourg" not in VILLES  # l'Alsace-Moselle (57, 67, 68) n'est pas dans DVF
    assert not {"57", "67", "68"} & set(departements())


def test_chaque_ville_a_son_code_insee_et_ses_communes_dans_le_bon_departement():
    for nom, (departement, code_ville, codes) in VILLES.items():
        assert code_ville.startswith(departement), nom
        assert all(code.startswith(departement) for code in codes), nom
        assert VILLE_DE[code_ville] == nom
        assert all(VILLE_DE[code] == nom for code in codes)


def test_seules_paris_lyon_et_marseille_sont_decoupees_en_arrondissements():
    decoupees = regroupements()
    assert {nom for nom, _ in decoupees.values()} == {"Paris", "Lyon", "Marseille"}
    assert {nom: len(codes) for nom, codes in decoupees.values()} == {"Paris": 20, "Lyon": 9, "Marseille": 16}
    assert decoupees["75056"][0] == "Paris"


def test_codes_du_departement():
    assert "69383" in codes_du_departement("69")
    assert codes_du_departement("59") == ["59350"]
    assert codes_du_departement("00") == []


# --- la ligne de commande -------------------------------------------------------------------------

def test_sans_argument_la_commande_liste_les_commandes(capsys):
    assert cli.main([]) == 0
    sortie = capsys.readouterr().out
    assert all(nom in sortie for nom in cli.COMMANDES)


def test_une_commande_inconnue_est_refusee_avec_la_liste_des_commandes():
    with pytest.raises(SystemExit) as sortie:
        cli.main(["inexistante"])
    assert "Commande inconnue" in str(sortie.value)
    assert "construire" in str(sortie.value)


@pytest.mark.parametrize("nom", list(cli.COMMANDES))
def test_chaque_commande_definit_ses_arguments_et_son_execution(nom):
    if nom == "graphique":
        pytest.importorskip("matplotlib")
    module = import_module(f"estimateur.commandes.{nom}")
    assert callable(module.ajouter_arguments)
    assert callable(module.executer)
