"""Freight rate index for Alaska: collect published freight rates and fuel surcharges,
log every change, and build a monthly index (base month = 100).

Writes
  site/data/freight-observations.json  every rate or surcharge seen, with the date it took effect
                                       and the document it came from. Append-only; the index is
                                       rebuilt from this log on each run.
  site/data/freight.json               monthly series for the Freight page: the index and its
                                       parts, fuel surcharges, hub air rates, benchmarks, and a
                                       table of current rates.
  site/data/status.json                (the "freight" entry) what each source returned.

Reads site/data/manual/freight.json for TOTE's rate increases, the Port of Alaska surcharge,
index weights and the base month.

Sources (all public, no keys):
  TOTE Maritime Alaska   STB tariff 501-A (found through the site's search API): Tacoma-Anchorage
                         truckload rates and the ocean fuel surcharge.
  Alaska Railroad        monthly fuel surcharge, with history back to 2005.
  Carlile Transportation fuel-surcharge history: road (weekly, from 2018), steamship (from 2009),
                         Southeast and Central barge, intra-Alaska air (from 2020).
  Northern Air Cargo     hub rates by weight break, and the current fuel surcharge.
  Everts Air Cargo       hub rates and fuel surcharge.
  Alaska Air Cargo       General Air Freight zone-to-zone rates (PDF linked from the rates page).
  USPS Notice 123        Alaska Bypass Service price.
  FRED                   BLS producer price indexes for freight; EIA West Coast diesel price.

Each source runs on its own: a failure is recorded in status.json and the rest still update.
Past rates from the Internet Archive's Wayback Machine are added with --backfill (run once,
or occasionally); they go into the same observation log.

Usage
  python3 scripts/fetch_freight.py              # collect current rates, rebuild the index
  python3 scripts/fetch_freight.py --backfill   # also read past NAC and Everts rate pages from the Wayback Machine
  python3 scripts/fetch_freight.py --rebuild    # rebuild freight.json from the log without fetching
"""
import calendar
import csv
import datetime as dt
import gzip
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
LOG = DATA / "freight-observations.json"
OUT = DATA / "freight.json"
MANUAL = DATA / "manual" / "freight.json"
UA = {"User-Agent": "Mozilla/5.0 (twocentsforalaska.org data refresh; github.com/sg23234/twocentsforalaska)",
      "Accept-Encoding": "gzip"}

URL = {
    "arrc": "https://www.alaskarailroad.com/freight/customer-tools",
    "carlile": "https://www.carlile.biz/fuel-surcharge-history/",
    "tote_media": "https://www.totemaritime.com/wp-json/wp/v2/media?search=501-A&per_page=10&_fields=date,source_url",
    "nac_rates": "https://www.nac.aero/rates/",
    "nac_fsc": "https://www.nac.aero/fuel-surcharge/",
    "everts": "https://evertsair.com/cargo/rates",
    "aac_rates": "https://public.alaskacargo.com/services/rates",
    "usps_n123": "https://pe.usps.com/text/dmm300/Notice123.pdf",
    "fred": "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}",
    "cdx": "https://web.archive.org/cdx/search/cdx?url={}&output=json&fl=timestamp,statuscode,digest&collapse=digest&filter=statuscode:200",
    "wayback": "https://web.archive.org/web/{}id_/{}",
}
FRED = {
    "PCU483111483111": "Deep sea freight transportation",
    "PCU482111482111": "Line-haul railroads",
    "PCU484121484121": "General freight trucking, long-distance truckload",
    "PCU481112481112": "Scheduled freight air transportation",
    "GASDESWCW": "Diesel, West Coast, weekly retail price",
}
HUBS = {"Bethel": "BET", "Nome": "OME", "Kotzebue": "OTZ", "Aniak": "ANI", "Dillingham": "DLG",
        "King Salmon": "AKN", "Unalakleet": "UNK", "Barrow": "BRW", "Deadhorse": "SCC", "Fairbanks": "FAI"}
TODAY = dt.date.today()


# ---------------------------------------------------------------- fetching and text helpers

def get(url, tries=3, timeout=120):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
                    b = gzip.decompress(b)
                return b
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def pdf_text(b):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)


def text_lines(b):
    s = b.decode("utf-8", "ignore") if isinstance(b, bytes) else b
    s = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "\n", s)).replace("\xa0", " ")
    return [ln.strip() for ln in s.split("\n") if ln.strip()]


def tables(b):
    s = b.decode("utf-8", "ignore") if isinstance(b, bytes) else b
    out = []
    for t in re.findall(r"<table\b.*?</table>", s, re.S | re.I):
        rows = []
        for r in re.findall(r"<tr\b.*?</tr>", t, re.S | re.I):
            cells = re.findall(r"<t[dh](?:\s[^>]*)?>(.*?)</t[dh]>", r, re.S | re.I)
            rows.append([" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ").split()) for c in cells])
        out.append(rows)
    return out


