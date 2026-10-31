"""Lodestar API + static web app.

uvicorn api.main:app --port 8000
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request, UploadFile
import zipfile

from fastapi import Form
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from lodestar import economics as ECON  # noqa: E402
from lodestar import report as R  # noqa: E402
from lodestar.drc import load_panels  # noqa: E402

SITES = ROOT / "data" / "sites"
REPORTS = SITES / "reports"
WEB = ROOT / "web"
VALIDATION = ROOT / "data" / "derived" / "validation.json"
DRC_PANEL = {"cd-nk-goma": "Goma", "cd-nk-lubero": "Lubero", "cd-nk-mutwanga": "Mutwanga"}
BUREAU_FIELDS = ["months_since_cod", "conn_household", "conn_sme", "kwh_per_household", "kwh_per_sme"]

app = FastAPI(title="Lodestar", description="Bankable demand forecasts for mini-grids")
env = Environment(loader=FileSystemLoader(str(ROOT / "api" / "templates")), autoescape=select_autoescape())
env.filters["mwh"] = lambda v: "n/a" if v is None else f"{v / 1000:,.1f}"
env.filters["num"] = lambda v, nd=0: "n/a" if v is None else f"{v:,.{nd}f}"
env.filters["pct"] = lambda v, nd=0: "n/a" if v is None else f"{100 * v:.{nd}f}%"
env.filters["usd"] = lambda v: "n/a" if v is None else (f"${v / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${v:,.0f}")
JOBS: dict[str, dict] = {}
DRAWS = int(os.environ.get("LODESTAR_DRAWS", "20000"))  # lower on small hosts


def features(site_id: str) -> dict:
    f = SITES / "features" / f"{site_id}.json"
    if not f.exists():
        raise HTTPException(404, f"unknown site {site_id}")
    return json.loads(f.read_text())


def actuals(site_id: str) -> dict | None:
    """Metered history for the DRC validation sites (Lunanga et al. 2026, CC0)."""
    if site_id not in DRC_PANEL:
        return None
    p = load_panels()[DRC_PANEL[site_id]]
    return {"months": p.months.astype(int).tolist(), "total_kwh": p.total_kwh.round(1).tolist(),
            "conn_household": p.conn_hh.tolist(), "conn_sme": p.conn_sme.tolist(),
            "kwh_per_household": np.nan_to_num(p.kwh_hh).round(2).tolist(),
            "kwh_per_sme": np.nan_to_num(p.kwh_sme).round(2).tolist(),
            "source": "Lunanga, Stoop, Verpoorten & Desbureaux (2026), Energy Economics; doi:10.7910/DVN/KPDREF (CC0)"}


def get_report(site_id: str, refresh: bool = False) -> dict:
    f = REPORTS / f"{site_id}.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text())
    rep = R.build(features(site_id), n=DRAWS)
    rep["actuals"] = actuals(site_id)
    rep["ledger"] = R.ledger_entry(rep)
    REPORTS.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rep))
    return rep


@app.get("/api/sites")
def sites():
    idx = SITES / "index.json"
    return json.loads(idx.read_text()) if idx.exists() else []


@app.get("/api/sites/{site_id}/report")
def site_report(site_id: str, refresh: bool = False):
    return get_report(site_id, refresh)


@app.get("/api/sites/{site_id}/geo")
def site_geo(site_id: str):
    f = SITES / "geo" / f"{site_id}.geojson"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/geo+json")


def _observed_from_rows(rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: float(r["months_since_cod"]))
    col = lambda k: [float(r[k]) if r.get(k) not in (None, "") else np.nan for r in rows]
    return {"months": col("months_since_cod"), "conn.household": col("conn_household"), "conn.sme": col("conn_sme"),
            "q.household": col("kwh_per_household"), "q.sme": col("kwh_per_sme")}


def bureau_update(site_id: str, rows: list[dict]) -> dict:
    if not rows:
        raise HTTPException(400, "no rows")
    missing = [k for k in BUREAU_FIELDS if k not in rows[0]]
    if missing:
        raise HTTPException(400, f"missing columns: {missing}")
    rep = R.build(features(site_id), observed=_observed_from_rows(rows), with_waterfall=False, n=DRAWS)
    rep["actuals"] = actuals(site_id)
    rep["prior_headline"] = get_report(site_id)["headline"]
    return rep


@app.post("/api/sites/{site_id}/bureau")
async def bureau_upload(site_id: str, file: UploadFile):
    text = (await file.read()).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    return bureau_update(site_id, rows)


@app.get("/api/sites/{site_id}/bureau-sample.csv")
def bureau_sample(site_id: str, months: int = 6):
    """For validation sites: the first N real metered months in Demand Bureau format."""
    a = actuals(site_id)
    if a is None:
        raise HTTPException(404, "sample meter data exists only for the DRC validation sites")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["site_hash", "country", "admin1"] + BUREAU_FIELDS)
    for i, m in enumerate(a["months"]):
        if m > months:
            break
        w.writerow([R.ledger_entry(get_report(site_id), write=False)["forecast_id"][:8], "CD", "North Kivu", m,
                    int(a["conn_household"][i]), int(a["conn_sme"][i]), a["kwh_per_household"][i] or "", a["kwh_per_sme"][i] or ""])
    return PlainTextResponse(out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{site_id}-first-{months}-months.csv"'})


@app.get("/api/sites/{site_id}/bureau-demo")
def bureau_demo(site_id: str, months: int = 6):
    a = actuals(site_id)
    if a is None:
        raise HTTPException(404, "demo meter data exists only for the DRC validation sites")
    rows = [dict(zip(BUREAU_FIELDS, (m, a["conn_household"][i], a["conn_sme"][i], a["kwh_per_household"][i] or None,
                                     a["kwh_per_sme"][i] or None)))
            for i, m in enumerate(a["months"]) if m <= months]
    return bureau_update(site_id, rows)


@app.get("/api/sites/{site_id}/load-8760.csv")
def load_8760(site_id: str):
    """Year-3 P50 hourly load (kW) for 8760 hours, HOMER/REopt single-column format."""
    rep = get_report(site_id)
    day = rep["load_profile"]["total_kw"]
    body = "\n".join(f"{day[h % 24]:.3f}" for h in range(8760)) + "\n"
    return PlainTextResponse(body, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{site_id}-load-8760-kw.csv"'})


@app.get("/api/sites/{site_id}/memo", response_class=HTMLResponse)
def memo(site_id: str):
    rep = get_report(site_id)
    val = json.loads(VALIDATION.read_text())["results"] if VALIDATION.exists() else None
    return env.get_template("memo.html").render(r=rep, v=val)


def _job(lat: float, lon: float, radius: float, jid: str):
    import features as F
    try:
        JOBS[jid]["stage"] = "fetching building footprints, OpenStreetMap and NASA POWER"
        sid = f"pt-{lat:.4f}-{lon:.4f}".replace(".", "_")
        feat, bg, pois = F.compute_site(lat, lon, radius, sid, f"Point {lat:.4f}, {lon:.4f}")
        if not feat["buildings"].get("count"):
            raise RuntimeError("no building footprints found here; " + "; ".join(feat["warnings"]))
        F.write_site(feat, bg, pois)
        JOBS[jid]["stage"] = "running forecast"
        rep = get_report(sid)
        JOBS[jid].update(status="done", site_id=sid, report=rep)
    except Exception as e:
        JOBS[jid].update(status="error", error=str(e))


@app.post("/api/forecast")
async def forecast_point(req: Request):
    b = await req.json()
    lat, lon = float(b["lat"]), float(b["lon"])
    radius = float(b.get("radius_m", 1500))
    if not (500 <= radius <= 3000):
        raise HTTPException(400, "radius_m must be 500-3000")
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"status": "running", "stage": "queued", "started": time.time()}
    threading.Thread(target=_job, args=(lat, lon, radius, jid), daemon=True).start()
    return {"job": jid}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404)
    j = dict(JOBS[jid])
    j["elapsed_s"] = round(time.time() - j.pop("started"), 1)
    return j


@app.get("/api/validation")
def validation():
    if not VALIDATION.exists():
        raise HTTPException(404)
    return json.loads(VALIDATION.read_text())


@app.get("/api/ledger")
def ledger():
    if not R.LEDGER.exists():
        return []
    return [json.loads(l) for l in R.LEDGER.read_text().splitlines() if l.strip()]


MTF_TIER2_KWH_MONTH = 6.0


def classify(rep: dict) -> tuple[str, str]:
    """Portfolio category for an RBF programme or DFI screening many settlements."""
    f, g = rep.get("finance") or {}, (rep["features"].get("grid") or {}).get("dist_km")
    conn = sum(rep["connections_y3"].values())
    if g is not None and g < 5:
        return "grid", "Check grid extension first"
    # World Bank Multi-Tier Framework: Tier 2 starts at 200 Wh/day (~6 kWh/month); below that,
    # solar home systems typically meet household needs
    if conn < 100 or rep["headline"]["p50"] / max(conn, 1) < MTF_TIER2_KWH_MONTH:
        return "shs", "Solar home systems"
    if f and f["tariff_with_rbf_usd_kwh"] <= f["region_tariff_usd_kwh"]:
        return "rbf", "Mini-grid: bankable with RBF grant"
    return "anchor", "Mini-grid: needs anchor load or tariff support"


@app.get("/api/portfolio")
def portfolio():
    rows = []
    for s in sites():
        rep = get_report(s["site_id"])
        f = rep.get("finance") or {}
        cat, label = classify(rep)
        o = (f.get("options") or {}).get("p50", {})
        rows.append({"site_id": s["site_id"], "name": rep["site"]["name"], "country": rep["site"]["country"],
                     "admin1": rep["site"]["admin1"], "category": cat, "category_label": label,
                     "y3_p90": rep["headline"]["p90"], "y3_p50": rep["headline"]["p50"], "y3_p10": rep["headline"]["p10"],
                     "connections_y3": sum(rep["connections_y3"].values()),
                     "kwh_per_connection": rep["headline"]["p50"] / max(sum(rep["connections_y3"].values()), 1),
                     "grid_km": (rep["features"].get("grid") or {}).get("dist_km"),
                     "capex_usd": o.get("capex_usd"), "pv_kwp": o.get("pv_kwp"),
                     "grant_per_connection_usd": f.get("grant_per_connection_usd"),
                     "tariff_with_rbf_usd_kwh": f.get("tariff_with_rbf_usd_kwh"),
                     "region_tariff_usd_kwh": f.get("region_tariff_usd_kwh"),
                     "cost_of_power_usd_kwh": o.get("cost_of_power_usd_kwh"),
                     "cost_of_power_if_p10_usd_kwh": (f.get("options") or {}).get("p10", {}).get("cost_of_power_usd_kwh"),
                     "metered": s["site_id"] in DRC_PANEL})
    return rows


@app.get("/api/economics")
def economics():
    rt = ROOT / "data" / "derived" / "runtime.json"
    m = json.loads(rt.read_text()) if rt.exists() else {"seconds_per_report": None, "report_kb_gzip": None}
    out = ECON.summary(m["seconds_per_report"] or 1.0, m["report_kb_gzip"] or 0.0)
    out["measured"]["note"] = m.get("note")
    return out


def sms_text(rep: dict) -> str:
    """One SMS (<=160 chars) summarising a forecast, for field officers on feature phones."""
    h, f = rep["headline"], rep.get("finance") or {}
    o = (f.get("options") or {}).get("p50", {})
    cat = classify(rep)[1]
    t = (f"{rep['site']['name'][:14]} Y3 demand MWh/mo P90 {h['p90'] / 1e3:.1f} P50 {h['p50'] / 1e3:.1f} "
         f"P10 {h['p10'] / 1e3:.1f}. PV {o.get('pv_kwp', 0):.0f}kWp. {cat}. ID {rep['ledger']['forecast_id'][:8]}")
    return t[:160]


def nearest_site(lat: float, lon: float, max_km: float = 10.0):
    best = None
    for s in sites():
        d = ((s["lat"] - lat) ** 2 + ((s["lon"] - lon) * np.cos(np.radians(lat))) ** 2) ** 0.5 * 111.32
        if best is None or d < best[1]:
            best = (s, d)
    return best if best and best[1] <= max_km else None


@app.get("/api/sms", response_class=PlainTextResponse)
def sms(site: str | None = None, lat: float | None = None, lon: float | None = None):
    """SMS reply text. Ready to be returned by an SMS gateway webhook (e.g. Africa's Talking)."""
    if site:
        return sms_text(get_report(site))
    if lat is not None and lon is not None:
        hit = nearest_site(lat, lon)
        if hit:
            return sms_text(get_report(hit[0]["site_id"]))
        return "No forecast cached within 10 km. Request queued: reply arrives by SMS when ready (2-5 min)."
    raise HTTPException(400, "give site= or lat= and lon=")


@app.post("/ussd", response_class=PlainTextResponse)
def ussd(sessionId: str = Form(""), serviceCode: str = Form(""), phoneNumber: str = Form(""), text: str = Form("")):
    """USSD menu in the Africa's Talking callback format (CON = continue, END = final screen).
    Not connected to a live short code; the phone number is never stored."""
    parts = [p for p in text.split("*") if p != ""] if text else []
    ss = sites()
    by_cc = {"1": "NG", "2": "KE", "3": "CD"}
    if not parts:
        return "CON Lodestar mini-grid demand\n1. Nigeria\n2. Kenya\n3. DR Congo"
    cc = by_cc.get(parts[0])
    if not cc:
        return "END Invalid choice"
    lst = [s for s in ss if s["country"] == cc][:9]
    if len(parts) == 1:
        return "CON Pick a village\n" + "\n".join(f"{i + 1}. {s['name']}" for i, s in enumerate(lst))
    try:
        s = lst[int(parts[1]) - 1]
    except (ValueError, IndexError):
        return "END Invalid choice"
    return "END " + sms_text(get_report(s["site_id"]))


@app.get("/api/sites/{site_id}/pack.zip")
def site_pack(site_id: str):
    """Offline site pack: lender memo (self-contained HTML), report JSON, 8760 load CSV, README."""
    rep = get_report(site_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("memo.html", memo(site_id))
        z.writestr("report.json", json.dumps(rep, indent=1))
        z.writestr("load-8760-kw.csv", load_8760(site_id).body.decode())
        z.writestr("README.txt", f"Lodestar offline site pack: {rep['site']['name']}\n"
                   f"Forecast ID {rep['ledger']['forecast_id']} issued {rep['ledger']['issued_at']}\n"
                   "memo.html opens in any browser without internet. load-8760-kw.csv imports into HOMER/REopt.\n"
                   f"SMS summary: {sms_text(rep)}\n")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="lodestar-{site_id}.zip"'})


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/docs-static", StaticFiles(directory=str(ROOT / "docs")), name="docs")
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
