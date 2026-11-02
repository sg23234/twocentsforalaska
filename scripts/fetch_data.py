"""Pull the live series for each dashboard and save them as JSON in site/data/.

Sources
  FRED  - public CSV download, no key needed. Most series live here.
  DOLWD - the Alaska Department of Labor's payroll-jobs CSV. Its own monthly
          estimates, which are what Alaska news reports and can differ from the
          federal (BLS/FRED) numbers for the latest months.
  BLS   - the BLS public API. Used only for Urban Alaska CPI detail, which FRED
          carries just twice a year. Works without a key (25 requests a day,
          shared by everyone on GitHub's servers); add a free key as the
          BLS_API_KEY secret to make it dependable.

Standard library only, so GitHub Actions can run it without installing anything.

Hand-maintained numbers (annual reports, surveys, budgets) are not here: they
live in site/data/manual/<dashboard>.json and you edit them directly.

Usage:
    python scripts/fetch_data.py            # fetch every dashboard
    python scripts/fetch_data.py housing    # fetch just one
"""
import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "site" / "data"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
DOLWD_CES = "https://live.laborstats.alaska.gov/labforce/csv/000000/01/ces.csv"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}

def s(label, units, freq, kind, optional=False):
    """Series metadata. kind: level | flow (counts you can add up) | index | rate | pct."""
    return {"label": label, "units": units, "freq": freq, "kind": kind, "optional": optional}


