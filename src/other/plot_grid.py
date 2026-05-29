import os
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GPKG_PATH = os.path.join(BASE_DIR, "data", "processed", "greengrid_full.gpkg")

print("Loading layers ...")
muni       = gpd.read_file(GPKG_PATH, layer="municipalities")
powerlines = gpd.read_file(GPKG_PATH, layer="power_lines")

# Clip power lines to Netherlands land boundary
print("Clipping power lines to land boundary ...")
nl_boundary = muni.dissolve().geometry
powerlines_clipped = gpd.clip(powerlines.to_crs(muni.crs), nl_boundary)

fig, ax = plt.subplots(1, 1, figsize=(10, 10))

# Layer 1: hybrid score choropleth
muni.plot(
    column="hybrid_score",
    ax=ax,
    cmap="YlGn",
    legend=True,
    legend_kwds={"label": "Hybrid Score", "shrink": 0.6},
    alpha=0.85,
    missing_kwds={"color": "lightgrey"}
)

# Layer 2: conflict level outlines
conflict_colors = {
    "low":    "yellow",
    "medium": "orange",
    "high":   "red",
}
for level, color in conflict_colors.items():
    subset = muni[muni["conflict_level"] == level]
    if not subset.empty:
        subset.boundary.plot(ax=ax, color=color, linewidth=1.5)

# Layer 3: clipped power lines
powerlines_clipped.plot(
    ax=ax,
    color="dodgerblue",
    linewidth=0.4,
    alpha=0.7
)

# Fix axis extent strictly to municipalities bounds
xmin, ymin, xmax, ymax = muni.total_bounds
ax.set_xlim(xmin, xmax)
ax.set_ylim(ymin, ymax)

# Legend
legend_elements = [
    Line2D([0], [0], color="yellow",     linewidth=2, label="Conflict: low (15–40%)"),
    Line2D([0], [0], color="orange",     linewidth=2, label="Conflict: medium (40–70%)"),
    Line2D([0], [0], color="red",        linewidth=2, label="Conflict: high (>70%)"),
    Line2D([0], [0], color="dodgerblue", linewidth=1, label="Power lines (OSM)"),
]
ax.legend(handles=legend_elements, loc="lower left", fontsize=9, framealpha=0.9)

ax.set_title(
    "Hybrid Score, Natura 2000 Conflict Levels,\nand Electricity Grid (Netherlands)",
    fontsize=14, fontweight="bold"
)
ax.axis("off")

plt.subplots_adjust(top=0.95, bottom=0.02, left=0.02, right=0.88)
output_path = os.path.join(BASE_DIR, "figs", "greengrid_grid_map.png")
os.makedirs(os.path.join(BASE_DIR, "figs"), exist_ok=True)
plt.savefig(output_path, dpi=150)
print(f"Saved -> {output_path}")
plt.show()