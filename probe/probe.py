"""One-time probe: inspect AOGCC Data Miner zips and NOAA degree-day sources. Writes probe/out.txt."""
import io, json, urllib.request, zipfile, csv, collections, traceback
UA = {"User-Agent": "twocentsforalaska.org data probe"}
out = []
def log(*a): out.append(" ".join(str(x) for x in a))
def get(url, n=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read() if n is None else r.read(n)
B = "https://aogcccdnstorage.blob.core.windows.net/dataminerzip/"
for name in ["storage", "facilities", "wellproductionpost2000", "wells"]:
    log(f"\n===== {name}.zip =====")
    try:
        raw = get(B + name + ".zip"); log("bytes", len(raw))
        z = zipfile.ZipFile(io.BytesIO(raw))
        for info in z.infolist():
            log("member", info.filename, info.file_size)
            with z.open(info) as f:
                data = f.read()
            for enc in ("utf-8-sig", "latin-1"):
                try: text = data.decode(enc); break
                except UnicodeDecodeError: continue
            lines = text.splitlines()
            log("lines", len(lines))
            for l in lines[:6]: log("  |", l[:600])
            try:
                rows = list(csv.reader(lines[:200000]))
                hdr = rows[0]
                for i, h in enumerate(hdr):
                    vals = collections.Counter(r[i] for r in rows[1:] if len(r) > i)
                    if len(vals) < 400:
                        log(f"  col {i} {h!r}: {len(vals)} distinct; top {vals.most_common(25)}")
                    else:
                        log(f"  col {i} {h!r}: {len(vals)} distinct; e.g. {list(vals)[:8]}")
                # Cook Inlet hints
                hits = [l for l in lines if "COOK" in l.upper() or "CINGSA" in l.upper() or "KENAI" in l.upper()]
                log("  rows mentioning COOK/CINGSA/KENAI:", len(hits))
                for l in hits[:15]: log("   >", l[:400])
                log("  last rows:")
                for l in lines[-4:]: log("   <", l[:400])
            except Exception as e:
                log("  csv parse failed", e)
    except Exception:
        log(traceback.format_exc()[-1500:])
for label, url in [
    ("acis daily", "https://data.rcc-acis.org/StnData?sid=ANC&sdate=2026-10-25&edate=2026-11-14&elems=%5B%7B%22name%22%3A%22hdd%22%7D%2C%7B%22name%22%3A%22hdd%22%2C%22normal%22%3A%221%22%7D%5D&output=json"),
    ("acis meta", "https://data.rcc-acis.org/StnMeta?sids=ANC&meta=name,sids,valid_daterange&elems=hdd&output=json"),
    ("cpc weekly", "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/cdus/degree_days/wctyhddy.txt"),
    ("pool stats", "http://aogweb.state.ak.us/PoolStatistics/"),
]:
    log(f"\n===== {label} =====")
    try:
        t = get(url).decode("utf-8", "replace")
        if label.startswith("cpc"):
            log("\n".join(t.splitlines()[:12])); log("\n".join(l for l in t.splitlines() if "ANCHORAGE" in l))
        else:
            log(t[:4000])
    except Exception:
        log(traceback.format_exc()[-800:])
open("probe/out.txt", "w").write("\n".join(out))
