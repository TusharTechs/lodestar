"""Lodestar's own unit economics: what it costs to run and what pays for it.

Measured: compute per report (timed in scripts/precompute.py) and payload size.
Cited: AMDA 2024 pipeline of 6,116 planned mini-grid sites; Nigeria's DARES targets 1,000+ mini-grids.
Proposed / assumed (labelled in the UI): prices, team cost, hosting.
"""
from __future__ import annotations

PIPELINE_SITES_AMDA = 6116          # AMDA 2024: sites planned by members (sec. 3.4)
DARES_TARGET_SITES = 1000           # AMDA 2024: DARES aims for over 1,000 mini-grids (Nigeria)
ESMAP_NEEDED_MINIGRIDS = 217_000    # ESMAP 2022 via Brief 03
ESMAP_COST_USD = 127e9

PRICE_REPORT_USD = 300.0            # proposed: Bankable Demand Report per site
PRICE_PORTFOLIO_USD_YR = 12_000.0   # proposed: portfolio screening for an RBF programme or DFI
TEAM_COST_USD_YR = 60_000.0         # assumption: two analyst-engineers based in Nairobi or Lagos
HOSTING_USD_YR = 25.0 * 12          # assumption: one small cloud instance
COMPUTE_USD_PER_HOUR = 0.05         # assumption: small cloud CPU


def summary(seconds_per_report: float, report_kb: float) -> dict:
    fixed = TEAM_COST_USD_YR + HOSTING_USD_YR
    per_report_compute = seconds_per_report / 3600 * COMPUTE_USD_PER_HOUR
    mg_cost = ESMAP_COST_USD / ESMAP_NEEDED_MINIGRIDS
    return {
        "measured": {"seconds_per_report": seconds_per_report, "report_kb_gzip": report_kb,
                     "compute_usd_per_report": per_report_compute},
        "proposed_prices": {"report_usd": PRICE_REPORT_USD, "portfolio_usd_yr": PRICE_PORTFOLIO_USD_YR},
        "assumed_costs": {"team_usd_yr": TEAM_COST_USD_YR, "hosting_usd_yr": HOSTING_USD_YR},
        "fixed_cost_usd_yr": fixed,
        "break_even_reports_yr": fixed / (PRICE_REPORT_USD - per_report_compute),
        "break_even_mix": {"portfolio_subscriptions": 3, "reports": max(0.0, (fixed - 3 * PRICE_PORTFOLIO_USD_YR) / PRICE_REPORT_USD)},
        "break_even_share_of_amda_pipeline": fixed / PRICE_REPORT_USD / PIPELINE_SITES_AMDA,
        "report_price_share_of_minigrid_cost": PRICE_REPORT_USD / mg_cost,
        "avg_minigrid_cost_usd": mg_cost,
        "pipeline": {"amda_planned_sites": PIPELINE_SITES_AMDA, "dares_target_sites": DARES_TARGET_SITES,
                     "esmap_needed_minigrids": ESMAP_NEEDED_MINIGRIDS},
    }
