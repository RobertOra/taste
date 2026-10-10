// Charts for the How it works page (plain SVG). Data: how/*.json, copied from the study's write-up data.
const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = () => ({ good: css('--good'), bad: css('--bad'), accent: css('--accent'), ink3: css('--ink-3'), band: css('--band'), line: css('--line') });
const load = (f) => fetch(`how/${f}.json`).then((r) => r.json());
const pctf = (d = 0) => (v) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`;
const charts = [];
const draw = (el, fn) => { charts.push([el, fn]); fn(); };
addEventListener('resize', () => charts.forEach(([, fn]) => fn()));
const W = (el) => Math.max(300, Math.min(760, el.clientWidth || 640));
function legend(id, items) { $(id).innerHTML = items.map(([l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join(''); }
function nice(lo, hi, n = 5) {
  const span = hi - lo || 1, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0)), step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0);
  const ticks = []; for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) ticks.push(+t.toFixed(10)); return ticks;
}

// line chart: series [{label, color, pts:[{x, y, lo?, hi?}], band?}]; opts {xfmt, yfmt, ydom, ref, refLabel, xlabel, ylabel, h, xticks}
function line(el, series, o) {
  const w = W(el), h = o.h || 260, pad = { l: 46, r: 14, t: 18, b: o.xlabel ? 40 : 26 };
  const xs = series.flatMap((s) => s.pts.map((p) => p.x)), ys = series.flatMap((s) => s.pts.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const [y0, y1] = o.ydom || [Math.min(...ys, o.ref ?? Infinity), Math.max(...ys, o.ref ?? -Infinity)];
  const yt = nice(y0, y1), Y0 = Math.min(y0, yt[0]), Y1 = Math.max(y1, yt[yt.length - 1]);
  const X = (v) => pad.l + (v - x0) / (x1 - x0 || 1) * (w - pad.l - pad.r), Yp = (v) => pad.t + (1 - (v - Y0) / (Y1 - Y0 || 1)) * (h - pad.t - pad.b);
  let s = yt.map((t) => `<line class="grid" x1="${pad.l}" x2="${w - pad.r}" y1="${Yp(t)}" y2="${Yp(t)}"/><text x="${pad.l - 6}" y="${Yp(t) + 4}" text-anchor="end">${o.yfmt(t)}</text>`).join('');
  (o.xticks || [...new Set(xs)]).forEach((t) => { s += `<text x="${X(t)}" y="${h - (o.xlabel ? 22 : 8)}" text-anchor="middle">${o.xfmt(t)}</text>`; });
  if (o.xlabel) s += `<text x="${(pad.l + w - pad.r) / 2}" y="${h - 4}" text-anchor="middle">${o.xlabel}</text>`;
  if (o.ref !== undefined) s += `<line class="ref" x1="${pad.l}" x2="${w - pad.r}" y1="${Yp(o.ref)}" y2="${Yp(o.ref)}"/>${o.refLabel ? `<text x="${o.refLeft ? pad.l + 4 : w - pad.r}" y="${Yp(o.ref) + (o.refBelow ? 14 : -5)}" text-anchor="${o.refLeft ? 'start' : 'end'}">${o.refLabel}</text>` : ''}`;
  for (const se of series) {
    const p = se.pts;
    if (se.band !== false && p[0].lo !== undefined) s += `<path d="M${p.map((q) => `${X(q.x)},${Yp(q.hi)}`).join('L')}L${[...p].reverse().map((q) => `${X(q.x)},${Yp(q.lo)}`).join('L')}Z" fill="${se.color}" opacity="0.14"/>`;
    s += `<path d="M${p.map((q) => `${X(q.x)},${Yp(q.y)}`).join('L')}" fill="none" stroke="${se.color}" stroke-width="${se.width || 2.2}" stroke-linejoin="round"${se.dash ? ' stroke-dasharray="5 4"' : ''}/>`;
    if (!se.dash) s += p.map((q) => `<circle cx="${X(q.x)}" cy="${Yp(q.y)}" r="3" fill="${se.color}"><title>${se.label}: ${o.yfmt(q.y)}</title></circle>`).join('');
  }
  el.innerHTML = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" style="display:block;max-width:100%">${s}</svg>`;
}

