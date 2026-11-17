"""Alaska migration from the Alaska Department of Labor and Workforce Development.

  1. Annual components of population change, 1945 to the latest July 1
     (ComponentsOfChangeAK.xlsx): births, deaths, natural increase, in- and
     out-migration (from 1980) and net migration for each July-to-June year.
  2. Migration by age from Permanent Fund Dividend applications: average yearly
     in- and out-migrants by five-year age group, statewide, for each five-year
     period since 1985 (the current-period file plus the historical file).

Writes site/data/migration.json. The PFD files are linked from DOLWD's Alaska
Migration Data page, and their addresses change when DOLWD posts new versions,
so the script finds them on that page by their link text.

Needs openpyxl (pip install openpyxl).

Usage:  python3 scripts/fetch_migration.py
        MIG_LOCAL=dir python3 scripts/fetch_migration.py   # read components_ak.xlsx,
              pfd_age_current.xlsx, pfd_age_hist.xlsx from dir (testing)
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "migration.json"
BASE = "https://live.laborstats.alaska.gov"
COMPONENTS = BASE + "/pop/estimates/data/ComponentsOfChangeAK.xlsx"
MIGRATION_PAGE = BASE + "/node/83"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}


def get(url, tries=3):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(8 * (attempt + 1))


def local(name):
    d = os.environ.get("MIG_LOCAL")
    return (Path(d) / name).read_bytes() if d else None


def num(x):
    if isinstance(x, (int, float)):
        return x
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def components(blob):
    ws = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True).active
    rows, title = [], ""
    for r in ws.iter_rows(values_only=True):
        a = r[0]
        if isinstance(a, str) and a.startswith("Annual Components"):
            title = a.strip()
        if not (isinstance(a, str) and re.match(r"^\d{4}-\d{2}$", a.strip())):
            continue
        y = a.strip()
        end = int(y[:4]) + 1
        rows.append({"year": y, "end": end, "population": num(r[1]), "births": num(r[4]), "deaths": num(r[5]),
                     "natural": num(r[6]), "in": num(r[7]), "out": num(r[8]), "net": num(r[9])})
    if len(rows) < 50:
        raise RuntimeError(f"components table: only {len(rows)} rows found")
    vint = re.search(r"(\d{4})$", title)
    return {"title": title, "vintage": vint.group(1) if vint else str(rows[-1]["end"]),
            "columns": ["year", "population", "births", "deaths", "natural", "in", "out", "net"],
            "rows": [[x["year"], x["population"], x["births"], x["deaths"], x["natural"], x["in"], x["out"], x["net"]] for x in rows]}


AGE_RE = re.compile(r"^(\d+)-(\d+)$|^(\d+)\+$")


def by_age(blob):
    """{period: {"in": {age: n}, "out": {age: n}, "total_in", "total_out"}} for the statewide rows."""
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        per = None
        res = {"ages": [], "in": [], "out": []}
        for r in ws.iter_rows(values_only=True):
            cells = [c for c in r if c is not None]
            if not cells:
                continue
            if per is None and isinstance(cells[0], str) and "Average Annual" in cells[0]:
                m = re.search(r"(\d{4}) to (\d{4})", cells[0])
                if m:
                    per = f"{m.group(1)}-{m.group(2)}"
            if str(cells[0]).strip() != "000":
                continue
            # statewide rows: ['000', 'Alaska', 'Total', in, m, f, out, m, f] then ['000', '0-4', in, m, f, out, m, f]
            if len(cells) >= 9 and cells[2] == "Total":
                res["total_in"], res["total_out"] = num(cells[3]), num(cells[6])
            elif len(cells) >= 8 and AGE_RE.match(str(cells[1]).strip()):
                res["ages"].append(str(cells[1]).strip())
                res["in"].append(num(cells[2]))
                res["out"].append(num(cells[5]))
        if per and res["ages"]:
            out[per] = res
    return out


def find_links():
    html = get(MIGRATION_PAGE).decode("utf-8", errors="replace")
    links = {}
    for href, text in re.findall(r'<a[^>]+href="([^"]+\.xlsx)"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        t = re.sub(r"<[^>]+>", "", text)
        t = " ".join(t.split())
        url = urllib.parse.urljoin(BASE, href)
        key = (t + " " + urllib.parse.unquote(href)).lower()
        if "by age and sex" in key and "historical" in key:
            links["hist"] = url
        elif "by age and sex" in key:
            links["current"] = url
    return links


def main():
    data = {"source": "Alaska Department of Labor and Workforce Development, Research and Analysis Section",
            "fetched": date.today().isoformat()}
    problems = []
    try:
        data["components"] = components(local("components_ak.xlsx") or get(COMPONENTS))
        r = data["components"]["rows"][-1]
        print(f"  components: {len(data['components']['rows'])} years, latest {r[0]} net {r[7]:+,.0f}")
    except Exception as e:
        problems.append(f"components: {e}")

    ages = {}
    try:
        if os.environ.get("MIG_LOCAL"):
            blobs = [local("pfd_age_hist.xlsx"), local("pfd_age_current.xlsx")]
        else:
            links = find_links()
            if "current" not in links:
                raise RuntimeError("couldn't find the PFD migration-by-age file on the Migration Data page")
            blobs = [get(links["hist"])] if "hist" in links else []
            blobs.append(get(links["current"]))
        for b in blobs:
            ages.update(by_age(b))
        data["by_age"] = {p: ages[p] for p in sorted(ages)}
        print(f"  by age: periods {', '.join(sorted(ages))}")
    except Exception as e:
        problems.append(f"by age: {e}")

    # the same yearly numbers as chartable series for site/js/ind.js (dated by the
    # July 1 that ends each year: 2024-25 -> 2025)
    if "components" in data:
        ser = {}
        for i, (sid, label) in enumerate([("births", "Births"), ("deaths", "Deaths"), ("natural", "Natural increase (births minus deaths)"),
                                          ("in", "In-migrants"), ("out", "Out-migrants"), ("net", "Net migration")], start=2):
            pts = [(f"{int(r[0][:4]) + 1}-01-01", r[i]) for r in data["components"]["rows"] if r[i] is not None]
            ser[sid] = {"label": f"{label}, Alaska, year to July 1", "units": "people", "freq": "annual", "kind": "flow",
                        "dates": [p[0] for p in pts], "values": [p[1] for p in pts]}
        data["series"] = ser

    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    for k in ("components", "by_age", "series"):  # keep what we had if a piece failed this time
        if k not in data and k in old:
            data[k] = old[k]
    for p in problems:
        print(f"::warning::migration {p}")
    if "components" not in data and "by_age" not in data:
        sys.exit("migration: nothing fetched")
    if {k: v for k, v in old.items() if k != "fetched"} == {k: v for k, v in data.items() if k != "fetched"}:
        print("  migration: no new data")
        return
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"  wrote {OUT.name}")


if __name__ == "__main__":
    main()
