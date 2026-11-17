"""Average weekly wages by industry and by borough from the Quarterly Census of
Employment and Wages (QCEW), read from the BLS QCEW open-data CSV slices.

Writes site/data/qcew.json:
  annual   - latest full year: statewide total, private sectors, government by
             level, and every borough/census area (all ownerships combined)
  quarter  - latest quarter: statewide total and private sectors, with the
             change in the average weekly wage from the same quarter a year earlier
  history  - statewide average weekly wage (all covered jobs) for each year
             since 2001, for the trend line

BLS withholds ("N") Alaska cells that could reveal a single employer, so some
industries are missing in some periods; they're simply left out.

No key needed. Standard library only.

Usage:  python3 scripts/fetch_qcew.py
        QCEW_LOCAL=dir python3 scripts/fetch_qcew.py   # read <year>_<qtr>_<kind>.csv files from dir (testing)
"""
import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "qcew.json"
API = "https://data.bls.gov/cew/data/api/{year}/{qtr}/{kind}/{code}.csv"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}

SECTORS = {
    "11": "Agriculture, forestry, fishing", "21": "Mining, oil and gas", "22": "Utilities", "23": "Construction",
    "31-33": "Manufacturing", "42": "Wholesale trade", "44-45": "Retail trade", "48-49": "Transportation and warehousing",
    "51": "Information", "52": "Finance and insurance", "53": "Real estate", "54": "Professional and technical services",
    "55": "Management of companies", "56": "Administrative and support", "61": "Private education",
    "62": "Health care and social assistance", "71": "Arts and recreation", "72": "Accommodation and food",
    "81": "Other services",
}
GOV = {"1": "Federal government", "2": "State government", "3": "Local government"}
AREAS = {
    "013": "Aleutians East", "016": "Aleutians West", "020": "Anchorage", "050": "Bethel", "060": "Bristol Bay",
    "063": "Chugach", "066": "Copper River", "068": "Denali", "070": "Dillingham", "090": "Fairbanks North Star",
    "100": "Haines", "105": "Hoonah-Angoon", "110": "Juneau", "122": "Kenai Peninsula", "130": "Ketchikan Gateway",
    "150": "Kodiak Island", "158": "Kusilvak", "164": "Lake and Peninsula", "170": "Matanuska-Susitna", "180": "Nome",
    "185": "North Slope", "188": "Northwest Arctic", "195": "Petersburg", "198": "Prince of Wales-Hyder",
    "220": "Sitka", "230": "Skagway", "240": "Southeast Fairbanks", "275": "Wrangell", "282": "Yakutat",
    "290": "Yukon-Koyukuk",
}


def get(year, qtr, kind, code, tries=2):
    local = os.environ.get("QCEW_LOCAL")
    if local:
        p = Path(local) / f"{year}_{qtr}_{kind}.csv"
        if not p.exists():
            raise FileNotFoundError(p)
        return list(csv.DictReader(io.StringIO(p.read_text())))
    url = API.format(year=year, qtr=qtr, kind=kind, code=code)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                text = r.read().decode("utf-8", errors="replace")
            if not text.startswith('"area_fips"'):
                raise RuntimeError("not a QCEW CSV (not published yet?)")
            return list(csv.DictReader(io.StringIO(text)))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def ok(r):
    return r.get("disclosure_code", "") != "N"


def pick(rows, wage, emp, chg):
    """Statewide pieces from one area file (02000)."""
    out = {"total": None, "private": None, "sectors": [], "government": []}
    for r in rows:
        if r["area_fips"] != "02000" or not ok(r):
            continue
        w, e, c = num(r.get(wage)), num(r.get(emp)), num(r.get(chg))
        if not w:
            continue
        row = {"wage": w, "jobs": e, "chg_pct": c}
        own, agg, ind = r["own_code"], r["agglvl_code"], r["industry_code"]
        if own == "0" and agg == "50":
            out["total"] = row
        elif own == "5" and agg == "51":
            out["private"] = row
        elif own == "5" and agg == "54" and ind in SECTORS:
            out["sectors"].append({"name": SECTORS[ind], "naics": ind, **row})
        elif own in GOV and agg == "51":
            out["government"].append({"name": GOV[own], **row})
    out["sectors"].sort(key=lambda x: -x["wage"])
    return out


