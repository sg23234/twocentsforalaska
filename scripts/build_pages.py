"""Build every indicator page (site/<slug>/index.html) and the front-page matrix.

Each page is described in PAGES below: its headline numbers, charts, tables,
notes and sources. Anything that comes from a live data file is written as a
small spec that site/js/ind.js fills in the browser, so those numbers stay
current between builds. Tables and bar charts that come from hand-kept files
(site/data/manual/*.json) or that need sums across many series are worked out
here, at build time; the refresh workflow reruns this script after each fetch.

Pages with their own hand-written HTML (Electricity) are not overwritten: they
appear in PAGES only so the front page can link to them and show their tile.

Usage:  python3 scripts/build_pages.py
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"

INK, BODY, MUTED, RULE, TILE, ACC, BLUE, ORANGE = "#14213D", "#33405C", "#5A6580", "#C9D2DE", "#F6F8FB", "#B42318", "#1F5FA8", "#C2610C"
E = html.escape


def load(name):
    p = DATA / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def manual(name):
    return load(f"manual/{name}")


def last(d, sid):
    s = (d.get("series") or {}).get(sid)
    return (s["dates"][-1], s["values"][-1]) if s and s.get("dates") else (None, None)


def at(d, sid, date):
    s = (d.get("series") or {}).get(sid)
    if not s:
        return None
    try:
        return s["values"][s["dates"].index(date)]
    except ValueError:
        return None


def year_ago(date):
    return str(int(date[:4]) - 1) + date[4:]


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month(date):
    return f"{MON[int(date[5:7]) - 1]} {date[:4]}"


def fnum(v, dec=0, prefix="", suffix="", sign=False):
    if v is None:
        return "—"
    s = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{s}{prefix}{abs(v):,.{dec}f}{suffix}"


# ---------------------------------------------------------------- components

def spec_attr(d):
    return E(json.dumps(d, separators=(",", ":")), quote=True)


def stat(label, sub="", spec=None, value=None):
    """A headline number: live (spec) or fixed (value)."""
    if spec:
        return (f'<div class="stat" data-spec="{spec_attr(spec)}"><b>—</b>'
                f'<span data-t="{E(label)}">{E(label)}</span>' + (f'<em data-t="{E(sub)}">{E(sub)}</em>' if sub else "") + "</div>")
    return f'<div class="stat"><b>{E(value)}</b><span>{E(label)}</span>' + (f"<em>{E(sub)}</em>" if sub else "") + "</div>"


def chart(title, kind, series, caption="", **opts):
    c = {"kind": kind, "series": series, "title": title, **opts}
    return (f'<figure class="chart" data-chart="{spec_attr(c)}"><h3>{E(title)}</h3><div class="plot"></div>'
            f'<figcaption data-t="{E(caption)}">{E(caption)}</figcaption></figure>')


def hbar(title, rows, caption="", dec=0, prefix="", suffix="", highlight=None):
    """Static horizontal bars: rows = [(label, value)]."""
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return ""
    mx = max(abs(v) for _, v in rows) or 1
    W, Lw, Rw, RH = 680, 210, 80, 30
    H = 8 + RH * len(rows)
    s = f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(title)}">'
    for i, (lab, v) in enumerate(rows):
        y = 6 + i * RH
        w = abs(v) / mx * (W - Lw - Rw)
        col = ACC if highlight and re.search(highlight, lab) else (ORANGE if v < 0 else BLUE)
        s += (f'<text x="{Lw - 10}" y="{y + 17}" text-anchor="end" font-size="13" fill="{INK}">{E(lab)}</text>'
              f'<rect x="{Lw}" y="{y + 5}" width="{w:.1f}" height="16" fill="{col}"></rect>'
              f'<text x="{Lw + w + 8:.1f}" y="{y + 17}" font-size="13" font-weight="600" fill="{INK}">{E(fnum(v, dec, prefix, suffix, sign=any(x < 0 for _, x in rows)))}</text>')
    s += "</svg>"
    return f'<figure class="chart"><h3>{E(title)}</h3><div class="plot">{s}</div><figcaption>{E(caption)}</figcaption></figure>'


def vbars(title, labels, values, caption="", dec=0, prefix="", suffix="", partial_last=False, colors=None):
    """Static vertical bars (one or two series). values: list or list of (name, list)."""
    multi = isinstance(values[0], tuple)
    sers = values if multi else [("", values)]
    allv = [v for _, vs in sers for v in vs if v is not None]
    if not allv:
        return ""
    lo, hi = min(0, min(allv)), max(0, max(allv))
    W, H, L, R, T, B = 680, 240, 56, 12, 20, 30
    span = (hi - lo) or 1
    Y = lambda v: T + (1 - (v - lo) / span) * (H - T - B)
    n, k = len(labels), len(sers)
    slot = (W - L - R) / n
    bw = min(40, slot * 0.7 / k)
    cols = colors or [BLUE, ORANGE]
    s = f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(title)}"><line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="{INK}"></line>'
    for i, lab in enumerate(labels):
        cx = L + slot * i + slot / 2
        for j, (_, vs) in enumerate(sers):
            v = vs[i]
            if v is None:
                continue
            x = cx - bw * k / 2 + j * bw
            top = Y(max(v, 0))
            op = "0.5" if partial_last and i == n - 1 else "1"
            s += f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw - 2:.1f}" height="{max(abs(Y(v) - Y(0)), .5):.1f}" fill="{cols[j % len(cols)]}" opacity="{op}"></rect>'
            if n * k <= 16:
                s += f'<text x="{x + bw / 2 - 1:.1f}" y="{(Y(v) + 13) if v < 0 else top - 5:.1f}" text-anchor="middle" font-size="11" font-weight="600" fill="{INK}">{E(fnum(v, dec, prefix, suffix))}</text>'
        s += f'<text x="{cx:.1f}" y="{H - 9}" text-anchor="middle" font-size="11" fill="{MUTED}">{E(lab)}{"*" if partial_last and i == n - 1 else ""}</text>'
    s += "</svg>"
    legend = ""
    if multi:
        legend = '<div class="legend">' + "".join(f'<span><i style="background:{cols[j % len(cols)]}"></i>{E(nm)}</span>' for j, (nm, _) in enumerate(sers)) + "</div>"
    return f'<figure class="chart"><h3>{E(title)}</h3><div class="plot">{s}{legend}</div><figcaption>{E(caption)}</figcaption></figure>'


def table(title, cols, rows, caption="", right=()):
    rc = lambda i: ' class="r"' if i in right else ""
    th = "".join(f'<th scope="col"{rc(i)}>{E(c)}</th>' for i, c in enumerate(cols))
    tr = "".join("<tr>" + "".join(f"<td{rc(i)}>{E(str(c))}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return (f'<figure class="chart tblfig"><h3>{E(title)}</h3><div class="tbl"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{tr}</tbody></table></div><figcaption>{E(caption)}</figcaption></figure>')


def plan(items, title="What this page will add"):
    return f'<div class="plan"><h3>{E(title)}</h3><ul>' + "".join(f"<li>{E(i)}</li>" for i in items) + "</ul></div>"


def text(title, paras):
    return f'<div class="textblock"><h3>{E(title)}</h3>' + "".join(f"<p>{E(p)}</p>" for p in paras) + "</div>"


def section(title, intro, *blocks):
    blocks = [b for b in blocks if b]
    if not blocks:
        return ""
    return (f'<section class="sec"><div class="sech"><h2>{E(title)}</h2>' + (f"<p>{E(intro)}</p>" if intro else "") + "</div>"
            + "".join(blocks) + "</section>")


def src(name, url):
    return (name, url)


# ---------------------------------------------------------------- page shell

CSS = """
:root{--bg:#FFFFFF;--ink:#14213D;--body:#33405C;--muted:#5A6580;--rule:#C9D2DE;--tile:#F6F8FB;--accent:#B42318;
--display:"Fraunces",Georgia,"Times New Roman",serif;--sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;
padding:env(safe-area-inset-top,0px) max(16px,env(safe-area-inset-right,0px)) calc(64px + env(safe-area-inset-bottom,0px)) max(16px,env(safe-area-inset-left,0px))}
.wrap{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:40px}
a{color:var(--accent)} a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3{font-family:var(--display);font-weight:700;margin:0;text-wrap:balance}
.kick{font-size:12px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.mast{display:flex;flex-direction:column;align-items:center;gap:10px;padding-block:28px 18px;border-bottom:4px double var(--ink);text-align:center}
.mast nav{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 22px;font-size:13px;font-weight:500;letter-spacing:.06em;text-transform:uppercase}
.mast nav a{color:var(--ink);text-decoration:none;border-bottom:1px solid transparent} .mast nav a:hover{border-color:var(--accent)}
.name{font-family:var(--display);font-size:clamp(30px,5vw,44px);font-weight:700;line-height:1;letter-spacing:-.02em;color:var(--ink);text-decoration:none}
.head{display:flex;flex-direction:column;gap:12px}
.head h1{font-size:clamp(34px,5vw,50px);line-height:1.05}
.head .lead{margin:0;font-size:18px;color:var(--body);max-width:68ch}
.badge{display:inline-block;width:fit-content;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;border:1px solid var(--ink)}
.badge.planned{border-style:dashed;color:var(--muted);border-color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.stat{background:var(--tile);border:1px solid var(--rule);border-radius:4px;padding:14px;display:flex;flex-direction:column;gap:2px;min-height:118px}
.stat b{font-family:var(--display);font-size:32px;line-height:1.1;font-variant-numeric:tabular-nums;order:2;margin-top:auto}
.stat b.na{color:var(--rule)}
.stat span{font-size:13px;font-weight:600;color:var(--ink);order:1}
.stat em{font-style:normal;font-size:12.5px;color:var(--muted);order:3}
.sec{display:flex;flex-direction:column;gap:18px}
.sech{display:flex;flex-direction:column;gap:4px;border-bottom:2px solid var(--ink);padding-bottom:8px}
.sech h2{font-size:28px} .sech p{margin:0;font-size:15px;color:var(--body);max-width:72ch}
figure.chart{margin:0;display:flex;flex-direction:column;gap:8px}
figure.chart h3{font-size:19px}
figure.chart svg{width:100%;height:auto;display:block}
figure.chart figcaption{font-size:12.5px;color:var(--muted)}
svg text{font-family:var(--sans)}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--muted)}
.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:6px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:28px}
.tbl{overflow-x:auto;border-top:2px solid var(--ink)}
table{border-collapse:collapse;width:100%;font-size:15px}
th{text-align:left;padding:9px 12px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid var(--rule);color:var(--body)}
th.r,td.r{text-align:right;font-variant-numeric:tabular-nums}
.plan,.textblock{border:1px dashed var(--muted);border-radius:4px;padding:16px 20px;display:flex;flex-direction:column;gap:8px}
.textblock{border-style:solid;border-color:var(--rule)}
.plan h3,.textblock h3{font-size:18px} .plan ul{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:4px;color:var(--body)}
.textblock p{margin:0;color:var(--body)}
.notes ul,.sources ul{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:5px;color:var(--body);font-size:14.5px}
.note{margin:0;font-size:13px;color:var(--muted)}
footer{border-top:4px double var(--ink);padding-top:14px;font-size:13px;color:var(--muted);text-align:center}
"""

STATUS = {"live": "Live data", "partial": "Partly live · draft", "static": "Draft · figures updated by hand", "planned": "Draft · data in development"}


def page_html(p):
    stats = "".join(p.get("stats", []))
    body = "".join(b for b in p.get("body", []) if b)
    notes = "".join(f"<li>{E(n)}</li>" for n in p.get("notes", []))
    srcs = "".join(f'<li><a href="{E(u)}" target="_blank" rel="noopener">{E(n)}</a></li>' for n, u in p.get("sources", []))
    st = p.get("status", "live")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(p['title'])} · Two Cents for Alaska</title>
<meta name="description" content="{E(p['lead'][:155])}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Instrument+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<!-- Built by scripts/build_pages.py. Edit the PAGES entry there, not this file. -->
<div class="wrap">
<header class="mast">
  <nav aria-label="Sections"><a href="/#micro">Micro</a><a href="/#macro">Macro</a><a href="/sources/">Sources</a></nav>
  <a class="name" href="/">Two Cents for Alaska</a>
</header>
<div class="head">
  <span class="kick">{E(p['group'])}</span>
  <h1>{E(p['title'])}</h1>
  <span class="badge{' planned' if st in ('planned', 'static') else ''}">{E(STATUS[st])}</span>
  <p class="lead">{E(p['lead'])}</p>
</div>
{f'<div class="stats">{stats}</div>' if stats else ''}
{body}
{f'<section class="sec notes"><div class="sech"><h2>Data notes</h2></div><ul>{notes}</ul></section>' if notes else ''}
{f'<section class="sec sources"><div class="sech"><h2>Sources</h2></div><ul>{srcs}</ul></section>' if srcs else ''}
<footer>Built from public data. <a href="/sources/">All sources</a> · <a href="/">Front page</a></footer>
</div>
<script src="/js/ind.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------- pages

def pages():
    P = []
    ks, bf, col, hou, lab, pop, gdp, en, util = (load(x) for x in
        ["key-sectors", "business-formation", "cost-of-living", "housing", "labor", "population", "gdp", "energy", "electricity-utilities"])
    m_en, m_ks, m_bf, m_col, m_hou, m_pop = (manual(x) for x in ["energy", "key-sectors", "business-formation", "cost-of-living", "housing", "population"])

    def tile(main=None, chg=None, value=None, change="", unit=""):
        return {"main": main, "chg": chg, "value": value, "change": change, "unit": unit}

    # ======================= INPUT COSTS =======================
    G = "Micro · Input costs"
    P.append(dict(slug="electricity", group=G, title="Electricity", custom=True, row="Input costs",
        tile=tile({"file": "energy", "series": "AK-ALL", "dec": 1, "suffix": "¢"}, {"file": "energy", "series": "AK-ALL", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True, "after": " y/y"}, unit="avg price, ¢/kWh")))

    gas = (m_en.get("charts") or {}).get("gas_price", {})
    P.append(dict(slug="natural-gas", group=G, title="Railbelt natural gas", row="Input costs", status="static",
        lead="Southcentral Alaska heats homes and generates most of its electricity with natural gas from Cook Inlet. As older fields decline, what utilities pay for gas, and whether they can get enough of it, is one of the biggest input costs for Railbelt households and businesses.",
        stats=[stat("Utility cost of gas", "Enstar, per thousand cubic feet · Sep 2026", value="~$11"),
               stat("Asian LNG spot price", "Japan–Korea benchmark, per Mcf · Sep 2026", value="$24"),
               stat("Share of Southcentral power from gas", "2026 · ISER via KBBI", value="70%+"),
               stat("Possible winter shortfall", "Enstar estimate if deliveries don't rise · Sep 2026", value="18 days")],
        body=[section("Gas prices", "What the Railbelt's gas utility pays now, compared with the price of imported liquefied natural gas.",
                      hbar(gas.get("title", "Natural gas price"), [(r["label"], r["value"]) for r in gas.get("rows", [])],
                           f"As of {gas.get('as_of', '')}. Source: {gas.get('source', '')}.", prefix="$")),
              plan(["Monthly Alaska natural gas prices from EIA (city-gate, commercial and residential), updated automatically.",
                    "Cook Inlet production by month from the Alaska Oil and Gas Conservation Commission.",
                    "Enstar's gas cost adjustment each year, and LNG import contracts as they are signed."])],
        notes=["Gas prices here are utility costs, not customer bills. Enstar adjusts rates each summer.",
               "Figures are kept by hand in data/manual/energy.json until the EIA series is wired in."],
        sources=[src("KDLL/KBBI, What to know about the Cook Inlet natural gas crunch, Sep 2026", "https://www.kbbi.org/2026-09-11/what-to-know-about-the-cook-inlet-natural-gas-crunch"),
                 src("Alaska Public Media, Enstar says bills likely to rise, Jul 2026", "https://alaskapublic.org/news/economy/energy/2026-07-28/southcentral-alaska-gas-utility-says-bills-likely-to-rise-amid-supply-shortage")],
        tile=tile(value="~$11", change="Enstar cost", unit="per Mcf")))

    P.append(dict(slug="heating-fuel", group=G, title="Rural heating fuel", row="Input costs", status="static",
        lead="Most of rural Alaska heats with fuel oil delivered by barge or plane. The state surveys prices in about 100 communities twice a year, which makes it the best regular measure of costs off the road system, where consumer price indexes don't reach.",
        stats=[stat("Average heating fuel price", "Across about 100 communities · Aug 2026", value="$7.97"),
               stat("Change since January", "A record high · DCRA survey", value="+23%")],
        body=[plan(["Prices by community and region from each Division of Community and Regional Affairs fuel price survey (heating fuel and gasoline).",
                    "A long history of the statewide average, with Anchorage and Fairbanks for comparison.",
                    "A ranked table of the most and least expensive communities, like the Electricity page."])],
        notes=["The survey is taken twice a year (January and July). Prices are what residents pay, including delivery."],
        sources=[src("Division of Community and Regional Affairs, Summer 2026 Alaska Fuel Price Report", "https://www.commerce.alaska.gov/web/Portals/4/pub/Summer%202026%20Alaska%20Fuel%20Price%20Report.pdf"),
                 src("KYUK, State report shows heating fuel prices at a record high in rural Alaska, Oct 2026", "https://www.kyuk.org/economy/2026-10-09/state-report-shows-heating-fuel-prices-are-at-a-record-high-in-rural-alaska")],
        tile=tile(value="$7.97", change="+23% since Jan", unit="per gallon, rural avg")))

    P.append(dict(slug="freight", group=G, title="Freight rate index", row="Input costs", status="planned",
        lead="Almost everything sold in Alaska arrives by ship, barge, truck or plane, so shipping costs are built into the price of nearly every good. No public index tracks what it costs to move freight to and within Alaska. This page will build one.",
        body=[plan(["Container rates from Tacoma to Anchorage from the carriers' published tariffs.",
                    "Barge rates from Anchorage or Seattle to regional hubs such as Bethel, Nome and Kotzebue.",
                    "Air freight and bypass mail rates to rural communities.",
                    "National freight price indexes from the Bureau of Labor Statistics for context.",
                    "An index (base year = 100) combining these, updated as tariffs change."], "How the index will be built")],
        notes=["This page is a placeholder. No figures are shown until the index is built."],
        tile=tile(unit="Seattle–Anchorage")))

    P.append(dict(slug="health-premium", group=G, title="Employer health premium", row="Input costs", status="static",
        lead="For employers, health insurance is part of the cost of every job. Alaska's premiums are among the highest in the country, which makes hiring here more expensive than the wage alone suggests.",
        stats=[stat("Average single-coverage premium, Alaska", "Employer and employee share · 2025", value="$10,630"),
               stat("United States", "Same measure · 2025", value="$9,025"),
               stat("Paid by the employer, Alaska", "82% of the premium · 2025", value="$8,699"),
               stat("Alaska vs. U.S.", "Single coverage · 2025", value="1.18×")],
        body=[section("Single coverage, 2025", "Average annual premium per enrolled private-sector employee.",
                      vbars("Annual premium, single coverage", ["Employer share", "Employee share", "Total"],
                            [("Alaska", [8699, 1931, 10630]), ("United States", [7208, 1817, 9025])],
                            "Source: KFF from the Medical Expenditure Panel Survey, Insurance Component, 2025.", prefix="$")),
              plan(["Family coverage premiums, and the change from year to year.",
                    "Premiums by firm size, since small employers pay more per worker.",
                    "Workers' compensation premium rates."])],
        notes=["Figures are private-sector employer plans from the Agency for Healthcare Research and Quality's MEPS Insurance Component, as tabulated by KFF. New data comes out each fall."],
        sources=[src("KFF, Average annual single premium per enrolled employee, 2025", "https://www.kff.org/health-costs/state-indicator/single-coverage/"),
                 src("AHRQ, Medical Expenditure Panel Survey, Insurance Component", "https://meps.ahrq.gov/mepsweb/data_stats/quick_tables_search.jsp?component=2&subcomponent=2")],
        tile=tile(value="$10,630", change="U.S. $9,025", unit="single coverage, 2025")))

    P.append(dict(slug="commercial-lease", group=G, title="Commercial lease rate", row="Input costs", status="planned",
        lead="Rent for offices, shops and warehouses is a fixed cost for most businesses. This page will track asking rents and vacancy for commercial space in Anchorage and the Mat-Su.",
        body=[plan(["Asking rent per square foot and vacancy for office, retail and industrial space, from commercial real estate market reports.",
                    "Anchorage and Mat-Su separately, with Fairbanks and Juneau where reports exist.",
                    "Commercial building permits and new space under construction."])],
        notes=["This page is a placeholder until a regularly published source is chosen."],
        tile=tile(unit="Anchorage, per sq ft")))

    # ======================= PHYSICAL VOLUMES =======================
    G = "Micro · Physical volumes"
    regs = sorted((util.get("regions") or {}).items(), key=lambda x: -x[1].get("sales_mwh", 0))
    P.append(dict(slug="electricity-load", group=G, title="Electricity load", row="Physical volumes", status="live",
        lead="How much electricity Alaskans buy each month. Power use follows activity in homes, stores, mines and offices, and it is reported quickly, so it can show changes in the economy before official statistics do.",
        stats=[stat("Electricity sold, {date}", "Million kWh (GWh)", {"file": "energy", "series": "AK-ALL:sales", "dec": 0}),
               stat("vs. a year earlier", "Same month", {"file": "energy", "series": "AK-ALL:sales", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Electricity sold, {year}", "Last full year, GWh", {"file": "energy", "series": "AK-ALL:sales", "calc": "annual_last", "agg": "sum", "dec": 0}),
               stat("vs. the year before", "Full year", {"file": "energy", "series": "AK-ALL:sales", "calc": "annual_yoy_pct", "agg": "sum", "dec": 1, "suffix": "%", "sign": True})],
        body=[section("Electricity sold each year", "Retail sales to all customers, in gigawatt-hours.",
                      chart("Electricity sold, Alaska", "bars", [{"file": "energy", "id": "AK-ALL:sales", "label": "Alaska"}],
                            "Annual totals of monthly EIA retail sales. Faded bar: year to date.", agg="sum", dec=0, **{"from": "2001-01-01"}),
                      chart("Change from the same month a year earlier", "line", [{"file": "energy", "id": "AK-ALL:sales", "label": "Alaska", "transform": "yoy_pct"}],
                            "Percent change from a year earlier, monthly. Latest: {date}.", dec=1, suffix="%", zero=False, **{"from": "2018-01-01"})),
              section("Where the power goes", f"Electricity sold by region, {util.get('year', '')}.",
                      hbar("Electricity sold by region, GWh", [(k, round(v["sales_mwh"] / 1000)) for k, v in regs if v.get("sales_mwh")],
                           f"Source: EIA-861, {util.get('year', '')}. Regions as on the Electricity page.") if regs else "")],
        notes=["Retail sales measure electricity sold by utilities. They leave out power that oil fields, mines and military bases generate for their own use.",
               "Monthly figures come from EIA's sample survey and are revised when the annual survey is final."],
        sources=[src("EIA, Electric Power Monthly, retail sales by state", "https://www.eia.gov/electricity/monthly/"),
                 src("EIA, Form EIA-861", "https://www.eia.gov/electricity/data/eia861/")],
        tile=tile({"file": "energy", "series": "AK-ALL:sales", "dec": 0, "suffix": " GWh"}, {"file": "energy", "series": "AK-ALL:sales", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True, "after": " y/y"}, unit="electricity sold")))

    P.append(dict(slug="port-tonnage", group=G, title="Port of Alaska tonnage", row="Physical volumes", status="planned",
        lead="Most goods that reach Southcentral and Interior Alaska come through the Port of Alaska in Anchorage. Tonnage crossing its docks is a direct measure of how much the state is consuming and building.",
        body=[plan(["Annual tonnage by type: containers and trailers, petroleum, cement and bulk.",
                    "Long history from the U.S. Army Corps of Engineers Waterborne Commerce statistics.",
                    "Port of Alaska modernization project milestones and costs."])],
        notes=["This page is a placeholder until tonnage figures are assembled."],
        tile=tile(unit="tons")))

    cargo = m_ks.get("air_cargo", {})
    P.append(dict(slug="air-cargo", group=G, title="ANC air cargo", row="Physical volumes", status="static",
        lead="Anchorage sits on the great-circle route between Asia and North America, and most trans-Pacific freighters stop there to refuel. Ted Stevens Anchorage International Airport handles more all-cargo landed weight than any other airport in the country.",
        stats=[stat("Rank among U.S. airports", "All-cargo landed weight · 2025", value="#1"),
               stat("All-cargo landed weight", "Billions of pounds · 2025, preliminary", value=fnum((cargo.get("rows") or [[None, None]])[0][1], 1)),
               stat("Change from 2024", "Landed weight · FAA preliminary", value="+3.2%")],
        body=[section("Busiest U.S. cargo airports", "All-cargo landed weight, billions of pounds.",
                      hbar(cargo.get("label", "All-cargo landed weight"), [tuple(r) for r in cargo.get("rows", [])],
                           f"{cargo.get('as_of', '')}. Source: {cargo.get('source', '')}. Next: {cargo.get('next_update', '')}.", dec=2, highlight="Anchorage")),
              plan(["Monthly cargo tonnage and freighter landings from the Alaska International Airport System reports.",
                    "Cargo-related jobs and fuel sales at the airport."])],
        notes=["Landed weight is the maximum weight of the aircraft that land, the FAA's standard measure. Anchorage's count includes freight that only stops to refuel."],
        sources=[src("FAA, CY2025 all-cargo airports, preliminary", "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-CY2025-all-cargo-airports-preliminary.pdf"),
                 src("Alaska International Airport System, reports", "https://dot.alaska.gov/aias/")],
        tile=tile(value="#1", change="+3.2% landed wt.", unit="U.S. cargo airport, 2025")))

    P.append(dict(slug="railroad-freight", group=G, title="Alaska Railroad freight", row="Physical volumes", status="static",
        lead="The state-owned Alaska Railroad runs from Seward and Whittier to Fairbanks. Its freight volume reflects construction (gravel), power generation (coal), fuel distribution and goods arriving from the Lower 48 by rail barge.",
        stats=[stat("Freight moved", "Tons · 2025", value="3.9M"),
               stat("Change from 2024", "About 300,000 more tons", value="+8%"),
               stat("Freight revenue", "42% of revenue incl. grants · 2025", value="$118.8M")],
        body=[section("What the railroad carries", "Freight by type, thousands of tons, 2024.",
                      hbar("Freight by type, 2024", [("Gravel", 1455), ("Coal", 647), ("Interline (via rail barge)", 644), ("Petroleum", 460), ("Other", 446)],
                           "Source: Alaska Railroad 2025 freight fact sheet, as reported by Alaska Business. 2025 breakdown to be added.")),
              plan(["Annual freight by type back to 2011 from the railroad's freight summaries.",
                    "Monthly carloads if the railroad publishes them."])],
        notes=["Gravel moves mostly in summer from Palmer to Anchorage, so tonnage swings with the construction season."],
        sources=[src("Alaska Railroad, 2026 business fact sheet: freight", "https://alaskarailroad.com/sites/default/files/Communications/2026_Business_Fact_Sheet_Freight_Services.pdf"),
                 src("Alaska Railroad, 2026 business fact sheet: overview", "https://alaskarailroad.com/sites/default/files/Communications/2026_Business_Fact_Sheet_Overview.pdf"),
                 src("Alaska Business, Tracking Progress", "https://digital.akbizmag.com/?p=76233")],
        tile=tile(value="3.9M", change="+8% vs 2024", unit="tons, 2025")))

    P.append(dict(slug="barge-amhs", group=G, title="Barge & AMHS volumes", row="Physical volumes", status="planned",
        lead="Barges supply most coastal and river communities, and the Alaska Marine Highway System carries people and vehicles between Southeast, Southcentral and Southwest Alaska. Together they are the freight and transit backbone for places off the road system.",
        body=[plan(["Alaska Marine Highway traffic by year: passengers and vehicles, and sailings by route, from the state's annual traffic volume reports.",
                    "Waterborne freight to Alaska ports from the U.S. Army Corps of Engineers.",
                    "The number of communities served and sailings cancelled."])],
        notes=["This page is a placeholder until volumes are assembled."],
        tile=tile(unit="loads")))

    # ======================= BUSINESS DYNAMISM =======================
    G = "Micro · Business dynamism"
    P.append(dict(slug="business-applications", group=G, title="Business applications", row="Business dynamism", status="live",
        lead="Applications for a federal employer ID number with signs of a real business, from the Census Bureau. They are an early, monthly signal of entrepreneurship: intent to start, not openings or jobs.",
        stats=[stat("Applications, {date}", "Not seasonally adjusted", {"file": "business-formation", "series": "BABATOTALNSAAK"}),
               stat("Year to date, {year}", "Through {date}", {"file": "business-formation", "series": "BABATOTALNSAAK", "calc": "ytd_sum"}),
               stat("vs. same months last year", "Alaska", {"file": "business-formation", "series": "BABATOTALNSAAK", "calc": "ytd_yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("U.S., same comparison", "Year to date", {"file": "business-formation", "series": "BABATOTALNSAUS", "calc": "ytd_yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Likely employers, {date}", "High-propensity share of applications", {"file": "business-formation", "series": "BAHBATOTALNSAAK", "calc": "ratio", "over": {"file": "business-formation", "series": "BABATOTALNSAAK"}, "scale": 100, "dec": 1, "suffix": "%"})],
        body=[section("Applications by year", "Sum of monthly applications.",
                      chart("Business applications, Alaska", "bars", [{"file": "business-formation", "id": "BABATOTALNSAAK", "label": "Alaska"}],
                            "Faded bar: year to date through {date}. Source: Census Business Formation Statistics via FRED.", agg="sum", **{"from": "2018-01-01"})),
              section("Month by month", "Not seasonally adjusted, so compare the same month across years.",
                      chart("Monthly applications", "line", [{"file": "business-formation", "id": "BABATOTALNSAAK", "label": "All applications"}, {"file": "business-formation", "id": "BAHBATOTALNSAAK", "label": "Likely employers"}],
                            "Latest: {date}.", **{"from": "2022-01-01"}))],
        notes=["An application is a filing for an employer ID number. It is not an LLC registration, an opening, or a job.",
               "High-propensity applications are those Census flags as likely to hire, for example because they list a planned wage date."],
        sources=[src("Census Bureau, Business Formation Statistics", "https://www.census.gov/econ/bfs/index.html"),
                 src("FRED, BABATOTALNSAAK", "https://fred.stlouisfed.org/series/BABATOTALNSAAK")],
        tile=tile({"file": "business-formation", "series": "BABATOTALNSAAK", "calc": "ytd_sum"}, {"file": "business-formation", "series": "BABATOTALNSAAK", "calc": "ytd_yoy_pct", "dec": 1, "suffix": "%", "sign": True, "after": " YTD"}, unit="applications, year to date")))

    oc = m_bf.get("openings_closings", {})
    q, op_, cl_ = oc.get("quarters", []), oc.get("jobs_gained_openings", []), oc.get("jobs_lost_closings", [])
    bed_chart = vbars("Jobs at opening and closing establishments", q, [("Gained at openings", op_), ("Lost at closings", cl_)],
                      f"Seasonally adjusted. Latest: {oc.get('as_of', '')}. Source: {oc.get('source', '')}.") if q else ""
    for slug, title, lead, i_val, lbl in [
        ("firm-entry", "Firm entry rate", "How often new businesses open. A steady flow of new firms is one of the main ways an economy finds new products, raises productivity and creates jobs; young firms account for a large share of new hiring.", op_, "Jobs gained at openings"),
        ("firm-exit", "Firm exit rate", "How often businesses close. Some turnover is healthy, as resources move from struggling firms to growing ones; a rising exit rate with few entrants signals a shrinking business base.", cl_, "Jobs lost at closings")]:
        P.append(dict(slug=slug, group=G, title=title, row="Business dynamism", status="partial",
            lead=lead,
            stats=[stat(f"{lbl}, {q[-1] if q else ''}", "Establishments, seasonally adjusted", value=fnum(i_val[-1]) if i_val else "—"),
                   stat("Same quarter a year earlier", q[0] if q else "", value=fnum(i_val[0]) if i_val else "—")],
            body=[section("Openings and closings", "A quarterly BLS series counts jobs at establishments that opened or closed.", bed_chart),
                  plan([f"The {'entry' if slug == 'firm-entry' else 'exit'} rate itself: new {'firms' if slug == 'firm-entry' else 'firm closures'} as a share of all firms, from the Census Bureau's Business Dynamics Statistics (annual), compared with the U.S.",
                        "Establishment births and deaths by industry from BLS Business Employment Dynamics.",
                        "Alaska business license counts from the state."])],
            notes=["Business Employment Dynamics data are published about seven months after each quarter. Figures are kept in data/manual/business-formation.json."],
            sources=[src("BLS, Business Employment Dynamics", "https://www.bls.gov/bdm/"),
                     src("Census Bureau, Business Dynamics Statistics", "https://www.census.gov/programs-surveys/bds.html")],
            tile=tile(value=fnum(i_val[-1]) if i_val else None, change=f"jobs, {q[-1]}" if q else "", unit=lbl.lower())))

    P.append(dict(slug="young-firms", group=G, title="Jobs at young firms", row="Business dynamism", status="planned",
        lead="The share of Alaska's jobs at firms five years old or younger. Research by John Haltiwanger and others finds that young firms, not small firms as such, drive net job creation, so this share is a good gauge of business dynamism.",
        body=[plan(["Employment at firms aged 0–5 years as a share of all employment, from the Census Bureau's Business Dynamics Statistics, Alaska vs. U.S.",
                    "Hiring and earnings at young firms by industry from the Quarterly Workforce Indicators.",
                    "A long history showing how the share has changed since the 1980s."])],
        notes=["This page is a placeholder until the Business Dynamics Statistics series is wired in."],
        sources=[src("Census Bureau, Business Dynamics Statistics", "https://www.census.gov/programs-surveys/bds.html")],
        tile=tile(unit="share of employment")))

    m_ft = manual("food-trucks")
    dp, pc, fees = m_ft.get("dec_permits", {}), m_ft.get("permit_counts", {}), m_ft.get("dec_fees", {})
    P.append(dict(slug="food-trucks", group=G, title="Food trucks", row="Business dynamism", status="partial",
        lead="Food trucks are one of the lowest-cost ways to open a restaurant in Alaska: a truck or trailer, a state permit of a few hundred dollars and a commissary agreement, instead of a lease and a build-out. The number of trucks is a small, visible gauge of how readily Alaskans start food businesses.",
        stats=[stat("Food truck permits, outside Anchorage", f"DEC FN-3 permits · {dp.get('as_of', '')}", value=dp.get("value", "—")),
               stat("Businesses with employees, {year}", "Census County Business Patterns", {"file": "food-trucks", "series": "cbp-AK:ESTAB"}),
               stat("Owner-operated, no employees, {year}", "Census Nonemployer Statistics", {"file": "food-trucks", "series": "nonemp-AK:NESTAB"}),
               stat("Employees, mid-March {year}", "At businesses with employees", {"file": "food-trucks", "series": "cbp-AK:EMP"})],
        body=[section("Permit counts", "Health permits are the closest thing to a headcount of trucks. The state and Anchorage keep separate counts, and the state has changed what it reports, so compare like with like.",
                      table("Food truck and mobile vendor permits", pc.get("columns", []), pc.get("rows", []),
                            "The 2012–13 state counts cover every type of mobile unit; the 2026 count covers self-contained trucks only, so growth since 2013 is at least as large as the gap suggests.", right=(1,))),
              section("Food truck businesses", "Census counts of businesses classified as mobile food services (NAICS 722330), by whether they have paid employees.",
                      chart("Mobile food businesses, Alaska", "line", [{"file": "food-trucks", "id": "nonemp-AK:NESTAB", "label": "No employees"}, {"file": "food-trucks", "id": "cbp-AK:ESTAB", "label": "With employees"}],
                            "Annual. Latest: {date}. Source: Census Bureau Nonemployer Statistics and County Business Patterns.")),
              section("What it costs to get permitted", "State health permit fees for mobile units, outside Anchorage.",
                      hbar(fees.get("label", "DEC permit fees"), [(r[0], r[1]) for r in fees.get("rows", [])], f"Annual fee, {fees.get('as_of', '')}. Source: Alaska DEC Food Safety and Sanitation fee schedule.", prefix="$")),
              plan(["A current statewide count from DEC's active-permit list (FN-2, FN-3, FN-3A and retail mobile vendors), by community, refreshed automatically.",
                    "Anchorage Health Department mobile food unit permits, so the count covers the whole state.",
                    "Food trucks per 100,000 residents, Alaska vs. the U.S.",
                    "How many permits stay active through winter."])],
        notes=["DEC permits food businesses everywhere in Alaska except the Municipality of Anchorage, which runs its own program. The DEC count therefore likely leaves out Anchorage trucks.",
               "FN-3 is DEC's self-contained mobile food service permit (a truck or trailer with its own water and wastewater). Carts and units that rely on a commissary are permitted separately as FN-2; trucks that also cater, as FN-3A.",
               "Census counts are by industry (NAICS 722330). A truck run by a restaurant or caterer may be counted under that business instead. Nonemployer counts appear about two and a half years after the year they cover, and small Alaska figures can be withheld.",
               "Permit counts are kept by hand in data/manual/food-trucks.json."],
        sources=[src("Alaska's News Source, Spenard food truck carnival highlights Alaska's growing mobile food scene, Jul 2026", "https://www.alaskasnewssource.com/2026/07/24/spenard-food-truck-carnival-draws-crowd-highlights-alaskas-growing-mobile-food-scene/"),
                 src("Anchorage Daily News, Food trucks proliferate, Jul 2013", "https://adn.com/food-drink/article/food-truck-craze-alaska-keeps-truckin-restaurants-wheels-proliferate-0/2013/07/24"),
                 src("Anchorage Daily News, Anchorage food trucks face winter, Oct 2016", "https://adn.com/business-economy/2016/10/23/anchorage-food-trucks-get-ready-to-face-one-of-their-biggest-challenges-winter"),
                 src("Alaska DEC, Food permit fees", "https://dec.alaska.gov/eh/fss/fees"),
                 src("Alaska DEC, Mobile food units, carts, kiosks", "https://dec.alaska.gov/eh/fss/food/food-service/mobile"),
                 src("Census Bureau, County Business Patterns", "https://www.census.gov/programs-surveys/cbp.html"),
                 src("Census Bureau, Nonemployer Statistics", "https://www.census.gov/programs-surveys/nonemployer-statistics.html")],
        tile=tile(value=dp.get("value"), change=f"DEC permits, {dp.get('as_of', '')}", unit="food trucks, outside Anchorage")))

    # ======================= LABOR MARKET =======================
    G = "Micro · Labor market"
    rows = []
    d0, _ = last(ks, "Total Nonfarm")
    if d0:
        for sid, meta in (ks.get("series") or {}).items():
            v, p = at(ks, sid, d0), at(ks, sid, year_ago(d0))
            if v is not None and p:
                rows.append((meta["label"].replace("Payroll jobs, ", "").capitalize(), v, v - p, (v / p - 1) * 100))
        tot = [r for r in rows if r[0].startswith("Total")]
        rows = tot + sorted([r for r in rows if not r[0].startswith("Total") and r[0] != "Mining and logging (includes oil and gas)"], key=lambda r: -r[1])
    P.append(dict(slug="payroll-jobs", group=G, title="Payroll jobs", row="Labor market", status="live",
        lead="The number of wage and salary jobs in Alaska, counted from a monthly survey of employers by the Alaska Department of Labor and Workforce Development. It is the most timely broad measure of the state's economy.",
        stats=[stat("Payroll jobs, {date}", "Not seasonally adjusted", {"file": "key-sectors", "series": "Total Nonfarm", "scale": 0.001, "dec": 1, "suffix": "k"}),
               stat("vs. a year earlier", "Jobs, same month", {"file": "key-sectors", "series": "Total Nonfarm", "calc": "yoy_diff", "sign": True}),
               stat("Percent change", "Same month a year earlier", {"file": "key-sectors", "series": "Total Nonfarm", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Average, {year}", "Last full year", {"file": "key-sectors", "series": "Total Nonfarm", "calc": "annual_last", "scale": 0.001, "dec": 1, "suffix": "k"})],
        body=[section("Jobs over time", "Total nonfarm payroll jobs, annual averages and the latest year to date.",
                      chart("Payroll jobs, annual average", "bars", [{"file": "key-sectors", "id": "Total Nonfarm", "label": "Alaska", "scale": 0.001}],
                            "Thousands of jobs. Faded bar: year to date through {date}.", agg="avg", dec=1, suffix="k", **{"from": "2010-01-01"}),
                      chart("Change from a year earlier", "line", [{"file": "key-sectors", "id": "Total Nonfarm", "label": "Alaska", "transform": "yoy_pct"}],
                            "Percent change in total payroll jobs from the same month a year earlier.", dec=1, suffix="%", zero=False, **{"from": "2016-01-01"})),
              section("By industry", f"Payroll jobs in {month(d0) if d0 else ''} and change from a year earlier.",
                      table("Jobs by industry", ["Industry", "Jobs", "Change", "Percent"], [(n, fnum(v), fnum(c, sign=True), fnum(pc, 1, suffix="%", sign=True)) for n, v, c, pc in rows],
                            "Source: Alaska DOLWD, Current Employment Statistics, not seasonally adjusted. Industries overlap (oil and gas is part of mining).", right=(1, 2, 3)) if rows else "")],
        notes=["Payroll counts exclude the self-employed, most commercial fishermen and uniformed military.",
               "These are the state's own monthly estimates, which can differ from the federal (BLS) figures for recent months."],
        sources=[src("Alaska DOLWD, monthly employment by industry", "https://live.laborstats.alaska.gov/labforce/000000/01/ces.html")],
        tile=tile({"file": "key-sectors", "series": "Total Nonfarm", "scale": 0.001, "dec": 1, "suffix": "k"}, {"file": "key-sectors", "series": "Total Nonfarm", "calc": "yoy_diff", "sign": True, "after": " y/y"}, unit="nonfarm")))

    P.append(dict(slug="job-postings", group=G, title="Job postings", row="Labor market", status="planned",
        lead="Online job postings show employers' demand for workers in close to real time, by occupation and region. They lead official hiring data by weeks.",
        body=[plan(["Job postings index for Alaska vs. the U.S. from Indeed Hiring Lab's public data.",
                    "Active job orders by occupation and region from AlaskaJobs (Alaska DOLWD).",
                    "Openings per unemployed worker, from the federal JOLTS state estimates."])],
        notes=["This page is a placeholder until a postings series is wired in."],
        sources=[src("Indeed Hiring Lab, job postings data", "https://data.indeed.com/"),
                 src("BLS, JOLTS state estimates", "https://www.bls.gov/jlt/jlt_statedata.htm")],
        tile=tile(unit="active")))

    P.append(dict(slug="wage-growth", group=G, title="Wage growth", row="Labor market", status="live",
        lead="How fast pay is rising for Alaska's private-sector workers, measured by average hourly earnings from the monthly employer survey. Wage growth above inflation means rising real pay.",
        stats=[stat("Average hourly earnings, {date}", "All private employees, Alaska", {"file": "labor", "series": "SMU02000000500000003", "dec": 2, "prefix": "$"}),
               stat("vs. a year earlier", "Alaska", {"file": "labor", "series": "SMU02000000500000003", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("U.S. average hourly earnings", "{date}", {"file": "labor", "series": "CES0500000003", "dec": 2, "prefix": "$"}),
               stat("U.S., vs. a year earlier", "{date}", {"file": "labor", "series": "CES0500000003", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True})],
        body=[section("Pay growth", "Percent change in average hourly earnings from a year earlier.",
                      chart("Average hourly earnings, change from a year earlier", "line",
                            [{"file": "labor", "id": "SMU02000000500000003", "label": "Alaska", "transform": "yoy_pct"}, {"file": "labor", "id": "CES0500000003", "label": "U.S.", "transform": "yoy_pct"}],
                            "Monthly. Latest: {date}. Source: BLS Current Employment Statistics via FRED.", dec=1, suffix="%", zero=False, **{"from": "2015-01-01"}),
                      chart("Average hourly earnings", "line",
                            [{"file": "labor", "id": "SMU02000000500000003", "label": "Alaska"}, {"file": "labor", "id": "CES0500000003", "label": "U.S."}],
                            "Dollars per hour, all private employees.", dec=2, prefix="$", zero=False, **{"from": "2010-01-01"})),
              plan(["Average weekly wages by industry and borough from the Quarterly Census of Employment and Wages.",
                    "Real (inflation-adjusted) wage growth using Urban Alaska CPI."])],
        notes=["State earnings estimates come from a sample and move around from month to month; the year-over-year change is more reliable than any single month."],
        sources=[src("FRED, SMU02000000500000003 (Alaska)", "https://fred.stlouisfed.org/series/SMU02000000500000003"),
                 src("FRED, CES0500000003 (U.S.)", "https://fred.stlouisfed.org/series/CES0500000003")],
        tile=tile({"file": "labor", "series": "SMU02000000500000003", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}, {"file": "labor", "series": "SMU02000000500000003", "dec": 2, "prefix": "$", "after": "/hr"}, unit="hourly earnings, y/y")))

    P.append(dict(slug="labor-force-participation", group=G, title="Labor force participation", row="Labor market", status="live",
        lead="The share of Alaskans 16 and older who are working or looking for work. It captures people who have left the job market altogether, which the unemployment rate misses, and it matters for an aging state with a tight supply of workers.",
        stats=[stat("Participation rate, {date}", "Alaska, seasonally adjusted", {"file": "labor", "series": "LBSSA02", "dec": 1, "suffix": "%"}),
               stat("vs. a year earlier", "Percentage points", {"file": "labor", "series": "LBSSA02", "calc": "yoy_diff", "dec": 1, "sign": True}),
               stat("U.S. participation rate", "{date}", {"file": "labor", "series": "CIVPART", "dec": 1, "suffix": "%"}),
               stat("Unemployment rate, {date}", "Alaska, seasonally adjusted", {"file": "labor", "series": "AKUR", "dec": 1, "suffix": "%"}),
               stat("U.S. unemployment rate", "{date}", {"file": "labor", "series": "UNRATE", "dec": 1, "suffix": "%"})],
        body=[section("Participation over time", "Percent of the population 16 and older in the labor force.",
                      chart("Labor force participation rate", "line", [{"file": "labor", "id": "LBSSA02", "label": "Alaska"}, {"file": "labor", "id": "CIVPART", "label": "U.S."}],
                            "Monthly, seasonally adjusted. Latest: {date}. Source: BLS via FRED.", dec=0, suffix="%", zero=False, **{"from": "2000-01-01"})),
              section("Unemployment", "",
                      chart("Unemployment rate", "line", [{"file": "labor", "id": "AKUR", "label": "Alaska"}, {"file": "labor", "id": "UNRATE", "label": "U.S."}],
                            "Monthly, seasonally adjusted. Latest: {date}.", dec=0, suffix="%", **{"from": "2000-01-01"})),
              plan(["Participation by age group, to separate aging from people leaving work.",
                    "Childcare cost and availability as a factor in participation."])],
        notes=["State participation and unemployment rates are modeled estimates from BLS and are revised each spring."],
        sources=[src("FRED, LBSSA02 (Alaska participation)", "https://fred.stlouisfed.org/series/LBSSA02"),
                 src("FRED, AKUR (Alaska unemployment)", "https://fred.stlouisfed.org/series/AKUR"),
                 src("BLS, Local Area Unemployment Statistics", "https://www.bls.gov/lau/")],
        tile=tile({"file": "labor", "series": "LBSSA02", "dec": 1, "suffix": "%"}, {"file": "labor", "series": "CIVPART", "dec": 1, "suffix": "%", "after": " U.S."}, unit="of 16+, seas. adj.")))

    comp, boro = m_pop.get("components", {}), m_pop.get("boroughs", {})
    P.append(dict(slug="net-migration", group=G, title="Net migration", row="Labor market", status="partial",
        lead="People moving to Alaska minus people leaving. Migration is the main way a small state's workforce grows or shrinks quickly, and Alaska has lost more people than it gained for more than a decade.",
        stats=[stat("Net migration", comp.get("label", "").replace("Components of population change, ", "") or "Jul 2024–Jul 2025", value=fnum(comp.get("net_migration"), sign=True)),
               stat("Natural increase", "Births minus deaths, same year", value=fnum(comp.get("natural_increase"), sign=True)),
               stat("Population, {year}", "Census Bureau estimate, July 1", {"file": "population", "series": "AKPOP", "scale": 1000}),
               stat("Years in a row of net out-migration", "Through 2025 · AK DOLWD", value="13")],
        body=[section("Population since 1970", "Resident population, Census Bureau estimates.",
                      chart("Alaska population", "line", [{"file": "population", "id": "AKPOP", "label": "Alaska", "scale": 1000}], "July 1 estimates. Latest: {date}.", zero=False)),
              section("Change by borough, 2020–2025", "Percent change in population, with 2025 population.",
                      hbar("Population change, 2020–2025", [(r[0], r[1]) for r in boro.get("rows", [])], f"Source: {boro.get('source', '')}. {boro.get('note', '')}", dec=1, suffix="%")),
              plan(["Net migration each year back to 1945 from the state's components-of-change table.",
                    "Migration by age, from Permanent Fund Dividend applications, which show who moves in and out each year."])],
        notes=["Alaska's migration estimates come from Permanent Fund Dividend applications, an unusually good source that most states lack."],
        sources=[src("Alaska DOLWD, population estimates", "https://live.laborstats.alaska.gov/data-pages/alaska-population-estimates"),
                 src("Alaska Economic Trends, Apr 2026: population change in the 2020s", "https://live.laborstats.alaska.gov/sites/default/files/trends/apr26art2.pdf"),
                 src("FRED, AKPOP", "https://fred.stlouisfed.org/series/AKPOP")],
        tile=tile(value=fnum(comp.get("net_migration"), sign=True), change="13th year negative", unit="people, to Jul 2025")))

    # ======================= COST OF LIVING =======================
    G = "Micro · Local cost of living"
    cat = []
    # latest month with a year-earlier value (Oct 2025 was never collected)
    d1 = next((d for d in reversed((col.get("series") or {}).get("CUURS49GSA0", {}).get("dates", []))
               if at(col, "CUURS49GSA0", year_ago(d)) is not None), None)
    if d1:
        for sid, meta in (col.get("series") or {}).items():
            if sid == "CUUR0000SA0":
                continue
            v, p = at(col, sid, d1), at(col, sid, year_ago(d1))
            if v is not None and p:
                cat.append((meta["label"].replace("CPI, ", "").replace(", Urban Alaska", "").capitalize(), (v / p - 1) * 100))
        cat.sort(key=lambda r: -r[1])
    ai = m_col.get("annual_inflation", {})
    P.append(dict(slug="cpi", group=G, title="Urban Alaska CPI", row="Local cost of living", status="live",
        lead="The consumer price index for Anchorage and the Mat-Su measures how fast prices are rising for a typical basket of goods and services. It is published every two months and covers urban Alaska only.",
        stats=[stat("Consumer prices, 12-month change", "All items · {date}", {"file": "cost-of-living", "series": "CUURS49GSA0", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Excluding food and energy", "Core · {date}", {"file": "cost-of-living", "series": "CUURS49GSA0L1E", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("U.S. city average", "All items · {date}", {"file": "cost-of-living", "series": "CUUR0000SA0", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Motor fuel", "12-month change · {date}", {"file": "cost-of-living", "series": "CUURS49GSETB", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True})],
        body=[section("Inflation over time", "Percent change from a year earlier.",
                      chart("Consumer prices, change from a year earlier", "line",
                            [{"file": "cost-of-living", "id": "CUURS49GSA0", "label": "Urban Alaska", "transform": "yoy_pct"}, {"file": "cost-of-living", "id": "CUUR0000SA0", "label": "U.S.", "transform": "yoy_pct"}],
                            "Urban Alaska is published every two months; U.S. monthly. Latest: {date}.", dec=1, suffix="%", zero=False, **{"from": "2018-01-01"})),
              section("What's driving prices", f"12-month change by category, {month(d1) if d1 else ''}.",
                      hbar("Price change by category", cat, "Source: BLS, Urban Alaska CPI-U.", dec=1, suffix="%") if cat else ""),
              section("Inflation by year", "Annual average change.",
                      vbars("Annual inflation", ai.get("years", []), [("Urban Alaska", ai.get("urban_alaska", [])), ("U.S. city average", ai.get("us_city_average", []))],
                            f"Source: {ai.get('source', '')}. Next: {ai.get('next_update', '')}.", dec=1, suffix="%") if ai.get("years") else "")],
        notes=["The CPI measures change over time, not the price level: a lower inflation rate does not mean Alaska is cheaper.",
               "October 2025 prices were not collected during the federal shutdown, so some year-over-year comparisons are missing."],
        sources=[src("BLS, Consumer Price Index, Anchorage area", "https://www.bls.gov/regions/west/news-release/consumerpriceindex_anchorage.htm"),
                 src("Alaska DOLWD, CPI tables", "https://live.laborstats.alaska.gov/cpi/table")],
        tile=tile({"file": "cost-of-living", "series": "CUURS49GSA0", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}, {"file": "cost-of-living", "series": "CUUR0000SA0", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True, "after": " U.S."}, unit="12 months")))

    rents = m_hou.get("rents", {})
    rrows = rents.get("rows", [])
    P.append(dict(slug="rent", group=G, title="Median rent", row="Local cost of living", status="partial",
        lead="What a two-bedroom apartment rents for across Alaska, with utilities included, from the state's annual rental market survey, plus the monthly rent index for urban Alaska.",
        stats=[stat("Anchorage 2-bedroom", f"Median adjusted rent · {rents.get('as_of', '')}", value=fnum(next((r[1] for r in rrows if r[0] == "Anchorage"), None), prefix="$")),
               stat("Mat-Su 2-bedroom", f"Change from a year earlier: {fnum(next(((r[1] / r[2] - 1) * 100 for r in rrows if r[0] == 'Matanuska-Susitna'), None), 1, suffix='%', sign=True)}", value=fnum(next((r[1] for r in rrows if r[0] == "Matanuska-Susitna"), None), prefix="$")),
               stat("Rent index, 12-month change", "Urban Alaska CPI, rent of primary residence · {date}", {"file": "cost-of-living", "series": "CUURS49GSEHA", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True})],
        body=[section("Rent by area", f"Median adjusted rent for a two-bedroom apartment, {rents.get('as_of', '')}.",
                      table("Two-bedroom rent by area", ["Area", "Rent, 2026", "Rent, 2025", "Change", "Vacancy"],
                            [(r[0], fnum(r[1], prefix="$"), fnum(r[2], prefix="$"), fnum((r[1] / r[2] - 1) * 100, 1, suffix="%", sign=True), fnum(r[3], 1, suffix="%")) for r in rrows],
                            f"Source: {rents.get('source', '')}. Next: {rents.get('next_update', '')}.", right=(1, 2, 3, 4)) if rrows else ""),
              section("Rent inflation", "Urban Alaska rent index, change from a year earlier.",
                      chart("Rent of primary residence, change from a year earlier", "line", [{"file": "cost-of-living", "id": "CUURS49GSEHA", "label": "Urban Alaska", "transform": "yoy_pct"}],
                            "Latest: {date}. Source: BLS CPI.", dec=1, suffix="%", zero=False, **{"from": "2018-01-01"}))],
        notes=["Adjusted rent includes utilities so units that include them and units that don't can be compared."],
        sources=[src("Alaska DOLWD, rental market survey", "https://live.laborstats.alaska.gov/housing/rentnumbedrms.html")],
        tile=tile(value=fnum(next((r[1] for r in rrows if r[0] == "Anchorage"), None), prefix="$"), change=rents.get("as_of", ""), unit="Anchorage 2BR")))

    anc = m_hou.get("anchorage", {})
    P.append(dict(slug="home-prices", group=G, title="Home prices", row="Local cost of living", status="live",
        lead="How fast home values are rising, from the Federal Housing Finance Agency's house price index, along with Anchorage listing prices and new homes permitted.",
        stats=[stat("Home prices, change from a year earlier", "FHFA index, Alaska · {date}", {"file": "housing", "series": "AKSTHPI", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("U.S.", "Same measure · {date}", {"file": "housing", "series": "USSTHPI", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("30-year mortgage rate", "U.S. average · {date}", {"file": "housing", "series": "MORTGAGE30US", "dec": 2, "suffix": "%"}),
               stat("Anchorage median December listing", anc.get("as_of", ""), value=fnum((anc.get("median_december_listing_price") or [None])[-1], prefix="$")),
               stat("Homes permitted, {year} so far", "Units authorized, through {date}", {"file": "housing", "series": "AKBPPRIV", "calc": "ytd_sum"})],
        body=[section("Home prices over time", "Percent change in the FHFA all-transactions index from a year earlier.",
                      chart("House price index, change from a year earlier", "line",
                            [{"file": "housing", "id": "AKSTHPI", "label": "Alaska", "transform": "yoy_pct"}, {"file": "housing", "id": "USSTHPI", "label": "U.S.", "transform": "yoy_pct"}],
                            "Quarterly. Latest: {date}. Source: FHFA via FRED.", dec=0, suffix="%", zero=False, **{"from": "2010-01-01"})),
              section("Anchorage listings", "Median December listing price.",
                      vbars("Median December listing price, Anchorage", anc.get("years", []), anc.get("median_december_listing_price", []),
                            f"Source: {anc.get('source', '')}.", prefix="$") if anc.get("years") else ""),
              section("New homes", "Housing units authorized by building permits.",
                      chart("Units authorized by permits", "bars", [{"file": "housing", "id": "AKBPPRIV", "label": "Alaska"}],
                            "Annual totals. Faded bar: year to date through {date}. Source: Census via FRED.", agg="sum", **{"from": "2010-01-01"}))],
        notes=["The FHFA all-transactions index includes refinance appraisals as well as sales.",
               "The mortgage rate is a national average; Alaska rates track it closely."],
        sources=[src("FHFA, House Price Index", "https://www.fhfa.gov/data/hpi"),
                 src("FRED, AKSTHPI", "https://fred.stlouisfed.org/series/AKSTHPI"),
                 src("FRED, AKBPPRIV", "https://fred.stlouisfed.org/series/AKBPPRIV"),
                 src("Municipality of Anchorage, Housing Action Plan 2026 progress report", "https://www.muni.org/Departments/Assembly/Documents/Assembly%20Housing%20Action%20Plan_2026%20Progress%20Report.pdf")],
        tile=tile({"file": "housing", "series": "AKSTHPI", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}, {"file": "housing", "series": "USSTHPI", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True, "after": " U.S."}, unit="FHFA index, y/y")))

    P.append(dict(slug="grocery-basket", group=G, title="Grocery basket", row="Local cost of living", status="partial",
        lead="What groceries cost in Anchorage compared with rural hubs. Until the community survey is added, this page tracks food price inflation for urban Alaska.",
        stats=[stat("Food at home, 12-month change", "Urban Alaska CPI · {date}", {"file": "cost-of-living", "series": "CUURS49GSAF11", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Food away from home", "12-month change · {date}", {"file": "cost-of-living", "series": "CUURS49GSEFV", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True})],
        body=[section("Food prices", "Percent change from a year earlier, urban Alaska.",
                      chart("Food prices, change from a year earlier", "line",
                            [{"file": "cost-of-living", "id": "CUURS49GSAF11", "label": "Groceries", "transform": "yoy_pct"}, {"file": "cost-of-living", "id": "CUURS49GSEFV", "label": "Restaurants", "transform": "yoy_pct"}],
                            "Latest: {date}. Source: BLS, Urban Alaska CPI.", dec=0, suffix="%", zero=False, **{"from": "2018-01-01"})),
              plan(["The weekly cost of a standard grocery basket by community from the UAF Cooperative Extension Service food cost survey, Anchorage vs. Bethel, Nome, Kotzebue and other hubs.",
                    "The gap between Anchorage and rural communities over time."])],
        sources=[src("BLS, Urban Alaska CPI", "https://www.bls.gov/regions/west/news-release/consumerpriceindex_anchorage.htm"),
                 src("UAF Cooperative Extension Service, food cost survey", "https://www.uaf.edu/ces/")],
        tile=tile({"file": "cost-of-living", "series": "CUURS49GSAF11", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}, None, unit="groceries, 12 months")))

    # ======================= MACRO =======================
    G = "Macro"
    P.append(dict(slug="gdp", group=G, title="Gross domestic product", row="Macro", status="live",
        lead="The value of everything produced in Alaska, adjusted for inflation, from the Bureau of Economic Analysis. Oil and gas swing the total, and quarterly state figures are often revised by several points.",
        stats=[stat("Real GDP growth, {date}", "Annual rate", {"file": "gdp", "series": "AKRQGSP", "calc": "qgrowth", "dec": 1, "suffix": "%", "sign": True}),
               stat("Real GDP, {year}", "Billions of chained 2017 dollars", {"file": "gdp", "series": "AKRGSP", "scale": 0.001, "dec": 1, "prefix": "$", "suffix": "B"}),
               stat("Growth, {year}", "From the year before", {"file": "gdp", "series": "AKRGSP", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Mining, incl. oil and gas, share", "Of real GDP · {date}", {"file": "gdp", "series": "AKMINRQGSP", "calc": "ratio", "over": {"file": "gdp", "series": "AKRQGSP"}, "scale": 100, "dec": 1, "suffix": "%"}),
               stat("Government share", "Of real GDP · {date}", {"file": "gdp", "series": "AKGOVRQGSP", "calc": "ratio", "over": {"file": "gdp", "series": "AKRQGSP"}, "scale": 100, "dec": 1, "suffix": "%"})],
        body=[section("Real GDP since 1997", "Billions of chained 2017 dollars.",
                      chart("Real GDP, Alaska", "line", [{"file": "gdp", "id": "AKRGSP", "label": "Alaska", "scale": 0.001}], "Annual. Latest: {date}. Source: BEA via FRED.", dec=0, prefix="$", suffix="B", zero=False)),
              section("Quarterly growth", "Real GDP, percent change at an annual rate.",
                      chart("Quarterly real GDP growth", "bars", [{"file": "gdp", "id": "AKRQGSP", "label": "Alaska", "transform": "qgrowth"}], "Latest: {date}.", dec=1, suffix="%", **{"from": "2022-01-01"})),
              section("Two big pieces", "Real output of mining (mostly oil and gas) and government.",
                      chart("Real GDP by industry", "line", [{"file": "gdp", "id": "AKMINRQGSP", "label": "Mining, oil and gas", "scale": 0.001}, {"file": "gdp", "id": "AKGOVRQGSP", "label": "Government", "scale": 0.001}],
                            "Billions of chained 2017 dollars, quarterly at annual rates.", dec=0, prefix="$", suffix="B", zero=False, **{"from": "2005-01-01"}))],
        notes=["State GDP comes out about three months after each quarter. Every September, BEA revises several years at once.",
               "GDP counts output produced in Alaska. Permanent Fund earnings and dividends are income to Alaskans but are not part of state GDP.",
               "Mining in BEA's figures is mining, quarrying, and oil and gas extraction, which in Alaska is mostly oil and gas."],
        sources=[src("BEA, GDP by State", "https://www.bea.gov/data/gdp/gdp-state"),
                 src("FRED, AKRGSP (annual)", "https://fred.stlouisfed.org/series/AKRGSP"),
                 src("FRED, AKRQGSP (quarterly)", "https://fred.stlouisfed.org/series/AKRQGSP")],
        tile=tile({"file": "gdp", "series": "AKRQGSP", "calc": "qgrowth", "dec": 1, "suffix": "%", "sign": True}, None, unit="real GDP, annual rate")))

    P.append(dict(slug="current-account", group=G, title="Current account", row="Macro", status="planned",
        lead="Alaska is a small open economy: most of what it consumes is shipped in and most of what it produces is sold outside the state. A state current account adds up what Alaska earns from the rest of the world and what it pays out, borrowing the framework countries use for their balance of payments. No official statistic does this for a state.",
        body=[text("How it works", ["Current account = goods balance + services balance + primary income balance + transfers balance.",
                                    "A surplus means Alaska earns more from outside the state than it pays out; a deficit means spending is financed by inflows such as federal transfers, Permanent Fund returns or borrowing."]),
              table("The four parts and where the data comes from", ["Part", "Money coming in", "Money going out", "Main sources"],
                    [("Goods", "Oil, seafood, minerals sold outside Alaska", "Consumer goods, fuel, building materials shipped in", "Census state exports, DOR, ADF&G, DNR, port tonnage"),
                     ("Services", "Visitor spending, air cargo services", "Freight, insurance, professional services, travel by Alaskans", "Visitor statistics, ANC cargo, BEA, Division of Insurance"),
                     ("Primary income", "Permanent Fund and other investment earnings, pensions", "Earnings of nonresident workers, profits of out-of-state owners", "APFC, ARMB, DOLWD nonresident worker report, DOR"),
                     ("Transfers", "Federal grants, payments to individuals, federal payroll", "Federal taxes paid by Alaskans", "BEA, USAspending, IRS Statistics of Income")],
                    "Methodology draft. Figures will be published once each line is sourced and checked."),
              plan(["Assemble each line for 2019 onward from the sources above.",
                    "Settle three classification choices: whether federal payroll counts as a service export, which seafood value to use, and how to estimate profits paid to out-of-state owners.",
                    "Publish the balance with and without federal flows, and a three-year average to smooth oil price swings."], "Next steps")],
        notes=["No figures are shown yet. Early estimates were rough and will not be published until each line is verified against its source."],
        tile=tile(unit="annual balance, estimate")))

    return P


# ---------------------------------------------------------------- front page

ROW_INTRO = {
    "Input costs": "What every business has to buy",
    "Physical volumes": "Throughput that leads official data",
    "Business dynamism": "New firms and who survives",
    "Labor market": "Who is working, and for what",
    "Local cost of living": "Prices where people actually live",
}


def tile_html(p):
    t = p["tile"]
    data = {k: t[k] for k in ("main", "chg") if t.get(k)}
    attr = f' data-tile="{spec_attr(data)}"' if t.get("main") else ""
    val = E(t["value"]) if t.get("value") else "—"
    na = "" if t.get("value") else " na"
    return (f'<a class="tile" href="/{p["slug"]}/"{attr}><span class="lbl">{E(p["title"])}</span>'
            f'<span class="val{na}" data-v>{val}</span><span class="cmp" data-c>{E(t.get("change") or "")}</span>'
            f'<span class="meta"><span>{E(t.get("unit") or "")}</span><span data-d></span></span></a>')


def micro_html(P):
    rows = []
    for row, intro in ROW_INTRO.items():
        tiles = "".join(tile_html(p) for p in P if p.get("row") == row)
        rows.append(f'<div class="row"><div class="row-head"><h3>{E(row)}</h3><span>{E(intro)}</span></div><div class="tiles">{tiles}</div></div>')
    return ('<section id="micro" aria-labelledby="h-micro">\n  <div class="sec-head"><h2 id="h-micro">Micro</h2>'
            '<p>The prices, volumes and decisions that sit underneath the headline numbers.</p></div>\n'
            '  <div class="matrix">\n' + "\n".join(rows) + "\n  </div>\n</section>")


def macro_html():
    gdp_main = {"file": "gdp", "series": "AKRQGSP", "calc": "qgrowth", "dec": 1, "suffix": "%", "sign": True}
    gdp_chart = chart("Real GDP, Alaska", "line", [{"file": "gdp", "id": "AKRGSP", "label": "Alaska", "scale": 0.001}], "Billions of chained 2017 dollars. Source: BEA.", dec=0, prefix="$", suffix="B", zero=False, height=200)
    sub = lambda label, spec: f'<div class="stat" data-spec="{spec_attr(spec)}"><b>—</b><span data-t="{E(label)}">{E(label)}</span></div>'
    return f"""<section id="macro" aria-labelledby="h-macro">
  <div class="sec-head"><h2 id="h-macro">Macro</h2><p>The state as a whole: what it produces, and what it earns from and pays to the outside world.</p></div>
  <div class="macro">
    <article class="panel">
      <span class="kick">Output</span>
      <h3><a href="/gdp/">Gross domestic product</a></h3>
      <div class="headline stat" data-spec="{spec_attr(gdp_main)}"><b>—</b><span data-t="Real GDP growth, {{date}}, annual rate">Real GDP growth, annual rate</span></div>
      {gdp_chart}
      <div class="sub">
        {sub("Real GDP, {year}", {"file": "gdp", "series": "AKRGSP", "scale": 0.001, "dec": 1, "prefix": "$", "suffix": "B"})}
        {sub("Growth, {year}", {"file": "gdp", "series": "AKRGSP", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True})}
        {sub("Oil & gas share", {"file": "gdp", "series": "AKMINRQGSP", "calc": "ratio", "over": {"file": "gdp", "series": "AKRQGSP"}, "scale": 100, "dec": 1, "suffix": "%"})}
        {sub("Government share", {"file": "gdp", "series": "AKGOVRQGSP", "calc": "ratio", "over": {"file": "gdp", "series": "AKRQGSP"}, "scale": 100, "dec": 1, "suffix": "%"})}
      </div>
      <a class="more" href="/gdp/">GDP page →</a>
    </article>
    <article class="panel">
      <span class="kick">External balance</span>
      <h3><a href="/current-account/">Current account</a></h3>
      <div class="headline"><b class="na">—</b><span>Annual balance, estimate · in development</span></div>
      <div class="chartph">Credits vs. debits, with and without federal flows</div>
      <div class="sub">
        <div><b class="na">—</b><span>Goods</span></div>
        <div><b class="na">—</b><span>Services</span></div>
        <div><b class="na">—</b><span>Primary income</span></div>
        <div><b class="na">—</b><span>Transfers</span></div>
      </div>
      <a class="more" href="/current-account/">How it will be built →</a>
    </article>
  </div>
