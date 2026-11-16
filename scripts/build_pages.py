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


def hbar(title, rows, caption="", dec=0, prefix="", suffix="", highlight=None, lw=210):
    """Static horizontal bars: rows = [(label, value)]."""
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return ""
    mx = max(abs(v) for _, v in rows) or 1
    W, Lw, Rw, RH = 680, lw, 80, 30
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


def vbars(title, labels, values, caption="", dec=0, prefix="", suffix="", partial_last=False, colors=None, show_values=None):
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
            if (n * k <= 16) if show_values is None else show_values:
                s += f'<text x="{x + bw / 2 - 1:.1f}" y="{(Y(v) + 13) if v < 0 else top - 5:.1f}" text-anchor="middle" font-size="{11 if n * k <= 16 else 10}" font-weight="600" fill="{INK}">{E(fnum(v, dec, prefix, suffix))}</text>'
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

    # Hand-built page (site/natural-gas/index.html), like Electricity. Its figures live in
    # data/manual/natural-gas.json (Enstar cost of gas, supply, projects) and data/natural-gas.json (EIA).
    gca = manual("natural-gas").get("gca", {}).get("rows", [])
    g_now, g_prev = (gca[-1], gca[-2]) if len(gca) >= 2 else (None, None)
    P.append(dict(slug="natural-gas", group=G, title="Railbelt natural gas", custom=True, row="Input costs",
        tile=tile(value=f"${g_now['value']:.2f}" if g_now else "—",
                  change=f"{(g_now['value'] / g_prev['value'] - 1) * 100:+.1f}% from {g_prev['period']}" if g_now else "",
                  unit="Enstar cost of gas, per Mcf")))

    P.append(dict(slug="freight", group=G, title="Freight rate index", row="Input costs", status="planned",
        lead="Almost everything sold in Alaska arrives by ship, barge, truck or plane, so shipping costs are built into the price of nearly every good. No public index tracks what it costs to move freight to and within Alaska. This page will build one.",
        body=[plan(["Container rates from Tacoma to Anchorage from the carriers' published tariffs.",
                    "Barge rates from Anchorage or Seattle to regional hubs such as Bethel, Nome and Kotzebue.",
                    "Air freight and bypass mail rates to rural communities.",
                    "National freight price indexes from the Bureau of Labor Statistics for context.",
                    "An index (base year = 100) combining these, updated as tariffs change."], "How the index will be built")],
        notes=["This page is a placeholder. No figures are shown until the index is built."],
        tile=tile(unit="Seattle–Anchorage")))

    P.append(dict(slug="health-premium", group=G, title="Employer health premium", row="Input costs", status="static", front=False,
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

    P.append(dict(slug="commercial-lease", group=G, title="Commercial lease rate", row="Input costs", status="planned", front=False,
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

    # ANC air cargo: hand-kept figures in data/manual/air-cargo.json; Alaska air
    # transportation jobs live from FRED (data/air-cargo.json).
    ac = manual("air-cargo")
    ton, hy, lw = ac.get("tonnage", {}), ac.get("half_year", {}), ac.get("landed_weight", {})
    ust, wt, ld, rm = ac.get("us_top", {}), ac.get("world_top", {}), ac.get("landings", {}), ac.get("recent_months", {})
    wb, nb, fl, jb, tr = (ac.get(k, {}) for k in ["carriers_widebody_2024", "carriers_narrowbody_2024", "flows_2021", "jobs_2021", "air_trade_2023"])
    t_y, t_v, t_r = ton.get("years", []), ton.get("values", []), ton.get("world_rank", [])
    h_p, h_a, h_f = hy.get("periods", []), hy.get("anc", []), hy.get("fai", [])
    h2 = hy.get("second_half", {})
    l_y, l_v = lw.get("years", []), lw.get("values", [])
    pct = lambda a, b: (a / b - 1) * 100 if a and b else None
    h_chg = pct(h_a[-1], h_a[0]) if len(h_a) == 2 else None
    jobs_spec = {"file": "air-cargo", "series": "SMU02000004348100001", "scale": 1000, "dec": 0}
    two = lambda *b: '<div class="two">' + "".join(x for x in b if x) + "</div>"
    P.append(dict(slug="air-cargo", group=G, title="ANC air cargo", row="Physical volumes", status="partial",
        lead="Anchorage sits on the great-circle route between Asia and North America, within about nine and a half hours' flying of 90% of the industrialized world, and most trans-Pacific freighters stop there to refuel. That makes Ted Stevens Anchorage International the busiest cargo airport in the United States and the third busiest in the world, though most of the freight is only passing through.",
        stats=[stat("Cargo handled, " + (t_y[-1] if t_y else ""), f"Million metric tons · #{t_r[-1] if t_r else '—'} in the world (ACI, preliminary)", value=fnum(t_v[-1] if t_v else None, 2)),
               stat("First half of " + (h_p[-1][-4:] if h_p else ""), f"Million metric tons · {fnum(h_chg, 1, suffix='%', sign=True)} from a year earlier", value=fnum(h_a[-1] / 1e6 if h_a else None, 2)),
               stat("All-cargo landed weight, " + (l_y[-1] if l_y else ""), f"Billion pounds · #1 in the U.S. (FAA) · {fnum(pct(l_v[-1], l_v[-2]) if len(l_v) > 1 else None, 1, suffix='%', sign=True)}", value=fnum(l_v[-1] if l_v else None, 1)),
               stat("Air transportation jobs, {date}", "Alaska, all airlines, passenger and cargo", jobs_spec),
               stat("vs. a year earlier", "Air transportation jobs, same month", {"file": "air-cargo", "series": "SMU02000004348100001", "calc": "yoy_pct", "dec": 1, "suffix": "%", "sign": True}),
               stat("Jobs tied to cargo airlines", "Incl. FedEx and UPS, with spinoff jobs · 2021", value=fnum(jb.get("cargo_jobs")))],
        body=[section("Cargo handled each year", "Freight and mail loaded, unloaded or passing through ANC, in millions of metric tons. Anchorage counts transit freight that never leaves the plane during a refueling stop, which most airports don't.",
                      vbars(ton.get("label", "Cargo handled at ANC"), t_y, t_v,
                            f"{ton.get('as_of', '')}. Source: {ton.get('source', '')}. World rank in {t_y[-1] if t_y else ''}: #{t_r[-1] if t_r else ''}. Next: {ton.get('next_update', '')}.", dec=2, show_values=True),
                      two(vbars(lw.get("label", "All-cargo landed weight"), l_y, l_v,
                                f"Source: {lw.get('source', '')}. ANC ranked #2 behind Memphis through 2020 and #1 since 2021.", dec=1),
                          table("This year and last: cargo tonnage by half-year", ["Period", "ANC, metric tons", "Change"],
                                [[h2.get("periods", ["", ""])[0], fnum(h2.get("anc", [None])[0]), ""],
                                 [h2.get("periods", ["", ""])[-1], fnum(h2.get("anc", [None])[-1]), fnum(pct(h2.get("anc", [0, 0])[-1], h2.get("anc", [0, 0])[0]), 1, suffix="%", sign=True)],
                                 [h_p[0] if h_p else "", fnum(h_a[0] if h_a else None), ""],
                                 [h_p[-1] if h_p else "", fnum(h_a[-1] if h_a else None), fnum(h_chg, 1, suffix="%", sign=True)]] if h_a and h2 else [],
                                f"Source: {hy.get('source', '')}; {h2.get('source', '')}. Fairbanks, ANC's backup airport, handled {fnum(h_f[-1] if h_f else None)} metric tons in {h_p[-1] if h_p else ''}, up from {fnum(h_f[0] if h_f else None)}.", right=(1, 2)))),
              section("How ANC compares", "Two ways to rank cargo airports: tons of freight and mail handled (ACI, worldwide) and the landed weight of cargo planes (FAA, U.S. only).",
                      two(hbar(wt.get("label", "World's busiest cargo airports"), [tuple(r) for r in wt.get("rows", [])],
                               f"Source: {wt.get('source', '')}.", dec=2, highlight="Anchorage", lw=150),
                          hbar(ust.get("label", "Top U.S. all-cargo airports"), [tuple(r) for r in ust.get("rows", [])],
                               f"Source: {ust.get('source', '')}. Next: {ust.get('next_update', '')}.", dec=2, highlight="Anchorage", lw=150))),
              section("The flights", "Cargo planes now make up most landings at ANC. The big international freighters are mostly Boeing 747s and 777s; a fleet of smaller planes carries freight on to the rest of Alaska.",
                      vbars("Aircraft landings at ANC, cargo and passenger", ld.get("years", []), [("Cargo", ld.get("cargo", [])), ("Passenger", ld.get("passenger", []))],
                            f"In 2021: {fnum((ld.get('cargo') or [None])[-1])} cargo and {fnum((ld.get('passenger') or [None])[-1])} passenger landings. Source: {ld.get('source', '')}. In fiscal 2026 the airport reported more than 55,000 cargo landings, about 138 wide-body cargo landings a day."),
                      two(hbar(wb.get("label", "Wide-body freighter landings by carrier"), [tuple(r) for r in wb.get("rows", [])],
                               f"Source: {wb.get('source', '')}.", suffix="%", lw=150),
                          hbar(nb.get("label", "Narrow-body freighter landings by carrier"), [tuple(r) for r in nb.get("rows", [])],
                               f"Source: {nb.get('source', '')}. These planes carry freight between Anchorage, Seattle and rural Alaska.", suffix="%", lw=190)),
                      table(rm.get("label", "Recent months"), ["Month", "Landings", "vs. a year earlier"],
                            [[r[0], fnum(r[1]), r[2] or "—"] for r in rm.get("rows", [])]
                            + ([[f"12 months to {rm['ltm']['through']}", fnum(rm["ltm"]["landings"]), rm["ltm"]["change"]]] if rm.get("ltm") else []),
                            f"International freighters only; the trade press hasn't reported every month. Source: {rm.get('source', '')}.", right=(1, 2))),
              section("What passes through", f"In 2021, the latest year studied in detail, {fl.get('transit_mt', '')} million metric tons stayed aboard during refueling stops and {fl.get('onoff_mt', '')} million were loaded or unloaded. About {fl.get('asia_to_us_share', '')}% of Asia-to-U.S. air cargo went through Anchorage, and {fl.get('us_to_asia_share', '')}% of U.S.-to-Asia.",
                      two(table("Where freighters to ANC came from, 2021", ["City", "Metric tons", "Flights"],
                                [[r[0], fnum(r[1]), fnum(r[2])] for r in fl.get("origins", [])], f"Top Asian origins. Source: {fl.get('source', '')}.", right=(1, 2)),
                          table("Where freighters from ANC went, 2021", ["City", "Metric tons", "Flights"],
                                [[r[0], fnum(r[1]), fnum(r[2])] for r in fl.get("destinations", [])], f"Top Lower 48 destinations. Source: {fl.get('source', '')}.", right=(1, 2))),
                      text("Trade that clears customs in Anchorage", [
                          f"Goods that clear customs at the Anchorage port of entry are a slice of what flies through. In 2023 air imports recorded there were worth ${tr.get('imports_bn', 0):.1f} billion and air exports ${tr.get('exports_bn', 0):.1f} billion. By weight the leading goods were electrical equipment and machinery, then instruments, plastics and toys; fish and seafood ranked eighth.",
                      ]) if tr else ""),
              section("Jobs", "Payroll jobs at airlines in Alaska, live from the Bureau of Labor Statistics. This counts passenger and cargo airlines alike; ground handling, fueling and freight forwarding are counted in other industries.",
                      chart("Air transportation jobs, Alaska", "line", [{"file": "air-cargo", "id": "SMU02000004348100001", "label": "Air transportation", "scale": 1000}],
                            "Monthly, not seasonally adjusted. Latest: {date}. Source: BLS via FRED, SMU02000004348100001.", **{"from": "2005-01-01"}),
                      table("Jobs and earnings that depend on ANC, 2021", ["Measure", "Jobs", "Labor income"],
                            [["Direct, at the airport", fnum(jb.get("direct")), ""],
                             ["Spinoff, in the wider economy", fnum(jb.get("indirect_induced")), ""],
                             ["Total", fnum(jb.get("total")), fnum(jb.get("labor_income_m"), 0, "$", "M")],
                             ["Of which: cargo airlines and express carriers", fnum(jb.get("cargo_jobs")), fnum(jb.get("cargo_labor_income_m"), 0, "$", "M")]] if jb else [],
                            f"Source: {jb.get('source', '')}. The state airport system credits ANC with about 1 in 7 jobs in the Anchorage region.", right=(1, 2))),
              section("What's changing", "",
                      text("Trade rules", ["The U.S. ended duty-free entry for low-value parcels (the $800 de minimis exemption) on goods from China in May 2025 and on goods from everywhere that August. Cross-border e-commerce by air fell sharply, and NorthLink Aviation's planned e-commerce hub at ANC stalled. Anchorage's tonnage kept growing anyway as general freight and electronics filled the space. FedEx cut its Anchorage landings by about 12% in the first nine months of 2025, while Kalitta Air, China Airlines and EVA Air added flights."]),
                      text("Jet fuel", ["Freighters stop in Anchorage mainly to refuel, and more than 70% of the airport's jet fuel arrives by tanker from Asian refineries. In March 2026, with the Strait of Hormuz disrupted and China limiting refined fuel exports, international cargo landings fell 8% from a year earlier, the first real monthly decline in over a year. By August they were 5% above a year earlier."]),
                      text("Room to park", ["Heavy snowstorms have shown how tight wide-body parking is at ANC: carriers with reserved spots keep landing, others divert. Private projects on airport land aim to add capacity: NorthLink Aviation's 120-acre South Airpark campus (a 55-year lease, with up to 11 drive-through hardstands planned), a cold-storage warehouse and hardstands by Alaska Cold Cargo Storage on the North Airpark, and six hardstands proposed by Alaska Airport Partners on the West Airpark. The state also lists $126 million for nine more airport-run hardstands."]),
                      text("Fairbanks as the backup", [f"Fairbanks International, about 260 miles north, is ANC's main diversion airport. Its cargo tonnage nearly tripled in the first half of 2026, from {fnum(h_f[0] if h_f else None)} to {fnum(h_f[-1] if h_f else None)} metric tons, as carriers used it during storms and summer construction at ANC."])),
              plan(["Monthly cargo tonnage and landings from the state airport system's monthly reports, once a regularly published table is found.",
                    "Jet fuel sold at ANC (fuel flowage), the clearest measure of the refueling business.",
                    "FAA landed weight back to 2000, and a comparison with trans-Pacific air freight rates."])],
        notes=["Tonnage counts freight and mail loaded, unloaded or in transit. Anchorage is the only top-10 airport whose count includes transit freight that stays aboard; in 2021 that was about 46% of its total, so ANC's world rank overstates how much freight is handled on the ground.",
               "Landed weight is the certificated maximum landing weight of the all-cargo aircraft that land, summed over the year. It measures flights, not freight, and is what the FAA uses to share out cargo grants to airports.",
               "ACI revises earlier years; the series here uses each year's figure as published with that year's ranking. The 2014 figure is from Air Cargo World. 2025 is preliminary.",
               "The 2021 economic impact study gives two figures for Anchorage's share of Asia-to-U.S. air cargo: 51% in its summary and 63% in its tables. The page uses the table figure.",
               "Recent-month landings are NorthLink Aviation's counts of international cargo landings, compiled from airport data and reported in the trade press. NorthLink is developing cargo facilities at ANC."],
        sources=[src("ACI World, 2025 airport rankings (via Wikipedia's list of busiest cargo airports)", "https://en.wikipedia.org/wiki/List_of_busiest_airports_by_cargo_traffic"),
                 src("FAA, CY2025 all-cargo airports by landed weight, final", "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/ARP-CY2025-all-cargo-airports.pdf"),
                 src("FAA, all-cargo data, previous years", "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/previous_years"),
                 src("Alaska International Airport System, 2026 Development Report, Q1–Q2", "https://dot.alaska.gov/aias/assets/2026-AIAS-Development-Report-Q1Q2.pdf"),
                 src("Alaska International Airport System, Biannual Report, Q3–Q4 2025", "https://dot.alaska.gov/aias/assets/AIAS-Biannual-Report-Q3-Q4-2025.pdf"),
                 src("Alaska International Airport System, Overview of ANC Air Cargo Activity 2016–2024", "https://dot.alaska.gov/aias/assets/Overview-of-ANC-Air-Cargo-Activity-2016-2024.pdf"),
                 src("McKinley Research Group for AEDC, ANC Economic Impact Study (2023)", "https://dot.alaska.gov/aias/assets/AEDC-ANC-Economic-Impact-Report.pdf"),
                 src("Ted Stevens Anchorage International Airport, facts", "https://dot.alaska.gov/anc/passengers-facts.shtml"),
                 src("FRED, Air transportation jobs in Alaska (SMU02000004348100001)", "https://fred.stlouisfed.org/series/SMU02000004348100001"),
                 src("STAT Times, Freighter landings rise 5% at ANC in August (Sep 2026)", "https://www.stattimes.com/aviation/freighter-landings-rise-5-at-anc-in-august-1360616"),
                 src("The Loadstar, Atlas Air trims Anchorage operations as Fairbanks emerges as fallback", "https://theloadstar.com/atlas-air-trims-anchorage-operations-as-fairbanks-emerges-as-fallback/"),
                 src("The Loadstar, Ecommerce hopes for Anchorage tied in red tape, but airport traffic grows", "https://theloadstar.com/ecommerce-hopes-for-anchorage-tied-in-red-tape-but-airport-traffic-grows/")],
        tile=tile(value=fnum(h_a[-1] / 1e6, 2, suffix="M") if h_a else "—", change=f"{fnum(h_chg, 1, suffix='%', sign=True)} y/y" if h_chg is not None else "",
                  unit=f"metric tons, {h_p[-1] if h_p else ''}")))

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
    # ---- Firm entry rate: Census Business Dynamics Statistics (data/firm-dynamics.json)
    fd = load("firm-dynamics")
    fds = fd.get("series") or {}
    FD = "firm-dynamics"

    def fser(sid):
        s = fds.get(sid) or {}
        return dict(zip((d[:4] for d in s.get("dates", [])), s.get("values", [])))

    ak_e, us_e = fser("FIRM_ENTRY_RATE-AK"), fser("FIRM_ENTRY_RATE-US")
    yrs = sorted(set(ak_e) & set(us_e))
    ly = yrs[-1] if yrs else None
    vint = (fds.get("FIRM_ENTRY_RATE-AK") or {}).get("vintage")

    # Decade averages, Alaska vs U.S. (the current decade is labeled with the years it covers so far)
    dec_rows = []
    for d0 in range(1980, 2030, 10):
        ys = [y for y in yrs if d0 <= int(y) < d0 + 10]
        if not ys:
            continue
        a, u = sum(ak_e[y] for y in ys) / len(ys), sum(us_e[y] for y in ys) / len(ys)
        lab = f"{d0}s" if len(ys) == 10 else f"{ys[0]}–{ys[-1]}"
        dec_rows.append((lab, f"{a:.1f}%", f"{u:.1f}%", fnum(a - u, 1, sign=True) + " pts"))

    # Years Alaska ran above the U.S.
    above = [y for y in yrs if ak_e[y] > us_e[y]]

    # Establishment entry by industry, latest year
    SECTORS = [("11", "Agriculture, forestry, fishing"), ("21", "Mining, oil and gas"), ("22", "Utilities"), ("23", "Construction"),
               ("31-33", "Manufacturing"), ("42", "Wholesale trade"), ("44-45", "Retail trade"), ("48-49", "Transportation and warehousing"),
               ("51", "Information"), ("52", "Finance and insurance"), ("53", "Real estate"), ("54", "Professional services"),
               ("56", "Administrative and support"), ("61", "Education"), ("62", "Health care and social assistance"),
               ("71", "Arts and recreation"), ("72", "Accommodation and food"), ("81", "Other services")]
    sec_rows, sec_bars = [], []
    sec_year = None
    for code, name in SECTORS:
        a, u, n = fser(f"SEC{code}:ESTAB_ENTRY_RATE-AK"), fser(f"SEC{code}:ESTAB_ENTRY_RATE-US"), fser(f"SEC{code}:ESTABS-AK")
        if not a:
            continue
        y = max(a)
        sec_year = max(sec_year or y, y)
    for code, name in SECTORS:
        a, u, n = fser(f"SEC{code}:ESTAB_ENTRY_RATE-AK"), fser(f"SEC{code}:ESTAB_ENTRY_RATE-US"), fser(f"SEC{code}:ESTABS-AK")
        if sec_year not in a:
            continue
        # five-year average smooths the year-to-year noise in small Alaska industries
        last5 = [str(int(sec_year) - k) for k in range(5)]
        a5 = [a[y] for y in last5 if y in a]
        u5 = [u[y] for y in last5 if y in u]
        avg_a = sum(a5) / len(a5) if len(a5) == 5 else None
        avg_u = sum(u5) / len(u5) if len(u5) == 5 else None
        sec_rows.append((name, fnum(n.get(sec_year)), f"{a[sec_year]:.1f}%", f"{u[sec_year]:.1f}%" if sec_year in u else "—",
                         f"{avg_a:.1f}%" if avg_a is not None else "—", f"{avg_u:.1f}%" if avg_u is not None else "—",
                         fnum(avg_a - avg_u, 1, sign=True) if avg_a is not None and avg_u is not None else "—", avg_a or 0))
        if avg_a is not None and avg_u is not None:
            sec_bars.append((name, avg_a - avg_u))
    sec_rows.sort(key=lambda r: -r[-1])
    sec_rows = [r[:-1] for r in sec_rows]
    sec_bars.sort(key=lambda r: -r[1])
    s5 = f"{int(sec_year) - 4}–{sec_year}" if sec_year else ""

    E_AK = {"file": FD, "series": "FIRM_ENTRY_RATE-AK", "dec": 1, "suffix": "%"}
    P.append(dict(slug="firm-entry", group=G, title="Firm entry rate", row="Business dynamism", status="live" if ly else "partial",
        lead="The share of Alaska's employer businesses that are brand new: firms in their first year with paid employees, as a percentage of all employer firms. A steady flow of new firms is one of the main ways an economy finds new products, raises productivity and creates jobs. The measure comes from the Census Bureau's Business Dynamics Statistics, which covers every employer in the country back to 1978 but is published with a lag of about two years.",
        stats=[stat("Firm entry rate, {year}", "Alaska, share of employer firms that are new", E_AK),
               stat("U.S., {year}", "Same measure, nationwide", {"file": FD, "series": "FIRM_ENTRY_RATE-US", "dec": 1, "suffix": "%"}),
               stat("Alaska vs. U.S.", "Percentage points, {year}", {"file": FD, "series": "FIRM_ENTRY_RATE-AK", "calc": "diff_vs", "over": {"file": FD, "series": "FIRM_ENTRY_RATE-US"}, "dec": 1, "sign": True, "suffix": " pts"}),
               stat("Change from a year earlier", "Alaska, percentage points", {"file": FD, "series": "FIRM_ENTRY_RATE-AK", "calc": "yoy_diff", "dec": 1, "sign": True, "suffix": " pts"}),
               stat("New employer firms, {year}", "Alaska, in their first year", {"file": FD, "series": "STARTUPS-AK"}),
               stat("Employer firms, {year}", "Alaska, all ages", {"file": FD, "series": "FIRMS-AK"})],
        body=[section("The long view", "In 1978 about one U.S. employer firm in seven was new. In Alaska, in the pipeline and early oil-revenue years, it was one in five. Alaska's rate fell to about the national rate after the 1986 oil-price crash, slipped below it around 2000, and has been roughly a point below since. Both have drifted down over the whole period.",
                      chart("Firm entry rate, Alaska and U.S.", "line", [{"file": FD, "id": "FIRM_ENTRY_RATE-AK", "label": "Alaska"}, {"file": FD, "id": "FIRM_ENTRY_RATE-US", "label": "U.S."}],
                            "New employer firms (age 0) as a share of all employer firms, percent. Each year is measured in March. Latest: {date}.", suffix="%", dec=0),
                      table("Average firm entry rate by decade", ["Period", "Alaska", "U.S.", "Alaska vs. U.S."], dec_rows,
                            f"Simple averages of annual rates. Alaska's rate was above the U.S. rate in {len(above)} of {len(yrs)} years from {yrs[0]} to {ly}." if yrs else "", right=(1, 2, 3)) if dec_rows else ""),
              section("New firms and the jobs they bring", "The count of new firms moves with the size of the economy; the share of jobs at those firms shows how much hiring they account for in their first year.",
                      '<div class="two">' +
                      chart("New employer firms, Alaska", "bars", [{"file": FD, "id": "STARTUPS-AK", "label": "Alaska"}], "Firms in their first year with paid employees. Latest: {date}.", **{"from": "2000-01-01"}) +
                      chart("Jobs at new firms, share of all jobs", "line", [{"file": FD, "id": "STARTUP_EMP_SHARE-AK", "label": "Alaska"}, {"file": FD, "id": "STARTUP_EMP_SHARE-US", "label": "U.S."}],
                            "Employment at age-0 firms as a percentage of total employment, March. Gaps are years the Census Bureau withheld Alaska's figure. Latest: {date}.", suffix="%", dec=1) +
                      "</div>"),
              section("By industry", f"Firm age isn't published by industry for individual states, so this compares the establishment entry rate: new business locations as a share of all locations. Small Alaska industries bounce around from year to year, so the comparison uses the {s5} average." if sec_year else "",
                      hbar(f"Alaska's establishment entry rate minus the U.S. rate, {s5} average", sec_bars, "Percentage points. Positive bars are industries where new locations open more often in Alaska than nationally.", dec=1, suffix=" pts", lw=250) if sec_bars else "",
                      table(f"Establishment entry rate by industry, {sec_year}", ["Industry", "Alaska locations", f"Alaska {sec_year}", f"U.S. {sec_year}", f"Alaska {s5} avg", f"U.S. {s5} avg", "Gap (pts)"], sec_rows,
                            "Sorted by Alaska's five-year average. Establishments are individual business locations; a new store opened by an existing chain counts as a new establishment but not as a new firm.", right=(1, 2, 3, 4, 5, 6)) if sec_rows else ""),
              section("A quicker read: openings and closings", f"Business Dynamics Statistics run about two years behind. The BLS Business Employment Dynamics series counts jobs at establishments that opened or closed each quarter, through {q[-1] if q else 'recent quarters'}.", bed_chart),
              section("Related measures", "",
                      chart("Establishment entry rate, Alaska and U.S.", "line", [{"file": FD, "id": "ESTAB_ENTRY_RATE-AK", "label": "Alaska"}, {"file": FD, "id": "ESTAB_ENTRY_RATE-US", "label": "U.S."}],
                            "New establishments as a share of the average number of establishments in the current and prior year, percent. Includes new locations of existing firms. Latest: {date}.", suffix="%", dec=0),
                      text("Three ways to count new businesses", [
                          "Business applications (Census Business Formation Statistics) count filings for an employer ID number. They are monthly and current, but many applications never become businesses with employees.",
                          "The firm entry rate on this page counts businesses that actually started paying employees. It is the most complete measure, covering every employer, but it is annual and about two years old.",
                          "Business Employment Dynamics (BLS) counts jobs at establishments that opened or closed, quarterly, with a lag of about seven months. It counts locations, not firms."]))],
        notes=["A firm is a business and all the locations it owns. A firm is age 0 in the year it first reports paid employees, measured in March. Firms with no employees (sole proprietors, most gig work) are not counted.",
               "Entry rate = age-0 firms ÷ all employer firms in the same year, the standard Census startup-rate definition. The U.S. figures use the national table; Census notes that firm counts summed across states can run slightly higher than the national total, because a firm operating in several states is counted once in each.",
               f"Figures are from the {vint} vintage of the Business Dynamics Statistics. Each new vintage can revise earlier years." if vint else "Each new vintage of the Business Dynamics Statistics can revise earlier years.",
               "The data refresh reads the Census Bureau's published CSV tables, checks for a new vintage on every run, and needs no API key.",
               "Alaska has about 15,000 employer firms, so 150 more or fewer new firms moves the rate by a full percentage point. Read single-year changes with care."],
        sources=[src("Census Bureau, Business Dynamics Statistics", "https://www.census.gov/programs-surveys/bds.html"),
                 src("Census Bureau, BDS data tables (CSV)", "https://www.census.gov/data/datasets/time-series/econ/bds/bds-datasets.html"),
                 src("BLS, Business Employment Dynamics", "https://www.bls.gov/bdm/")],
        tile=tile(E_AK, {"file": FD, "series": "FIRM_ENTRY_RATE-AK", "calc": "diff_vs", "over": {"file": FD, "series": "FIRM_ENTRY_RATE-US"}, "dec": 1, "sign": True, "after": " pts vs. U.S."}, unit="% of employer firms") if ly else
             tile(value=fnum(op_[-1]) if op_ else None, change=f"jobs, {q[-1]}" if q else "", unit="jobs gained at openings")))

    for slug, title, lead, i_val, lbl in [
        ("firm-exit", "Firm exit rate", "How often businesses close. Some turnover is healthy, as resources move from struggling firms to growing ones; a rising exit rate with few entrants signals a shrinking business base.", cl_, "Jobs lost at closings")]:
        P.append(dict(slug=slug, group=G, title=title, row="Business dynamism", status="partial",
            lead=lead,
            stats=[stat(f"{lbl}, {q[-1] if q else ''}", "Establishments, seasonally adjusted", value=fnum(i_val[-1]) if i_val else "—"),
                   stat("Same quarter a year earlier", q[0] if q else "", value=fnum(i_val[0]) if i_val else "—")],
            body=[section("Openings and closings", "A quarterly BLS series counts jobs at establishments that opened or closed.", bed_chart),
                  plan(["The exit rate itself: firm closures as a share of all firms, from the Census Bureau's Business Dynamics Statistics (annual), compared with the U.S.",
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

    P.append(current_account_page(tile))

    return P


# ---------------------------------------------------------------- current account

def ca_model():
    """Add up site/data/manual/current-account.json. Billions of dollars."""
    d = manual("current-account")
    a, L = d["absorption"], d["lines"]
    v = lambda k: a[k]["value"]
    half = lambda x: (x["high"] - x["low"]) / 2
    absorb = v("pce") + v("investment") + v("state_local")
    tb = v("gdp") - absorb
    tb_sd = (half(a["investment"]) ** 2 + half(a["state_local"]) ** 2) ** 0.5
    tot = lambda acc, side, fed=None: sum(l["value"] for l in L if l["account"] == acc and l["side"] == side and (fed is None or l["federal"] == fed))
    X = tot("trade", "credit")
    pc, pd = tot("primary", "credit"), tot("primary", "debit")
    sc, sd = tot("secondary", "credit"), tot("secondary", "debit")
    ca = tb + (pc - pd) + (sc - sd)
    sd_all = (tb_sd ** 2 + sum(half(l) ** 2 for l in L if l["account"] != "trade")) ** 0.5
    fed_in = sum(l["value"] for l in L if l["federal"] and l["side"] == "credit")
    fed_out = sum(l["value"] for l in L if l["federal"] and l["side"] == "debit")
    return dict(d=d, a=a, L=L, absorb=absorb, tb=tb, tb_sd=tb_sd, X=X, M=X - tb, pc=pc, pd=pd, sc=sc, sd=sd,
                primary=pc - pd, secondary=sc - sd, ca=ca, lo=ca - sd_all, hi=ca + sd_all, gdp=v("gdp"),
                fed_in=fed_in, fed_out=fed_out, fed_net=fed_in - fed_out, ex_fed=ca - (fed_in - fed_out),
                gains=d["memo"]["apf_realized_gains"]["value"])


def bn(v, sign=False, dec=1):
    return fnum(v, dec, "$", "B", sign=sign)


def current_account_page(tile):
    m = ca_model()
    d, L, a, mm = m["d"], m["L"], m["a"], m["d"]["memo"]
    yr = d["year"]
    pct = lambda v: f"{v / m['gdp'] * 100:.0f}%"
    line = {l["id"]: l for l in L}
    val = lambda k: line[k]["value"]
    rng = lambda l: f"{bn(l['low'])}–{bn(l['high'])}" if l["low"] != l["high"] else "—"
    rows = lambda ls: [(l["label"], bn(l["value"]), rng(l), l["confidence"], l["basis"], l["source"]) for l in ls]
    cols = ["Line", "$ billions", "Range", "Confidence", "How it is estimated", "Source"]
    credits = sorted([l for l in L if l["side"] == "credit"], key=lambda l: -l["value"])
    debits = sorted([l for l in L if l["side"] == "debit"], key=lambda l: -l["value"])
    debits_rows = [("Imports (derived)", m["M"])] + [(l.get("short", l["label"]), l["value"]) for l in debits]
    debits_rows.sort(key=lambda r: -r[1])
    fed = [l for l in L if l["federal"]]
    oil_per10 = mm["oil_barrels_m"] * 10 / 1000
    oil_ca10 = oil_per10 * mm["marginal_state_take"]
    big4 = val("oil") + val("metals") + val("seafood") + val("visitors")

    stats = [
        stat(f"Current account, {yr}", f"Estimate · {pct(m['ca'])} of GDP", value=bn(m["ca"], sign=True)),
        stat("Likely range", "Combined uncertainty of every line", value=f"{bn(m['lo'], sign=True, dec=0)} to {bn(m['hi'], sign=True, dec=0)}"),
        stat("Without federal flows", "Balance if federal money in and out is removed", value=bn(m["ex_fed"], sign=True)),
        stat("Net federal flows", f"In {bn(m['fed_in'])}, out {bn(m['fed_out'])} · {pct(m['fed_net'])} of GDP", value=bn(m["fed_net"], sign=True)),
        stat("Goods and services", "Exports less imports", value=bn(m["tb"], sign=True)),
        stat("Primary income", "Wages, profits, interest, dividends", value=bn(m["primary"], sign=True)),
        stat("Transfers", "Grants, benefits and taxes", value=bn(m["secondary"], sign=True)),
    ]

    glance = hbar("The four balances", [
        ("Goods and services", m["tb"]), ("Primary income", m["primary"]), ("Transfers", m["secondary"]),
        ("Current account", m["ca"]), ("Without federal flows", m["ex_fed"])],
        f"Billions of dollars, {yr}. Blue is money coming in on balance, orange is money going out.", dec=1, prefix="$", suffix="B", highlight=r"^Current account$")

    body = [
        text("The short version", [
            f"In {yr}, Alaskans earned more from the rest of the world than they paid out: a surplus of roughly {bn(m['ca'])}, about {pct(m['ca'])} of the state's GDP. The likely range runs from {bn(m['lo'], dec=0)} to {bn(m['hi'], dec=0)}, because several lines have to be estimated.",
            f"The surplus does not come from trade. Alaska sells about {bn(m['X'], dec=0)} of goods and services to the outside each year and buys about {bn(m['M'], dec=0)}, so trade roughly balances ({bn(m['tb'], sign=True)}). Income going out to nonresident workers, out-of-state owners and lenders ({bn(m['pd'])}) also roughly cancels investment income coming in ({bn(m['pc'])}).",
            f"What tips the balance is the federal government. Counting its payroll, purchases, grants and benefits against the federal taxes Alaskans pay, about {bn(m['fed_net'])} more arrives from Washington than leaves for it. Without that, Alaska would run a deficit of about {bn(abs(m['ex_fed']))}.",
        ]),
        section("The account at a glance", "A current account adds up every payment between a place and the rest of the world that is not a loan, an investment or a sale of assets. Countries publish one; states do not, so this is an estimate.",
                glance,
                table("Summary", ["", f"$ billions, {yr}", "Share of GDP"], [
                    ("Exports of goods and services", bn(m["X"]), pct(m["X"])),
                    ("Imports of goods and services (derived)", bn(-m["M"]), pct(m["M"])),
                    ("Goods and services balance", bn(m["tb"], sign=True), pct(m["tb"])),
                    ("Primary income received", bn(m["pc"]), pct(m["pc"])),
                    ("Primary income paid", bn(-m["pd"]), pct(m["pd"])),
                    ("Primary income balance", bn(m["primary"], sign=True), pct(m["primary"])),
                    ("Transfers received", bn(m["sc"]), pct(m["sc"])),
                    ("Transfers paid", bn(-m["sd"]), pct(m["sd"])),
                    ("Transfers balance", bn(m["secondary"], sign=True), pct(m["secondary"])),
                    ("Current account balance", bn(m["ca"], sign=True), pct(m["ca"])),
                    ("Likely range", f"{bn(m['lo'], sign=True)} to {bn(m['hi'], sign=True)}", ""),
                ], f"GDP {bn(m['gdp'])} (BEA). Shares are of GDP. Imports are worked out as exports minus the goods-and-services balance; see How the estimate is built.", right=(1, 2))),
        section("Money coming in", f"Every payment from outside Alaska to Alaskans, largest first. Federal flows total {bn(m['fed_in'])}, more than crude oil ({bn(val('oil'))}).",
                hbar("Money coming in", [(l.get("short", l["label"]), l["value"]) for l in credits], f"Billions of dollars, {yr}. Federal lines in red.", dec=1, prefix="$", suffix="B", highlight=r"^(Federal)", lw=290),
                table("Each incoming line", cols, rows(credits), "Confidence: High means taken directly from an official figure; Medium means an official figure adjusted or combined with others; Low means an estimate built from partial information.", right=(1,))),
        section("Money going out", f"Every payment from Alaskans to the outside. Imports are by far the largest, at about {bn(m['M'], dec=0)}.",
                hbar("Money going out", debits_rows, f"Billions of dollars, {yr}. Imports are derived, not measured.", dec=1, prefix="$", suffix="B", highlight=r"^(Federal)", lw=290),
                table("Each outgoing line", cols, [("Imports of goods and services (derived)", bn(m["M"]), f"{bn(m['M'] - m['tb_sd'])}–{bn(m['M'] + m['tb_sd'])}", "Low",
                                                   "Exports minus the goods-and-services balance. The balance itself is GDP minus household consumption, private investment and state and local government spending. Includes freight, tanker shipping, fuel brought in for air cargo, and what Alaskans spend while traveling.", "Derived; BEA")] + rows(debits), "", right=(1,))),
        section("The federal government's part", f"Federal money arrives four ways and leaves one way. On balance about {bn(m['fed_net'])} a year comes in, roughly {pct(m['fed_net'])} of GDP.",
                table("Federal flows", ["Flow", "Direction", "$ billions", "Counted as"],
                      [(l["label"], "In" if l["side"] == "credit" else "Out", bn(l["value"]),
                        {"trade": "Export of goods and services", "secondary": "Transfer"}.get(l["account"], "Income")) for l in fed]
                      + [("Net federal flows", "", bn(m["fed_net"], sign=True), "")], "", right=(2,)),
                text("Why federal payroll and purchases count as exports", [
                    "A national current account treats a foreign embassy's spending like any other export: the customer sits outside the country. The same logic applies here. When the Defense Department pays a soldier at JBER or a contractor building a hangar at Eielson, the customer is in Washington, so the payment is a sale of services to the outside.",
                    "Grants and benefits are different. The federal government gets nothing in return, so they are counted as transfers, like foreign aid or remittances. Federal income and payroll taxes paid by Alaskans are the matching transfers going out.",
                    f"For comparison, a 2026 ISER presentation put federal spending in Alaska at just under $20 billion in 2023, or about $18 billion without temporary pandemic money. This page's gross figure for {yr}, {bn(m['fed_in'])}, is in that range. An earlier ISER estimate of $13 billion to $14 billion a year counted fewer streams."])),
        section("Oil's part", f"Crude oil is the largest single export, but much of its value leaves again as profit for out-of-state owners.",
                table("Where a year of North Slope oil goes", ["Piece", "$ billions", "Stays in Alaska?"], [
                    ("Crude oil sold outside Alaska", bn(val("oil")), "Comes in"),
                    ("State petroleum revenue (FY2024)", bn(mm["state_petroleum_revenue_fy24"]), "Yes"),
                    ("Local oil and gas property taxes (FY2024)", bn(mm["municipal_oil_property_tax_fy24"]), "Yes"),
                    ("Producers' profit before federal income tax", bn(val("oil_profits")), "No"),
                    ("Operating, drilling and transport costs, depreciation", "the rest", "Partly: Alaska wages and suppliers stay, imported equipment and nonresident workers do not"),
                ], "State revenue includes royalties, production tax, property tax and corporate income tax, restricted and unrestricted. Sources: DOR, AOGA.", right=(1,)),
                text("How oil prices move the balance", [
                    f"North Slope fields produce about {mm['oil_barrels_m']:.0f} million barrels a year, so every $10 change in the price changes the value of oil exports by about {bn(oil_per10)}.",
                    f"Most of that change ends up with the producers, whose owners are outside Alaska, so it leaves again as profit. What stays is mainly the state's share. At recent prices, royalties and production tax take roughly {mm['marginal_state_take'] * 100:.0f}% of an extra dollar, so a $10 rise in the price improves Alaska's current account by only about {bn(oil_ca10)}. That share is an approximation; the production tax's sliding scale makes it shift with price.",
                    "This is why oil price swings shake the state budget more than they shake the current account."])),
        section("Investment income: the Permanent Fund and household savings", "Alaskans own large savings invested outside the state, publicly through the Permanent Fund and privately through retirement accounts and pensions.",
                table("Permanent Fund income", ["", "FY2024", "FY2025"], [
                    ("Interest, dividends and real estate income", bn(mm["apf_cash_fy24"], dec=2), bn(mm["apf_cash_fy25"], dec=2)),
                    ("Statutory net income (adds realized gains)", bn(mm["apf_sni_fy24"], dec=2), bn(mm["apf_sni_fy25"], dec=2)),
                ], "State fiscal years ending June 30. Source: APFC 2025 Annual Report.", right=(1, 2)),
                text("Which Permanent Fund number belongs in the account", [
                    f"National accounts count interest, dividends and rent as income, and leave out capital gains, which are treated as a change in the value of assets. Following that rule, this page counts {bn(val('apf'), dec=2)} of Permanent Fund income for {yr}.",
                    f"The Legislature budgets from a broader measure. Adding the Fund's realized gains, about {bn(m['gains'])} for {yr}, would raise the current account to about {bn(m['ca'] + m['gains'], sign=True)}.",
                    f"The dividend is not in the account at all. The {yr} dividend and energy relief payment, about {bn(mm['pfd_2024'], dec=2)}, moved money from one Alaska account to Alaskans, so it is neither income from outside nor a payment to it.",
                    f"Household investment income is the larger and less certain piece. BEA counts {bn(mm['bea_dir'])} of dividends, interest and rent received by Alaskans, including returns credited through pension funds such as the state retirement systems. This page assumes about 70% comes from outside Alaska. Each 10 percentage points on that assumption moves the balance by about {bn(mm['bea_dir'] * 0.1)}."])),
        section("How the estimate is built", "",
                text("The goods-and-services balance", [
                    "No agency counts what Alaska buys from the Lower 48, because there are no customs records between states. Instead, the balance is worked out from the national accounts identity: what a place produces, minus what it spends, equals what it sells to the outside on balance.",
                    f"Alaska's GDP in {yr} was {bn(m['gdp'])}. Alaskans spent {bn(a['pce']['value'])} on household consumption (BEA), about {bn(a['investment']['value'])} on private investment and about {bn(a['state_local']['value'])} through state and local government, for a total of {bn(m['absorb'])}. The difference, {bn(m['tb'], sign=True)}, is the goods-and-services balance. Federal spending in Alaska is left out of the spending total because it is counted as an export.",
                    "The export lines are measured directly where possible. Imports are then whatever is needed to produce the balance. The split between goods and services is not reliable, so the page shows them together."]),
                text("Three choices that had to be made", [
                    "Federal payroll and purchases count as exports of services, for the reasons in the federal section.",
                    "Seafood is valued at first wholesale, the price processors get when the fish leaves their hands. Ex-vessel value, what fishermen are paid, would understate what Alaska sells.",
                    "Out-of-state owners' profits are counted after state taxes and royalties but before federal income tax. All of that profit leaves Alaska, whoever ends up with it."]),
                text("What is not in the estimate", [
                    "Capital gains and losses on investments, realized or not.",
                    "Pension payments to retirees who have left Alaska, and to those who have moved in. BEA's investment income figure partly captures these.",
                    "Loans, new investment and asset sales. Those belong to the financial account, which shows how a surplus or deficit is financed. Oil companies' spending on Willow and Pikka, for example, is an investment flowing in, not part of the current account; only its future profits will be."])),
        section("Cross-checks", "Places where two independent sources can be compared.",
                table("Cross-checks", ["Item", "This page", "Other source", "What it shows"], [
                    ("Nonresident earnings", bn(val("nonres_wages")), f"{bn(mm['bea_residence_adjustment'], sign=True, dec=2)} (BEA residence adjustment)",
                     "BEA's adjustment relies on commuting surveys that miss most seasonal workers, so it badly understates money leaving with nonresidents. The state labor department's payroll-based count is used here."),
                    ("Oil producers' profits", bn(val("oil_profits")), "About $2.9B (DOR barrel economics, FY2024); about $3.5B (scaled from ConocoPhillips)", "Two methods within $0.6B of each other."),
                    ("Federal benefits", bn(val("fed_payments")), "About $6.4B of federally funded transfers in BEA's personal income for 2024", "Close agreement."),
                    ("Federal money coming in", bn(m["fed_in"]), "Just under $20B in 2023; about $18B without temporary pandemic money (ISER, 2026)", "Close agreement."),
                    ("Imports", bn(m["M"]), "Roughly $32B by adding up likely imported shares of consumption, oil and mining inputs, construction and government purchases", "The derived figure is plausible."),
                ], "")),
        plan([f"Extend the estimate back to 2019 and forward to 2025, using the same lines, so the balance can be followed over time.",
              "Show a three-year average alongside each year to smooth swings in oil prices.",
              "Replace estimated lines with measured ones where data allow: BEA's split of dividends, interest and rent, mortgage servicing data for interest paid out, and at-sea versus shore-based seafood value.",
              "Update once a year, after BEA's September release of state GDP, personal income and consumption."], "What comes next"),
    ]
    notes = [
        f"All figures are for calendar {yr} unless marked. Where a source uses the state fiscal year (July to June) or the federal fiscal year (October to September), the closest year or an average of two years is used, as described in each line.",
        "The likely range combines each line's low-to-high range as if the errors were independent, which is a standard way to add up uncertain pieces. It is a guide, not a statistical confidence interval.",
        "Seafood value includes fish processed at sea by Seattle-based catcher-processors, which BEA does not count in Alaska's GDP. Because imports are derived, this raises both exports and imports by the same amount and does not change the balance.",
        "Crude oil exports count all North Slope production, including oil refined in Alaska. Refined products used in Alaska therefore show up in derived imports, and the balance is unaffected.",
        "Spending in Alaska by nonresident workers is an export, like visitor spending, but is not measured separately. It is captured in the goods-and-services balance through the GDP identity.",
        "No official statistic measures a state's current account. These are this site's estimates and will be revised as better data are found.",
    ]
    sources = [
        src("BEA via FRED, Alaska GDP (AKNGSP)", "https://fred.stlouisfed.org/series/AKNGSP"),
        src("BEA via FRED, Alaska personal consumption expenditures (AKPCE)", "https://fred.stlouisfed.org/data/AKPCE"),
        src("BEA via FRED, Alaska dividends, interest and rent (AKODIV)", "https://fred.stlouisfed.org/series/AKODIV"),
        src("BEA via FRED, Alaska residence adjustment (AKEADJ)", "https://fred.stlouisfed.org/series/AKEADJ"),
        src("BEA SAINC35, personal current transfer receipts, via ArcticStat", "https://www.arcticstat.org/doc/document/2023-06-07-07.pdf"),
        src("Alaska DOR, Revenue Sources Book, Fall 2024", "https://tax.alaska.gov/programs/programs/reports/RSB.aspx?Type=Fall&Year=2024"),
        src("Alaska DOR, Spring 2025 Revenue Forecast", "https://dor.alaska.gov/docs/default-source/homepage-documents/revenue-spring-2025-forecast.pdf?sfvrsn=c1a81c75_1"),
        src("ConocoPhillips, 2024 Form 10-K", "https://www.sec.gov/Archives/edgar/data/1163165/000116316525000012/cop-20241231.htm"),
        src("ConocoPhillips Alaska, 2024 earnings review", "https://alaska.conocophillips.com/newsroom/story/2024-conocophillips-alaska-earnings-review/"),
        src("AOGA, Economic Impacts of the Oil and Gas Industry in Alaska (2025)", "https://www.aoga.org/wp-content/uploads/2026/02/AOGA-Economic-Impact-Report-2025-Final-Report.pdf"),
        src("ASMI, Economic Value of Alaska's Seafood Industry (2026)", "https://www.alaskaseafood.org/wp-content/uploads/2026-Economic-Value-of-AK-Seafood-Industry-2023-2024-data-final.pdf"),
        src("DGGS, Alaska's Mineral Industry", "https://dggs.alaska.gov/pubs/minerals"),
        src("ATIA, FY2024-25 Marketing Plan (visitor spending)", "https://www.alaskatia.org/sites/default/files/2024-09/AKFY24-25_Marketing%20Plan%20Final%20Optimized.pdf"),
        src("AIAS 2024 Annual Report", "https://dot.alaska.gov/aias/assets/2024-AIAS-Annual-Report.pdf"),
        src("Alaska Beacon via Alaska's News Source, nonresident workers in 2024", "https://www.alaskasnewssource.com/2026/02/06/almost-one-four-alaska-workers-doesnt-live-state-new-report-concludes/"),
        src("Wrangell Sentinel, nonresident fishermen's share of earnings", "https://www.wrangellsentinel.com/stories/nonresidents-held-almost-23-of-alaska-jobs-in-2024-second-highest-since-1992,50172"),
        src("APFC, 2025 Annual Report", "https://fliphtml5.com/weyac/yojf/APFC_2025_Annual_Report_(old)/"),
        src("Alaska DOR, 2024 Permanent Fund Dividend Annual Report", "https://dor.alaska.gov/docs/permanentfunddividendlibraries/annual-reports/2024-pfd-annual-report.pdf?sfvrsn=214f2751_1"),
        src("Commonwealth North, Half of Alaska's Recent Growth Came From Washington (ISER)", "https://www.commonwealthnorth.org/half-of-alaskas-recent-growth-came-from-washington/"),
        src("Commonwealth North, Federal Spending Shifts Reshape Alaska's Economic Outlook", "https://www.commonwealthnorth.org/federal-spending-shifts-reshape-alaskas-economic-outlook/"),
        src("DOLWD, Alaska Economic Trends, May 2025 (federal employment)", "https://live.laborstats.alaska.gov/sites/default/files/trends/may25art1_0.pdf"),
        src("IRS Data Book 2025, Table 5", "https://www.irs.gov/pub/irs-pdf/p55b.pdf"),
        src("IRS Data Book 2023, Table 5", "https://www.irs.gov/pub/irs-prior/p55b--2024.pdf"),
        src("AGC of Alaska, 2024 Construction Spending Forecast", "https://rdc.memberclicks.net/assets/Breakfasts/2024/Info%20Sheet%20%202024%20Construction%20Spending%20Forecast.pdf"),
        src("Alaska Business, 2025 Top 49ers", "https://digital.akbizmag.com/issue/october-2025/2025-top-49ers/"),
    ]
    return dict(slug="current-account", group="Macro", title="Current account", row="Macro", status="static",
        lead=f"Alaska is a small open economy: most of what it consumes is shipped in and most of what it produces is sold outside the state. A current account adds up what Alaskans earn from the rest of the world and what they pay out, using the framework countries use for their balance of payments. No official statistic does this for a state, so the balance here is an estimate for {yr}, built line by line, with a range and a confidence grade for each line.",
        stats=stats, body=body, notes=notes, sources=sources,
        tile=tile(value=bn(m["ca"], sign=True), unit=f"annual balance, {yr} estimate"))


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
        tiles = "".join(tile_html(p) for p in P if p.get("row") == row and p.get("front", True))
        rows.append(f'<div class="row"><div class="row-head"><h3>{E(row)}</h3><span>{E(intro)}</span></div><div class="tiles">{tiles}</div></div>')
    return ('<section id="micro" aria-labelledby="h-micro">\n  <div class="sec-head"><h2 id="h-micro">Micro</h2>'
            '<p>The prices, volumes and decisions that sit underneath the headline numbers.</p></div>\n'
            '  <div class="matrix">\n' + "\n".join(rows) + "\n  </div>\n</section>")


def macro_html():
    gdp_main = {"file": "gdp", "series": "AKRQGSP", "calc": "qgrowth", "dec": 1, "suffix": "%", "sign": True}
    gdp_chart = chart("Real GDP, Alaska", "line", [{"file": "gdp", "id": "AKRGSP", "label": "Alaska", "scale": 0.001}], "Billions of chained 2017 dollars. Source: BEA.", dec=0, prefix="$", suffix="B", zero=False, height=200)
    ca = ca_model()
    ca_chart = hbar("Current account", [("Goods and services", ca["tb"]), ("Primary income", ca["primary"]), ("Transfers", ca["secondary"]), ("Current account", ca["ca"]), ("Without federal flows", ca["ex_fed"])],
                    f"Billions of dollars, {ca['d']['year']}. Estimate.", dec=1, prefix="$", suffix="B", highlight=r"^Current account$")
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
      <div class="headline"><b>{bn(ca["ca"], sign=True)}</b><span>Annual balance, {ca["d"]["year"]} estimate · likely range {bn(ca["lo"], sign=True, dec=0)} to {bn(ca["hi"], sign=True, dec=0)}</span></div>
      {ca_chart}
      <div class="sub">
        <div class="stat"><b>{bn(ca["tb"], sign=True)}</b><span>Goods &amp; services</span></div>
        <div class="stat"><b>{bn(ca["primary"], sign=True)}</b><span>Primary income</span></div>
        <div class="stat"><b>{bn(ca["secondary"], sign=True)}</b><span>Transfers</span></div>
        <div class="stat"><b>{bn(ca["ex_fed"], sign=True)}</b><span>Without federal flows</span></div>
      </div>
      <a class="more" href="/current-account/">Current account page →</a>
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
