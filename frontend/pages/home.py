"""
Page 1 — Siting Map
====================
Choropleth map of Dutch municipalities coloured by hybrid/wind/solar score.
Left sidebar: constraint filters (synced to Analytics page via dcc.Store).
Bottom panel: NL→Cypher chat backed by DeepSeek + AuraDB.
"""

import json, os, sys
import dash
from dash import html, dcc, callback, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import geopandas as gpd
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.nl_cypher import ask

dash.register_page(__name__, path="/", name="🗺️ Map", order=0)

# ── Load geodata once at startup ──────────────────────────────────────────────
_GPKG = os.getenv("GPKG_PATH", "greengrid_full.gpkg")
_gdf  = gpd.read_file(_GPKG, layer="municipalities").to_crs(4326)
_gdf  = _gdf.reset_index(drop=True)
_GEOJSON = json.loads(_gdf.to_json())
_DF = pd.DataFrame(_gdf.drop(columns="geometry"))

SCORE_OPTIONS = [
    {"label": "Hybrid score",  "value": "hybrid_score"},
    {"label": "Wind score",    "value": "wind_score"},
    {"label": "Solar score",   "value": "solar_score"},
    {"label": "Grid distance (km)", "value": "grid_distance_km"},
    {"label": "Available land (ha)",  "value": "available_land_ha"},
]

CONFLICT_COLORS = {"none": "#2ecc71", "low": "#f1c40f", "medium": "#e67e22", "high": "#e74c3c"}

