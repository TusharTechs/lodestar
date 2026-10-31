"""Turn open geospatial features of a settlement into a demand forecast.

Every multiplier below is tagged with where it comes from:
  "calibrated"  fitted to the DRC metered/census data
  "benchmark"   published benchmark (AMDA 2024, RAMP archetypes)
  "assumption"  team prior, not yet calibrated; the Demand Bureau is how it gets calibrated
"""
from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from .drc import load_panels
from .forecast import Anchor, LogNormal, SiteSpec, exceedance, simulate
from .priors import AMDA_ACPU, benchmark_prior, fit_site

DATA = Path(__file__).resolve().parent / "data"
REGION_OF = {"NG": "west_central", "CD": "west_central", "KE": "east_south"}
REGION_LABEL = {"west_central": "West & Central Africa", "east_south": "East & Southern Africa"}

# Footprints -> potential customers. Calibrated on the two DRC village sites, where the
# source census counts households and firms in the service area:
#   households / dwelling-size buildings (<=120 m2): Mutwanga 5513/11122 = 0.50, Lubero 4160/12221 = 0.34
#   firms / large buildings (>120 m2):              Mutwanga 317/278   = 1.14, Lubero 536/520    = 1.03
# All buildings up to 120 m2 count as possible dwellings: in rural Kenya and northern Nigeria most
# dwellings are huts under 30 m2, and several structures typically belong to one household compound.
HH_PER_RES_BUILDING = float(np.sqrt(0.50 * 0.34))     # geometric mean 0.41
SME_PER_LARGE_BUILDING = float(np.sqrt(1.14 * 1.03))  # 1.08
POT_SIGMA = 0.30                                      # covers the 0.53-0.78 spread and footprint errors

# Anchor loads (kWh/month) from RAMP SSA archetypes (Stevanato 2026, CC-BY-4.0)
SCHOOL_KWH_MONTH = 7046.4 / 12        # SCH_T1 rural primary school
CLINIC_KWH_MONTH = 2771.5 / 12        # HF_T1 dispensary / health post
MILL_KWH_MONTH = 300.0                # assumption: ~5 kW mill x 2 h/day x 30 days
MAX_PER_ANCHOR_TYPE = 3


@lru_cache(maxsize=1)
def drc_fits_by_site():
    return {name: fit_site(p) for name, p in load_panels().items()}


def drc_fits():
    return list(drc_fits_by_site().values())


# The metered DRC sites are shown next to their real meters, so their own forecasts must not learn
# from their own data: growth curves come from the other sites only (same as the validation).
DRC_SITE = {"cd-nk-goma": "Goma", "cd-nk-lubero": "Lubero", "cd-nk-mutwanga": "Mutwanga"}
# Households per dwelling-size building and firms per large building, measured site by site
# (census counts / footprint counts within the 2 km service radius)
_DRC_RATIOS = {"Lubero": (0.34, 1.03), "Mutwanga": (0.50, 1.14)}


def held_out(feat: dict) -> dict:
    """Overrides that keep a metered site's own data out of its forecast."""
    name = DRC_SITE.get(feat.get("site_id"))
    if not name:
        return {}
    others = [n for n in _DRC_RATIOS if n != name]
    hh = float(np.exp(np.mean([np.log(_DRC_RATIOS[n][0]) for n in others])))
    sme = float(np.exp(np.mean([np.log(_DRC_RATIOS[n][1]) for n in others])))
    return {"fits": [f for n, f in drc_fits_by_site().items() if n != name], "hh_ratio": hh, "sme_ratio": sme}


@lru_cache(maxsize=1)
def load_shapes():
    return json.loads((DATA / "load_shapes.json").read_text())


def drivers_for(feat: dict) -> list[dict]:
    """Explainable multiplicative drivers derived from the site's features."""
    b, p, road = feat["buildings"], feat["pois"] or {}, (feat.get("road") or {}).get("dist_major_km")
    out = []
    med = b.get("median_area_m2")
    if med:
        f = float(np.clip((med / 40.0) ** 0.5, 0.75, 1.35))
        out.append(dict(key="wealth", target="Q.household", factor=f, source="assumption",
                        text=f"Median building footprint {med:.0f} m² (reference 40 m²) used as a wealth proxy"))
    if p.get("market"):
        out.append(dict(key="market", target="pot.sme", factor=1.25, source="assumption",
                        text=f"{p['market']} market(s) mapped in OpenStreetMap: more businesses likely"))
    if road is not None and road > 5:
        out.append(dict(key="remote", target="Q", factor=0.85, source="assumption",
                        text=f"{road:.1f} km from the nearest major road: lower appliance access"))
    elif road is None:
        out.append(dict(key="remote", target="Q", factor=0.85, source="assumption",
                        text="No major road within 15 km in OpenStreetMap: lower appliance access"))
    return out


def anchors_for(feat: dict) -> list[Anchor]:
    p = feat["pois"] or {}
    out = []
    for kind, kwh, sig in (("school", SCHOOL_KWH_MONTH, 0.35), ("health", CLINIC_KWH_MONTH, 0.35),
                           ("mill", MILL_KWH_MONTH, 0.60)):
        for _ in range(min(int(p.get(kind) or 0), MAX_PER_ANCHOR_TYPE)):
            out.append(Anchor(kind=kind, kwh_month=kwh, sigma=sig, connect_month=3.0))
    return out


