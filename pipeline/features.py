"""Lodestar site feature pipeline.

compute_features(lat, lon, radius_m=1500, site_id=None, name=None) -> dict
CLI: python pipeline/features.py LAT LON [--radius 1500] [--id ID] [--name NAME] [--write]

Rule: never fabricate. Any source that fails yields null for its fields + a warning.
"""
import argparse, datetime as dt, hashlib, json, math, pathlib, re, sys, time
import numpy as np, pandas as pd, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import shapely
from shapely.geometry import Point, LineString, box
from pyproj import CRS, Transformer

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OVP_CACHE = CACHE / "overpass"
GRID_DIR = ROOT / "data" / "raw" / "large" / "gridfinder"
SITES = ROOT / "data" / "sites"
GEO = ROOT / "data" / "geo"  # small committed copies of the VIDA row-group index and clipped GridFinder lines
UA = {"User-Agent": "Lodestar-hackathon/0.1 (geospatial feature pipeline)"}
OVERPASS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
LIVE_OVERPASS = {"retries": 1, "timeout": 60, "race": True}  # live app: one 60 s race across mirrors, then degrade
MAX_GEO_BUILDINGS = 6000
ISO3_TO_2 = {"NGA": "NG", "KEN": "KE", "COD": "CD"}

POI_KEYS = ["school", "health", "market", "worship", "shop", "mill", "telecom", "fuel",
            "bank", "water_pump", "other_commercial"]


# ------------------------------------------------------------------ helpers
def utm_crs(lat, lon):
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _deg_window(lat, r_m, pad=1.02):
    dlat = r_m / 111320.0 * pad
    dlon = dlat / max(math.cos(math.radians(lat)), 0.2)
    return dlat, dlon


def _null_pois():
    return {k: None for k in POI_KEYS}


# ------------------------------------------------------------------ buildings (VIDA)
_duck = None


def _con():
    global _duck
    if _duck is None:
        import duckdb
        _duck = duckdb.connect()
        _duck.execute("install httpfs; load httpfs; install spatial; load spatial")
    return _duck


_idx_cache = {}


def _vida_index():
    if not _idx_cache:
        for p in sorted(CACHE.glob("vida_index_*.parquet")) or sorted(GEO.glob("vida_index_*.parquet")):
            _idx_cache[p.stem.split("_")[-1]] = pd.read_parquet(p)
    return _idx_cache


def get_buildings(lat, lon, r_m):
    """Return (GeoDataFrame in EPSG:4326 with area_m2, iso3, source) or raise."""
    import geopandas as gpd
    dlat, dlon = _deg_window(lat, r_m)
    x0, x1, y0, y1 = lon - dlon, lon + dlon, lat - dlat, lat + dlat
    iso = None
    urls = []
    for k, df in _vida_index().items():
        m = df[(df.xmin <= x1) & (df.xmax >= x0) & (df.ymin <= y1) & (df.ymax >= y0)]
        if len(m):
            urls += list(m.url.unique())
            iso = iso or k
    if not urls:
        raise RuntimeError("no VIDA row groups cover this location (country index missing or no buildings)")
    q = f"""select bf_source, ST_AsWKB(geometry) as wkb from read_parquet({urls!r})
            where bbox.xmin<={x1} and bbox.xmax>={x0} and bbox.ymin<={y1} and bbox.ymax>={y0}"""
    last = None
    for attempt in range(3):
        try:
            rows = _con().execute(q).fetchall()
            break
        except Exception as e:  # network flake
            last = e
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"VIDA query failed: {last}")
    geoms = shapely.from_wkb([bytes(r[1]) for r in rows]) if rows else np.array([], dtype=object)
    gdf = gpd.GeoDataFrame({"bf_source": [r[0] for r in rows]}, geometry=geoms, crs=4326)
    return gdf, iso


