"""The front page's "What's new" list: the ten most recent data updates across the
site, each with its headline number and a sentence on what it means.

How "new" is decided
  Every item below watches one series (or one hand-kept figure). The script keeps
  a log in site/data/updates.json of the latest period it has seen for each item
  and the day that period first appeared. When a refresh brings a newer period,
  that day becomes the item's "updated" date. The list shows the ten items with
  the most recent updated dates (ties broken by the data's own period).

  On the first run there is no log, so the updated date is taken from the date
  the data file last changed (its "fetched" field), or the hand-kept file's
  as_of date.

The "what it means" sentences are written here from the numbers themselves
(direction, size, comparison with the U.S. or with inflation), so they change
with the data and never need hand-editing. They describe; they don't advise.

Called by build_pages.py, which reruns after every data refresh.
"""
import html
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
LOG = DATA / "updates.json"
E = html.escape
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
SHOW = 10

_cache = {}


def load(name):
    if name not in _cache:
        p = DATA / f"{name}.json"
        _cache[name] = json.loads(p.read_text()) if p.exists() else {}
    return _cache[name]


def ser(file, sid):
    s = (load(file).get("series") or {}).get(sid)
    return s if s and s.get("dates") else None


def yago(d):
    return str(int(d[:4]) - 1) + d[4:]


def at(s, d):
    try:
        return s["values"][s["dates"].index(d)]
    except (ValueError, TypeError, KeyError):
        return None


def latest_yoy(s, back=6):
    """(date, value, value a year earlier) for the latest period that has one,
    skipping back over gaps such as October 2025 (shutdown)."""
    n = len(s["dates"])
    for i in range(n - 1, max(-1, n - 1 - back), -1):
        p = at(s, yago(s["dates"][i]))
        if p not in (None, 0):
            return s["dates"][i], s["values"][i], p
    return s["dates"][-1], s["values"][-1], None


def period(d, freq):
    if freq == "annual":
        return d[:4]
    if freq == "quarterly":
        return f"Q{(int(d[5:7]) - 1) // 3 + 1} {d[:4]}"
    if freq in ("weekly", "daily"):
        return f"{MON[int(d[5:7]) - 1]} {int(d[8:10])}, {d[:4]}"
    return f"{MON[int(d[5:7]) - 1]} {d[:4]}"


def n(v, dec=0, prefix="", suffix="", sign=False):
    s = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{s}{prefix}{abs(v):,.{dec}f}{suffix}"


def pct(a, b):
    return (a / b - 1) * 100


def word(v, up="up", down="down", flat="unchanged", tol=0.05):
    return flat if abs(v) < tol else up if v > 0 else down


# ---------------------------------------------------------------- items
# Each returns None (data missing) or a dict:
#   key, slug, title, date (ISO, the data's period), freq, value, change, means

def payroll():
    s = ser("key-sectors", "Total Nonfarm")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    if p is None:
        return None
    diff, g = v - p, pct(v, p)
    # which industries drove the change
    moves = []
    for sid, x in load("key-sectors")["series"].items():
        if sid in ("Total Nonfarm", "Mining and Logging") or not x.get("dates"):
            continue
        a, b = at(x, d), at(x, yago(d))
        if a is not None and b is not None:
            moves.append((a - b, sid))
    moves.sort()
    if diff >= 0 and moves and moves[-1][0] > 0:
        lead = f"{moves[-1][1].lower()} added the most ({n(moves[-1][0], sign=True)})"
    elif moves and moves[0][0] < 0:
        lead = f"{moves[0][1].lower()} lost the most ({n(moves[0][0], sign=True)})"
    else:
        lead = ""
    means = (f"Alaska has {n(abs(diff))} {'more' if diff >= 0 else 'fewer'} payroll jobs than a year earlier, "
             f"a {n(abs(g), 1)}% {'gain' if diff >= 0 else 'drop'}" + (f"; {lead}." if lead else "."))
    return dict(key="payroll", slug="payroll-jobs", title="Payroll jobs", date=d, freq="monthly",
                value=f"{v / 1000:,.1f}k", change=f"{n(diff, sign=True)} y/y", means=means)


