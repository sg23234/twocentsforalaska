"""Alaska electricity prices by utility, from EIA Form 861 (annual), plus region averages.

Downloads the newest final EIA-861 year (and the year before it, for the change),
reads "Sales to Ultimate Customers" (long form and short form), keeps Alaska
utilities, and works out average prices = revenue / kWh sold, by sector.

Region for each utility comes from site/data/manual/electricity-regions.json
(name patterns, edit by hand); its "exclude" list drops utilities entirely. Region averages are weighted by sales (total
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
STATES = {}
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
    """Rows from Sales_Ult_Cust (long form, EIA-861) and Short_Form (EIA-861S, small utilities).
    Sales_Ult_Cust_CS (customer-sited sales) is left out."""
    import openpyxl
    out = []
    DIAG["files"] = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
    names = [n for n in zf.namelist() if re.search(r"(sales_ult_cust|short_form)_\d{4}\.xlsx$", n, re.I)]
    if not names:
        raise RuntimeError(f"{year}: no Sales_Ult_Cust sheet in {DIAG['files'][:30]}")
    for name in names:
        wb = openpyxl.load_workbook(io.BytesIO(zf.read(name)), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        head = []
        for _ in range(6):
            r = next(rows)
            head.append(r)
            if any(str(c or "").strip().lower() == "utility name" for c in r):
                break
        else:
            raise RuntimeError(f"{name}: no 'Utility Name' header in first rows")
        low = head[-1]
        groups = [""] * len(low)
        for hr in head[:-1]:
            cur = ""
            for i in range(len(low)):
                if i < len(hr) and hr[i] not in (None, ""):
                    cur = str(hr[i]).strip().lower()
                groups[i] = (groups[i] + " " + cur).strip()
        cols = [(groups[i], str(low[i] or "").strip().lower().replace("\n", " ")) for i in range(len(low))]
        DIAG.setdefault("headers", {})[name] = cols[:40]
        def idx(pred):
            for i, c in enumerate(cols):
                if pred(*c): return i
            return None
        meta = {k: idx(lambda g, l, k=k: l == k) for k in ["utility number", "utility name", "service type", "state", "ownership"]}
        if meta["utility name"] is None or meta["state"] is None:
            raise RuntimeError(f"{name}: unexpected headers {cols[:12]}")
        units = {"rev": ("thousand",), "mwh": ("megawatt", "(mwh)"), "cust": ("count", "customers")}
        # Long form: sector in the group header, unit in the label. Short form: one label like "total sales (mwh)".
        sec = {s: {m: idx(lambda g, l, s=s, m=m: (s in g or (not g and l.startswith(s))) and any(u in l for u in units[m]))
                   for m in units} for s in SECTORS}
        n0 = len(out)
        for r in rows:
            nm = r[meta["utility name"]] if r and len(r) > meta["utility name"] else None
            if nm in (None, "") or str(nm).strip().lower() in ("withheld",) or str(nm).lower().startswith("adjustment"):
                continue
            g = lambda k: r[meta[k]] if meta[k] is not None and meta[k] < len(r) else None
            d = {"utility": str(nm).strip(), "state": str(g("state") or "").strip(), "id": g("utility number"),
                 "ownership": str(g("ownership") or "").strip(), "service": str(g("service type") or "").strip(),
                 "form": "861S" if "short" in name.lower() else "861"}
            for s, m in sec.items():
                for k, i in m.items():
                    d[f"{s}_{k}"] = num(r[i]) if i is not None and i < len(r) else None
            out.append(d)
        DIAG.setdefault("ak_rows", {})[name] = sum(1 for x in out[n0:] if x["state"] == "AK")
    return out


def price(rev_k, mwh):
    """thousand dollars / MWh -> cents per kWh."""
    return round(rev_k / mwh * 100, 2) if rev_k and mwh else None


def load_year(year):
    blob = get(ZIP.format(year))
    if not blob:
        return None
    return read_sales(zipfile.ZipFile(io.BytesIO(blob)), year)


COMPARE_STATES = ["AK", "HI", "WA"]


def summarize(rows, regions, exclude=()):
    """Delivery-only rows (retail-choice states) report the same kWh as the energy-only
    row for that customer, but only the wires charge as revenue. Their revenue counts;
    their kWh do not, so electricity is not counted twice. This matches EIA's own
    state and U.S. averages."""
    ak = {}
    us = {s: [0.0, 0.0] for s in SECTORS}
    st = {x: {s: [0.0, 0.0] for s in SECTORS} for x in COMPARE_STATES}
    for r in rows:
        delivery = r.get("service", "").lower().startswith("delivery")
        for s in SECTORS:
            rev, mwh = r.get(f"{s}_rev") or 0, 0 if delivery else (r.get(f"{s}_mwh") or 0)
            if rev or mwh:
                us[s][0] += rev; us[s][1] += mwh
                if r["state"] in st:
                    st[r["state"]][s][0] += rev; st[r["state"]][s][1] += mwh
        if r["state"] != "AK" or delivery:
            continue
        if any(re.search(p, r["utility"], re.I) for p in exclude):
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
    STATES.update({x: {s: price(*v) for s, v in d.items()} for x, d in st.items()})
    return ak, {s: price(*v) for s, v in us.items()}


US_OUT = ROOT / "electricity-us-utilities.json"


def write_us_utilities(rows, year, exclude=()):
    """Every U.S. utility's all-customer price and customer count, for the Electricity page scatter plots.

    Keeps bundled service only (utilities that both supply and deliver power, plus short-form filers).
    Energy-only and delivery-only rows in retail-choice states cover only part of a customer's bill,
    so their price per kWh is not comparable. Drops utilities under 50 customers and prices outside
    1-300 cents. One row per utility and state: [state, name, customers, cents per kWh].
    """
    acc = {}
    for r in rows:
        svc = (r.get("service") or "").lower()
        if svc and not svc.startswith("bundle"):
            continue
        if r["state"] == "AK" and any(re.search(p, r["utility"], re.I) for p in exclude):
            continue
        k = (r["state"], str(r.get("id") or r["utility"]))
        a = acc.setdefault(k, {"state": r["state"], "name": r["utility"], "rev": 0, "mwh": 0, "cust": 0})
        a["rev"] += r.get("total_rev") or 0; a["mwh"] += r.get("total_mwh") or 0; a["cust"] += r.get("total_cust") or 0
    out = []
    for a in acc.values():
        pr = price(a["rev"], a["mwh"])
        if not pr or not (1 <= pr <= 300) or a["cust"] < 50 or not a["state"]:
            continue
        out.append([a["state"], a["name"], int(a["cust"]), pr])
    out.sort(key=lambda x: (x[0], -x[2]))
    data = {"source": "U.S. Energy Information Administration, Form EIA-861 (Sales to Ultimate Customers, long and short form)",
            "url": "https://www.eia.gov/electricity/data/eia861/", "year": year,
            "note": "Bundled service only; utilities with 50 or more customers; all-customer price = revenue / kWh sold.",
            "fields": ["state", "utility", "customers", "cents_per_kwh"], "rows": out}
    old = json.loads(US_OUT.read_text()) if US_OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "fetched"} == data:
        print("us utilities: no change"); return
    data["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    US_OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"us utilities: {len(out)} rows written")


def region_for(name, regions):
    for reg, pats in regions.items():
        if reg.startswith("_"): continue
        if any(re.search(p, name, re.I) for p in pats):
            return reg
    return "Unassigned"


def main():
    cfg = json.loads(REGIONS.read_text())
    regions, exclude = cfg["regions"], cfg.get("exclude", [])
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
    ak, us = summarize(cur[1], regions, exclude)
    states_cur = dict(STATES)
    ak_prev, us_prev = summarize(prev[1], regions, exclude) if prev else ({}, {})
    utils = []
    for u in sorted(ak.values(), key=lambda u: -(u.get("total_price") or 0)):
        if not u.get("total_price"):
            continue
        o = {k: u.get(k) for k in ("utility", "id", "region", "ownership", "total_price", "commercial_price", "residential_price", "industrial_price")}
        o["customers"] = int(u.get("total_cust") or 0)
        o["sales_mwh"] = round(u.get("total_mwh") or 0)
        o["commercial_mwh"] = round(u.get("commercial_mwh") or 0) if u.get("commercial_price") else None
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
        "states": states_cur,
        "regions": dict(sorted(reg.items())),
        "unassigned": sorted(u["utility"] for u in utils if u["region"] == "Unassigned"),
        "utilities": utils,
        "rows_read": DIAG.get("ak_rows"),
    }
    write_us_utilities(cur[1], y, exclude)
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
