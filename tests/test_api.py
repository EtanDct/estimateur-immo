"""Tests de l'API : ce que le site reçoit, et ce que l'API refuse.

Chaque test lance l'API pour de vrai (démarrage compris) sur les ventes factices de conftest.py,
et l'interroge comme le ferait le site.
"""

import re

import pytest
from fastapi.testclient import TestClient

from conftest import LILLE, LYON_1ER, LYON_3E, ORIGINE_DU_SITE, TRACABILITE
from estimateur import api
from estimateur.modele import enregistrer_modeles

BASE = {"commune": "Lille", "type_local": "Appartement", "surface": 60}
CLE = "cle-de-test"


def estimation(client, **parametres):
    return client.get("/estimation", params={**BASE, **parametres})


def limite_par_minute():
    return int(api.LIMITE_ESTIMATION.split("/")[0])


# --- les routes qui ne calculent pas -------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.head("/health").status_code == 200


def test_health_n_est_jamais_limite(client):
    # Le contrôle de santé de Docker l'appelle toutes les 30 secondes : il ne doit jamais recevoir de 429.
    assert all(client.get("/health").status_code == 200 for _ in range(100))


def test_communes_liste_les_noms_tries_et_se_met_en_cache(client):
    reponse = client.get("/communes")
    assert reponse.status_code == 200
    noms = reponse.json()
    assert "Lille" in noms and "Lyon 3e Arrondissement" in noms and "Paris" in noms and "Lyon" in noms
    assert noms == sorted(noms, key=str.casefold)
    assert reponse.headers["cache-control"] == "public, max-age=3600"


def test_info_decrit_la_zone_et_le_modele(client, modeles):
    reponse = client.get("/info")
    assert reponse.status_code == 200
    info = reponse.json()
    assert info["departements"] == ["59", "69", "75"]
    assert info["villes"] == ["Lille", "Lyon", "Paris"]
    assert (info["annee_min"], info["annee_max"]) == (2024, 2025)
    assert info["modele"]["methodes"] == ["adresse", "commune", "mediane"]
    assert info["modele"]["entrainement"] == [2021, 2025]
    assert info["modele"]["erreur_mediane_pct"] == {"adresse": 10.0}  # les mesures de evaluer passent telles quelles
    # Le site lit les bornes de surface ici pour vérifier une demande avant de l'envoyer.
    assert info["modele"]["surfaces"] == {type_local: list(bornes) for type_local, bornes in modeles["surfaces"].items()}
    # D'où vient le modèle : la date, le commit et le nombre de ventes d'entraînement.
    assert info["modele"]["entraine_le"] == TRACABILITE["entraine_le"]
    assert info["modele"]["commit"] == TRACABILITE["commit"]
    assert info["modele"]["nombre_ventes"] == modeles["nombre_ventes"]
    assert reponse.headers["cache-control"] == "public, max-age=3600"


def test_info_donne_null_pour_un_fichier_de_modeles_sans_tracabilite(monkeypatch, tmp_path, prix, modeles):
    ancien = {cle: valeur for cle, valeur in modeles.items() if cle not in ("tracabilite", "nombre_ventes")}
    prix.to_csv(tmp_path / "prix_communes.csv", index=False)
    enregistrer_modeles(ancien, tmp_path)
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    monkeypatch.setattr(api, "CLES_API", [])
    with TestClient(api.app) as client:
        info = client.get("/info").json()["modele"]
    assert info["entraine_le"] is None and info["commit"] is None and info["nombre_ventes"] is None
    assert info["entrainement"] == [2021, 2025]  # le reste du modèle est servi normalement


@pytest.mark.parametrize("chemin", ["/health", "/communes", "/info"])
def test_head_repond_comme_get_sans_corps(client, chemin):
    reponse = client.head(chemin)
    assert reponse.status_code == 200
    assert reponse.content == b""


def test_head_n_existe_pas_sur_estimation(client):
    # Un HEAD calculerait une estimation pour rien, en consommant la limite de requêtes.
    reponse = client.head("/estimation", params=BASE)
    assert reponse.status_code == 405
    assert "GET" in reponse.headers["allow"]


@pytest.mark.parametrize("chemin", ["/docs", "/redoc"])
def test_la_documentation_interactive_est_desactivee_par_defaut(client, chemin):
    # Ces pages chargent leurs scripts depuis un CDN public.
    assert client.get(chemin).status_code == 404


