"""Trace le graphique des communes les plus chères et l'enregistre dans docs/.

À lancer depuis la racine du projet, après explorer.py : python graphique.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from immo import VENTES_MIN, charger_prix_communes, classer_communes

NB_COMMUNES = 15
SORTIE = Path(__file__).parent / "docs" / "communes_les_plus_cheres.png"

# Couleurs : une seule teinte pour l'ordre de grandeur, le reste en gris discrets.
SURFACE = "#fcfcfb"
ENCRE = "#0b0b0b"
ENCRE_SECONDAIRE = "#52514e"
ENCRE_DISCRETE = "#898781"
GRILLE = "#e1e0d9"
AXE = "#c3c2b7"
BARRE = "#2a78d6"

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]


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


def main():
    prix = charger_prix_communes()
    departement = prix["code_commune"].str[:2].iloc[0]  # le code de commune commence par le département

    maisons = classer_communes(prix, "Maison")
    appartements = classer_communes(prix, "Appartement")
    n_maisons = min(NB_COMMUNES, len(maisons))
    n_apparts = min(NB_COMMUNES, len(appartements))

    # Hauteurs proportionnelles au nombre de barres : toutes les barres ont la même épaisseur.
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 0.36 * (n_maisons + n_apparts) + 2.6), sharex=True,
        gridspec_kw={"height_ratios": [n_maisons, n_apparts]}, facecolor=SURFACE,
    )

    _tracer(ax1, maisons, f"Maisons : {n_maisons} communes les plus chères (sur {len(maisons)})")
    _tracer(ax2, appartements, f"Appartements : {len(appartements)} communes avec au moins {VENTES_MIN} ventes")
    ax2.set_xlabel("Prix médian au m² (€)", color=ENCRE_DISCRETE, fontsize=9, loc="left")
    ax2.set_xlim(0, max(maisons["mediane"].max(), appartements["mediane"].max()) * 1.38)

    fig.suptitle(
        f"Communes les plus chères du département {departement}",
        x=0.02, ha="left", fontsize=14, fontweight="bold", color=ENCRE,
    )
    fig.text(0.02, 0.945, f"Médiane du prix au m² des ventes DVF. Seules les communes avec au moins {VENTES_MIN} ventes sont classées.",
             ha="left", fontsize=9.5, color=ENCRE_SECONDAIRE)
    fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.5)

    SORTIE.parent.mkdir(exist_ok=True)
    fig.savefig(SORTIE, dpi=160, facecolor=SURFACE)
    print(f"Graphique enregistré : {SORTIE}")


if __name__ == "__main__":
    main()
