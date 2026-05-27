"""
greengrid_analysis.py
=====================
Renewable Energy Siting Analysis – Netherlands
----------------------------------------------
Inputs  (all expected in the same folder as this script unless noted):
  - brpgewaspercelen_definitief_2025.gpkg   : agricultural parcels  (EPSG:28992)
  - BestuurlijkeGebieden_2025.gpkg          : municipality boundaries
  - NLD_power-density_100m (1).tif          : wind power density raster
  - global-pv-potential-study-raster-data-layers-globalsolaratlas/
      global-PV-potential-study--RASTER-DATA-LAYERS--GlobalSolarAtlas-info/
      derived/PVOUT_level1.tif              : solar PV output raster
  - natura2000.gpkg                         : Natura 2000 protected areas

Output:
  - greengrid_scores.gpkg                   : scored GeoDataFrame per municipality

Columns produced:
  gemeente_naam, avg_wind_wpd, avg_solar_pvout, available_land_ha,
  natura2000_overlap_pct, wind_score, solar_score, hybrid_score, conflict_flag
"""

import os
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import fiona
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterstats import zonal_stats
from shapely.ops import unary_union
import tempfile

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ─────────────────────────────────────────────────────────────────────────────
# 0.  PATHS  (all relative to script location)
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "raw")

BRP_PATH        = os.path.join(DATA_DIR, "brpgewaspercelen_definitief_2025.gpkg")
MUNI_PATH       = os.path.join(DATA_DIR, "BestuurlijkeGebieden_2025.gpkg")
WIND_TIF        = os.path.join(DATA_DIR, "NLD_wind-speed_100m.tif")
SOLAR_TIF       = os.path.join(DATA_DIR,
                    "Netherlands_GISdata_LTAy_AvgDailyTotals_GlobalSolarAtlas-v2_GEOTIFF",
                    "PVOUT.tif")
NATURA_PATH     = os.path.join(DATA_DIR, "natura2000.gpkg")
OUTPUT_PATH     = os.path.join(BASE_DIR, "greengrid_scores.gpkg")

TARGET_CRS      = "EPSG:28992"          # RD New – metric, Netherlands

# BRP categories to include as "available land"
AVAILABLE_CATS  = {"Bouwland", "Grasland"}

# ─────────────────────────────────────────────────────────────────────────────
# HELPER – clip raster to a bbox (in raster's own CRS) then reproject
# ─────────────────────────────────────────────────────────────────────────────
# Netherlands bounding box in WGS-84 (EPSG:4326) – used to window-read
# global rasters before reprojecting, avoiding planet-scale temp files.
NL_BBOX_WGS84 = (3.2, 50.7, 7.3, 53.7)   # (west, south, east, north)

def reproject_raster(src_path: str, dst_crs: str) -> str:
    """
    Clip *src_path* to the Netherlands bounding box (in src CRS),
    reproject the clip to *dst_crs*, and return path to the temp file.
    Works correctly for both Netherlands-only rasters and global rasters.
    """
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS as RioCRS
    import pyproj
    from pyproj import Transformer

    with rasterio.open(src_path) as src:
        src_crs = src.crs

        # ── Compute the clip window in the raster's native CRS ───────────────
        # Transform NL bbox corners from WGS-84 to src CRS
        try:
            transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
            xmin, ymin = transformer.transform(NL_BBOX_WGS84[0], NL_BBOX_WGS84[1])
            xmax, ymax = transformer.transform(NL_BBOX_WGS84[2], NL_BBOX_WGS84[3])
        except Exception:
            # If transform fails fall back to full raster bounds
            xmin, ymin, xmax, ymax = src.bounds

        # Intersect with actual raster bounds to avoid out-of-range windows
        xmin = max(xmin, src.bounds.left)
        ymin = max(ymin, src.bounds.bottom)
        xmax = min(xmax, src.bounds.right)
        ymax = min(ymax, src.bounds.top)

        if xmin >= xmax or ymin >= ymax:
            # Bounding boxes don't overlap — use full raster
            print("    WARNING: NL bbox does not intersect raster; using full extent.")
            xmin, ymin, xmax, ymax = src.bounds

        # ── Read clipped window ───────────────────────────────────────────────
        window = src.window(xmin, ymin, xmax, ymax)
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        clipped_transform = src.window_transform(window)
        win_width  = int(window.width)
        win_height = int(window.height)

        print(f"    Clip window: {win_width} x {win_height} px "
              f"(from {src.width} x {src.height})")

        data = src.read(window=window)
        nodata = src.nodata if src.nodata is not None else -9999

        # ── Reproject clipped data to dst_crs ────────────────────────────────
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, win_width, win_height,
            left=xmin, bottom=ymin, right=xmax, top=ymax
        )

        dst_data = np.full(
            (src.count, dst_height, dst_width),
            fill_value=nodata,
            dtype=data.dtype,
        )

        reproject(
            source=data,
            destination=dst_data,
            src_transform=clipped_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=nodata,
            dst_nodata=nodata,
        )

        kwargs = src.meta.copy()
        kwargs.update({
            "crs":       dst_crs,
            "transform": dst_transform,
            "width":     dst_width,
            "height":    dst_height,
            "nodata":    nodata,
            "count":     src.count,
        })

        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        tmp.close()
        with rasterio.Env(CHECK_DISK_FREE_SPACE="FALSE"):
            with rasterio.open(tmp.name, "w", **kwargs) as dst:
                dst.write(dst_data)

        size_mb = os.path.getsize(tmp.name) / 1e6
        print(f"    Written {size_mb:.1f} MB -> {tmp.name}")
        return tmp.name