def test_le_schema_openapi_decrit_toutes_les_reponses_de_estimation(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/estimation"]["get"]
    assert {"200", "401", "404", "422", "429"} <= set(operation["responses"])
    assert all(parametre["description"] for parametre in operation["parameters"] if parametre["name"] != "x-api-key")
    # HEAD n'est pas documenté : la même fonction aurait deux fois le même identifiant d'opération.
    assert all(set(methodes) == {"get"} for methodes in schema["paths"].values())
    identifiants = [operation["operationId"] for methodes in schema["paths"].values() for operation in methodes.values()]
    assert len(identifiants) == len(set(identifiants))


# --- /estimation : le contrat avec le site ------------------------------------------------------

def test_estimation_renvoie_exactement_les_champs_attendus_par_le_site(client):
    reponse = estimation(client)
    assert reponse.status_code == 200
    estimation_json = reponse.json()
    assert set(estimation_json) == set(api.Estimation.model_fields)
    assert set(estimation_json) == {
        "commune", "type_local", "surface", "nombre_ventes", "annee_min", "annee_max",
        "prix_m2_median", "prix_bas", "prix_median", "prix_haut", "methode", "repli",
    }
    assert estimation_json["commune"] == "Lille" and estimation_json["type_local"] == "Appartement" and estimation_json["surface"] == 60
    assert estimation_json["methode"] == "commune" and estimation_json["repli"] is None
    for champ in ("prix_m2_median", "prix_bas", "prix_median", "prix_haut", "nombre_ventes"):
        assert isinstance(estimation_json[champ], int), champ
    assert estimation_json["prix_bas"] <= estimation_json["prix_median"] <= estimation_json["prix_haut"]


def test_estimation_avec_une_adresse_utilise_le_modele_d_adresse(client):
    reponse = estimation(client, commune="Lyon 3e Arrondissement", latitude=LYON_3E[0], longitude=LYON_3E[1])
    assert reponse.status_code == 200
    assert reponse.json()["methode"] == "adresse"


def test_estimation_d_une_ville_entiere_sans_adresse_utilise_les_medianes(client):
    assert estimation(client, commune="Lyon").json()["methode"] == "mediane"


def test_estimation_signale_le_repli_sur_la_ville(client):
    reponse = estimation(client, commune="Paris 1er Arrondissement", type_local="Maison", surface=100)
    assert reponse.status_code == 200
    assert (reponse.json()["methode"], reponse.json()["repli"]) == ("mediane", "Paris")


def test_estimation_sans_fichier_de_modele_repond_avec_les_medianes(client_sans_modele):
    reponse = estimation(client_sans_modele)
    assert reponse.status_code == 200 and reponse.json()["methode"] == "mediane"
    # Même avec une adresse : sans modèle, elle est ignorée.
    assert estimation(client_sans_modele, latitude=LILLE[0], longitude=LILLE[1]).json()["methode"] == "mediane"
    assert "surfaces" not in client_sans_modele.get("/info").json().get("modele", {})


def test_l_api_refuse_de_demarrer_sans_les_statistiques(monkeypatch, tmp_path):
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="construire"), TestClient(api.app):
        pass


# --- les erreurs : toujours {"detail": "une phrase en français"} ----------------------------------

CAS_D_ERREUR = [
    ("commune inconnue", dict(commune="Atlantide"), 404, "Commune introuvable"),
    ("type inconnu", dict(type_local="Château"), 422, "Type de bien inconnu"),
    ("surface trop petite", dict(surface=8.99), 422, "entre 9 et 1000"),
    ("surface trop grande", dict(surface=10000.01), 422, r"\(reçu : 10000.01\)"),
    ("surface minuscule", dict(surface="1e-9"), 422, r"\(reçu : 1e-09\)"),
    ("surface nan", dict(surface="nan"), 422, "entre 9 et 1000"),
    ("surface inf", dict(surface="inf"), 422, "entre 9 et 1000"),
    ("surface pas un nombre", dict(surface="abc"), 422, "Le paramètre surface doit être un nombre"),
    ("commune avec octet nul", dict(commune="Lille\x00"), 422, "trop long ou contient des caractères invalides"),
    ("commune de 5000 caractères", dict(commune="A" * 5000), 422, "trop long"),
    ("latitude seule", dict(latitude=50.6), 422, "vont ensemble"),
    ("latitude hors du globe", dict(latitude=200, longitude=999), 422, "Coordonnées hors limites"),
    ("latitude nan", dict(latitude="nan", longitude=3.0), 422, "doivent être des nombres"),
    ("latitude pas un nombre", dict(latitude="abc", longitude=3.0), 422, "Le paramètre latitude doit être un nombre"),
    ("adresse dans un autre arrondissement", dict(commune="Lyon 1er Arrondissement", latitude=LYON_3E[0], longitude=LYON_3E[1]), 422,
     "Cette adresse se trouve à Lyon 3e Arrondissement, pas à Lyon 1er Arrondissement"),
    ("adresse en mer", dict(latitude=0, longitude=0), 422, "en dehors des villes couvertes"),
]


