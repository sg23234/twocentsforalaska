# Two Cents for Alaska

Source for **twocentsforalaska.org**, a monthly read on Alaska's economy.

## How it fits together

```
site/                        ← everything the public sees (Cloudflare Pages serves this folder)
  index.html                 ← front page (monthly issue)
  gdp/index.html …           ← one folder per dashboard → twocentsforalaska.org/gdp/ (12 total)
  js/tc.js                   ← shared page code: loads data, draws simple charts, shows the AI summary
  data/<topic>.json          ← live series, written by the refresh job. Don't edit by hand.
  data/manual/<topic>.json   ← numbers from reports, surveys and budgets. Edit these by hand.
  data/summaries.json        ← AI-drafted "The read" for each page, written by the refresh job
  data/status.json           ← what each live source returned on the last run, and any problems
scripts/
  fetch_data.py              ← pulls live series (FRED, BLS, Alaska DOLWD) into site/data/
  write_summaries.py         ← drafts each page's summary with Claude and checks its numbers
.github/workflows/
  refresh-data.yml           ← runs both scripts on the 2nd and 16th, and whenever scripts,
                               manual data or pages change; commits the results
```

The loop: **GitHub Action runs the scripts → new JSON committed → Cloudflare sees the push → site redeploys.**

## Where each page's numbers come from

| Page | Live (updates itself) | Hand-kept in `data/manual/` |
|---|---|---|
| GDP | BEA via FRED, all charts | — |
| Cost of living | Urban Alaska CPI by category (BLS API) | Annual inflation (official annual averages) |
| Housing | Building permits, mortgage rate (FRED) | Anchorage prices and vacancy, rents by area |
| Business formation | Business applications (Census via FRED) | Jobs at openings and closings (BLS BED) |
| Population | Census population since 1970 (FRED) | Components of change, boroughs |
| Productivity | BLS state productivity, output, hours (FRED) | — (comparison tables are in the page) |
| Key sectors | Payroll jobs by industry (Alaska DOLWD) | Visitors, air cargo |
| Spending | Public and private payrolls (DOLWD) | State budget (UGF) and scale charts |
| State capacity | — | All charts, incl. the capital-asset running total |
| Energy, Connectivity | — | All charts |
| Education | — (no charts) | — |

Payroll jobs come from DOLWD's own CSV, not FRED: for recent months the federal (BLS) numbers on FRED differ from DOLWD's monthly estimates, and DOLWD's are the ones Alaska news reports.

Indicator tiles, section intros and the front page are still written in the HTML. Labels that name the latest month (as-of lines, table headers, a few intros) update with the data.

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
GitHub repo → **Actions → Refresh data → Run workflow**. In a minute or two you should see a green check and a "Data refresh" commit if anything changed. Cloudflare redeploys automatically.


### 4. AI summaries (optional, about 5 minutes)
The refresh job can redraft each page's "The read" paragraph with Claude whenever that page's numbers change. Until you add a key, it skips this step and the hand-written paragraphs stay up.
1. In the Claude Console, add a payment method (Billing) and create an API key at **platform.claude.com/settings/keys**. Copy it.
2. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. Name: `ANTHROPIC_API_KEY`. Paste the key. Save.
3. **Actions → Refresh data → Run workflow.** Each page gets a new paragraph in `site/data/summaries.json`, and the page shows it with a line saying it was drafted by Claude.

How it stays honest: the script sends Claude only what the page shows (tiles, captions, tables, notes) plus the live and hand-kept data, with changes already worked out. Every number in the draft must appear in that material, exactly or rounded; if one doesn't, Claude gets one retry, and if it still fails the previous paragraph stays up. A page is only redrafted when its material changed, so a typical run costs a few cents (default model `claude-opus-5-5`; set a repository *variable* named `SUMMARY_MODEL` to use another).

To preview what Claude would be sent for a page, without calling it: `python3 scripts/write_summaries.py --dry-run housing`.

### 5. BLS key (optional)
The CPI detail comes from the BLS API, which works without a key but allows only 25 requests a day per network, shared with everyone on GitHub's servers. If `status.json` ever shows a BLS limit message, register for a free key at data.bls.gov/registrationEngine and add it as a secret named `BLS_API_KEY`. A failed BLS fetch keeps the previous data and only fails the run once that data is 75 days old.

## Day-to-day

- **Update a hand-kept number:** edit `site/data/manual/<topic>.json` on GitHub (the pencil icon works fine from an iPad), commit. The chart redraws and the summary is redrafted within a couple of minutes. Each file says where its numbers come from and when they next update.
- **Edit a page:** change the HTML in `site/<topic>/index.html`, commit. Live in about a minute.
- **Check the data:** `site/data/status.json` lists the latest date for every live series and any problems from the last run. A failed run also shows a red X on the Actions tab, and GitHub emails you.
- **Preview locally:** `cd site && python3 -m http.server`, then open http://localhost:8000. (Opening files by double-clicking works too, but charts fall back to built-in snapshots.)
- **Monthly issue:** update the front page lead story, briefs, "Latest" column and calendar in `site/index.html`.

## Adding a live series

1. Add it to `DASHBOARDS` in `scripts/fetch_data.py` (FRED ID, BLS ID, or DOLWD industry name). Mark it `optional=True` if you're not sure the ID exists; a missing optional series only warns.
2. Push. The workflow runs on script changes and writes `site/data/<topic>.json`.
3. In that page's `<script>`, read it from `TC.load()` (see any dashboard for the pattern) and keep a snapshot as the fallback.

## Not done yet
- Indicator tiles and section intros are still hand-written, so between your edits they can show an earlier month than the charts below them. The AI summary uses the newest figures and names their month.
- The front page doesn't read the data files yet.
