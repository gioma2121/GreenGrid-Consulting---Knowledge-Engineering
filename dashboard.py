"""
dashboard.py
============
GreenGrid Consulting – Interactive Renewable Energy Siting Dashboard
Run with: python dashboard.py
Then open http://127.0.0.1:8050 in your browser.
"""

import numpy as np
np.bool8 = np.bool_  # compatibility fix

import pandas as pd
from dash import Dash, dcc, html, Input, Output, dash_table
import plotly.express as px
import plotly.graph_objects as go
import geopandas as gpd
import os

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA  (replace with your actual path)
# ─────────────────────────────────────────────────────────────────────────────
import geopandas as gpd, os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GPKG_PATH = os.path.join(BASE_DIR, "greengrid_full.gpkg")
gdf = gpd.read_file(GPKG_PATH, layer="municipalities")
df  = pd.DataFrame(gdf.drop(columns="geometry"))

# Derived: composite "solar siting score" penalising grid distance
# higher grid_distance = harder to connect, so we normalise and subtract
df["grid_norm"] = (df["grid_distance_km"] - df["grid_distance_km"].min()) / \
                  (df["grid_distance_km"].max() - df["grid_distance_km"].min())
df["solar_siting_score"] = (df["solar_score"] * 0.5 +
                             (1 - df["grid_norm"]) * 0.3 +
                             df["available_land_ha"].clip(0, 20000) / 20000 * 0.2).round(4)

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR MAP
# ─────────────────────────────────────────────────────────────────────────────
CONFLICT_COLORS = {"none": "#2ecc71", "low": "#f1c40f",
                   "medium": "#e67e22", "high": "#e74c3c"}
BRAND_GREEN  = "#1a6b3c"
BRAND_LIGHT  = "#e8f5e9"
BRAND_DARK   = "#0d3320"
ACCENT       = "#f0a500"

# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "GreenGrid – NL Renewable Energy Siting"

