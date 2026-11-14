/* Two Cents for Alaska: shared code for indicator pages and front-page tiles.
 *
 * Pages are written by scripts/build_pages.py. Anything that comes from a live
 * data file is described by a small JSON spec in a data-* attribute and filled
 * in here, so the numbers update whenever the refresh job commits new data:
 *
 *   <div class="stat" data-spec='{"file":"labor","series":"AKUR","calc":"latest","dec":1,"suffix":"%"}'>
 *   <figure class="chart" data-chart='{"kind":"line","series":[...]}'>
 *   <a class="tile" data-tile='{"main":{...},"chg":{...}}'>   (front page)
 *
 * Text in labels can use {date} (latest period of that series) and {year}.
 */
(function () {
  const IND = (window.IND = {});
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const cache = {};

  IND.get = file => cache[file] || (cache[file] = fetch(`/data/${file}.json`, { cache: 'no-cache' })
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .catch(() => (window.SNAPSHOT && window.SNAPSHOT[file]) || null));

  const series = (d, id) => {
    const s = d && d.series && d.series[id];
    return s && s.dates && s.dates.length ? s : null;
  };

  /* ---------- dates ---------- */
  function fdate(d, freq) {
    const y = d.slice(0, 4), m = +d.slice(5, 7);
    if (freq === 'annual') return y;
    if (freq === 'quarterly') return 'Q' + (Math.floor((m - 1) / 3) + 1) + ' ' + y;
    if (freq === 'weekly' || freq === 'daily') return MON[m - 1] + ' ' + +d.slice(8, 10) + ', ' + y;
    return MON[m - 1] + ' ' + y;
  }
  const yearAgo = d => (+d.slice(0, 4) - 1) + d.slice(4);
  const xOf = d => +d.slice(0, 4) + (+d.slice(5, 7) - 1) / 12;

  /* ---------- numbers ---------- */
  function fmt(v, o = {}) {
    if (v == null || !isFinite(v)) return '—';
    const x = v * (o.scale || 1), dec = o.dec == null ? 0 : o.dec;
    const sign = o.sign ? (x > 0 ? '+' : x < 0 ? '−' : '') : x < 0 ? '−' : '';
    return sign + (o.prefix || '') + Math.abs(x).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + (o.suffix || '');
  }
  IND.fmt = fmt;

  function annual(s, agg) {
    const by = {};
    s.dates.forEach((d, i) => (by[d.slice(0, 4)] = by[d.slice(0, 4)] || []).push(s.values[i]));
    const per = { monthly: 12, bimonthly: 6, quarterly: 4, annual: 1, weekly: 52 }[s.freq] || 12;
    const out = [];
    for (const y of Object.keys(by).sort()) {
      const v = by[y], full = s.freq === 'weekly' ? v.length >= 50 : v.length >= per;
      out.push({ year: y, value: agg === 'sum' ? v.reduce((a, b) => a + b, 0) : v.reduce((a, b) => a + b, 0) / v.length, full, n: v.length });
    }
    return out;
  }

  /* calc: returns {value, date, freq} */
  function calc(spec, s, other) {
    const n = s.dates.length - 1, d = s.dates[n], v = s.values[n], f = s.freq;
    const at = date => { const i = s.dates.indexOf(date); return i < 0 ? null : s.values[i]; };
    switch (spec.calc || 'latest') {
      case 'latest': return { value: v, date: d, freq: f };
      case 'yoy_pct': case 'yoy_diff': {
        // Latest period that has a value a year earlier (a missing month, such as
        // October 2025 during the federal shutdown, falls back to the one before).
        for (let i = n; i >= Math.max(0, n - 6); i--) {
          const p = at(yearAgo(s.dates[i]));
          if (p != null && p !== 0) return { value: spec.calc === 'yoy_pct' ? (s.values[i] / p - 1) * 100 : s.values[i] - p, date: s.dates[i], freq: f };
        }
        return { value: null, date: d, freq: f };
      }
      case 'prev_pct': { const p = s.values[n - 1]; return { value: p ? (v / p - 1) * 100 : null, date: d, freq: f }; }
      case 'qgrowth': { const p = s.values[n - 1]; return { value: p ? (Math.pow(v / p, 4) - 1) * 100 : null, date: d, freq: f }; }
      case 'ytd_sum': {
        const y = d.slice(0, 4); let t = 0;
        s.dates.forEach((x, i) => { if (x.slice(0, 4) === y) t += s.values[i]; });
        return { value: t, date: d, freq: f, ytd: true };
      }
      case 'ytd_yoy_pct': {
        const y = d.slice(0, 4), py = String(+y - 1), mm = d.slice(5); let a = 0, b = 0;
        s.dates.forEach((x, i) => { if (x.slice(0, 4) === y) a += s.values[i]; if (x.slice(0, 4) === py && x.slice(5) <= mm) b += s.values[i]; });
        return { value: b ? (a / b - 1) * 100 : null, date: d, freq: f };
      }
      case 'annual_last': case 'annual_yoy_pct': {
        const a = annual(s, spec.agg).filter(r => r.full), L = a[a.length - 1], P = a[a.length - 2];
        if (!L) return { value: null, date: d, freq: 'annual' };
        const val = spec.calc === 'annual_last' ? L.value : P ? (L.value / P.value - 1) * 100 : null;
        return { value: val, date: L.year + '-01-01', freq: 'annual' };
      }
      case 'ratio': case 'diff_vs': {
        if (!other) return { value: null, date: d, freq: f };
        const i = other.dates.indexOf(d), o = i < 0 ? other.values[other.values.length - 1] : other.values[i];
        return { value: spec.calc === 'ratio' ? v / o : v - o, date: d, freq: f };
      }
      default: return { value: v, date: d, freq: f };
    }
  }

  async function evaluate(spec) {
    const d = await IND.get(spec.file), s = series(d, spec.series);
    if (!s) return null;
    let other = null;
    if (spec.over) { const od = await IND.get(spec.over.file); other = series(od, spec.over.series); }
    return calc(spec, s, other);
  }
  IND.evaluate = evaluate;

  const fill = (txt, r) => txt.replace(/\{date\}/g, r ? fdate(r.date, r.freq) : '').replace(/\{year\}/g, r ? r.date.slice(0, 4) : '');

  /* ---------- stats ---------- */
  async function stat(el) {
    let spec; try { spec = JSON.parse(el.dataset.spec); } catch (e) { return; }
    const r = await evaluate(spec);
    const b = el.querySelector('b');
    if (!r || r.value == null) { b.textContent = '—'; b.classList.add('na'); return; }
    b.textContent = fmt(r.value, spec);
    el.querySelectorAll('[data-t]').forEach(x => (x.textContent = fill(x.dataset.t, r)));
  }

  /* ---------- charts ---------- */
  function ticks(lo, hi, n = 4) {
    const span = hi - lo || Math.abs(hi) || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(k => span / k <= n + 0.5) || 10 * mag;
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, out = [];
    for (let t = a; t <= b + step / 1e6; t += step) out.push(+t.toFixed(10));
    return out;
  }
  const PALETTE = ['#1F5FA8', '#C2610C', '#5A6580', '#2E7D5B'];
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function transform(s, t) {
    if (!t) return s;
    const by = new Map(s.dates.map((d, i) => [d, s.values[i]])), d = [], v = [];
    s.dates.forEach((x, i) => {
      let y = null;
      if (t === 'yoy_pct') { const p = by.get(yearAgo(x)); if (p) y = (s.values[i] / p - 1) * 100; }
      if (t === 'qgrowth' && i > 0) y = (Math.pow(s.values[i] / s.values[i - 1], 4) - 1) * 100;
      if (t === 'yoy_diff') { const p = by.get(yearAgo(x)); if (p != null) y = s.values[i] - p; }
      if (y != null) { d.push(x); v.push(y); }
    });
    return { ...s, dates: d, values: v };
  }

  async function chart(fig) {
    let c; try { c = JSON.parse(fig.dataset.chart); } catch (e) { return; }
    const plot = fig.querySelector('.plot');
    const got = [];
    for (const [k, sp] of c.series.entries()) {
      const d = await IND.get(sp.file), s0 = series(d, sp.id);
      if (!s0) continue;
      let s = transform(s0, sp.transform);
      if (c.agg) { const a = annual(s, c.agg); s = { ...s, dates: a.map(r => r.year + '-01-01'), values: a.map(r => r.value), partial: a.map(r => !r.full), freq: 'annual' }; }
      const from = c.from || '0000';
      const keep = s.dates.map((x, i) => i).filter(i => s.dates[i] >= from);
      got.push({ label: sp.label, color: sp.color || PALETTE[k % PALETTE.length], dates: keep.map(i => s.dates[i]), values: keep.map(i => s.values[i]), partial: s.partial && keep.map(i => s.partial[i]), freq: s.freq, scale: sp.scale || 1, rawDate: s0.dates[s0.dates.length - 1], rawFreq: s0.freq });
    }
    if (!got.length) { plot.innerHTML = '<p class="note">Data not available yet.</p>'; return; }
    got.forEach(g => (g.values = g.values.map(v => v * g.scale)));
    const o = { dec: c.dec || 0, prefix: c.prefix || '', suffix: c.suffix || '' };
    plot.innerHTML = c.kind === 'bars' ? bars(got[0], o, c) : line(got, o, c);
    const last = got[0];
    fig.querySelectorAll('[data-t]').forEach(x => (x.textContent = fill(x.dataset.t, { date: last.rawDate, freq: last.rawFreq })));
  }

  function line(G, o, c) {
    const W = 680, H = c.height || 260, L = 52, R = 96, T = 12, B = 28;
    const xs = G.flatMap(g => g.dates.map(xOf)), ys = G.flatMap(g => g.values);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (c.zero !== false && lo > 0) lo = 0;
    const tk = ticks(lo, hi), y0 = tk[0], y1 = tk[tk.length - 1];
    const X = x => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), Y = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.aria || c.title || 'Chart')}">`;
    tk.forEach(t => (s += `<line x1="${L}" x2="${W - R}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="${t === 0 && y0 < 0 ? '#14213D' : '#C9D2DE'}"/><text x="${L - 6}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="#5A6580">${esc(fmt(t, { ...o, dec: Math.abs(y1 - y0) < 5 && o.dec ? o.dec : 0 }))}</text>`));
    const yr0 = Math.ceil(x0), yr1 = Math.floor(x1), stepY = Math.max(1, Math.ceil((yr1 - yr0) / 6));
    for (let y = yr0; y <= yr1; y += stepY) s += `<text x="${X(y).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#5A6580">${y}</text>`;
    let lastLabelY = [];
    G.forEach(g => {
      s += `<polyline points="${g.dates.map((d, i) => X(xOf(d)).toFixed(1) + ',' + Y(g.values[i]).toFixed(1)).join(' ')}" fill="none" stroke="${g.color}" stroke-width="2.4" stroke-linejoin="round"/>`;
      const i = g.values.length - 1; let ly = Y(g.values[i]) + 4;
      lastLabelY.forEach(p => { if (Math.abs(p - ly) < 14) ly = p + (ly >= p ? 14 : -14); }); lastLabelY.push(ly);
      s += `<text x="${(X(xOf(g.dates[i])) + 6).toFixed(1)}" y="${ly.toFixed(1)}" font-size="12" font-weight="600" fill="${g.color}">${esc((G.length > 1 ? g.label + ' ' : '') + fmt(g.values[i], o))}</text>`;
    });
    return s + '</svg>' + (G.length > 1 ? `<div class="legend">${G.map(g => `<span><i style="background:${g.color}"></i>${esc(g.label)}</span>`).join('')}</div>` : '');
  }

  function bars(g, o, c) {
    const W = 680, H = c.height || 240, L = 52, R = 12, T = 18, B = 28, n = g.values.length;
    let lo = Math.min(0, ...g.values), hi = Math.max(0, ...g.values);
    const tk = ticks(lo, hi), y0 = tk[0], y1 = tk[tk.length - 1];
    const Y = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B), slot = (W - L - R) / n, bw = Math.min(46, slot * 0.66);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.aria || c.title || 'Chart')}">`;
    tk.forEach(t => (s += `<line x1="${L}" x2="${W - R}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="${t === 0 ? '#14213D' : '#C9D2DE'}"/><text x="${L - 6}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="#5A6580">${esc(fmt(t, { ...o, dec: 0 }))}</text>`));
    const every = Math.max(1, Math.ceil(n / 12));
    g.values.forEach((v, i) => {
      const cx = L + slot * i + slot / 2, top = Y(Math.max(v, 0)), h = Math.abs(Y(v) - Y(0)), part = g.partial && g.partial[i];
      s += `<rect x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(h, 0.5).toFixed(1)}" fill="${v < 0 ? '#C2610C' : g.color}" opacity="${part ? 0.5 : 1}"/>`;
      if (n <= 14) s += `<text x="${cx.toFixed(1)}" y="${(v < 0 ? Y(v) + 13 : top - 5).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="600" fill="#14213D">${esc(fmt(v, o))}</text>`;
      if (i % every === 0 || i === n - 1) s += `<text x="${cx.toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#5A6580">${esc((g.freq === 'quarterly' ? fdate(g.dates[i], 'quarterly').replace(' 20', " '") : g.dates[i].slice(0, 4)) + (part ? '*' : ''))}</text>`;
    });
    return s + '</svg>';
  }

  /* ---------- front-page tiles ---------- */
  async function tile(el) {
    let t; try { t = JSON.parse(el.dataset.tile); } catch (e) { return; }
    const r = await evaluate(t.main);
    if (!r || r.value == null) return;
    const v = el.querySelector('[data-v]'); v.textContent = fmt(r.value, t.main); v.classList.remove('na');
    const d = el.querySelector('[data-d]'); if (d) d.textContent = fdate(r.date, r.freq);
    if (t.chg) {
      const c = await evaluate(t.chg), ce = el.querySelector('[data-c]');
      if (ce) ce.textContent = c && c.value != null ? fmt(c.value, t.chg) + (t.chg.after || '') : '';
    }
  }

  IND.run = () => {
    document.querySelectorAll('.stat[data-spec]').forEach(stat);
    document.querySelectorAll('figure[data-chart]').forEach(chart);
    document.querySelectorAll('[data-tile]').forEach(tile);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', IND.run); else IND.run();
})();
