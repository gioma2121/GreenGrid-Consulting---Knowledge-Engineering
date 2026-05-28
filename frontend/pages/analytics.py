"""
Page 2 — Analytics
===================
Migrated from dashboard.py — changes made:
  1. Added dash.register_page(...)
  2. Removed app = Dash(...) and server = app.server
  3. Changed @app.callback → @callback
  4. Wrapped app.layout in def layout(**kwargs)
  5. Removed if __name__ == '__main__': app.run()
"""

import numpy as np
np.bool8 = np.bool_

import dash
from dash import dcc, html, callback, Input, Output, dash_table
import plotly.express as px
import plotly.graph_objects as go
import geopandas as gpd
import pandas as pd
import os

dash.register_page(__name__, path="/analytics", name="📊 Analytics", order=1)

# ─── Data ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
GPKG_PATH = os.getenv("GPKG_PATH", os.path.join(BASE_DIR, "..", "..", "greengrid_full.gpkg"))

gdf = gpd.read_file(GPKG_PATH, layer="municipalities")
df  = pd.DataFrame(gdf.drop(columns="geometry"))

df["grid_norm"] = (df["grid_distance_km"] - df["grid_distance_km"].min()) / \
                  (df["grid_distance_km"].max() - df["grid_distance_km"].min())
df["solar_siting_score"] = (
    df["solar_score"] * 0.5 +
    (1 - df["grid_norm"]) * 0.3 +
    df["available_land_ha"].clip(0, 20000) / 20000 * 0.2
).round(4)

# ─── Colours ──────────────────────────────────────────────────────────────────
CONFLICT_COLORS = {"none": "#2ecc71", "low": "#f1c40f",
                   "medium": "#e67e22", "high": "#e74c3c"}
BRAND_GREEN = "#1a6b3c"
BRAND_DARK  = "#0d3320"
ACCENT      = "#f0a500"

# ─── Table style ──────────────────────────────────────────────────────────────
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

