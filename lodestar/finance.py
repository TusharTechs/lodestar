"""System sizing and lender stress test across Monte Carlo demand draws.

Cited benchmarks (AMDA, Benchmarking Africa's Minigrids 2024):
  CAPEX per kWp, four-year average: $5,775 East & Southern, $7,209 West & Central (sec. 5.1)
  OPEX per customer 2024: $16-26 per year (sec. 5 summary) -> midpoint $21
  Average tariff: $0.40/kWh East & Southern (residential), $0.25/kWh West & Central (sec. 6.3)
  Residential ARPU: $2.5 East & Southern, $2.0 West & Central per month (Table 8)
  CAPEX per connection: $1,948 East & Southern, $1,046 West & Central (Figure 12)
  RBF grants: Nigeria Electrification Project subsidised $350-600 per connection (sec. 4.1)
Productive-use scenario: CrossBoundary Innovation Lab found average consumption of 11.0 kWh/month
on sites with income-generating-appliance financing vs 6.7 on control sites (CrossBoundary/ESMAP
Access-to-Finance roadshow, 2025).
Everything else in ASSUMPTIONS is a team assumption shown in the UI and editable via the API.
"""
from __future__ import annotations

import numpy as np

CAPEX_PER_KWP = {"east_south": 5775.0, "west_central": 7209.0}
TARIFF = {"east_south": 0.40, "west_central": 0.25}
ARPU_HH = {"east_south": 2.5, "west_central": 2.0}
OPEX_PER_CUSTOMER_YR = 21.0
CAPEX_PER_CONNECTION = {"east_south": 1948.0, "west_central": 1046.0}
RBF_GRANT_PER_CONNECTION = (350.0, 600.0)
PUE_UPLIFT = 11.0 / 6.7

ASSUMPTIONS = {
    "performance_ratio": 0.75,       # PV system losses
    "battery_dod": 0.80,
    "battery_efficiency": 0.90,
    "inverter_margin": 1.25,
    "collection_rate": 0.95,
    "life_years": 20,
    "grant_share": None,             # share of CAPEX covered by grant (e.g. RBF); None = grant needed at P50
    "debt_sizing": "p90",            # size debt so DSCR >= covenant on the P90 (or P50) demand path
    "debt_rate": 0.12,
    "debt_tenor": 7,
    "debt_grace_years": 2,           # no debt service while connections ramp up; interest capitalised
    "dscr_covenant": 1.20,
    "hurdle_irr": 0.12,
}
SIZE_YEAR = 3