// bar chart: groups [{label, values:[{v, lo?, hi?, color, label?}]}]; opts {yfmt, h}
function bars(el, groups, o) {
  const w = W(el), h = o.h || 250, pad = { l: 46, r: 8, t: 18, b: 40 };
  const vs = groups.flatMap((g) => g.values.flatMap((v) => [v.v, v.lo ?? v.v, v.hi ?? v.v, 0]));
  const yt = nice(Math.min(...vs), Math.max(...vs)), Y0 = Math.min(...vs, yt[0]), Y1 = Math.max(...vs, yt[yt.length - 1]);
  const Yp = (v) => pad.t + (1 - (v - Y0) / (Y1 - Y0 || 1)) * (h - pad.t - pad.b);
  const gw = (w - pad.l - pad.r) / groups.length;
  let s = yt.map((t) => `<line class="grid" x1="${pad.l}" x2="${w - pad.r}" y1="${Yp(t)}" y2="${Yp(t)}"/><text x="${pad.l - 6}" y="${Yp(t) + 4}" text-anchor="end">${o.yfmt(t)}</text>`).join('');
  s += `<line class="axis" x1="${pad.l}" x2="${w - pad.r}" y1="${Yp(0)}" y2="${Yp(0)}"/>`;
  groups.forEach((g, i) => {
    const k = g.values.length, bw = Math.min(46, gw * 0.75 / k), x0 = pad.l + gw * (i + 0.5) - (k * bw + (k - 1) * 3) / 2;
    g.values.forEach((v, j) => {
      const x = x0 + j * (bw + 3), top = Yp(Math.max(0, v.v)), bot = Yp(Math.min(0, v.v));
      s += `<rect x="${x}" y="${top}" width="${bw}" height="${Math.max(1, bot - top)}" rx="3" fill="${v.color}"><title>${v.label || g.label}: ${o.yfmt(v.v)}</title></rect>`;
      if (v.lo !== undefined && v.lo !== null) s += `<line x1="${x + bw / 2}" x2="${x + bw / 2}" y1="${Yp(v.lo)}" y2="${Yp(v.hi)}" stroke="${css('--ink-3')}" stroke-width="1.4"/>`;
    });
    const words = g.label.split(' '), mid = Math.ceil(words.length / 2), l1 = words.length > 2 ? words.slice(0, mid).join(' ') : g.label, l2 = words.length > 2 ? words.slice(mid).join(' ') : '';
    s += `<text x="${pad.l + gw * (i + 0.5)}" y="${h - 22}" text-anchor="middle">${l1}</text>${l2 ? `<text x="${pad.l + gw * (i + 0.5)}" y="${h - 8}" text-anchor="middle">${l2}</text>` : ''}`;
  });
  el.innerHTML = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" style="display:block;max-width:100%">${s}</svg>`;
}

const [repeat, ladder, careers, careerten, fan, obs, genre, years, decade] = await Promise.all(
  ['repeat', 'ladder', 'careers', 'careerten', 'fanvalue', 'obstaste', 'genre', 'yeargrowth', 'decade'].map(load));

