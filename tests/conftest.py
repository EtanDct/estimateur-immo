"""Données factices partagées par les tests.

Aucun test n'a besoin des vraies données : data/ n'est pas dans Git (400 000 ventes), donc la CI ne
l'aurait pas. Les tests construisent à la place un petit jeu de ventes aux prix connus, avec les
vrais codes de commune, et entraînent de vrais modèles dessus (quelques secondes en tout).
"""

import os

# L'environnement de celui qui lance les tests ne doit rien changer : ces variables sont lues
# quand estimateur.api est importé, donc on les retire avant.
for variable in ("CLES_API", "ORIGINES_AUTORISEES", "LIMITE_ESTIMATION", "LIMITE_DEFAUT", "ACTIVER_DOCS", "DOSSIER_DONNEES"):
    os.environ.pop(variable, None)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from estimateur import api  # noqa: E402
from estimateur.donnees import prix_par_commune, regrouper_communes  # noqa: E402
from estimateur.modele import enregistrer_modeles, entrainer_modeles  # noqa: E402
from estimateur.villes import VILLE_DE, regroupements  # noqa: E402

# Dans les tests d'API, les visiteurs viennent de cette origine, la seule que l'API autorise par défaut.
ORIGINE_DU_SITE = "https://www.tatane.me"

# Ce que la commande modeliser écrit dans le fichier de modèles : la date et le commit du code qui entraîne.
TRACABILITE = {"entraine_le": "2026-10-23", "commit": "0123456789ab"}

ANNEE_MAX = 2025

# Les communes factices : (code, nom, latitude, longitude du centre, prix au m² d'un appartement,
# d'une maison, nombre d'appartements, nombre de maisons). Les codes sont les vrais : Lyon et Paris
# sont découpées en arrondissements, regroupées en « Lyon » et « Paris » comme dans le projet.
# Paris 1er n'a que 3 ventes de maisons (moins de 10) : c'est le cas du repli sur la ville.
COMMUNES = [
    ("59350", "Lille", 50.630, 3.060, 3300, 3500, 150, 100),
    ("69381", "Lyon 1er Arrondissement", 45.770, 4.830, 5000, 5200, 100, 50),
    ("69383", "Lyon 3e Arrondissement", 45.760, 4.860, 4500, 4700, 100, 50),
    ("75101", "Paris 1er Arrondissement", 48.862, 2.336, 13000, 14000, 100, 3),
    ("75102", "Paris 2e Arrondissement", 48.868, 2.344, 12000, 13000, 100, 50),
]

# Surfaces des ventes factices, en m² : les bornes acceptées par le modèle en découlent.
SURFACES = {"Appartement": (20, 120), "Maison": (70, 220)}

# Points de test : le centre de chaque arrondissement factice.
LILLE = (50.630, 3.060)
LYON_1ER = (45.770, 4.830)
LYON_3E = (45.760, 4.860)
PARIS_1ER = (48.862, 2.336)
EN_MER = (0.0, 0.0)  # golfe de Guinée : loin de toute vente


def fabriquer_ventes():
    """Construit les ventes factices, au format de data/villes/ventes_propres.csv.

    Le prix au m² dépend de la commune, du type de bien, de la surface (un peu moins cher quand le bien
    est grand) et de l'année (+2 % par an), avec un bruit de 10 %. Le tirage est fixé : les mêmes
    ventes à chaque lancement.
    """
    hasard = np.random.default_rng(0)
    lignes = []
    for code, nom, latitude, longitude, prix_appartement, prix_maison, n_appartements, n_maisons in COMMUNES:
        for type_local, prix_de_base, n in (("Appartement", prix_appartement, n_appartements), ("Maison", prix_maison, n_maisons)):
            mini, maxi = SURFACES[type_local]
            surface = hasard.uniform(mini, maxi, n).round(1)
            # Les années se suivent à tour de rôle de 2025 vers 2021 : autant de ventes chaque année, et
            # les 3 maisons de Paris 1er tombent en 2025, 2024 et 2023 (2 seulement dans les statistiques).
            annee = np.resize(np.arange(ANNEE_MAX, ANNEE_MAX - 5, -1), n)
            prix_m2 = prix_de_base * (1 - 0.002 * (surface - 60)) * 1.02 ** (annee - ANNEE_MAX) * hasard.lognormal(0, 0.1, n)
            lignes.append(pd.DataFrame({
                "annee": annee,
                "code_commune": code,
                "nom_commune": nom,
                "type_local": type_local,
                "surface_reelle_bati": surface,
                "latitude": latitude + hasard.normal(0, 0.002, n),
                "longitude": longitude + hasard.normal(0, 0.003, n),
                "prix_m2": prix_m2,
            }))
    return pd.concat(lignes, ignore_index=True)


@pytest.fixture(scope="session")
def ventes():
    """Les ventes factices (toutes les années 2021 à 2025)."""
    return fabriquer_ventes()


@pytest.fixture(scope="session")
def prix(ventes):
    """Les statistiques par commune, comme data/villes/prix_communes.csv (années 2024 et 2025 seulement)."""
    recentes = ventes[ventes["annee"].isin((2024, 2025))]
    statistiques = prix_par_commune(regrouper_communes(recentes, regroupements()))
    statistiques["ville"] = statistiques["code_commune"].map(VILLE_DE)
    return statistiques


@pytest.fixture(scope="session")
def modeles(ventes):
    """Les modèles entraînés sur les ventes factices : trois quantiles, deux modèles (commune et adresse)."""
    modeles = entrainer_modeles(ventes, regroupements(), {"resume": {"annee_testee": 2025, "erreur_mediane_pct": {"adresse": 10.0}}})
    modeles["tracabilite"] = TRACABILITE  # ce que la commande modeliser ajoute avant d'enregistrer
    return modeles


@pytest.fixture(scope="session")
def dossier_donnees(tmp_path_factory, prix, modeles):
    """Un dossier de données complet, comme data/villes/ sur le serveur : statistiques et modèles."""
    dossier = tmp_path_factory.mktemp("donnees")
    prix.to_csv(dossier / "prix_communes.csv", index=False)
    enregistrer_modeles(modeles, dossier)
    return dossier


@pytest.fixture(autouse=True)
def compteurs_a_zero():
    """Remet à zéro la limite de requêtes entre deux tests : sinon ils se la partageraient."""
    api.limiter.reset()


@pytest.fixture
def client(monkeypatch, dossier_donnees):
    """Un client de l'API démarrée sur les données factices, sans clé d'API."""
    monkeypatch.setenv("DOSSIER_DONNEES", str(dossier_donnees))
    monkeypatch.setattr(api, "CLES_API", [])
    with TestClient(api.app) as client:
        yield client


@pytest.fixture
def client_sans_modele(monkeypatch, tmp_path, prix):
    """Un client de l'API démarrée sans modeles.joblib : les médianes seules répondent."""
    prix.to_csv(tmp_path / "prix_communes.csv", index=False)
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    monkeypatch.setattr(api, "CLES_API", [])
    with TestClient(api.app) as client:
        yield client
