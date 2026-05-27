"""
test.py
=======
Inspects the full greengrid_full.gpkg dataset to verify all columns
are present and properly populated before building the dashboard.
"""

import os
import geopandas as gpd
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GPKG_PATH = os.path.join(BASE_DIR, "greengrid_full.gpkg")

print("=" * 65)
print("GREENGRID DATASET INSPECTION")
print("=" * 65)

# ─────────────────────────────────────────────────────────────────────────────
# Load municipalities layer
# ─────────────────────────────────────────────────────────────────────────────
muni = gpd.read_file(GPKG_PATH, layer="municipalities")

print(f"\n── SHAPE ───────────────────────────────────────────────────")
print(f"  Rows: {len(muni)}")
print(f"  Columns: {len(muni.columns)}")

print(f"\n── COLUMNS ─────────────────────────────────────────────────")
for col in muni.columns:
    dtype = muni[col].dtype
    nulls = muni[col].isna().sum()
    print(f"  {col:<35} dtype: {str(dtype):<15} nulls: {nulls}")

print(f"\n── NUMERIC SUMMARY ─────────────────────────────────────────")
numeric_cols = [
    "wind_score", "solar_score", "hybrid_score",
    "available_land_ha", "natura2000_overlap_pct",
    "grid_distance_km", "pop_density_km2", "population"
]
for col in numeric_cols:
    if col in muni.columns:
        s = muni[col]
        print(f"  {col:<35} min: {s.min():>10.2f}  "
              f"max: {s.max():>10.2f}  "
              f"mean: {s.mean():>10.2f}  "
              f"nulls: {s.isna().sum()}")
    else:
        print(f"  {col:<35} *** MISSING ***")

print(f"\n── CONFLICT LEVEL DISTRIBUTION ─────────────────────────────")
print(muni["conflict_level"].value_counts())

print(f"\n── TOP 10 CONFLICT-FREE BY HYBRID SCORE ────────────────────")
clean = muni[muni["conflict_flag"] == False].copy()
print(f"  Total conflict-free municipalities: {len(clean)}")
print(clean.sort_values("hybrid_score", ascending=False)[[
    "gemeente_naam", "hybrid_score", "wind_score", "solar_score",
    "available_land_ha", "grid_distance_km", "pop_density_km2"
]].head(10).to_string(index=False))

print(f"\n── TOP 10 OVERALL BY HYBRID SCORE ──────────────────────────")
print(muni.sort_values("hybrid_score", ascending=False)[[
    "gemeente_naam", "hybrid_score", "conflict_level",
    "grid_distance_km", "pop_density_km2"
]].head(10).to_string(index=False))

print(f"\n── CRS ─────────────────────────────────────────────────────")
print(f"  {muni.crs}")

print(f"\n── SAMPLE ROW (first conflict-free municipality) ───────────")
sample = clean.sort_values("hybrid_score", ascending=False).iloc[0]
for col in muni.columns:
    if col != "geometry":
        print(f"  {col:<35} {sample[col]}")

print("\n" + "=" * 65)
print("INSPECTION COMPLETE")
print("=" * 65)