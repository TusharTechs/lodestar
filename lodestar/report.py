"""Assemble the full site report (JSON) consumed by the API, the web app and the lender memo."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from . import finance, village
from .forecast import condition, exceedance
from .priors import OBS_SIGMA

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "ledger" / "forecasts.jsonl"


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def fan(draws) -> dict:
    t = draws.months
    tot = draws.total
    pc = {f"p{k}": np.percentile(tot, 100 - k, axis=0) for k in (90, 75, 50, 25, 10)}
    segs = {}
    for s in draws.conn:
        segs[s] = {"connections_p50": np.median(draws.conn[s], 0).round(1).tolist(),
                   "kwh_per_conn_p50": np.median(draws.q[s], 0).round(2).tolist(),
                   "energy_p50": np.median(draws.energy[s], 0).round(1).tolist()}
    if "anchors" in draws.energy:
        segs["anchors"] = {"energy_p50": np.median(draws.energy["anchors"], 0).round(1).tolist()}
    return {"months": t.astype(int).tolist(), **{k: v.round(1).tolist() for k, v in pc.items()}, "segments": segs}


def confidence(p90, p10):
    ratio = p10 / max(p90, 1e-9)
    return ("high" if ratio < 2.0 else "medium" if ratio < 4.0 else "low"), ratio


# Where each input comes from and how current it is. Refresh targets drive the freshness status
# shown in the app (Track record tab) and in every report.
SOURCES = {
    "footprints": {"label": "Building footprints", "source": "VIDA merge of Google, Microsoft and OSM Open Buildings (satellite-derived)",
                   "refresh_days": 365},
    "osm": {"label": "Schools, clinics, markets, mills, roads", "source": "OpenStreetMap", "refresh_days": 180},
    "solar": {"label": "Solar resource", "source": "NASA POWER long-term monthly climatology", "refresh_days": 3650},
    "grid": {"label": "Grid lines", "source": "GridFinder (Arderne et al. 2020)", "as_of": "2020", "refresh_days": 730},
    "benchmarks": {"label": "Consumption, cost and tariff benchmarks", "source": "AMDA Benchmarking Africa's Minigrids 2024",
                   "as_of": "2024", "refresh_days": 730},
    "meters": {"label": "Growth curves (metered mini-grids)", "source": "3 DR Congo mini-grids, 38-70 months each (Lunanga et al. 2026)",
               "as_of": "2024-12", "refresh_days": 120},
}


def basis(feat: dict, rep: dict) -> dict:
    """Plain-language explanation of what this forecast is built from (deterministic template)."""
    b, p = feat["buildings"], feat.get("pois") or {}
    pc = rep["potential_customers"]
    a = village.AMDA_ACPU[rep["region"]]
    anchors = {k: min(int(p.get(k) or 0), village.MAX_PER_ANCHOR_TYPE) for k in ("school", "health", "mill")}
    steps = [
        ("Who could connect",
         f"We counted {b['count']:,} buildings within {feat['radius_m'] / 1000:.1f} km in satellite-derived building footprints, "
         f"which suggests about {pc['household']:,.0f} households and {pc['sme']:,.0f} businesses. The buildings-to-households ratio "
         "was calibrated on census counts from two metered DR Congo mini-grid towns."),
        ("How much each will use",
         f"We start from what customers of African mini-grids actually use today ({a['household']} kWh/month per household and "
         f"{a['sme']} per business in {rep['region_label']}, AMDA 2024), then adjust for this village's drivers, shown below."),
        ("How fast it grows",
         "New customers don't all connect on day one, and they buy appliances over time. We learned both patterns from real "
         "mini-grids in DR Congo with 38-70 months of monthly meter data. "
         + ("This site is one of them, so its forecast learns only from the other two and never sees its own meters."
            if village.DRC_SITE.get(feat.get("site_id")) else "This site has no meter data yet; the forecast uses none.")),
        ("Big customers",
         (f"OpenStreetMap shows {anchors['school']} school(s), {anchors['health']} clinic(s) and {anchors['mill']} mill(s) here; "
          "their loads come from published load profiles (RAMP), mills from a stated assumption.")
         if sum(anchors.values()) else
         "OpenStreetMap shows no schools, clinics or mills here, so no anchor loads are added. Rural areas are often "
         "under-mapped, which makes this forecast conservative."),
        ("How sure we are",
         f"We run {rep['method']['draws']:,} scenarios that vary every uncertain input. P50 is the middle; P90 is the level demand beats in 9 of 10 "
         "scenarios, the safe number to lend against. On held-out metered sites the real demand fell inside our P90-P10 range "
         "in 5 of 6 site-years."),
    ]
    fetched = feat.get("fetched_at")
    age = None
    if fetched:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(fetched)).days
    inputs = [
        {**SOURCES["footprints"], "value": f"{b['count']:,} buildings", "as_of": (fetched or "")[:10]},
        {**SOURCES["osm"], "value": ", ".join(f"{p.get(k) or 0} {k}" for k in ("school", "health", "market", "mill")),
         "as_of": (fetched or "")[:10]},
        {**SOURCES["solar"], "value": f"{(feat.get('solar') or {}).get('ghi_annual') or 'n/a'} kWh/m²/day", "as_of": (fetched or "")[:10]},
        {**SOURCES["grid"], "value": f"{(feat.get('grid') or {}).get('dist_km', 'n/a')} km to nearest line"},
        {**SOURCES["benchmarks"], "value": f"{a['household']} / {a['sme']} kWh per household / business"},
        {**SOURCES["meters"], "value": "ramp shapes for connections and consumption"},
    ]
    return {"steps": [{"title": t, "text": x} for t, x in steps], "inputs": inputs,
            "site_data_fetched_at": fetched, "site_data_age_days": age}


def build(feat: dict, observed: dict | None = None, n: int = 20000, fin_overrides: dict | None = None,
          with_waterfall: bool = True) -> dict:
    region = village.region_of(feat)
    d = village.forecast(feat, n=n)
    update = None
    if observed:
        months = np.asarray(observed.pop("months"), float)
        d, diag = condition(d, observed, months, sigma=OBS_SIGMA)
        update = {"months_used": int(len(months)), "diagnostics": diag}
    y3 = village.year_energy(d, 3) / 12
    p = {"p90": float(np.percentile(y3, 10)), "p50": float(np.percentile(y3, 50)), "p10": float(np.percentile(y3, 90))}
    conf, ratio = confidence(p["p90"], p["p10"])
    yearly = []
    for y in range(1, 6):
        e = village.year_energy(d, y) / 12
        yearly.append({"year": y, **{k: float(np.percentile(e, q)) for k, q in (("p90", 10), ("p50", 50), ("p10", 90))}})
    seg_y3 = {}
    m = (d.months > 24) & (d.months <= 36)
    for s, arr in d.energy.items():
        seg_y3[s] = float(np.median(arr[:, m].mean(1)))
    conn_y3 = {s: float(np.median(c[:, 36])) for s, c in d.conn.items()}
    profile = village.hourly_profile(d, feat)
    fin = finance.stress_test(d, feat, region, profile, fin_overrides) if feat.get("solar", {}).get("ghi_monthly") else None
    rep = {
        "site": {k: feat.get(k) for k in ("site_id", "name", "country", "admin1", "lat", "lon", "radius_m")},
        "features": {k: feat.get(k) for k in ("buildings", "pois", "grid", "road", "solar")},
        "warnings": list(feat.get("warnings") or []),
        "region": region, "region_label": village.REGION_LABEL[region], "benchmark_note": village.benchmark_note(feat),
        "headline": {"year": 3, "unit": "kWh/month", **p, "confidence": conf, "p10_over_p90": ratio},
        "yearly": yearly, "fan": fan(d), "segments_y3_kwh_month": seg_y3, "connections_y3": conn_y3,
        "potential_customers": {s: village.build_spec(feat).potentials[s].median for s in ("household", "sme")},
        "anchors": [{"kind": a.kind, "kwh_month": a.kwh_month} for a in village.anchors_for(feat)],
        "drivers": village.drivers_for(feat),
        "waterfall": village.waterfall(feat) if with_waterfall else None,
        "load_profile": profile, "finance": fin, "update": update,
        "method": {"draws": n, "model_version": "lodestar-0.3",
                   "percentiles": "P90 = exceeded with 90% probability (conservative), P50 median, P10 optimistic"},
    }
    rep["basis"] = basis(feat, rep)
    n_conn = sum(conn_y3.values())
    avg = {"west_central": 592, "east_south": 209}[region]
    if n_conn < 100:
        rep["warnings"].append(f"Small for a mini-grid: about {n_conn:.0f} connections by year 3 at P50 (AMDA 2024 average site: {avg} connections in {village.REGION_LABEL[region]}). Solar home systems may serve this settlement more cheaply.")
    g = (feat.get("grid") or {}).get("dist_km")
    if g is not None and g < 5:
        rep["warnings"].append(f"Within {g:.1f} km of a mapped grid line (GridFinder): check grid-extension plans before building a mini-grid.")
    return json.loads(json.dumps(rep, default=lambda o: float(o) if isinstance(o, np.floating) else int(o)))


def ledger_entry(rep: dict, write: bool = True) -> dict:
    """Pre-register a forecast: hash of the site and its forecast numbers, timestamped, append-only."""
    core = {"site": rep["site"], "headline": rep["headline"], "yearly": rep["yearly"],
            "model_version": rep["method"]["model_version"]}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    entry = {"forecast_id": hashlib.sha256(blob).hexdigest()[:16],
             "issued_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "site_id": rep["site"]["site_id"], "name": rep["site"]["name"],
             "y3_p90": _r(rep["headline"]["p90"]), "y3_p50": _r(rep["headline"]["p50"]), "y3_p10": _r(rep["headline"]["p10"]),
             "status": ("scored against historical meters (backtest)" if village.DRC_SITE.get(rep["site"]["site_id"])
                        else "awaiting metered data")}
    if write:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        existing = LEDGER.read_text().splitlines() if LEDGER.exists() else []
        if not any(json.loads(l)["forecast_id"] == entry["forecast_id"] for l in existing):
            with LEDGER.open("a") as f:
                f.write(json.dumps(entry) + "\n")
    return entry