# ─── Filter panel ─────────────────────────────────────────────────────────────
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
            style={"fontSize": "13px", "gap": "12px"},
        ),
    ], style={"marginBottom": "16px"}),

    html.Div([
        html.Div([
            html.Label("Min. Available Land (HA)", style={"fontWeight": "600", "fontSize": "12px",
                                                           "color": "#666", "textTransform": "uppercase",
                                                           "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-land", min=0, max=40000, step=500, value=0,
                       marks={0: "0", 10000: "10k", 20000: "20k", 40000: "40k"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1"}),

        html.Div([
            html.Label("Max. Grid Distance (KM)", style={"fontWeight": "600", "fontSize": "12px",
                                                          "color": "#666", "textTransform": "uppercase",
                                                          "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-grid", min=0, max=25, step=0.5, value=25,
                       marks={0: "0", 5: "5", 10: "10", 25: "25+"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1"}),

        html.Div([
            html.Label("Max. Population Density (KM²)", style={"fontWeight": "600", "fontSize": "12px",
                                                                 "color": "#666", "textTransform": "uppercase",
                                                                 "letterSpacing": "0.05em"}),
            dcc.Slider(id="filter-density", min=0, max=7000, step=100, value=7000,
                       marks={0: "0", 2000: "2k", 4000: "4k", 7000: "7k"},
                       tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"flex": "1"}),
    ], style={"display": "flex", "gap": "32px"}),

], style={
    "background": "white", "border": "1px solid #e0e0e0",
    "borderRadius": "12px", "padding": "20px 24px",
    "marginBottom": "24px", "boxShadow": "0 1px 4px rgba(0,0,0,0.06)",
})

# ─── KPI cards ────────────────────────────────────────────────────────────────
def kpi_card(title, value, subtitle, color=BRAND_GREEN):
    return html.Div([
        html.Div(title, style={"fontSize": "11px", "fontWeight": "700",
                                "color": "#888", "textTransform": "uppercase",
                                "letterSpacing": "0.08em", "marginBottom": "6px"}),
        html.Div(value, style={"fontSize": "28px", "fontWeight": "800",
                                "color": color, "lineHeight": "1"}),
        html.Div(subtitle, style={"fontSize": "12px", "color": "#999", "marginTop": "4px"}),
    ], style={
        "background": "white", "borderRadius": "12px", "padding": "18px 20px",
        "border": "1px solid #e0e0e0", "borderTop": f"3px solid {color}",
        "flex": "1", "boxShadow": "0 1px 4px rgba(0,0,0,0.06)",
    })

kpi_row = html.Div([
    html.Div(id="kpi-total",    style={"flex": "1"}),
    html.Div(id="kpi-conflict", style={"flex": "1"}),
    html.Div(id="kpi-land",     style={"flex": "1"}),
    html.Div(id="kpi-grid",     style={"flex": "1"}),
], style={"display": "flex", "gap": "16px", "marginBottom": "24px"})

# ─── Layout ───────────────────────────────────────────────────────────────────
def layout(**kwargs):
    return html.Div([
        html.Div([
            filter_panel,
            kpi_row,
            dcc.Tabs(id="tabs", value="rq1", children=[
                dcc.Tab(label="☀️  RQ1 · Solar Potential",  value="rq1",
                        style={"fontWeight": "600", "fontSize": "13px"},
                        selected_style={"fontWeight": "700", "fontSize": "13px",
                                        "borderTop": f"3px solid {ACCENT}", "color": BRAND_GREEN}),
                dcc.Tab(label="💨  RQ2 · Wind Suitability", value="rq2",
                        style={"fontWeight": "600", "fontSize": "13px"},
                        selected_style={"fontWeight": "700", "fontSize": "13px",
                                        "borderTop": f"3px solid {BRAND_GREEN}", "color": BRAND_GREEN}),
                dcc.Tab(label="⚡  RQ3 · Hybrid Zones",     value="rq3",
                        style={"fontWeight": "600", "fontSize": "13px"},
                        selected_style={"fontWeight": "700", "fontSize": "13px",
                                        "borderTop": "3px solid #3498db", "color": BRAND_GREEN}),
            ], style={"marginBottom": "20px"}),
            html.Div(id="tab-content"),
        ], style={"maxWidth": "1400px", "margin": "0 auto", "padding": "24px 24px 40px"}),
    ], style={"fontFamily": "'Segoe UI', system-ui, sans-serif",
              "background": "#f5f6f8", "minHeight": "100vh"})

# ─── Helper ───────────────────────────────────────────────────────────────────
def apply_filters(conflict_levels, min_land, max_grid, max_density):
    mask = (
        df["conflict_level"].isin(conflict_levels) &
        (df["available_land_ha"] >= min_land) &
        (df["grid_distance_km"]  <= max_grid) &
        (df["pop_density_km2"]   <= max_density)
    )
    return df[mask].copy()

# ─── Callbacks ────────────────────────────────────────────────────────────────
@callback(
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
    total       = len(d)
    no_conflict = len(d[d["conflict_level"] == "none"])
    avg_land    = d["available_land_ha"].mean()
    avg_grid    = d["grid_distance_km"].mean()
    return (
        kpi_card("Municipalities", str(total), "match current filters", BRAND_GREEN),
        kpi_card("Conflict-free", str(no_conflict),
                 f"{no_conflict/total*100:.0f}% of filtered set" if total else "—", "#2ecc71"),
        kpi_card("Avg. Available Land", f"{avg_land:,.0f} ha", "Bouwland + Grasland", ACCENT),
        kpi_card("Avg. Grid Distance",  f"{avg_grid:.1f} km", "to nearest power line", "#3498db"),
    )


@callback(
    Output("tab-content", "children"),
    Input("tabs",            "value"),
    Input("filter-conflict", "value"),
    Input("filter-land",     "value"),
    Input("filter-grid",     "value"),
    Input("filter-density",  "value"),
)
def render_tab(tab, conflict, land, grid, density):
    d = apply_filters(conflict, land, grid, density)

    # ── RQ1 Solar ────────────────────────────────────────────────────────────
    if tab == "rq1":
        d_sorted = d.sort_values("solar_siting_score", ascending=False)

        fig_scatter = px.scatter(
            d_sorted, x="grid_distance_km", y="solar_score",
            size="available_land_ha", color="conflict_level",
            color_discrete_map=CONFLICT_COLORS,
            hover_name="gemeente_naam",
            hover_data={"solar_score": ":.3f", "grid_distance_km": ":.2f",
                        "available_land_ha": ":,.0f", "pop_density_km2": ":,.0f",
                        "conflict_level": True},
            labels={"grid_distance_km": "Grid Distance (km)", "solar_score": "Solar Score",
                    "available_land_ha": "Available Land (ha)", "conflict_level": "Conflict Level"},
            title="Solar Score vs. Grid Distance — bubble size = available land",
            size_max=40,
        )
        fig_scatter.update_layout(plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI", title_font_size=14, title_font_color=BRAND_DARK,
            legend_title_text="Conflict Level", margin=dict(t=50, b=40, l=40, r=20))
        fig_scatter.update_xaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)
        fig_scatter.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)

        top20 = d_sorted.head(20)
        fig_bar = px.bar(
            top20, x="gemeente_naam", y="solar_siting_score",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            hover_data={"solar_score": ":.3f", "grid_distance_km": ":.2f",
                        "available_land_ha": ":,.0f"},
            labels={"gemeente_naam": "", "solar_siting_score": "Solar Siting Score",
                    "conflict_level": "Conflict"},
            title="Top 20 Municipalities — Solar Siting Score (irradiance + land + grid proximity)",
        )
        fig_bar.update_layout(plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI", title_font_size=14, title_font_color=BRAND_DARK,
            xaxis_tickangle=-35, margin=dict(t=50, b=100, l=40, r=20), showlegend=False)
        fig_bar.update_yaxes(showgrid=True, gridcolor="#f0f0f0")

        table_cols = ["gemeente_naam", "solar_score", "available_land_ha",
                      "grid_distance_km", "pop_density_km2", "conflict_level", "solar_siting_score"]
        table_data = d_sorted[table_cols].round(3).to_dict("records")

        return html.Div([
            html.Div([
                html.Div([dcc.Graph(figure=fig_bar)],     style={"flex": "1.2"}),
                html.Div([dcc.Graph(figure=fig_scatter)], style={"flex": "1"}),
            ], style={"display": "flex", "gap": "20px", "marginBottom": "24px"}),
            html.H3("Full Municipality Table — Solar Siting",
                    style={"fontSize": "14px", "fontWeight": "700",
                           "color": BRAND_DARK, "marginBottom": "12px"}),
            dash_table.DataTable(
                data=table_data,
                columns=[{"name": c.replace("_", " ").title(), "id": c} for c in table_cols],
                **TABLE_STYLE, id="table-rq1"),
        ])

    # ── RQ2 Wind ─────────────────────────────────────────────────────────────
    elif tab == "rq2":
        d_sorted = d.sort_values("wind_score", ascending=False)

        fig_wind = px.scatter(
            d_sorted, x="natura2000_overlap_pct", y="wind_score",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            size="available_land_ha", size_max=35,
            hover_name="gemeente_naam",
            hover_data={"wind_score": ":.3f", "natura2000_overlap_pct": ":.1f",
                        "available_land_ha": ":,.0f", "conflict_level": True},
            labels={"natura2000_overlap_pct": "Natura 2000 Overlap (%)",
                    "wind_score": "Wind Score", "conflict_level": "Conflict Level"},
            title="Wind Score vs. Natura 2000 Overlap — ideal = top-left corner",
        )
        fig_wind.add_vline(x=15, line_dash="dash", line_color="#e74c3c",
                           annotation_text="Conflict threshold (15%)",
                           annotation_position="top right", annotation_font_size=11)
        fig_wind.update_layout(plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI", title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=50, b=40, l=40, r=20))
        fig_wind.update_xaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)
        fig_wind.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)

        conflict_counts = d.groupby("conflict_level").size().reset_index(name="count")
        fig_dist = px.bar(
            conflict_counts, x="conflict_level", y="count",
            color="conflict_level", color_discrete_map=CONFLICT_COLORS,
            labels={"conflict_level": "Conflict Level", "count": "Municipalities"},
            title="Conflict Level Distribution",
        )
        fig_dist.update_layout(plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI", title_font_size=14, title_font_color=BRAND_DARK,
            showlegend=False, margin=dict(t=50, b=40, l=40, r=20))
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
                columns=[{"name": c.replace("_", " ").title(), "id": c} for c in table_cols],
                **TABLE_STYLE, id="table-rq2"),
        ])

    # ── RQ3 Hybrid ───────────────────────────────────────────────────────────
    elif tab == "rq3":
        d_sorted = d.sort_values("hybrid_score", ascending=False)
        top20 = d_sorted.head(20).copy()

        fig_parallel = px.parallel_coordinates(
            top20,
            dimensions=["wind_score", "solar_score", "available_land_ha",
                        "grid_distance_km", "pop_density_km2", "hybrid_score"],
            color="hybrid_score",
            color_continuous_scale=px.colors.sequential.Greens,
            labels={"wind_score": "Wind Score", "solar_score": "Solar Score",
                    "available_land_ha": "Avail. Land (ha)",
                    "grid_distance_km": "Grid Dist. (km)",
                    "pop_density_km2": "Pop. Density", "hybrid_score": "Hybrid Score"},
            title="Top 20 Municipalities — Multi-dimensional Profile",
        )
        fig_parallel.update_layout(paper_bgcolor="white", font_family="Segoe UI",
            title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=60, b=40, l=60, r=60), coloraxis_colorbar_title="Hybrid")

        fig_bubble = px.scatter(
            d_sorted, x="wind_score", y="solar_score",
            color="hybrid_score", color_continuous_scale=px.colors.sequential.Greens,
            size="available_land_ha", size_max=40,
            symbol="conflict_level",
            hover_name="gemeente_naam",
            hover_data={"hybrid_score": ":.3f", "wind_score": ":.3f",
                        "solar_score": ":.3f", "available_land_ha": ":,.0f",
                        "grid_distance_km": ":.2f", "pop_density_km2": ":,.0f",
                        "conflict_level": True},
            labels={"wind_score": "Wind Score", "solar_score": "Solar Score",
                    "hybrid_score": "Hybrid Score",
                    "available_land_ha": "Available Land (ha)", "conflict_level": "Conflict"},
            title="Wind vs. Solar Score — bubble=land, shape=conflict level",
        )
        fig_bubble.update_layout(plot_bgcolor="white", paper_bgcolor="white",
            font_family="Segoe UI", title_font_size=14, title_font_color=BRAND_DARK,
            margin=dict(t=50, b=40, l=40, r=20))
        fig_bubble.update_xaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)
        fig_bubble.update_yaxes(showgrid=True, gridcolor="#f0f0f0", zeroline=False)

        table_cols = ["gemeente_naam", "hybrid_score", "wind_score", "solar_score",
                      "available_land_ha", "grid_distance_km", "pop_density_km2", "conflict_level"]
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
                columns=[{"name": c.replace("_", " ").title(), "id": c} for c in table_cols],
                **TABLE_STYLE, id="table-rq3"),
        ])