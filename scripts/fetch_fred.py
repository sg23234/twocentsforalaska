"""Pull FRED series for each dashboard and save them as JSON in site/data/.

No API key needed: uses FRED's public CSV download. Standard library only,
so GitHub Actions can run it without installing anything.

Add a topic by adding an entry to DASHBOARDS below.

Usage:
    python scripts/fetch_fred.py            # fetch every dashboard
    python scripts/fetch_fred.py gdp        # fetch just one
"""
import csv
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "site" / "data"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

# dashboard slug -> FRED series it uses
DASHBOARDS = {
    "gdp": {
        "AKRGSP": "Real GDP, annual, millions of chained 2017 dollars",
        "AKRQGSP": "Real GDP, quarterly SAAR, millions of chained 2017 dollars",
        "AKMINRQGSP": "Real GDP, mining (incl. oil & gas), quarterly SAAR",
        "AKGOVRQGSP": "Real GDP, government, quarterly SAAR",
    },
    # Next ones to wire up (uncomment once the page reads them):
    # "business-formation": {"BABATOTALNSAAK": "Business applications, monthly, NSA"},
    # "housing": {"AKBPPRIV": "New private housing units authorized, monthly"},
}


def parse_fred_csv(text):
    """Return (dates, values) from a FRED CSV, skipping missing values ('.')."""
    rows = list(csv.reader(io.StringIO(text)))
    dates, values = [], []
    for row in rows[1:]:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        dates.append(row[0])
        values.append(float(row[1]))
    if not dates:
        raise ValueError("no data rows")
    return dates, values


def fetch(series_id, tries=3):
    req = urllib.request.Request(
        FRED_CSV.format(series_id),
        headers={"User-Agent": "twocentsforalaska.org data refresh"},
    )
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return parse_fred_csv(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{series_id}: {e}") from e
            time.sleep(5 * (attempt + 1))


def build(slug, series):
    out = {
        "dashboard": slug,
        "source": "FRED, Federal Reserve Bank of St. Louis",
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "series": {},
    }
    for sid, label in series.items():
        dates, values = fetch(sid)
        out["series"][sid] = {"label": label, "dates": dates, "values": values}
        print(f"  {sid}: {len(values)} obs, latest {dates[-1]} = {values[-1]:,.1f}")
    return out


def write_if_changed(slug, data):
    """Only rewrite the file when the numbers changed, so the workflow
    doesn't commit every month just because the fetch date moved."""
    path = DATA_DIR / f"{slug}.json"
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("series") == data["series"]:
            print(f"  {slug}: no new data")
            return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    print(f"  {slug}: updated {path.name}")
    return True


def main(argv):
    wanted = argv or list(DASHBOARDS)
    failed = []
    for slug in wanted:
        print(slug)
        try:
            write_if_changed(slug, build(slug, DASHBOARDS[slug]))
        except Exception as e:  # keep going so one bad series doesn't block the rest
            print(f"  FAILED: {e}")
            failed.append(slug)
    if failed:
        sys.exit(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(sys.argv[1:])