// 1. repeat
draw($('#ch-repeat'), () => {
  const c = C(), rows = repeat.filter((r) => (r.measure || 'discernment') === 'discernment').sort((a, b) => a.mid - b.mid);
  legend('#leg-repeat', [['Average later rank', c.accent], ['Perfect repeat / pure luck', c.ink3]]);
  line($('#ch-repeat'), [{ label: 'Later rank', color: c.accent, pts: rows.map((r) => ({ x: r.mid, y: r.later_mean, lo: r.later_p25, hi: r.later_p75 })) },
    { label: 'Perfect repeat', color: c.ink3, dash: true, band: false, width: 1.2, pts: [{ x: 5, y: 5 }, { x: 99.5, y: 99.5 }] }],
  { xfmt: (v) => String(v), yfmt: (v) => String(Math.round(v)), ydom: [0, 100], ref: 50, refLabel: 'Pure luck', xticks: [0, 25, 50, 75, 90, 100].filter((t) => t >= 5), xlabel: 'Rank in earlier years (percentile)' });
});
// 2. ladder
draw($('#ch-ladder'), () => {
  const c = C(), rows = ladder.filter((r) => !r.detail && r.mid !== null).sort((a, b) => a.mid - b.mid);
  line($('#ch-ladder'), [{ label: 'Their new artists', color: c.accent, pts: rows.map((r) => ({ x: r.mid, y: r.rate * 1000 })) },
    { label: 'Similar artists', color: c.ink3, dash: true, width: 1.4, pts: rows.map((r) => ({ x: r.mid, y: r.similar_rate * 1000 })) }],
  { xfmt: (v) => (v === 5 ? 'bottom 10%' : v === 99.5 ? 'top 1%' : String(v)), yfmt: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)), ydom: [0, 12], xticks: [5, 25, 50, 75, 90, 99.5], xlabel: "Picker's rank from earlier years (percentile)" });
});
// 3. careers
draw($('#ch-careers'), () => {
  const c = C(), ser = [['best', "Best fifth's new artists", c.good], ['worst', "Worst fifth's new artists", c.bad]];
  legend('#leg-careers', ser.map(([, l, col]) => [l, col]));
  line($('#ch-careers'), ser.map(([g, l, col]) => ({ label: l, color: col, pts: [{ x: 0, y: 0, lo: 0, hi: 0 }, ...careers.filter((r) => r.group === g).sort((a, b) => a.years - b.years).map((r) => ({ x: r.years, y: r.growth, lo: r.lo, hi: r.hi }))] })),
    { xfmt: (v) => (v === 0 ? 'Found' : `${v} yr`), yfmt: pctf(), ref: 0 });
});
draw($('#ch-careerten'), () => {
  const c = C(), ser = [['top1', 'Top 1%', c.accent], ['top5', 'Top 5%', css('--good')], ['best', 'Best fifth', c.ink3], ['worst', 'Worst fifth', c.bad]];
  legend('#leg-careerten', ser.map(([, l, col]) => [l, col]));
  line($('#ch-careerten'), ser.map(([g, l, col]) => ({ label: l, color: col, band: g === 'top1', pts: careerten.filter((r) => r.group === g).sort((a, b) => a.years - b.years).map((r) => ({ x: r.years, y: r.times_similar, lo: r.lo, hi: r.hi })) })),
    { xfmt: (v) => `${v} yr`, yfmt: (v) => `${v.toFixed(1)}×`, ref: 1, refLabel: 'Same as similar artists', refBelow: true, refLeft: true, ydom: [0.5, 5.4] });
});
// 4. fan value
draw($('#ch-fan'), () => {
  const c = C(), fans = [['good', 'Good picker', c.good], ['ordinary', 'Ordinary fan', c.ink3], ['poor', 'Poor picker', c.bad]];
  legend('#leg-fan', fans.map(([, l, col]) => [l, col]));
  const get = (k) => fan.find((r) => r.key === k);
  bars($('#ch-fan'), [['small', 'Small artist (≤20)'], ['medium', 'Medium (21–100)'], ['big', 'Big (100+)']].map(([st, label]) => ({ label,
    values: fans.map(([f, l, col]) => { const r = get(`${st}:${f}`); return { v: r.effect, lo: r.lo, hi: r.hi, color: col, label: l }; }) })), { yfmt: pctf() });
});
// 6. obsessions
draw($('#ch-obs'), () => {
  const c = C(), ser = [['top', 'Top-fifth pickers', c.good], ['bottom', 'Bottom-fifth pickers', c.bad]];
  legend('#leg-obs', ser.map(([, l, col]) => [l, col]));
  const labels = new Map(obs.filter((r) => r.group === 'all').map((r) => [r.decile, r.label]));
  line($('#ch-obs'), ser.map(([g, l, col]) => ({ label: l, color: col, band: false, pts: obs.filter((r) => r.group === g).sort((a, b) => a.decile - b.decile).map((r) => ({ x: r.decile, y: r.growth })) })),
    { xfmt: (v) => labels.get(v) || '', yfmt: pctf(), ref: 0, xlabel: 'Plays before committing (tenths of all picks)' });
});
// 7. genre
draw($('#ch-genre'), () => {
  const c = C(), rows = genre.filter((r) => r.family && r.gap !== undefined).sort((a, b) => b.gap - a.gap);
  bars($('#ch-genre'), rows.map((r) => ({ label: r.family.replace(' & ', ' & '), values: [{ v: r.gap, lo: r.gap_lo, hi: r.gap_hi, color: c.accent }] })), { yfmt: pctf(), h: 270 });
});
// 8. years
draw($('#ch-years'), () => {
  const c = C(), rows = years.filter((r) => r.year !== undefined && r.year !== null).sort((a, b) => a.year - b.year);
  const ser = [['best', 'Best fifth of pickers', c.good], ['worst', 'Worst fifth of pickers', c.bad]];
  legend('#leg-years', ser.map(([, l, col]) => [l, col]));
  line($('#ch-years'), ser.map(([g, l, col]) => ({ label: l, color: col, pts: rows.map((r) => ({ x: r.year, y: r[`${g}_growth`], lo: r[`${g}_lo`], hi: r[`${g}_hi`] })) })),
    { xfmt: (v) => String(v), yfmt: pctf(), ref: 0, xticks: rows.map((r) => r.year).filter((y) => y % 2 === 0) });
});
// 9. decade
draw($('#ch-decade'), () => {
  const c = C(), rows = decade.filter((r) => r.measure === 'prescience').sort((a, b) => a.years_later - b.years_later);
  const ser = [['top_in_top', '2015 top fifth still in the top fifth', c.good], ['bottom_in_bottom', '2015 bottom fifth still in the bottom fifth', c.bad]];
  legend('#leg-decade', ser.map(([, l, col]) => [l, col]));
  line($('#ch-decade'), ser.map(([k, l, col]) => ({ label: l, color: col, pts: rows.map((r) => ({ x: r.years_later, y: r[k], lo: r[`${k}_lo`], hi: r[`${k}_hi`] })) })),
    { xfmt: (v) => `${v}`, yfmt: (v) => `${Math.round(v * 100)}%`, ydom: [0.1, 0.4], ref: 0.2, refLabel: 'Chance: 20%', xlabel: 'Years after 2015' });
});
