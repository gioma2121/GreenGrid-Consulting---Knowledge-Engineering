"""
Page 3 — Knowledge Graph
Interactive subgraph visualisation using Dash Cytoscape.
Uses simple queries (no complex COLLECT) and gemeente_naam as node IDs.

pip install dash-cytoscape
"""

import os, logging
import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc

log = logging.getLogger(__name__)

try:
    import dash_cytoscape as cyto
    cyto.load_extra_layouts()
    _CYTO_OK = True
except ImportError:
    _CYTO_OK = False

from neo4j import GraphDatabase

dash.register_page(__name__, path="/kg", name="🕸️ Knowledge Graph", order=2)

NEO4J_URI  = os.getenv("NEO4J_URI",  "neo4j+s://14361706.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "14361706")
NEO4J_PASS = os.getenv("NEO4J_PASS", "")

FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', sans-serif"
C_CONFLICT = {"none": "#2ecc71", "low": "#f1c40f", "medium": "#e67e22", "high": "#e74c3c"}


# ── Neo4j helpers ─────────────────────────────────────────────────────────────
def _load_subgraph(limit: int = 25):
    """
    Load a subgraph using simple queries. Returns (nodes, edges) for Cytoscape.
    Uses gemeente_naam / site_code as string IDs (avoids id() deprecation issues).
    """
    nodes, edges = [], []
    if not NEO4J_PASS:
        log.error("NEO4J_PASS not set")
        return nodes, edges

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session() as session:

            # 1. Top-N municipalities
            res = session.run("""
                MATCH (m:Municipality)
                RETURN m.gemeente_naam      AS name,
                       m.hybrid_score       AS hybrid,
                       m.wind_score         AS wind,
                       m.solar_score        AS solar,
                       m.conflict_level     AS conflict,
                       m.grid_distance_km   AS grid_km,
                       m.available_land_ha  AS land_ha,
                       m.pop_density_km2    AS pop_den
                ORDER BY m.hybrid_score DESC
                LIMIT $limit
            """, limit=limit)
            muni_names = []
            for r in res:
                name = r["name"]
                muni_names.append(name)
                nodes.append({"data": {
                    "id":           name,
                    "label":        name,
                    "type":         "Municipality",
                    "color":        C_CONFLICT.get(r["conflict"] or "none", "#2ecc71"),
                    "hybrid_score": round(r["hybrid"] or 0, 3),
                    "wind_score":   round(r["wind"]   or 0, 3),
                    "solar_score":  round(r["solar"]  or 0, 3),
                    "conflict_level":    r["conflict"] or "none",
                    "grid_distance_km":  round(r["grid_km"] or 0, 2),
                    "available_land_ha": round(r["land_ha"] or 0, 0),
                }})
            log.info("KG: loaded %d municipality nodes", len(muni_names))

            if not muni_names:
                return nodes, edges

            # 2. ADJACENT_TO edges (between top municipalities only)
            res = session.run("""
                MATCH (a:Municipality)-[:ADJACENT_TO]->(b:Municipality)
                WHERE a.gemeente_naam IN $names
                  AND b.gemeente_naam IN $names
                RETURN a.gemeente_naam AS a, b.gemeente_naam AS b
                LIMIT 300
            """, names=muni_names)
            seen_adj = set()
            for r in res:
                key = tuple(sorted([r["a"], r["b"]]))
                if key not in seen_adj:
                    seen_adj.add(key)
                    edges.append({"data": {
                        "id":     f"adj_{r['a']}_{r['b']}",
                        "source": r["a"], "target": r["b"],
                        "label":  "adjacent", "color": "#bdc3c7",
                    }})

            # 3. Natura 2000 sites with significant overlap
            res = session.run("""
                MATCH (n:Natura2000Site)-[r:OVERLAPS_WITH]->(m:Municipality)
                WHERE m.gemeente_naam IN $names
                  AND r.overlap_pct > 25
                RETURN n.site_code AS code, n.site_name AS site_name,
                       m.gemeente_naam AS muni,
                       round(r.overlap_pct, 1) AS pct
                LIMIT 60
            """, names=muni_names)
            natura_seen = set()
            for r in res:
                code = r["code"] or "UNK"
                nid  = f"n_{code}"
                if nid not in natura_seen:
                    natura_seen.add(nid)
                    nodes.append({"data": {
                        "id":    nid,
                        "label": (r["site_name"] or code)[:18],
                        "type":  "Natura2000Site",
                        "color": "#8e44ad",
                        "site_code": code,
                        "site_name": r["site_name"] or code,
                    }})
                edges.append({"data": {
                    "id":     f"ov_{code}_{r['muni']}",
                    "source": nid, "target": r["muni"],
                    "label":  f"{r['pct']}%", "color": "#e74c3c",
                }})
            log.info("KG: loaded %d Natura2000 nodes, %d overlap edges",
                     len(natura_seen), len([e for e in edges if "ov_" in e["data"]["id"]]))

            # 4. EnergyTechnology singletons
            res = session.run("MATCH (e:EnergyTechnology) RETURN e.name AS name")
            for r in res:
                nodes.append({"data": {
                    "id": f"tech_{r['name']}", "label": r["name"],
                    "type": "EnergyTechnology", "color": "#2980b9",
                }})

            # 5. SUITABLE_FOR edges (top-10 municipalities only, score > 0.65)
            res = session.run("""
                MATCH (m:Municipality)-[r:SUITABLE_FOR]->(e:EnergyTechnology)
                WHERE m.gemeente_naam IN $names AND r.score > 0.65
                RETURN m.gemeente_naam AS muni, e.name AS tech,
                       round(r.score, 3) AS score
                LIMIT 80
            """, names=muni_names[:15])
            for r in res:
                edges.append({"data": {
                    "id":     f"sf_{r['muni']}_{r['tech']}",
                    "source": r["muni"], "target": f"tech_{r['tech']}",
                    "label":  str(r["score"]), "color": "#27ae60",
                }})

    except Exception as exc:
        log.error("KG load failed: %s", exc)
    finally:
        driver.close()

    log.info("KG: total %d nodes, %d edges", len(nodes), len(edges))
    return nodes, edges


# ── Cytoscape stylesheet ──────────────────────────────────────────────────────
STYLESHEET = [
    {"selector": "node", "style": {
        "label":            "data(label)",
        "background-color": "data(color)",
        "color":            "#fff",
        "font-size":        "10px",
        "text-valign":      "center",
        "text-halign":      "center",
        "width":            "42px",
        "height":           "42px",
        "border-width":     "1.5px",
        "border-color":     "rgba(255,255,255,0.3)",
        "text-wrap":        "wrap",
        "text-max-width":   "60px",
        "font-family":      FONT,
    }},
    {"selector": "node[type='Natura2000Site']", "style": {
        "shape": "diamond", "width": "32px", "height": "32px", "font-size": "8px",
    }},
    {"selector": "node[type='EnergyTechnology']", "style": {
        "shape": "hexagon", "width": "36px", "height": "36px",
    }},
    {"selector": "node:selected", "style": {
        "border-width": "3px", "border-color": "#1d1d1f",
        "width": "52px", "height": "52px",
    }},
    {"selector": "edge", "style": {
        "line-color":           "data(color)",
        "target-arrow-color":   "data(color)",
        "target-arrow-shape":   "triangle",
        "curve-style":          "bezier",
        "width":                1.5,
        "opacity":              0.6,
        "font-size":            "8px",
        "font-family":          FONT,
        "color":                "#555",
        "text-rotation":        "autorotate",
    }},
    {"selector": "edge[label='adjacent']", "style": {
        "width": 1, "opacity": 0.3, "target-arrow-shape": "none",
    }},
]


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**kwargs):
    if not _CYTO_OK:
        return html.Div(
            dbc.Alert([html.Strong("dash-cytoscape not installed. "),
                       "Run: ", html.Code("pip install dash-cytoscape"),
                       " then restart."], color="warning"),
            style={"padding": "1rem"},
        )

    return html.Div([

        # Top bar
        html.Div([
            html.Span("Knowledge Graph Explorer", style={
                "fontWeight": "600", "fontSize": "14px",
                "color": "#1d1d1f", "fontFamily": FONT, "letterSpacing": "-0.01em",
            }),
            html.Div([
                html.Span("Top N:", style={"fontSize": "12px", "color": "#86868b",
                                            "fontFamily": FONT, "marginRight": "8px"}),
                html.Div(dcc.Slider(id="kg-limit", min=10, max=50, step=5, value=25,
                             marks={10: "10", 25: "25", 50: "50"},
                             tooltip={"placement": "top"}),
                         style={"width": "160px"}),
                html.Button("Reload", id="kg-reload", n_clicks=0, style={
                    "marginLeft": "12px", "padding": "5px 14px",
                    "backgroundColor": "#1d1d1f", "color": "white",
                    "border": "none", "borderRadius": "20px",
                    "fontSize": "12px", "fontWeight": "500",
                    "cursor": "pointer", "fontFamily": FONT,
                }),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "center",
            "padding": "10px 20px", "backgroundColor": "white",
            "borderBottom": "1px solid #f0f0f0",
        }),

        # Graph + side panel
        html.Div([
            # Loading + Cytoscape
            html.Div([
                dcc.Loading(type="dot", color="#1d1d1f", children=[
                    html.Div(id="kg-loading-output"),
                ]),
                cyto.Cytoscape(
                    id="kg-graph",
                    layout={"name": "cose", "randomize": False,
                            "idealEdgeLength": 100, "nodeRepulsion": 5000,
                            "animate": False},
                    style={"width": "100%", "height": "100%"},
                    elements=[],   # loaded via callback on mount
                    stylesheet=STYLESHEET,
                    minZoom=0.2, maxZoom=3.5,
                ),
            ], style={"flex": "1", "position": "relative", "height": "100%"}),

            # Side panel
            html.Div([
                html.Div(id="kg-side-panel", children=[
                    html.Div([
                        html.Div("Click a node to", style={"fontSize": "12px", "color": "#86868b",
                                                             "fontFamily": FONT}),
                        html.Div("inspect it", style={"fontSize": "12px", "color": "#86868b",
                                                       "fontFamily": FONT}),
                    ], style={"marginTop": "30px", "textAlign": "center"}),
                ]),
            ], style={
                "width": "240px", "minWidth": "240px",
                "borderLeft": "1px solid #f0f0f0",
                "backgroundColor": "white", "padding": "16px",
                "overflowY": "auto",
            }),
        ], style={"display": "flex", "flex": "1", "minHeight": "0"}),

        # Legend
        html.Div([
            *[html.Span([
                html.Span("●", style={"color": c, "marginRight": "3px"}),
                html.Span(lv, style={"marginRight": "14px", "color": "#555"}),
            ], style={"fontSize": "11px", "fontFamily": FONT})
              for lv, c in C_CONFLICT.items()],
            html.Span("◆ Natura 2000", style={"fontSize": "11px", "color": "#8e44ad",
                                               "marginRight": "14px", "fontFamily": FONT}),
            html.Span("⬡ Energy tech", style={"fontSize": "11px", "color": "#2980b9",
                                               "fontFamily": FONT}),
        ], style={
            "padding": "8px 20px", "backgroundColor": "white",
            "borderTop": "1px solid #f0f0f0", "display": "flex", "alignItems": "center",
        }),

        # Trigger initial load
        dcc.Store(id="kg-init-trigger"),

    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "calc(100vh - 52px)", "overflow": "hidden",
        "fontFamily": FONT, "backgroundColor": "#fafafa",
    })


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("kg-graph",          "elements"),
    Output("kg-loading-output", "children"),
    Input("kg-reload",  "n_clicks"),
    State("kg-limit",   "value"),
)
def load_graph(n_clicks, limit):
    nodes, edges = _load_subgraph(limit=limit or 25)
    if not nodes:
        msg = html.Div("Could not load graph — check Neo4j credentials and connection.",
                       style={"padding": "20px", "color": "#ff3b30",
                              "fontSize": "13px", "fontFamily": FONT})
        return [], msg
    return nodes + edges, None


# Trigger initial load on page open (n_clicks=0 fires once on mount)
@callback(
    Output("kg-reload", "n_clicks"),
    Input("kg-init-trigger", "data"),
    prevent_initial_call=False,
)
def trigger_initial_load(_):
    return 1


@callback(
    Output("kg-side-panel", "children"),
    Input("kg-graph", "tapNodeData"),
    prevent_initial_call=True,
)
def show_node_detail(data):
    if not data:
        return html.Span("Click a node to inspect it.",
                         style={"fontSize": "12px", "color": "#86868b", "fontFamily": FONT})

    skip = {"id", "label", "type", "color"}
    color = data.get("color", "#ccc")
    node_type = data.get("type", "")

    rows = []
    for k, v in data.items():
        if k in skip or v is None:
            continue
        rows.append(html.Div([
            html.Span(k.replace("_", " "), style={
                "fontSize": "10px", "color": "#86868b", "textTransform": "uppercase",
                "letterSpacing": "0.06em", "display": "block", "fontFamily": FONT,
                "marginBottom": "1px",
            }),
            html.Span(str(v), style={
                "fontSize": "13px", "color": "#1d1d1f", "fontWeight": "500",
                "fontFamily": FONT,
            }),
        ], style={"marginBottom": "10px"}))

    return html.Div([
        html.Div([
            html.Div(style={
                "width": "10px", "height": "10px", "borderRadius": "50%",
                "backgroundColor": color, "flexShrink": "0",
            }),
            html.Span(node_type, style={
                "fontSize": "10px", "color": "#86868b", "textTransform": "uppercase",
                "letterSpacing": "0.08em", "fontFamily": FONT,
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "6px"}),
        html.Div(data.get("label", ""), style={
            "fontSize": "15px", "fontWeight": "700", "color": "#1d1d1f",
            "letterSpacing": "-0.02em", "fontFamily": FONT, "marginBottom": "14px",
            "paddingBottom": "12px", "borderBottom": "1px solid #f0f0f0",
        }),
        *rows,
    ])