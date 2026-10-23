"""Les dix grandes villes couvertes par le projet.

Pour chaque ville : le département DVF, le code INSEE de la ville, et les codes de commune sous
lesquels DVF enregistre ses ventes. Paris, Lyon et Marseille y sont découpées en arrondissements
(« Paris 10e Arrondissement » est une commune à part, de code 75110).

Strasbourg n'y figure pas : l'Alsace-Moselle (57, 67, 68) n'est pas couverte par DVF. Rennes,
onzième ville de France, prend sa place.
"""

# nom : (département, code INSEE de la ville, codes de commune dans DVF)
VILLES = {
    "Paris": ("75", "75056", [f"751{n:02d}" for n in range(1, 21)]),
    "Marseille": ("13", "13055", [f"132{n:02d}" for n in range(1, 17)]),
    "Lyon": ("69", "69123", [f"6938{n}" for n in range(1, 10)]),
    "Toulouse": ("31", "31555", ["31555"]),
    "Nice": ("06", "06088", ["06088"]),
    "Nantes": ("44", "44109", ["44109"]),
    "Montpellier": ("34", "34172", ["34172"]),
    "Bordeaux": ("33", "33063", ["33063"]),
    "Lille": ("59", "59350", ["59350"]),
    "Rennes": ("35", "35238", ["35238"]),
}


# Le nom de la ville pour chaque code de commune : "75110" -> "Paris".
VILLE_DE = {code: nom for nom, (_, _, codes) in VILLES.items() for code in codes}


def departements():
    """Renvoie les départements à charger, triés."""
    return sorted({departement for departement, _, _ in VILLES.values()})


def codes_du_departement(departement):
    """Renvoie les codes de commune des villes situées dans ce département."""
    return [code for dep, _, codes in VILLES.values() if dep == departement for code in codes]


def regroupements():
    """Renvoie les villes découpées en arrondissements : {code INSEE: (nom, codes des arrondissements)}.

    À donner à immo.regrouper_communes() pour que « Paris » existe aussi en entier.
    """
    return {code_ville: (nom, codes) for nom, (_, code_ville, codes) in VILLES.items() if len(codes) > 1}
