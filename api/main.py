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
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

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


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/docs-static", StaticFiles(directory=str(ROOT / "docs")), name="docs")
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
