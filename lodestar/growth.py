"""Growth curves: connections ramp x consumption per connection.

    uptake(t) = R / (1 + exp(-k (t - t0)))          share of potential customers connected
    q(t)      = Q * (1 - a * exp(-t / tau))          kWh/month per connected customer
    E(t)      = sum_segments  N_pot * uptake(t) * q(t)
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares


def uptake(t, R, k, t0):
    return R / (1.0 + np.exp(-k * (np.asarray(t, float) - t0)))


def per_conn(t, Q, a, tau):
    return Q * (1.0 - a * np.exp(-np.asarray(t, float) / tau))


def fit_uptake(t, share):
    m = np.isfinite(share)
    t, y = t[m], share[m]
    x0 = [min(0.95, max(y.max() * 1.1, 0.02)), 0.15, max(6.0, t[np.argmax(y >= y.max() / 2)])]
    res = least_squares(
        lambda p: uptake(t, *p) - y, x0,
        bounds=([0.005, 0.01, -12.0], [1.0, 2.0, 120.0]), loss="soft_l1", f_scale=0.02,
    )
    return dict(zip(["R", "k", "t0"], res.x)), res


def fit_per_conn(t, q, weights=None):
    m = np.isfinite(q) & (q > 0)
    t, y = t[m], q[m]
    w = np.ones_like(y) if weights is None else np.sqrt(np.asarray(weights, float)[m])
    x0 = [np.median(y[-12:]) if len(y) > 12 else y.mean(), 0.5, 4.0]
    res = least_squares(
        lambda p: (np.log(per_conn(t, *p)) - np.log(y)) * w, x0,
        bounds=([0.5, 0.0, 0.3], [5000.0, 0.95, 60.0]), loss="soft_l1", f_scale=0.15,
    )
    resid = np.log(per_conn(t, *res.x)) - np.log(y)
    return dict(zip(["Q", "a", "tau"], res.x)), float(np.std(resid))
