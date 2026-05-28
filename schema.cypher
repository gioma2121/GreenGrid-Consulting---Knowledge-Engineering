// ============================================================
// GreenGrid Knowledge Graph — Neo4j schema
// Run this BEFORE load_kg.py
// Compatible with Neo4j 5.x (IF NOT EXISTS syntax)
// ============================================================

// ─── Uniqueness constraints ──────────────────────────────────
// Each constraint also creates a lookup index automatically.

CREATE CONSTRAINT muni_unique IF NOT EXISTS
  FOR (m:Municipality)    REQUIRE m.gemeente_naam IS UNIQUE;

CREATE CONSTRAINT province_unique IF NOT EXISTS
  FOR (p:Province)        REQUIRE p.naam IS UNIQUE;

CREATE CONSTRAINT natura_unique IF NOT EXISTS
  FOR (n:Natura2000Site)  REQUIRE n.site_code IS UNIQUE;

CREATE CONSTRAINT grid_unique IF NOT EXISTS
  FOR (g:GridSegment)     REQUIRE g.osm_id IS UNIQUE;

CREATE CONSTRAINT croptype_unique IF NOT EXISTS
  FOR (c:CropType)        REQUIRE c.code IS UNIQUE;

CREATE CONSTRAINT landuse_unique IF NOT EXISTS
  FOR (l:LandUseCategory) REQUIRE l.name IS UNIQUE;

CREATE CONSTRAINT conflict_level_unique IF NOT EXISTS
  FOR (cl:ConflictLevel)  REQUIRE cl.level IS UNIQUE;

CREATE CONSTRAINT energy_tech_unique IF NOT EXISTS
  FOR (e:EnergyTechnology) REQUIRE e.name IS UNIQUE;

CREATE CONSTRAINT conflict_id_unique IF NOT EXISTS
  FOR (c:Conflict)        REQUIRE c.conflict_id IS UNIQUE;

// ─── Range indexes for filter/sort queries ───────────────────
// These are hit by almost every competency question.

CREATE INDEX muni_hybrid_score   IF NOT EXISTS
  FOR (m:Municipality) ON (m.hybrid_score);

CREATE INDEX muni_wind_score     IF NOT EXISTS
  FOR (m:Municipality) ON (m.wind_score);

CREATE INDEX muni_solar_score    IF NOT EXISTS
  FOR (m:Municipality) ON (m.solar_score);

CREATE INDEX muni_conflict_level IF NOT EXISTS
  FOR (m:Municipality) ON (m.conflict_level);

CREATE INDEX muni_grid_distance  IF NOT EXISTS
  FOR (m:Municipality) ON (m.grid_distance_km);

CREATE INDEX muni_available_land IF NOT EXISTS
  FOR (m:Municipality) ON (m.available_land_ha);

CREATE INDEX muni_pop_density    IF NOT EXISTS
  FOR (m:Municipality) ON (m.pop_density_km2);

// ─── Relationship property index (Neo4j 5.x) ────────────────
// Speeds up the "find all pairs within X km" pattern.

CREATE INDEX near_to_dist IF NOT EXISTS
  FOR ()-[r:NEAR_TO]-() ON (r.distance_km);

CREATE INDEX overlap_pct_idx IF NOT EXISTS
  FOR ()-[r:OVERLAPS_WITH]-() ON (r.overlap_pct);