def cpi():
    s, us = ser("cost-of-living", "CUURS49GSA0"), ser("cost-of-living", "CUUR0000SA0")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    if p is None:
        return None
    g = pct(v, p)
    u = at(us, d) if us else None
    up = at(us, yago(d)) if us else None
    gu = pct(u, up) if u and up else None
    cats = []
    for sid, x in load("cost-of-living")["series"].items():
        if sid in ("CUURS49GSA0", "CUUR0000SA0", "CUURS49GSA0L1E"):
            continue
        a, b = at(x, d), at(x, yago(d))
        if a and b:
            cats.append((pct(a, b), x["label"].replace("CPI, ", "").replace(", Urban Alaska", "")))
    cats.sort()
    cmp = ""
    if gu is not None:
        gap = g - gu
        cmp = (f", {'faster than' if gap > 0.15 else 'slower than' if gap < -0.15 else 'about the same as'} the U.S. ({n(gu, 1)}%)")
    top = f" The biggest increase was in {cats[-1][1]} ({n(cats[-1][0], 1, sign=True, suffix='%')})." if cats and cats[-1][0] > 0 else ""
    means = f"Prices in Anchorage and the Mat-Su rose {n(g, 1)}% over the year{cmp}.{top}"
    return dict(key="cpi", slug="cpi", title="Urban Alaska CPI", date=d, freq="monthly",
                value=n(g, 1, sign=True, suffix="%"), change="12-month change", means=means)


def wages():
    w, c = ser("labor", "SMU02000000500000003"), ser("cost-of-living", "CUURS49GSA0")
    if not w:
        return None
    d, v, p = latest_yoy(w)
    if p is None:
        return None
    g = pct(v, p)
    real = ""
    if c:
        # latest month with both a wage and a CPI reading, and year-earlier values for both
        for dd in reversed(w["dates"]):
            a, b, ca, cb = at(w, dd), at(w, yago(dd)), at(c, dd), at(c, yago(dd))
            if None not in (a, b, ca, cb):
                r = ((a / b) / (ca / cb) - 1) * 100
                real = (f" After Urban Alaska inflation, real pay was {word(r, 'up', 'down', 'flat', 0.1)}"
                        + (f" {n(abs(r), 1)}%" if abs(r) >= 0.1 else "") + f" in {period(dd, 'monthly')}"
                        + (", so paychecks are gaining buying power." if r >= 0.1 else ", so paychecks are losing buying power." if r <= -0.1 else "."))
                break
    means = f"Average hourly pay for private-sector workers is {word(g)} {n(abs(g), 1)}% from a year earlier, to {n(v, 2, '$')}.{real}"
    return dict(key="wages", slug="wage-growth", title="Wage growth", date=d, freq="monthly",
                value=n(g, 1, sign=True, suffix="%"), change=f"{n(v, 2, '$')}/hr", means=means)


def participation():
    s, us = ser("labor", "LBSSA02"), ser("labor", "CIVPART")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    u = at(us, d) if us else None
    ch = f"{n(v - p, 1, sign=True)} pts y/y" if p is not None else ""
    vs = f"{'above' if v > u else 'below' if v < u else 'equal to'} the U.S. rate of {u:.1f}%" if u else ""
    trend = (f"{'up' if v - p > 0.05 else 'down' if v - p < -0.05 else 'unchanged'} from {p:.1f}% a year earlier" if p is not None else "")
    means = f"{v:.1f}% of Alaskans 16 and older are working or looking for work, " + ", ".join(x for x in (trend, vs) if x) + "."
    return dict(key="lfp", slug="labor-force-participation", title="Labor force participation", date=d, freq="monthly",
                value=f"{v:.1f}%", change=ch, means=means)