# ─────────────────────────────────────────────────────────────────────────────
# HELPER – normalise a pd.Series to [0, 1]
# ─────────────────────────────────────────────────────────────────────────────
def minmax_norm(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 – Load and reproject municipality boundaries
# ═════════════════════════════════════════════════════════════════════════════
print("\n[1/7] Loading municipality boundaries …")

# Inspect available layers
muni_layers = fiona.listlayers(MUNI_PATH)
print(f"  Layers in BestuurlijkeGebieden: {muni_layers}")

# Pick the municipality (gemeente) layer – usually contains 'gemeente' in its name
muni_layer = next(
    (l for l in muni_layers if "gemeente" in l.lower()),
    muni_layers[0]
)
print(f"  Using layer: {muni_layer}")

muni = gpd.read_file(MUNI_PATH, layer=muni_layer)
print(f"  Loaded {len(muni)} municipalities, CRS: {muni.crs}")
muni = muni.to_crs(TARGET_CRS)

# Identify the name column (commonly 'naam' or 'gemeentenaam')
name_col = next(
    (c for c in muni.columns if c.lower() in ("naam", "gemeentenaam", "gm_naam")),
    muni.columns[0]
)
print(f"  Municipality name column: '{name_col}'")
muni = muni.rename(columns={name_col: "gemeente_naam"})

# Keep only essential columns + geometry
muni = muni[["gemeente_naam", "geometry"]].copy()
muni["muni_area_m2"] = muni.geometry.area        # used for % calculations later
muni = muni.reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 – Zonal statistics: Wind power density
# ═════════════════════════════════════════════════════════════════════════════
print("\n[2/7] Computing wind power density zonal statistics …")

wind_tif_28992 = reproject_raster(WIND_TIF, TARGET_CRS)
wind_stats = zonal_stats(
    muni,
    wind_tif_28992,
    stats=["mean"],
    nodata=-9999,
    geojson_out=False,
    all_touched=False,
)
muni["avg_wind_wpd"] = [s["mean"] if s["mean"] is not None else np.nan
                        for s in wind_stats]
print(f"  Wind WPD – min: {muni['avg_wind_wpd'].min():.2f}  "
      f"max: {muni['avg_wind_wpd'].max():.2f}  "
      f"(W/m²)  NaN: {muni['avg_wind_wpd'].isna().sum()}")

# Clean up temp file if we created one
if wind_tif_28992 != WIND_TIF:
    os.unlink(wind_tif_28992)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 – Zonal statistics: Solar PV output
# ═════════════════════════════════════════════════════════════════════════════
print("\n[3/7] Computing solar PV output zonal statistics …")

solar_tif_28992 = reproject_raster(SOLAR_TIF, TARGET_CRS)
solar_stats = zonal_stats(
    muni,
    solar_tif_28992,
    stats=["mean"],
    nodata=-9999,
    geojson_out=False,
    all_touched=False,
)
muni["avg_solar_pvout"] = [s["mean"] if s["mean"] is not None else np.nan
                           for s in solar_stats]
print(f"  Solar PVOUT – min: {muni['avg_solar_pvout'].min():.4f}  "
      f"max: {muni['avg_solar_pvout'].max():.4f}  "
      f"NaN: {muni['avg_solar_pvout'].isna().sum()}")

if solar_tif_28992 != SOLAR_TIF:
    os.unlink(solar_tif_28992)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 – BRP parcel join → available land (Bouwland / Grasland)
# ═════════════════════════════════════════════════════════════════════════════
print("\n[4/7] Processing BRP agricultural parcels …")

brp_layers = fiona.listlayers(BRP_PATH)
print(f"  BRP layers: {brp_layers}")
brp_layer = brp_layers[0]   # typically only one layer

# Read only the columns we need to save memory on 2.33 M polygons
with fiona.open(BRP_PATH, layer=brp_layer) as src:
    # Use schema to get property names (fiona integer indexing is unreliable on GPKG)
    if src.schema and src.schema.get("properties"):
        sample_props = list(src.schema["properties"].keys())
    else:
        first_feat = next(iter(src), None)
        sample_props = list(first_feat["properties"].keys()) if first_feat else []
    print(f"  BRP columns: {sample_props}")

# Find the category column
cat_col = next(
    (c for c in sample_props
     if c.lower() in ("gewasgroep", "category", "categorie", "cat", "hoofdgewasgroep")),
    None
)
if cat_col is None:
    print("  WARNING: Could not auto-detect category column. Available columns:")
    for c in sample_props:
        print(f"    {c}")
    raise ValueError(
        "Please inspect the BRP columns above and set 'cat_col' manually in the script."
    )
print(f"  Using category column: '{cat_col}'")

# Read with column filter
print("  Reading BRP (this may take a few minutes for 2.33 M rows) …")
brp = gpd.read_file(BRP_PATH, layer=brp_layer, columns=[cat_col])
print(f"  Loaded {len(brp)} parcels, CRS: {brp.crs}")

# Reproject if needed
if brp.crs.to_epsg() != 28992:
    print("  Reprojecting BRP to EPSG:28992 …")
    brp = brp.to_crs(TARGET_CRS)

# Filter to available categories (case-insensitive partial match)
def is_available(val):
    if val is None:
        return False
    val_lower = str(val).lower()
    return any(cat.lower() in val_lower for cat in AVAILABLE_CATS)

brp_avail = brp[brp[cat_col].apply(is_available)].copy()
print(f"  Available parcels (Bouwland/Grasland): {len(brp_avail):,}")

# Add parcel area in m²
brp_avail["parcel_area_m2"] = brp_avail.geometry.area

# Spatial join to municipalities (use centroid for speed on large dataset)
print("  Spatial join BRP → municipalities …")
brp_avail["centroid"] = brp_avail.geometry.centroid
brp_centroids = brp_avail.set_geometry("centroid")
joined = gpd.sjoin(brp_centroids, muni[["gemeente_naam", "geometry"]],
                   how="inner", predicate="within")

# Sum area per municipality
land_by_muni = (joined
                .groupby("gemeente_naam")["parcel_area_m2"]
                .sum()
                .rename("available_land_m2")
                .reset_index())
land_by_muni["available_land_ha"] = land_by_muni["available_land_m2"] / 10_000

muni = muni.merge(land_by_muni[["gemeente_naam", "available_land_ha"]],
                  on="gemeente_naam", how="left")
muni["available_land_ha"] = muni["available_land_ha"].fillna(0.0)
print(f"  Total available land: {muni['available_land_ha'].sum():,.0f} ha")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 – Natura 2000 overlap
# ═════════════════════════════════════════════════════════════════════════════
print("\n[5/7] Computing Natura 2000 overlap …")

natura_layers = fiona.listlayers(NATURA_PATH)
print(f"  Natura 2000 layers: {natura_layers}")
natura = gpd.read_file(NATURA_PATH, layer=natura_layers[0])
print(f"  Loaded {len(natura)} Natura 2000 polygons, CRS: {natura.crs}")
natura = natura.to_crs(TARGET_CRS)

# Dissolve to a single union geometry for efficiency
print("  Dissolving Natura 2000 geometries …")
natura_union = unary_union(natura.geometry)

# Compute intersection area per municipality
def natura_overlap_m2(geom):
    try:
        return geom.intersection(natura_union).area
    except Exception:
        return 0.0

print("  Computing intersection areas (may take ~1-2 min) …")
muni["natura2000_area_m2"] = muni.geometry.apply(natura_overlap_m2)
muni["natura2000_overlap_pct"] = (
    muni["natura2000_area_m2"] / muni["muni_area_m2"] * 100
).clip(0, 100)
print(f"  Mean Natura 2000 overlap: {muni['natura2000_overlap_pct'].mean():.1f}%")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 – Normalise scores and derive flags
# ═════════════════════════════════════════════════════════════════════════════
print("\n[6/7] Normalising scores …")

muni["wind_score"]  = minmax_norm(muni["avg_wind_wpd"].fillna(0))
muni["solar_score"] = minmax_norm(muni["avg_solar_pvout"].fillna(0))
muni["hybrid_score"] = (muni["wind_score"] + muni["solar_score"]) / 2

def classify_conflict(pct):
    if pct <= 15:
        return "none"
    elif pct <= 40:
        return "low"
    elif pct <= 70:
        return "medium"
    else:
        return "high"

muni["conflict_level"] = muni["natura2000_overlap_pct"].apply(classify_conflict)
muni["conflict_flag"] = muni["natura2000_overlap_pct"] > 15.0

print(muni["conflict_level"].value_counts())


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7 – Export final GeoDataFrame
# ═════════════════════════════════════════════════════════════════════════════
print("\n[7/7] Exporting greengrid_scores.gpkg …")

OUTPUT_COLS = [
    "gemeente_naam",
    "avg_wind_wpd",
    "avg_solar_pvout",
    "available_land_ha",
    "natura2000_overlap_pct",
    "wind_score",
    "solar_score",
    "hybrid_score",
    "conflict_flag",
    "conflict_level",
    "geometry",
]

result = muni[OUTPUT_COLS].copy()

# Round floats for cleaner output
for col in ["avg_wind_wpd", "avg_solar_pvout", "available_land_ha",
            "natura2000_overlap_pct", "wind_score", "solar_score", "hybrid_score"]:
    result[col] = result[col].round(4)

result.to_file(OUTPUT_PATH, driver="GPKG")
print(f"  Done. Saved {len(result)} municipality rows -> {OUTPUT_PATH}")

# ─── Summary table ───────────────────────────────────────────────────────────
print("\n" + "="*65)
print("GREENGRID ANALYSIS COMPLETE – Top 10 by hybrid_score")
print("="*65)
top10 = (result.drop(columns="geometry")
               .sort_values("hybrid_score", ascending=False)
               .head(10))
print(top10.to_string(index=False))
print("="*65)
print(f"\nOutput: {OUTPUT_PATH}")

# ── Full GeoPackage export with all layers ────────────────────────────────
full_gpkg_path = os.path.join(BASE_DIR, "greengrid_full.gpkg")

# Layer 1: Municipalities with scores (polygons)
result.to_file(full_gpkg_path, layer="municipalities", driver="GPKG")
print(f"  Layer 1 written: municipalities ({len(result)} rows)")

# Layer 2: All available BRP parcels with municipality name attached (polygons)
brp_avail_export = joined[["gemeente_naam", cat_col, "parcel_area_m2", "geometry"]].copy()
brp_avail_export = brp_avail_export.rename(columns={cat_col: "category"})
brp_avail_export["parcel_area_ha"] = (brp_avail_export["parcel_area_m2"] / 10_000).round(4)
brp_avail_export = brp_avail_export.drop(columns="parcel_area_m2")
brp_avail_export = gpd.GeoDataFrame(brp_avail_export, geometry="geometry", crs=TARGET_CRS)
brp_avail_export.to_file(full_gpkg_path, layer="parcels_available", driver="GPKG")
print(f"  Layer 2 written: parcels_available ({len(brp_avail_export)} rows)")

# Layer 3: Natura 2000 protected areas (polygons)
natura.to_file(full_gpkg_path, layer="natura2000", driver="GPKG")
print(f"  Layer 3 written: natura2000 ({len(natura)} rows)")

# Layer 4: Crop area aggregated per municipality (no geometry — attribute table)
df_crop_muni = (joined
                .groupby(["gemeente_naam", cat_col])["parcel_area_m2"]
                .sum()
                .reset_index()
                .rename(columns={cat_col: "category", "parcel_area_m2": "total_area_m2"}))
df_crop_muni["total_area_ha"] = (df_crop_muni["total_area_m2"] / 10_000).round(2)
df_crop_muni = df_crop_muni.drop(columns="total_area_m2")
# Add municipality geometry so it becomes a spatial layer
df_crop_muni = df_crop_muni.merge(result[["gemeente_naam", "geometry"]], on="gemeente_naam", how="left")
df_crop_muni = gpd.GeoDataFrame(df_crop_muni, geometry="geometry", crs=TARGET_CRS)
df_crop_muni.to_file(full_gpkg_path, layer="crop_area_per_municipality", driver="GPKG")
print(f"  Layer 4 written: crop_area_per_municipality ({len(df_crop_muni)} rows)")

print(f"\nFull GeoPackage saved -> {full_gpkg_path}")
print(f"  Open in QGIS to explore all 4 layers visually")