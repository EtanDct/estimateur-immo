"""L'estimation par médiane : trouver la commune d'un bien et en tirer une fourchette de prix.

Comme donnees.py, ce module n'affiche rien : il renvoie des valeurs ou lève des exceptions.
L'estimation par modèle (modele.py) s'appuie sur les mêmes vérifications.
"""

import unicodedata

from .config import SURFACE_MAX, TYPES_DE_BIEN, VENTES_MIN


# Les deux erreurs d'une estimation sont des ValueError : un programme qui attrape ValueError les
# attrape toutes les deux, et l'API les distingue pour choisir le code de réponse.
class ParametreInvalide(ValueError):
    """Un paramètre d'une estimation est inacceptable (surface, type de bien, commune ambiguë)."""


class BienIntrouvable(ValueError):
    """Aucune estimation possible : commune inconnue, ou pas assez de ventes de ce type de bien."""


def _normaliser(texte):
    """Met un nom sous une forme comparable : minuscules, sans accents, sans tirets ni apostrophes.

    "Épernay" et "epernay" donnent la même chose, comme "Saint-Martin-d'Ablois" et
    "saint martin d ablois".
    """
    # NFD sépare chaque lettre accentuée en lettre + accent ; on jette les accents.
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c))
    simple = sans_accents.casefold().replace("œ", "oe").replace("æ", "ae")
    for separateur in ("-", "'", "’"):
        simple = simple.replace(separateur, " ")
    return " ".join(simple.split())  # split() + join : supprime les espaces en trop


def chercher_ligne(prix, commune, type_local, surface, ventes_min=VENTES_MIN):
    """Vérifie les paramètres d'une estimation et renvoie la ligne de statistiques qui la concerne.

    prix : le tableau produit par prix_par_commune() (ou lu par charger_prix_communes()).
    La ligne renvoyée porte le nom de commune et le type de bien écrits comme dans le tableau.
    Lève une ValueError au message clair : ParametreInvalide si la surface ou le type de bien
    est invalide ou si le nom de commune désigne plusieurs communes, BienIntrouvable si la
    commune est inconnue ou compte moins de ventes_min ventes.
    """
    # not (0 < surface <= max) plutôt que surface <= 0 : une valeur NaN fait échouer toute
    # comparaison, donc elle est rejetée aussi.
    if not 0 < surface <= SURFACE_MAX:
        raise ParametreInvalide(f"La surface doit être comprise entre 0 et {SURFACE_MAX} m² (reçu : {surface:g}).")

    types = {_normaliser(t): t for t in TYPES_DE_BIEN}
    if _normaliser(type_local) not in types:
        raise ParametreInvalide(f"Type de bien inconnu : {type_local!r}. Valeurs possibles : {', '.join(TYPES_DE_BIEN)}.")
    type_local = types[_normaliser(type_local)]

    # On compare les noms sous forme normalisée, pour ignorer la casse et les accents.
    noms = prix["nom_commune"].map(_normaliser)
    de_la_commune = prix[noms == _normaliser(commune)]
    if de_la_commune.empty:
        raise BienIntrouvable(f"Commune introuvable : {commune!r} (nom mal écrit, ou aucune vente exploitable).")

    lignes = de_la_commune[de_la_commune["type_local"] == type_local]
    nom = de_la_commune["nom_commune"].iloc[0]
    if lignes.empty:
        raise BienIntrouvable(f"Aucune vente exploitable de {type_local.lower()} à {nom}.")
    if len(lignes) > 1:  # une ligne par commune et par type : plusieurs lignes = plusieurs communes
        codes = ", ".join(lignes["code_commune"])
        raise ParametreInvalide(f"Plusieurs communes s'appellent {nom} (codes {codes}).")

    ligne = lignes.iloc[0]
    if ligne["nombre_ventes"] < ventes_min:
        raise BienIntrouvable(
            f"Seulement {ligne['nombre_ventes']} vente(s) de {type_local.lower()} à {nom} : "
            f"il en faut au moins {ventes_min} pour une estimation fiable."
        )
    return ligne


def estimer(prix, commune, type_local, surface, ventes_min=VENTES_MIN):
    """Estime une fourchette de prix pour un bien, à partir des statistiques par commune.

    prix : le tableau produit par prix_par_commune() (ou lu par charger_prix_communes()).
    Renvoie un dictionnaire : commune, type_local, surface, nombre_ventes, annee_min,
    annee_max, prix_m2_median, et prix_bas / prix_median / prix_haut (surface x quartile_1,
    mediane, quartile_3). Les erreurs sont celles de chercher_ligne().
    """
    ligne = chercher_ligne(prix, commune, type_local, surface, ventes_min)
    return {
        "commune": ligne["nom_commune"],
        "type_local": ligne["type_local"],
        "surface": surface,
        "nombre_ventes": int(ligne["nombre_ventes"]),
        "annee_min": int(ligne["annee_min"]),
        "annee_max": int(ligne["annee_max"]),
        "prix_m2_median": float(ligne["mediane"]),
        "prix_bas": surface * float(ligne["quartile_1"]),
        "prix_median": surface * float(ligne["mediane"]),
        "prix_haut": surface * float(ligne["quartile_3"]),
    }


def noms_communes(prix):
    """Renvoie les noms des communes présentes dans prix, sans doublon, triés sans tenir compte des accents."""
    return sorted(prix["nom_commune"].unique(), key=_normaliser)


def _departement(code_commune):
    """Déduit le département d'un code de commune : "51454" -> "51", "2A004" -> "2A", "97105" -> "971"."""
    return code_commune[:3] if code_commune.startswith("97") else code_commune[:2]


def zone_couverte(prix):
    """Décrit ce que couvrent les données : départements, première et dernière année, nombre de communes.

    Tout est déduit du tableau : rien n'est écrit en dur. Si le tableau a une colonne ville
    (voir la commande construire), la zone liste aussi les villes.
    """
    zone = {
        "departements": sorted(prix["code_commune"].map(_departement).unique()),
        "annee_min": int(prix["annee_min"].min()),
        "annee_max": int(prix["annee_max"].max()),
        "nombre_communes": int(prix["code_commune"].nunique()),
    }
    if "ville" in prix.columns:
        zone["villes"] = sorted(prix["ville"].dropna().unique(), key=_normaliser)
    return zone


def classer_communes(prix, type_local, ventes_min=VENTES_MIN):
    """Classe les communes d'un type de bien de la plus chère à la moins chère.

    Le classement porte sur la médiane du prix au m². Seules les communes qui comptent au
    moins ventes_min ventes sont gardées, pour que le classement repose sur assez de ventes.
    """
    lignes = prix[(prix["type_local"] == type_local) & (prix["nombre_ventes"] >= ventes_min)]
    return lignes.sort_values("mediane", ascending=False).reset_index(drop=True)
