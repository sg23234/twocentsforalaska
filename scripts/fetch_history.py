"""One-off: pull federal award totals for Alaska by fiscal year from USAspending
(FY2008 onward) into site/data/manual/usaspending-ak.json. Run by the
'History pull' workflow; safe to rerun."""
import json, time, urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "manual" / "usaspending-ak.json"
res = {"_about": "USAspending.gov award totals for Alaska recipients by federal fiscal year, dollars. From /api/v2/recipient/state/awards/02/.", "years": {}}
for fy in range(2008, 2027):
    url = f"https://api.usaspending.gov/api/v2/recipient/state/awards/02/?year={fy}"
    for t in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "data refresh script"}), timeout=60) as r:
                rows = json.load(r)
            res["years"][str(fy)] = {row["type"]: row.get("amount") for row in rows}
            print(fy, res["years"][str(fy)])
            break
        except Exception as e:
            print(fy, "retry", e); time.sleep(5)
OUT.write_text(json.dumps(res, indent=1) + "\n")
