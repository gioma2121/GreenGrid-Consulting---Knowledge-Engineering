"""
fetch_cbs.py
============
Fetches population density per municipality from CBS Statline API.
"""

import os
import requests
import pandas as pd
import geopandas as gpd

try:
    import cbsodata
except ImportError:
    os.system("pip install cbsodata")
    import cbsodata

try:
    from rapidfuzz import process, fuzz
except ImportError:
    os.system("pip install rapidfuzz")
    from rapidfuzz import process, fuzz

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GPKG_PATH = os.path.join(BASE_DIR, "data", "processed", "greengrid_full.gpkg")
CACHE_PATH = os.path.join(BASE_DIR, "data", "raw", "cbs_70072ned.csv")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – Fetch full CBS table (no filter)
# ─────────────────────────────────────────────────────────────────────────────
import time

print("[1/3] Fetching CBS data ...")
if os.path.exists(CACHE_PATH):
    print(f"  Loading from cache: {CACHE_PATH}")
    df = pd.read_csv(CACHE_PATH)
    print(f"  Loaded {len(df)} rows from cache")
else:
    df = None
    for attempt in range(1, 6):
        try:
            print(f"  Attempt {attempt}/5 ...")
            df = pd.DataFrame(cbsodata.get_data('70072ned'))
            print(f"  Retrieved {len(df)} rows")
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            df.to_csv(CACHE_PATH, index=False)
            print(f"  Cached to {CACHE_PATH}")
            break
        except Exception as e:
            print(f"  Failed: {e}")
            if attempt < 5:
                print("  Waiting 10 seconds ...")
                time.sleep(10)
    if df is None:
        print("  ERROR: All attempts failed. Try again later.")
        exit()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – Filter in pandas
# ─────────────────────────────────────────────────────────────────────────────
print("[2/3] Filtering ...")

cbs = df[["RegioS", "Perioden",
          "TotaleBevolking_1",
          "Bevolkingsdichtheid_57"]].copy()

# Load municipality names from GeoPackage to use as reference
muni = gpd.read_file(GPKG_PATH, layer="municipalities")
muni_names = set(muni["gemeente_naam"].tolist())

# Filter CBS to most recent year
available_years = sorted(cbs["Perioden"].unique())
print(f"  Available years (last 5): {available_years[-5:]}")
most_recent = available_years[-1]
print(f"  Using year: {most_recent}")
cbs = cbs[cbs["Perioden"] == most_recent].copy()

# Filter to rows where RegioS matches a known municipality name
cbs_muni = cbs[cbs["RegioS"].str.strip().isin(muni_names)].copy()
print(f"  Direct name matches: {len(cbs_muni)}")

cbs_muni = cbs_muni.rename(columns={
    "RegioS":                 "gemeente_naam",
    "TotaleBevolking_1":      "population",
    "Bevolkingsdichtheid_57": "pop_density_km2"
})
cbs_muni["gemeente_naam"] = cbs_muni["gemeente_naam"].str.strip()
cbs_muni = cbs_muni[["gemeente_naam", "population",
                      "pop_density_km2"]].reset_index(drop=True)