@pytest.mark.parametrize("nom, parametres, statut, message", CAS_D_ERREUR, ids=[cas[0] for cas in CAS_D_ERREUR])
def test_les_erreurs_ont_le_bon_statut_et_une_phrase_en_francais(client, nom, parametres, statut, message):
    reponse = estimation(client, **parametres)
    assert reponse.status_code == statut
    if message:
        assert set(reponse.json()) == {"detail"}
        assert isinstance(reponse.json()["detail"], str)
        assert re.search(message, reponse.json()["detail"])


def test_un_appartement_hors_des_surfaces_du_modele_est_refuse_avec_ses_bornes(client, modeles):
    haut = modeles["surfaces"]["Appartement"][1]
    reponse = estimation(client, surface=haut + 1)
    assert reponse.status_code == 422
    assert f"entre {modeles['surfaces']['Appartement'][0]} et {haut} m²" in reponse.json()["detail"]


def test_les_parametres_obligatoires_manquants_sont_listes_en_francais(client):
    reponse = client.get("/estimation", params={"commune": "Lille"})
    assert reponse.status_code == 422
    assert reponse.json() == {"detail": "Paramètre obligatoire manquant : type_local. Paramètre obligatoire manquant : surface."}


def test_un_parametre_repete_est_refuse(client):
    reponse = client.get("/estimation?commune=Lille&commune=Lyon&type_local=Maison&surface=60")
    assert (reponse.status_code, reponse.json()) == (422, {"detail": "Paramètre répété : commune."})


# --- la clé d'API --------------------------------------------------------------------------------

@pytest.fixture
def avec_cle(client, monkeypatch):
    """L'API configurée avec une clé (CLES_API) : toutes les routes sauf /health l'exigent."""
    monkeypatch.setattr(api, "CLES_API", [CLE.encode()])
    return client


ROUTES = ["/communes", "/info", "/estimation?commune=Lille&type_local=Appartement&surface=60"]


@pytest.mark.parametrize("route", ROUTES)
def test_sans_cle_l_api_refuse_toutes_les_routes_sauf_health(avec_cle, route):
    reponse = avec_cle.get(route)
    assert (reponse.status_code, reponse.json()) == (401, {"detail": "Clé d'API manquante ou invalide."})
    assert avec_cle.get(route, headers={"X-API-Key": "mauvaise"}).status_code == 401
    assert avec_cle.get(route, headers={"X-API-Key": ""}).status_code == 401
    assert avec_cle.get(route, headers={"X-API-Key": CLE}).status_code == 200
    assert avec_cle.get("/health").status_code == 200


def test_une_clef_proche_de_la_bonne_est_refusee(avec_cle):
    for fausse in (CLE + "x", CLE[:-1], CLE.upper(), " " + CLE):
        assert avec_cle.get("/communes", headers={"X-API-Key": fausse}).status_code == 401


def test_plusieurs_cles_sont_acceptees_pour_changer_de_cle_sans_interruption(avec_cle, monkeypatch):
    monkeypatch.setattr(api, "CLES_API", [b"ancienne", b"nouvelle"])
    for cle in ("ancienne", "nouvelle"):
        assert avec_cle.get("/communes", headers={"X-API-Key": cle}).status_code == 200
    assert avec_cle.get("/communes", headers={"X-API-Key": "retiree"}).status_code == 401


def test_les_cles_se_lisent_dans_la_variable_d_environnement(monkeypatch):
    monkeypatch.setenv("CLES_API", " a , b,, ")
    assert api._lire_cles() == [b"a", b"b"]
    monkeypatch.setenv("CLES_API", "")
    assert api._lire_cles() == []


