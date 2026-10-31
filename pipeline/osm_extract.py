"""Pre-extract the OpenStreetMap layers the model uses, so live forecasts need no Overpass call.

python pipeline/osm_extract.py nigeria.osm.pbf kenya.osm.pbf congo-democratic-republic.osm.pbf
(Geofabrik extracts; needs pyosmium). Writes data/geo/osm_pois.parquet (classified POIs, same
rules as features.classify_poi; type and location only, no names) and data/geo/osm_roads.parquet (trunk-tertiary roads as points
every <=250 m, so distance to a road is exact to about 125 m).
"""
import json, math, pathlib, re, sys
import numpy as np, osmium, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "geo"
ROADS = {"trunk", "primary", "secondary", "tertiary"}
STEP_M = 250.0


def classify_poi(t):  # kept identical to features.classify_poi
    a, s, mm = t.get("amenity"), t.get("shop"), t.get("man_made")
    if a in ("school", "college", "kindergarten"): return "school"
    if a in ("clinic", "hospital", "doctors", "pharmacy") or "healthcare" in t: return "health"
    if a == "marketplace": return "market"
    if a == "place_of_worship": return "worship"
    if a == "fuel": return "fuel"
    if a == "bank": return "bank"
    if mm in ("water_well", "water_tower") or a == "water_point": return "water_pump"
    if mm in ("mast", "tower") and t.get("tower:type") == "communication": return "telecom"
    if "craft" in t or mm == "works" or re.search(r"mill", t.get("name", ""), re.I): return "mill"
    if s: return "shop"
    if a in ("restaurant", "cafe", "bar", "fast_food", "pub", "atm", "bureau_de_change", "car_wash",
             "nightclub", "internet_cafe") or "office" in t or t.get("tourism") in ("guest_house", "hotel", "hostel"):
        return "other_commercial"
    return None


def resample(pts):
    """Points every STEP_M metres along the line (plus both ends)."""
    out, carry = [pts[0]], 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot((x1 - x0) * 111320 * math.cos(math.radians(y0)), (y1 - y0) * 111320)
        pos = STEP_M - carry
        while pos <= d:
            f = pos / d
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)); pos += STEP_M
        carry = (carry + d) % STEP_M if d else carry
    out.append(pts[-1])
    return out


def extract(pbf):
    pois, roads = [], []
    fp = (osmium.FileProcessor(pbf).with_locations()
          .with_filter(osmium.filter.KeyFilter("amenity", "healthcare", "shop", "craft", "office", "tourism", "man_made", "name", "highway")))
    for o in fp:
        if o.is_relation():
            continue
        t = dict(o.tags)
        if o.is_way() and t.get("highway") in ROADS:
            try:
                pts = [(n.lon, n.lat) for n in o.nodes if n.location.valid()]
            except osmium.InvalidLocationError:
                continue
            if len(pts) >= 2:
                roads += resample(pts)
            continue
        c = classify_poi(t)
        if not c:
            continue
        if o.is_node():
            lon, lat = o.location.lon, o.location.lat
        else:
            xs = [n.lon for n in o.nodes if n.location.valid()]; ys = [n.lat for n in o.nodes if n.location.valid()]
            if not xs: continue
            lon, lat = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2  # bbox centre, as Overpass "out center"
        pois.append((lat, lon, c))  # no names: keep the bundled data free of anything personal
    return pois, roads


if __name__ == "__main__":
    P, Rd = [], []
    for f in sys.argv[1:]:
        p, r = extract(f); P += p; Rd += r
        print(f, len(p), "pois", len(r), "road points", flush=True)
    pois = pd.DataFrame(P, columns=["lat", "lon", "poi_type"]).sort_values(["lat", "lon"])
    pois["poi_type"] = pois.poi_type.astype("category")
    pois.to_parquet(GEO / "osm_pois.parquet", index=False, compression="zstd")
    rd = pd.DataFrame(np.round(np.array(Rd, float), 5)[:, ::-1], columns=["lat", "lon"]).drop_duplicates().sort_values("lat")
    rd.astype("float32").to_parquet(GEO / "osm_roads.parquet", index=False, compression="zstd")
    print("written", len(pois), "pois", len(rd), "road points")
