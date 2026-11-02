"""Draft "The read" for each dashboard with Claude, from that page's own numbers.

Runs in the refresh job after fetch_data.py. Needs the ANTHROPIC_API_KEY
repository secret; without it this script does nothing and exits cleanly.

For each dashboard page:
  1. Gather what the page shows: title, as-of line, indicator tiles, section
     intros, captions, tables and data notes (from site/<slug>/index.html,
     leaving out the charts' drawing code and the current summary), plus the
     live series in site/data/<slug>.json (with changes worked out here, so
     the model never has to do arithmetic) and the hand-kept numbers in
     site/data/manual/<slug>.json.
  2. Skip the page if none of that changed since its last summary.
  3. Ask Claude for a short paragraph in the site's voice.
  4. Check every number in the draft against the material. One retry with the
     offending numbers named; if it still fails, the old summary stays up.
  5. Save site/data/summaries.json, which the pages read.

Usage:
    python scripts/write_summaries.py            # every page that changed
    python scripts/write_summaries.py housing    # just one
    python scripts/write_summaries.py --force    # redo all, even unchanged
    python scripts/write_summaries.py --dry-run housing   # print the prompt, no API call
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"
OUT = DATA / "summaries.json"

MODEL = os.environ.get("SUMMARY_MODEL") or "claude-opus-5-5"
API = "https://api.anthropic.com/v1/messages"
PROMPT_VERSION = "1"  # bump to force every page to redraft after changing the prompt

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

SYSTEM = """You write "The read", the short summary at the top of each dashboard on Two Cents for Alaska, a monthly, information-first site about Alaska's economy modeled on Jason Furman's Econvitals.

Write one paragraph of 3 to 5 sentences, under 110 words, from the material provided.

Voice and content:
- Plain, neutral and factual, for a general Alaska reader. No policy advice, opinions, predictions or loaded words such as "alarming" or "impressive".
- Lead with the most important or most recent development, then give context: change from a year earlier, comparison with the U.S., or the longer history the page shows.
- Name the period for each figure ("in September", "in 2025", "in fiscal 2025").
- Use only facts in the material. Do not add background knowledge.

Numbers:
- Use only numbers that appear in the material, either exactly or rounded (54.3% may become 54%). Never compute new ones: no differences, ratios, averages or percentages that are not already given.
- The "Live data" section is the newest. Where it covers the same measure as an indicator tile for an earlier period, use the live figure and its period.
- Write numbers the way the material does: thousands with commas, percents with %, dollars with $.

