"""Loader for the North Kivu (DRC) metered mini-grid panel.

Source: Lunanga, Stoop, Verpoorten & Desbureaux (2026), "From demand deficit to
development strategy: Navigating mini-grid viability in a fragile context",
Energy Economics. Replication data, Harvard Dataverse, doi:10.7910/DVN/KPDREF (CC0).

Area coding differs between files (verified against client counts):
  electricity1 / census / survey : 1=Goma, 2=Lubero, 3=Mutwanga
  electricity2 (client level)    : 1=Mutwanga, 2=Goma, 3=Lubero
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "drc_lunanga2026"

SITES = {1: "Goma", 2: "Lubero", 3: "Mutwanga"}
E2_TO_NAME = {1: "Mutwanga", 2: "Goma", 3: "Lubero"}


@dataclass
class SitePanel:
    name: str
    months: np.ndarray          # months since grid installation
    conn_hh: np.ndarray         # connected household clients
    conn_sme: np.ndarray        # connected SME clients
    kwh_hh: np.ndarray          # average kWh/month per household client (nan if none)
    kwh_sme: np.ndarray         # average kWh/month per SME client (nan if none)
    pot_hh: int                 # census households in service area (potential customers)
    pot_sme: int                # census firms in service area

    @property
    def total_kwh(self) -> np.ndarray:
        hh = np.nan_to_num(self.kwh_hh) * self.conn_hh
        sme = np.nan_to_num(self.kwh_sme) * self.conn_sme
        return hh + sme


def load_panels() -> dict[str, SitePanel]:
    e1 = pd.read_csv(RAW / "electricity1_site_month.tsv", sep="\t")
    census = pd.read_csv(RAW / "census.tsv", sep="\t")
    pots = census.groupby(["area", "firm"]).size().unstack()
    out = {}
    for code, name in SITES.items():
        d = e1[e1.area == code].sort_values("months_grid")
        # drop the commissioning month(s) with zero clients
        d = d[d.clients > 0]
        out[name] = SitePanel(
            name=name,
            months=d.months_grid.to_numpy(float),
            conn_hh=d.clients_hh.to_numpy(float),
            conn_sme=d.clients_sme.to_numpy(float),
            kwh_hh=d.kwh_month_av_hh.to_numpy(float),
            kwh_sme=d.kwh_month_av_sme.to_numpy(float),
            pot_hh=int(pots.loc[code, 0.0]),
            pot_sme=int(pots.loc[code, 1.0]),
        )
    return out


def load_clients() -> pd.DataFrame:
    """Client-level average monthly kWh, with site names and segment."""
    e2 = pd.read_csv(RAW / "electricity2_client.tsv", sep="\t")
    e2["site"] = e2.area.map(E2_TO_NAME)
    e2["segment"] = e2.client.map({1: "household", 2: "sme"})
    return e2[["site", "segment", "kwh_client_av"]]