def test_l_api_sans_cle_configuree_est_ouverte(client):
    assert client.get("/communes").status_code == 200


# --- la limite de requêtes -----------------------------------------------------------------------

def test_au_dela_de_la_limite_l_api_repond_429_avec_le_temps_d_attente(client):
    for _ in range(limite_par_minute()):
        assert estimation(client).status_code == 200
    reponse = estimation(client)
    assert reponse.status_code == 429
    attente = int(reponse.headers["retry-after"])
    assert 1 <= attente <= 60
    assert reponse.json() == {"detail": f"Trop de requêtes : réessayez dans {attente} s."}


def test_la_reponse_429_porte_les_en_tetes_cors_pour_que_le_navigateur_la_lise(client):
    for _ in range(limite_par_minute()):
        estimation(client)
    reponse = client.get("/estimation", params=BASE, headers={"Origin": ORIGINE_DU_SITE})
    assert reponse.status_code == 429
    assert reponse.headers["access-control-allow-origin"] == ORIGINE_DU_SITE
    assert "retry-after" in reponse.headers["access-control-expose-headers"].lower()


def test_la_limite_s_applique_a_chaque_visiteur_transmis_par_le_site(avec_cle):
    # Le serveur du site appelle l'API : sans X-Visiteur-IP, tous les visiteurs auraient l'IP de Vercel.
    def appel(visiteur):
        return avec_cle.get("/estimation", params=BASE, headers={"X-API-Key": CLE, "X-Visiteur-IP": visiteur})

    for _ in range(limite_par_minute()):
        assert appel("203.0.113.1").status_code == 200
    assert appel("203.0.113.1").status_code == 429
    assert appel("203.0.113.2").status_code == 200  # un autre visiteur n'est pas touché


def test_x_visiteur_ip_n_est_pas_cru_sans_cle_valide(client):
    # Sans clé configurée, n'importe qui pourrait inventer cet en-tête pour échapper à la limite.
    for numero in range(limite_par_minute()):
        assert client.get("/estimation", params=BASE, headers={"X-Visiteur-IP": f"198.51.100.{numero}"}).status_code == 200
    assert client.get("/estimation", params=BASE, headers={"X-Visiteur-IP": "198.51.100.200"}).status_code == 429


def test_x_visiteur_ip_n_est_pas_cru_avec_une_mauvaise_cle(avec_cle):
    reponse = avec_cle.get("/estimation", params=BASE, headers={"X-API-Key": "mauvaise", "X-Visiteur-IP": "203.0.113.9"})
    assert reponse.status_code == 401


# --- CORS : seul le site peut appeler l'API depuis un navigateur -----------------------------------

def test_le_site_peut_appeler_l_api_depuis_le_navigateur(client):
    reponse = client.options(
        "/estimation", headers={"Origin": ORIGINE_DU_SITE, "Access-Control-Request-Method": "GET"},
    )
    assert reponse.status_code == 200
    assert reponse.headers["access-control-allow-origin"] == ORIGINE_DU_SITE
    assert reponse.headers["access-control-allow-methods"] == "GET"


def test_un_autre_site_n_est_pas_autorise(client):
    reponse = client.options(
        "/estimation", headers={"Origin": "https://autre-site.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in reponse.headers
    reponse = client.get("/communes", headers={"Origin": "https://autre-site.example"})
    assert "access-control-allow-origin" not in reponse.headers


def test_les_methodes_qui_modifient_ne_sont_pas_ouvertes(client):
    reponse = client.options(
        "/estimation", headers={"Origin": ORIGINE_DU_SITE, "Access-Control-Request-Method": "POST"},
    )
    assert reponse.status_code == 400
    assert client.post("/estimation", params=BASE).status_code == 405


def test_les_adresses_de_lyon_donnent_des_prix_differents_par_arrondissement(client):
    # Le point de Lyon 1er (5 000 €/m² dans les ventes factices) est plus cher que celui de Lyon 3e (4 500).
    premier = estimation(client, commune="Lyon", latitude=LYON_1ER[0], longitude=LYON_1ER[1]).json()
    troisieme = estimation(client, commune="Lyon", latitude=LYON_3E[0], longitude=LYON_3E[1]).json()
    assert premier["prix_m2_median"] > troisieme["prix_m2_median"]
