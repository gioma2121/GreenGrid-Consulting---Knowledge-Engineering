# GreenGrid NL — Renewable Energy Siting via Knowledge Graph

A knowledge engineering project that combines Dutch geospatial open data, a Neo4j knowledge graph, and an interactive Dash dashboard to identify optimal municipalities for wind and solar energy deployment in the Netherlands.

---

## What it does

GreenGrid NL answers spatial siting questions like:

- Which municipalities have high hybrid energy potential, low Natura 2000 conflict, and good grid access?
- Which clusters of adjacent municipalities together offer large contiguous areas of available land?
- Which protected nature sites are the binding constraint for the top wind-scoring municipalities?

These are answered through Cypher queries over a Neo4j knowledge graph, and visualised through a three-page web dashboard.

---

## Architecture

```
Raw data (GeoPackage / rasters / OSM)
        ↓
greengrid_analysis.py   ← builds greengrid_full.gpkg (scores, parcels, natura2000)
fetch_grid.py           ← adds OSM power line layer + grid_distance_km
fetch_cbs.py            ← patches population density + provincie_naam from CBS/PDOK
        ↓
greengrid_full.gpkg     ← single source of truth for all spatial data
        ↓
load_kg.py              ← loads everything into Neo4j
        ↓
Neo4j knowledge graph   ← queried by the dashboard + NL→Cypher backend
        ↓
app.py (Dash)           ← interactive web dashboard
```

---

## Knowledge Graph Schema

### Node types

| Label | Description |
|---|---|
| `Municipality` | 342 Dutch municipalities with energy scores, land availability, population, and conflict level |
| `Province` | 12 Dutch provinces |
| `Natura2000Site` | 209 EU-protected nature areas |
| `GridSegment` | OSM power line segments (~20k) |
| `Conflict` | Reified conflict between a municipality and a Natura 2000 site (overlap ≥ 15%) |
| `ConflictLevel` | Singleton: none / low / medium / high |
| `EnergyTechnology` | Singleton: Wind / Solar / Hybrid |
| `LandUseCategory` | Singleton: Arable / Permanent Grassland / Other Agricultural |
| `CropType` | BL (Bouwland) / GL (Grasland) / OV (Overig) |
| `Parcel` *(Tier 2)* | Individual agricultural parcels (1.29M, optional) |

### Relationships

| Relationship | From → To | Condition / Properties |
|---|---|---|
| `BELONGS_TO_PROVINCE` | `Municipality` → `Province` | Always; derived from PDOK spatial join |
| `ADJACENT_TO` | `Municipality` ↔ `Municipality` | Geometries share a border (50m buffer) |
| `NEAR_TO` | `Municipality` ↔ `Municipality` | Top-10 nearest centroids; has `distance_km` |
| `OVERLAPS_WITH` | `Natura2000Site` → `Municipality` | Spatial overlap > 0.1 ha; has `overlap_pct`, `overlap_ha` |
| `NEAREST_GRID_SEGMENT` | `Municipality` → `GridSegment` | Nearest OSM power line to centroid; has `distance_km` |
| `SUITABLE_FOR` | `Municipality` → `EnergyTechnology` | Always (one per tech); has `score` ∈ [0, 1] |
| `IS_ABOUT` | `Conflict` → `Municipality` | overlap_pct ≥ 15% |
| `WITH_SITE` | `Conflict` → `Natura2000Site` | overlap_pct ≥ 15% |
| `HAS_LEVEL` | `Conflict` → `ConflictLevel` | low (15–40%) / medium (40–70%) / high (70–100%) |
| `SUBCLASS_OF` | `CropType` → `LandUseCategory` | Hardcoded crop taxonomy |
| `LOCATED_IN` *(Tier 2)* | `Parcel` → `Municipality` | Spatial within |
| `HAS_CROP_TYPE` *(Tier 2)* | `Parcel` → `CropType` | From BRP gewasgroep code |

---

## Data Sources

