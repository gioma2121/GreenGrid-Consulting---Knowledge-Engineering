import geopandas as gpd
import pandas as pd

# Controlla i layer disponibili
import fiona
print(fiona.listlayers("greengrid_full.gpkg"))

# Carica il layer principale
muni = gpd.read_file("greengrid_full.gpkg", layer="municipalities")

# Struttura e statistiche
print(muni.shape)
print(muni.dtypes)
print(muni.describe())


# Top 10 per hybrid score
print(muni.sort_values("hybrid_score", ascending=False)
         [["gemeente_naam","wind_score","solar_score","hybrid_score","conflict_flag"]]
         .head(10))

# Top 10 conflict-FREE (i candidati reali)
clean = muni[muni["conflict_flag"] == False]
print(clean.sort_values("hybrid_score", ascending=False)
          [["gemeente_naam","wind_score","solar_score","hybrid_score","available_land_ha"]]
          .head(10))

# Quanti conflitti?
print(f"Conflitti: {muni['conflict_flag'].sum()} / {len(muni)}")


import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(18, 6))

muni.plot(column="wind_score", ax=axes[0], cmap="Blues", 
          legend=True, missing_kwds={"color":"lightgrey"})
axes[0].set_title("Wind Score")
axes[0].axis("off")

muni.plot(column="solar_score", ax=axes[1], cmap="Oranges",
          legend=True, missing_kwds={"color":"lightgrey"})
axes[1].set_title("Solar Score")
axes[1].axis("off")

muni.plot(column="hybrid_score", ax=axes[2], cmap="Greens",
          legend=True, missing_kwds={"color":"lightgrey"})
axes[2].set_title("Hybrid Score")
axes[2].axis("off")

plt.tight_layout()
plt.savefig("greengrid_scores_map.png", dpi=150)
plt.show()

fig, ax = plt.subplots(figsize=(10, 10))

# Base: hybrid score
muni.plot(column="hybrid_score", ax=ax, cmap="YlGn", legend=True, alpha=0.8)

# Overlay: comuni conflittuali in rosso
muni[muni["conflict_flag"]].boundary.plot(ax=ax, color="red", linewidth=1.2, label="Conflitto Natura 2000")

ax.set_title("Hybrid Score + Natura 2000 Conflicts", fontsize=14)
ax.axis("off")
plt.legend()
plt.savefig("greengrid_conflicts_map.png", dpi=150)
plt.show()

# Parcelle disponibili
parcels = gpd.read_file("greengrid_full.gpkg", layer="parcels_available")
print(parcels.head())
print(parcels["category"].value_counts())

# Natura 2000
natura = gpd.read_file("greengrid_full.gpkg", layer="natura2000")
print(f"Aree protette: {len(natura)}")
print(natura.columns.tolist())

# Land use per comune
crops = gpd.read_file("greengrid_full.gpkg", layer="crop_area_per_municipality")
print(crops.groupby("category")["total_area_ha"].sum().sort_values(ascending=False))