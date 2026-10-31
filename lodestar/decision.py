"""Decision backtest: what each sizing method would have cost on real metered demand.

For a held-out metered site we replay the actual monthly demand against three plans:
  desk      single build sized on a survey-style desk estimate (households counted x typical uptake x
            AMDA benchmark kWh), the status quo the brief describes
  lodestar  build at Lodestar's day-0 P50 (open data only), then add a module of 25% of the initial PV
            when the trailing 6 months of metered demand average more than 90% of capacity
            (at most one expansion per 12 months, 3-month lead time)
  hindsight single build sized on the site's actual year-3 demand (the unattainable ideal)
Unserved energy is valued as diesel a customer would burn instead (assumptions below).
"""
from __future__ import annotations

import numpy as np

from . import finance

MODULE_SHARE = 0.25          # each expansion adds 25% of the initial PV (assumption)
TRIGGER = 0.90               # expand when trailing-6-month mean demand > 90% of capacity (assumption)
WINDOW = 6
MIN_GAP = 12                 # months between expansions (assumption)
LEAD_MONTHS = 3              # months from trigger to commissioning (assumption)
KWH_PER_LITRE_DIESEL = 3.0   # small genset (assumption; typical 2.5-3.5)
KG_CO2_PER_LITRE = 2.68      # diesel combustion emission factor (IPCC 2006 default ~74.1 t CO2/TJ)
DIESEL_USD_PER_LITRE = 1.0   # assumption, order of magnitude for rural Africa


def _size(kwh_month, night, ghi, region):
    s = finance.size_system(kwh_month * 12 / 365, night, 0.0, ghi)
    return s["pv_kwp"], s["pv_kwp"] * finance.CAPEX_PER_KWP[region]


def replay(months, actual, kwp0, ghi, region, staged, a=finance.ASSUMPTIONS):
    kwh_per_kwp_month = float(np.mean(ghi)) * a["performance_ratio"] * 30.4
    kwp, pending, served, unserved, events, last = kwp0, [], 0.0, 0.0, [], -1e9
    cap_y3 = None
    for i, (m, d) in enumerate(zip(months, actual)):
        for due in [p for p in pending if p[0] <= m]:
            kwp += due[1]; pending.remove(due); events.append({"month": int(m), "added_kwp": due[1]})
        cap = kwp * kwh_per_kwp_month
        served += min(d, cap); unserved += max(d - cap, 0.0)
        if (staged and i >= WINDOW - 1 and not pending and m - last >= MIN_GAP
                and np.mean(actual[i - WINDOW + 1:i + 1]) > TRIGGER * cap):
            pending.append((m + LEAD_MONTHS, MODULE_SHARE * kwp0)); last = m
        if m <= 36:
            cap_y3 = kwp
    y3 = (months > 24) & (months <= 36)
    need_y3 = float(np.mean(actual[y3])) if y3.any() else float(np.mean(actual[-12:]))
    cap_kwh_y3 = cap_y3 * kwh_per_kwp_month
    idle = max(cap_kwh_y3 - need_y3, 0.0) / cap_kwh_y3
    capex = kwp * finance.CAPEX_PER_KWP[region]
    litres = unserved / KWH_PER_LITRE_DIESEL
    return {"initial_kwp": kwp0, "final_kwp": kwp, "capex_usd": capex, "expansions": events,
            "idle_capacity_share_y3": idle, "idle_capital_y3_usd": idle * cap_y3 * finance.CAPEX_PER_KWP[region],
            "unserved_share": unserved / max(served + unserved, 1e-9), "unserved_mwh": unserved / 1e3,
            "diesel_litres": litres, "diesel_usd": litres * DIESEL_USD_PER_LITRE,
            "co2_t": litres * KG_CO2_PER_LITRE / 1e3, "months": int(len(months)),
            "capex_per_mwh_served_usd": capex / max(served / 1e3, 1e-9)}


def backtest(months, actual, desk_kwh_month, lodestar_p50_kwh_month, night, ghi, region):
    y3 = (months > 24) & (months <= 36)
    hind = float(np.mean(actual[y3])) if y3.any() else float(np.mean(actual[-12:]))
    out = {}
    for name, kwh, staged in (("desk", desk_kwh_month, False), ("lodestar", lodestar_p50_kwh_month, True),
                              ("hindsight", hind, False)):
        kwp, _ = _size(kwh, night, ghi, region)
        out[name] = {"sized_on_kwh_month": kwh, **replay(months, actual, kwp, ghi, region, staged)}
    return out
