# Two Cents for Alaska

Source for **twocentsforalaska.org** — a monthly, nonpartisan read on Alaska's economy.

## How it fits together

```
site/                   ← everything the public sees (Cloudflare Pages serves this folder)
  index.html            ← front page (monthly issue)
  gdp/index.html        ← one folder per dashboard → twocentsforalaska.org/gdp/
  cost-of-living/ …     ← 12 dashboards total
  data/gdp.json         ← numbers the charts read; rewritten by the refresh job
scripts/fetch_fred.py   ← pulls series from FRED and writes site/data/*.json
.github/workflows/
  refresh-data.yml      ← runs the script on the 2nd and 16th, commits new data
```

The loop: **GitHub Action runs script → new JSON committed → Cloudflare sees the push → site redeploys.** No servers, no cost.

Right now **GDP is the only dashboard wired to live data** (both charts). The other 11 pages are the November draft with numbers written into the page. Wire them one at a time using GDP as the pattern.

## One-time setup (about 20 minutes)

### 1. GitHub
1. Sign in at github.com and click **New repository**. Name: `twocentsforalaska`. Public is fine (the data is all public). Don't add a README.
2. On the empty repo page, click **uploading an existing file** and drag in the *contents* of this folder (including the hidden `.github` folder — on a Mac press ⌘⇧. in Finder to show it). Commit.
   - Or from a terminal in this folder:
     ```
     git init && git add . && git commit -m "Initial site"
     git branch -M main
     git remote add origin https://github.com/YOUR-USERNAME/twocentsforalaska.git
     git push -u origin main
     ```
3. Repo **Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → Save. (Lets the refresh job commit data.)

### 2. Cloudflare Pages
1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**. Authorize GitHub and pick `twocentsforalaska`.
2. Build settings:
   - Framework preset: **None**
   - Build command: *(leave blank)*
   - Build output directory: **`site`**
3. Save and Deploy. You'll get a `*.pages.dev` URL in about a minute — check it.
4. In the Pages project → **Custom domains → Set up a custom domain** → `twocentsforalaska.org`. Because the domain is already in your Cloudflare account, it adds the DNS record for you. Add `www.twocentsforalaska.org` too.

### 3. Test the data job
GitHub repo → **Actions → Refresh data → Run workflow**. In a minute or two you should see a green check and a "Data refresh" commit replacing the seeded GDP numbers with the full FRED history. Cloudflare redeploys automatically.

## Day-to-day

- **Edit a page:** change the HTML in `site/<topic>/index.html`, commit, push. Live in ~1 minute.
- **Preview locally:** `cd site && python3 -m http.server` then open http://localhost:8000. (Opening files by double-clicking works too, but charts fall back to built-in numbers.)
- **Monthly issue:** update the front page lead story, briefs, "Latest" column and calendar in `site/index.html`.

## Wiring the next dashboard

1. Add its series to `DASHBOARDS` in `scripts/fetch_fred.py` (two are already stubbed: business formation and housing permits).
2. Run `python3 scripts/fetch_fred.py business-formation` to create `site/data/business-formation.json`.
3. In that page's `<script>`, replace the hard-coded arrays with a `fetch('/data/business-formation.json')`, keeping the arrays as the fallback — copy the pattern at the bottom of `site/gdp/index.html`.

Sources that aren't on FRED (state DOLWD, DEED, DCRA fuel survey, EIA) get their own script in `scripts/` later; same idea, same `site/data/` output.

## Still hand-written on every page
Indicator tiles, "The read" summaries and the front-page numbers. Next step after a few charts are live: generate tiles from the JSON, then have the summaries drafted from it.
