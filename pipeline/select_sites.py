"""Pick demo villages (NG, KE), add DRC validation sites, run compute_features, write index.json.

python pipeline/select_sites.py [--per-country 12] [--max-candidates 14] [--force] [--only ng|ke|drc|index]
"""
import argparse, json, random, re, sys, time, unicodedata, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import features as F

SITES = F.SITES
REGIONS = {
    "NG": [("Kaduna", "kd"), ("Niger", "ni"), ("Kano", "kn"), ("Kogi", "kg"), ("Plateau", "pl")],
    "KE": [("Turkana", "tur"), ("Marsabit", "mar"), ("Kitui", "kit"), ("Kajiado", "kaj"), ("Narok", "nar"),
           ("West Pokot", "wpk")],
}
DRC = [  # site_id, name, approx lat, lon, osm place regex, radius
    ("cd-nk-mutwanga", "Mutwanga", 0.33, 29.75, "^Mutwanga"),
    ("cd-nk-lubero", "Lubero", -0.16, 29.24, "^Lubero"),
    ("cd-nk-goma", "Goma", -1.68, 29.23, "^Goma"),
]


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def places(state):
    q = (f'[out:json][timeout:120];area[boundary=administrative][admin_level=4][name~"^{state}"]->.a;'
         f'node(area.a)[place~"^(village|hamlet)$"][name];out;')
    return [(e["tags"]["name"], e["lat"], e["lon"], e["tags"]["place"]) for e in F.overpass(q)["elements"]]


def productive(pois):
    return bool(pois and ((pois.get("market") or 0) > 0 or (pois.get("mill") or 0) > 0 or (pois.get("shop") or 0) >= 3))


def pick_country(cc, per_country, max_cand, seed=1, only_state=None, compute=False):
    rnd = random.Random(seed)
    found = []
    states = [s for s in REGIONS[cc] if only_state in (None, s[1])]
    for state, code in states:
        cache = F.CACHE / f"candidates_{cc}_{code}.json"
        if cache.exists():
            found += json.loads(cache.read_text()); continue
        try:
            pl = places(state)
        except Exception as e:
            print(f"[{cc}] places failed for {state}: {e}"); continue
        rnd.shuffle(pl)
        seen_names, good, tried, nfar = set(), [], 0, 0
        for name, lat, lon, kind in pl:
            if len(good) >= max_cand // 2 + 1 or tried >= max_cand * 3: break
            if name.lower() in seen_names: continue
            seen_names.add(name.lower())
            try:
                d = F.grid_dist_km(lat, lon)
                if d is None or d <= 5: continue
                tf = F.target_frac(lat, lon, 1500)
                if tf is None or tf > 0.02: continue
            except Exception as e:
                print("grid check failed", e); continue
            nfar += 1; tried += 1
            try:
                raw, _ = F.get_buildings(lat, lon, 1500)
                n = len(F.building_stats(lat, lon, 1500, raw))
            except Exception as e:
                print(f"  bld fail {name}: {e}"); continue
            print(f"[{cc}/{state}] {name} d={d:.1f} tf={tf:.3f} n={n}", flush=True)
            if not (150 <= n <= 3000): continue
            try:
                pois = {k: v for k, v in zip(F.POI_KEYS, [0] * 11)}
                for p in F.get_pois(lat, lon, 1500): pois[p["poi_type"]] += 1
            except Exception as e:
                pois = None
            good.append(dict(state=state, code=code, name=name, lat=lat, lon=lon, n=n, d=d, tf=tf,
                             productive=productive(pois), pois=pois))
            if compute:
                run_site(f"{cc.lower()}-{code}-{slug(name)}", name, lat, lon, 1500, cc, state)
        cache.write_text(json.dumps(good))
        found += good
    # balanced selection: productive first (~half), round-robin by state
    def rr(items):
        by = {}
        for c in items: by.setdefault(c["code"], []).append(c)
        out = []
        while any(by.values()):
            for k in list(by):
                if by[k]: out.append(by[k].pop(0))
        return out
    prod, non = rr([c for c in found if c["productive"]]), rr([c for c in found if not c["productive"]])
    half = per_country // 2
    chosen = prod[:half]
    chosen += [c for c in rr(non + prod[half:]) if c not in chosen][: per_country - len(chosen)]
    return chosen


def run_site(sid, name, lat, lon, radius, country, admin1, extra_warn=None, force=False):
    f = SITES / "features" / f"{sid}.json"
    if f.exists() and not force:
        print("skip", sid); return
    t = time.time()
    feat = F.compute_features(lat, lon, radius, sid, name, country=country, admin1=admin1, write=False)
    # re-run write path via compute_site cache-free: recompute pieces for geo
    feat_full, bg, pois = F.compute_site(lat, lon, radius, sid, name, country, admin1)
    feat_full["warnings"] = feat["warnings"] + [w for w in (extra_warn or [])]
    F.write_site(feat_full, bg, pois)
    print(f"done {sid} {time.time()-t:.1f}s warnings={feat_full['warnings']}", flush=True)


def drc_sites(force):
    for sid, name, lat, lon, rx in DRC:
        warn = []
        q = f'[out:json][timeout:60];node(around:30000,{lat},{lon})[place~"^(city|town|village)$"][name~"{rx}"];out;'
        try:
            els = F.overpass(q)["elements"]
            if els:
                e = min(els, key=lambda e: (e["lat"] - lat) ** 2 + (e["lon"] - lon) ** 2)
                if abs(e["lat"] - lat) > 0.005 or abs(e["lon"] - lon) > 0.005:
                    warn.append(f"centre moved to OSM place node ({e['lat']:.4f},{e['lon']:.4f}); prior approx ({lat},{lon})")
                lat, lon = e["lat"], e["lon"]
            else:
                warn.append("no OSM place node found; using approximate centre")
        except Exception as ex:
            warn.append(f"OSM place verification failed ({ex}); using approximate centre")
        if sid.endswith("goma"): warn.append("urban; service area not delimited")
        run_site(sid, name, lat, lon, 2000, "CD", "North Kivu", warn, force)


def build_index():
    rows = []
    for f in sorted((SITES / "features").glob("*.json")):
        d = json.loads(f.read_text())
        p = d["pois"]
        rows.append({"site_id": d["site_id"], "name": d["name"], "country": d["country"], "admin1": d["admin1"],
                     "lat": d["lat"], "lon": d["lon"], "n_buildings": d["buildings"]["count"],
                     "dist_grid_km": d["grid"]["dist_km"],
                     "has_market": None if p["market"] is None else p["market"] > 0,
                     "has_mill": None if p["mill"] is None else p["mill"] > 0})
    (SITES / "index.json").write_text(json.dumps(rows, indent=1))
    print("index:", len(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-country", type=int, default=12)
    ap.add_argument("--max-candidates", type=int, default=14)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", choices=["ng", "ke", "drc", "index"])
    ap.add_argument("--state", help="CC:code, e.g. NG:kd - build candidates (and features) for one state, then exit")
    a = ap.parse_args()
    if a.state:
        cc, code = a.state.split(":")
        pick_country(cc, a.per_country, a.max_candidates, only_state=code, compute=True)
        sys.exit(0)
    if a.only in (None, "drc"): drc_sites(a.force)
    for cc in ("NG", "KE"):
        if a.only in (None, cc.lower()):
            for c in pick_country(cc, a.per_country, a.max_candidates):
                sid = f"{cc.lower()}-{c['code']}-{slug(c['name'])}"
                run_site(sid, c["name"], c["lat"], c["lon"], 1500, cc, c["state"], force=a.force)
    build_index()
