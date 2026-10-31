"""Population priors for growth parameters.

Shapes (how fast connections and consumption ramp) are learned from metered panels.
Levels (uptake ceiling R, mature consumption Q) come either from metered panels
("regional prior", i.e. Demand Bureau data) or from the AMDA 2024 benchmarks
("pan-African prior").
"""
from __future__ import annotations

import numpy as np

from .drc import SitePanel
from .forecast import LogNormal, Normal, SegmentPrior
from .growth import fit_per_conn, fit_uptake

# AMDA, Benchmarking Africa's Minigrids Report 2024, Table 7 (kWh/month per user)
AMDA_ACPU = {
    "east_south": {"household": 6.0, "sme": 13.1},
    "west_central": {"household": 8.1, "sme": 39.8},
}
# AMDA 2024 section 6.3: average tariffs (US$/kWh)
AMDA_TARIFF = {"east_south": 0.40, "west_central": 0.25}
# Brief 03 / ESMAP: per-customer demand varies roughly sevenfold across sites (5-35 kWh).
# A lognormal whose P10-P90 range spans 7x has sigma = ln(7) / (2 * 1.2816).
SIGMA_SEVENFOLD = float(np.log(7) / (2 * 1.2816))

# Minimum prior spreads. With only a handful of metered sites the between-site spread
# is poorly estimated, so it is floored. Set so that leave-one-site-out P90-P10
# coverage on the village-scale sites is ~80% (calibration, disclosed in the report).
FLOORS = {"R": 0.60, "k": 0.60, "t0": 15.0, "Q": 0.50, "a": 0.25, "tau": 0.80}
# Observation noise (log scale) used when updating on metered months. Monthly residuals
# around the fitted curves are strongly autocorrelated in the DRC panel (lag-1 rho 0.93 for
# connections, 0.66 for kWh per connection), so n consecutive months carry far less than n
# independent pieces of evidence. The per-month noise (0.30 / 0.35) is inflated by the AR(1)
# effective-sample-size factor sqrt((1+rho)/(1-rho)) = 5.3 / 2.2.
OBS_SIGMA = {"conn": 1.60, "q": 0.77}
# Month-to-month noise added when scoring individual metered months.
MONTH_NOISE = 0.20


def fit_site(p: SitePanel) -> dict[str, dict[str, float]]:
    out = {}
    for seg, conn, pot, kwh in (
        ("household", p.conn_hh, p.pot_hh, p.kwh_hh),
        ("sme", p.conn_sme, p.pot_sme, p.kwh_sme),
    ):
        u, _ = fit_uptake(p.months, conn / pot)
        c, sd = fit_per_conn(p.months, kwh, conn)
        out[seg] = {**u, **c, "resid_sd": sd}
    return out


def _lognormal(vals, floor):
    v = np.log(np.asarray(vals, float))
    sd = float(np.std(v, ddof=1)) if v.size > 1 else 0.0
    return LogNormal(float(np.exp(v.mean())), max(sd, floor))


def _normal(vals, floor):
    v = np.asarray(vals, float)
    sd = float(np.std(v, ddof=1)) if v.size > 1 else 0.0
    return Normal(float(v.mean()), max(sd, floor))


def pooled_prior(fits: list[dict], seg: str) -> SegmentPrior:
    g = lambda key: [f[seg][key] for f in fits]
    return SegmentPrior(
        R=_lognormal(g("R"), FLOORS["R"]),
        k=_lognormal(g("k"), FLOORS["k"]),
        t0=_normal(g("t0"), FLOORS["t0"]),
        Q=_lognormal(g("Q"), FLOORS["Q"]),
        a=_normal(g("a"), FLOORS["a"]),
        tau=_lognormal(g("tau"), FLOORS["tau"]),
    )


def benchmark_prior(fits: list[dict], seg: str, region: str) -> SegmentPrior:
    """Shapes from metered panels; consumption level from AMDA with the sevenfold spread."""
    sp = pooled_prior(fits, seg)
    sp.Q = LogNormal(AMDA_ACPU[region][seg], SIGMA_SEVENFOLD)
    return sp
