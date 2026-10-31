"""Clip GridFinder grid.gpkg (Arderne et al. 2020, CC-BY 4.0) to the demo countries.

Writes data/raw/large/gridfinder/grid_ng_ke.parquet used by pipeline/features.py.
"""
import pathlib
import geopandas as gpd
import pandas as pd

D = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "large" / "gridfinder"
BBOXES = {  # lon_min, lat_min, lon_max, lat_max (+1 deg margin)
    "NG": (1.5, 3.2, 15.7, 14.9),
    "KE": (32.9, -5.7, 42.9, 6.0),
    "CD_east": (26.0, -4.0, 31.5, 2.5),
}
parts = []
for k, bb in BBOXES.items():
    g = gpd.read_file(D / "grid.gpkg", bbox=bb)
    print(k, len(g), flush=True)
    parts.append(g[["geometry"]])
out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs).to_crs(4326)
out.to_parquet(D / "grid_ng_ke.parquet")
print("wrote", len(out))
