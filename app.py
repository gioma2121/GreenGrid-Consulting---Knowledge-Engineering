"""
GreenGrid NL — main app entry point
====================================
Run with:  python app.py
Then open: http://127.0.0.1:8050
"""

import os, sys
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src", "dashboard"))
os.environ.setdefault("GPKG_PATH", os.path.join(_HERE, "data", "processed", "greengrid_full.gpkg"))

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder=os.path.join(_HERE, "src", "dashboard", "pages"),
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # for gunicorn / Render deployment

# ── Navbar ────────────────────────────────────────────────────────────────────
def _nav_link(label, href):
    return dcc.Link(label, href=href, style={
        "color": "rgba(255,255,255,0.85)", "textDecoration": "none",
        "marginLeft": "1.75rem", "fontWeight": "500", "fontSize": "0.9rem",
    })

navbar = html.Div([
    html.Div([
        html.Span("🌿", style={"fontSize": "1.3rem", "marginRight": "0.4rem"}),
        html.Span("GreenGrid NL", style={
            "fontSize": "1.15rem", "fontWeight": "700", "color": "white"
        }),
        html.Span(" · Renewable Energy Siting", style={
            "fontSize": "0.8rem", "color": "rgba(255,255,255,0.55)", "marginLeft": "0.6rem"
        }),
    ], style={"display": "flex", "alignItems": "center"}),
    html.Div([
        _nav_link("🗺️  Map",              "/"),
        _nav_link("📊  Analytics",        "/analytics"),
        _nav_link("🕸️  Knowledge Graph",  "/kg"),
    ]),
], style={
    "backgroundColor": "#1a3c2e",
    "padding": "0.7rem 1.5rem",
    "display": "flex",
    "alignItems": "center",
    "justifyContent": "space-between",
    "boxShadow": "0 2px 6px rgba(0,0,0,0.25)",
})

# ── Shared filter state (persists across page navigation) ─────────────────────
filters_store = dcc.Store(
    id="filters-store",
    storage_type="session",
    data={
        "conflict_levels": ["none", "low", "medium", "high"],
        "min_land_ha":     0,
        "max_grid_km":     25,
        "max_pop_density": 7000,
    },
)

# ── Root layout ───────────────────────────────────────────────────────────────
app.layout = html.Div([
    navbar,
    filters_store,
    dash.page_container,
], style={
    "fontFamily": "'Segoe UI', system-ui, sans-serif",
    "backgroundColor": "#f4f6f5",
    "minHeight": "100vh",
})

if __name__ == "__main__":
    app.run(debug=True, port=8050)