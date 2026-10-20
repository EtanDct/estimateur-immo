"""Modèle de prix au m² : séparation par année, référence, entraînement et mesure de l'erreur.

Comme immo.py, ce module n'affiche rien : evaluer.py l'appelle et présente les résultats.
"""

# L'année de test : on entraîne sur les années d'avant, on teste sur celle-ci, comme en vrai
# (le modèle prédit l'avenir à partir du passé).
ANNEE_TEST = 2025


def separer_par_annee(df, annee_test=ANNEE_TEST):
    """Sépare les ventes nettoyées en deux tableaux : (entrainement, test).

    Le test contient les ventes de annee_test, l'entraînement celles des années précédentes.
    """
    raise NotImplementedError


def predire_par_mediane(entrainement, test):
    """Référence : prédit le prix_m2 de chaque vente du test par une médiane mesurée sur l'entraînement.

    La médiane est celle de la commune et du type de bien de la vente, calculée sur
    l'entraînement seulement. Renvoie une série alignée sur test.
    """
    raise NotImplementedError


def entrainer(entrainement):
    """Entraîne un modèle de prix_m2 sur les ventes d'entraînement et le renvoie."""
    raise NotImplementedError


def mesurer_erreur(reel, prevu):
    """Mesure l'écart entre les valeurs réelles et les valeurs prédites."""
    raise NotImplementedError
