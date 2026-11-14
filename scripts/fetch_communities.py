"""Community electricity rates from the Alaska Energy Data Gateway (UAF ACEP).

Dataset: "Yearly Electricity Rates For Communities" (v3), CC-BY-4.0.
https://akenergygateway.alaska.edu/explore/data/public_yearly_electric_rates
Built from the Alaska Energy Statistics workbooks (AEA Power Cost Equalization
reports plus EIA utility reporting). Annual, about a year behind.

Writes site/data/electricity-communities.json:
  {"source", "citation", "fetched", "years": [...], "fields": [...],
   "rows": [{fips_code, name, reporting_entity_name, year, residential_rate, ...}]}
Rates are kept exactly as published (see "units" in the file).
Standard library only. Keeps the previous file if the download fails.
"""
import csv, io, json, re, sys, time, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

PAGE = "https://akenergygateway.alaska.edu/explore/data/public_yearly_electric_rates"
FALLBACK = ("https://akenergygateway.alaska.edu/rails/active_storage/blobs/redirect/"
            "eyJfcmFpbHMiOnsiZGF0YSI6NTgsInB1ciI6ImJsb2JfaWQifX0=--4d6db1ad45a266605d95c038ac723e0e05fbbbd6/"
            "public_yearly_electric_rates.zip?disposition=attachment")
OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "electricity-communities.json"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}
RATE_FIELDS = ["residential_rate", "residential_rate_subsidized", "commercial_rate", "industrial_rate",
               "transportation_rate", "community_rate", "other_rate", "total_rate"]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise RuntimeError(f"{url[:80]}: {e}") from e
            time.sleep(10 * (i + 1))


def zip_url():
    """The download link changes when ACEP posts a new version, so read it off the page."""
    try:
        html = get(PAGE).decode("utf-8", "replace")
        m = re.search(r'href="([^"]*public_yearly_electric_rates\.zip[^"]*)"', html)
        if m:
            u = m.group(1).replace("&amp;", "&")
            return u if u.startswith("http") else "https://akenergygateway.alaska.edu" + u
    except Exception as e:
        print(f"::warning::AEDG page: {e}")
    return FALLBACK


def num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def main():
    try:
        z = zipfile.ZipFile(io.BytesIO(get(zip_url())))
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("utf-8-sig", "replace")
    except Exception as e:
        print(f"::error::community rates: {e}")
        sys.exit(1)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        for f in RATE_FIELDS:
            if f in r:
                r[f] = num(r[f])
        try:
            r["year"] = int(float(r.get("year", "")))
        except ValueError:
            continue
        rows.append(r)
    if not rows:
        print("::error::community rates: CSV had no rows")
        sys.exit(1)
    rates = [r["total_rate"] for r in rows if r.get("total_rate")]
    units = "dollars per kWh" if rates and max(rates) < 5 else "cents per kWh"
    data = {
        "source": "Alaska Energy Data Gateway, Alaska Center for Energy and Power (UAF): Yearly Electricity Rates For Communities",
        "citation": "Alaska Center for Energy and Power (ACEP) at the University of Alaska Fairbanks (UAF). Yearly Electricity Rates For Communities. Alaska Energy Data Gateway. " + PAGE + ". CC-BY-4.0.",
        "units": units,
        "years": sorted({r["year"] for r in rows}),
        "fields": list(rows[0].keys()),
        "rows": rows,
    }
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if old.get("rows") == rows:
        print("community rates: no new data")
        return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"community rates: {len(rows)} rows, years {data['years'][0]}–{data['years'][-1]}, {units}")


if __name__ == "__main__":
    main()
