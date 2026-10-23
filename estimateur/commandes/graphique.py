"""Trace le prix médian au m² des dix grandes villes et l'enregistre dans docs/.

À lancer après la commande construire : python -m estimateur graphique
"""

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from ..config import DOCS_DIR, DOSSIER_VILLES, VENTES_MIN
from ..donnees import charger_prix_communes
from ..estimation import classer_communes
from ..villes import VILLES

NB_COMMUNES = len(VILLES)
SORTIE = DOCS_DIR / "villes_les_plus_cheres.png"

# Couleurs : une seule teinte pour l'ordre de grandeur, le reste en gris discrets.
SURFACE = "#fcfcfb"
ENCRE = "#0b0b0b"
ENCRE_SECONDAIRE = "#52514e"
ENCRE_DISCRETE = "#898781"
GRILLE = "#e1e0d9"
AXE = "#c3c2b7"
BARRE = "#2a78d6"


def _milliers(valeur):
    """Écrit un nombre avec des espaces entre les milliers : 3 391."""
    return f"{valeur:,.0f}".replace(",", " ")


def _tracer(ax, classement, titre):
    """Dessine un classement en barres horizontales, la commune la plus chère en haut."""
    haut = classement.head(NB_COMMUNES).iloc[::-1]  # inversé : matplotlib dessine de bas en haut
    ax.barh(haut["nom_commune"], haut["mediane"], height=0.62, color=BARRE, zorder=3)

    for y, (_, ligne) in enumerate(haut.iterrows()):
        ax.text(
            ligne["mediane"] + 40, y,
            f"{_milliers(ligne['mediane'])} €  ·  {_milliers(ligne['nombre_ventes'])} ventes",
            va="center", fontsize=9, color=ENCRE,
        )

    ax.set_title(titre, loc="left", fontsize=11, fontweight="bold", color=ENCRE, pad=10)
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRILLE, linewidth=0.8, zorder=0)  # grille fine, au second plan
    ax.set_axisbelow(True)
    for cote in ("top", "right", "bottom"):
        ax.spines[cote].set_visible(False)
    ax.spines["left"].set_color(AXE)
    ax.tick_params(axis="y", length=0, labelsize=9.5, labelcolor=ENCRE_SECONDAIRE)
    ax.tick_params(axis="x", length=0, labelsize=9, labelcolor=ENCRE_DISCRETE)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _milliers(v)))


def ajouter_arguments(parser):
    """Cette commande n'a pas d'option."""


def executer(args):
    """Lit prix_communes.csv, trace les deux classements et écrit l'image."""
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

    prix = charger_prix_communes(DOSSIER_VILLES)
    # Une ligne par ville : le code INSEE de la ville (« Paris » entière, pas ses arrondissements).
    prix = prix[prix["code_commune"].isin([code_ville for _, code_ville, _ in VILLES.values()])]

    maisons = classer_communes(prix, "Maison")
    appartements = classer_communes(prix, "Appartement")
    n_maisons = min(NB_COMMUNES, len(maisons))
    n_apparts = min(NB_COMMUNES, len(appartements))

    # Hauteurs proportionnelles au nombre de barres : toutes les barres ont la même épaisseur.
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 0.36 * (n_maisons + n_apparts) + 2.6), sharex=True,
        gridspec_kw={"height_ratios": [n_maisons, n_apparts]}, facecolor=SURFACE,
    )

    _tracer(ax1, maisons, "Maisons")
    _tracer(ax2, appartements, "Appartements")
    ax2.set_xlabel("Prix médian au m² (€)", color=ENCRE_DISCRETE, fontsize=9, loc="left")
    ax2.set_xlim(0, max(maisons["mediane"].max(), appartements["mediane"].max()) * 1.38)

    fig.suptitle(
        f"Prix au m² dans les {NB_COMMUNES} grandes villes",
        x=0.02, ha="left", fontsize=14, fontweight="bold", color=ENCRE,
    )
    annees = f"{prix['annee_min'].min()} à {prix['annee_max'].max()}"
    fig.text(0.02, 0.945, f"Médiane du prix au m² des ventes DVF de {annees}. Seules les villes avec au moins {VENTES_MIN} ventes de ce type de bien sont classées.",
             ha="left", fontsize=9.5, color=ENCRE_SECONDAIRE)
    fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.5)

    SORTIE.parent.mkdir(exist_ok=True)
    fig.savefig(SORTIE, dpi=160, facecolor=SURFACE)
    print(f"Graphique enregistré : {SORTIE}")
