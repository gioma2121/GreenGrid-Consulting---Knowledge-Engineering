"""
Page 1 — Siting Map
Full-viewport layout: left sidebar (filters) + right column (map on top, chat pinned at bottom).
"""

import json, os, sys
import dash
from dash import html, dcc, callback, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import geopandas as gpd
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nl_cypher import ask

dash.register_page(__name__, path="/", name="🗺️ Map", order=0)

# ── Data ──────────────────────────────────────────────────────────────────────
_GPKG  = os.getenv("GPKG_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "processed", "greengrid_full.gpkg"))
_gdf   = gpd.read_file(_GPKG, layer="municipalities").to_crs(4326).reset_index(drop=True)
_GJ    = json.loads(_gdf.to_json())
_DF    = pd.DataFrame(_gdf.drop(columns="geometry"))

SCORE_OPTIONS = [
    {"label": "Hybrid score",        "value": "hybrid_score"},
    {"label": "Wind score",          "value": "wind_score"},
    {"label": "Solar score",         "value": "solar_score"},
    {"label": "Grid distance (km)",  "value": "grid_distance_km"},
    {"label": "Available land (ha)", "value": "available_land_ha"},
]
C_COLORS = {"none": "#2ecc71", "low": "#f1c40f", "medium": "#e67e22", "high": "#e74c3c"}

FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', 'Helvetica Neue', Arial, sans-serif"

# ── Map builder ───────────────────────────────────────────────────────────────
def _make_map(dff, color_col="hybrid_score"):
    reverse = color_col == "grid_distance_km"
    fig = px.choropleth_mapbox(
        dff, geojson=_GJ, locations=dff.index, color=color_col,
        color_continuous_scale="RdYlGn_r" if reverse else "RdYlGn",
        range_color=[0, dff[color_col].max()] if reverse else [0, 1],
        mapbox_style="open-street-map", zoom=6.4,
        center={"lat": 52.3, "lon": 5.3}, opacity=0.72,
        hover_name="gemeente_naam",
        hover_data={"hybrid_score": ":.3f", "wind_score": ":.3f",
                    "solar_score": ":.3f", "conflict_level": True,
                    "grid_distance_km": ":.2f", "available_land_ha": ":,.0f"},
        labels={color_col: color_col.replace("_", " ").title()},
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=None,
        coloraxis_colorbar=dict(thickness=12, len=0.55, x=0.99, y=0.5,
                                tickfont=dict(size=11)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

# ── Sidebar ───────────────────────────────────────────────────────────────────
LABEL_STYLE = {
    "fontSize": "10px", "fontWeight": "600", "letterSpacing": "0.08em",
    "color": "#86868b", "textTransform": "uppercase", "marginBottom": "6px",
    "display": "block", "fontFamily": FONT,
}
DIVIDER = html.Hr(style={"border": "none", "borderTop": "1px solid #f0f0f0", "margin": "14px 0"})

sidebar = html.Div([

    html.Span("COLOUR BY", style=LABEL_STYLE),
    dcc.Dropdown(id="map-color-col", options=SCORE_OPTIONS, value="hybrid_score",
                 clearable=False, style={"fontSize": "13px", "fontFamily": FONT}),

    DIVIDER,

    html.Span("CONFLICT LEVEL", style=LABEL_STYLE),
    dcc.Checklist(
        id="map-conflict",
        options=[{"label": html.Span(lv, style={"color": C_COLORS[lv], "fontWeight": "600",
                                                  "fontSize": "13px", "marginLeft": "5px",
                                                  "fontFamily": FONT}),
                  "value": lv} for lv in ["none", "low", "medium", "high"]],
        value=["none", "low", "medium", "high"],
        labelStyle={"display": "flex", "alignItems": "center", "marginBottom": "5px"},
    ),

    DIVIDER,

    html.Span("MIN AVAILABLE LAND (HA)", style=LABEL_STYLE),
    dcc.Slider(id="map-land", min=0, max=40000, step=500, value=0,
               marks={0: "0", 10000: "10k", 20000: "20k", 40000: "40k"},
               tooltip={"placement": "bottom", "always_visible": False}),

    DIVIDER,

    html.Span("MAX GRID DISTANCE (KM)", style=LABEL_STYLE),
    dcc.Slider(id="map-grid", min=0, max=25, step=0.5, value=25,
               marks={0: "0", 5: "5", 10: "10", 25: "25+"},
               tooltip={"placement": "bottom", "always_visible": False}),

    DIVIDER,

    html.Span("MAX POP DENSITY (KM²)", style=LABEL_STYLE),
    dcc.Slider(id="map-pop", min=0, max=7000, step=100, value=7000,
               marks={0: "0", 2000: "2k", 5000: "5k", 7000: "7k"},
               tooltip={"placement": "bottom", "always_visible": False}),

    DIVIDER,

    html.Div(id="map-count-badge"),

], style={
    "width": "200px", "minWidth": "200px", "flexShrink": "0",
    "backgroundColor": "white",
    "borderRight": "1px solid #f0f0f0",
    "padding": "20px 16px",
    "overflowY": "auto",
    "fontFamily": FONT,
})

# ── Chat panel ────────────────────────────────────────────────────────────────
chat_panel = html.Div([
    html.Div([
        # Input row
        html.Div([
            html.Span("✦", style={
                "fontSize": "14px", "color": "#1d1d1f", "marginRight": "10px",
                "flexShrink": "0", "lineHeight": "1",
            }),
            dcc.Input(
                id="chat-input", type="text", n_submit=0,
                placeholder="Ask the knowledge graph anything…",
                style={
                    "flex": "1", "border": "none", "outline": "none",
                    "fontSize": "14px", "color": "#1d1d1f",
                    "backgroundColor": "transparent", "fontFamily": FONT,
                    "letterSpacing": "-0.01em",
                },
            ),
            html.Button("Ask →", id="chat-submit", n_clicks=0, style={
                "flexShrink": "0", "border": "none", "outline": "none",
                "backgroundColor": "#1d1d1f", "color": "white",
                "padding": "7px 16px", "borderRadius": "20px",
                "fontSize": "13px", "fontWeight": "500", "cursor": "pointer",
                "fontFamily": FONT, "letterSpacing": "-0.01em",
                "transition": "opacity 0.15s",
            }),
        ], style={
            "display": "flex", "alignItems": "center",
            "backgroundColor": "#f5f5f7",
            "borderRadius": "12px",
            "padding": "10px 14px",
            "gap": "6px",
        }),

        # Results area
        dcc.Loading(type="circle", color="#1d1d1f", children=[
            html.Div(id="chat-output", style={"marginTop": "10px"}),
        ]),
    ], style={"maxWidth": "900px", "margin": "0 auto", "width": "100%"}),
], style={
    "borderTop": "1px solid #e8e8ed",
    "backgroundColor": "white",
    "padding": "14px 24px 16px",
    "fontFamily": FONT,
    "flexShrink": "0",
})

# ── Page layout ───────────────────────────────────────────────────────────────
layout = html.Div([
    html.Div([
        # LEFT: Sidebar
        sidebar,

        # RIGHT: Map + Chat
        html.Div([
            # Map (fills remaining height)
            dcc.Graph(
                id="main-map",
                figure=_make_map(_DF),
                config={"scrollZoom": True},
                style={"flex": "1", "minHeight": "0"},
            ),
            # Chat (pinned at bottom)
            chat_panel,
        ], style={
            "flex": "1", "display": "flex", "flexDirection": "column",
            "minWidth": "0", "height": "100%",
        }),

    ], style={
        "display": "flex",
        "height": "calc(100vh - 52px)",
        "overflow": "hidden",
    }),
], style={"fontFamily": FONT})


# ── Callbacks ─────────────────────────────────────────────────────────────────
@callback(
    Output("main-map",        "figure"),
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
        (_DF["available_land_ha"] >= min_land) &
        (_DF["grid_distance_km"]  <= max_grid) &
        (_DF["pop_density_km2"]   <= max_pop)
    ]
    fig = _make_map(dff, color_col)
    badge = html.Div([
        html.Span(f"{len(dff)}", style={
            "fontSize": "28px", "fontWeight": "700", "color": "#1d1d1f",
            "letterSpacing": "-0.03em", "fontFamily": FONT,
        }),
        html.Span(f" / 342", style={"fontSize": "13px", "color": "#86868b", "fontFamily": FONT}),
        html.Br(),
        html.Span("municipalities", style={"fontSize": "11px", "color": "#86868b",
                                            "fontFamily": FONT, "letterSpacing": "0.02em"}),
    ], style={"marginTop": "8px"})
    store = {"conflict_levels": conflicts, "min_land_ha": min_land,
             "max_grid_km": max_grid, "max_pop_density": max_pop}
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
        return None

    result = ask(question.strip())

    if result["error"]:
        return html.Div([
            html.Div([
                html.Span("Something went wrong", style={
                    "fontSize": "13px", "fontWeight": "500", "color": "#ff3b30", "fontFamily": FONT,
                }),
                html.Details([
                    html.Summary("View error", style={"fontSize": "12px", "color": "#86868b",
                                                       "cursor": "pointer", "fontFamily": FONT}),
                    html.Code(result["error"], style={"fontSize": "11px", "color": "#ff3b30"}),
                ], style={"marginTop": "4px"}),
            ] + ([_cypher_block(result["cypher"])] if result["cypher"] else []),
            style={"padding": "10px 14px", "backgroundColor": "#fff2f0",
                   "borderRadius": "10px", "border": "1px solid #ffccc7"}),
        ])

    if not result["rows"]:
        return html.Div(
            "No results found for this query.",
            style={"fontSize": "13px", "color": "#86868b", "fontFamily": FONT,
                   "padding": "8px 0"},
        )

    # Results table — minimal style
    table = dash_table.DataTable(
        columns=[{"name": c.replace("_", " "), "id": c} for c in result["columns"]],
        data=[dict(zip(result["columns"], row)) for row in result["rows"]],
        page_size=6, sort_action="native",
        style_table={"overflowX": "auto", "borderRadius": "10px",
                     "border": "1px solid #e8e8ed"},
        style_header={"backgroundColor": "#f5f5f7", "color": "#1d1d1f",
                      "fontWeight": "600", "fontSize": "11px",
                      "textTransform": "uppercase", "letterSpacing": "0.06em",
                      "padding": "9px 12px", "border": "none",
                      "fontFamily": FONT},
        style_cell={"fontSize": "12px", "padding": "8px 12px",
                    "border": "none", "borderBottom": "1px solid #f5f5f7",
                    "fontFamily": FONT, "color": "#1d1d1f"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafafa"}
        ],
    )

    retried = html.Span(" · auto-retried", style={
        "fontSize": "11px", "color": "#ff9500", "fontFamily": FONT
    }) if result["retried"] else None

    return html.Div([
        html.Div([
            html.Span(f"{len(result['rows'])} result{'s' if len(result['rows']) != 1 else ''}",
                      style={"fontSize": "12px", "color": "#86868b", "fontFamily": FONT}),
            retried,
        ], style={"display": "flex", "alignItems": "center", "gap": "4px",
                  "marginBottom": "8px"}),
        table,
        _cypher_block(result["cypher"]),
    ])


def _cypher_block(cypher):
    if not cypher:
        return html.Div()
    return html.Details([
        html.Summary("View Cypher", style={
            "fontSize": "11px", "color": "#86868b", "cursor": "pointer",
            "marginTop": "8px", "fontFamily": FONT, "letterSpacing": "0.01em",
        }),
        html.Pre(cypher, style={
            "backgroundColor": "#f5f5f7", "padding": "10px 14px",
            "borderRadius": "8px", "fontSize": "11px", "lineHeight": "1.6",
            "overflowX": "auto", "marginTop": "6px",
            "color": "#1d1d1f", "fontFamily": "'SF Mono', 'Fira Code', monospace",
            "border": "1px solid #e8e8ed",
        }),
    ])