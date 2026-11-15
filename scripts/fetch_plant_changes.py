"""Latest Alaska power plant changes, for the Electricity page.

Source: EIA's monthly generator inventory (Form EIA-860M) through the EIA API v2
route electricity/operating-generator-capacity. Needs EIA_API_KEY.

Writes site/data/electricity-plant-changes.json with:
- additions: Alaska generators with the most recent first-operation month, each
  labeled as a new plant, a backup unit (EIA status "standby/backup"), a
  replacement (another unit at the plant retired the same month), added capacity
  (plant total went up), or a new unit (no earlier inventory to compare with).
- retirements: generators that were in last run's inventory and are gone now.
- capacity_down: plants whose total capacity fell from one run to the next.
- inventory / plant_mw: this run's generators and plant totals, kept so the next
  run can find what changed.

Change-based labels (replacement, added capacity, retirements, capacity down)
come from comparing runs, so they build up over time. Keeps the old file if EIA fails.
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
        status = str(r.get("statusDescription") or r.get("status") or "")
        gens[gid] = {"plant": r.get("plantName"), "owner": r.get("entityName"), "mw": num(r.get("nameplate-capacity-mw")) or 0,
                     "fuel": FUEL.get(r.get("energy_source_code"), r.get("technology") or "Other"),
                     "backup": "standby" in status.lower() or "backup" in status.lower() or str(r.get("status")) == "SB",
                     "month": str(r.get("operating-year-month") or "")[:7]}
    if not gens:
        print("::warning::plant changes: empty inventory; kept old file"); return

    plant_of = lambda gid: gid.split(":")[0]
    plant_mw = {}
    for gid, g in gens.items():
        plant_mw[plant_of(gid)] = round(plant_mw.get(plant_of(gid), 0) + g["mw"], 1)

    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev_inv, prev_mw = old.get("inventory", {}), old.get("plant_mw", {})
    retired, down = old.get("retirements", []), old.get("capacity_down", [])
    labels = old.get("labels", {})  # generator id -> label decided when it first appeared
    new_period = bool(prev_inv) and old.get("period") != period
    if new_period:
        gone = {gid: g for gid, g in prev_inv.items() if gid not in gens}
        for gid, g in gone.items():
            retired.insert(0, {**g, "month": period, "id": gid})
        for pid, after in plant_mw.items():
            before = prev_mw.get(pid)
            if before is not None and after < before - 0.05:
                any_g = next(g for gid, g in gens.items() if plant_of(gid) == pid)
                down.insert(0, {"plant": any_g["plant"], "owner": any_g["owner"], "before": before, "after": after, "month": period, "id": pid})
        for pid, before in prev_mw.items():
            if pid not in plant_mw:  # whole plant gone
                g = next((g for gid, g in prev_inv.items() if plant_of(gid) == pid), {})
                down.insert(0, {"plant": g.get("plant"), "owner": g.get("owner"), "before": before, "after": 0, "month": period, "id": pid})
        for gid, g in gens.items():
            if gid in prev_inv or gid in labels:
                continue
            pid = plant_of(gid)
            if g["backup"]:
                labels[gid] = "backup"
            elif pid not in prev_mw:
                labels[gid] = "new_plant"
            elif any(plant_of(r) == pid for r in gone):
                labels[gid] = "replacement"
            elif plant_mw[pid] > prev_mw[pid] + 0.05:
                labels[gid] = "added"
            else:
                labels[gid] = "unit"

    adds = []
    for gid, g in sorted(gens.items(), key=lambda kv: kv[1]["month"], reverse=True)[:12]:
        if not g["month"]:
            continue
        pid = plant_of(gid)
        same = [x for x, y in gens.items() if plant_of(x) == pid]
        if gid in labels:
            lab = labels[gid]
        elif g["backup"]:
            lab = "backup"
        elif all(gens[x]["month"] == g["month"] for x in same):
            lab = "new_plant"
        else:
            lab = "unit"
        adds.append({**g, "id": gid, "label": lab, "plant_mw": plant_mw[pid], "plant_units": len(same)})

    data = {"source": "U.S. Energy Information Administration, Form EIA-860M, via EIA API v2",
            "url": "https://www.eia.gov/electricity/data/eia860m/", "period": period,
            "additions": adds, "retirements": retired[:12], "capacity_down": down[:12],
            "labels": labels, "plant_mw": plant_mw,
            "inventory": {gid: {k: g[k] for k in ("plant", "owner", "mw", "fuel", "backup")} for gid, g in gens.items()}}
    if {k: v for k, v in old.items() if k != "fetched"} == data:
        print("plant changes: no change"); return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"plant changes: {period}, {len(gens)} generators, {sum(g['backup'] for g in gens.values())} backup")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"::warning::plant changes: {e}"); sys.exit(0)