def annual_paths(draws, life: int, uplift: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Annual energy (kWh) and mean connections per draw, years 1..life (flat after the forecast horizon).
    `uplift` scales household and business consumption (productive-use scenario); anchors are unchanged."""
    T = int(draws.months.max())
    yrs = T // 12
    e, c = [], []
    conn_tot = sum(draws.conn.values())
    n_anchor = len([k for k in draws.params if k.startswith("anchor")])
    total = sum(v * (1.0 if k == "anchors" else uplift) for k, v in draws.energy.items())
    for y in range(1, yrs + 1):
        m = (draws.months > 12 * (y - 1)) & (draws.months <= 12 * y)
        e.append(total[:, m].sum(axis=1))
        c.append(conn_tot[:, m].mean(axis=1) + n_anchor)
    e, c = np.stack(e, 1), np.stack(c, 1)
    if life > yrs:
        e = np.concatenate([e, np.repeat(e[:, -1:], life - yrs, 1)], 1)
        c = np.concatenate([c, np.repeat(c[:, -1:], life - yrs, 1)], 1)
    return e, c


def size_system(kwh_day: float, night_share: float, peak_kw: float, ghi_month: list[float], a=ASSUMPTIONS) -> dict:
    ghi_design = min(ghi_month)
    pv = kwh_day / (ghi_design * a["performance_ratio"])
    batt = kwh_day * night_share / (a["battery_dod"] * a["battery_efficiency"])
    return {"pv_kwp": pv, "battery_kwh": batt, "inverter_kw": peak_kw * a["inverter_margin"],
            "design_ghi": ghi_design, "deliverable_kwh_yr": pv * float(np.mean(ghi_month)) * a["performance_ratio"] * 365}


def npv(rate, flows):
    """flows (n, T+1); rate scalar or (n,)"""
    t = np.arange(flows.shape[1])
    r = np.asarray(rate, float).reshape(-1, 1)
    return (flows / (1 + r) ** t).sum(axis=1)


def irr(flows: np.ndarray, lo=-0.95, hi=1.5, it=60) -> np.ndarray:
    lo_a, hi_a = np.full(flows.shape[0], lo), np.full(flows.shape[0], hi)
    f_lo = npv(lo_a, flows)
    for _ in range(it):
        mid = (lo_a + hi_a) / 2
        f_mid = npv(mid, flows)
        same = np.sign(f_mid) == np.sign(f_lo)
        lo_a = np.where(same, mid, lo_a)
        f_lo = np.where(same, f_mid, f_lo)
        hi_a = np.where(same, hi_a, mid)
    out = (lo_a + hi_a) / 2
    out[npv(np.full(flows.shape[0], lo), flows) * npv(np.full(flows.shape[0], hi), flows) > 0] = np.nan
    return out


def project_cashflows(energy, conn, size, capex, tariff, a=ASSUMPTIONS):
    served = np.minimum(energy, size["deliverable_kwh_yr"])
    revenue = served * tariff * a["collection_rate"]
    opex = conn * OPEX_PER_CUSTOMER_YR
    cfads = revenue - opex
    return served, revenue, opex, cfads


def debt_service(principal, a=ASSUMPTIONS):
    """Annual payment after the grace period (interest capitalised during grace)."""
    r, n, g = a["debt_rate"], int(a["debt_tenor"]), int(a["debt_grace_years"])
    return principal * (1 + r) ** g * r / (1 - (1 + r) ** -(n - g))


def debt_capacity(cfads: np.ndarray, pctile: float, a=ASSUMPTIONS) -> float:
    """Largest annuity loan whose DSCR stays >= covenant every year on the given cash-flow percentile path."""
    r, n, g = a["debt_rate"], int(a["debt_tenor"]), int(a["debt_grace_years"])
    cf = np.percentile(cfads[:, g:n], pctile, axis=0).min()
    return max(cf / a["dscr_covenant"], 0.0) * (1 - (1 + r) ** -(n - g)) / r / (1 + r) ** g


def stress_test(draws, feat, region: str, profile: dict, a=None, uplift: float = 1.0) -> dict:
    a = {**ASSUMPTIONS, **(a or {})}
    life = int(a["life_years"])
    energy, conn = annual_paths(draws, life, uplift)
    y3 = energy[:, SIZE_YEAR - 1]
    tariff = TARIFF[region]
    night = sum(v for h, v in enumerate(profile["total_kw"]) if h < 7 or h >= 18) / max(sum(profile["total_kw"]), 1e-9)
    ghi = feat["solar"]["ghi_monthly"]
    peak_per_kwhday = profile["peak_kw"] / max(sum(profile["total_kw"]), 1e-9)

    disc = (1 + a["hurdle_irr"]) ** -np.arange(1, life + 1)
    crf = a["hurdle_irr"] / (1 - (1 + a["hurdle_irr"]) ** -life)
    c50 = np.median(conn, axis=0)
    n_conn = max(float(np.median(conn[:, SIZE_YEAR - 1])), 1)

    def cost_of_power(capex, served):
        """Annualised CAPEX at the hurdle rate + OPEX, per kWh served, on the P50 path."""
        return (capex * crf + float(np.mean(c50)) * OPEX_PER_CUSTOMER_YR) / float(np.mean(np.median(served, 0)))

    def tariff_needed(capex, served, grant_usd=0.0):
        """Tariff that earns the hurdle IRR on the P50 path (revenue is linear in tariff)."""
        e = np.median(served, 0)
        grant_usd = min(grant_usd, capex)
        return ((capex - grant_usd) + (c50 * OPEX_PER_CUSTOMER_YR * disc).sum()) / ((e * a["collection_rate"] * disc).sum())

    tenor, grace = int(a["debt_tenor"]), int(a["debt_grace_years"])

    def breach_prob(cfads, principal):
        if principal <= 0:
            return 0.0
        return float(np.mean((cfads[:, grace:tenor] / debt_service(principal, a)).min(1) < a["dscr_covenant"]))

    def grant_needed(cfads, capex):
        """Share of CAPEX a grant must cover so the project earns the hurdle IRR, per draw."""
        return np.clip(1 - (cfads * disc).sum(1) / capex, 0, 1)

    def evaluate(kwh_yr_size, grant=None):
        kwh_day = kwh_yr_size / 365
        size = size_system(kwh_day, night, kwh_day * peak_per_kwhday, ghi, a)
        capex = size["pv_kwp"] * CAPEX_PER_KWP[region]
        served, revenue, opex, cfads = project_cashflows(energy, conn, size, capex, tariff, a)
        g_need = grant_needed(cfads, capex)
        g = float(np.median(g_need)) if grant is None else grant
        invest = capex * (1 - g)
        proj = np.concatenate([np.full((energy.shape[0], 1), -invest), cfads], 1)
        p_irr = irr(proj)
        debt = {lab: min(debt_capacity(cfads, pc, a), invest) for lab, pc in (("p90", 10), ("p50", 50))}
        principal = debt[a["debt_sizing"]]
        ds = debt_service(principal, a)
        dscr = cfads[:, grace:tenor] / ds if ds > 0 else np.full((energy.shape[0], tenor - grace), np.nan)
        breach = {lab: breach_prob(cfads, v) for lab, v in debt.items()}
        unserved = 1 - served.sum(1) / energy.sum(1)
        return dict(size=size, capex=capex, p_irr=p_irr, unserved=unserved, cfads=cfads, served=served,
                    ds=ds, grant=g, g_need=g_need, invest=invest, principal=principal, dscr=dscr, debt=debt, breach=breach)

    q = {"p90": np.percentile(y3, 10), "p50": np.percentile(y3, 50), "p10": np.percentile(y3, 90)}
    options = {}
    # Grant fixed at what a P50-sized system needs, so the sizing options are comparable
    base = evaluate(q["p50"], a["grant_share"])
    for lab, v in q.items():
        ev = evaluate(v, base["grant"])
        size, capex, p_irr, unserved = ev["size"], ev["capex"], ev["p_irr"], ev["unserved"]
        options[lab] = {
            "sized_on_kwh_month": v / 12, "pv_kwp": size["pv_kwp"], "battery_kwh": size["battery_kwh"],
            "inverter_kw": size["inverter_kw"], "capex_usd": capex,
            "irr_p50": float(np.nanmedian(p_irr)), "irr_p90": float(np.nanpercentile(p_irr, 10)),
            "prob_irr_below_hurdle": float(np.mean(np.nan_to_num(p_irr, nan=-1) < a["hurdle_irr"])),
            "prob_dscr_breach": ev["breach"][a["debt_sizing"]], "debt_usd": ev["principal"],
            "debt_p50_usd": ev["debt"]["p50"], "prob_dscr_breach_if_p50_debt": ev["breach"]["p50"],
            "unserved_share_median": float(np.median(unserved)),
            "unserved_share_p10_demand": float(np.percentile(unserved, 90)),
            "cost_of_power_usd_kwh": cost_of_power(capex, ev["served"]),
            "tariff_with_rbf_usd_kwh": tariff_needed(capex, ev["served"], RBF_GRANT_PER_CONNECTION[1] * n_conn),
        }

    # Recommended: size on P50, stress across all draws
    ev = base
    size, capex, p_irr, unserved, cfads, ds = (ev[k] for k in ("size", "capex", "p_irr", "unserved", "cfads", "ds"))
    p_breach = ev["breach"][a["debt_sizing"]]
    # if debt were sized on P50 demand instead: how often, and below what demand, the covenant breaks
    p50b = ev["breach"]["p50"]
    breakeven = float(np.percentile(y3, 100 * p50b)) / 12 if 0 < p50b < 1 else None
    safe_debt = ev["debt"]["p90"]
    req_tariff = tariff_needed(capex, ev["served"])
    hh_kwh = float(np.median(draws.q["household"][:, 36])) * uplift if "household" in draws.q else None
    lcoe = cost_of_power(capex, ev["served"])
    gpc = ev["grant"] * capex / n_conn
    out = {
        "region_tariff_usd_kwh": tariff, "capex_per_kwp_usd": CAPEX_PER_KWP[region],
        "opex_per_customer_usd_yr": OPEX_PER_CUSTOMER_YR, "assumptions": a,
        "night_share": night, "options": options, "recommended": "p50",
        "irr_distribution": {k: float(np.nanpercentile(p_irr, v)) for k, v in (("p90", 10), ("p50", 50), ("p10", 90))},
        "irr_histogram": np.histogram(np.clip(np.nan_to_num(p_irr, nan=-0.2), -0.2, 0.5), bins=28, range=(-0.2, 0.5))[0].tolist(),
        "prob_dscr_breach": p_breach, "debt_sized_on": a["debt_sizing"],
        "debt_p50_usd": ev["debt"]["p50"], "prob_dscr_breach_if_p50_debt": p50b,
        "breach_below_kwh_month": breakeven,
        "breach_percentile_label": f"P{round(100 * (1 - p50b))}" if 0 < p50b < 1 else None,
        "debt_service_usd_yr": ds, "debt_planned_usd": ev["principal"], "safe_debt_p90_usd": safe_debt,
        "grant_share_used": ev["grant"], "grant_usd": ev["grant"] * capex, "capex_usd": capex,
        "grant_needed": {"p90_demand": float(np.percentile(ev["g_need"], 90)), "p50_demand": float(np.median(ev["g_need"])),
                         "p10_demand": float(np.percentile(ev["g_need"], 10))},
        "dscr_years": list(range(grace + 1, tenor + 1)),
        "dscr_by_year_p50": np.nan_to_num(np.median(ev["dscr"], 0)).tolist(),
        "dscr_by_year_p90": np.nan_to_num(np.percentile(ev["dscr"], 10, 0)).tolist(),
        "grant_per_connection_usd": gpc,
        "rbf_benchmark_per_connection_usd": RBF_GRANT_PER_CONNECTION,
        "rbf_fit": "within" if gpc <= RBF_GRANT_PER_CONNECTION[1] else "above",
        "capex_per_connection_usd": capex / n_conn, "amda_capex_per_connection_usd": CAPEX_PER_CONNECTION[region],
        "lcoe_usd_kwh": lcoe, "uplift": uplift,
        "tariff_with_rbf_usd_kwh": tariff_needed(capex, ev["served"], RBF_GRANT_PER_CONNECTION[1] * n_conn),
        "cfads_by_year": {k: np.percentile(cfads[:, :10], q, 0).tolist() for k, q in (("p90", 10), ("p50", 50), ("p10", 90))},
        "first_year_p90_covers_opex": next((y + 1 for y in range(cfads.shape[1]) if np.percentile(cfads[:, y], 10) > 0), None),
        "required_tariff_usd_kwh": float(req_tariff),
        "affordability": {"hh_kwh_month_y3_p50": hh_kwh, "hh_bill_usd_month": None if hh_kwh is None else hh_kwh * tariff,
                          "amda_residential_arpu_usd_month": ARPU_HH[region]},
    }
    return out