</section>"""


FRONT_CSS = """
a.tile{text-decoration:none;color:inherit}
.panel h3 a{color:var(--ink);text-decoration:none} .panel h3 a:hover{text-decoration:underline}
.headline.stat{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.headline b.na,.sub b.na{color:var(--rule)}
.sub .stat{padding:10px 12px 10px 0;border-bottom:1px solid var(--rule);display:flex;flex-direction:column}
.sub .stat b{font-family:var(--display);font-size:20px;font-variant-numeric:tabular-nums}
.sub .stat span{font-size:12.5px;color:var(--muted)}
.chartph{height:200px;border:1px dashed var(--rule);border-radius:4px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px;background:var(--tile)}
.panel figure.chart{margin:0;height:auto;border:0;background:none;display:block} figure.chart h3{display:none} figure.chart svg{width:100%;height:auto;display:block}
.sub .stat b{color:var(--ink)}
figure.chart figcaption{font-size:12px;color:var(--muted)}
"""


def build_front(P):
    p = SITE / "index.html"
    s = p.read_text()
    s = re.sub(r'<section id="micro".*?</section>', lambda m: micro_html(P), s, count=1, flags=re.S)
    s = re.sub(r'<section id="macro".*?</section>', lambda m: macro_html(), s, count=1, flags=re.S)
    s = re.sub(r"<script>\s*/\* Electricity tile.*?</script>\s*", "", s, flags=re.S)
    if "/js/ind.js" not in s:
        s = s.replace("</body>", '<script src="/js/ind.js"></script>\n</body>')
    block = "/* front-page tiles (build_pages) */" + FRONT_CSS + "/* end build_pages */"
    if "/* front-page tiles (build_pages) */" in s:
        s = re.sub(r"/\* front-page tiles \(build_pages\) \*/.*?(/\* end build_pages \*/|(?=</style>))", lambda m: block, s, count=1, flags=re.S)
    else:
        s = s.replace("</style>", block + "</style>", 1)
    p.write_text(s)


def build_sources(P):
    """Per-page source lists on /sources/, between PAGE-SOURCES markers."""
    p = SITE / "sources" / "index.html"
    s = p.read_text()
    groups = {}
    for pg in P:
        if pg.get("custom"):
            continue
        groups.setdefault(pg["group"], []).append(pg)
    out = '<!-- PAGE-SOURCES (built by scripts/build_pages.py) -->\n'
    for g, items in groups.items():
        out += f'<section aria-label="{E(g)}"><h2>{E(g)}</h2>'
        for pg in items:
            links = "".join(f'<li><a href="{E(u)}" target="_blank" rel="noopener">{E(n)}</a></li>' for n, u in pg.get("sources", []))
            out += (f'<div class="src" id="{pg["slug"]}"><h3><a href="/{pg["slug"]}/" style="color:inherit">{E(pg["title"])}</a></h3><dl>'
                    f'<dt>Status</dt><dd>{E(STATUS[pg.get("status", "live")])}</dd>'
                    + (f'<dt>Sources</dt><dd><ul style="margin:0;padding-left:18px">{links}</ul></dd>' if links else '<dt>Sources</dt><dd>To be chosen; see the page for what is planned.</dd>')
                    + "</dl></div>")
        out += "</section>"
    out += "\n<!-- /PAGE-SOURCES -->"
    if "<!-- PAGE-SOURCES" in s:
        s = re.sub(r"<!-- PAGE-SOURCES.*?<!-- /PAGE-SOURCES -->", lambda m: out, s, flags=re.S)
    else:
        s = s.replace("<footer>", out + "\n\n<footer>", 1)
    p.write_text(s)


def main():
    P = pages()
    n = 0
    for p in P:
        if p.get("custom"):
            continue
        out = SITE / p["slug"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page_html(p))
        n += 1
    build_front(P)
    build_sources(P)
    print(f"built {n} pages and the front page")


if __name__ == "__main__":
    main()