Return only the paragraph, with no heading, quotation marks or notes."""


# ---------- page text ----------

class PageText(HTMLParser):
    """Visible text of a dashboard page, minus scripts, charts and the current summary."""
    BLOCK = {"h1", "h2", "h3", "p", "li", "tr", "figcaption", "header", "section", "table", "ul", "footer"}
    SKIP = {"script", "style", "svg", "head", "title", "nav"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.read_depth, self.depth = [], 0, None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        if tag == "div":
            self.depth += 1
            cls = a.get("class", "")
            if "read" in cls.split() and self.read_depth is None:
                self.read_depth = self.depth
            if "tile" in cls.split():
                self.out.append("\n- Tile:")
        if tag == "footer":
            self.skip += 1  # source list: names, not figures
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("h2", "h3"):
            self.out.append("## " if tag == "h2" else "### ")
        if tag in ("td", "th"):
            self.out.append(" | ")
        if tag == "span":
            self.out.append(" | " if self.out and self.out[-1].strip() else " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP or tag == "footer":
            self.skip = max(0, self.skip - 1)
        if tag == "div":
            if self.read_depth == self.depth:
                self.read_depth = -1  # done with the summary block
            self.depth -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip or (self.read_depth is not None and self.read_depth > 0 and self.depth >= self.read_depth):
            return
        self.out.append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r" *\n *", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def page_text(slug):
    p = PageText()
    p.feed((SITE / slug / "index.html").read_text(encoding="utf-8"))
    return p.text()


# ---------- live data facts ----------

def fnum(v, d=None):
    if d is None:
        d = 0 if abs(v) >= 100 or float(v).is_integer() else (1 if abs(v) >= 10 else 2)
    return f"{v:,.{d}f}"


def pct(a, b):
    return (a / b - 1) * 100


def signed(v, d=1):
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):,.{d}f}"


def period(d, freq):
    y, m = d[:4], int(d[5:7])
    if freq == "annual":
        return y
    if freq == "quarterly":
        return f"Q{(m - 1) // 3 + 1} {y}"
    if freq == "weekly":
        return f"{MON[m - 1]} {int(d[8:10])}, {y}"
    return f"{MON[m - 1]} {y}"


def as_count(v, units):
    """Thousands of jobs/people -> a plain count, which is how readers say it."""
    if units.startswith("thousands of"):
        noun = units.split("thousands of", 1)[1].strip()
        return f"{v * 1000:,.0f} {noun}"
    if units.startswith("millions of") and abs(v) >= 1000:
        return f"${v / 1000:,.1f} billion ({units.replace('millions of', '').strip()})"
    return None


def series_facts(sid, s):
    dates, vals, freq, kind, units = s["dates"], s["values"], s.get("freq", ""), s.get("kind", "level"), s.get("units", "")
    by = dict(zip(dates, vals))
    last_d, last_v = dates[-1], vals[-1]
    ints = all(float(v).is_integer() for v in vals)
    lines = [f"* {s['label']} [{sid}; {units}; {freq}]"]

    def show(d, v):
        c = as_count(v, units)
        return f"{period(d, freq)} = {fnum(v)}" + (f" ({c})" if c else "")

    lines.append(f"  Latest: {show(last_d, last_v)}")
    if len(dates) > 1:
        lines.append(f"  Previous: {show(dates[-2], vals[-2])}")

    # same period a year earlier
    if freq == "weekly":
        ago = [d for d in dates if d <= f"{int(last_d[:4]) - 1}{last_d[4:]}"]
        ago_d = ago[-1] if ago else None
    elif freq == "annual":
        ago_d = dates[-2] if len(dates) > 1 else None
    else:
        ago_d = f"{int(last_d[:4]) - 1}{last_d[4:]}"
    if ago_d in by:
        a = by[ago_d]
        if kind in ("rate", "pct"):
            lines.append(f"  A year earlier: {period(ago_d, freq)} = {fnum(a, 2)}; change {signed(last_v - a, 2)} points")
        else:
            ch = last_v - a
            c = as_count(ch, units) if units.startswith("thousands of") else None
            lines.append(f"  A year earlier: {show(ago_d, a)}; change {signed(ch, 0 if ints or abs(ch) >= 100 else 1)}"
                         + (f" ({'+' if ch > 0 else ''}{c})" if c else "") + f", {signed(pct(last_v, a))}%")

    if kind == "index" and freq in ("monthly", "bimonthly"):
        # 12-month inflation for the last few releases
        rel = [(d, pct(v, by[f"{int(d[:4]) - 1}{d[4:]}"])) for d, v in zip(dates, vals) if f"{int(d[:4]) - 1}{d[4:]}" in by][-4:]
        if rel:
            lines.append("  12-month change: " + "; ".join(f"{period(d, freq)} {signed(c)}%" for d, c in rel))
        ann = s.get("annual")
        if ann and len(ann["dates"]) > 1:
            ch = [(ann["dates"][i], pct(ann["values"][i], ann["values"][i - 1])) for i in range(1, len(ann["dates"]))][-7:]
            lines.append("  Annual average change: " + "; ".join(f"{y} {signed(c)}%" for y, c in ch))

    if kind == "flow" and freq == "monthly":
        y, m = last_d[:4], last_d[5:7]
        ytd = sum(v for d, v in zip(dates, vals) if d[:4] == y and d[5:7] <= m)
        py = str(int(y) - 1)
        pytd = sum(v for d, v in zip(dates, vals) if d[:4] == py and d[5:7] <= m)
        if pytd:
            lines.append(f"  Year to date: Jan–{MON[int(m) - 1]} {y} = {fnum(ytd)}; Jan–{MON[int(m) - 1]} {py} = {fnum(pytd)}; change {signed(pct(ytd, pytd))}%")
        years = sorted({d[:4] for d in dates if sum(1 for x in dates if x[:4] == d[:4]) == 12})[-5:]
        if years:
            lines.append("  Full-year totals: " + "; ".join(f"{yy} = {fnum(sum(v for d, v in zip(dates, vals) if d[:4] == yy))}" for yy in years))
        hi = max(range(len(vals)), key=lambda i: vals[i])
        lines.append(f"  Highest month in the data (since {period(dates[0], freq)}): {period(dates[hi], freq)} = {fnum(vals[hi])}")

    if freq == "quarterly" and len(vals) > 1 and kind == "level":
        g = (pow(vals[-1] / vals[-2], 4) - 1) * 100
        lines.append(f"  Growth at an annual rate, latest quarter: {signed(g)}%")

    if freq == "annual" and len(vals) > 5:
        hi = max(range(len(vals)), key=lambda i: vals[i])
        lines.append(f"  Record high: {period(dates[hi], freq)} = {fnum(vals[hi])}"
                     + (f" ({as_count(vals[hi], units)})" if as_count(vals[hi], units) else ""))
        tail = list(zip(dates, vals))[-8:]
        lines.append("  Recent years: " + "; ".join(f"{d[:4]} {fnum(v)}" for d, v in tail))
        if kind == "index":
            chg = [(dates[i][:4], pct(vals[i], vals[i - 1])) for i in range(len(vals) - 7, len(vals))]
            lines.append("  Year-to-year change: " + "; ".join(f"{y} {signed(c)}%" for y, c in chg))
    return "\n".join(lines)


def live_facts(slug):
    path = DATA / f"{slug}.json"
    if not path.exists():
        return "", None
    d = json.loads(path.read_text())
    blocks = [series_facts(sid, s) for sid, s in d["series"].items()]
    latest = max(s["dates"][-1] for s in d["series"].values())
    return f"Source: {d.get('source', '')}\n" + "\n".join(blocks), latest


def manual_facts(slug):
    path = DATA / "manual" / f"{slug}.json"
    if not path.exists():
        return ""
    d = json.loads(path.read_text())
    d.pop("_about", None)
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def material(slug):
    live, latest = live_facts(slug)
    parts = [f"PAGE: twocentsforalaska.org/{slug}/", "", "=== What the page shows ===", page_text(slug)]
    if live:
        parts += ["", "=== Live data (refreshed automatically; newest figures) ===", live]
    man = manual_facts(slug)
    if man:
        parts += ["", "=== Hand-maintained figures behind the page's charts (JSON) ===", man]
    return "\n".join(parts), latest


# ---------- number check ----------

NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def numbers(text):
    out = []
    for m in NUM.finditer(text):
        s = m.group(0).rstrip(",")
        try:
            out.append((s, float(s.replace(",", ""))))
        except ValueError:
            pass
    return out


def check(draft, source):
    """Return the numbers in the draft that don't appear in the source (exactly or rounded)."""
    have = [v for _, v in numbers(source)]
    bad = []
    for s, x in numbers(draft):
        if x <= 12 and x.is_integer():
            continue  # counts, months, quarters, "2-bedroom"
        dec = len(s.split(".")[1]) if "." in s else 0
        ok = any(abs(round(y, dec) - x) < 1e-9 for y in have)
        # Also accept a whole number rounded from a value given with decimals ("54.3%" -> "54%")
        if not ok and dec == 0:
            ok = any(abs(y - x) < 0.5 + 1e-9 and not float(y).is_integer() for y in have)
        if not ok:
            bad.append(s)
    return bad


