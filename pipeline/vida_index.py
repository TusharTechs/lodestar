"""Build/query a local row-group bbox index for VIDA S2-partitioned geoparquet.

Remote footers are large (~5 s each), so we read them once per country and cache
the per-row-group bbox stats in data/cache/vida_index_{ISO}.parquet.
"""
import re, sys, pathlib
import duckdb, pandas as pd, requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
BASE = "https://data.source.coop/vida/"
PFX = "google-microsoft-osm-open-buildings/geoparquet/by_country_s2/country_iso={iso}/"


def con():
    c = duckdb.connect()
    c.execute("install httpfs; load httpfs; install spatial; load spatial")
    return c


def build(iso):
    out = CACHE / f"vida_index_{iso}.parquet"
    xml = requests.get(BASE + "google-microsoft-osm-open-buildings/",
                       params={"prefix": PFX.format(iso=iso).split("/", 1)[1]}, timeout=60).text
    keys = re.findall(r"<Key>([^<]*\.parquet)</Key>", xml)
    c = con()
    rows = []
    for k in keys:
        u = BASE + k
        r = c.execute(f"""select row_group_id, path_in_schema,
            min(cast(stats_min_value as double)), max(cast(stats_max_value as double)), max(num_values)
            from parquet_metadata('{u}')
            where path_in_schema in ('bbox, xmin','bbox, ymin','bbox, xmax','bbox, ymax') group by all""").fetchall()
        d = {}
        for rg, p, mn, mx, n in r:
            d.setdefault(rg, {"n": n})[p.split(", ")[1]] = (mn, mx)
        for rg, v in d.items():
            rows.append(dict(url=u, rg=rg, n=v["n"], xmin=v["xmin"][0], xmax=v["xmax"][1],
                             ymin=v["ymin"][0], ymax=v["ymax"][1]))
        print(iso, k[-30:], len(d), flush=True)
    pd.DataFrame(rows).to_parquet(out)
    return out


if __name__ == "__main__":
    CACHE.mkdir(parents=True, exist_ok=True)
    for iso in sys.argv[1:]:
        build(iso)
