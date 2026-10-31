"""Leave-one-site-out validation on the North Kivu (DRC) metered mini-grid panel.

For each held-out site:
  * Day 0: forecast monthly site energy with NO metered data from that site.
    Consumption levels come from AMDA 2024 pan-African benchmarks; ramp shapes come
    from the OTHER metered sites only; potential customers from the census.
  * Learning curve: update the same forecast with the site's first k metered months
    (k = 3, 6, 12) and score only the months after k.
Metrics: WAPE (sum|err| / sum actual), error on cumulative energy, and the share of
months whose actual falls inside the P90-P10 band (target ~80%).
Baselines: flat desk estimate (benchmark kWh x pooled uptake from day 1) and, for the
learning curve, persistence of the last observed month.

Writes data/derived/validation.json and docs/validation/drc_backtest.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lodestar.drc import load_clients, load_panels  # noqa: E402
from lodestar.forecast import LogNormal, SiteSpec, condition, exceedance, simulate, with_month_noise  # noqa: E402
from lodestar.priors import AMDA_ACPU, MONTH_NOISE, OBS_SIGMA, benchmark_prior, fit_site  # noqa: E402

REGION = "west_central"          # AMDA groups Central Africa with West Africa
LEARN_MONTHS = [3, 6, 12]
N_DRAWS = 40000
OUT_JSON = ROOT / "data" / "derived" / "validation.json"
FIG_DIR = ROOT / "docs" / "validation"
NOTES = {
    "Goma": "Urban network (~16,700 potential customers in a city of ~2M). Outside the village mini-grid scope the tool targets; reported for transparency.",
    "Mutwanga": "Consumption fell ~82% around month 22 after an armed-conflict shock documented by the source paper (M23). No demand model can foresee this; it is why bankability is stress-tested on the low (P90) case.",
    "Lubero": "Town-scale site; 38 months of data.",
}


def spec_for(panel, priors):
    return SiteSpec(
        potentials={"household": LogNormal(panel.pot_hh, 0.05), "sme": LogNormal(panel.pot_sme, 0.05)},
        priors=priors,
        horizon=int(panel.months.max()),
    )


def year_metrics(t, actual, tot, start):
    """Error and band coverage of annual energy for the 3 years after `start` (sizing horizon)."""
    out = []
    for y in range(3):
        w = (t > start + 12 * y) & (t <= start + 12 * (y + 1))
        if w.sum() < 10:
            continue
        ys, act = tot[:, w].sum(1), actual[w].sum()
        p90, p50, p10 = np.percentile(ys, [10, 50, 90])
        out.append({"year": y + 1, "actual_mwh": act / 1e3, "p50_mwh": p50 / 1e3, "p90_mwh": p90 / 1e3,
                    "p10_mwh": p10 / 1e3, "error": float((p50 - act) / act), "inside_band": bool(p90 <= act <= p10)})
    return out


def metrics(t, actual, bands, start, tot=None):
    m = (t > start) & (actual > 0)
    a, p50 = actual[m], bands["p50"][m]
    inside = (a >= bands["p90"][m]) & (a <= bands["p10"][m])
    win = m & (t <= start + 36)
    return {
        "wape": float(np.sum(np.abs(p50 - a)) / np.sum(a)),
        "coverage_p90_p10": float(np.mean(inside)),
        "cum36_error": float((bands["p50"][win].sum() - actual[win].sum()) / actual[win].sum()),
        "cum36_actual_inside_band": bool(bands["p90"][win].sum() <= actual[win].sum() <= bands["p10"][win].sum()),
        "median_band_ratio_p10_over_p90": float(np.median(bands["p10"][m] / np.maximum(bands["p90"][m], 1e-9))),
        "n_months_scored": int(m.sum()),
        **({"years": year_metrics(t, actual, tot, start)} if tot is not None else {}),
    }


def at(draws, t):
    return draws.total[:, np.searchsorted(draws.months, t)]


def bands_at(draws, t):
    """Predictive bands for individual metered months (model + month-to-month noise)."""
    return exceedance(with_month_noise(at(draws, t), MONTH_NOISE))


def main():
    panels = load_panels()
    fits = {n: fit_site(p) for n, p in panels.items()}
    out = {"method": {
        "data": "Lunanga, Stoop, Verpoorten & Desbureaux (2026), Energy Economics; Harvard Dataverse doi:10.7910/DVN/KPDREF (CC0)",
        "protocol": "Leave-one-site-out. Day-0 forecasts use no metered data from the held-out site.",
        "day0_inputs": "Potential customers (census) + AMDA 2024 consumption benchmarks (West & Central Africa) + ramp shapes fitted on the other metered sites.",
        "percentiles": "P90 = exceeded with 90% probability (conservative); P10 = optimistic.",
        "metrics": "WAPE = sum|P50 - actual| / sum actual over scored months; coverage = share of months with actual inside P90-P10 (target ~0.8); cum36 = error of P50 on cumulative energy over the next 36 months.",
    }, "sites": {}, "notes": NOTES, "summary": {}}
    paths = {}
    for name, panel in panels.items():
        train = [fits[o] for o in panels if o != name]
        prior = {s: benchmark_prior(train, s, REGION) for s in ("household", "sme")}
        d0 = simulate(spec_for(panel, prior), n=N_DRAWS, seed=1)
        t, actual = panel.months, panel.total_kwh
        b0 = bands_at(d0, t)
        site = {"potential_customers": {"household": panel.pot_hh, "sme": panel.pot_sme},
                "months_observed": int(t.max()), "fitted_parameters": fits[name],
                "day0": metrics(t, actual, b0, 0, at(d0, t)), "learning": {}}
        R_hh = np.exp(np.mean([np.log(f["household"]["R"]) for f in train]))
        R_sme = np.exp(np.mean([np.log(f["sme"]["R"]) for f in train]))
        # Desk-study baseline: AMDA benchmark kWh x mature uptake of the other sites, flat from day 1
        flat = (panel.pot_hh * R_hh * AMDA_ACPU[REGION]["household"]
                + panel.pot_sme * R_sme * AMDA_ACPU[REGION]["sme"]) * np.ones_like(t)
        m0 = actual > 0
        site["baseline_flat_wape"] = float(np.sum(np.abs(flat[m0] - actual[m0])) / np.sum(actual[m0]))
        site["baseline_flat_years"] = [{"year": y + 1, "error": float((flat[w].sum() - actual[w].sum()) / actual[w].sum())}
                                       for y in range(3) for w in [(t > 12 * y) & (t <= 12 * (y + 1))] if w.sum() >= 10]
        paths[name] = {"months": t.tolist(), "actual": actual.tolist(),
                       "day0": {k: v.tolist() for k, v in b0.items()}}
        for k in LEARN_MONTHS:
            om = t[t <= k]
            n = len(om)
            obs = {"conn.household": panel.conn_hh[:n], "conn.sme": panel.conn_sme[:n],
                   "q.household": panel.kwh_hh[:n], "q.sme": panel.kwh_sme[:n]}
            dk, diag = condition(d0, obs, om, sigma=OBS_SIGMA)
            bk = bands_at(dk, t)
            last = actual[n - 1]
            mm = (t > k) & (actual > 0)
            site["learning"][str(k)] = {
                **metrics(t, actual, bk, k, at(dk, t)),
                "baseline_persistence_wape": float(np.sum(np.abs(last - actual[mm])) / np.sum(actual[mm])),
                "update_diagnostics": diag,
            }
            paths[name][f"after_{k}"] = {kk: v.tolist() for kk, v in bk.items()}
        out["sites"][name] = site

    # V1b: end-to-end from open data only (footprints + OpenStreetMap), no census, no own meters.
    # Footprint->customer ratios and growth shapes come from the OTHER sites only.
    from lodestar import village as V
    feats = {n: json.loads((ROOT / "data" / "sites" / "features" / f"cd-nk-{n.lower()}.json").read_text())
             for n in ("Lubero", "Mutwanga")}
    out["end_to_end"] = {}
    for name in feats:
        other = [o for o in feats if o != name][0]
        po, fo = panels[other], feats[other]["buildings"]
        spec = V.build_spec(feats[name], fits=[fits[o] for o in panels if o != name], horizon=int(panels[name].months.max()),
                            hh_ratio=po.pot_hh / (fo["n_residential"] + fo["n_small"]), sme_ratio=po.pot_sme / fo["n_large"])
        de = simulate(spec, n=N_DRAWS, seed=2)
        panel = panels[name]
        t, actual = panel.months, panel.total_kwh
        out["end_to_end"][name] = {
            **metrics(t, actual, bands_at(de, t), 0, at(de, t)),
            "potential_from_footprints": {s: round(spec.potentials[s].median) for s in spec.potentials},
            "potential_census": {"household": panel.pot_hh, "sme": panel.pot_sme},
            "ratios_from": other,
        }
        paths[name]["end_to_end"] = {k: v.tolist() for k, v in bands_at(de, t).items()}
        out["end_to_end"][name]["learning"] = {}
        for k in LEARN_MONTHS:
            n = int((t <= k).sum())
            obs = {"conn.household": panel.conn_hh[:n], "conn.sme": panel.conn_sme[:n],
                   "q.household": panel.kwh_hh[:n], "q.sme": panel.kwh_sme[:n]}
            dk, _ = condition(de, obs, t[:n], sigma=OBS_SIGMA)
            mm = (t > k) & (actual > 0)
            out["end_to_end"][name]["learning"][str(k)] = {
                **metrics(t, actual, bands_at(dk, t), k, at(dk, t)),
                "baseline_persistence_wape": float(np.sum(np.abs(actual[n - 1] - actual[mm])) / np.sum(actual[mm]))}
            paths[name][f"e2e_after_{k}"] = {kk: v.tolist() for kk, v in bands_at(dk, t).items()}
    # Decision backtest: replay actual monthly demand (first 36 months) against a single desk build and
    # Lodestar's plan (build at open-data day-0 P50, expand on sustained metered demand).
    from lodestar import decision as DB
    out["decision_backtest"] = {}
    for name in feats:
        panel = panels[name]
        train = [fits[o] for o in panels if o != name]
        R_hh = np.exp(np.mean([np.log(f["household"]["R"]) for f in train]))
        R_sme = np.exp(np.mean([np.log(f["sme"]["R"]) for f in train]))
        desk = panel.pot_hh * R_hh * AMDA_ACPU[REGION]["household"] + panel.pot_sme * R_sme * AMDA_ACPU[REGION]["sme"]
        other = [o for o in feats if o != name][0]
        po, fo = panels[other], feats[other]["buildings"]
        spec = V.build_spec(feats[name], fits=[fits[o] for o in panels if o != name], horizon=36,
                            hh_ratio=po.pot_hh / (fo["n_residential"] + fo["n_small"]), sme_ratio=po.pot_sme / fo["n_large"])
        p50 = float(np.median(V.year_energy(simulate(spec, n=N_DRAWS, seed=2), 3))) / 12
        prof = V.hourly_profile(simulate(spec, n=4000, seed=3), feats[name])["total_kw"]
        night = sum(v for h, v in enumerate(prof) if h < 7 or h >= 18) / sum(prof)
        m = panel.months <= 36
        r = DB.backtest(panel.months[m], panel.total_kwh[m], desk, p50, night, feats[name]["solar"]["ghi_monthly"], REGION)
        h = r["hindsight"]["final_kwp"]
        for k in r:
            r[k]["kwp_vs_hindsight_y3"] = r[k]["final_kwp"] / h - 1 if k != "hindsight" else 0.0
        out["decision_backtest"][name] = r
    dbt = out["decision_backtest"]
    out["summary"]["decision_backtest"] = {
        k: {"abs_capacity_gap_kwp": float(sum(abs(v[k]["final_kwp"] - v["hindsight"]["final_kwp"]) for v in dbt.values())),
            "capex_usd": float(sum(v[k]["capex_usd"] for v in dbt.values())),
            "idle_capital_y3_usd": float(sum(v[k]["idle_capital_y3_usd"] for v in dbt.values())),
            "unserved_mwh": float(sum(v[k]["unserved_mwh"] for v in dbt.values())),
            "diesel_litres": float(sum(v[k]["diesel_litres"] for v in dbt.values()))}
        for k in ("desk", "lodestar", "hindsight")}
    e2e = out["end_to_end"]
    out["summary"]["end_to_end_village"] = {
        "annual_abs_error": float(np.mean([abs(y["error"]) for s in e2e.values() for y in s["years"]])),
        "annual_coverage": float(np.mean([y["inside_band"] for s in e2e.values() for y in s["years"]])),
        "monthly_coverage": float(np.mean([s["coverage_p90_p10"] for s in e2e.values()])),
        "wape": float(np.mean([s["wape"] for s in e2e.values()])),
        "n_site_years": int(sum(len(s["years"]) for s in e2e.values())),
        **{f"after_{k}m_wape": float(np.mean([s["learning"][str(k)]["wape"] for s in e2e.values()])) for k in LEARN_MONTHS},
        **{f"after_{k}m_coverage": float(np.mean([s["learning"][str(k)]["coverage_p90_p10"] for s in e2e.values()])) for k in LEARN_MONTHS},
        **{f"persistence_after_{k}m_wape": float(np.mean([s["learning"][str(k)]["baseline_persistence_wape"] for s in e2e.values()])) for k in LEARN_MONTHS},
    }

    clients = load_clients()
    spread = {}
    for name in panels:
        for seg in ("household", "sme"):
            own = clients[(clients.site == name) & (clients.segment == seg) & (clients.kwh_client_av > 0)].kwh_client_av
            other = clients[(clients.site != name) & (clients.segment == seg) & (clients.kwh_client_av > 0)]
            sig = float(np.mean([np.log(g.kwh_client_av).std() for _, g in other.groupby("site")]))
            spread.setdefault(name, {})[seg] = {
                "actual_p10_over_p90_customer_ratio": float(np.percentile(own, 90) / np.percentile(own, 10)),
                "predicted_from_other_sites": float(np.exp(2 * 1.2816 * sig)),
                "n_clients": int(own.size),
            }
    out["client_spread"] = spread

    village = [s for s in panels if s != "Goma"]
    mean = lambda f, sites: float(np.mean([f(out["sites"][s]) for s in sites]))
    for label, sites in (("village_sites", village), ("all_sites", list(panels))):
        out["summary"][label] = {
            "day0_wape": mean(lambda s: s["day0"]["wape"], sites),
            "day0_coverage": mean(lambda s: s["day0"]["coverage_p90_p10"], sites),
            "baseline_flat_wape": mean(lambda s: s["baseline_flat_wape"], sites),
            **{f"after_{k}m_wape": mean(lambda s, k=k: s["learning"][str(k)]["wape"], sites) for k in LEARN_MONTHS},
            **{f"after_{k}m_coverage": mean(lambda s, k=k: s["learning"][str(k)]["coverage_p90_p10"], sites) for k in LEARN_MONTHS},
            **{f"persistence_after_{k}m_wape": mean(lambda s, k=k: s["learning"][str(k)]["baseline_persistence_wape"], sites) for k in LEARN_MONTHS},
            "day0_annual_abs_error": float(np.mean([abs(y["error"]) for s in sites for y in out["sites"][s]["day0"]["years"]])),
            "day0_annual_coverage": float(np.mean([y["inside_band"] for s in sites for y in out["sites"][s]["day0"]["years"]])),
            "baseline_flat_annual_abs_error": float(np.mean([abs(y["error"]) for s in sites for y in out["sites"][s]["baseline_flat_years"]])),
            "n_site_years": int(sum(len(out["sites"][s]["day0"]["years"]) for s in sites)),
        }
    import datetime as _dt
    out["run_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"results": out, "paths": paths}, indent=1))
    plot(paths)
    plot_e2e(paths, out["end_to_end"])
    print(json.dumps(out["summary"], indent=1))
    for n, e in out["end_to_end"].items():
        print("E2E", n, e["potential_from_footprints"], "census", e["potential_census"], [(y["year"], round(y["error"], 2), y["inside_band"]) for y in e["years"]])
    for n, s in out["sites"].items():
        print(f"{n:9s} day0 WAPE {s['day0']['wape']:.2f} cov {s['day0']['coverage_p90_p10']:.2f} cum36 {s['day0']['cum36_error']:+.2f} | flat {s['baseline_flat_wape']:.2f} | "
              + " ".join(f"m{k}: {s['learning'][str(k)]['wape']:.2f}/{s['learning'][str(k)]['coverage_p90_p10']:.2f} (pers {s['learning'][str(k)]['baseline_persistence_wape']:.2f})" for k in LEARN_MONTHS))


def plot(paths):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    cols = [("day0", "Day 0 · open data only"), ("after_6", "After 6 metered months"), ("after_12", "After 12 metered months")]
    fig, axes = plt.subplots(len(paths), len(cols), figsize=(13, 3.1 * len(paths)))
    for i, (name, p) in enumerate(paths.items()):
        t = np.array(p["months"])
        for j, (k, title) in enumerate(cols):
            ax = axes[i, j]
            b = p.get({"day0": "end_to_end", "after_6": "e2e_after_6", "after_12": "e2e_after_12"}[k], p[k])
            ax.fill_between(t, np.array(b["p90"]) / 1e3, np.array(b["p10"]) / 1e3, color="#f4a261", alpha=0.35, label="P90–P10 band")
            ax.plot(t, np.array(b["p50"]) / 1e3, color="#e76f51", lw=1.8, label="P50 forecast")
            ax.plot(t, np.array(p["actual"]) / 1e3, color="#264653", lw=1.6, label="Metered actual")
            if k != "day0":
                ax.axvspan(0, int(k.split("_")[1]), color="#2a9d8f", alpha=0.12, label="Months used")
            if k == "day0" and "end_to_end" not in p:
                title = "Day 0 · census + benchmarks (urban, out of scope)"
            ax.set_title(f"{name} — {title}", fontsize=9)
            ax.set_ylabel("MWh / month", fontsize=8)
            ax.grid(alpha=0.25)
        axes[i, 1].legend(fontsize=7, loc="upper left")
    for ax in axes[-1]:
        ax.set_xlabel("Months since commissioning")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "drc_backtest.png", dpi=150)


def plot_e2e(paths, e2e):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(e2e), figsize=(11, 3.6))
    for ax, (name, e) in zip(axes, e2e.items()):
        p = paths[name]
        t, b = np.array(p["months"]), p["end_to_end"]
        ax.fill_between(t, np.array(b["p90"]) / 1e3, np.array(b["p10"]) / 1e3, color="#f4a261", alpha=0.35, label="P90–P10 band")
        ax.plot(t, np.array(b["p50"]) / 1e3, color="#e76f51", lw=2, label="P50 forecast (open data only)")
        ax.plot(t, np.array(p["actual"]) / 1e3, color="#264653", lw=1.8, label="Metered actual (unseen)")
        yrs = ", ".join(f"Y{y['year']} {100 * y['error']:+.0f}%" for y in e["years"])
        ax.set_title(f"{name}: annual P50 error {yrs}", fontsize=9)
        ax.set_xlabel("Months since commissioning"); ax.set_ylabel("MWh / month"); ax.grid(alpha=0.25)
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle("Held-out DRC mini-grids forecast from building footprints + OpenStreetMap only (no census, no site meters)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "drc_end_to_end.png", dpi=150)


if __name__ == "__main__":
    main()
