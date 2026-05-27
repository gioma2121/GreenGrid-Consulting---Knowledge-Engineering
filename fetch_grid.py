"""
fetch_grid.py
=============
Fetches Dutch power line geometries from OpenStreetMap Overpass API
and saves them to greengrid_full.gpkg as a new layer, also computing
grid_distance_km for each municipality.
"""

import os
import requests
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import unary_union

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GPKG_PATH = os.path.join(BASE_DIR, "greengrid_full.gpkg")
TARGET_CRS = "EPSG:28992"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – Fetch power lines from OSM
# ─────────────────────────────────────────────────────────────────────────────
print("[1/3] Querying OpenStreetMap Overpass API ...")

query = """
[out:json][timeout:120];
area["name"="Nederland"]["admin_level"="2"]->.nl;
(
  way["power"="line"](area.nl);
  way["power"="cable"](area.nl);
);
out geom;
"""

try:
    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers={"User-Agent": "GreenGrid-KnowledgeEngineering/1.0"},
        timeout=180
    )
    r.raise_for_status()
    elements = r.json().get("elements", [])
    print(f"  Retrieved {len(elements)} elements from OSM")

except requests.exceptions.Timeout:
    print("  ERROR: Request timed out. Try again later or use a mirror.")
    exit()
except requests.exceptions.RequestException as e:
    print(f"  ERROR: {e}")
    exit()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – Build GeoDataFrame from OSM geometries
# ─────────────────────────────────────────────────────────────────────────────
print("[2/3] Building GeoDataFrame ...")

lines = []
for el in elements:
    if el.get("type") == "way" and "geometry" in el:
        coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
        if len(coords) >= 2:
            lines.append(LineString(coords))

if not lines:
    print("  ERROR: No line geometries found in OSM response.")
    exit()

powerlines = gpd.GeoDataFrame(geometry=lines, crs="EPSG:4326")
powerlines = powerlines.to_crs(TARGET_CRS)
print(f"  Built {len(powerlines)} power line geometries in EPSG:28992")

# Save to GeoPackage
powerlines.to_file(GPKG_PATH, layer="power_lines", driver="GPKG")
print(f"  Layer power_lines written to {GPKG_PATH}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – Compute grid_distance_km per municipality
# ─────────────────────────────────────────────────────────────────────────────
print("[3/3] Computing grid proximity per municipality ...")

muni = gpd.read_file(GPKG_PATH, layer="municipalities")

grid_union = unary_union(powerlines.geometry)

muni["grid_distance_km"] = (
    muni.geometry.centroid
    .apply(lambda pt: pt.distance(grid_union) / 1000)
    .round(3)
)

print(f"  grid_distance_km – min: {muni['grid_distance_km'].min():.2f} km  "
      f"max: {muni['grid_distance_km'].max():.2f} km  "
      f"mean: {muni['grid_distance_km'].mean():.2f} km")

print("\n  Top 10 furthest from grid:")
print(muni[["gemeente_naam", "grid_distance_km"]]
      .sort_values("grid_distance_km", ascending=False)
      .head(10).to_string(index=False))

print("\n  Top 10 closest to grid:")
print(muni[["gemeente_naam", "grid_distance_km"]]
      .sort_values("grid_distance_km")
      .head(10).to_string(index=False))

# Overwrite municipalities layer with updated grid_distance_km column
muni.to_file(GPKG_PATH, layer="municipalities", driver="GPKG")
print(f"\n  municipalities layer updated in {GPKG_PATH}")
print("Done.")