def unemployment():
    s, us = ser("labor", "AKUR"), ser("labor", "UNRATE")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    u = at(us, d) if us else None
    gap = f", {abs(v - u):.1f} points {'above' if v > u else 'below'} the U.S." if u is not None and abs(v - u) >= 0.05 else (", the same as the U.S." if u is not None else "")
    move = f"{'up' if v > p else 'down' if v < p else 'unchanged'} from {p:.1f}% a year earlier" if p is not None else ""
    means = f"Alaska's unemployment rate is {v:.1f}%{gap}" + (f", {move}." if move else ".")
    return dict(key="unemp", slug="labor-force-participation", title="Unemployment rate", date=d, freq="monthly",
                value=f"{v:.1f}%", change=f"{n(v - p, 1, sign=True)} pts y/y" if p is not None else "", means=means)


def business_apps():
    s, us = ser("business-formation", "BABATOTALNSAAK"), ser("business-formation", "BABATOTALNSAUS")
    if not s:
        return None
    d = s["dates"][-1]
    y, mm = d[:4], d[5:7]

    def ytd(x, yr):
        return sum(v for dd, v in zip(x["dates"], x["values"]) if dd[:4] == yr and dd[5:7] <= mm)
    a, b = ytd(s, y), ytd(s, str(int(y) - 1))
    if not b:
        return None
    g = pct(a, b)
    cmp = ""
    if us:
        ua, ub = ytd(us, y), ytd(us, str(int(y) - 1))
        if ub:
            gu = pct(ua, ub)
            cmp = f" Nationally, filings are {word(gu)} {n(abs(gu), 1)}%."
    means = (f"Alaskans filed {n(a)} applications to start businesses through {FULL[int(mm) - 1]}, "
             f"{n(abs(g), 1)}% {'more' if g >= 0 else 'fewer'} than a year earlier.{cmp} Applications are an early read on the firms that will open over the next year or two.")
    return dict(key="bizapps", slug="business-applications", title="Business applications", date=d, freq="monthly",
                value=n(a), change=f"{n(g, 1, sign=True, suffix='%')} YTD", means=means)


def electricity():
    s, us = ser("energy", "AK-ALL"), ser("energy", "US-ALL")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    u = at(us, d) if us else None
    ratio = f" That is {v / u:.1f} times the U.S. average of {u:.1f}¢." if u else ""
    ch = f"{word(pct(v, p))} {n(abs(pct(v, p)), 1)}% from a year earlier" if p else ""
    means = f"Alaska's average retail power price was {v:.1f}¢ per kilowatt-hour" + (f", {ch}." if ch else ".") + ratio
    return dict(key="elec", slug="electricity", title="Electricity price", date=d, freq="monthly",
                value=f"{v:.1f}¢", change=f"{n(pct(v, p), 1, sign=True, suffix='%')} y/y" if p else "", means=means)


def gas():
    s, us = ser("natural-gas", "AK-CITYGATE"), ser("natural-gas", "US-CITYGATE")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    u = at(us, d) if us else None
    rel = f" The U.S. city gate price was {n(u, 2, '$')}." if u else ""
    means = (f"Gas utilities in Alaska paid {n(v, 2, '$')} per thousand cubic feet at the city gate"
             + (f", {word(pct(v, p))} {n(abs(pct(v, p)), 1)}% from a year earlier." if p else ".") + rel
             + " The city gate price feeds through to home heating and power bills.")
    return dict(key="gas", slug="natural-gas", title="Natural gas (city gate)", date=d, freq="monthly",
                value=n(v, 2, "$"), change=f"{n(pct(v, p), 1, sign=True, suffix='%')} y/y" if p else "", means=means)