| Data | Source | File |
|---|---|---|
| Municipality boundaries | CBS BestuurlijkeGebieden 2025 | `data/raw/BestuurlijkeGebieden_2025.gpkg` |
| Agricultural parcels | RVO BRP 2025 | `data/raw/brpgewaspercelen_definitief_2025.gpkg` |
| Wind power density | Global Wind Atlas (100m) | `data/raw/NLD_wind-speed_100m.tif` |
| Solar PV output | Global Solar Atlas (PVOUT) | `data/raw/.../PVOUT.tif` |
| Natura 2000 boundaries | RIVM | `data/raw/natura2000.gpkg` |
| Power grid lines | OpenStreetMap Overpass API | fetched by `fetch_grid.py` |
| Population density | CBS Statline table 70072ned | fetched by `fetch_cbs.py` |
| Province mapping | PDOK WFS gebiedsindelingen 2024 | fetched by `fetch_cbs.py` |

---

## Setup

### Prerequisites

```bash
pip install -r requirements.txt
```

A running Neo4j instance is required. Set credentials via environment variables:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASS=your_password
```

Or edit the `CONFIG` block at the top of `load_kg.py`.

### Building the data pipeline

Run scripts in this order:

```bash
# 1. Compute energy scores and build the GeoPackage
python src/dataset/greengrid_analysis.py

# 2. Add OSM power grid layer and grid_distance_km per municipality
python src/dataset/fetch_grid.py

# 3. Add population density and province mapping (CBS + PDOK)
python src/dataset/fetch_cbs.py

# 4. Load the knowledge graph into Neo4j (Tier 1 — ~1000 nodes, ~8000 edges)
python src/dataset/load_kg.py

# Optional: also load 1.29M parcel nodes (Tier 2, memory-intensive)
python src/dataset/load_kg.py --parcels
```

### Running the dashboard

```bash
python app.py
# Open http://127.0.0.1:8050
```

---

## Dashboard Pages

| Page | Description |
|---|---|
| **Map** (`/`) | Choropleth map of the Netherlands coloured by energy score, with filters for conflict level, land area, grid distance, and population density |
| **Analytics** (`/analytics`) | Charts and rankings — top municipalities by technology, province-level summaries, conflict distribution |
| **Knowledge Graph** (`/kg`) | Interactive graph explorer backed by the Neo4j KG; supports natural language queries via NL→Cypher |

---

## Competency Questions

Predefined Cypher queries for the five core competency questions are in `competency_queries.cypher`:

- **CQ1** — Multi-constraint siting filter (hybrid score, conflict, grid, population)
- **CQ2** — Contiguous low-conflict municipal clusters by adjacency or proximity
- **CQ3** — Natura 2000 sites most often blocking top wind municipalities
- **CQ4** — Province-level conflict level distribution
- **CQ5** — Dominant crop types in conflict-free municipalities *(requires Tier 2)*

---

## Project Structure

```
.
├── requirements.txt
├── README.md
│
├── src/
│   ├── dataset/                      # data → GeoPackage → Neo4j
│   │   ├── greengrid_analysis.py     # Main scoring pipeline
│   │   ├── fetch_grid.py             # OSM power grid fetch
│   │   ├── fetch_cbs.py              # CBS/PDOK population + province fetch
│   │   └── load_kg.py                # Neo4j loader (Tier 1 + optional Tier 2)
│   │
│   ├── dashboard/                    # Dash web application
│   │   ├── app.py                    # Entry point
│   │   ├── nl_cypher.py              # Natural language → Cypher translation
│   │   └── pages/
│   │       ├── home.py               # Map page
│   │       ├── analytics.py          # Analytics page
│   │       └── kg.py                 # Knowledge graph explorer page
│   │
│   └── other/                        # Knowledge graph artifacts + exploratory scripts
│       ├── schema.cypher             # Neo4j constraints and indexes
│       ├── competency_queries.cypher # Validation queries
│       ├── analysis.py
│       ├── preprocessing.py
│       └── plot_grid.py
│
├── data/
│   ├── raw/                          # Input rasters and GeoPackages (not in git)
│   └── processed/                    # greengrid_full.gpkg, greengrid_scores.gpkg (not in git)
│
└── figs/                             # Output maps and visualisations
```