# ── Helper: build choropleth ──────────────────────────────────────────────────
def _make_map(dff: pd.DataFrame, color_col: str = "hybrid_score"):
    reverse = color_col == "grid_distance_km"  # lower = better for grid distance
    fig = px.choropleth_mapbox(
        dff,
        geojson=_GEOJSON,
        locations=dff.index,
        color=color_col,
        color_continuous_scale="RdYlGn_r" if reverse else "RdYlGn",
        range_color=[0, dff[color_col].max()] if reverse else [0, 1],
        mapbox_style="open-street-map",
        zoom=6.4,
        center={"lat": 52.3, "lon": 5.3},
        opacity=0.72,
        hover_name="gemeente_naam",
        hover_data={
            "hybrid_score":    ":.3f",
            "wind_score":      ":.3f",
            "solar_score":     ":.3f",
            "conflict_level":  True,
            "grid_distance_km": ":.2f",
            "available_land_ha": ":,.0f",
        },
        labels={color_col: color_col.replace("_", " ").title()},
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=530,
        coloraxis_colorbar=dict(thickness=14, len=0.6, x=0.99),
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
SIDEBAR = html.Div([

    html.P("COLOUR BY", style={"fontSize": "0.7rem", "fontWeight": "700",
                                "color": "#6c757d", "letterSpacing": "0.08em", "marginBottom": "0.3rem"}),
    dcc.Dropdown(
        id="map-color-col",
        options=SCORE_OPTIONS,
        value="hybrid_score",
        clearable=False,
        style={"fontSize": "0.85rem"},
    ),

    html.Hr(style={"margin": "1rem 0"}),

    html.P("CONFLICT LEVEL", style={"fontSize": "0.7rem", "fontWeight": "700",
                                     "color": "#6c757d", "letterSpacing": "0.08em", "marginBottom": "0.4rem"}),
    dcc.Checklist(
        id="map-conflict",
        options=[{"label": html.Span(lv, style={"color": CONFLICT_COLORS[lv], "fontWeight": "600",
                                                  "marginLeft": "0.3rem"}),
                  "value": lv}
                 for lv in ["none", "low", "medium", "high"]],
        value=["none", "low", "medium", "high"],
        labelStyle={"display": "flex", "alignItems": "center", "marginBottom": "0.4rem"},
    ),

    html.Hr(style={"margin": "1rem 0"}),

    html.P("MIN AVAILABLE LAND (HA)", style={"fontSize": "0.7rem", "fontWeight": "700",
                                              "color": "#6c757d", "letterSpacing": "0.08em", "marginBottom": "0.4rem"}),
    dcc.Slider(id="map-land", min=0, max=40000, step=500, value=0,
               marks={0: "0", 10000: "10k", 20000: "20k", 40000: "40k"},
               tooltip={"placement": "bottom", "always_visible": False}),

    html.Hr(style={"margin": "1rem 0"}),

    html.P("MAX GRID DISTANCE (KM)", style={"fontSize": "0.7rem", "fontWeight": "700",
                                             "color": "#6c757d", "letterSpacing": "0.08em", "marginBottom": "0.4rem"}),
    dcc.Slider(id="map-grid", min=0, max=25, step=0.5, value=25,
               marks={0: "0", 5: "5", 10: "10", 25: "25+"},
               tooltip={"placement": "bottom", "always_visible": False}),

    html.Hr(style={"margin": "1rem 0"}),

    html.P("MAX POP DENSITY (KM²)", style={"fontSize": "0.7rem", "fontWeight": "700",
                                            "color": "#6c757d", "letterSpacing": "0.08em", "marginBottom": "0.4rem"}),
    dcc.Slider(id="map-pop", min=0, max=7000, step=100, value=7000,
               marks={0: "0", 2000: "2k", 5000: "5k", 7000: "7k"},
               tooltip={"placement": "bottom", "always_visible": False}),

    html.Hr(style={"margin": "1.2rem 0 0.5rem"}),

    html.Div(id="map-count-badge", style={"textAlign": "center"}),

], style={
    "width": "220px", "minWidth": "220px", "padding": "1rem",
    "backgroundColor": "white", "borderRadius": "8px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.1)", "height": "fit-content",
})


# ── Chat panel ────────────────────────────────────────────────────────────────
CHAT_PANEL = html.Div([
    html.Div([
        html.Span("💬 Ask the Knowledge Graph", style={
            "fontWeight": "700", "fontSize": "0.95rem", "color": "#1a3c2e"
        }),
        html.Span(" — natural language → Cypher → AuraDB", style={
            "fontSize": "0.78rem", "color": "#6c757d", "marginLeft": "0.5rem"
        }),
    ], style={"marginBottom": "0.6rem"}),

    html.Div([
        dcc.Input(
            id="chat-input",
            type="text",
            placeholder='e.g. "Top 10 wind municipalities with no Natura 2000 conflict"',
            debounce=False,
            style={
                "width": "100%", "padding": "0.5rem 0.75rem",
                "border": "1.5px solid #d0d7d2", "borderRadius": "6px",
                "fontSize": "0.88rem", "outline": "none",
            },
            n_submit=0,
        ),
        html.Button("Ask →", id="chat-submit", n_clicks=0, style={
            "marginLeft": "0.6rem", "padding": "0.5rem 1.1rem",
            "backgroundColor": "#1a3c2e", "color": "white",
            "border": "none", "borderRadius": "6px",
            "fontWeight": "600", "cursor": "pointer", "whiteSpace": "nowrap",
        }),
    ], style={"display": "flex", "alignItems": "center"}),

    # Loading wrapper
    dcc.Loading(type="circle", color="#1a3c2e", children=[
        html.Div(id="chat-output", style={"marginTop": "0.75rem"}),
    ]),

], style={
    "backgroundColor": "white", "borderRadius": "8px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.1)",
    "padding": "1rem 1.2rem", "marginTop": "0.75rem",
})


# ── Page layout ───────────────────────────────────────────────────────────────
layout = html.Div([

    # Top section: sidebar + map
    html.Div([
        SIDEBAR,
        html.Div([
            dcc.Graph(id="main-map", config={"scrollZoom": True},
                      figure=_make_map(_DF)),
        ], style={"flex": "1", "minWidth": "0"}),
    ], style={"display": "flex", "gap": "0.75rem", "padding": "0.75rem"}),

    # Bottom section: chat
    html.Div(CHAT_PANEL, style={"padding": "0 0.75rem 0.75rem"}),

])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("main-map",       "figure"),
    Output("map-count-badge", "children"),
    Output("filters-store",   "data"),
    Input("map-color-col", "value"),
    Input("map-conflict",  "value"),
    Input("map-land",      "value"),
    Input("map-grid",      "value"),
    Input("map-pop",       "value"),
)
def update_map(color_col, conflicts, min_land, max_grid, max_pop):
    dff = _DF[
        _DF["conflict_level"].isin(conflicts) &
        (_DF["available_land_ha"]  >= min_land) &
        (_DF["grid_distance_km"]   <= max_grid) &
        (_DF["pop_density_km2"]    <= max_pop)
    ]
    fig = _make_map(dff, color_col)

    badge = html.Div([
        html.Span(f"{len(dff)}", style={"fontSize": "1.8rem", "fontWeight": "700", "color": "#1a3c2e"}),
        html.Span(" / 342", style={"fontSize": "0.85rem", "color": "#6c757d"}),
        html.Br(),
        html.Span("municipalities", style={"fontSize": "0.75rem", "color": "#6c757d"}),
    ])

    store = {
        "conflict_levels": conflicts,
        "min_land_ha":     min_land,
        "max_grid_km":     max_grid,
        "max_pop_density": max_pop,
    }
    return fig, badge, store