# ── Shared filter panel ───────────────────────────────────────────────────────
filter_panel = html.Div([
    html.Div([
        html.Label("Conflict Level", style={"fontWeight": "600", "fontSize": "12px",
                                             "color": "#666", "textTransform": "uppercase",
                                             "letterSpacing": "0.05em"}),
        dcc.Checklist(
            id="filter-conflict",
            options=[{"label": f" {v.capitalize()}", "value": v}
                     for v in ["none", "low", "medium", "high"]],
            value=["none", "low", "medium", "high"],
            inline=True,
            style={"fontSize": "13px", "gap": "12px"}
        ),
    ], style={"marginBottom": "16px"}),

    html.Div([
        html.Div([
            html.Label("Min. Available Land (ha)",
                       style={"fontWeight": "600", "fontSize": "12px",
                              "color": "#666", "textTransform": "uppercase",
                              "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-land", min=0, max=40000, step=500, value=0,
                       marks={0: "0", 10000: "10k", 20000: "20k",
                              30000: "30k", 40000: "40k"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1", "paddingRight": "24px"}),

        html.Div([
            html.Label("Max. Grid Distance (km)",
                       style={"fontWeight": "600", "fontSize": "12px",
                              "color": "#666", "textTransform": "uppercase",
                              "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-grid", min=0, max=25, step=1, value=25,
                       marks={0: "0", 5: "5", 10: "10",
                              15: "15", 20: "20", 25: "25+"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1", "paddingRight": "24px"}),

        html.Div([
            html.Label("Max. Population Density (km²)",
                       style={"fontWeight": "600", "fontSize": "12px",
                              "color": "#666", "textTransform": "uppercase",
                              "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-density", min=0, max=7000, step=100, value=7000,
                       marks={0: "0", 2000: "2k", 4000: "4k", 7000: "7k"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1"}),
    ], style={"display": "flex"}),
], style={
    "background": "white",
    "border": f"1px solid #e0e0e0",
    "borderRadius": "12px",
    "padding": "20px 24px",
    "marginBottom": "24px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.06)"
})

# ── KPI cards ─────────────────────────────────────────────────────────────────
def kpi_card(title, value, subtitle, color=BRAND_GREEN):
    return html.Div([
        html.Div(title, style={"fontSize": "11px", "fontWeight": "700",
                                "color": "#888", "textTransform": "uppercase",
                                "letterSpacing": "0.08em", "marginBottom": "6px"}),
        html.Div(value, style={"fontSize": "28px", "fontWeight": "800",
                                "color": color, "lineHeight": "1"}),
        html.Div(subtitle, style={"fontSize": "12px", "color": "#999",
                                   "marginTop": "4px"}),
    ], style={
        "background": "white",
        "borderRadius": "12px",
        "padding": "18px 20px",
        "border": f"1px solid #e0e0e0",
        "borderTop": f"3px solid {color}",
        "flex": "1",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.06)"
    })

kpi_row = html.Div([
    html.Div(id="kpi-total",    style={"flex": "1"}),
    html.Div(id="kpi-conflict", style={"flex": "1"}),
    html.Div(id="kpi-land",     style={"flex": "1"}),
    html.Div(id="kpi-grid",     style={"flex": "1"}),
], style={"display": "flex", "gap": "16px", "marginBottom": "24px"})

# ── Table columns ─────────────────────────────────────────────────────────────
TABLE_STYLE = {
    "style_table": {"overflowX": "auto", "borderRadius": "8px",
                    "border": "1px solid #e0e0e0"},
    "style_header": {"backgroundColor": BRAND_GREEN, "color": "white",
                     "fontWeight": "700", "fontSize": "12px",
                     "textTransform": "uppercase", "letterSpacing": "0.05em",
                     "padding": "12px 14px", "border": "none"},
    "style_cell":   {"padding": "10px 14px", "fontSize": "13px",
                     "fontFamily": "monospace", "border": "none",
                     "borderBottom": "1px solid #f0f0f0"},
    "style_data_conditional": [
        {"if": {"row_index": "odd"}, "backgroundColor": "#fafafa"},
        {"if": {"column_id": "conflict_level", "filter_query": '{conflict_level} = "none"'},
         "color": "#2ecc71", "fontWeight": "700"},
        {"if": {"column_id": "conflict_level", "filter_query": '{conflict_level} = "low"'},
         "color": "#f1c40f", "fontWeight": "700"},
        {"if": {"column_id": "conflict_level", "filter_query": '{conflict_level} = "medium"'},
         "color": "#e67e22", "fontWeight": "700"},
        {"if": {"column_id": "conflict_level", "filter_query": '{conflict_level} = "high"'},
         "color": "#e74c3c", "fontWeight": "700"},
    ],
    "page_size": 15,
    "sort_action": "native",
    "filter_action": "native",
}

# ── Layout ────────────────────────────────────────────────────────────────────
app.layout = html.Div([

    # Header
    html.Div([
        html.Div([
            html.Div("🌱", style={"fontSize": "32px", "marginRight": "12px"}),
            html.Div([
                html.H1("GreenGrid NL", style={
                    "margin": "0", "fontSize": "24px", "fontWeight": "800",
                    "color": "white", "letterSpacing": "-0.02em"
                }),
                html.Div("Renewable Energy Siting Dashboard · Netherlands",
                         style={"color": "rgba(255,255,255,0.7)",
                                "fontSize": "13px", "marginTop": "2px"}),
            ]),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div([
            html.Span("342 municipalities", style={"color": "rgba(255,255,255,0.9)",
                                                    "fontSize": "13px",
                                                    "fontWeight": "600"}),
            html.Span(" · ", style={"color": "rgba(255,255,255,0.4)"}),
            html.Span("Data: ICIJ, OSM, CBS, Global Solar/Wind Atlas",
                      style={"color": "rgba(255,255,255,0.5)", "fontSize": "12px"}),
        ]),
    ], style={
        "background": f"linear-gradient(135deg, {BRAND_DARK} 0%, {BRAND_GREEN} 100%)",
        "padding": "20px 32px",
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "marginBottom": "24px",
        "borderRadius": "0 0 16px 16px",
        "boxShadow": "0 4px 20px rgba(26,107,60,0.3)"
    }),

    # Main content
    html.Div([

        # Filters
        filter_panel,

        # KPIs
        kpi_row,

        # Tabs
        dcc.Tabs(id="tabs", value="rq1", children=[
            dcc.Tab(label="☀️  RQ1 · Solar Potential",  value="rq1",
                    style={"fontWeight": "600", "fontSize": "13px"},
                    selected_style={"fontWeight": "700", "fontSize": "13px",
                                    "borderTop": f"3px solid {ACCENT}",
                                    "color": BRAND_GREEN}),
            dcc.Tab(label="💨  RQ2 · Wind Suitability", value="rq2",
                    style={"fontWeight": "600", "fontSize": "13px"},
                    selected_style={"fontWeight": "700", "fontSize": "13px",
                                    "borderTop": f"3px solid {BRAND_GREEN}",
                                    "color": BRAND_GREEN}),
            dcc.Tab(label="⚡  RQ3 · Hybrid Zones",     value="rq3",
                    style={"fontWeight": "600", "fontSize": "13px"},
                    selected_style={"fontWeight": "700", "fontSize": "13px",
                                    "borderTop": "3px solid #3498db",
                                    "color": BRAND_GREEN}),
        ], style={"marginBottom": "20px"}),

        html.Div(id="tab-content"),

    ], style={"maxWidth": "1400px", "margin": "0 auto", "padding": "0 24px 40px"}),

], style={"fontFamily": "'Segoe UI', system-ui, sans-serif",
          "background": "#f5f6f8", "minHeight": "100vh"})


# ─────────────────────────────────────────────────────────────────────────────
# HELPER – filter dataframe
# ─────────────────────────────────────────────────────────────────────────────
def apply_filters(conflict_levels, min_land, max_grid, max_density):
    mask = (
        df["conflict_level"].isin(conflict_levels) &
        (df["available_land_ha"] >= min_land) &
        (df["grid_distance_km"]  <= max_grid) &
        (df["pop_density_km2"]   <= max_density)
    )
    return df[mask].copy()


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK – KPIs
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    Output("kpi-total",    "children"),
    Output("kpi-conflict", "children"),
    Output("kpi-land",     "children"),
    Output("kpi-grid",     "children"),
    Input("filter-conflict", "value"),
    Input("filter-land",     "value"),
    Input("filter-grid",     "value"),
    Input("filter-density",  "value"),
)
def update_kpis(conflict, land, grid, density):
    d = apply_filters(conflict, land, grid, density)
    total      = len(d)
    no_conflict= len(d[d["conflict_level"] == "none"])
    avg_land   = d["available_land_ha"].mean()
    avg_grid   = d["grid_distance_km"].mean()

    return (
        kpi_card("Municipalities", str(total), "match current filters", BRAND_GREEN),
        kpi_card("Conflict-free", str(no_conflict),
                 f"{no_conflict/total*100:.0f}% of filtered set" if total else "—", "#2ecc71"),
        kpi_card("Avg. Available Land", f"{avg_land:,.0f} ha",
                 "Bouwland + Grasland", ACCENT),
        kpi_card("Avg. Grid Distance", f"{avg_grid:.1f} km",
                 "to nearest power line", "#3498db"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK – Tab content
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    Output("tab-content", "children"),
    Input("tabs",            "value"),
    Input("filter-conflict", "value"),
    Input("filter-land",     "value"),
    Input("filter-grid",     "value"),
    Input("filter-density",  "value"),
)
def render_tab(tab, conflict, land, grid, density):
    d = apply_filters(conflict, land, grid, density)

    # ── RQ1 – Solar ──────────────────────────────────────────────────────────
    if tab == "rq1":
        d_sorted = d.sort_values("solar_siting_score", ascending=False)

        # Scatter: solar score vs grid distance
        fig_scatter = px.scatter(
            d_sorted, x="grid_distance_km", y="solar_score",
            size="available_land_ha", color="conflict_level",
            color_discrete_map=CONFLICT_COLORS,
            hover_name="gemeente_naam",
            hover_data={
                "solar_score":        ":.3f",
                "grid_distance_km":   ":.2f",
                "available_land_ha":  ":,.0f",
                "pop_density_km2":    ":,.0f",
                "conflict_level":     True,
            },
            labels={
                "grid_distance_km":  "Grid Distance (km)",
                "solar_score":       "Solar Score",
                "available_land_ha": "Available Land (ha)",
                "conflict_level":    "Conflict Level",
            },
            title="Solar Score vs. Grid Distance — bubble size = available land",
            size_max=40,
        )
        fig_scatter.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            legend_title_text="Conflict Level",
            margin=dict(t=50, b=40, l=40, r=20),
        )
        fig_scatter.update_xaxes(showgrid=True, gridcolor="#f0f0f0",
                                  zeroline=False)
        fig_scatter.update_yaxes(showgrid=True, gridcolor="#f0f0f0",
                                  zeroline=False)

        # Bar: top 20 solar siting score
        top20 = d_sorted.head(20)
        fig_bar = px.bar(
            top20, x="gemeente_naam", y="solar_siting_score",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            hover_data={
                "solar_score":       ":.3f",
                "grid_distance_km":  ":.2f",
                "available_land_ha": ":,.0f",
            },
            labels={"gemeente_naam": "", "solar_siting_score": "Solar Siting Score",
                    "conflict_level": "Conflict"},
            title="Top 20 Municipalities — Solar Siting Score (irradiance + land + grid proximity)",
        )
        fig_bar.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            xaxis_tickangle=-35,
            margin=dict(t=50, b=100, l=40, r=20),
            showlegend=False,
        )
        fig_bar.update_yaxes(showgrid=True, gridcolor="#f0f0f0")

        table_cols = ["gemeente_naam", "solar_score", "available_land_ha",
                      "grid_distance_km", "pop_density_km2", "conflict_level",
                      "solar_siting_score"]
        table_data = d_sorted[table_cols].round(3).to_dict("records")

        return html.Div([
            html.Div([
                html.Div([dcc.Graph(figure=fig_bar)],
                         style={"flex": "1.2"}),
                html.Div([dcc.Graph(figure=fig_scatter)],
                         style={"flex": "1"}),
            ], style={"display": "flex", "gap": "20px", "marginBottom": "24px"}),

            html.H3("Full Municipality Table — Solar Siting",
                    style={"fontSize": "14px", "fontWeight": "700",
                           "color": BRAND_DARK, "marginBottom": "12px"}),
            dash_table.DataTable(
                data=table_data,
                columns=[{"name": c.replace("_", " ").title(), "id": c}
                         for c in table_cols],
                **TABLE_STYLE,
                id="table-rq1"
            ),
        ])

    # ── RQ2 – Wind ───────────────────────────────────────────────────────────
    elif tab == "rq2":
        d_sorted = d.sort_values("wind_score", ascending=False)

        # Scatter: wind score vs natura2000 overlap
        fig_wind = px.scatter(
            d_sorted, x="natura2000_overlap_pct", y="wind_score",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            size="available_land_ha", size_max=35,
            hover_name="gemeente_naam",
            hover_data={
                "wind_score":             ":.3f",
                "natura2000_overlap_pct": ":.1f",
                "available_land_ha":      ":,.0f",
                "conflict_level":         True,
            },
            labels={
                "natura2000_overlap_pct": "Natura 2000 Overlap (%)",
                "wind_score":             "Wind Score",
                "conflict_level":         "Conflict Level",
            },
            title="Wind Score vs. Natura 2000 Overlap — ideal = top-left corner",
        )
        # Add quadrant line at 15% (conflict threshold)
        fig_wind.add_vline(x=15, line_dash="dash", line_color="#e74c3c",
                           annotation_text="Conflict threshold (15%)",
                           annotation_position="top right",
                           annotation_font_size=11)
        fig_wind.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        fig_wind.update_xaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)
        fig_wind.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)

        # Stacked bar: conflict level distribution
        conflict_counts = d.groupby(
            ["conflict_level"]).size().reset_index(name="count")
        fig_dist = px.bar(
            conflict_counts, x="conflict_level", y="count",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            labels={"conflict_level": "Conflict Level", "count": "Municipalities"},
            title="Conflict Level Distribution",
        )
        fig_dist.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            showlegend=False,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        fig_dist.update_yaxes(showgrid=True, gridcolor="#f0f0f0")

        table_cols = ["gemeente_naam", "wind_score", "avg_wind_wpd",
                      "natura2000_overlap_pct", "conflict_level",
                      "available_land_ha", "grid_distance_km"]
        table_data = d_sorted[table_cols].round(3).to_dict("records")

        return html.Div([
            html.Div([
                html.Div([dcc.Graph(figure=fig_wind)], style={"flex": "2"}),
                html.Div([dcc.Graph(figure=fig_dist)], style={"flex": "1"}),
            ], style={"display": "flex", "gap": "20px", "marginBottom": "24px"}),

            html.H3("Full Municipality Table — Wind Suitability",
                    style={"fontSize": "14px", "fontWeight": "700",
                           "color": BRAND_DARK, "marginBottom": "12px"}),
            dash_table.DataTable(
                data=table_data,
                columns=[{"name": c.replace("_", " ").title(), "id": c}
                         for c in table_cols],
                **TABLE_STYLE,
                id="table-rq2"
            ),
        ])

    # ── RQ3 – Hybrid ─────────────────────────────────────────────────────────
    elif tab == "rq3":
        d_sorted = d.sort_values("hybrid_score", ascending=False)

        # Radar / parallel coordinates for top 20
        top20 = d_sorted.head(20).copy()

        # Normalize columns for radar
        for col in ["wind_score", "solar_score", "available_land_ha",
                    "pop_density_km2", "grid_distance_km"]:
            mn, mx = df[col].min(), df[col].max()
            if mx > mn:
                top20[f"{col}_n"] = (top20[col] - mn) / (mx - mn)
            else:
                top20[f"{col}_n"] = 0.5
        # Invert grid and density (lower = better)
        top20["grid_score_n"]    = 1 - top20["grid_distance_km_n"]
        top20["density_score_n"] = 1 - top20["pop_density_km2_n"]

        fig_parallel = px.parallel_coordinates(
            top20,
            dimensions=["wind_score", "solar_score", "available_land_ha",
                        "grid_distance_km", "pop_density_km2", "hybrid_score"],
            color="hybrid_score",
            color_continuous_scale=px.colors.sequential.Greens,
            labels={
                "wind_score":        "Wind Score",
                "solar_score":       "Solar Score",
                "available_land_ha": "Avail. Land (ha)",
                "grid_distance_km":  "Grid Dist. (km)",
                "pop_density_km2":   "Pop. Density",
                "hybrid_score":      "Hybrid Score",
            },
            title="Top 20 Municipalities — Multi-dimensional Profile",
        )
        fig_parallel.update_layout(
            paper_bgcolor="white", font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=60, b=40, l=60, r=60),
            coloraxis_colorbar_title="Hybrid",
        )

        # Scatter: wind vs solar, coloured by hybrid
        fig_bubble = px.scatter(
            d_sorted, x="wind_score", y="solar_score",
            color="hybrid_score",
            color_continuous_scale=px.colors.sequential.Greens,
            size="available_land_ha", size_max=40,
            symbol="conflict_level",
            hover_name="gemeente_naam",
            hover_data={
                "hybrid_score":      ":.3f",
                "wind_score":        ":.3f",
                "solar_score":       ":.3f",
                "available_land_ha": ":,.0f",
                "grid_distance_km":  ":.2f",
                "pop_density_km2":   ":,.0f",
                "conflict_level":    True,
            },
            labels={
                "wind_score":        "Wind Score",
                "solar_score":       "Solar Score",
                "hybrid_score":      "Hybrid Score",
                "available_land_ha": "Available Land (ha)",
                "conflict_level":    "Conflict",
            },
            title="Wind vs. Solar Score — bubble=land, shape=conflict level",
        )
        fig_bubble.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        fig_bubble.update_xaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)
        fig_bubble.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)

        table_cols = ["gemeente_naam", "hybrid_score", "wind_score",
                      "solar_score", "available_land_ha", "grid_distance_km",
                      "pop_density_km2", "conflict_level"]
        table_data = d_sorted[table_cols].round(3).to_dict("records")

        return html.Div([
            html.Div([
                html.Div([dcc.Graph(figure=fig_bubble)],   style={"flex": "1"}),
                html.Div([dcc.Graph(figure=fig_parallel)], style={"flex": "1.2"}),
            ], style={"display": "flex", "gap": "20px", "marginBottom": "24px"}),

            html.H3("Full Municipality Table — Hybrid Zones",
                    style={"fontSize": "14px", "fontWeight": "700",
                           "color": BRAND_DARK, "marginBottom": "12px"}),
            dash_table.DataTable(
                data=table_data,
                columns=[{"name": c.replace("_", " ").title(), "id": c}
                         for c in table_cols],
                **TABLE_STYLE,
                id="table-rq3"
            ),
        ])


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
