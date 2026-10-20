"""Script de travail : explore les données DVF d'un département et teste les fonctions de immo.py.

À lancer depuis la racine du projet : python explorer.py
"""

import logging

from immo import DATA_DIR, charger, nettoyer, prix_par_commune

logging.basicConfig(level=logging.INFO, format="%(message)s")  # affiche le journal de nettoyer()

DEPARTEMENT = "51"

# --- Fichier brut ---
df = charger(DEPARTEMENT)
print(df.shape)
print(df["annee"].value_counts().sort_index())  # lignes par année
print(df.columns)    # la liste des noms de colonnes
print(df.head())     # les 5 premières lignes

# Répartition des types de biens (dropna=False : compte aussi les cases vides)
code_counts = df["type_local"].value_counts(dropna=False)
print(code_counts)

# --- Lignes sans type_local ---
sans_type = df[df["type_local"].isna()]  # filtre : on garde les lignes où type_local est vide
print(len(sans_type))                                # combien de lignes
print(sans_type["surface_terrain"].notna().sum())    # combien ont une surface de terrain
print(sans_type["nature_culture"].notna().sum())     # combien ont une nature de culture

# Les lignes sans nature_culture ni surface_terrain (& = ET)
inclassables = sans_type[sans_type["nature_culture"].isna() & sans_type["surface_terrain"].isna()]
print(len(inclassables))
print(inclassables[["nature_mutation", "valeur_fonciere", "nombre_lots", "id_parcelle"]].head())

# --- Lignes sans surface_reelle_bati, par type_local ---
sans_surface = df[df["surface_reelle_bati"].isna()]
print(sans_surface["type_local"].value_counts(dropna=False))

print(df.isna().sum())  # nombre de valeurs manquantes par colonne

# --- Nettoyage ---
propre = nettoyer(df)
print(propre.shape)
print(propre[["nom_commune", "type_local", "valeur_fonciere", "surface_reelle_bati", "prix_m2"]].head())
print(propre["prix_m2"].describe().round(0))

# --- Prix par commune ---
prix = prix_par_commune(propre)
print(prix.shape)
print(prix.head())
prix.to_csv(DATA_DIR / "prix_communes.csv", index=False)
