"""Monte Carlo demand forecast with Bayesian updating from metered months.

A site is described by its potential customers per segment and a prior over the
growth parameters of each segment. We draw many parameter sets, simulate the
monthly path of connections and consumption for each draw, and summarise the
distribution. When metered months are available, draws are re-weighted by how
well they explain the observations (importance sampling) and resampled.

Percentile naming follows the project-finance convention used in solar/wind
energy-yield reports: P90 is the value exceeded with 90% probability
(conservative), P50 the median, P10 the optimistic case.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


SEGMENTS = ("household", "sme")


@dataclass
class LogNormal:
    median: float
    sigma: float

    def draw(self, rng, n):
        return self.median * np.exp(self.sigma * rng.standard_normal(n))


@dataclass
class Normal:
    mean: float
    sd: float

    def draw(self, rng, n):
        return self.mean + self.sd * rng.standard_normal(n)


@dataclass
class SegmentPrior:
    R: LogNormal        # uptake ceiling (share of potential customers), clipped to <= 0.98
    k: LogNormal        # ramp speed (1/month)
    t0: Normal          # ramp midpoint (months)
    Q: LogNormal        # mature kWh/month per connection
    a: Normal           # initial shortfall of consumption vs mature (0..0.95)
    tau: LogNormal      # consumption ramp time constant (months)


@dataclass
class Anchor:
    kind: str
    kwh_month: float
    sigma: float = 0.35          # uncertainty on the anchor's consumption
    connect_month: float = 3.0   # anchors are typically signed before commissioning


@dataclass
class SiteSpec:
    potentials: dict[str, LogNormal]           # potential customers per segment (uncertain)
    priors: dict[str, SegmentPrior]
    anchors: list[Anchor] = field(default_factory=list)
    horizon: int = 60


@dataclass
class Draws:
    months: np.ndarray
    conn: dict[str, np.ndarray]        # (n, T)
    q: dict[str, np.ndarray]           # (n, T) kWh/month per connection
    energy: dict[str, np.ndarray]      # (n, T) kWh/month by segment (incl. 'anchors')
    params: dict[str, np.ndarray]      # flat parameter arrays for explanation
    weights: np.ndarray | None = None

    @property
    def total(self) -> np.ndarray:
        return sum(self.energy.values())

    @property
    def n(self) -> int:
        return self.total.shape[0]


def ramp_shape(t, k, t0):
    """Logistic uptake share relative to the ceiling R.

    Not forced to zero at commissioning: many sites sign customers up before
    commissioning (Mutwanga had 11% of households connected in month 1), which a
    negative or small t0 represents.
    """
    t = np.asarray(t, float)
    return np.clip(1.0 / (1.0 + np.exp(-k * (t - t0))), 1e-6, 1.0)


def consumption_shape(t, a, tau):
    return 1.0 - a * np.exp(-np.asarray(t, float) / tau)


def simulate(spec: SiteSpec, n: int = 20000, seed: int = 7) -> Draws:
    rng = np.random.default_rng(seed)
    t = np.arange(0, spec.horizon + 1, dtype=float)
    conn, q, energy, params = {}, {}, {}, {}
    for seg in SEGMENTS:
        if seg not in spec.priors:
            continue
        p = spec.priors[seg]
        pot = spec.potentials[seg].draw(rng, n)
        R = np.clip(p.R.draw(rng, n), 0.005, 0.98)
        k = p.k.draw(rng, n)
        t0 = p.t0.draw(rng, n)
        Q = p.Q.draw(rng, n)
        a = np.clip(p.a.draw(rng, n), 0.0, 0.95)
        tau = p.tau.draw(rng, n)
        c = (pot * R)[:, None] * ramp_shape(t[None, :], k[:, None], t0[:, None])
        qq = Q[:, None] * consumption_shape(t[None, :], a[:, None], tau[:, None])
        conn[seg], q[seg], energy[seg] = c, qq, c * qq
        for name, arr in dict(pot=pot, R=R, k=k, t0=t0, Q=Q, a=a, tau=tau).items():
            params[f"{seg}.{name}"] = arr
        params[f"{seg}._level_prior_conn"] = np.array([np.log(spec.potentials[seg].median) + np.log(p.R.median),
                                                      np.hypot(spec.potentials[seg].sigma, p.R.sigma)])
        params[f"{seg}._level_prior_q"] = np.array([np.log(p.Q.median), p.Q.sigma])
    if spec.anchors:
        e = np.zeros((n, t.size))
        for i, an in enumerate(spec.anchors):
            kwh = an.kwh_month * np.exp(an.sigma * rng.standard_normal(n))
            on = (t >= an.connect_month).astype(float)
            e += kwh[:, None] * on[None, :]
            params[f"anchor{i}.{an.kind}"] = kwh
        energy["anchors"] = e
    return Draws(months=t, conn=conn, q=q, energy=energy, params=params)


def _tempered_weights(loglik: np.ndarray, min_ess: float) -> tuple[np.ndarray, float, float]:
    """Importance weights, tempered (likelihood ** lam) only if the ESS would collapse."""
    lam = 1.0
    for _ in range(40):
        w = np.exp(lam * (loglik - loglik.max()))
        w /= w.sum()
        ess = float(1.0 / np.sum(w ** 2))
        if ess >= min_ess:
            return w, ess, lam
        lam *= 0.7
    return w, ess, lam


def condition(d: Draws, observed: dict[str, np.ndarray], obs_months: np.ndarray,
              sigma: dict[str, float] | None = None, seed: int = 11,
              min_ess: float = 300.0) -> tuple[Draws, dict]:
    """Bayesian update from metered months (Rao-Blackwellised importance sampling).

    Each block is  log y(t) = L + g(t; shape) + noise,  where the level L is
    log(pot * R) for connections or log(Q) for consumption, and g is the log of the
    normalised ramp. Given the shape parameters the posterior of L is Gaussian and
    exact, so we (1) weight each prior draw of the shape by its marginal likelihood
    with L integrated out, (2) resample shapes, (3) sample L from its exact posterior.
    Blocks (connections / consumption, per segment) are independent a priori and the
    likelihood factorises, so they are updated separately.

    observed keys: 'conn.household', 'conn.sme', 'q.household', 'q.sme'
    """
    sigma = sigma or {"conn": 0.15, "q": 0.25}
    rng = np.random.default_rng(seed)
    t_all = d.months
    conn, q, params = dict(d.conn), dict(d.q), dict(d.params)
    diag = {}
    for key, obs in observed.items():
        kind, seg = key.split(".")
        if seg not in d.conn:
            continue
        obs = np.asarray(obs, float)
        m = np.isfinite(obs) & (obs > 0)
        if not m.any():
            continue
        tj = np.asarray(obs_months, float)[m]
        y = np.log(obs[m])
        P = d.params
        if kind == "conn":
            g_obs = np.log(ramp_shape(tj[None, :], P[f"{seg}.k"][:, None], P[f"{seg}.t0"][:, None]))
            mu0, s0 = P[f"{seg}._level_prior_conn"]
        else:
            g_obs = np.log(np.maximum(consumption_shape(tj[None, :], P[f"{seg}.a"][:, None], P[f"{seg}.tau"][:, None]), 1e-6))
            mu0, s0 = P[f"{seg}._level_prior_q"]
        s2, v0, nobs = sigma[kind] ** 2, s0 ** 2, y.size
        r = y[None, :] - g_obs - mu0
        sr = r.sum(axis=1)
        loglik = -0.5 * ((r ** 2).sum(axis=1) - v0 * sr ** 2 / (s2 + nobs * v0)) / s2
        w, ess, lam = _tempered_weights(loglik, min_ess)
        pick = rng.choice(d.n, size=d.n, replace=True, p=w)
        prec = 1.0 / v0 + nobs / s2
        post_mean = mu0 + (sr[pick] / s2) / prec
        L = post_mean + rng.standard_normal(d.n) / np.sqrt(prec)
        if kind == "conn":
            k_, t0_ = P[f"{seg}.k"][pick], P[f"{seg}.t0"][pick]
            pot = P[f"{seg}.pot"][pick]
            R = np.clip(np.exp(L) / pot, 0.005, 0.98)
            conn[seg] = (pot * R)[:, None] * ramp_shape(t_all[None, :], k_[:, None], t0_[:, None])
            params.update({f"{seg}.k": k_, f"{seg}.t0": t0_, f"{seg}.pot": pot, f"{seg}.R": R})
        else:
            a_, tau_ = P[f"{seg}.a"][pick], P[f"{seg}.tau"][pick]
            Q = np.exp(L)
            q[seg] = Q[:, None] * consumption_shape(t_all[None, :], a_[:, None], tau_[:, None])
            params.update({f"{seg}.a": a_, f"{seg}.tau": tau_, f"{seg}.Q": Q})
        diag[key] = {"ess": round(ess, 1), "temper": round(lam, 3), "n_obs": int(nobs),
                     "level_prior": round(float(np.exp(mu0)), 2),
                     "level_posterior_median": round(float(np.exp(np.median(L))), 2)}
    energy = {seg: conn[seg] * q[seg] for seg in conn}
    if "anchors" in d.energy:
        energy["anchors"] = d.energy["anchors"]
    return Draws(months=d.months, conn=conn, q=q, energy=energy, params=params), diag


def with_month_noise(arr: np.ndarray, sigma: float, seed: int = 3) -> np.ndarray:
    """Predictive distribution of individual metered months (adds month-to-month noise)."""
    if sigma <= 0:
        return arr
    rng = np.random.default_rng(seed)
    return arr * np.exp(sigma * rng.standard_normal(arr.shape) - 0.5 * sigma ** 2)


def exceedance(arr: np.ndarray, axis: int = 0) -> dict[str, np.ndarray]:
    """P90 (exceeded 90% of the time), P50, P10 along the draw axis."""
    return {
        "p90": np.percentile(arr, 10, axis=axis),
        "p50": np.percentile(arr, 50, axis=axis),
        "p10": np.percentile(arr, 90, axis=axis),
    }
