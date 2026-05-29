"""
GreenGrid — NL → Cypher backend
================================
Translates natural language questions into Cypher queries using DeepSeek,
executes them against Neo4j AuraDB, and returns structured results.

Usage (standalone test):
    python nl_cypher.py "Which municipalities near Zeewolde have good hybrid scores?"

Usage (from Dash callback):
    from nl_cypher import ask
    result = ask("Top 5 wind municipalities with no Natura 2000 conflict")
    # result = {"cypher": "...", "columns": [...], "rows": [...], "error": None}

Dependencies:
    pip install openai neo4j
"""

import os
import re
import logging
from typing import Any

from openai import OpenAI
from neo4j import GraphDatabase

log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
NEO4J_URI    = os.getenv("NEO4J_URI",       "neo4j+s://14361706.databases.neo4j.io")
NEO4J_USER   = os.getenv("NEO4J_USER",      "14361706")   # AuraDB instance ID
NEO4J_PASS   = os.getenv("NEO4J_PASS",      "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")

MAX_ROWS    = 50
TIMEOUT_SEC = 15


# ─── Schema ──────────────────────────────────────────────────────────────────
SCHEMA = """
Node labels and key properties:
- Municipality       { gemeente_naam (unique), hybrid_score, wind_score, solar_score,
                       conflict_level (none|low|medium|high), conflict_flag,
                       grid_distance_km, available_land_ha, pop_density_km2,
                       population, avg_wind_wpd, avg_solar_pvout,
                       natura2000_overlap_pct }
- Natura2000Site     { site_code (unique), site_name, area_ha }
- GridSegment        { osm_id (unique), voltage_kv, length_km }
- Conflict           { conflict_id (unique), overlap_pct, overlap_ha }
- ConflictLevel      { level: "none" | "low" | "medium" | "high" }
- EnergyTechnology   { name: "Wind" | "Solar" | "Hybrid" }
- CropType           { code: "BL"|"GL"|"OV", name }
- LandUseCategory    { name: "Arable" | "Permanent Grassland" | "Other Agricultural" }

Relationships:
- (Municipality)-[:ADJACENT_TO]->(Municipality)
- (Municipality)-[:NEAR_TO {distance_km}]->(Municipality)
- (Natura2000Site)-[:OVERLAPS_WITH {overlap_pct, overlap_ha}]->(Municipality)
- (Municipality)-[:NEAREST_GRID_SEGMENT {distance_km}]->(GridSegment)
- (Municipality)-[:SUITABLE_FOR {score}]->(EnergyTechnology)
- (Conflict)-[:IS_ABOUT]->(Municipality)
- (Conflict)-[:WITH_SITE]->(Natura2000Site)
- (Conflict)-[:HAS_LEVEL]->(ConflictLevel)
- (CropType)-[:SUBCLASS_OF]->(LandUseCategory)

Score ranges: 0.0–1.0. conflict_level thresholds: none=0-15%, low=15-40%, medium=40-70%, high>70%.
""".strip()


# ─── Few-shot examples ────────────────────────────────────────────────────────
FEW_SHOTS = [
    {
        "question": "Top 10 municipalities for wind energy with no Natura 2000 conflict",
        "cypher": """MATCH (m:Municipality)
WHERE m.conflict_level = 'none'
RETURN m.gemeente_naam AS municipality,
       m.wind_score    AS wind_score,
       m.available_land_ha AS land_ha
ORDER BY m.wind_score DESC
LIMIT 10"""
    },
    {
        "question": "Which Natura 2000 sites are blocking the most high-wind municipalities?",
        "cypher": """MATCH (m:Municipality)-[rel:SUITABLE_FOR]->(e:EnergyTechnology {name: 'Wind'})
WITH m ORDER BY rel.score DESC LIMIT 30
MATCH (c:Conflict)-[:IS_ABOUT]->(m)
MATCH (c)-[:WITH_SITE]->(n:Natura2000Site)
MATCH (c)-[:HAS_LEVEL]->(cl:ConflictLevel)
WHERE cl.level IN ['medium', 'high']
RETURN n.site_name             AS natura2000_site,
       count(DISTINCT m)       AS municipalities_blocked,
       avg(c.overlap_pct)      AS avg_overlap_pct
ORDER BY municipalities_blocked DESC
LIMIT 10"""
    },
    {
        "question": "Find adjacent municipality pairs both with hybrid score above 0.5 and conflict-free",
        "cypher": """MATCH (a:Municipality)-[:ADJACENT_TO]->(b:Municipality)
WHERE a.hybrid_score > 0.5 AND b.hybrid_score > 0.5
  AND a.conflict_level IN ['none', 'low']
  AND b.conflict_level IN ['none', 'low']
RETURN a.gemeente_naam AS muni_a, b.gemeente_naam AS muni_b,
       round(a.hybrid_score, 3) AS score_a, round(b.hybrid_score, 3) AS score_b
ORDER BY (a.hybrid_score + b.hybrid_score) DESC
LIMIT 20"""
    },
    {
        "question": "Which municipalities near Zeewolde have good hybrid scores but are far from the grid?",
        "cypher": """MATCH (anchor:Municipality {gemeente_naam: 'Zeewolde'})
MATCH (anchor)-[r:NEAR_TO]-(neighbour:Municipality)
WHERE neighbour.hybrid_score > 0.5 AND neighbour.grid_distance_km > 5
RETURN neighbour.gemeente_naam   AS municipality,
       round(r.distance_km, 1)   AS dist_from_zeewolde_km,
       neighbour.hybrid_score    AS hybrid_score,
       neighbour.grid_distance_km AS grid_dist_km
ORDER BY neighbour.hybrid_score DESC"""
    },
    {
        "question": "Show me the conflict level distribution across all municipalities",
        "cypher": """MATCH (m:Municipality)
RETURN m.conflict_level AS conflict_level, count(m) AS count,
       avg(m.hybrid_score) AS avg_hybrid_score
ORDER BY count DESC"""
    },
    {
        "question": "Top solar municipalities with grid distance under 5km and population density under 300",
        "cypher": """MATCH (m:Municipality)
WHERE m.grid_distance_km < 5 AND m.pop_density_km2 < 300
RETURN m.gemeente_naam AS municipality, m.solar_score AS solar_score,
       m.grid_distance_km AS grid_dist_km, m.available_land_ha AS land_ha
ORDER BY m.solar_score DESC
LIMIT 20"""
    },
]


