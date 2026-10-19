import pandas as pd
from immo import charger, nettoyer

df = pd.read_csv("data/51.csv", dtype={"code_departement": str, "code_commune": str, "code_postal": str})
print(df.shape)  
print(df.columns)    # la liste des noms de colonnes
print(df.head())      # les 5 premières lignes

code_counts = df["type_local"].value_counts(dropna=False)  # compter les occurrences de chaque type de local, y compris les NaN
print(code_counts)

# --- Test 1 : les lignes sans type_local (des terrains ?) ---
sans_type = df[df["type_local"].isna()]  # filtre : on garde les lignes où type_local est vide
print(len(sans_type))                                # combien de lignes
print(sans_type["surface_terrain"].notna().sum())    # combien ont une surface de terrain
print(sans_type["nature_culture"].notna().sum())     # combien ont une nature de culture

# les "inclassables" : ni nature_culture ni surface_terrain (& = ET)
inclassables = sans_type[sans_type["nature_culture"].isna() & sans_type["surface_terrain"].isna()]
print(len(inclassables))
print(inclassables[["nature_mutation", "valeur_fonciere", "nombre_lots", "id_parcelle"]].head())

# --- Test 2 : les lignes sans surface_reelle_bati, par type_local ---
sans_surface = df[df["surface_reelle_bati"].isna()]
print(sans_surface["type_local"].value_counts(dropna=False))

print(df.isna().sum())  # compter le nombre de valeurs manquantes par colonne

# --- Étape 2 : test de nettoyer() ---
propre = nettoyer(charger("51"), verbose=True)
print(propre.shape)
print(propre[["nom_commune", "type_local", "valeur_fonciere", "surface_reelle_bati", "prix_m2"]].head())
print(propre["prix_m2"].describe().round(0))