# ---------- Claude API ----------

def ask(messages, key, tries=4):
    body = json.dumps({"model": MODEL, "max_tokens": 600, "system": SYSTEM, "messages": messages}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read().decode())
            return "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text").strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"Claude API {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"Claude API unreachable: {e}") from e


def draft(slug, mat, key):
    msgs = [{"role": "user", "content": f"Write The read for this page.\n\n{mat}"}]
    text = ask(msgs, key)
    bad = check(text, mat)
    if bad:
        msgs += [{"role": "assistant", "content": text},
                 {"role": "user", "content": "These numbers in your paragraph are not in the material: "
                  + ", ".join(bad) + ". Rewrite the paragraph using only numbers that appear in the material."}]
        text = ask(msgs, key)
        bad = check(text, mat)
    return text, bad


def pages():
    return sorted(p.parent.name for p in SITE.glob("*/index.html") if p.parent.name not in ("data", "js"))


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv
    wanted = [a for a in argv if not a.startswith("--")] or pages()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key and not dry:
        print("::notice::No ANTHROPIC_API_KEY secret set, so AI summaries were skipped.")
        return
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    new, errors = dict(old), []
    for slug in wanted:
        mat, latest = material(slug)
        fp = hashlib.sha256(f"{PROMPT_VERSION}|{MODEL}|{mat}".encode()).hexdigest()[:16]
        if dry:
            print(f"===== {slug} ({len(mat):,} chars)\n{mat}\n")
            continue
        if not force and old.get(slug, {}).get("fingerprint") == fp:
            print(f"{slug}: unchanged, kept")
            continue
        try:
            text, bad = draft(slug, mat, key)
        except Exception as e:
            print(f"::error::{slug}: {e}")
            errors.append(slug)
            continue
        if bad or not text:
            print(f"::warning::{slug}: draft used numbers not on the page ({', '.join(bad)}); kept the previous summary")
            continue
        new[slug] = {"text": text, "generated": date.today().isoformat(), "model": MODEL,
                     "data_through": latest, "fingerprint": fp}
        print(f"{slug}: new summary\n  {text}")
    if not dry and new != old:
        OUT.write_text(json.dumps(dict(sorted(new.items())), indent=1, ensure_ascii=False) + "\n")
    if errors:
        sys.exit(f"Summaries failed: {', '.join(errors)}")


if __name__ == "__main__":
    main(sys.argv[1:])