def building_stats(lat, lon, r_m, gdf):
    """Filter to radius (centroid within), compute UTM areas. Returns gdf with area_m2, cls."""
    crs = utm_crs(lat, lon)
    if len(gdf) == 0:
        gdf = gdf.copy(); gdf["area_m2"] = []; gdf["cls"] = []
        return gdf
    g = gdf.to_crs(crs)
    cen = g.geometry.centroid
    ctr = Point(*Transformer.from_crs(4326, crs, always_xy=True).transform(lon, lat))
    keep = cen.distance(ctr) <= r_m
    out = gdf[keep.values].copy()
    out["area_m2"] = g.geometry.area[keep.values].values
    out["cls"] = np.where(out.area_m2 < 30, "small", np.where(out.area_m2 <= 120, "residential", "large"))
    return out


# ------------------------------------------------------------------ Overpass
def overpass(query, retries=4, timeout=150, race=False):
    """Cached Overpass call. race=True asks every mirror at once and keeps the first answer
    (used for live requests, where one slow mirror would otherwise hold up the forecast)."""
    OVP_CACHE.mkdir(parents=True, exist_ok=True)
    f = OVP_CACHE / (hashlib.sha1(query.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text())

    def ask(url):
        r = requests.post(url, data={"data": query}, headers=UA, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"{url} HTTP {r.status_code}")
        return r.json()

    last = None
    for i in range(retries):
        if race:
            ex = ThreadPoolExecutor(len(OVERPASS))
            futs = [ex.submit(ask, u) for u in OVERPASS]
            try:
                for fu in as_completed(futs):
                    try:
                        j = fu.result()
                    except Exception as e:
                        last = str(e) if isinstance(e, RuntimeError) else type(e).__name__
                        continue
                    f.write_text(json.dumps(j))
                    return j
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
        else:
            for url in OVERPASS:
                try:
                    j = ask(url)
                    f.write_text(json.dumps(j))
                    return j
                except Exception as e:
                    last = str(e) if isinstance(e, RuntimeError) else f"{url} {type(e).__name__}"
        if i < retries - 1:
            time.sleep(3 * 2 ** i)
    raise RuntimeError(f"Overpass failed: {last}")


def classify_poi(t):
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


def poi_query(lat, lon, r):
    a = f"(around:{int(r)},{lat},{lon})"
    return f"""[out:json][timeout:90];(
nwr{a}[amenity~"^(school|college|kindergarten|clinic|hospital|doctors|pharmacy|marketplace|place_of_worship|fuel|bank|water_point|restaurant|cafe|bar|fast_food|pub|atm|bureau_de_change|car_wash|nightclub|internet_cafe)$"];
nwr{a}[healthcare];
nwr{a}[shop];
nwr{a}[craft];
nwr{a}[office];
nwr{a}[tourism~"^(guest_house|hotel|hostel)$"];
nwr{a}[man_made~"^(works|mast|tower|water_well|water_tower)$"];
nwr{a}[name~"mill",i];
);out center tags;"""


def _pois_from(elements):
    seen, pts = set(), []
    for e in elements:
        key = (e["type"], e["id"])
        if key in seen: continue
        seen.add(key)
        t = e.get("tags", {})
        c = classify_poi(t)
        if not c: continue
        la = e.get("lat") or (e.get("center") or {}).get("lat")
        lo = e.get("lon") or (e.get("center") or {}).get("lon")
        if la is None: continue
        pts.append({"poi_type": c, "name": t.get("name"), "lat": la, "lon": lo})
    return pts


def get_pois(lat, lon, r_m, **ovp):
    return _pois_from(overpass(poi_query(lat, lon, r_m), **ovp).get("elements", []))


ROAD_QUERY = '[highway~"^(trunk|primary|secondary|tertiary)$"]'


def _nearest_line_km(lat, lon, elements):
    crs = utm_crs(lat, lon)
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    p = Point(*tr.transform(lon, lat))
    best = None
    for e in elements:
        gm = e.get("geometry") or []
        if len(gm) < 2: continue
        xs, ys = tr.transform([g["lon"] for g in gm], [g["lat"] for g in gm])
        d = LineString(list(zip(xs, ys))).distance(p)
        best = d if best is None else min(best, d)
    return None if best is None else best / 1000.0


def road_dist_km(lat, lon, search_m=15000, **ovp):
    q = f'[out:json][timeout:90];way(around:{search_m},{lat},{lon}){ROAD_QUERY};out geom;'
    return _nearest_line_km(lat, lon, overpass(q, **ovp).get("elements", []))


# Pre-extracted OpenStreetMap layers for the countries the app covers (pipeline/osm_extract.py,
# Geofabrik extracts of 2026-10-31). Live forecasts read these instead of calling Overpass.
OSM_POIS, OSM_ROADS = GEO / "osm_pois.parquet", GEO / "osm_roads.parquet"
OSM_AS_OF = "2026-10-31"
_osm = {}


def _osm_layers():
    if not _osm:
        p = pd.read_parquet(OSM_POIS)
        r = pd.read_parquet(OSM_ROADS)
        _osm.update(plat=p.lat.to_numpy(), plon=p.lon.to_numpy(), ptype=p.poi_type.astype(str).to_numpy(),
                    rlat=r.lat.to_numpy(np.float64), rlon=r.lon.to_numpy(np.float64))
    return _osm


def _metres(lat, lon, la, lo):
    return np.hypot((lo - lon) * 111320 * math.cos(math.radians(lat)), (la - lat) * 111320)


def local_osm(lat, lon, r_m, road_m=15000):
    """POIs within r_m and distance to the nearest trunk-tertiary road (within road_m), from the
    pre-extracted layers. Same classification as the Overpass path."""
    L = _osm_layers()
    dlat, dlon = _deg_window(lat, r_m)
    i0, i1 = np.searchsorted(L["plat"], [lat - dlat, lat + dlat])
    la, lo = L["plat"][i0:i1], L["plon"][i0:i1]
    m = (np.abs(lo - lon) <= dlon) & (_metres(lat, lon, la, lo) <= r_m)
    pts = [{"poi_type": t, "name": None, "lat": float(a), "lon": float(b)}
           for t, a, b in zip(L["ptype"][i0:i1][m], la[m], lo[m])]
    dlat, dlon = _deg_window(lat, road_m)
    j0, j1 = np.searchsorted(L["rlat"], [lat - dlat, lat + dlat])
    ra, ro = L["rlat"][j0:j1], L["rlon"][j0:j1]
    k = np.abs(ro - lon) <= dlon
    d = _metres(lat, lon, ra[k], ro[k]) if k.any() else np.array([])
    road = float(d.min()) / 1000 if d.size and d.min() <= road_m else None
    return pts, road


def admin1_nominatim(lat, lon):
    r = requests.get("https://nominatim.openstreetmap.org/reverse", params={"lat": f"{lat:.4f}", "lon": f"{lon:.4f}",
                     "zoom": 5, "format": "jsonv2", "accept-language": "en"}, headers=UA, timeout=8)
    r.raise_for_status()
    return (r.json().get("address") or {}).get("state")


# The model only uses road distance as "more than 5 km from a major road" (village.drivers_for),
# so live requests search 6 km instead of 15 km, which is far cheaper for Overpass.
LIVE_ROAD_M = 6000


def live_osm(lat, lon, r_m):
    """POIs, nearest major road (within LIVE_ROAD_M) and admin-1 name in ONE Overpass request,
    raced across mirrors. Returns (pois, road_km or None, admin1 or None)."""
    pq = poi_query(lat, lon, r_m).split(";(", 1)[1].rsplit(";out center tags;", 1)[0]
    q = (f"[out:json][timeout:55];({pq};out center tags;"
         f"way(around:{LIVE_ROAD_M},{lat},{lon}){ROAD_QUERY};out geom;"
         f"is_in({lat},{lon})->.a;area.a[boundary=administrative][admin_level=4];out tags;")
    els = overpass(q, **LIVE_OVERPASS).get("elements", [])
    areas = [e for e in els if e["type"] == "area"]
    roads = [e for e in els if e["type"] == "way" and "geometry" in e]
    rest = [e for e in els if e["type"] != "area" and "geometry" not in e]
    adm = next((a.get("tags", {}).get("name:en") or a.get("tags", {}).get("name") for a in areas
                if a.get("tags", {}).get("name:en") or a.get("tags", {}).get("name")), None)
    return _pois_from(rest), _nearest_line_km(lat, lon, roads), adm


def admin1_of(lat, lon, **ovp):
    q = f'[out:json][timeout:60];is_in({lat},{lon})->.a;area.a[boundary=administrative][admin_level=4];out tags;'
    for e in overpass(q, **ovp).get("elements", []):
        n = e.get("tags", {}).get("name:en") or e.get("tags", {}).get("name")
        if n: return n
    return None


# ------------------------------------------------------------------ grid
GRID_PARQUET = GRID_DIR / "grid_ng_ke.parquet"
if not GRID_PARQUET.exists():  # deployed copy (committed): data/geo/
    GRID_PARQUET = GEO / "grid_ng_ke.parquet"
_grid = None


def _load_grid():
    global _grid
    if _grid is None:
        import geopandas as gpd
        _grid = gpd.read_parquet(GRID_PARQUET)
        _grid.sindex  # build
    return _grid


def grid_dist_km(lat, lon):
    g = _load_grid()
    crs = utm_crs(lat, lon)
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    p = Point(*tr.transform(lon, lat))
    for w in (0.1, 0.3, 1.0, 3.0, 8.0):
        idx = g.sindex.query(box(lon - w, lat - w, lon + w, lat + w))
        if len(idx) == 0: continue
        sub = g.geometry.iloc[idx]
        d = sub.to_crs(crs).distance(p).min() / 1000.0
        if d <= w * 100 * math.cos(math.radians(lat)):  # guaranteed nearest within window
            return float(d)
    return None


def target_frac(lat, lon, r_m):
    import rasterio
    from rasterio.windows import from_bounds
    dlat, dlon = _deg_window(lat, r_m, 1.2)
    with rasterio.open(GRID_DIR / "targets.tif") as ds:
        win = from_bounds(lon - dlon, lat - dlat, lon + dlon, lat + dlat, ds.transform).round_offsets().round_lengths()
        a = ds.read(1, window=win)
        tf = ds.window_transform(win)
    rows, cols = np.indices(a.shape)
    xs, ys = rasterio.transform.xy(tf, rows.ravel(), cols.ravel())
    xs, ys = np.array(xs), np.array(ys)
    dx = (xs - lon) * 111320 * math.cos(math.radians(lat))
    dy = (ys - lat) * 111320
    m = (dx ** 2 + dy ** 2) <= r_m ** 2
    if m.sum() == 0: return None
    return float((a.ravel()[m] == 1).mean())


# ------------------------------------------------------------------ solar
def get_solar(lat, lon):
    OVP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    f = CACHE / "power" / f"{lat:.2f}_{lon:.2f}.json"
    f.parent.mkdir(exist_ok=True)
    if f.exists():
        j = json.loads(f.read_text())
    else:
        url = ("https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=ALLSKY_SFC_SW_DWN"
               f"&community=RE&longitude={lon:.4f}&latitude={lat:.4f}&format=JSON")
        last = None
        for i in range(3):
            try:
                r = requests.get(url, headers=UA, timeout=60); r.raise_for_status()
                j = r.json(); f.write_text(json.dumps(j)); break
            except Exception as e:
                last = e; time.sleep(2 * (i + 1))
        else:
            raise RuntimeError(f"NASA POWER failed: {last}")
    p = j["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    vals = [p[m] for m in months]
    if any(v is None or v < 0 for v in vals):
        raise RuntimeError("NASA POWER returned fill values")
    return {"ghi_annual": round(p["ANN"], 3), "ghi_monthly": [round(v, 3) for v in vals], "units": "kWh/m2/day"}


# ------------------------------------------------------------------ main
def _num(x, nd=3):
    return None if x is None else round(float(x), nd)


def compute_site(lat, lon, radius_m=1500, site_id=None, name=None, country=None, admin1=None, timings=None,
                 live=False, progress=None):
    """Returns (features dict, buildings GeoDataFrame|None, pois list|None).

    live=True fetches all sources at once and races the Overpass mirrors with a time budget (for
    the web app); a source that fails or runs out of time yields nulls and a warning, never a guess.
    `progress` (dict) is updated as each source finishes, for the app's progress display."""
    T = timings if timings is not None else {}
    P = progress if progress is not None else {}
    ovp = LIVE_OVERPASS if live else {}
    W = []
    out = {"site_id": site_id, "name": name, "country": country, "admin1": admin1,
           "lat": lat, "lon": lon, "radius_m": radius_m}
    area_km2 = math.pi * (radius_m / 1000) ** 2
    res = {"bg": None, "pois": None}

    def buildings():
        src = "VIDA Google-Microsoft-OSM Open Buildings (source.coop), areas computed in local UTM"
        try:
            raw, iso = get_buildings(lat, lon, radius_m)
            bg = building_stats(lat, lon, radius_m, raw)
            if country is None and iso: out["country"] = ISO3_TO_2.get(iso, iso)
            a = bg.area_m2.values
            out["buildings"] = {"count": int(len(bg)), "total_area_m2": _num(a.sum(), 1) if len(a) else 0.0,
                                "median_area_m2": _num(np.median(a), 1) if len(a) else None,
                                "n_small": int((bg.cls == "small").sum()), "n_residential": int((bg.cls == "residential").sum()),
                                "n_large": int((bg.cls == "large").sum()),
                                "density_per_km2": _num(len(bg) / area_km2, 1), "source": src}
            res["bg"] = bg
            if len(bg) == 0: W.append("no buildings found within radius")
        except Exception as e:
            out["buildings"] = {k: None for k in ["count", "total_area_m2", "median_area_m2", "n_small", "n_residential",
                                                   "n_large", "density_per_km2"]} | {"source": src}
            W.append(f"buildings unavailable: {e}")
            return False

    def pois():
        try:
            pts = get_pois(lat, lon, radius_m, **ovp)
            cnt = {k: 0 for k in POI_KEYS}
            for q in pts: cnt[q["poi_type"]] += 1
            out["pois"] = cnt; res["pois"] = pts
        except Exception as e:
            out["pois"] = _null_pois(); W.append(f"POIs unavailable (Overpass): {e}")
            return False

    def grid():
        g = {"dist_km": None, "electrified_target_frac": None}
        try:
            g["dist_km"] = _num(grid_dist_km(lat, lon))
            if g["dist_km"] is None: W.append("grid distance unavailable: no GridFinder lines near point (outside clipped regions?)")
        except Exception as e:
            W.append(f"grid distance unavailable: {e}")
        try:
            g["electrified_target_frac"] = _num(target_frac(lat, lon, radius_m), 4)
        except Exception as e:
            W.append(f"electrified_target_frac unavailable: {e}")
        out["grid"] = g

    def road():
        try:
            d = road_dist_km(lat, lon, **ovp)
            out["road"] = {"dist_major_km": _num(d)}
            if d is None: W.append("no trunk/primary/secondary/tertiary road within 15 km in OSM (dist_major_km null)")
        except Exception as e:
            out["road"] = {"dist_major_km": None}; W.append(f"road distance unavailable (Overpass): {e}")
            return False

    def solar():
        try:
            out["solar"] = get_solar(lat, lon)
        except Exception as e:
            out["solar"] = {"ghi_annual": None, "ghi_monthly": None, "units": "kWh/m2/day"}
            W.append(f"solar unavailable: {e}")
            return False

    def admin():
        if out["admin1"] is None:
            try: out["admin1"] = admin1_of(lat, lon, **ovp)
            except Exception: pass
            if out["admin1"] is None: W.append("admin1 unknown")

    def osm():
        if OSM_POIS.exists() and OSM_ROADS.exists():
            pts, d = local_osm(lat, lon, radius_m)
            cnt = {k: 0 for k in POI_KEYS}
            for q in pts: cnt[q["poi_type"]] += 1
            out["pois"] = cnt; res["pois"] = pts
            out["road"] = {"dist_major_km": _num(d), "osm_as_of": OSM_AS_OF}
            if d is None: W.append("no trunk/primary/secondary/tertiary road within 15 km in OSM (dist_major_km null)")
            if out["admin1"] is None:
                try: out["admin1"] = admin1_nominatim(lat, lon)
                except Exception: pass
                if out["admin1"] is None: W.append("admin1 unknown")
            return
        try:
            pts, d, adm = live_osm(lat, lon, radius_m)
        except Exception as e:
            out["pois"] = _null_pois(); out["road"] = {"dist_major_km": None, "searched_km": LIVE_ROAD_M / 1000}
            W.append(f"OpenStreetMap unavailable (Overpass): {e}; POIs and road distance missing")
            if out["admin1"] is None: W.append("admin1 unknown")
            return False
        cnt = {k: 0 for k in POI_KEYS}
        for q in pts: cnt[q["poi_type"]] += 1
        out["pois"] = cnt; res["pois"] = pts
        out["road"] = {"dist_major_km": _num(d), "searched_km": LIVE_ROAD_M / 1000}
        if d is None: W.append(f"no trunk/primary/secondary/tertiary road within {LIVE_ROAD_M / 1000:.0f} km in OSM (dist_major_km null)")
        if out["admin1"] is None: out["admin1"] = adm
        if out["admin1"] is None: W.append("admin1 unknown")

    def run(key, fn):
        t = time.time(); P[key] = "running"
        ok = fn()
        T[key] = time.time() - t; P[key] = "failed" if ok is False else "done"

    if live:
        steps = [("buildings", buildings), ("osm", osm), ("grid", grid), ("solar", solar)]
    else:
        steps = [("buildings", buildings), ("pois", pois), ("grid", grid), ("road", road), ("solar", solar), ("admin1", admin)]
    if live:
        with ThreadPoolExecutor(len(steps)) as ex:
            list(ex.map(lambda kv: run(*kv), steps))
    else:
        for kv in steps: run(*kv)

    out["population"] = {"worldpop": None}  # not implemented; see README
    out["warnings"] = W
    out["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    # key order per schema
    order = ["site_id", "name", "country", "admin1", "lat", "lon", "radius_m", "buildings", "pois", "grid", "road",
             "population", "solar", "warnings", "fetched_at"]
    return {k: out[k] for k in order}, res["bg"], res["pois"]


def warm():
    """Load the slow-to-start pieces (DuckDB extensions, building index, grid lines) ahead of the first request."""
    _con(); _vida_index(); _load_grid()
    if OSM_POIS.exists(): _osm_layers()


def geojson_for(bg, pois):
    feats = []
    if bg is not None and len(bg):
        b = bg
        if len(b) > MAX_GEO_BUILDINGS:
            b = b.sample(MAX_GEO_BUILDINGS, random_state=0)
        geoms = shapely.set_precision(b.geometry.values, 1e-6)
        for g, a, c in zip(geoms, b.area_m2.values, b.cls.values):
            feats.append({"type": "Feature", "properties": {"area_m2": round(float(a), 1), "cls": c},
                          "geometry": json.loads(shapely.to_geojson(g))})
    for p in pois or []:
        feats.append({"type": "Feature", "properties": {"poi_type": p["poi_type"], "name": p["name"]},
                      "geometry": {"type": "Point", "coordinates": [round(p["lon"], 6), round(p["lat"], 6)]}})
    return {"type": "FeatureCollection", "features": feats}


def write_site(feat, bg, pois):
    (SITES / "features").mkdir(parents=True, exist_ok=True)
    (SITES / "geo").mkdir(parents=True, exist_ok=True)
    sid = feat["site_id"]
    (SITES / "features" / f"{sid}.json").write_text(json.dumps(feat, indent=1))
    (SITES / "geo" / f"{sid}.geojson").write_text(json.dumps(geojson_for(bg, pois), separators=(",", ":")))


def compute_features(lat, lon, radius_m=1500, site_id=None, name=None, country=None, admin1=None,
                     write=False):
    timings = {}
    feat, bg, pois = compute_site(lat, lon, radius_m, site_id, name, country, admin1, timings)
    if bg is not None and len(bg) > MAX_GEO_BUILDINGS:
        feat["warnings"].append(f"geojson capped at {MAX_GEO_BUILDINGS} of {len(bg)} buildings (random sample); stats use all")
    if write:
        if not site_id: raise ValueError("site_id required to write")
        write_site(feat, bg, pois)
    return feat


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float); ap.add_argument("lon", type=float)
    ap.add_argument("--radius", type=float, default=1500)
    ap.add_argument("--id"); ap.add_argument("--name")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    t = time.time()
    f = compute_features(a.lat, a.lon, a.radius, a.id, a.name, write=a.write)
    print(json.dumps(f, indent=1)); print(f"# {time.time()-t:.1f}s", file=sys.stderr)