def freight():
    s, idx = ser("freight", "ocean:container"), ser("freight", "idx:total")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    extra = ""
    if idx:
        di, vi, pi = latest_yoy(idx)
        if pi:
            extra = f" The site's all-mode Alaska freight index is {word(pct(vi, pi))} {n(abs(pct(vi, pi)), 1)}% over the same span."
    means = (f"Shipping a groceries trailer from Tacoma to Anchorage costs {n(v, 0, '$')}"
             + (f", {word(pct(v, p))} {n(abs(pct(v, p)), 1)}% from a year earlier." if p else ".")
             + extra + " Freight is built into the shelf price of most goods in the state.")
    return dict(key="freight", slug="freight", title="Freight costs", date=d, freq="monthly",
                value=n(v, 0, "$"), change=f"{n(pct(v, p), 1, sign=True, suffix='%')} y/y" if p else "", means=means)


def home_prices():
    s, us = ser("housing", "AKSTHPI"), ser("housing", "USSTHPI")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    if not p:
        return None
    g = pct(v, p)
    u, up = (at(us, d), at(us, yago(d))) if us else (None, None)
    cmp = f", compared with {n(pct(u, up), 1)}% for the U.S." if u and up else "."
    means = f"Alaska home values rose {n(g, 1)}% over the year on the FHFA index{cmp}" if g >= 0 else f"Alaska home values fell {n(abs(g), 1)}% over the year on the FHFA index{cmp}"
    return dict(key="hpi", slug="home-prices", title="Home prices", date=d, freq="quarterly",
                value=n(g, 1, sign=True, suffix="%"), change="FHFA index, y/y", means=means)


def permits():
    s = ser("housing", "AKBPPRIV")
    if not s:
        return None
    d = s["dates"][-1]
    y, mm = d[:4], d[5:7]
    a = sum(v for dd, v in zip(s["dates"], s["values"]) if dd[:4] == y and dd[5:7] <= mm)
    b = sum(v for dd, v in zip(s["dates"], s["values"]) if dd[:4] == str(int(y) - 1) and dd[5:7] <= mm)
    if not b:
        return None
    g = pct(a, b)
    means = (f"Builders were authorized to start {n(a)} new housing units through {FULL[int(mm) - 1]}, "
             f"{n(abs(g), 1)}% {'more' if g >= 0 else 'fewer'} than the same months last year. Permits are the earliest sign of how much new housing supply is coming.")
    return dict(key="permits", slug="home-prices", title="Housing permits", date=d, freq="monthly",
                value=n(a), change=f"{n(g, 1, sign=True, suffix='%')} YTD", means=means)


def gdp():
    s = ser("gdp", "AKRQGSP")
    if not s or len(s["values"]) < 2:
        return None
    d, v, p = s["dates"][-1], s["values"][-1], s["values"][-2]
    g = ((v / p) ** 4 - 1) * 100
    mining = ser("gdp", "AKMINRQGSP")
    share = ""
    if mining and at(mining, d):
        share = f" Mining, oil and gas made up {at(mining, d) / v * 100:.0f}% of real output."
    means = f"Alaska's real economy {'grew' if g >= 0 else 'shrank'} at a {n(abs(g), 1)}% annual rate in {period(d, 'quarterly')}.{share}"
    return dict(key="gdp", slug="gdp", title="Real GDP", date=d, freq="quarterly",
                value=n(g, 1, sign=True, suffix="%"), change="annual rate", means=means)


def air_freight_price():
    s = ser("air-cargo", "IC1312")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    if not p:
        return None
    g = pct(v, p)
    means = (f"The price of air freight from Asia to the U.S. is {word(g)} {n(abs(g), 1)}% from a year earlier. "
             "Much of that freight stops at Anchorage, so the price is a gauge of demand for ANC's transpacific cargo business.")
    return dict(key="airprice", slug="air-cargo", title="Asia air freight prices", date=d, freq="monthly",
                value=n(g, 1, sign=True, suffix="%"), change="BLS price index, y/y", means=means)