def pct(s):
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def num(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(s):
    s = (s or "").strip().replace(",", ", ").replace("  ", " ")
    for f in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%m.%d.%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})/(\d{2})(\d{4})", s)          # "04/302025" typo in Carlile's table
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


def month_of(name_year):
    """'December 2026' -> '2026-12'."""
    try:
        d = dt.datetime.strptime(" ".join(name_year.split()), "%B %Y")
        return f"{d.year}-{d.month:02d}"
    except ValueError:
        return None


# ---------------------------------------------------------------- parsers (pure: content in, values out)

def parse_arrc(b):
    """Alaska Railroad: {'YYYY-MM': percent} from the percentage-based tables."""
    out = {}
    for t in tables(b):
        if not t or "percentage" not in " ".join(t[0]).lower():
            continue
        for r in t:
            if len(r) >= 2 and month_of(r[0]) and "%" in r[1]:
                out[month_of(r[0])] = pct(r[1])
    return out


CARLILE_KIND = [("Road", "road"), ("Water", "ocean"), ("Kodiak", "kodiak"), ("Barge (S.E", "se_barge"),
                ("Barge (Central", "central_barge"), ("Air", "air")]


def parse_carlile(b):
    """Carlile: {kind: [(start, end, percent)]}. 'ocean' is the steamship (Water) base rate."""
    out = {}
    for t in tables(b):
        for r in t:
            if len(r) < 4:
                continue
            kind = next((k for p, k in CARLILE_KIND if r[0].startswith(p)), None)
            a, z, v = parse_date(r[1]), parse_date(r[2]), pct(r[3])
            if kind and a and z and v is not None:
                out.setdefault(kind, []).append((min(a, z), max(a, z), v))
    return out


def parse_nac_rates(b):
    """Northern Air Cargo rates page (current or archived): effective date and {hub: {break: $/lb}}."""
    L = text_lines(b)
    eff = None
    for ln in L:
        m = re.search(r"Rates effective ([A-Z][a-z]+ \d{1,2}, \d{4})", ln)
        if m:
            eff = parse_date(m.group(1))
            break
    try:
        i = next(i for i, ln in enumerate(L) if ln == "Minimum" and i + 1 < len(L) and "lb" in L[i + 1])
    except StopIteration:
        return {"effective": eff, "rates": {}}
    breaks, j = [], i + 1
    while j < len(L) and re.fullmatch(r"(\d+) lb\. Rate", L[j]):
        breaks.append(re.fullmatch(r"(\d+) lb\. Rate", L[j]).group(1)); j += 1
    rates = {}
    while j + 1 < len(L) and L[j + 1].startswith("$"):        # each row: name, minimum charge, one rate per break
        vals = [num(x) for x in L[j + 2:j + 2 + len(breaks)]]
        if L[j] in HUBS and all(v is not None for v in vals):
            rates[HUBS[L[j]]] = dict(zip(breaks, vals))
        j += 2 + len(breaks)
    return {"effective": eff, "rates": rates}


def parse_nac_fsc(b):
    L = text_lines(b)
    for i, ln in enumerate(L):
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", ln)
        if m and i + 1 < len(L):
            e = re.search(r"effective\s+(\d{1,2}/\d{1,2}/\d{4})", L[i + 1], re.I)
            if e:
                return float(m.group(1)), parse_date(e.group(1))
    return None, None


def parse_everts(b):
    """Everts: Anchorage-origin effective date, {hub: {break: $/lb}}, and fuel surcharge."""
    L = text_lines(b)
    out = {"effective": None, "rates": {}, "fsc": None, "fsc_effective": None}
    try:
        i = next(i for i, ln in enumerate(L) if ln.startswith("Anchorage To"))
    except StopIteration:
        return out
    for ln in L[max(0, i - 6):i]:
        m = re.search(r"Rates effective ([A-Z][a-z]+ \d{1,2}, \d{4})", ln)
        if m:
            out["effective"] = parse_date(m.group(1))
    hdr, j = [], i + 1
    while j < len(L) and not re.search(r"\([A-Z]{3}\)$", L[j]):
        if re.fullmatch(r"Rate Per #", L[j]):
            hdr.append("1")
        elif re.fullmatch(r"(\d+) #", L[j]):
            hdr.append(re.fullmatch(r"(\d+) #", L[j]).group(1))
        j += 1
    while j < len(L) and re.search(r"\(([A-Z]{3})\)$", L[j]):
        code = re.search(r"\(([A-Z]{3})\)$", L[j]).group(1)
        k = j + 1 + (1 if L[j + 1] in ("General", "Priority") else 0)
        vals = [num(x) for x in L[k:k + len(hdr)]]
        if hdr and all(v is not None for v in vals):
            out["rates"][code] = dict(zip(hdr, vals))
        j = k + len(hdr)
    for ln in L[j:j + 12]:
        m = re.search(r"Fuel Surcharge\s*\W*\s*(\d+(?:\.\d+)?)%,?\s*effective ([A-Z][a-z]+ \d{1,2}, \d{4})", ln)
        if m:
            out["fsc"], out["fsc_effective"] = float(m.group(1)), parse_date(m.group(2))
            break
    return out


