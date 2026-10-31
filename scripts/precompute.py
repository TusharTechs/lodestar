"""Rebuild the site index and pre-compute (and pre-register in the ledger) a report for every site.

python scripts/precompute.py [--force]
"""
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import select_sites  # noqa: E402
from api.main import get_report  # noqa: E402

force = "--force" in sys.argv
select_sites.build_index()
times, sizes = [], []
for row in json.loads((ROOT / "data" / "sites" / "index.json").read_text()):
    t = time.process_time()
    rep = get_report(row["site_id"], refresh=force)
    times.append(time.process_time() - t)
    sizes.append(len(gzip.compress(json.dumps(rep).encode())) / 1024)
    h = rep["headline"]
    print(f"{row['site_id']:28s} y3 P90 {h['p90']/1e3:6.1f}  P50 {h['p50']/1e3:6.1f}  P10 {h['p10']/1e3:6.1f} MWh/mo  {rep['ledger']['forecast_id']}")

if force:
    (ROOT / "data" / "derived" / "runtime.json").write_text(json.dumps(
        {"seconds_per_report": sum(times) / len(times), "report_kb_gzip": sum(sizes) / len(sizes), "n_sites": len(times),
         "note": "CPU seconds per full report (20,000 draws incl. driver waterfall and finance), measured on a laptop"}, indent=1))
