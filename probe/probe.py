"""One-time probe (2): read AOGCC xlsx tables and test ACIS degree days. Writes probe/out.txt."""
import io, json, urllib.request, zipfile, collections, traceback
import openpyxl
UA = {"User-Agent": "twocentsforalaska.org data probe"}
out = []
def log(*a): out.append(" ".join(str(x) for x in a))
def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()
B = "https://aogcccdnstorage.blob.core.windows.net/dataminerzip/"
def rows_of(name):
    z = zipfile.ZipFile(io.BytesIO(get(B + name + ".zip")))
    m = z.namelist()[0]
    wb = openpyxl.load_workbook(io.BytesIO(z.read(m)), read_only=True, data_only=True)
    log("sheets", wb.sheetnames)
    ws = wb[wb.sheetnames[0]]
    return list(ws.iter_rows(values_only=True))
def describe(name, rows, maxdistinct=300):
    hdr = rows[0]; body = rows[1:]
    log(f"rows {len(body)}  header {hdr}")
    for r in body[:5]: log("  ", r)
    for i, h in enumerate(hdr):
        c = collections.Counter(r[i] for r in body if len(r) > i)
        if len(c) <= maxdistinct: log(f"  col {i} {h!r}: {len(c)} distinct; top {c.most_common(40)}")
        else: log(f"  col {i} {h!r}: {len(c)} distinct; e.g. {[k for k,_ in c.most_common(6)]}")
for name in ["storage", "facilities"]:
    log(f"\n===== {name} =====")
    try:
        rows = rows_of(name); describe(name, rows)
        for r in rows[1:]:
            if any(isinstance(v, str) and ("CINGSA" in v.upper() or "KENAI" in v.upper() or "STORAGE" in v.upper() or "COOK" in v.upper()) for v in r):
                log("  hit", r)
        if name == "storage":
            log("  last 30 rows:"); [log("   ", r) for r in rows[-30:]]
    except Exception: log(traceback.format_exc()[-1500:])
log("\n===== wellproductionpost2000 =====")
try:
    rows = rows_of("wellproductionpost2000")
    hdr = rows[0]; log("header", hdr); [log("  ", r) for r in rows[1:6]]
    body = rows[1:]
    for i, h in enumerate(hdr):
        c = collections.Counter(r[i] for r in body)
        if len(c) <= 120: log(f"  col {i} {h!r}: {len(c)} distinct; top {c.most_common(120)}")
        else: log(f"  col {i} {h!r}: {len(c)} distinct; e.g. {[k for k,_ in c.most_common(8)]}")
    log("  last rows:"); [log("   ", r) for r in rows[-5:]]
except Exception: log(traceback.format_exc()[-1500:])
log("\n===== ACIS =====")
try:
    q = {"sid": "ANC", "sdate": "2026-10-25", "edate": "2026-11-14", "elems": [{"name": "hdd"}, {"name": "hdd", "normal": "1"}]}
    log(get("https://data.rcc-acis.org/StnData", data=json.dumps(q).encode(), headers={"Content-Type": "application/json"}).decode()[:3000])
    q = {"sid": "ANC", "sdate": "2025-07", "edate": "2026-10", "elems": [{"name": "hdd", "interval": "mly", "duration": "mly", "reduce": "sum"}, {"name": "hdd", "interval": "mly", "duration": "mly", "reduce": "sum", "normal": "1"}]}
    log(get("https://data.rcc-acis.org/StnData", data=json.dumps(q).encode(), headers={"Content-Type": "application/json"}).decode()[:3000])
except Exception: log(traceback.format_exc()[-1500:])
open("probe/out.txt", "w").write("\n".join(out))