print(f"\n  Sample:")
print(cbs_muni.head(10).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – Merge + fuzzy match for unmatched
# ─────────────────────────────────────────────────────────────────────────────

print("\n[3/3] Joining to municipalities layer ...")
# Drop columns if they already exist from a previous run
for col in ["population", "pop_density_km2"]:
    if col in muni.columns:
        muni = muni.drop(columns=[col])

muni = muni.merge(cbs_muni, on="gemeente_naam", how="left")

# Manual mapping for known name differences
manual_map = {
    "Utrecht":       "Utrecht (gemeente)",
    "Groningen":     "Groningen (gemeente)",
    "'s-Gravenhage": "'s-Gravenhage (gemeente)",
    "Laren":         "Laren (NH.)",
    "Beek":          "Beek (L.)",
    "Stein":         "Stein (L.)",
    "Rijswijk":      "Rijswijk (ZH.)",
    "Middelburg":    "Middelburg (Z.)",
    "Bergen (L)":    "Bergen (L.)",
    "Bergen (NH)":   "Bergen (NH.)",
    "Hengelo (O)":   "Hengelo (O.)",
}

print("\n  Applying manual name mapping ...")
for orig, cbs_name in manual_map.items():
    cbs_row = cbs[cbs["RegioS"].str.strip() == cbs_name]
    if not cbs_row.empty:
        print(f"    '{orig}' → '{cbs_name}' ✓")
        muni.loc[muni["gemeente_naam"] == orig, "population"] = \
            cbs_row["TotaleBevolking_1"].values[0]
        muni.loc[muni["gemeente_naam"] == orig, "pop_density_km2"] = \
            cbs_row["Bevolkingsdichtheid_57"].values[0]
    else:
        print(f"    '{orig}' → '{cbs_name}' NOT FOUND IN CBS")

# Final report
still_unmatched = muni[muni["pop_density_km2"].isna()]["gemeente_naam"].tolist()
print(f"\n  Final unmatched: {len(still_unmatched)}")
if still_unmatched:
    print(f"  {still_unmatched}")

print(f"\n  pop_density_km2 – "
      f"min: {muni['pop_density_km2'].min():.1f}  "
      f"max: {muni['pop_density_km2'].max():.1f}  "
      f"mean: {muni['pop_density_km2'].mean():.1f}")

print(f"\n  Top 10 most densely populated:")
print(muni[["gemeente_naam", "pop_density_km2", "hybrid_score"]]
      .sort_values("pop_density_km2", ascending=False)
      .head(10).to_string(index=False))

print(f"\n  Top 10 least densely populated:")
print(muni[["gemeente_naam", "pop_density_km2", "hybrid_score"]]
      .sort_values("pop_density_km2")
      .head(10).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – Fetch gemeente → provincie mapping from PDOK WFS
# ─────────────────────────────────────────────────────────────────────────────
print("\n[4/4] Fetching gemeente → provincie mapping from PDOK ...")

PDOK_BASE = (
    "https://service.pdok.nl/cbs/gebiedsindelingen/2024/wfs/v1_0"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeName=gebiedsindelingen:{layer}"
    "&outputFormat=application/json"
    "&count=1000"
)

try:
    # Fetch gemeente labelpoints (centroid per gemeente, small download)
    resp_g = requests.get(PDOK_BASE.format(layer="gemeente_labelpoint"), timeout=30)
    resp_g.raise_for_status()
    gdf_gemeente = gpd.GeoDataFrame.from_features(
        resp_g.json()["features"], crs="EPSG:28992"
    )[["statnaam", "geometry"]]
    print(f"  Fetched {len(gdf_gemeente)} gemeente labelpoints")

    # Fetch province polygons
    resp_p = requests.get(PDOK_BASE.format(layer="provincie_gegeneraliseerd"), timeout=30)
    resp_p.raise_for_status()
    gdf_prov = gpd.GeoDataFrame.from_features(
        resp_p.json()["features"], crs="EPSG:28992"
    )[["statnaam", "geometry"]].rename(columns={"statnaam": "provincie_naam"})
    print(f"  Fetched {len(gdf_prov)} province polygons")

    # Point-in-polygon join
    joined = gpd.sjoin(gdf_gemeente, gdf_prov, predicate="within", how="left")
    prov_map = dict(zip(joined["statnaam"], joined["provincie_naam"]))
    print(f"  Resolved {sum(v is not None for v in prov_map.values())}/{len(prov_map)} mappings")

    # PDOK uses "Bergen (NH.)" while our dataset uses "Bergen (NH)" — strip
    # the dot before the closing parenthesis so both key forms are in the map
    import re
    prov_map_normalized = {
        re.sub(r"\.\)", ")", k): v for k, v in prov_map.items()
    }
    prov_map.update(prov_map_normalized)

    muni["provincie_naam"] = muni["gemeente_naam"].map(prov_map)

    # Municipalities whose names are ambiguous in PDOK (plain name vs. "(XX.)" suffix)
    province_fallback = {
        "Beek":       "Limburg",
        "Laren":      "Noord-Holland",
        "Middelburg": "Zeeland",
        "Stein":      "Limburg",
        "Rijswijk":   "Zuid-Holland",
    }
    for gem, prov in province_fallback.items():
        muni.loc[muni["gemeente_naam"] == gem, "provincie_naam"] = prov

    unmatched = muni[muni["provincie_naam"].isna()]["gemeente_naam"].tolist()
    if unmatched:
        print(f"  Unmatched ({len(unmatched)}): {unmatched}")

    print(f"  Matched: {muni['provincie_naam'].notna().sum()}/{len(muni)}")
    print(f"  Provinces found: {sorted(muni['provincie_naam'].dropna().unique())}")

except Exception as e:
    print(f"  WARNING: Could not fetch province mapping: {e}")
    print("  provincie_naam column will not be added — BELONGS_TO_PROVINCE edges won't load.")

# Save
muni.to_file(GPKG_PATH, layer="municipalities", driver="GPKG")
print(f"\n  municipalities layer updated in {GPKG_PATH}")
print("Done.")