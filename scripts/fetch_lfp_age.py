"""Labor force participation by age, Alaska and the U.S., from the Census
Bureau's American Community Survey 1-year estimates (subject table S2301).

Writes site/data/lfp-age.json as annual series that site/js/ind.js can chart:
  AK:<age> / US:<age>     participation rate for each published age group
  AK:25-54 etc.           rates for wider groups, weighted by population
  AK:pop55+ / US:pop55+   people 55 and older as a share of everyone 16 and older
                          (how much of the change in the overall rate is aging)

The 1-year ACS starts in this form in 2015 (earlier years use different age
groups) and skips 2020, when the Census Bureau didn't release standard 1-year
estimates. Each year comes out in September for the year before.

The Census data API now asks for a key: set the free CENSUS_API_KEY secret
(https://api.census.gov/data/key_signup.html). Without it this script warns
and leaves the existing file alone.

Usage:  python3 scripts/fetch_lfp_age.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "lfp-age.json"
API = "https://api.census.gov/data/{y}/acs/acs1/subject"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}
# row number in S2301 (2015 on) -> age group
AGES = {2: "16-19", 3: "20-24", 4: "25-29", 5: "30-34", 6: "35-44", 7: "45-54", 8: "55-59", 9: "60-64", 10: "65-74", 11: "75+"}
GROUPS = {"16-24": ["16-19", "20-24"], "25-54": ["25-29", "30-34", "35-44", "45-54"], "55-64": ["55-59", "60-64"], "65+": ["65-74", "75+"]}
FIRST = 2015


def get(year, key, tries=3):
    rows = [1] + list(AGES)
    fields = ["NAME"] + [f"S2301_C01_{r:03d}E" for r in rows] + [f"S2301_C02_{r:03d}E" for r in rows]
    q = {"get": ",".join(fields), "for": "state:02", "key": key}
    out = {}
    for geo in ("state:02", "us:1"):
        q["for"] = geo
        url = API.format(y=year) + "?" + urllib.parse.urlencode(q, safe=",:")
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                    body = r.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    return None  # year not published
                if attempt == tries - 1:
                    raise
                time.sleep(5)
        try:
            head, vals = json.loads(body)[:2]
        except ValueError:
            raise RuntimeError(f"{year}: not JSON (key refused?): {body[:120]!r}")
        rec = dict(zip(head, vals))
        num = lambda k: float(rec[k]) if rec.get(k) not in (None, "", "null") and float(rec[k]) >= 0 else None
        pop = {AGES[r]: num(f"S2301_C01_{r:03d}E") for r in AGES}
        rate = {AGES[r]: num(f"S2301_C02_{r:03d}E") for r in AGES}
        out["AK" if geo.startswith("state") else "US"] = {"pop16": num("S2301_C01_001E"), "rate16": num("S2301_C02_001E"), "pop": pop, "rate": rate}
    return out


def main():
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        print("::warning::lfp-age: skipped, CENSUS_API_KEY secret not set (the Census data API now requires a key)")
        return
    series = {}

    def put(sid, label, y, v):
        if v is None:
            return
        s = series.setdefault(sid, {"label": label, "units": "percent", "freq": "annual", "kind": "rate", "dates": [], "values": []})
        s["dates"].append(f"{y}-01-01")
        s["values"].append(round(v, 2))

    for y in range(FIRST, date.today().year):
        if y == 2020:
            continue
        try:
            got = get(y, key)
        except Exception as e:
            print(f"::warning::lfp-age {y}: {e}")
            continue
        if not got:
            continue
        for geo, d in got.items():
            name = "Alaska" if geo == "AK" else "United States"
            put(f"{geo}:16+", f"Labor force participation, 16 and older, {name}", y, d["rate16"])
            for a in AGES.values():
                put(f"{geo}:{a}", f"Labor force participation, ages {a}, {name}", y, d["rate"][a])
            for g, parts in GROUPS.items():
                if all(d["pop"][p] and d["rate"][p] is not None for p in parts):
                    tot = sum(d["pop"][p] for p in parts)
                    put(f"{geo}:{g}", f"Labor force participation, ages {g}, {name}", y, sum(d["pop"][p] * d["rate"][p] for p in parts) / tot)
            older = [d["pop"][p] for p in ("55-59", "60-64", "65-74", "75+")]
            if d["pop16"] and all(older):
                put(f"{geo}:pop55+", f"People 55 and older as a share of the 16+ population, {name}", y, sum(older) / d["pop16"] * 100)
        print(f"  {y}: AK 16+ {got['AK']['rate16']}%, US {got['US']['rate16']}%")
    if not series:
        sys.exit("lfp-age: nothing returned")
    data = {"dashboard": "lfp-age", "source": "U.S. Census Bureau, American Community Survey 1-year estimates, table S2301",
            "fetched": date.today().isoformat(), "series": series}
    if OUT.exists() and json.loads(OUT.read_text()).get("series") == series:
        print("  lfp-age: no new data")
        return
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"  wrote {OUT.name}")


if __name__ == "__main__":
    main()
