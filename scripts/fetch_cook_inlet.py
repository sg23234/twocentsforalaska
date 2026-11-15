"""Cook Inlet gas production and storage (AOGCC), and Anchorage heating degree days (NOAA).

Writes:
  site/data/cook-inlet.json   monthly gas production by field and storage injections/withdrawals
  site/data/anchorage-hdd.json daily heating degree days at Anchorage airport, with 1991-2020 normals

Sources:
  AOGCC Data Miner full-table downloads (updated daily; xlsx inside a zip):
    wellproductionpost2000.zip  monthly production by well since 2000
    storage.zip                 monthly injection/withdrawal by storage well
  NOAA Regional Climate Centers' ACIS web service (data.rcc-acis.org), station ANC.

Needs openpyxl. Each part runs on its own: if one source fails the other files still update,
and the script exits non-zero at the end.
"""
import calendar, collections, datetime as dt, io, json, os, sys, time, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data")
UA = {"User-Agent": "twocentsforalaska.org data refresh (github.com/sg23234/twocentsforalaska)"}
AOGCC = "https://aogcccdnstorage.blob.core.windows.net/dataminerzip/"
ACIS = "https://data.rcc-acis.org/StnData"
AREA = "COOK INLET BASIN"


def get(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(15 * (i + 1))


def xlsx_rows(name):
    import openpyxl
    z = zipfile.ZipFile(io.BytesIO(get(AOGCC + name + ".zip")))
    wb = openpyxl.load_workbook(io.BytesIO(z.read(z.namelist()[0])), read_only=True, data_only=True)
    it = wb[wb.sheetnames[0]].iter_rows(values_only=True)
    hdr = next(it)
    idx = {h: i for i, h in enumerate(hdr)}
    for r in it:
        yield {h: r[i] for h, i in idx.items()}


def month_key(v):
    """'9/1/2026 12:00:00 AM' or a datetime -> '2026-09'."""
    if isinstance(v, (dt.datetime, dt.date)):
        return f"{v.year}-{v.month:02d}"
    m, d, y = str(v).split()[0].split("/")
    return f"{int(y)}-{int(m):02d}"


def days(mk):
    y, m = map(int, mk.split("-"))
    return calendar.monthrange(y, m)[1]


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# Hand-picked display names; any field not listed uses AOGCC's name in title case.
FIELD_NAMES = {"BELUGA RIVER": "Beluga River", "NORTH COOK INLET": "North Cook Inlet", "NINILCHIK": "Ninilchik",
               "KENAI": "Kenai", "KITCHEN LIGHTS": "Kitchen Lights", "MCARTHUR RIVER": "McArthur River",
               "SWANSON RIVER": "Swanson River", "KENAI C.L.U.": "Kenai (Cannery Loop)", "IVAN RIVER": "Ivan River",
               "W MCARTHUR RIV": "West McArthur River", "GRANITE PT": "Granite Point", "MIDDLE GROUND SHOAL": "Middle Ground Shoal"}


def production():
    tot = collections.Counter()               # month -> mcf
    by_field = collections.defaultdict(collections.Counter)  # field -> month -> mcf
    ops = {}                                  # field -> (month, operator) of the latest row
    storage_status = collections.Counter()    # month -> mcf from wells whose status mentions storage
    for r in xlsx_rows("wellproductionpost2000"):
        if r.get("AreaName") != AREA:
            continue
        g = num(r.get("GasProduced"))
        mk = month_key(r["ReportDate"])
        f = r.get("FieldName") or "UNKNOWN"
        tot[mk] += g
        by_field[f][mk] += g
        if "torage" in str(r.get("WellStatus") or ""):
            storage_status[mk] += g
        if g > 0 and (f not in ops or mk >= ops[f][0]):
            ops[f] = (mk, r.get("OperatorName") or "")
    months = sorted(tot)
    # Drop a trailing month that looks partly reported (under 80% of the month before).
    while len(months) > 2 and tot[months[-1]] < 0.8 * tot[months[-2]]:
        months.pop()
    mmcfd = lambda mcf, mk: round(mcf / days(mk) / 1000, 2)
    fields = []
    last12 = months[-12:]
    for f, s in by_field.items():
        v12 = sum(s[m] for m in last12)
        if v12 <= 0:
            continue
        fields.append({"key": f, "name": FIELD_NAMES.get(f, f.title()), "operator": ops.get(f, ("", ""))[1],
                       "last12_bcf": round(v12 / 1e6, 3),
                       "values": [mmcfd(s[m], m) for m in months]})
    fields.sort(key=lambda x: -x["last12_bcf"])
    check = {m: {"all": mmcfd(tot[m], m), "excl_storage_status": mmcfd(tot[m] - storage_status[m], m)}
             for m in ["2020-01", "2021-02", "2024-08", "2025-01", "2025-03", "2025-12", "2026-01"] if m in tot}
    return {"months": [f"{m}-01" for m in months],
            "total_mmcfd": [mmcfd(tot[m], m) for m in months],
            "fields": fields, "_check": check}


STORAGE_GROUPS = [  # (label, test on a row)
    ("CINGSA", lambda r: "Cook Inlet Natural Gas Storage" in str(r.get("OperatorName")) or r.get("FieldName") == "KENAI C.L.U."),
    ("Hilcorp, Kenai field", lambda r: r.get("FieldName") == "KENAI"),
    ("Hilcorp, other fields", lambda r: True),
]


def storage():
    inj = collections.defaultdict(collections.Counter)
    wd = collections.defaultdict(collections.Counter)
    for r in xlsx_rows("storage"):
        if r.get("AreaName") != AREA:
            continue
        mk = month_key(r["ReportDate"])
        if mk < "2005-01":
            continue
        g = next(lbl for lbl, test in STORAGE_GROUPS if test(r))
        inj[g][mk] += num(r.get("GasInjected"))
        wd[g][mk] += num(r.get("GasProduced"))
    months = sorted({m for d in (inj, wd) for s in d.values() for m in s})
    groups = [{"name": lbl,
               "injected_bcf": [round(inj[lbl][m] / 1e6, 4) for m in months],
               "withdrawn_bcf": [round(wd[lbl][m] / 1e6, 4) for m in months]}
              for lbl, _ in STORAGE_GROUPS if any(inj[lbl][m] or wd[lbl][m] for m in months)]
    return {"months": [f"{m}-01" for m in months], "groups": groups}


def hdd():
    """Daily HDD and normal at Anchorage airport from two heating seasons back (July 1) to yesterday,
    plus each heating season's total since 1953 for context."""
    today = dt.date.today()
    season0 = today.year - (1 if today.month < 7 else 0)
    q = {"sid": "ANC", "sdate": f"{season0 - 1}-07-01", "edate": (today - dt.timedelta(days=1)).isoformat(),
         "elems": [{"name": "hdd"}, {"name": "hdd", "normal": "1"}]}
    d = json.loads(get(ACIS, data=json.dumps(q).encode(), headers={"Content-Type": "application/json"}))
    rows = [r for r in d["data"] if r[1] not in ("M", "")]
    q2 = {"sid": "ANC", "sdate": "1953-07", "edate": f"{today.year}-{today.month:02d}",
          "elems": [{"name": "hdd", "interval": "mly", "duration": "mly", "reduce": "sum"}]}
    m = json.loads(get(ACIS, data=json.dumps(q2).encode(), headers={"Content-Type": "application/json"}))["data"]
    seasons = collections.defaultdict(lambda: [0, 0])  # start year -> [hdd, months]
    for ym, v in m:
        y, mo = map(int, ym.split("-"))
        s = y if mo >= 7 else y - 1
        if v not in ("M", ""):
            seasons[s][0] += int(float(v)); seasons[s][1] += 1
    full = [{"season": f"{s}–{str(s + 1)[2:]}", "hdd": v[0]} for s, v in sorted(seasons.items()) if v[1] == 12]
    to_int = lambda v: int(float(v)) if v not in ("M", "", "T") else 0
    return {"station": d["meta"]["name"], "season_start": f"{season0}-07-01",
            "dates": [r[0] for r in rows], "hdd": [to_int(r[1]) for r in rows], "normal": [to_int(r[2]) for r in rows],
            "seasons": full}


def write(name, obj, source):
    obj = {"updated": dt.datetime.utcnow().strftime("%Y-%m-%d"), "source": source, **obj}
    with open(os.path.join(DATA, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    print("wrote", name)


def main():
    failed = []
    try:
        ci = {"production": production()}
        print("production check (MMcf/d):", json.dumps(ci["production"]["_check"]))
        try:
            ci["storage"] = storage()
        except Exception as e:
            failed.append(f"storage: {type(e).__name__}: {e}")
            try:  # keep the last good storage data
                ci["storage"] = json.load(open(os.path.join(DATA, "cook-inlet.json")))["storage"]
            except Exception:
                pass
        write("cook-inlet.json", ci, "Alaska Oil and Gas Conservation Commission, Data Miner (production and storage tables)")
    except Exception as e:
        failed.append(f"production: {type(e).__name__}: {e}")
    try:
        write("anchorage-hdd.json", hdd(), "NOAA Regional Climate Centers, Applied Climate Information System (ACIS); normals 1991-2020")
    except Exception as e:
        failed.append(f"hdd: {type(e).__name__}: {e}")
    if failed:
        print("FAILED:", *failed, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
