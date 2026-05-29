"""
GreenGrid Knowledge Graph — Neo4j loading script
=================================================
Reads greengrid_full.gpkg and populates a Neo4j instance in two tiers:

  Tier 1 (default):  Municipality, Province, Natura2000Site, GridSegment,
                     and all classification nodes + every relationship.
                     ~1 000 nodes, ~8 000 edges.  Loads in < 2 minutes.

  Tier 2 (--parcels): also loads 1.29M Parcel nodes with LOCATED_IN and
                     HAS_CROP_TYPE edges.  Memory-intensive; only needed
                     if your competency questions require parcel-level detail.

Usage
-----
  # Set credentials via env vars (or edit the CONFIG block below)
  export NEO4J_URI=bolt://localhost:7687
  export NEO4J_USER=neo4j
  export NEO4J_PASS=your_password

  # Tier 1 (recommended for the course project)
  python load_kg.py --gpkg greengrid_full.gpkg

  # Tier 2 (full parcel load)
  python load_kg.py --gpkg greengrid_full.gpkg --parcels

Dependencies
------------
  pip install neo4j geopandas pandas numpy scipy shapely
"""

import os
import sys
import logging
import argparse

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree
from shapely.ops import unary_union, nearest_points
from neo4j import GraphDatabase

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── CONFIG (override via env vars or edit here) ─────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI",  "neo4j+s://14361706.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "14361706")
NEO4J_PASS = os.getenv("NEO4J_PASS", "SWxo6d9xO3xKXNZGrxKyQsY6tQ-drdTdl8sYdTLUbKo")

NEAR_TO_K    = 10    # top-K nearest neighbours per municipality
ADJ_BUFFER_M = 50    # buffer in metres to detect shared-border adjacency
BATCH        = 500   # rows per UNWIND batch


# ─── Helpers ─────────────────────────────────────────────────────────────────
def batch_write(session, cypher: str, rows: list, label: str = "") -> None:
    """Write `rows` to Neo4j in batches of BATCH using UNWIND."""
    if not rows:
        log.warning("  %s — no rows to write, skipping", label)
        return
    for i in range(0, len(rows), BATCH):
        session.run(cypher, rows=rows[i : i + BATCH])
    log.info("  %s: wrote %d rows", label, len(rows))


def coerce(val, typ, default):
    """Safe type coercion for dirty GeoPackage values."""
    try:
        return typ(val)
    except (TypeError, ValueError):
        return default


# ─── Layer loaders ───────────────────────────────────────────────────────────
def load_layers(gpkg_path: str):
    """Return (muni, natura, grid, parcels) GeoDataFrames in EPSG:28992."""
    log.info("Reading GeoPackage: %s", gpkg_path)

    muni = gpd.read_file(gpkg_path, layer="municipalities").to_crs(28992)
    log.info("  municipalities: %d rows, columns: %s",
             len(muni), list(muni.columns))

    natura = gpd.read_file(gpkg_path, layer="natura2000").to_crs(28992)
    log.info("  natura2000: %d rows", len(natura))

    try:
        grid = gpd.read_file(gpkg_path, layer="grid_lines").to_crs(28992)
        log.info("  grid_lines: %d rows", len(grid))
    except Exception:
        try:
            # Vaggelis saved it as power_lines in some versions
            grid = gpd.read_file(gpkg_path, layer="power_lines").to_crs(28992)
            log.info("  power_lines: %d rows", len(grid))
        except Exception:
            grid = None
            log.warning("  grid layer not found — GridSegment nodes will be skipped")

    parcels = None  # loaded on demand (Tier 2)
    return muni, natura, grid, parcels