def build_spec(feat: dict, use: set[str] | None = None, horizon: int = 60, fits: list | None = None,
               hh_ratio: float = HH_PER_RES_BUILDING, sme_ratio: float = SME_PER_LARGE_BUILDING) -> SiteSpec:
    """Spec for a site. `use` limits which drivers/anchors are switched on (for the waterfall).
    `fits`, `hh_ratio`, `sme_ratio` can be overridden for leave-one-site-out validation."""
    region = REGION_OF.get(feat.get("country"), "west_central")
    if fits is None:
        ho = held_out(feat)
        fits = ho.get("fits") or drc_fits()
        hh_ratio, sme_ratio = ho.get("hh_ratio", hh_ratio), ho.get("sme_ratio", sme_ratio)
    priors = {s: benchmark_prior(fits, s, region) for s in ("household", "sme")}
    b = feat["buildings"]
    pot = {"household": max((b["n_residential"] + b["n_small"]) * hh_ratio, 5.0),
           "sme": max(b["n_large"] * sme_ratio, 1.0)}
    for d in drivers_for(feat):
        if use is not None and d["key"] not in use:
            continue
        tgt = d["target"]
        if tgt.startswith("pot."):
            pot[tgt[4:]] *= d["factor"]
        else:
            segs = ("household", "sme") if tgt == "Q" else (tgt.split(".")[1],)
            for s in segs:
                priors[s] = replace(priors[s], Q=LogNormal(priors[s].Q.median * d["factor"], priors[s].Q.sigma))
    anchors = anchors_for(feat) if (use is None or "anchors" in use) else []
    return SiteSpec(potentials={s: LogNormal(v, POT_SIGMA) for s, v in pot.items()},
                    priors=priors, anchors=anchors, horizon=horizon)


def year_energy(draws, year: int) -> np.ndarray:
    m = (draws.months > 12 * (year - 1)) & (draws.months <= 12 * year)
    return draws.total[:, m].sum(axis=1)


def waterfall(feat: dict, n: int = 6000) -> list[dict]:
    """One-driver-at-a-time contributions to year-3 P50 energy (common random numbers)."""
    steps = [("base", "Settlement size from footprints x regional benchmark consumption", set())]
    keys = [d["key"] for d in drivers_for(feat)]
    texts = {d["key"]: (d["text"], d["source"]) for d in drivers_for(feat)}
    for k in keys:
        steps.append((k, texts[k][0], {k}))
    if anchors_for(feat):
        steps.append(("anchors", "Anchor customers (schools, clinics, mills)", {"anchors"}))
    out, used = [], set()
    prev = None
    for key, text, add in steps:
        used |= add
        p50 = float(np.median(year_energy(simulate(build_spec(feat, use=set(used)), n=n, seed=5), 3))) / 12
        row = {"key": key, "text": text, "p50_kwh_month": p50,
               "source": "calibrated + benchmark" if key == "base" else texts.get(key, ("", "RAMP archetypes / assumption"))[1]}
        if key == "anchors":
            row["source"] = "benchmark (RAMP) + assumption (mills)"
        if prev is not None:
            row["delta_pct"] = (p50 - prev) / prev
        out.append(row)
        prev = p50
    return out


def hourly_profile(draws, feat: dict, year: int = 3) -> dict:
    """Mean-day load profile (kW) at P50 for the given year, by segment."""
    sh = load_shapes()
    zone = "household_F1" if feat["lat"] >= 10 else "household_F2"
    m = (draws.months > 12 * (year - 1)) & (draws.months <= 12 * year)
    prof = {}
    seg_kwh_day = {s: float(np.median(draws.energy[s][:, m].mean(axis=1))) / 30.4 for s in draws.energy if s != "anchors"}
    prof["household"] = np.array(sh[zone]) * seg_kwh_day.get("household", 0)
    prof["sme"] = np.array(sh["sme"]) * seg_kwh_day.get("sme", 0)
    anc = np.zeros(24)
    for i, k in enumerate([k for k in draws.params if k.startswith("anchor")]):
        kind = k.split(".")[1]
        anc += np.array(sh[kind]) * float(np.median(draws.params[k])) / 30.4
    prof["anchors"] = anc
    total = sum(prof.values())
    def lf(x):
        return float(x.mean() / x.max()) if x.max() > 0 else None
    return {"hours": list(range(24)), "kw": {k: v.round(3).tolist() for k, v in prof.items()},
            "total_kw": total.round(3).tolist(), "peak_kw": float(total.max()),
            "load_factor": lf(total), "load_factor_households_only": lf(prof["household"]),
            "shapes_source": sh["_source"] + " " + sh["_assumptions"]}


def region_of(feat: dict) -> str:
    return REGION_OF.get(feat.get("country"), "west_central")


def benchmark_note(feat: dict) -> str:
    r = region_of(feat)
    a = AMDA_ACPU[r]
    return (f"AMDA 2024 {REGION_LABEL[r]} benchmarks: {a['household']} kWh/month per household, "
            f"{a['sme']} kWh/month per business connection")


def forecast(feat: dict, n: int = 20000, seed: int = 7):
    return simulate(build_spec(feat), n=n, seed=seed)


__all__ = ["forecast", "build_spec", "waterfall", "hourly_profile", "year_energy", "exceedance",
           "drivers_for", "anchors_for", "region_of", "benchmark_note"]