def productivity():
    s = ser("productivity", "IPUZNL000020000")
    if not s or len(s["values"]) < 2:
        return None
    d, v, p = s["dates"][-1], s["values"][-1], s["values"][-2]
    g = pct(v, p)
    o, h = ser("productivity", "IPUZNT010020000"), ser("productivity", "IPUZNL010020000")
    why = ""
    if o and h and at(o, d) and at(o, yago(d)) and at(h, d) and at(h, yago(d)):
        go, gh = pct(at(o, d), at(o, yago(d))), pct(at(h, d), at(h, yago(d)))
        why = f" Output {word(go, 'rose', 'fell', 'held steady')} {n(abs(go), 1)}% while hours worked {word(gh, 'rose', 'fell', 'held steady')} {n(abs(gh), 1)}%."
    means = f"Output per hour in Alaska's private economy {word(g, 'rose', 'fell', 'held steady')} {n(abs(g), 1)}% in {d[:4]}.{why}"
    return dict(key="prod", slug="gdp", title="Labor productivity", date=d, freq="annual",
                value=n(g, 1, sign=True, suffix="%"), change=d[:4], means=means)


def firm_entry():
    s, us = ser("firm-dynamics", "FIRM_ENTRY_RATE-AK"), ser("firm-dynamics", "FIRM_ENTRY_RATE-US")
    if not s:
        return None
    d, v = s["dates"][-1], s["values"][-1]
    u = at(us, d) if us else None
    cmp = f", {'above' if v > u else 'below'} the U.S. rate of {u:.1f}%" if u else ""
    means = f"New employer firms were {v:.1f}% of all Alaska firms in {d[:4]}{cmp}. A higher entry rate means more new competitors and more turnover."
    return dict(key="entry", slug="firm-entry", title="Firm entry rate", date=d, freq="annual",
                value=f"{v:.1f}%", change=f"{n(v - u, 1, sign=True)} pts vs U.S." if u else "", means=means)


def population():
    s = ser("population", "AKPOP")
    if not s or len(s["values"]) < 2:
        return None
    d, v, p = s["dates"][-1], s["values"][-1] * 1000, s["values"][-2] * 1000
    means = f"The Census Bureau puts Alaska's population at {n(v)} as of July {d[:4]}, {'up' if v >= p else 'down'} {n(abs(v - p))} from a year earlier."
    return dict(key="pop", slug="net-migration", title="Population", date=d, freq="annual",
                value=f"{v / 1000:,.1f}k", change=f"{n(v - p, sign=True)} y/y", means=means)


def postings():
    s, us = ser("job-postings", "AK"), ser("job-postings", "US")
    if not s:
        return None
    d, v, p = latest_yoy(s)
    u = at(us, d) if us else None
    g = pct(v, p) if p else None
    means = (f"Indeed job postings in Alaska are at {v:.0f}% of their February 2020 level"
             + (f", {word(g)} {n(abs(g), 1)}% from a year earlier" if g is not None else "")
             + (f"; nationally the index is {u:.0f}." if u else ".")
             + " Postings move ahead of hiring, so they hint at where payroll jobs are heading.")
    return dict(key="postings", slug="job-postings", title="Job postings", date=d, freq="monthly",
                value=f"{v:.0f}", change=f"{n(g, 1, sign=True, suffix='%')} y/y" if g is not None else "", means=means)


def net_migration():
    m = load("manual/population")
    hist = m.get("net_migration_history") or {}
    rows = hist.get("rows") or []
    if not rows:
        return None
    last = rows[-1]
    yr, net = last[0], last[2]
    streak = 0
    for r in reversed(rows):
        if r[2] is not None and r[2] < 0:
            streak += 1
        else:
            break
    nat = last[1]
    means = (f"{n(abs(net))} more people left Alaska than moved in during the year to July {yr[-4:] if len(yr) > 4 else yr}, "
             f"the {streak}{'th' if 10 <= streak % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(streak % 10, 'th')} straight year of net out-migration."
             + (f" Births minus deaths ({n(nat, sign=True)}) more than made up for it." if nat and nat > abs(net) else ""))
    as_of = hist.get("as_of_iso") or f"{yr[-4:]}-07-01"
    return dict(key="netmig", slug="net-migration", title="Net migration", date=as_of, freq="annual",
                value=n(net, sign=True), change=f"year to Jul {yr[-4:]}", means=means, manual=hist.get("released"))