# ─── Spatial pre-computations ─────────────────────────────────────────────────
def compute_adjacency(muni: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Detect shared-border pairs via buffer + sjoin.
    Returns DataFrame with columns [a, b] (gemeente_naam pairs).
    """
    log.info("Computing adjacency (buffer=%dm) …", ADJ_BUFFER_M)
    buf = muni[["gemeente_naam", "geometry"]].copy()
    buf["geometry"] = buf.geometry.buffer(ADJ_BUFFER_M)
    joined = gpd.sjoin(
        buf.rename(columns={"gemeente_naam": "a"}),
        buf.rename(columns={"gemeente_naam": "b"})[["b", "geometry"]],
        predicate="intersects",
    )
    pairs = (
        joined[joined["a"] != joined["b"]][["a", "b"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    log.info("  found %d adjacency pairs", len(pairs))
    return pairs


def compute_near_to(muni: gpd.GeoDataFrame, k: int = NEAR_TO_K) -> pd.DataFrame:
    """
    Top-k nearest municipality centroids (Euclidean on EPSG:28992).
    Returns DataFrame with columns [a, b, distance_km].
    Edges stored bidirectionally — MERGE in both directions during load.
    """
    log.info("Computing top-%d nearest-centroid pairs …", k)
    centroids = muni.geometry.centroid
    coords = np.column_stack([centroids.x, centroids.y])
    tree = cKDTree(coords)
    dists, idxs = tree.query(coords, k=k + 1)  # +1 to skip self (idx 0)
    names = muni["gemeente_naam"].values
    rows = [
        {"a": names[i], "b": names[j], "distance_km": round(float(d) / 1000, 3)}
        for i, (d_row, i_row) in enumerate(zip(dists, idxs))
        for d, j in zip(d_row[1:], i_row[1:])
    ]
    log.info("  computed %d near-to directed edges", len(rows))
    return pd.DataFrame(rows)


def compute_pairwise_overlaps(
    muni: gpd.GeoDataFrame, natura: gpd.GeoDataFrame
) -> pd.DataFrame:
    """
    Spatial intersection → per-pair overlap statistics.
    Returns DataFrame: [gemeente_naam, site_code, site_name, overlap_pct, overlap_ha].
    Pairs with < 0.1 ha overlap are dropped (digitisation artefacts).
    """
    log.info("Computing pairwise municipality ↔ Natura 2000 overlaps …")
    muni_sm = muni[["gemeente_naam", "geometry"]].copy()
    muni_sm["muni_area_m2"] = muni_sm.geometry.area

    # Detect column names — different versions of the dataset use different names
    code_col = next(
        (c for c in natura.columns if c.lower().startswith("sitecode")),
        next((c for c in natura.columns if c.lower() in ("site_code", "code")), natura.columns[0]),
    )
    name_col = next(
        (c for c in natura.columns if c.lower() in ("naam_n2k", "naam", "name", "site_name")),
        natura.columns[1],
    )
    nat_sm = natura[[code_col, name_col, "geometry"]].rename(
        columns={code_col: "site_code", name_col: "site_name"}
    )

    ix = gpd.overlay(muni_sm, nat_sm, how="intersection", keep_geom_type=False)
    ix["overlap_ha"]  = (ix.geometry.area / 10_000).round(4)
    ix["overlap_pct"] = (ix.geometry.area / ix["muni_area_m2"] * 100).round(3)

    result = (
        ix[ix["overlap_ha"] > 0.1][
            ["gemeente_naam", "site_code", "site_name", "overlap_pct", "overlap_ha"]
        ]
        .reset_index(drop=True)
    )
    log.info("  found %d overlapping pairs", len(result))
    return result


def compute_nearest_grid(
    muni: gpd.GeoDataFrame, grid: gpd.GeoDataFrame
) -> pd.DataFrame:
    """
    For each municipality centroid, find the nearest grid segment.
    Returns DataFrame: [gemeente_naam, osm_id, distance_km].
    Uses a single unary_union + nearest_points to avoid O(n²) distance calls.
    """
    log.info("Computing municipality → nearest GridSegment …")

    id_col = next(
        (c for c in grid.columns if c.lower() in ("osm_id", "@id", "id")),
        None,
    )

    grid_union = unary_union(grid.geometry)
    rows = []
    for _, r in muni.iterrows():
        centroid = r.geometry.centroid
        pt_on_grid, _ = nearest_points(grid_union, centroid)
        dist_km = centroid.distance(pt_on_grid) / 1000
        grid["_tmp_dist"] = grid.geometry.distance(centroid)
        closest = grid.loc[grid["_tmp_dist"].idxmin()]
        osm_id = str(closest[id_col]) if id_col else str(closest.name)
        rows.append({
            "gemeente_naam": r["gemeente_naam"],
            "osm_id":        osm_id,
            "distance_km":   round(dist_km, 3),
        })

    if "_tmp_dist" in grid.columns:
        grid.drop(columns=["_tmp_dist"], inplace=True)

    log.info("  computed %d municipality→grid edges", len(rows))
    return pd.DataFrame(rows)


# ─── Schema application ───────────────────────────────────────────────────────
def apply_schema(session) -> None:
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "src", "other", "schema.cypher")
    if not os.path.exists(schema_path):
        log.warning("schema.cypher not found — run it manually in Neo4j Browser")
        return
    with open(schema_path) as fh:
        statements = [
            s.strip()
            for s in fh.read().split(";")
            if s.strip() and not s.strip().startswith("//")
        ]
    log.info("Applying schema (%d statements) …", len(statements))
    for stmt in statements:
        session.run(stmt)
    log.info("  schema applied")


# ─── Node writers ─────────────────────────────────────────────────────────────
def write_classification_nodes(session) -> None:
    log.info("Writing classification nodes …")

    # ConflictLevel singletons
    session.run("""
        UNWIND $rows AS r
        MERGE (cl:ConflictLevel {level: r.level})
          SET cl.threshold_lower_pct = r.lo,
              cl.threshold_upper_pct = r.hi
    """, rows=[
        {"level": "none",   "lo":  0, "hi": 15},
        {"level": "low",    "lo": 15, "hi": 40},
        {"level": "medium", "lo": 40, "hi": 70},
        {"level": "high",   "lo": 70, "hi": 100},
    ])

    # EnergyTechnology singletons
    session.run("""
        UNWIND $names AS n
        MERGE (:EnergyTechnology {name: n})
    """, names=["Wind", "Solar", "Hybrid"])

    # LandUseCategory singletons
    session.run("""
        UNWIND $names AS n
        MERGE (:LandUseCategory {name: n})
    """, names=["Arable", "Permanent Grassland", "Other Agricultural"])

    # CropType nodes + SUBCLASS_OF edges
    # BRP uses Bouwland (BL) and Grasland (GL) as the two main groups
    session.run("""
        UNWIND $rows AS r
        MERGE (ct:CropType {code: r.code})
          SET ct.name = r.name
        WITH ct, r
        MATCH (luc:LandUseCategory {name: r.category})
        MERGE (ct)-[:SUBCLASS_OF]->(luc)
    """, rows=[
        {"code": "BL", "name": "Bouwland", "category": "Arable"},
        {"code": "GL", "name": "Grasland", "category": "Permanent Grassland"},
        {"code": "OV", "name": "Overig",   "category": "Other Agricultural"},
    ])

    log.info("  classification nodes written")


def write_municipality_nodes(session, muni: gpd.GeoDataFrame) -> None:
    log.info("Writing %d Municipality nodes …", len(muni))
    rows = []
    for _, r in muni.iterrows():
        rows.append({
            "gemeente_naam":          str(r["gemeente_naam"]),
            "avg_wind_wpd":           coerce(r.get("avg_wind_wpd"), float, 0.0),
            "avg_solar_pvout":        coerce(r.get("avg_solar_pvout"), float, 0.0),
            "available_land_ha":      coerce(r.get("available_land_ha"), float, 0.0),
            "natura2000_overlap_pct": coerce(r.get("natura2000_overlap_pct"), float, 0.0),
            "wind_score":             coerce(r.get("wind_score"), float, 0.0),
            "solar_score":            coerce(r.get("solar_score"), float, 0.0),
            "hybrid_score":           coerce(r.get("hybrid_score"), float, 0.0),
            "conflict_flag":          bool(r.get("conflict_flag", False)),
            "conflict_level":         str(r.get("conflict_level", "none")),
            "grid_distance_km":       coerce(r.get("grid_distance_km"), float, 0.0),
            "population":             coerce(r.get("population"), int, 0),
            "pop_density_km2":        coerce(r.get("pop_density_km2"), float, 0.0),
        })
    batch_write(session, """
        UNWIND $rows AS r
        MERGE (m:Municipality {gemeente_naam: r.gemeente_naam})
          SET m += r
    """, rows, label="Municipality")


def write_province_nodes(session, muni: gpd.GeoDataFrame) -> None:
    """
    Extract province from the municipalities layer.
    BestuurlijkeGebieden typically includes a 'provincie_naam' or 'prov_naam' column.
    Falls back to a hardcoded CBS lookup if the column is missing.
    """
    log.info("Writing Province nodes …")

    prov_col = next(
        (c for c in muni.columns if "provin" in c.lower() or "prov" == c.lower()),
        None,
    )

    if prov_col:
        for prov_naam, group in muni.groupby(prov_col):
            session.run("""
                MERGE (p:Province {naam: $naam})
                WITH p
                UNWIND $munis AS gn
                MATCH (m:Municipality {gemeente_naam: gn})
                MERGE (m)-[:BELONGS_TO_PROVINCE]->(p)
            """, naam=str(prov_naam), munis=list(group["gemeente_naam"]))
        log.info("  provinces written from column '%s'", prov_col)
    else:
        log.warning(
            "  No province column found in municipalities layer.\n"
            "  Add a 'provincie_naam' column to greengrid_full.gpkg, or\n"
            "  run a separate spatial join with CBS provinciegrenzen."
        )


def write_natura2000_nodes(session, natura: gpd.GeoDataFrame) -> None:
    log.info("Writing %d Natura2000Site nodes …", len(natura))

    code_col = next(
        (c for c in natura.columns if c.lower().startswith("sitecode")),
        next((c for c in natura.columns if c.lower() in ("site_code", "code")), natura.columns[0]),
    )
    name_col = next(
        (c for c in natura.columns if c.lower() in ("naam_n2k", "naam", "name", "site_name")),
        natura.columns[1],
    )

    rows = [
        {
            "site_code": str(r[code_col]),
            "site_name": str(r[name_col]),
            "area_ha":   round(float(r.geometry.area) / 10_000, 2),
        }
        for _, r in natura.iterrows()
    ]
    batch_write(session, """
        UNWIND $rows AS r
        MERGE (n:Natura2000Site {site_code: r.site_code})
          SET n.site_name = r.site_name, n.area_ha = r.area_ha
    """, rows, label="Natura2000Site")


def write_gridsegment_nodes(session, grid: gpd.GeoDataFrame) -> None:
    log.info("Writing %d GridSegment nodes …", len(grid))
    id_col = next(
        (c for c in grid.columns if c.lower() in ("osm_id", "@id", "id")),
        None,
    )
    rows = []
    for i, r in grid.iterrows():
        osm_id = str(r[id_col]) if id_col else str(i)
        rows.append({
            "osm_id":     osm_id,
            "voltage_kv": str(r.get("voltage", "unknown")),
            "length_km":  round(float(r.geometry.length) / 1000, 3),
        })
    batch_write(session, """
        UNWIND $rows AS r
        MERGE (g:GridSegment {osm_id: r.osm_id})
          SET g.voltage_kv = r.voltage_kv, g.length_km = r.length_km
    """, rows, label="GridSegment")


# ─── Relationship writers ─────────────────────────────────────────────────────
def write_adjacency(session, adj_df: pd.DataFrame) -> None:
    log.info("Writing ADJACENT_TO edges …")
    rows = adj_df[["a", "b"]].to_dict("records")
    batch_write(session, """
        UNWIND $rows AS r
        MATCH (a:Municipality {gemeente_naam: r.a})
        MATCH (b:Municipality {gemeente_naam: r.b})
        MERGE (a)-[:ADJACENT_TO]->(b)
        MERGE (b)-[:ADJACENT_TO]->(a)
    """, rows, label="ADJACENT_TO")


def write_near_to(session, near_df: pd.DataFrame) -> None:
    log.info("Writing NEAR_TO edges …")
    rows = near_df.to_dict("records")
    batch_write(session, """
        UNWIND $rows AS r
        MATCH (a:Municipality {gemeente_naam: r.a})
        MATCH (b:Municipality {gemeente_naam: r.b})
        MERGE (a)-[e:NEAR_TO]->(b)
          SET e.distance_km = r.distance_km
        MERGE (b)-[f:NEAR_TO]->(a)
          SET f.distance_km = r.distance_km
    """, rows, label="NEAR_TO")


def write_overlaps(session, overlaps_df: pd.DataFrame) -> None:
    log.info("Writing OVERLAPS_WITH edges …")
    rows = overlaps_df.to_dict("records")
    batch_write(session, """
        UNWIND $rows AS r
        MATCH (m:Municipality  {gemeente_naam: r.gemeente_naam})
        MATCH (n:Natura2000Site {site_code:    r.site_code})
        MERGE (n)-[e:OVERLAPS_WITH]->(m)
          SET e.overlap_pct = r.overlap_pct,
              e.overlap_ha  = r.overlap_ha
    """, rows, label="OVERLAPS_WITH")


def write_conflict_reification(session, overlaps_df: pd.DataFrame) -> None:
    """
    Create a Conflict node for every (municipality, Natura2000Site) pair
    where overlap_pct >= 15 (i.e. conflict_level != 'none').
    Each Conflict node is linked to the Municipality, the Natura2000Site,
    and the ConflictLevel singleton — the reification pattern from Lecture 3.
    """
    log.info("Writing Conflict (reified) nodes …")

    def _level(pct: float) -> str:
        if pct < 15:  return "none"
        if pct < 40:  return "low"
        if pct < 70:  return "medium"
        return "high"

    rows = overlaps_df.copy()
    rows["level"]       = rows["overlap_pct"].apply(_level)
    rows = rows[rows["level"] != "none"].copy()
    rows["conflict_id"] = rows["gemeente_naam"].astype(str) + "__" + rows["site_code"].astype(str)

    batch_write(session, """
        UNWIND $rows AS r
        MATCH (m:Municipality  {gemeente_naam: r.gemeente_naam})
        MATCH (n:Natura2000Site {site_code:    r.site_code})
        MATCH (cl:ConflictLevel {level:        r.level})
        MERGE (c:Conflict {conflict_id: r.conflict_id})
          SET c.overlap_pct = r.overlap_pct,
              c.overlap_ha  = r.overlap_ha
        MERGE (c)-[:IS_ABOUT]->(m)
        MERGE (c)-[:WITH_SITE]->(n)
        MERGE (c)-[:HAS_LEVEL]->(cl)
    """, rows.to_dict("records"), label="Conflict")


def write_nearest_grid(session, grid_df: pd.DataFrame) -> None:
    log.info("Writing NEAREST_GRID_SEGMENT edges …")
    rows = grid_df.to_dict("records")
    batch_write(session, """
        UNWIND $rows AS r
        MATCH (m:Municipality {gemeente_naam: r.gemeente_naam})
        MATCH (g:GridSegment  {osm_id:        r.osm_id})
        MERGE (m)-[e:NEAREST_GRID_SEGMENT]->(g)
          SET e.distance_km = r.distance_km
    """, rows, label="NEAREST_GRID_SEGMENT")


def write_suitable_for(session, muni: gpd.GeoDataFrame) -> None:
    """
    Three SUITABLE_FOR edges per municipality — one per EnergyTechnology.
    Edge property `score` carries the pre-computed normalised score.
    """
    log.info("Writing SUITABLE_FOR edges …")
    rows = []
    for _, r in muni.iterrows():
        for tech, col in [("Wind", "wind_score"), ("Solar", "solar_score"), ("Hybrid", "hybrid_score")]:
            rows.append({
                "gemeente_naam": r["gemeente_naam"],
                "tech":          tech,
                "score":         coerce(r.get(col), float, 0.0),
            })
    batch_write(session, """
        UNWIND $rows AS r
        MATCH (m:Municipality    {gemeente_naam: r.gemeente_naam})
        MATCH (e:EnergyTechnology {name:         r.tech})
        MERGE (m)-[rel:SUITABLE_FOR]->(e)
          SET rel.score = r.score
    """, rows, label="SUITABLE_FOR")


# ─── Tier 2: Parcel nodes ─────────────────────────────────────────────────────
def write_parcels(session, gpkg_path: str, muni: gpd.GeoDataFrame) -> None:
    """
    Load individual Parcel nodes (1.29M rows) with LOCATED_IN and HAS_CROP_TYPE.
    Memory note: reads in chunks of 200k rows. Expect ~15 min on modest hardware.
    """
    log.info("Loading Tier 2: Parcel nodes (this may take a while) …")

    parcels = gpd.read_file(gpkg_path, layer="parcels_available").to_crs(28992)
    log.info("  parcels layer: %d rows", len(parcels))

    muni_sm = muni[["gemeente_naam", "geometry"]]
    joined  = gpd.sjoin(parcels, muni_sm, predicate="within", how="left")

    crop_col = next(
        (c for c in parcels.columns if "gewas" in c.lower()),
        parcels.columns[0],
    )
    id_col = next(
        (c for c in parcels.columns if "perceel" in c.lower() or c.lower() == "id"),
        None,
    )

    rows = []
    for i, r in joined.iterrows():
        pid = str(r[id_col]) if id_col else str(i)
        rows.append({
            "parcel_id":     pid,
            "area_ha":       round(float(r.geometry.area) / 10_000, 4),
            "gewasgroep":    str(r.get(crop_col, "OV")),
            "gemeente_naam": str(r.get("gemeente_naam", "")),
        })
        if len(rows) >= BATCH:
            session.run("""
                UNWIND $rows AS r
                MERGE (p:Parcel {parcel_id: r.parcel_id})
                  SET p.area_ha = r.area_ha, p.gewasgroep = r.gewasgroep
                WITH p, r WHERE r.gemeente_naam <> ''
                MATCH (m:Municipality {gemeente_naam: r.gemeente_naam})
                MERGE (p)-[:LOCATED_IN]->(m)
                WITH p, r
                MATCH (ct:CropType {code: r.gewasgroep})
                MERGE (p)-[:HAS_CROP_TYPE]->(ct)
            """, rows=rows)
            rows = []

    if rows:
        session.run("""
            UNWIND $rows AS r
            MERGE (p:Parcel {parcel_id: r.parcel_id})
              SET p.area_ha = r.area_ha, p.gewasgroep = r.gewasgroep
            WITH p, r WHERE r.gemeente_naam <> ''
            MATCH (m:Municipality {gemeente_naam: r.gemeente_naam})
            MERGE (p)-[:LOCATED_IN]->(m)
            WITH p, r
            MATCH (ct:CropType {code: r.gewasgroep})
            MERGE (p)-[:HAS_CROP_TYPE]->(ct)
        """, rows=rows)

    log.info("  Parcel nodes written")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Load GreenGrid KG into Neo4j")
    parser.add_argument("--gpkg",    default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "processed", "greengrid_full.gpkg"),
                        help="Path to greengrid_full.gpkg")
    parser.add_argument("--parcels", action="store_true",
                        help="Also load Tier 2 parcel nodes (1.29M rows)")
    args = parser.parse_args()

    if not os.path.exists(args.gpkg):
        log.error("GeoPackage not found: %s", args.gpkg)
        sys.exit(1)

    # ── Load spatial layers ────────────────────────────────────────────────
    muni, natura, grid, _ = load_layers(args.gpkg)

    # ── Pre-compute spatial relationships ──────────────────────────────────
    adj_df     = compute_adjacency(muni)
    near_df    = compute_near_to(muni)
    overlap_df = compute_pairwise_overlaps(muni, natura)
    grid_df    = compute_nearest_grid(muni, grid) if grid is not None else None

    # ── Connect and load ───────────────────────────────────────────────────
    log.info("Connecting to Neo4j at %s …", NEO4J_URI)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    with driver.session() as session:
        apply_schema(session)

        # Nodes
        write_classification_nodes(session)
        write_municipality_nodes(session, muni)
        write_province_nodes(session, muni)
        write_natura2000_nodes(session, natura)
        if grid is not None:
            write_gridsegment_nodes(session, grid)

        # Relationships
        write_adjacency(session, adj_df)
        write_near_to(session, near_df)
        write_overlaps(session, overlap_df)
        write_conflict_reification(session, overlap_df)
        if grid_df is not None:
            write_nearest_grid(session, grid_df)
        write_suitable_for(session, muni)

        # Tier 2 (optional)
        if args.parcels:
            write_parcels(session, args.gpkg, muni)

    driver.close()
    log.info("✓ Knowledge graph loaded successfully.")


if __name__ == "__main__":
    main()