def parse_aac(text):
    """Alaska Air Cargo General Air Freight PDF: effective date and {(from, to): $/lb}."""
    eff = re.search(r"effective ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out, frm = {}, None
    for ln in lines:
        if re.fullmatch(r"\d{1,2}", ln):
            frm = int(ln)
        elif ln.startswith("Per lb") and frm:
            for to, tok in enumerate(ln.split()[2:], start=1):
                v = num(tok)
                if v is not None:
                    out[f"{frm}-{to}"] = v
    return {"effective": parse_date(eff.group(1)) if eff else None, "rates": out}


TOTE_ITEMS = {"2300": "Groceries/foodstuff", "2420": "Freight, all kinds", "2132": "Building materials"}


def parse_tote(text, url=""):
    rates = {}
    for m in re.finditer(r"NORTHBOUND\s*(?:\([A-Z]\)\s*)?\$([\d,]+)\s*SOUTHBOUND\s*(?:\([A-Z]\)\s*)?\$([\d,]+)\s*(\d{4})", text):
        rates.setdefault(m.group(3), num(m.group(1)))
    f = re.search(r"subject to an increase of\s+[a-z\- ]+?\s*percent\s*\((\d+(?:\.\d+)?)%\)", text)
    e = re.search(r"Effective[-_ ](\d{1,2}[.\-]\d{1,2}[.\-]\d{4})", url)
    return {"effective": parse_date(e.group(1).replace("-", ".")) if e else None,
            "fsc": float(f.group(1)) if f else None, "rates": {k: rates[k] for k in TOTE_ITEMS if k in rates}}


def parse_bypass(text):
    p = re.search(r"Alaska Bypass Service\s*Weight Not Over\s*\(pounds\)\s*70\s*\$([\d.]+)", text)
    e = re.search(r"Notice 123\s*\W*\s*Effective ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    return (float(p.group(1)) if p else None), (parse_date(e.group(1)) if e else None)


# ---------------------------------------------------------------- observation log

def load_log():
    return json.loads(LOG.read_text()) if LOG.exists() else {"about": "Every freight rate or surcharge seen by scripts/fetch_freight.py. "
            "'effective' is the date the carrier says it took effect, or, when it gives none, the date the page was seen.", "observations": []}


def observe(log, source, key, value, effective, url, seen=None, until=None):
    """Add an observation unless it repeats the latest one for this source and key."""
    if value is None:
        return False
    seen = (seen or TODAY).isoformat()
    eff = (effective.isoformat() if isinstance(effective, dt.date) else effective) or seen
    obs = log["observations"]
    same = [o for o in obs if o["source"] == source and o["key"] == key]
    if any(o["effective"] == eff and o["value"] == value for o in same):
        return False
    o = {"source": source, "key": key, "value": value, "effective": eff, "seen": seen, "url": url}
    if until:
        o["until"] = until.isoformat()
    obs.append(o)
    obs.sort(key=lambda o: (o["source"], o["key"], o["effective"], o["seen"]))
    return True


def compact(log):
    """Keep only changes: within each source and key, drop an observation whose value repeats the one before it
    (by effective date). The kept one inherits the dropped ones' end date, so Carlile's ranges stay whole."""
    out, groups = [], {}
    for o in log["observations"]:
        groups.setdefault((o["source"], o["key"]), []).append(o)
    for (_, _), obs in sorted(groups.items()):
        obs.sort(key=lambda o: (o["effective"], o["seen"]))
        for o in obs:
            if out and (out[-1]["source"], out[-1]["key"]) == (o["source"], o["key"]) and out[-1]["value"] == o["value"]:
                if o.get("until") and o["until"] > out[-1].get("until", ""):
                    out[-1]["until"] = o["until"]
                continue
            out.append(dict(o))
    log["observations"] = out
    return log


def history(log, source, key):
    return sorted((o["effective"], o["value"]) for o in log["observations"] if o["source"] == source and o["key"] == key)


# ---------------------------------------------------------------- collectors (each one fetches and logs)

def c_arrc(log):
    b = get(URL["arrc"])
    rows = parse_arrc(b)
    if len(rows) < 12:
        raise RuntimeError(f"railroad table not found ({len(rows)} rows)")
    for m, v in rows.items():
        observe(log, "arrc", "fsc", v, m + "-01", URL["arrc"])
    return max(rows)


def c_carlile(log):
    b = get(URL["carlile"])
    t = parse_carlile(b)
    if "road" not in t or "ocean" not in t:
        raise RuntimeError("road or steamship table not found")
    for kind, rows in t.items():
        for a, z, v in rows:
            observe(log, "carlile", kind, v, a, URL["carlile"], until=z)
    return max(a for a, _, _ in t["road"]).isoformat()


def c_tote(log):
    """Every 501-A revision TOTE still posts (newest first); each one's rates and ocean fuel surcharge are logged."""
    media = sorted(json.loads(get(URL["tote_media"])), key=lambda m: m["date"], reverse=True)
    media = [m for m in media if "501-A" in m["source_url"]]
    if not media:
        raise RuntimeError("no tariff 501-A found through the site search")
    seen_urls = {o["url"] for o in log["observations"] if o["source"] == "tote"}
    latest = None
    for i, m in enumerate(media):
        url = m["source_url"]
        if i and url in seen_urls:
            continue
        r = parse_tote(pdf_text(get(url)), url)
        eff = r["effective"] or dt.date.fromisoformat(m["date"][:10])     # no date in the file name: use the upload date
        if not r["rates"] or r["fsc"] is None:
            if i == 0:
                raise RuntimeError("tariff 501-A rates or fuel surcharge not found in " + url)
            continue
        for item, v in r["rates"].items():
            observe(log, "tote", item, v, eff, url)
        observe(log, "tote", "fsc", r["fsc"], eff, url)
        latest = latest or eff
    return latest.isoformat()


def c_nac(log):
    r = parse_nac_rates(get(URL["nac_rates"]))
    if not r["rates"]:
        raise RuntimeError("hub rate table not found")
    for hub, br in r["rates"].items():
        for w, v in br.items():
            observe(log, "nac", f"{hub}:{w}", v, r["effective"], URL["nac_rates"])
    f, fe = parse_nac_fsc(get(URL["nac_fsc"]))
    if f is None:
        raise RuntimeError("fuel surcharge not found (rates were saved)")
    observe(log, "nac", "fsc", f, fe, URL["nac_fsc"])
    return (fe or TODAY).isoformat()


def c_everts(log):
    r = parse_everts(get(URL["everts"]))
    if not r["rates"]:
        raise RuntimeError("Anchorage rate table not found")
    for hub, br in r["rates"].items():
        for w, v in br.items():
            observe(log, "everts", f"{hub}:{w}", v, r["effective"], URL["everts"])
    observe(log, "everts", "fsc", r["fsc"], r["fsc_effective"], URL["everts"])
    return (r["fsc_effective"] or r["effective"] or TODAY).isoformat()


def c_aac(log):
    page = get(URL["aac_rates"]).decode("utf-8", "ignore")
    m = re.search(r'href="([^"]*/General_Rates[^"]*\.pdf)"', page, re.I)
    if not m:
        raise RuntimeError("General Air Freight PDF link not found")
    url = urllib.parse.urljoin(URL["aac_rates"], m.group(1))
    r = parse_aac(pdf_text(get(url)))
    for lane in ("4-2", "2-1", "4-3", "4-1"):     # Seattle->Anchorage, Anchorage->rural, Seattle->Southeast, Seattle->rural
        observe(log, "aac", lane, r["rates"].get(lane), r["effective"], url)
    if "4-2" not in r["rates"]:
        raise RuntimeError("zone 4 to zone 2 rate not found")
    return (r["effective"] or TODAY).isoformat()


def c_usps(log):
    p, e = parse_bypass(pdf_text(get(URL["usps_n123"])))
    if p is None:
        raise RuntimeError("Alaska Bypass price not found in Notice 123")
    observe(log, "usps", "bypass70", p, e, URL["usps_n123"])
    return (e or TODAY).isoformat()


def c_fred(log, fred):
    for sid in FRED:
        rows = list(csv.reader(io.StringIO(get(URL["fred"].format(sid)).decode())))[1:]
        fred[sid] = [(d, float(v)) for d, v in rows if v not in ("", ".")]
    return max(v[-1][0] for v in fred.values())


def backfill(log):
    """Past NAC and Everts rate pages from the Wayback Machine."""
    added = 0
    for src, page, parse in (("nac", URL["nac_rates"], parse_nac_rates), ("everts", URL["everts"], parse_everts)):
        bare = page.split("://", 1)[1].replace("www.", "")
        snaps = json.loads(get(URL["cdx"].format(urllib.parse.quote(bare, safe=""))))[1:]
        print(f"{src}: {len(snaps)} archived versions")
        for ts, _, _ in snaps:
            try:
                b = get(URL["wayback"].format(ts, page), tries=1, timeout=40)
            except Exception as e:
                print(f"  {ts}: {type(e).__name__}"); continue
            r = parse(b)
            seen = dt.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
            for hub, br in r["rates"].items():
                for w, v in br.items():
                    added += observe(log, src, f"{hub}:{w}", v, r["effective"] or seen, f"https://web.archive.org/web/{ts}/{page}", seen=seen)
            if src == "everts" and r.get("fsc") is not None:
                added += observe(log, src, "fsc", r["fsc"], r["fsc_effective"] or seen, f"https://web.archive.org/web/{ts}/{page}", seen=seen)
            print(f"  {ts}: effective {r['effective']}, {len(r['rates'])} hubs")
            time.sleep(2)
    return added


# ---------------------------------------------------------------- monthly series and the index

def months(a, b):
    y, m = map(int, a.split("-"))
    out = []
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def step_at(hist, day):
    """Value in effect on a day (ISO string) from [(effective, value)] sorted."""
    v = None
    for e, x in hist:
        if e <= day:
            v = x
        else:
            break
    return v


def monthly_from_ranges(rows):
    """Day-weighted monthly average of [(start, end, value)] (start/end ISO). Months less than half covered are dropped."""
    day = {}
    for a, z, v in sorted(rows):
        d, z = dt.date.fromisoformat(a), dt.date.fromisoformat(z)
        while d <= z:
            day[d] = v
            d += dt.timedelta(days=1)
    by = {}
    for d, v in day.items():
        by.setdefault(f"{d.year}-{d.month:02d}", []).append(v)
    return {m: sum(v) / len(v) for m, v in by.items() if len(v) >= calendar.monthrange(int(m[:4]), int(m[5:]))[1] / 2}


def carlile_monthly(log, kind, notes):
    """Monthly averages from Carlile's dated ranges. If the table stops before this month, the last
    rate is carried forward (and a note says so), since the surcharge stays in force until changed."""
    obs = sorted((o["effective"], o.get("until") or o["effective"], o["value"]) for o in log["observations"]
                 if o["source"] == "carlile" and o["key"] == kind)
    if not obs:
        return {}
    # Each rate runs until the next one starts (the table has a few gaps and overlaps); the latest runs to its stated end.
    rows = []
    for i, (a, z, v) in enumerate(obs):
        nxt = (dt.date.fromisoformat(obs[i + 1][0]) - dt.timedelta(days=1)).isoformat() if i + 1 < len(obs) else z
        if (dt.date.fromisoformat(nxt) - dt.date.fromisoformat(z)).days > 45:     # a gap in the table: leave it empty
            nxt = z
        rows.append((a, max(a, nxt), v))
    end = obs[-1][1]
    if end < TODAY.isoformat():
        rows.append(((dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat(), TODAY.isoformat(), obs[-1][2]))
        if (TODAY - dt.date.fromisoformat(end)).days > 21:
            nm = {"air": "in-state air", "se_barge": "Southeast barge", "central_barge": "Central Alaska barge", "road": "road", "ocean": "steamship"}.get(kind, kind)
            notes.append(f"Carlile's {nm} surcharge was last posted for {dt.date.fromisoformat(end):%b %-d, %Y}; its last rate ({obs[-1][2]:g}%) is carried forward.")
    else:
        rows[-1] = (rows[-1][0], TODAY.isoformat(), rows[-1][2])
    return monthly_from_ranges(rows)


def mid(m):
    return m + "-15"


def ser(label, units, freq, kind, pairs, source=""):
    pairs = [(d, round(v, 4)) for d, v in pairs if v is not None]
    return {"label": label, "units": units, "freq": freq, "kind": kind, "source": source,
            "dates": [d for d, _ in pairs], "values": [v for _, v in pairs]}


def build(log, fred, manual, status):
    S, notes = {}, []
    last_m = f"{TODAY.year}-{TODAY.month:02d}"

    # Fuel surcharges, monthly
    arrc = {o[0][:7]: o[1] for o in history(log, "arrc", "fsc")}
    fsc = {"rail": arrc}
    for kind in ("road", "ocean", "air", "se_barge", "central_barge"):
        fsc[kind] = carlile_monthly(log, kind, notes)
    names = {"rail": ("Alaska Railroad", "Alaska Railroad"), "road": ("Truck, Lower 48 to Alaska road system (Carlile)", "Carlile"),
             "ocean": ("Steamship, Tacoma to Southcentral (Carlile)", "Carlile"), "air": ("Air, within Alaska (Carlile)", "Carlile"),
             "se_barge": ("Barge, Southeast Alaska (Carlile)", "Carlile"), "central_barge": ("Barge, Central Alaska (Carlile)", "Carlile")}
    tote_fsc = history(log, "tote", "fsc")
    if tote_fsc:
        since = manual.get("tote_fsc_since", {}).get("date")
        if since and since < tote_fsc[0][0]:
            tote_fsc = [(since, tote_fsc[0][1])] + tote_fsc
        fsc["tote"] = {m: step_at(tote_fsc, mid(m)) for m in months(tote_fsc[0][0][:7], last_m)}
        names["tote"] = ("Ocean, Tacoma to Anchorage (TOTE)", "TOTE Maritime Alaska")
    for k, d in fsc.items():
        S[f"fsc:{k}"] = ser(f"Fuel surcharge: {names[k][0]}", "percent", "monthly", "pct", [(m + "-01", d[m]) for m in sorted(d) if m <= last_m], names[k][1])

    # Hub air rates (1,000 lb break), monthly step series
    hubs = manual.get("hubs", {})
    for src, nm in (("nac", "Northern Air Cargo"), ("everts", "Everts Air Cargo")):
        for code, city in hubs.items():
            h = history(log, src, f"{code}:1000")
            if h:
                S[f"rate:{src}:{code}"] = ser(f"{nm}, Anchorage to {city}, 1,000 lb", "dollars per pound", "monthly", "rate",
                                              [(m + "-01", step_at(h, mid(m))) for m in months(h[0][0][:7], last_m)], nm)

    # One 1,000 lb pallet, Anchorage to Bethel, Northern Air Cargo: base rate x (1 + fuel surcharge) x federal tax.
    # NAC posts only its current surcharge; earlier months use Carlile's in-state air surcharge.
    bet, nfsc = history(log, "nac", "BET:1000"), history(log, "nac", "fsc")
    pal = []
    for m in months("2020-01", last_m):
        r = step_at(bet, mid(m))
        f = step_at(nfsc, mid(m)) if nfsc and mid(m) >= nfsc[0][0] else fsc["air"].get(m)
        if r is not None and f is not None:
            pal.append((m + "-01", 1000 * r * (1 + f / 100) * 1.0625))
    S["pallet:nac:BET"] = ser("1,000 lb pallet, Anchorage to Bethel, Northern Air Cargo, delivered", "dollars", "monthly", "level", pal, "Northern Air Cargo; Carlile")

    # Diesel and producer price indexes
    if fred.get("GASDESWCW"):
        by = {}
        for d, v in fred["GASDESWCW"]:
            by.setdefault(d[:7], []).append(v)
        S["diesel:wc"] = ser("Diesel, West Coast retail, monthly average", "dollars per gallon", "monthly", "rate",
                             [(m + "-01", sum(v) / len(v)) for m, v in sorted(by.items())], "EIA via FRED")
    for sid, lab in FRED.items():
        if sid.startswith("PCU") and fred.get(sid):
            S[f"ppi:{sid}"] = ser("PPI: " + lab, "index", "monthly", "index", [(d, v) for d, v in fred[sid] if d >= "2015"], "BLS via FRED")

    # ---- index parts, monthly from start_month
    M = months(manual["start_month"], last_m)
    gri = sorted((r["effective"], r["pct"]) for r in manual["tote_gri"]["rows"])
    pamp = sorted((r["effective"], r["value"]) for r in manual["pamp_per_container"]["rows"])
    tote = history(log, "tote", "2300")

    def tote_rate(m):
        """TOTE groceries rate (Item 2300, 40' northbound), carried back with the GRIs before the earliest tariff seen."""
        if not tote:
            return None
        day = mid(m)
        if day >= tote[0][0]:
            return step_at(tote, day)
        f = 1.0
        for e, p in gri:
            if day < e <= tote[0][0]:
                f *= 1 + p / 100
        return tote[0][1] / f

    part = {"ocean": {}, "rail": {}, "truck": {}, "lastmile": {}}
    for m in M:
        r, o = tote_rate(m), fsc.get("tote", {}).get(m)
        if r is not None and o is not None:
            part["ocean"][m] = r * (1 + o / 100) + (step_at(pamp, mid(m)) or 0)
        if m in fsc["rail"]:
            part["rail"][m] = 1 + fsc["rail"][m] / 100
        if m in fsc["road"]:
            part["truck"][m] = 1 + fsc["road"][m] / 100
        # Last mile: hub air rates (NAC and Everts, 1,000 lb) x intra-Alaska air fuel surcharge.
        a = fsc["air"].get(m)
        rel = []
        for src in ("nac", "everts"):
            vals = [step_at(history(log, src, f"{c}:1000"), mid(m)) for c in hubs]
            if a is not None and all(v is not None for v in vals):
                rel.append((src, sum(vals) / len(vals) * (1 + a / 100)))
        if rel:
            part["lastmile"][m] = dict(rel)

    base = manual["base_month"]
    w = manual["weights"]

    def rebase(d):
        return {m: v / d[base] * 100 for m, v in d.items()} if base in d else {}

    oc, ra, tr = rebase(part["ocean"]), rebase(part["rail"]), rebase(part["truck"])
    lm_by = {src: rebase({m: v[src] for m, v in part["lastmile"].items() if src in v}) for src in ("nac", "everts")}
    lm = {}
    for m in M:
        xs = [lm_by[s][m] for s in lm_by if m in lm_by[s]]
        if xs:
            lm[m] = sum(xs) / len(xs)
    gw = {m: w["gateway"]["ocean"] * oc[m] + w["gateway"]["rail"] * ra[m] + w["gateway"]["truck"] * tr[m] for m in M if m in oc and m in ra and m in tr}
    tot = {m: w["total"]["gateway"] * gw[m] + w["total"]["lastmile"] * lm[m] for m in M if m in gw and m in lm}
    if not tot:
        notes.append("Index could not be computed: a part is missing for the base month.")

    # Lower 48 benchmark with the same weights: deep sea / rail / truck / air PPIs
    def ppi(sid):
        return {d[:7]: v for d, v in fred.get(sid, [])}
    bp = {k: rebase(ppi(s)) for k, s in (("ocean", "PCU483111483111"), ("rail", "PCU482111482111"), ("truck", "PCU484121484121"), ("air", "PCU481112481112"))}
    bgw = {m: sum(w["gateway"][k] * bp[k][m] for k in ("ocean", "rail", "truck")) for m in M if all(m in bp[k] for k in ("ocean", "rail", "truck"))}
    btot = {m: w["total"]["gateway"] * bgw[m] + w["total"]["lastmile"] * bp["air"][m] for m in M if m in bgw and m in bp["air"]}

    lab = f"{dt.date.fromisoformat(base + '-01'):%b %Y} = 100"
    for k, d, label in (("idx:total", tot, "Alaska freight rate index"), ("idx:gateway", gw, "Gateway: Lower 48 to Southcentral and Interior"),
                        ("idx:lastmile", lm, "Last mile: air freight to rural hubs"), ("idx:ocean", oc, "Ocean, Tacoma to Anchorage"),
                        ("idx:rail", ra, "Rail fuel surcharge factor"), ("idx:truck", tr, "Truck fuel surcharge factor"),
                        ("bench:total", btot, "Lower 48 benchmark (BLS producer prices, same weights)"),
                        ("bench:gateway", bgw, "Lower 48 benchmark, gateway parts"), ("bench:air", bp["air"], "Lower 48 benchmark, air freight")):
        S[k] = ser(f"{label} ({lab})", "index", "monthly", "index", [(m + "-01", d[m]) for m in M if m in d], "Two Cents for Alaska")
    S["ocean:container"] = ser("Groceries, one 40-ft trailer, Tacoma to Anchorage: rate + fuel surcharge + port surcharge", "dollars",
                               "monthly", "level", [(m + "-01", part["ocean"].get(m)) for m in M], "TOTE tariff 501-A; Carlile; Port of Alaska")

    return S, notes


def receipts(log, manual, series):
    """Itemized cost of two typical shipments today, for the page's receipts."""
    def latest(src, key):
        h = history(log, src, key)
        return h[-1] if h else (None, None)
    today = TODAY.isoformat()
    pamp = step_at(sorted((r["effective"], r["value"]) for r in manual["pamp_per_container"]["rows"]), today)
    pamp_next = next((r for r in sorted(manual["pamp_per_container"]["rows"], key=lambda r: r["effective"]) if r["effective"] > today), None)
    (te, base), (fe, fsc) = latest("tote", "2300"), latest("tote", "fsc")
    (ne, nr), (nfe, nf) = latest("nac", "BET:1000"), latest("nac", "fsc")
    (ee, er), (efe, ef) = latest("everts", "BET:1000"), latest("everts", "fsc")
    (be, bp) = latest("usps", "bypass70")
    out = {}
    if base and fsc is not None:
        tc = dict(zip(series.get("ocean:container", {}).get("dates", []), series.get("ocean:container", {}).get("values", [])))
        out["trailer"] = {"base": base, "base_eff": te, "fsc": fsc, "fsc_eff": fe, "fuel": base * fsc / 100, "pamp": pamp,
                          "total": base * (1 + fsc / 100) + (pamp or 0), "jan2025": tc.get("2025-01-01"),
                          "pamp_next": pamp_next and {"value": pamp_next["value"], "effective": pamp_next["effective"]}}
    if nr and nf is not None:
        pc = dict(zip(series.get("pallet:nac:BET", {}).get("dates", []), series.get("pallet:nac:BET", {}).get("values", [])))
        out["pallet"] = {"rate": nr, "rate_eff": ne, "fsc": nf, "fsc_eff": nfe, "base": 1000 * nr, "fuel": 1000 * nr * nf / 100,
                         "tax": 1000 * nr * (1 + nf / 100) * 0.0625, "total": 1000 * nr * (1 + nf / 100) * 1.0625,
                         "jan2025": pc.get("2025-01-01"),
                         "everts": er and ef is not None and 1000 * er * (1 + ef / 100) * 1.0625,
                         "bypass": bp and 1000 / 70 * bp}
    return out


def current_table(log):
    """Latest value of each tracked rate, for the page's table."""
    def latest(src, key):
        h = [o for o in log["observations"] if o["source"] == src and o["key"] == key]
        return max(h, key=lambda o: (o["effective"], o["seen"])) if h else None
    rows = []
    spec = [("tote", "2300", "Ocean", "TOTE, Tacoma to Anchorage, groceries, 40-ft trailer", "$/trailer"),
            ("tote", "2420", "Ocean", "TOTE, Tacoma to Anchorage, freight all kinds, 40-ft trailer", "$/trailer"),
            ("tote", "fsc", "Ocean", "TOTE ocean fuel surcharge", "%"),
            ("arrc", "fsc", "Rail", "Alaska Railroad fuel surcharge", "%"),
            ("aac", "4-2", "Air", "Alaska Air Cargo, Seattle to Anchorage, general freight", "$/lb"),
            ("aac", "2-1", "Air", "Alaska Air Cargo, Anchorage to rural Alaska, general freight", "$/lb"),
            ("nac", "BET:1000", "Air", "Northern Air Cargo, Anchorage to Bethel, 1,000 lb", "$/lb"),
            ("nac", "OME:1000", "Air", "Northern Air Cargo, Anchorage to Nome, 1,000 lb", "$/lb"),
            ("nac", "fsc", "Air", "Northern Air Cargo fuel surcharge", "%"),
            ("everts", "BET:1000", "Air", "Everts, Anchorage to Bethel, 1,000 lb", "$/lb"),
            ("everts", "OME:1000", "Air", "Everts, Anchorage to Nome, 1,000 lb", "$/lb"),
            ("everts", "fsc", "Air", "Everts fuel surcharge", "%"),
            ("usps", "bypass70", "Mail", "USPS Alaska Bypass, per 70 lb", "$")]
    for src, key, mode, label, unit in spec:
        o = latest(src, key)
        if o:
            rows.append({"mode": mode, "label": label, "value": o["value"], "unit": unit, "effective": o["effective"], "url": o["url"]})
    return rows


# ---------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    manual = json.loads(MANUAL.read_text())
    log = load_log()
    for r in manual.get("extra_observations", {}).get("rows", []):
        observe(log, r["source"], r["key"], r["value"], r["effective"], r["url"], seen=dt.date.fromisoformat(r["effective"]))
    status = {"source": "carrier tariffs, fuel-surcharge pages, USPS, FRED", "latest": {}, "problems": [], "notes": []}
    fred = {}
    if "--rebuild" not in args:
        for name, fn in (("tote", c_tote), ("arrc", c_arrc), ("carlile", c_carlile), ("nac", c_nac), ("everts", c_everts),
                         ("aac", c_aac), ("usps", c_usps), ("fred", lambda lg: c_fred(lg, fred))):
            try:
                status["latest"][name] = fn(log)
                print(f"{name}: ok ({status['latest'][name]})")
            except Exception as e:
                status["problems"].append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
                print(f"{name}: FAILED {e}")
        if "--backfill" in args:
            print("backfill:", backfill(log), "observations added")
        LOG.write_text(json.dumps(compact(log), indent=1) + "\n")
    if "--rebuild" in args:
        LOG.write_text(json.dumps(compact(log), indent=1) + "\n")
    if not fred:          # --rebuild, or FRED failed: reuse the last saved benchmark series
        old = json.loads(OUT.read_text()) if OUT.exists() else {}
        fred = old.get("fred", {})
    series, notes = build(log, fred, manual, status)
    series = {k: v for k, v in series.items() if v["dates"]}
    status["notes"] = [n for n in notes if n.startswith("Carlile's")]          # information, not failures
    status["problems"] += [n for n in notes if not n.startswith("Carlile's")]
    out = {"dashboard": "freight", "source": status["source"], "fetched": TODAY.isoformat(),
           "base_month": manual["base_month"], "weights": manual["weights"],
           "current": current_table(log), "receipts": receipts(log, manual, series), "series": series,
           "fred": {k: [r for r in v if r[0] >= "2015"] for k, v in fred.items()}}
    OUT.write_text(json.dumps(out, indent=1) + "\n")

    sp = DATA / "status.json"
    st = json.loads(sp.read_text()) if sp.exists() else {}
    st["freight"] = status
    sp.write_text(json.dumps(dict(sorted(st.items())), indent=1) + "\n")
    tot = series.get("idx:total", {})
    if tot.get("dates"):
        print(f"index {tot['dates'][-1]}: {tot['values'][-1]:.1f}")
    if status["problems"]:
        print("problems:", *status["problems"], sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