@callback(
    Output("chat-output", "children"),
    Input("chat-submit", "n_clicks"),
    Input("chat-input",  "n_submit"),
    State("chat-input",  "value"),
    prevent_initial_call=True,
)
def run_chat(n_clicks, n_submit, question):
    if not question or not question.strip():
        return html.Span("Please type a question first.", style={"color": "#6c757d", "fontSize": "0.85rem"})

    result = ask(question.strip())

    # ── Error state ─────────────────────────────────────────────────────────
    if result["error"]:
        return html.Div([
            html.Div("⚠️ Query failed", style={"fontWeight": "600", "color": "#c0392b", "marginBottom": "0.3rem"}),
            html.Code(result["error"], style={"fontSize": "0.78rem", "color": "#c0392b"}),
            _cypher_toggle(result["cypher"]),
        ])

    # ── Empty result ─────────────────────────────────────────────────────────
    if not result["rows"]:
        return html.Div([
            html.Span("✓ Query ran but returned no results.", style={"color": "#6c757d", "fontSize": "0.85rem"}),
            _cypher_toggle(result["cypher"]),
        ])

    # ── Results table ────────────────────────────────────────────────────────
    table = dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in result["columns"]],
        data=[dict(zip(result["columns"], row)) for row in result["rows"]],
        page_size=8,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#1a3c2e", "color": "white",
            "fontWeight": "600", "fontSize": "0.78rem", "textTransform": "uppercase",
            "letterSpacing": "0.05em",
        },
        style_cell={
            "fontSize": "0.83rem", "padding": "0.4rem 0.6rem",
            "border": "1px solid #e9ecef", "textAlign": "left",
        },
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#f8faf9"}],
    )

    retried_badge = (
        html.Span(" (auto-retried)", style={"fontSize": "0.72rem", "color": "#e67e22", "marginLeft": "0.4rem"})
        if result["retried"] else None
    )

    return html.Div([
        html.Div([
            html.Span(f"✓ {len(result['rows'])} row(s)", style={"fontWeight": "600", "color": "#1a3c2e", "fontSize": "0.85rem"}),
            retried_badge,
        ], style={"marginBottom": "0.4rem"}),
        table,
        _cypher_toggle(result["cypher"]),
    ])


def _cypher_toggle(cypher: str):
    """Collapsible 'View Cypher' block shown under every result."""
    if not cypher:
        return html.Div()
    return html.Details([
        html.Summary("View Cypher", style={
            "cursor": "pointer", "fontSize": "0.78rem",
            "color": "#6c757d", "marginTop": "0.5rem",
        }),
        html.Pre(cypher, style={
            "backgroundColor": "#f1f3f2", "padding": "0.6rem 0.8rem",
            "borderRadius": "5px", "fontSize": "0.78rem",
            "overflowX": "auto", "marginTop": "0.4rem",
            "border": "1px solid #dde3df",
        }),
    ])