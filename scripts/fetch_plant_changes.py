"""Latest Alaska power plant additions and retirements, for the Electricity page.

Source: EIA's monthly generator inventory (Form EIA-860M) through the EIA API v2
route electricity/operating-generator-capacity. Needs EIA_API_KEY.

- Additions: Alaska generators with the most recent first-operation month.
- Retirements: generators that were in last run's inventory but are gone from
  this one (found by comparing runs, so the list starts empty and fills over time).

Writes site/data/electricity-plant-changes.json. Keeps the old file if EIA fails.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "electricity-plant-changes.json"
URL = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}
FUEL = {"NG": "Natural gas", "DFO": "Diesel", "RFO": "Oil", "JF": "Oil", "KER": "Oil", "WO": "Oil", "PC": "Oil",
        "BIT": "Coal", "SUB": "Coal", "LIG": "Coal", "WC": "Coal", "WAT": "Hydro", "WND": "Wind", "SUN": "Solar",
        "MWH": "Battery", "LFG": "Landfill gas", "WDS": "Wood", "OBG": "Biogas"}


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
        print("::warning::plant changes: EIA_API_KEY not set; skipped"); return
    base = [("api_key", key), ("frequency", "monthly"), ("facets[stateid][]", "AK")]
    head = get(base + [("data[]", "nameplate-capacity-mw"), ("sort[0][column]", "period"),
                       ("sort[0][direction]", "desc"), ("length", "1")])
    rows = head.get("response", {}).get("data", [])
    if not rows:
        print("::warning::plant changes: no rows"); return
    period = rows[0]["period"]
    res = get(base + [("start", period), ("end", period), ("length", "5000"),
                      ("data[]", "nameplate-capacity-mw"), ("data[]", "operating-year-month")])
    rows = res.get("response", {}).get("data", [])
    gens = {}
    for r in rows:
        gid = f'{r.get("plantid")}:{r.get("generatorid")}'
        gens[gid] = {"plant": r.get("plantName"), "owner": r.get("entityName"), "mw": num(r.get("nameplate-capacity-mw")),
                     "fuel": FUEL.get(r.get("energy_source_code"), r.get("technology") or "Other"),
                     "month": str(r.get("operating-year-month") or "")[:7]}
    if not gens:
        print("::warning::plant changes: empty inventory; kept old file"); return
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev_ids = old.get("inventory", {})
    retired = old.get("retirements", [])
    if prev_ids and old.get("period") != period:
        for gid, g in prev_ids.items():
            if gid not in gens:
                retired.insert(0, {**g, "month": period, "id": gid})
    adds = sorted(({**g, "id": gid} for gid, g in gens.items() if g["month"]), key=lambda g: g["month"], reverse=True)[:12]
    data = {"source": "U.S. Energy Information Administration, Form EIA-860M, via EIA API v2",
            "url": "https://www.eia.gov/electricity/data/eia860m/", "period": period,
            "additions": adds, "retirements": retired[:12],
            "inventory": {gid: {k: g[k] for k in ("plant", "owner", "mw", "fuel")} for gid, g in gens.items()}}
    if {k: v for k, v in old.items() if k != "fetched"} == data:
        print("plant changes: no change"); return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"plant changes: {period}, {len(gens)} generators, latest addition {adds[0]['month'] if adds else '-'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"::warning::plant changes: {e}"); sys.exit(0)
