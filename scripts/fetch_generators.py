"""Alaska power plants (1 MW and up) for the Electricity page map.

Source: EIA's monthly generator inventory (Form EIA-860M), through the EIA API v2
route electricity/operating-generator-capacity. Needs EIA_API_KEY (same key as
fetch_data.py). Keeps the latest month, Alaska only, and rolls generators up to
plants: location, owner, capacity by fuel, first year in service.

Writes site/data/generators.json. Leaves the old file alone if the request fails.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "generators.json"
URL = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}

FUEL = {  # EIA energy source code -> site category
    "NG": "gas", "LFG": "other", "OBG": "other",
    "DFO": "oil", "RFO": "oil", "JF": "oil", "KER": "oil", "WO": "oil", "PC": "oil",
    "BIT": "coal", "SUB": "coal", "LIG": "coal", "WC": "coal", "RC": "coal",
    "WAT": "hydro", "WND": "wind", "SUN": "solar", "MWH": "storage",
}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get(params, tries=3):
    url = URL + "?" + urllib.parse.urlencode(params)
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:
            err = e
            time.sleep(8 * (i + 1))
    raise RuntimeError(f"EIA request failed: {type(err).__name__}")


def main():
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        print("::warning::generators: EIA_API_KEY not set; skipped"); return
    base = [("api_key", key), ("frequency", "monthly"), ("facets[stateid][]", "AK")]
    # latest month available
    head = get(base + [("data[]", "nameplate-capacity-mw"), ("sort[0][column]", "period"),
                       ("sort[0][direction]", "desc"), ("length", "1")])
    rows = head.get("response", {}).get("data", [])
    if not rows:
        print(f"::warning::generators: no rows ({str(head)[:200]})"); return
    period = rows[0]["period"]
    res = get(base + [("start", period), ("end", period), ("length", "5000"),
                      ("data[]", "nameplate-capacity-mw"), ("data[]", "latitude"),
                      ("data[]", "longitude"), ("data[]", "operating-year-month")])
    rows = res.get("response", {}).get("data", [])
    print(f"generators: {period}, {len(rows)} generator rows; fields {sorted(rows[0].keys()) if rows else []}")
    plants = {}
    for r in rows:
        mw = num(r.get("nameplate-capacity-mw"))
        lat, lon = num(r.get("latitude")), num(r.get("longitude"))
        if not mw or lat is None or lon is None:
            continue
        pid = str(r.get("plantid") or r.get("plantName"))
        p = plants.setdefault(pid, {"id": pid, "name": r.get("plantName"), "owner": r.get("entityName"),
                                    "lat": round(lat, 4), "lon": round(lon, 4), "mix": {}, "year": None,
                                    "sector": r.get("sectorName") or r.get("sector")})
        f = FUEL.get(r.get("energy_source_code"), "other")
        p["mix"][f] = round(p["mix"].get(f, 0) + mw, 1)
        y = str(r.get("operating-year-month") or "")[:4]
        if y.isdigit() and (p["year"] is None or int(y) < p["year"]):
            p["year"] = int(y)
    out, totals = [], {}
    for p in plants.values():
        p["mw"] = round(sum(p["mix"].values()), 1)
        p["fuel"] = max(p["mix"], key=p["mix"].get)
        for f, v in p["mix"].items():
            totals[f] = round(totals.get(f, 0) + v, 1)
        out.append(p)
    if not out:
        print("::warning::generators: no plants with coordinates; kept old file"); return
    out.sort(key=lambda p: -p["mw"])
    data = {"source": "U.S. Energy Information Administration, Form EIA-860M (Monthly Update to the Annual Electric Generator Report), via EIA API v2",
            "url": "https://www.eia.gov/electricity/data/eia860m/", "period": period,
            "plants": out, "totals": dict(sorted(totals.items(), key=lambda x: -x[1])),
            "total_mw": round(sum(totals.values()), 1)}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "fetched"} == data:
        print("generators: no change"); return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"generators: {len(out)} plants, {data['total_mw']} MW")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"::warning::generators: {e}"); sys.exit(0)
