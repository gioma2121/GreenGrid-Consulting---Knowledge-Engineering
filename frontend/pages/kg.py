"""
Page 3 — Knowledge Graph
=========================
Interactive subgraph visualisation using Dash Cytoscape.
Loads top-N municipalities from AuraDB + their direct connections.
Click a node to inspect its properties in the side panel.

pip install dash-cytoscape
"""

import os, sys
import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    import dash_cytoscape as cyto
    cyto.load_extra_layouts()   # enables "cose-bilkent" force layout
    _CYTO_OK = True
except ImportError:
    _CYTO_OK = False

from neo4j import GraphDatabase

dash.register_page(__name__, path="/kg", name="🕸️ Knowledge Graph", order=2)

# ── Neo4j config ──────────────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI",  "neo4j+s://14361706.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "14361706")
NEO4J_PASS = os.getenv("NEO4J_PASS", "")

CONFLICT_COLORS = {
    "none":   "#2ecc71",
    "low":    "#f1c40f",
    "medium": "#e67e22",
    "high":   "#e74c3c",
}
NODE_COLORS = {
    "Municipality":   None,          # coloured by conflict level
    "Natura2000Site": "#8e44ad",
    "EnergyTechnology": "#2980b9",
    "ConflictLevel":  "#7f8c8d",
    "GridSegment":    "#1abc9c",
}
EDGE_COLORS = {
    "OVERLAPS_WITH":        "#e74c3c",
    "NEAR_TO":              "#3498db",
    "ADJACENT_TO":          "#95a5a6",
    "SUITABLE_FOR":         "#27ae60",
    "NEAREST_GRID_SEGMENT": "#1abc9c",
    "HAS_LEVEL":            "#7f8c8d",
    "IS_ABOUT":             "#e74c3c",
    "WITH_SITE":            "#8e44ad",
}


# ── Cypher query: fetch a readable subgraph ───────────────────────────────────
SUBGRAPH_QUERY = """
// Top-N municipalities by hybrid score + their direct connections
MATCH (m:Municipality)
WITH m ORDER BY m.hybrid_score DESC LIMIT $limit

// Neighbours
OPTIONAL MATCH (m)-[r1:ADJACENT_TO|NEAR_TO]->(m2:Municipality)
  WHERE m2.hybrid_score > 0.4
OPTIONAL MATCH (n:Natura2000Site)-[r2:OVERLAPS_WITH]->(m)
  WHERE r2.overlap_pct > 20
OPTIONAL MATCH (m)-[r3:SUITABLE_FOR]->(e:EnergyTechnology)
OPTIONAL MATCH (c:Conflict)-[r4:IS_ABOUT]->(m)
OPTIONAL MATCH (c)-[r5:WITH_SITE]->(n2:Natura2000Site)
OPTIONAL MATCH (c)-[r6:HAS_LEVEL]->(cl:ConflictLevel)

WITH collect(DISTINCT m)  AS munis,
     collect(DISTINCT m2) AS neighbours,
     collect(DISTINCT n)  AS natura,
     collect(DISTINCT n2) AS natura2,
     collect(DISTINCT e)  AS techs,
     collect(DISTINCT c)  AS conflicts,
     collect(DISTINCT cl) AS levels,
     collect(DISTINCT {start: id(m), end: id(m2), type: "ADJACENT_TO"})  AS e1,
     collect(DISTINCT {start: id(m), end: id(m2), type: "NEAR_TO",
                       dist: r1.distance_km})                             AS e2,
     collect(DISTINCT {start: id(n), end: id(m),  type: "OVERLAPS_WITH",
                       pct: r2.overlap_pct})                              AS e3,
     collect(DISTINCT {start: id(m), end: id(e),  type: "SUITABLE_FOR",
                       score: r3.score})                                  AS e4,
     collect(DISTINCT {start: id(c), end: id(m),  type: "IS_ABOUT"})     AS e5,
     collect(DISTINCT {start: id(c), end: id(n2), type: "WITH_SITE"})    AS e6,
     collect(DISTINCT {start: id(c), end: id(cl), type: "HAS_LEVEL"})    AS e7

RETURN munis, neighbours, natura, natura2, techs, conflicts, levels,
       e1+e2+e3+e4+e5+e6+e7 AS edges
"""