# dashboard slug -> {"source": ..., "series": {id: metadata}}
# optional=True: try it, but a failure is only a warning (used for series whose
# FRED ID we couldn't confirm ahead of time; the page copes without them).
DASHBOARDS = {
    "gdp": {"source": "fred", "series": {
        "AKRGSP": s("Real GDP, annual, millions of chained 2017 dollars", "millions of 2017 dollars", "annual", "level"),
        "AKRQGSP": s("Real GDP, quarterly SAAR, millions of chained 2017 dollars", "millions of 2017 dollars, annual rate", "quarterly", "level"),
        "AKMINRQGSP": s("Real GDP, mining (incl. oil & gas), quarterly SAAR", "millions of 2017 dollars, annual rate", "quarterly", "level"),
        "AKGOVRQGSP": s("Real GDP, government, quarterly SAAR", "millions of 2017 dollars, annual rate", "quarterly", "level"),
    }},
    "population": {"source": "fred", "series": {
        "AKPOP": s("Resident population (Census Bureau estimate, July 1)", "thousands of people", "annual", "level"),
    }},
    "business-formation": {"source": "fred", "series": {
        "BABATOTALNSAAK": s("Business applications, Alaska", "applications", "monthly", "flow"),
        "BAHBATOTALNSAAK": s("High-propensity business applications (likely employers), Alaska", "applications", "monthly", "flow", optional=True),
        "BABATOTALNSAUS": s("Business applications, United States", "applications", "monthly", "flow", optional=True),
    }},
    "housing": {"source": "fred", "series": {
        "AKBPPRIV": s("New private housing units authorized by building permits, Alaska", "units", "monthly", "flow"),
        "MORTGAGE30US": s("30-year fixed mortgage rate, U.S. average (Freddie Mac)", "percent", "weekly", "rate"),
    }},
    "cost-of-living": {"source": "bls", "soft": True, "series": {
        "CUURS49GSA0": s("CPI, all items, Urban Alaska", "index 1982-84=100", "bimonthly", "index"),
        "CUURS49GSA0L1E": s("CPI, all items less food and energy, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETB": s("CPI, motor fuel, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETB01": s("CPI, gasoline (all types), Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAR": s("CPI, recreation, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAT": s("CPI, transportation, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAG": s("CPI, other goods and services, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAH1": s("CPI, shelter, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEHC": s("CPI, owners' equivalent rent, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAH": s("CPI, housing, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEHA": s("CPI, rent of primary residence, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUURS49GSAF11": s("CPI, food at home, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSEFV": s("CPI, food away from home, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAA": s("CPI, apparel, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAE": s("CPI, education and communication, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAM": s("CPI, medical care, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSAH3": s("CPI, household furnishings and operations, Urban Alaska", "index", "bimonthly", "index"),
        "CUURS49GSETA": s("CPI, new and used motor vehicles, Urban Alaska", "index", "bimonthly", "index", optional=True),
        "CUUR0000SA0": s("CPI, all items, U.S. city average", "index 1982-84=100", "monthly", "index"),
    }},
    "productivity": {"source": "fred", "series": {
        "IPUZNL000020000": s("Labor productivity, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
        "IPUZNT010020000": s("Real value-added output, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
        "IPUZNL010020000": s("Hours worked, private nonfarm, Alaska", "index 2017=100", "annual", "index"),
    }},
    # Payroll jobs straight from Alaska DOLWD (not seasonally adjusted). Keyed by
    # the industry name exactly as it appears in DOLWD's CSV.
    "key-sectors": {"source": "dolwd", "soft": True, "series": {
        "Total Nonfarm": s("Payroll jobs, total nonfarm", "jobs", "monthly", "level"),
        "Trade, Transportation, Utilities": s("Payroll jobs, trade, transportation and utilities", "jobs", "monthly", "level"),
        "Construction": s("Payroll jobs, construction", "jobs", "monthly", "level"),
        "Mining and Logging": s("Payroll jobs, mining and logging (includes oil and gas)", "jobs", "monthly", "level"),
        "Oil & Gas": s("Payroll jobs, oil and gas", "jobs", "monthly", "level"),
        "Health Care": s("Payroll jobs, health care", "jobs", "monthly", "level"),
        "Manufacturing": s("Payroll jobs, manufacturing (mostly seafood processing)", "jobs", "monthly", "level"),
        "Information": s("Payroll jobs, information", "jobs", "monthly", "level"),
        "Leisure & Hospitality": s("Payroll jobs, leisure and hospitality", "jobs", "monthly", "level"),
        "Financial Activities": s("Payroll jobs, financial activities", "jobs", "monthly", "level"),
        "Professional & Business Svcs": s("Payroll jobs, professional and business services", "jobs", "monthly", "level"),
        "Local Government": s("Payroll jobs, local government (incl. schools)", "jobs", "monthly", "level"),
        "State Government": s("Payroll jobs, state government", "jobs", "monthly", "level"),
        "Federal Government": s("Payroll jobs, federal government (civilian)", "jobs", "monthly", "level"),
    }},
    "spending": {"source": "dolwd", "soft": True, "series": {
        "Total Nonfarm": s("Payroll jobs, total nonfarm", "jobs", "monthly", "level"),
        "Government": s("Payroll jobs, government", "jobs", "monthly", "level"),
        "Local Government": s("Payroll jobs, local government (incl. schools)", "jobs", "monthly", "level"),
        "State Government": s("Payroll jobs, state government", "jobs", "monthly", "level"),
        "Federal Government": s("Payroll jobs, federal government (civilian)", "jobs", "monthly", "level"),
    }},
}

SOURCE_NAMES = {
    "fred": "FRED, Federal Reserve Bank of St. Louis",
    "bls": "U.S. Bureau of Labor Statistics API",
    "dolwd": "Alaska Department of Labor and Workforce Development, Current Employment Statistics",
}

# A soft dashboard (BLS without a key can be rate-limited) only fails the job
# once its data is this many days old.
SOFT_STALE_DAYS = 75


def note(level, msg):
    """Print a message GitHub shows as an annotation on the run."""
    print(f"::{level}::{msg}")


# ---------- FRED ----------

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


def fetch_fred(series_id, tries=3):
    req = urllib.request.Request(FRED_CSV.format(series_id), headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dates, values = parse_fred_csv(r.read().decode("utf-8"))
                return {"dates": dates, "values": values}
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(str(e)) from e
            time.sleep(5 * (attempt + 1))


# ---------- BLS ----------

def fetch_bls(series_ids, tries=3):
    """Return {series_id: {"dates", "values", "annual": {...}}} for the ids BLS knows.
    One request for up to 25 series (50 with a key). Ten years of history (20 with a key)."""
    key = os.environ.get("BLS_API_KEY", "").strip()
    end = date.today().year
    body = {"seriesid": list(series_ids), "startyear": str(end - (19 if key else 9)), "endyear": str(end)}
    if key:
        body.update(registrationkey=key, annualaverage=True)
    req = urllib.request.Request(BLS_V2 if key else BLS_V1, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"BLS request failed: {e}") from e
            time.sleep(10 * (attempt + 1))
    if res.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {res.get('status')} {' '.join(res.get('message', []))}"[:300])
    out = {}
    for ser in res.get("Results", {}).get("series", []):
        monthly, annual = {}, {}
        for obs in ser.get("data", []):
            try:
                v = float(obs["value"])
            except (ValueError, KeyError):
                continue  # '-' marks a missing value
            per = obs["period"]
            if per == "M13":
                annual[obs["year"]] = v
            elif per.startswith("M"):
                monthly[f"{obs['year']}-{per[1:]}-01"] = v
        if monthly:
            d = sorted(monthly)
            out[ser["seriesID"]] = {"dates": d, "values": [monthly[x] for x in d]}
            if annual:
                y = sorted(annual)
                out[ser["seriesID"]]["annual"] = {"dates": y, "values": [annual[x] for x in y]}
    return out


# ---------- Alaska DOLWD ----------

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def fetch_dolwd(names, tries=3):
    """Return {industry name: {"dates", "values"}} from DOLWD's statewide payroll CSV."""
    req = urllib.request.Request(DOLWD_CES, headers=UA)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8-sig", errors="replace")
            break
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"DOLWD CSV: {e}") from e
            time.sleep(10 * (attempt + 1))
    # The file opens with a title line ("Alaska Monthly Employment Statistics") before the header.
    start = text.find("areaname,")
    found = {}
    reader = csv.DictReader(io.StringIO(text[start:] if start >= 0 else text))
    for raw in reader:
        # Rows can carry trailing commas; csv puts those extras under a None key as a list.
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if isinstance(k, str) and not isinstance(v, list)}
        name = row.get("industry", "")
        if name not in names or row.get("adjusted", "0") not in ("0", ""):
            continue
        year = row.get("year", "")
        for i, m in enumerate(MONTHS):
            v = row.get(f"emp_{m}", "").replace(",", "")
            if v:
                found.setdefault(name, {})[f"{year}-{i + 1:02d}-01"] = float(v)
    if not found:
        snippet = " ".join(text[:300].split())
        raise RuntimeError(f"DOLWD CSV had none of the expected rows; it began: {snippet!r}")
    out = {}
    for name, obs in found.items():
        d = sorted(obs)
        out[name] = {"dates": d, "values": [obs[x] for x in d]}
    return out


# ---------- build / write ----------

def build(slug, cfg):
    """Fetch one dashboard. Returns (data, problems) where problems lists
    (series_id, message, optional)."""
    out = {
        "dashboard": slug,
        "source": SOURCE_NAMES[cfg["source"]],
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "series": {},
    }
    problems = []
    meta = cfg["series"]
    if cfg["source"] == "bls":
        got = fetch_bls(meta.keys())
    elif cfg["source"] == "dolwd":
        got = fetch_dolwd(set(meta))
    else:
        got = {}
        for sid, m in meta.items():
            try:
                got[sid] = fetch_fred(sid)
            except Exception as e:
                problems.append((sid, str(e), m["optional"]))
    for sid, m in meta.items():
        if sid not in got:
            if not any(p[0] == sid for p in problems):
                problems.append((sid, "not returned by the source", m["optional"]))
            continue
        entry = {k: v for k, v in m.items() if k != "optional"}
        entry.update(got[sid])
        out["series"][sid] = entry
        print(f"  {sid}: {len(entry['values'])} obs, latest {entry['dates'][-1]} = {entry['values'][-1]:,.3f}")
    return out, problems


def write_if_changed(slug, data):
    """Only rewrite the file when the numbers changed, so the workflow
    doesn't commit every run just because the fetch date moved."""
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


def age_days(slug):
    path = DATA_DIR / f"{slug}.json"
    if not path.exists():
        return None
    fetched = json.loads(path.read_text()).get("fetched")
    try:
        return (date.today() - date.fromisoformat(fetched)).days
    except (TypeError, ValueError):
        return None


def update_status(results):
    """site/data/status.json: what each dashboard has and any problems.
    No timestamps of the run itself, so it only changes when something real does."""
    path = DATA_DIR / "status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    for slug, info in results.items():
        status[slug] = info
    path.write_text(json.dumps(dict(sorted(status.items())), indent=1) + "\n")


def main(argv):
    wanted = argv or list(DASHBOARDS)
    failed, results = [], {}
    for slug in wanted:
        cfg = DASHBOARDS[slug]
        print(slug)
        try:
            data, problems = build(slug, cfg)
        except Exception as e:
            data, problems = None, [("*", str(e), False)]
        hard = [p for p in problems if not p[2]]
        for sid, msg, opt in problems:
            note("warning" if opt else "error", f"{slug} {sid}: {msg}")
        if data and data["series"] and not hard:
            write_if_changed(slug, data)
        # If a required series is missing, keep the old file rather than publish a partial one.
        info = {
            "source": cfg["source"],
            "latest": {sid: v["dates"][-1] for sid, v in (data or {}).get("series", {}).items()},
            "problems": [f"{sid}: {msg}" + (" (optional)" if opt else "") for sid, msg, opt in problems],
        }
        if hard:
            if cfg.get("soft"):
                age = age_days(slug)
                if age is not None and age <= SOFT_STALE_DAYS:
                    note("warning", f"{slug}: kept data from {age} days ago")
                    info["problems"].append(f"kept existing data ({age} days old)")
                else:
                    failed.append(slug)
            else:
                failed.append(slug)
        if not info["problems"]:
            del info["problems"]
        results[slug] = info
    update_status(results)
    if failed:
        sys.exit(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(sys.argv[1:])