# ─── System prompt ────────────────────────────────────────────────────────────
def _build_system_prompt() -> str:
    shots = "\n\n".join(
        f"Q: {ex['question']}\nCypher:\n```cypher\n{ex['cypher']}\n```"
        for ex in FEW_SHOTS
    )
    return f"""You are a Neo4j Cypher expert for the GreenGrid renewable energy siting project in the Netherlands.
Your job: translate the user's natural language question into a single valid Cypher query.

{SCHEMA}

Rules:
1. Return ONLY the Cypher query — no explanation, no markdown, no preamble.
2. Always add a LIMIT clause (default 20, max 50) unless asking for counts/distributions.
3. Use round(x, 3) for float properties in RETURN.
4. Never use WRITE operations (CREATE, MERGE, DELETE, SET). Read-only only.
5. For specific municipality names use WHERE m.gemeente_naam = 'Name' (Dutch spelling).
6. For "near" use NEAR_TO; for "bordering"/"adjacent" use ADJACENT_TO.
7. Scores are 0–1. "good" means > 0.5; "excellent" means > 0.7.

Few-shot examples:
{shots}

Now answer the user's question with a single Cypher query."""


# ─── DeepSeek call ───────────────────────────────────────────────────────────
def _generate_cypher(question: str, error_feedback: dict | None = None) -> str:
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
    messages = [{"role": "system", "content": _build_system_prompt()}]

    if error_feedback:
        messages += [
            {"role": "user",      "content": question},
            {"role": "assistant", "content": error_feedback.get("previous_cypher", "")},
            {"role": "user",      "content": f"That query returned an error: {error_feedback['error']}\nPlease fix it and return only the corrected Cypher."},
        ]
    else:
        messages.append({"role": "user", "content": question})

    resp = client.chat.completions.create(
        model="deepseek-chat", messages=messages, temperature=0.0, max_tokens=512
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:cypher)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


# ─── Neo4j execution ─────────────────────────────────────────────────────────
def _run_cypher(cypher: str) -> tuple[list[str], list[list[Any]]]:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session() as session:
            result = session.run(cypher, timeout=TIMEOUT_SEC)
            keys = list(result.keys())
            rows = [[record[k] for k in keys] for record in result][:MAX_ROWS]
        return keys, rows
    finally:
        driver.close()


# ─── Public API ──────────────────────────────────────────────────────────────
def ask(question: str) -> dict:
    """
    Main entry point. Returns:
    { "cypher": str, "columns": list, "rows": list, "error": str|None, "retried": bool }
    """
    if not DEEPSEEK_KEY:
        return _err("DEEPSEEK_API_KEY environment variable not set.")
    if not NEO4J_PASS:
        return _err("NEO4J_PASS environment variable not set.")

    # Step 1: generate
    try:
        cypher = _generate_cypher(question)
        log.info("Generated Cypher:\n%s", cypher)
    except Exception as exc:
        return _err(f"DeepSeek API error: {exc}")

    # Step 2: execute
    first_err_msg = None
    try:
        columns, rows = _run_cypher(cypher)
        return {"cypher": cypher, "columns": columns, "rows": rows, "error": None, "retried": False}
    except Exception as exc:
        first_err_msg = str(exc)
        log.warning("First attempt failed: %s — retrying", first_err_msg)

    # Step 3: retry with error context
    cypher2 = cypher
    try:
        cypher2 = _generate_cypher(question, error_feedback={"previous_cypher": cypher, "error": first_err_msg})
        log.info("Retry Cypher:\n%s", cypher2)
        columns, rows = _run_cypher(cypher2)
        return {"cypher": cypher2, "columns": columns, "rows": rows, "error": None, "retried": True}
    except Exception as exc2:
        return {"cypher": cypher2, "columns": [], "rows": [], "error": str(exc2), "retried": True}


def _err(msg: str) -> dict:
    return {"cypher": "", "columns": [], "rows": [], "error": msg, "retried": False}


# ─── CLI test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    question = " ".join(sys.argv[1:]) or "Top 10 hybrid municipalities with no high conflict"
    print(f"\nQuestion: {question}\n")
    result = ask(question)
    print(f"Cypher:\n{result['cypher']}\n")
    if result["error"]:
        print(f"Error: {result['error']}")
    else:
        if result["retried"]:
            print("(succeeded after retry)\n")
        print(f"Results ({len(result['rows'])} rows):")
        print("  " + " | ".join(result["columns"]))
        print("  " + "-" * 60)
        for row in result["rows"]:
            print("  " + " | ".join(str(v) for v in row))