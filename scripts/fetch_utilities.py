"""Alaska electricity prices by utility, from EIA Form 861 (annual), plus region averages.

Downloads the newest final EIA-861 year (and the year before it, for the change),
reads "Sales to Ultimate Customers" (long form and short form), keeps Alaska
utilities, and works out average prices = revenue / kWh sold, by sector.

Region for each utility comes from site/data/manual/electricity-regions.json
(name patterns, edit by hand). Region averages are weighted by sales (total
revenue / total kWh across that region's utilities). U.S. averages come from the
same file, all states.

Writes site/data/electricity-utilities.json. Needs openpyxl (the workflow installs it).
Picks up a new year by itself: each run tries the most recent years first.
"""
import io, json, re, sys, time, urllib.request, zipfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "site" / "data"
OUT = ROOT / "electricity-utilities.json"
REGIONS = ROOT / "manual" / "electricity-regions.json"
ZIP = "https://www.eia.gov/electricity/data/eia861/zip/f861{}.zip"
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}
DIAG = {}
SECTORS = ["residential", "commercial", "industrial", "transportation", "total"]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:
            err = e
        time.sleep(10 * (i + 1))
    raise RuntimeError(f"{url}: {err}")


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def read_sales(zf, year):
    """Return list of dicts from Sales_Ult_Cust and Sales_Ult_Cust_CS sheets."""
    import openpyxl
    out = []
    DIAG["files"] = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
    names = [n for n in zf.namelist() if re.search(r"sales_ult_cust(_cs)?_\d{4}\.xlsx$", n, re.I)]
    if not names:
        raise RuntimeError(f"{year}: no Sales_Ult_Cust sheet in {zf.namelist()[:30]}")
    for name in names:
        wb = openpyxl.load_workbook(io.BytesIO(zf.read(name)), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        top, mid, low = next(rows), next(rows), next(rows)   # three header rows
        DIAG.setdefault("headers", {})[name] = [list(map(str, top[:12])), list(map(str, mid[:12])), list(map(str, low[:12]))]
        cols, group, sub = [], "", ""
        for i in range(len(low)):
            if top[i]: group = str(top[i]).strip().lower()
            if mid[i]: sub = str(mid[i]).strip().lower()
            cols.append((group, sub, str(low[i] or "").strip().lower()))
        def idx(pred):
            for i, c in enumerate(cols):
                if pred(*c): return i
            return None
        meta = {k: idx(lambda g, s, l, k=k: l == k) for k in
                ["data year", "utility number", "utility name", "service type", "state", "ownership"]}
        if meta["utility name"] is None or meta["state"] is None:
            raise RuntimeError(f"{name}: unexpected headers {cols[:12]}")
        sec = {}
        for s in SECTORS:
            sec[s] = {m: idx(lambda g, sb, l, s=s, m=m: s in g and l.startswith({"rev": "thousand", "mwh": "megawatt", "cust": "count"}[m]))
                      for m in ("rev", "mwh", "cust")}
        for r in rows:
            if not r or r[meta["utility name"]] in (None, "") or str(r[meta["utility name"]]).lower().startswith("adjustment"):
                continue
            d = {"utility": str(r[meta["utility name"]]).strip(), "state": str(r[meta["state"]] or "").strip(),
                 "id": r[meta["utility number"]], "ownership": str(r[meta["ownership"]] or "").strip() if meta["ownership"] is not None else "",
                 "service": str(r[meta["service type"]] or "").strip() if meta["service type"] is not None else ""}
            for s, m in sec.items():
                for k, i in m.items():
                    d[f"{s}_{k}"] = num(r[i]) if i is not None else None
            out.append(d)
        DIAG.setdefault("ak_rows", {})[name] = sum(1 for x in out if x["state"] == "AK")
    return out


def price(rev_k, mwh):
    """thousand dollars / MWh -> cents per kWh."""
    return round(rev_k / mwh * 100, 2) if rev_k and mwh else None


def load_year(year):
    blob = get(ZIP.format(year))
    if not blob:
        return None
    return read_sales(zipfile.ZipFile(io.BytesIO(blob)), year)


def summarize(rows, regions):
    ak = {}
    us = {s: [0.0, 0.0] for s in SECTORS}
    for r in rows:
        for s in SECTORS:
            if r.get(f"{s}_rev") and r.get(f"{s}_mwh"):
                us[s][0] += r[f"{s}_rev"]; us[s][1] += r[f"{s}_mwh"]
        if r["state"] != "AK":
            continue
        u = ak.setdefault(r["utility"], {"utility": r["utility"], "id": r["id"], "ownership": r["ownership"]})
        for s in SECTORS:
            for k in ("rev", "mwh", "cust"):
                v = r.get(f"{s}_{k}")
                if v is not None:
                    u[f"{s}_{k}"] = u.get(f"{s}_{k}", 0) + v
    for u in ak.values():
        u["region"] = region_for(u["utility"], regions)
        for s in SECTORS:
            u[f"{s}_price"] = price(u.get(f"{s}_rev"), u.get(f"{s}_mwh"))
    return ak, {s: price(*v) for s, v in us.items()}


def region_for(name, regions):
    for reg, pats in regions.items():
        if reg.startswith("_"): continue
        if any(re.search(p, name, re.I) for p in pats):
            return reg
    return "Unassigned"


def main():
    regions = json.loads(REGIONS.read_text())["regions"]
    this = date.today().year
    cur = prev = None
    for y in range(this - 1, this - 4, -1):
        try:
            rows = load_year(y)
        except Exception as e:
            print(f"::warning::EIA-861 {y}: {e}")
            rows = None
        if rows:
            cur = (y, rows); break
    if not cur:
        print("::error::no EIA-861 year found"); sys.exit(1)
    y = cur[0]
    try:
        p = load_year(y - 1)
        prev = (y - 1, p) if p else None
    except Exception as e:
        print(f"::warning::EIA-861 {y-1}: {e}")
    ak, us = summarize(cur[1], regions)
    ak_prev, us_prev = summarize(prev[1], regions) if prev else ({}, {})
    utils = []
    for u in sorted(ak.values(), key=lambda u: -(u.get("total_price") or 0)):
        if not u.get("total_price"):
            continue
        o = {k: u.get(k) for k in ("utility", "id", "region", "ownership", "total_price", "commercial_price", "residential_price", "industrial_price")}
        o["customers"] = int(u.get("total_cust") or 0)
        o["sales_mwh"] = round(u.get("total_mwh") or 0)
        pv = ak_prev.get(u["utility"], {}).get("total_price")
        o["prev_total_price"] = pv
        o["change_pct"] = round((u["total_price"] / pv - 1) * 100, 1) if pv else None
        utils.append(o)
    def regsum(d):
        acc = {}
        for u in d.values():
            if not u.get("total_rev") or not u.get("total_mwh"): continue
            a = acc.setdefault(u["region"], {"rev": 0, "mwh": 0, "cust": 0, "n": 0, "crev": 0, "cmwh": 0})
            a["rev"] += u["total_rev"]; a["mwh"] += u["total_mwh"]; a["cust"] += u.get("total_cust") or 0; a["n"] += 1
            if u.get("commercial_rev") and u.get("commercial_mwh"):
                a["crev"] += u["commercial_rev"]; a["cmwh"] += u["commercial_mwh"]
        return {k: {"avg_price": price(v["rev"], v["mwh"]), "commercial_price": price(v["crev"], v["cmwh"]),
                    "utilities": v["n"], "customers": int(v["cust"]), "sales_mwh": round(v["mwh"])} for k, v in acc.items()}
    reg, reg_prev = regsum(ak), regsum(ak_prev)
    for k, v in reg.items():
        pv = reg_prev.get(k, {}).get("avg_price")
        v["prev_avg_price"] = pv
        v["change_pct"] = round((v["avg_price"] / pv - 1) * 100, 1) if pv and v["avg_price"] else None
    data = {
        "source": "U.S. Energy Information Administration, Form EIA-861 Annual Electric Power Industry Report (Sales to Ultimate Customers, long and short form)",
        "url": "https://www.eia.gov/electricity/data/eia861/",
        "year": y, "prev_year": prev[0] if prev else None,
        "units": "cents per kWh (revenue / sales)",
        "us": us, "us_prev": us_prev,
        "regions": dict(sorted(reg.items())),
        "unassigned": sorted(u["utility"] for u in utils if u["region"] == "Unassigned"),
        "utilities": utils,
        "diagnostics": DIAG,
    }
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "fetched"} == data:
        print("utilities: no change"); return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"utilities: {y}, {len(utils)} Alaska utilities, {len(data['unassigned'])} unassigned")
    for n in data["unassigned"]:
        print(f"::warning::no region for {n} (add a pattern to data/manual/electricity-regions.json)")


if __name__ == "__main__":
    main()
