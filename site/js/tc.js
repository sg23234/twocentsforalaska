/* Two Cents for Alaska: shared helpers for every dashboard page.
 *
 * - TC.load(slug)    fetches /data/<slug>.json (written by the refresh job) and
 *                    /data/manual/<slug>.json (hand-maintained). Missing files
 *                    come back as null, so pages fall back to built-in numbers.
 * - TC.charts(m)     draws every <svg data-chart="name"> from manual.charts.
 * - TC.fillLatest(a) fills <span data-latest="SERIES_ID"> with that series' latest date.
 * - The AI summary from /data/summaries.json replaces "The read" when one exists.
 */
(function () {
  const TC = (window.TC = {});
  const me = document.currentScript;
  TC.page = (me && me.dataset.page) || location.pathname.split('/').filter(Boolean)[0] || 'home';

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  TC.MON = MON;
  TC.month = d => MON[+d.slice(5, 7) - 1] + ' ' + d.slice(0, 4);
  TC.mon = d => MON[+d.slice(5, 7) - 1];
  TC.quarter = d => 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1) + ' ' + d.slice(0, 4);
  TC.year = d => d.slice(0, 4);
  TC.esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  TC.fmt = (v, d = 0) => v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  TC.signed = (v, d = 0) => (v > 0 ? '+' : v < 0 ? '−' : '') + TC.fmt(Math.abs(v), d);

  TC.get = url => fetch(url, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(r.status + ' ' + url); return r.json(); });
  TC.load = (slug = TC.page, { auto = true, manual = true } = {}) => Promise.all([
    auto ? TC.get(`/data/${slug}.json`).catch(() => null) : null,
    manual ? TC.get(`/data/manual/${slug}.json`).catch(() => null) : null,
  ]).then(([a, m]) => ({ auto: a, manual: m }));

  /** Series helpers: {dates, values} -> lookups */
  TC.byDate = s => new Map(s.dates.map((d, i) => [d, s.values[i]]));
  TC.last = s => ({ date: s.dates[s.dates.length - 1], value: s.values[s.values.length - 1] });
  TC.yearAgo = d => (+d.slice(0, 4) - 1) + d.slice(4);

  TC.fillLatest = auto => {
    if (!auto) return;
    document.querySelectorAll('[data-latest]').forEach(el => {
      const s = auto.series[el.dataset.latest];
      if (!s) return;
      const f = { month: TC.month, quarter: TC.quarter, year: TC.year }[el.dataset.fmt || 'month'] || TC.month;
      el.textContent = f(TC.last(s).date);
    });
  };

  /* ---------- Generic charts for hand-maintained numbers ---------- */
  const col = c => (c && !c.startsWith('var(') && !c.startsWith('#') ? `var(--${c})` : c || 'var(--accent)');
  const fmtWith = (f = {}) => v => (f.prefix || '') + TC.fmt(v, f.decimals || 0) + (f.suffix || '');

  // Horizontal bars, one row per item: {label, value, color, text}
  TC.hbar = (svg, o) => {
    const W = 640, L = o.label_width || 200, R = 70, rows = o.rows, T = 6, RH = 34;
    const max = o.max || Math.max(...rows.map(r => r.value)) * 1.15, n = o.ticks || 4;
    const H = T + rows.length * RH + 24, X = v => L + (v / max) * (W - L - R), f = fmtWith(o.format), tf = fmtWith({ ...o.format, decimals: o.tick_decimals || 0 });
    let s = '';
    for (let i = 0; i <= n; i++) {
      const t = (max * i) / n;
      s += `<line class="grid" x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="${T}" y2="${H - 24}"/><text x="${X(t).toFixed(1)}" y="${H - 6}" text-anchor="middle">${TC.esc(tf(t))}</text>`;
    }
    rows.forEach((r, i) => {
      const y = T + 6 + i * RH, w = Math.max(0, X(r.value) - L);
      s += `<text x="${L - 8}" y="${y + 13}" text-anchor="end" style="fill:var(--ink)">${TC.esc(r.label)}</text>`;
      s += `<rect x="${L}" y="${y}" width="${w.toFixed(1)}" height="18" fill="${col(r.color)}"/>`;
      s += `<text class="strong" x="${(L + w + 6).toFixed(1)}" y="${y + 13}">${TC.esc(r.text || f(r.value))}</text>`;
    });
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('aria-label', (o.title ? o.title + ': ' : '') + rows.map(r => `${r.label} ${r.text || f(r.value)}`).join('; '));
    svg.innerHTML = s;
  };

  // One bar split into parts: {label, value, color, text}
  TC.split = (svg, o) => {
    const W = 640, x0 = 20, x1 = 620, tot = o.parts.reduce((a, p) => a + p.value, 0);
    let x = x0, s = '';
    o.parts.forEach(p => {
      const w = ((p.value / tot) * (x1 - x0));
      s += `<rect x="${x.toFixed(1)}" y="14" width="${w.toFixed(1)}" height="34" fill="${col(p.color)}"/>`;
      s += `<text class="strong" x="${(x + 4).toFixed(1)}" y="66" style="font-size:12px">${TC.esc(p.label)}</text><text x="${(x + 4).toFixed(1)}" y="82">${TC.esc(p.text || '')}</text>`;
      x += w;
    });
    s += `<line x1="${x0}" x2="${x0}" y1="8" y2="88" stroke="var(--rule)"/>`;
    svg.setAttribute('viewBox', `0 0 ${W} 96`);
    svg.setAttribute('aria-label', (o.title ? o.title + ': ' : '') + o.parts.map(p => `${p.label} ${p.text || ''}`).join('; '));
    svg.innerHTML = s;
  };

  // Draw every <svg data-chart="key"> that has a definition in manual.charts.
  TC.charts = manual => {
    if (!manual || !manual.charts) return;
    document.querySelectorAll('svg[data-chart]').forEach(svg => {
      const c = manual.charts[svg.dataset.chart];
      if (!c) return;
      try { (c.type === 'split' ? TC.split : TC.hbar)(svg, c); } catch (e) { console.warn('chart', svg.dataset.chart, e); }
    });
  };

  /* ---------- AI summary for "The read" ---------- */
  function showSummary(all) {
    const s = all && all[TC.page];
    const box = document.querySelector('.read');
    if (!s || !s.text || !box) return;
    box.querySelectorAll('p').forEach(p => p.remove());
    const tag = box.querySelector('.tag');
    s.text.split(/\n\s*\n/).forEach(par => {
      const p = document.createElement('p');
      p.textContent = par.trim();
      box.insertBefore(p, tag);
    });
    if (tag) {
      const d = new Date(s.generated + 'T12:00:00');
      tag.textContent = `Drafted by Claude, an AI model, from the figures on this page on ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}. Every number was checked against the page's data before publishing.`;
    }
  }
  if (TC.page !== 'home') TC.get('/data/summaries.json').then(showSummary).catch(() => {});
})();
