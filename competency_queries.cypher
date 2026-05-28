// ============================================================
// GreenGrid Knowledge Graph — Competency Question Queries
// Run against a loaded Neo4j instance to validate the schema.
// ============================================================

// ── CQ1: Multi-constraint siting filter ─────────────────────
// Which municipalities have hybrid_score > 0.6, no high Natura
// conflict, grid distance < 10 km, and pop density < 500/km²?
// (RQ3 core query)

MATCH (m:Municipality)
WHERE m.hybrid_score > 0.6
  AND m.conflict_level IN ['none', 'low', 'medium']
  AND m.grid_distance_km < 10
  AND m.pop_density_km2 < 500
RETURN m.gemeente_naam       AS municipality,
       m.hybrid_score        AS hybrid_score,
       m.conflict_level      AS conflict_level,
       m.grid_distance_km    AS grid_dist_km,
       m.available_land_ha   AS land_ha
ORDER BY m.hybrid_score DESC;


// ── CQ2: Contiguous low-conflict patches ────────────────────
// Find chains of 3+ ADJACENT_TO municipalities all with
// available_land > 1000 ha and conflict_level ∈ {none, low}.
// The NEAR_TO variant replaces ADJACENT_TO for cross-province clusters.

// Version A — adjacency-based (same or neighbouring province)
MATCH path = (a:Municipality)-[:ADJACENT_TO*2..4]->(b:Municipality)
WHERE ALL(m IN nodes(path) WHERE
      m.available_land_ha > 1000
  AND m.conflict_level IN ['none', 'low'])
  AND length(path) >= 2
RETURN [m IN nodes(path) | m.gemeente_naam] AS cluster,
       length(path) + 1                      AS cluster_size,
       reduce(ha = 0.0, m IN nodes(path) | ha + m.available_land_ha) AS total_ha
ORDER BY total_ha DESC
LIMIT 20;

// Version B — Euclidean nearness (cross-province clusters)
MATCH path = (a:Municipality)-[:NEAR_TO*2..3]->(b:Municipality)
WHERE ALL(r IN relationships(path) WHERE r.distance_km < 20)
  AND ALL(m IN nodes(path) WHERE
      m.available_land_ha > 1000
  AND m.conflict_level IN ['none', 'low'])
RETURN [m IN nodes(path) | m.gemeente_naam] AS cluster,
       length(path) + 1                      AS cluster_size,
       reduce(ha = 0.0, m IN nodes(path) | ha + m.available_land_ha) AS total_ha
ORDER BY total_ha DESC
LIMIT 20;


// ── CQ3: Binding Natura 2000 constraints ────────────────────
// Which Natura 2000 sites appear most often as the binding
// constraint in the top-20 wind municipalities?

MATCH (m:Municipality)-[rel:SUITABLE_FOR]->(e:EnergyTechnology {name: 'Wind'})
WITH m ORDER BY rel.score DESC LIMIT 20
MATCH (c:Conflict)-[:IS_ABOUT]->(m)
MATCH (c)-[:WITH_SITE]->(n:Natura2000Site)
MATCH (c)-[:HAS_LEVEL]->(cl:ConflictLevel)
WHERE cl.level IN ['medium', 'high']
RETURN n.site_name        AS natura2000_site,
       n.site_code        AS site_code,
       count(DISTINCT m)  AS municipalities_blocked,
       avg(c.overlap_pct) AS avg_overlap_pct
ORDER BY municipalities_blocked DESC;


// ── CQ4: Province-level conflict distribution ────────────────
// Tally conflict levels per province — useful for the report's
// geographic analysis section.

MATCH (m:Municipality)-[:BELONGS_TO_PROVINCE]->(p:Province)
RETURN p.naam                                                AS province,
       count(m)                                             AS total_municipalities,
       sum(CASE WHEN m.conflict_level = 'none'   THEN 1 ELSE 0 END) AS none_count,
       sum(CASE WHEN m.conflict_level = 'low'    THEN 1 ELSE 0 END) AS low_count,
       sum(CASE WHEN m.conflict_level = 'medium' THEN 1 ELSE 0 END) AS medium_count,
       sum(CASE WHEN m.conflict_level = 'high'   THEN 1 ELSE 0 END) AS high_count
ORDER BY high_count DESC;


// ── CQ5: Dominant crop types in conflict-free municipalities ─
// Which crop categories dominate available land where there is
// no Natura 2000 conflict?
// (Requires Tier 2 parcel nodes — skip if --parcels not loaded)

MATCH (p:Parcel)-[:LOCATED_IN]->(m:Municipality)
WHERE m.conflict_level = 'none'
MATCH (p)-[:HAS_CROP_TYPE]->(ct:CropType)-[:SUBCLASS_OF]->(luc:LandUseCategory)
RETURN luc.name       AS land_use_category,
       ct.name        AS crop_type,
       count(p)       AS parcel_count,
       sum(p.area_ha) AS total_ha
ORDER BY total_ha DESC;

// Aggregate version (no parcels needed — uses per-municipality totals)
MATCH (m:Municipality)
WHERE m.conflict_level = 'none'
RETURN 'All (conflict-free)' AS group,
       count(m)              AS municipalities,
       sum(m.available_land_ha) AS total_available_ha,
       avg(m.available_land_ha) AS avg_available_ha
ORDER BY total_available_ha DESC;


// ── CQ6 (bonus): NL→Cypher demo query ───────────────────────
// "Which municipalities near Zeewolde have good hybrid scores
//  but are not yet connected well to the grid?"
// This is the kind of query the NL→Cypher chat should handle.

MATCH (anchor:Municipality {gemeente_naam: 'Zeewolde'})
MATCH (anchor)-[:NEAR_TO {distance_km: dist}]-(neighbour:Municipality)
WHERE neighbour.hybrid_score > 0.5
  AND neighbour.grid_distance_km > 5
RETURN neighbour.gemeente_naam  AS municipality,
       round(dist, 1)            AS dist_from_zeewolde_km,
       neighbour.hybrid_score    AS hybrid_score,
       neighbour.grid_distance_km AS grid_dist_km
ORDER BY neighbour.hybrid_score DESC;