def _load_subgraph(limit: int = 25) -> tuple[list, list]:
    """Return (cytoscape_nodes, cytoscape_edges) from AuraDB."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    nodes, edges = [], []
    seen_nodes, seen_edges = set(), set()

    def _add_node(nid, label, props, color=None):
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        c_level = props.get("conflict_level", "none")
        bg = (CONFLICT_COLORS.get(c_level, "#2ecc71")
              if label == "Municipality" else color or "#bdc3c7")
        nodes.append({"data": {
            "id":    str(nid),
            "label": props.get("gemeente_naam") or props.get("site_name") or
                     props.get("name") or props.get("level") or str(nid),
            "type":  label,
            "color": bg,
            **{k: (round(v, 3) if isinstance(v, float) else v)
               for k, v in props.items() if k != "geometry"},
        }})

    def _add_edge(src, tgt, rel_type, extra=None):
        key = (str(src), str(tgt), rel_type)
        if key in seen_edges or src is None or tgt is None:
            return
        seen_edges.add(key)
        edges.append({"data": {
            "source": str(src), "target": str(tgt),
            "label":  rel_type,
            "color":  EDGE_COLORS.get(rel_type, "#95a5a6"),
            **(extra or {}),
        }})

    try:
        with driver.session() as session:
            rec = session.run(SUBGRAPH_QUERY, limit=limit).single()
            if not rec:
                return [], []

            for m in rec["munis"] + rec["neighbours"]:
                if m: _add_node(m.id, "Municipality", dict(m))
            for n in rec["natura"] + rec["natura2"]:
                if n: _add_node(n.id, "Natura2000Site", dict(n), NODE_COLORS["Natura2000Site"])
            for e in rec["techs"]:
                if e: _add_node(e.id, "EnergyTechnology", dict(e), NODE_COLORS["EnergyTechnology"])
            for c in rec["conflicts"]:
                if c: _add_node(c.id, "Conflict", dict(c), "#c0392b")
            for cl in rec["levels"]:
                if cl: _add_node(cl.id, "ConflictLevel", dict(cl), NODE_COLORS["ConflictLevel"])

            for edge in rec["edges"]:
                if edge and edge.get("start") and edge.get("end"):
                    extra = {}
                    if "dist"  in edge: extra["distance_km"] = edge["dist"]
                    if "pct"   in edge: extra["overlap_pct"] = edge["pct"]
                    if "score" in edge: extra["score"]       = edge["score"]
                    _add_edge(edge["start"], edge["end"], edge["type"], extra)
    finally:
        driver.close()

    return nodes, edges


# ── Stylesheet ────────────────────────────────────────────────────────────────
CY_STYLESHEET = [
    {"selector": "node", "style": {
        "label":            "data(label)",
        "background-color": "data(color)",
        "color":            "#fff",
        "font-size":        "9px",
        "text-valign":      "center",
        "text-halign":      "center",
        "width":            "40px",
        "height":           "40px",
        "border-width":     "2px",
        "border-color":     "rgba(0,0,0,0.15)",
        "text-wrap":        "wrap",
        "text-max-width":   "55px",
    }},
    {"selector": "node[type='Natura2000Site']",   "style": {"shape": "diamond",  "width": "30px", "height": "30px"}},
    {"selector": "node[type='EnergyTechnology']", "style": {"shape": "hexagon",  "width": "34px", "height": "34px"}},
    {"selector": "node[type='ConflictLevel']",    "style": {"shape": "round-rectangle", "width": "50px", "height": "22px"}},
    {"selector": "node[type='Conflict']",         "style": {"shape": "star",     "width": "20px", "height": "20px", "background-color": "#c0392b"}},
    {"selector": "node:selected", "style": {"border-width": "3px", "border-color": "#1a3c2e", "width": "50px", "height": "50px"}},
    {"selector": "edge", "style": {
        "line-color":           "data(color)",
        "target-arrow-color":   "data(color)",
        "target-arrow-shape":   "triangle",
        "curve-style":          "bezier",
        "width":                1.5,
        "opacity":              0.65,
        "label":                "data(label)",
        "font-size":            "7px",
        "color":                "#555",
        "text-rotation":        "autorotate",
    }},
]


# ── Layout builder ────────────────────────────────────────────────────────────
def layout(**kwargs):
    if not _CYTO_OK:
        return html.Div([
            dbc.Alert([
                html.Strong("dash-cytoscape not installed. "),
                "Run: ",
                html.Code("pip install dash-cytoscape"),
                " then restart the app.",
            ], color="warning", style={"margin": "1rem"}),
        ])

    nodes, edges = _load_subgraph(limit=25)

    return html.Div([
        # Controls bar
        html.Div([
            html.Span("🕸️ Knowledge Graph Explorer", style={
                "fontWeight": "700", "fontSize": "0.95rem", "color": "#1a3c2e"
            }),
            html.Div([
                html.Label("Top N municipalities:", style={"fontSize": "0.82rem", "marginRight": "0.5rem"}),
                html.Div(dcc.Slider(id="kg-limit", min=10, max=50, step=5, value=25,
                           marks={10: "10", 25: "25", 50: "50"},
                           tooltip={"placement": "top"}), style={"width": "180px"}),
                html.Button("Reload", id="kg-reload", n_clicks=0, style={
                    "marginLeft": "1rem", "padding": "0.3rem 0.8rem",
                    "backgroundColor": "#1a3c2e", "color": "white",
                    "border": "none", "borderRadius": "5px",
                    "cursor": "pointer", "fontSize": "0.83rem",
                }),
            ], style={"display": "flex", "alignItems": "center", "gap": "0.3rem"}),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "center",
            "backgroundColor": "white", "padding": "0.6rem 1rem",
            "borderBottom": "1px solid #e9ecef",
        }),

        # Main area: graph + side panel
        html.Div([
            # Graph
            dcc.Loading(type="circle", color="#1a3c2e", children=[
                cyto.Cytoscape(
                    id="kg-graph",
                    layout={"name": "cose-bilkent", "randomize": False,
                            "idealEdgeLength": 120, "nodeRepulsion": 8000},
                    style={"width": "100%", "height": "calc(100vh - 120px)"},
                    elements=nodes + edges,
                    stylesheet=CY_STYLESHEET,
                    minZoom=0.3, maxZoom=3.0,
                ),
            ]),

            # Side panel (shown on node click)
            html.Div(id="kg-side-panel", style={
                "width": "260px", "minWidth": "260px",
                "backgroundColor": "white", "borderLeft": "1px solid #e9ecef",
                "padding": "1rem", "overflowY": "auto",
                "height": "calc(100vh - 120px)",
            }),
        ], style={"display": "flex", "flex": "1"}),

        # Legend
        html.Div([
            html.Span("⬤ Municipality (by conflict)", style={"marginRight": "1rem", "fontSize": "0.75rem"}),
            *[html.Span(f"⬤ {k}", style={"color": v, "marginRight": "0.75rem", "fontSize": "0.75rem"})
              for k, v in CONFLICT_COLORS.items()],
            html.Span("◆ Natura 2000", style={"color": NODE_COLORS["Natura2000Site"], "marginRight": "0.75rem", "fontSize": "0.75rem"}),
            html.Span("⬡ Energy tech", style={"color": NODE_COLORS["EnergyTechnology"], "fontSize": "0.75rem"}),
        ], style={
            "backgroundColor": "white", "padding": "0.4rem 1rem",
            "borderTop": "1px solid #e9ecef", "fontSize": "0.75rem",
        }),

    ], style={"display": "flex", "flexDirection": "column",
              "height": "calc(100vh - 52px)", "overflow": "hidden"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("kg-graph", "elements"),
    Input("kg-reload", "n_clicks"),
    State("kg-limit",  "value"),
    prevent_initial_call=True,
)
def reload_graph(_, limit):
    nodes, edges = _load_subgraph(limit=limit or 25)
    return nodes + edges


@callback(
    Output("kg-side-panel", "children"),
    Input("kg-graph", "tapNodeData"),
    prevent_initial_call=True,
)
def show_node_detail(data):
    if not data:
        return html.Span("Click a node to inspect it.", style={"color": "#6c757d", "fontSize": "0.85rem"})

    node_type = data.get("type", "")
    label     = data.get("label", "")
    color     = data.get("color", "#ccc")

    rows = []
    skip = {"id", "label", "type", "color"}
    for k, v in data.items():
        if k in skip or v is None:
            continue
        rows.append(html.Tr([
            html.Td(k.replace("_", " "), style={"fontSize": "0.75rem", "color": "#6c757d",
                                                  "paddingRight": "0.5rem", "whiteSpace": "nowrap"}),
            html.Td(str(v), style={"fontSize": "0.82rem", "fontWeight": "500"}),
        ]))

    return html.Div([
        html.Div([
            html.Div(style={
                "width": "12px", "height": "12px", "borderRadius": "50%",
                "backgroundColor": color, "marginRight": "0.4rem", "flexShrink": "0",
            }),
            html.Span(node_type, style={"fontSize": "0.72rem", "color": "#6c757d", "textTransform": "uppercase"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "0.25rem"}),

        html.H6(label, style={"fontWeight": "700", "color": "#1a3c2e", "marginBottom": "0.75rem"}),

        html.Table(html.Tbody(rows), style={"width": "100%", "borderCollapse": "collapse"}),
    ])