def boroughs(rows, wage, emp, chg):
    out = []
    for r in rows:
        f = r["area_fips"]
        if not f.startswith("02") or f == "02000" or r["own_code"] != "0" or r["agglvl_code"] != "70" or not ok(r):
            continue
        name = AREAS.get(f[2:])
        w = num(r.get(wage))
        if name and w:
            out.append({"name": name, "fips": f, "wage": w, "jobs": num(r.get(emp)), "chg_pct": num(r.get(chg))})
    out.sort(key=lambda x: -x["wage"])
    return out


def main():
    this = date.today().year
    data = {"source": "U.S. Bureau of Labor Statistics, Quarterly Census of Employment and Wages (open data CSV)",
            "url": "https://www.bls.gov/cew/", "fetched": date.today().isoformat()}

    # latest full year
    for y in (this - 1, this - 2):
        try:
            area = get(y, "a", "area", "02000")
        except Exception as e:
            print(f"  annual {y}: {e}")
            continue
        st = pick(area, "annual_avg_wkly_wage", "annual_avg_emplvl", "oty_annual_avg_wkly_wage_pct_chg")
        if not st["total"]:
            continue
        try:
            br = boroughs(get(y, "a", "industry", "10"), "annual_avg_wkly_wage", "annual_avg_emplvl", "oty_annual_avg_wkly_wage_pct_chg")
        except Exception as e:
            print(f"  boroughs {y}: {e}")
            br = []
        data["annual"] = {"year": y, **st, "boroughs": br}
        print(f"  annual {y}: statewide ${st['total']['wage']:,.0f}/wk, {len(st['sectors'])} sectors, {len(br)} areas")
        break

    # latest quarter
    done = False
    for y in (this, this - 1):
        for q in (4, 3, 2, 1):
            try:
                area = get(y, q, "area", "02000")
            except Exception:
                continue
            st = pick(area, "avg_wkly_wage", "month3_emplvl", "oty_avg_wkly_wage_pct_chg")
            if st["total"]:
                data["quarter"] = {"year": y, "qtr": q, **st}
                print(f"  quarter {y} Q{q}: statewide ${st['total']['wage']:,.0f}/wk")
                done = True
                break
        if done:
            break

    # statewide history (annual, all covered jobs)
    hist = []
    last = data.get("annual", {}).get("year", this - 1)
    old = json.loads(OUT.read_text()).get("history", {}) if OUT.exists() else {}
    have = dict(zip(old.get("years", []), old.get("wages", [])))
    for y in range(2001, last + 1):
        if y in have and y < last - 1:  # older years don't get revised; skip the download
            hist.append((y, have[y]))
            continue
        try:
            rows = get(y, "a", "area", "02000")
        except Exception:
            continue
        t = pick(rows, "annual_avg_wkly_wage", "annual_avg_emplvl", "oty_annual_avg_wkly_wage_pct_chg")["total"]
        if t:
            hist.append((y, t["wage"]))
    if hist:
        data["history"] = {"years": [h[0] for h in hist], "wages": [h[1] for h in hist]}

    if "annual" not in data and "quarter" not in data:
        sys.exit("QCEW: nothing returned")
    if OUT.exists():
        prev = json.loads(OUT.read_text())
        if {k: v for k, v in prev.items() if k != "fetched"} == {k: v for k, v in data.items() if k != "fetched"}:
            print("  qcew: no new data")
            return
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"  wrote {OUT.name}")


if __name__ == "__main__":
    main()