ITEMS = [payroll, cpi, wages, participation, unemployment, business_apps, electricity, gas, freight,
         home_prices, permits, gdp, air_freight_price, firm_entry, population, postings, net_migration]

# data file behind each item, for the first-run "updated" date
FILE_OF = {"payroll": "key-sectors", "cpi": "cost-of-living", "wages": "labor", "lfp": "labor", "unemp": "labor",
           "bizapps": "business-formation", "elec": "energy", "gas": "natural-gas", "freight": "freight",
           "hpi": "housing", "permits": "housing", "gdp": "gdp", "airprice": "air-cargo", "prod": "productivity",
           "entry": "firm-dynamics", "pop": "population", "postings": "job-postings"}


def build(today=None, write=True):
    """Return the ten newest items, updating the log."""
    today = today or date.today().isoformat()
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    items = []
    for f in ITEMS:
        try:
            it = f()
        except Exception as e:  # one broken item shouldn't take down the front page
            print(f"  what's new: {f.__name__} skipped ({e})")
            it = None
        if not it:
            continue
        prev = log.get(it["key"])
        if prev and prev.get("period") == it["date"]:
            seen = prev["seen"]
        elif prev:
            seen = today
        else:
            seen = it.get("manual") or load(FILE_OF.get(it["key"], "")).get("fetched") or today
        log[it["key"]] = {"period": it["date"], "seen": seen}
        it["seen"] = seen
        items.append(it)
    if write:
        new = json.dumps(dict(sorted(log.items())), indent=1) + "\n"
        if not LOG.exists() or LOG.read_text() != new:
            LOG.write_text(new)
    items.sort(key=lambda x: (x["seen"], x["date"]), reverse=True)
    return items[:SHOW]


def seen_label(iso):
    return f"{MON[int(iso[5:7]) - 1]} {int(iso[8:10])}"


def html_block(items):
    lis = []
    for it in items:
        lis.append(
            f'<li class="wn-item"><div class="wn-when"><span class="wn-per">{E(period(it["date"], it["freq"]))}</span>'
            f'<span class="wn-seen">Updated {E(seen_label(it["seen"]))}</span></div>'
            f'<div class="wn-body"><h3><a href="/{it["slug"]}/">{E(it["title"])}</a></h3>'
            f'<p class="wn-num"><b>{E(it["value"])}</b> <span>{E(it["change"])}</span></p>'
            f'<p class="wn-means">{E(it["means"])}</p></div></li>')
    return ('<section id="new" aria-labelledby="h-new">\n  <div class="sec-head"><h2 id="h-new">What\'s new</h2>'
            '<p>The latest data to land on the site, newest first, and what each number means.</p></div>\n'
            '  <ol class="wn">' + "".join(lis) + "</ol>\n</section>")


CSS = """
.wn{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:0 28px}
.wn-item{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:14px 0;border-bottom:1px solid var(--rule)}
.wn-when{display:flex;flex-direction:column;gap:2px;font-size:12px;color:var(--muted)}
.wn-per{font-weight:600;color:var(--ink);font-size:13px}
.wn-body{display:flex;flex-direction:column;gap:4px;min-width:0}
.wn-body h3{font-size:18px;line-height:1.2} .wn-body h3 a{color:var(--ink);text-decoration:none} .wn-body h3 a:hover{text-decoration:underline}
.wn-num{margin:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}
.wn-num b{font-family:var(--display);font-size:24px;line-height:1.1;font-variant-numeric:tabular-nums}
.wn-num span{font-size:13px;font-weight:600;color:var(--muted)}
.wn-means{margin:0;font-size:14.5px;color:var(--body)}
"""

if __name__ == "__main__":
    for it in build(write=False):
        print(it["seen"], period(it["date"], it["freq"]), it["title"], it["value"], it["change"])
        print("   ", it["means"])
