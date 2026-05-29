import os
import geopandas as gpd
import fiona

gpkg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw", "brpgewaspercelen_definitief_2025.gpkg")

# ── 1. List all layers ──────────────────────────────────────────────
layers = fiona.listlayers(gpkg_path)
print(f"Layers found ({len(layers)}):", layers)

# ── 2. Explore each layer ───────────────────────────────────────────
for layer in layers:
    print(f"\n{'='*60}")
    print(f"LAYER: {layer}")
    print('='*60)

    gdf = gpd.read_file(gpkg_path, layer=layer)

    print(f"  Feature count   : {len(gdf)}")
    print(f"  Geometry type   : {gdf.geom_type.unique()}")
    print(f"  CRS             : {gdf.crs}")
    print(f"  Bounding box    : {gdf.total_bounds}")
    print(f"  Columns ({len(gdf.columns)}): {list(gdf.columns)}")
    print(f"\n  Data types:\n{gdf.dtypes}")
    print(f"\n  Missing values:\n{gdf.isnull().sum()}")
    print(f"\n  First 3 rows:\n{gdf.head(3)}")

    # Basic stats for numeric columns
    numeric_cols = gdf.select_dtypes(include='number').columns.tolist()
    if numeric_cols:
        print(f"\n  Numeric summary:\n{gdf[numeric_cols].describe()}")