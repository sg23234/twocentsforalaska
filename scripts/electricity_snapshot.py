"""Refresh the backup copy of the data saved inside site/electricity/index.html.

The Electricity page loads data/energy.json and data/electricity-utilities.json.
If those fail to load, it falls back to window.SNAPSHOT in the page. This keeps
that copy in step with the data files. Run after the fetch scripts.
"""
import json
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "electricity" / "index.html"
KEEP = ("AK-ALL", "US-ALL", "AK-ALL:sales", "US-ALL:sales")


def main():
    E = json.loads((SITE / "data" / "energy.json").read_text())
    U = json.loads((SITE / "data" / "electricity-utilities.json").read_text())
    snap = {"energy": {"series": {k: {"dates": v["dates"], "values": v["values"]}
                                  for k, v in E["series"].items() if k in KEEP}},
            "utilities": U}
    lines = PAGE.read_text().split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith("window.SNAPSHOT = ")]
    if len(idx) != 1:
        print("::warning::electricity snapshot line not found; skipped"); return
    new = "window.SNAPSHOT = " + json.dumps(snap, separators=(",", ":")) + ";"
    if lines[idx[0]] == new:
        print("electricity snapshot: no change"); return
    lines[idx[0]] = new
    PAGE.write_text("\n".join(lines))
    print("electricity snapshot: updated")


if __name__ == "__main__":
    main()
