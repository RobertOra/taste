// Taste Test page: reads Spotify files, scores them with engine.js (in the browser), renders the report.
import { scoreHistory, monthLabel } from './engine.js';

const $ = (s) => document.querySelector(s);
let META = null;
const metaReady = fetch('data/meta.json').then((r) => r.json()).then((m) => (META = m));
const fetchShard = async (i) => { const r = await fetch(`data/s/${i.toString(16).padStart(4, '0')}.bin`); return r.ok ? await r.arrayBuffer() : null; };

// ---------- input
async function readEntries(entry, out) {   // a dropped folder
  if (entry.isFile) { if (/\.(zip|json)$/i.test(entry.name)) out.push(await new Promise((res, rej) => entry.file(res, rej))); return; }
  const reader = entry.createReader(); let batch;
  do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); for (const e of batch) await readEntries(e, out); } while (batch.length);
}
function status(msg, { err = false, progress = null } = {}) {
  const s = $('#status'); s.hidden = false; s.classList.toggle('error', err);
  s.innerHTML = `<div></div>${progress === null ? '' : '<div class="bar"><i></i></div>'}`;
  s.firstChild.textContent = msg;
  if (progress !== null) s.querySelector('.bar i').style.width = `${Math.round(progress * 100)}%`;
}
async function run(fileList) {
  const files = [...fileList].filter((f) => /\.(zip|json)$/i.test(f.name));
  if (!files.length) return status('No Spotify files found. Look for files named Streaming_History_Audio_….json, or the zip that contains them.', { err: true });
  try {
    $('#report').hidden = true;
    status('Reading your files…');
    const data = await Promise.all(files.map(async (f) => ({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) })));
    await metaReady;
    status('Checking how your finds did…', { progress: 0 });
    const r = await scoreHistory(data, META, fetchShard, (x) => status('Checking how your finds did…', { progress: x }));
    if (!r.ok) return status((r.checks || []).filter((c) => !c.ok).map((c) => c.text).join(' ') || 'We couldn\'t score these files.', { err: true });
    $('#status').hidden = true;
    render(r);
  } catch (e) { console.error(e); status(`Something went wrong reading these files: ${e.message || e}`, { err: true }); }
}
const drop = $('#drop');
['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', async (e) => {
  const items = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (items.length) { const files = []; for (const it of items) await readEntries(it, files); run(files); } else run([...e.dataTransfer.files]);
});
$('#pick-files').addEventListener('change', (e) => run([...e.target.files]));
$('#pick-folder').addEventListener('change', (e) => run([...e.target.files]));

// ---------- formatting
const pct = (x, d = 0) => (x >= 0 ? '+' : '−') + Math.abs(100 * x).toFixed(d) + '%';
const ord = (n) => { n = Math.round(n); const s = (n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'); return n + s; };
const n = (x) => Math.round(x).toLocaleString();
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const cls = (x) => (x >= 0 ? 'pos' : 'neg');
const card = (title, sub, body, extra = '') => `<section class="card"${extra}><h2>${title}</h2>${sub ? `<p class="sub">${sub}</p>` : ''}${body}</section>`;
const tier = (p) => (p >= 90 ? 'Trendsetter' : p >= 75 ? 'Ahead of the curve' : p >= 50 ? 'Good ear' : p >= 25 ? 'In the mix' : 'Following the crowd');

function distChart(score, lo, hi, ref) {   // reference listeners' scores, your score and likely range
  const W = 460, H = 130, pad = 18, L = -0.15, U = 0.15, bins = 48, bw = (U - L) / bins, cnt = new Array(bins).fill(0);
  for (const v of ref) cnt[Math.floor((Math.min(U - 1e-9, Math.max(L, v)) - L) / bw)]++;
  const max = Math.max(...cnt), x = (v) => pad + (Math.min(U, Math.max(L, v)) - L) / (U - L) * (W - 2 * pad), base = H - 22;
  const bars = cnt.map((c, i) => `<rect class="barref" x="${x(L + i * bw) + 0.5}" y="${base - c / max * (base - 22)}" width="${(W - 2 * pad) / bins - 1}" height="${c / max * (base - 22)}"/>`).join('');
  const ticks = [-0.1, -0.05, 0, 0.05, 0.1].map((t) => `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${t === 0 ? 'average' : pct(t)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Your score among reference listeners">
    <rect class="bandref" x="${x(lo)}" y="18" width="${Math.max(2, x(hi) - x(lo))}" height="${base - 18}" rx="3"/>${bars}
    <line class="axis" x1="${pad}" x2="${W - pad}" y1="${base}" y2="${base}"/>${ticks}
    <line class="you" x1="${x(score)}" x2="${x(score)}" y1="14" y2="${base}"/><text class="youlabel" x="${x(score)}" y="11" text-anchor="middle">you</text></svg>`;
}
function signedBars(items) {
  const m = Math.max(0.02, ...items.filter((i) => i.v !== null).map((i) => Math.abs(i.v)));
  return `<table class="sbars">${items.map((i) => `<tr><td style="width:42%">${i.label}</td><td>${i.v === null ? '<span class="muted">–</span>' : `<div class="impact"><div class="track">
    <div class="fill ${cls(i.v)}" style="${i.v >= 0 ? 'left:50%' : 'right:50%'};width:${Math.abs(i.v) / m * 50}%"></div></div><span class="val ${cls(i.v)}">${pct(i.v)}</span></div>`}</td>
    <td class="num muted">${i.note || ''}</td></tr>`).join('')}</table>`;
}

// ---------- report
function render(r) {
  const u = r.units.artist, R = r.report;
  const warn = (r.checks || []).filter((c) => c.warn).map((c) => `<p class="warnline">${esc(c.text)}</p>`).join('');
  const hero = `<section class="card"><div class="hero">
      <div><span class="tier">${tier(u.percentile)}</span>
        <div class="big">${u.percentile}%<small>of listeners beaten</small></div>
        <p class="meaning">You're better than <b>${u.percentile}%</b> of listeners at finding artists before they take off. The artists you got into gained
          <b class="${cls(R.avgGrowth)}">${pct(R.avgGrowth, 1)}</b> new listeners compared with similar artists over the next year.</p>
        <p class="meaning">Your true rank is most likely between the <b>${ord(u.range[0])}</b> and <b>${ord(u.range[1])}</b> percentile.</p>${warn}</div>
      <div>${distChart(u.score, R.rangeScores[0], R.rangeScores[1], META.scores)}
        <p class="note">Gray bars: ${n(META.scores.length)} ListenBrainz listeners scored the same way. Blue band: your likely range.
          Based on ${n(u.picks)} artists you got into, ${esc(u.window)}.</p></div>
    </div></section>`;

  const F = R.facts;
  const facts = `<div class="facts" style="margin:16px 0">
    <div class="fact"><b>${n(F.plays)}</b><span>plays over ${F.years} years</span></div>
    <div class="fact"><b>${n(F.artists)}</b><span>different artists</span></div>
    <div class="fact"><b>${n(F.finds)}</b><span>artists you really got into (about ${F.findsPerYear} a year)</span></div>
    <div class="fact"><b>${r.took_off.yours} <span style="font-size:15px;color:var(--ink-3)">vs ${r.took_off.expected} typical</span></b><span>of your scored finds took off (3× the new listeners a year later)</span></div>
  </div>`;

  const A = R.ahead;
  const ahead = A.share === null ? '' : card('Ahead of the crowd', null, `<div class="big">${Math.round(A.share * 100)}%</div>
    <p class="meaning">On average, ${Math.round(A.share * 100)}% of each artist's ListenBrainz fans got into them <b>after</b> you did
      (across ${n(A.artists)} artists that took off after 2010).</p>
    ${A.best.length ? `<div class="calls">${A.best.map((b) => `<div class="call"><b>${esc(b.name)}</b><span>you got into them in ${monthLabel(b.m)},<br>before ${Math.round(b.share * 100)}% of their ${n(b.fans)} fans</span></div>`).join('')}</div>` : ''}`);

  const sure = card('How sure is this?', null, `<div class="facts">
    <div class="fact"><b>${n(u.picks)}</b><span>artists scored (your last five judged years)</span></div>
    <div class="fact"><b>${ord(u.range[0])}–${ord(u.range[1])}</b><span>likely range of your rank (80%)</span></div>
    <div class="fact"><b>${u.reliability.toFixed(2)}</b><span>reliability with this much history (1 = perfectly repeatable)</span></div>
    <div class="fact"><b>${Math.round(R.matchedShare * 100)}%</b><span>of the artists you got into were in the reference data</span></div></div>
    <p class="note">Any single find is mostly luck, so a score built from a few hundred is fuzzy; more history narrows the range. Taste also drifts:
      in the study, good taste faded over about a decade, so only your last five judged years count.</p>`);

  const where = card('Where your edge comes from', 'Part of a score comes from being into scenes that were about to grow; the rest from picking better artists than others in the same scene. Your score counts only the second.',
    signedBars([{ label: 'Being in rising scenes', v: R.edge.scenes }, { label: 'Picking well within your scenes', v: R.edge.within }]));
  const years = card('Year by year', 'How the artists you got into each year did. Gray years are outside your score.',
    signedBars(R.byYear.map((y) => ({ label: y.inScore ? String(y.year) : `<span class="muted">${y.year}</span>`, v: y.growth, note: `${y.finds} artists` }))));
  const conv = card('Conviction', 'Your finds grouped by how many times you played them in their first six months.',
    signedBars(R.conviction.map((c) => ({ label: `${c.label} <span class="muted">(${c.hi === Infinity || c.hi === null ? c.lo + '+' : c.lo + '–' + c.hi})</span>`, v: c.finds >= 5 ? c.growth : null, note: `${n(c.finds)} artists` }))));
  const how = R.how.length > 1 ? card('How you found them', 'How the first play of each find started, from your Spotify data.',
    signedBars(R.how.map((h) => ({ label: h.label, v: h.finds >= 5 ? h.growth : null, note: `${n(h.finds)} artists` })))) : '';

  const big = [...R.finds].sort((a, b) => b.extra - a.extra).slice(0, 10);
  const bigT = card('Biggest finds', 'Your finds that gained the most new listeners beyond what was typical for similar artists, in the year after you got into them.', `<div class="tablewrap"><table>
    <tr><th>Artist</th><th>Found</th><th class="num">New listeners then → a year later</th><th class="num hide-sm">Typical</th><th class="num">Beyond typical</th></tr>
    ${big.map((f) => `<tr><td class="artist" title="${esc(f.name)}">${esc(f.name)}</td><td class="muted">${f.found}</td><td class="num nowrap">${n(f.a0)} → ${n(f.a1)}</td>
      <td class="num muted hide-sm">${n(f.a1 - f.extra)}</td><td class="num pos">+${n(f.extra)}</td></tr>`).join('')}</table></div>
    <p class="note">New listeners: ListenBrainz listeners who first played the artist in the six months up to when you got into them, and in the same six months a year later.</p>`);

  const openT = R.open.length ? card('Open bets', 'Your newest finds, too recent to score (each needs a year). How they are doing so far, by new listeners.', `<div class="tablewrap"><table>
    <tr><th>Artist</th><th>Found</th><th class="num">New listeners then → lately</th><th class="num">So far</th><th class="num hide-sm">Your plays</th></tr>
    ${R.open.map((o) => `<tr><td class="artist">${esc(o.name)}</td><td class="muted">${o.found}</td><td class="num nowrap">${n(o.then)} → ${o.now === null ? '…' : n(o.now)}</td>
      <td class="num ${o.now === null ? 'muted' : cls(o.now - o.then)}">${o.now === null ? 'too new' : pct((o.now + 1) / (o.then + 1) - 1)}</td><td class="num hide-sm">${o.plays26}</td></tr>`).join('')}</table></div>`) : '';

  const NC = R.notCounted, reasons = [
    ['Only tried', NC.tried, 'Played in fewer than four separate weeks, or not four weeks within six months of first hearing them. An artist counts as a find once you play them in four different weeks.'],
    ['Warm-up', NC.warmup, 'First heard in your first six months of history: when a history starts, artists you already loved show up as "new". Reference listeners get the same warm-up.'],
    ['Too recent to judge', NC.tooRecent, 'Found less than a year before the reference data ends, so there\'s no year of follow-up yet. See Open bets.'],
    ['Older finds', NC.older, 'Finds from before your last five judged years. Taste drifts, so they don\'t count toward your score.'],
    ['Not in the reference data', NC.unrecognised, 'Fewer than two ListenBrainz listeners ever played them, or the name is spelled differently there.'],
    ['Before 2011', NC.early, 'The reference data starts in 2011.'],
  ].filter(([, l]) => l.length);
  const ncT = card('Not counted', 'The rest of your history, and why it isn\'t in the score.', `<div class="reasons">
    ${reasons.map(([t, l, why]) => `<details><summary><b>${n(l.length)}</b> ${t}</summary><p class="why">${why}</p><div class="list">${l.slice(0, 300).map((d) => esc(d)).join('<br>')}${l.length > 300 ? `<br>… and ${n(l.length - 300)} more` : ''}</div></details>`).join('')}</div>`);

  $('#report').innerHTML = hero + facts + `<div class="cols">${ahead}${sure}</div>` + `<div class="cols">${where}${conv}</div>` + `<div class="cols">${years}${how}</div>`
    + picksCard(u) + bigT + openT + ncT
    + `<p class="note" style="text-align:center"><a href="how.html">How this works</a> · <a href="#" id="again">Score another history</a></p>`;
  $('#report').hidden = false;
  wirePicks(R);
  $('#again').onclick = (e) => { e.preventDefault(); $('#report').hidden = true; window.scrollTo(0, 0); };
  $('#report').scrollIntoView();
}

// every scored find, by impact on the score
let sortKey = 'impact', sortDir = -1, filter = '', showAll = false;
function picksCard(u) {
  return `<section class="card"><h2>Every find, by impact</h2>
    <p class="sub">How much each artist moved your score; together they add up to it. An artist helps when it gained more new listeners than similar
      artists found the same month (same size, momentum, scene, age and release timing).</p>
    <div class="tablebar"><input id="pick-filter" placeholder="Find an artist…" autocomplete="off"><button id="pick-all" class="btn small ghost"></button></div>
    <div class="tablewrap"><table id="pick-table"></table></div></section>`;
}
function wirePicks(R) {
  const tbl = $('#pick-table'), A = R.finds, maxC = Math.max(...A.map((x) => Math.abs(x.impact)));
  const cols = [['impact', 'Impact', ''], ['name', 'Artist', ''], ['m', 'Found', ''], ['a0', 'New listeners then → a year later', 'num'], ['vs', 'vs similar', 'num'], ['plays26', 'Your plays', 'num hide-sm']];
  const rank = new Map([...A].sort((a, b) => b.impact - a.impact).map((x, i) => [x, i + 1]));
  const row = (x) => `<tr><td><div class="impact"><span class="muted" style="width:34px;text-align:right">${rank.get(x)}</span><div class="track"><div class="fill ${cls(x.impact)}" style="${x.impact >= 0 ? 'left:50%' : 'right:50%'};width:${Math.abs(x.impact) / maxC * 50}%"></div></div></div></td>
      <td class="artist" title="${esc(x.name)}${x.track ? ` (first heard: ${esc(x.track)})` : ''}">${esc(x.name)}</td><td class="muted nowrap">${x.found}</td><td class="num nowrap">${n(x.a0)} → ${n(x.a1)}</td>
      <td class="num ${cls(x.vs)}">${pct(x.vs)}</td><td class="num hide-sm">${x.plays26}</td></tr>`;
  function draw() {
    let ps = [...A].sort((a, b) => { const x = a[sortKey], y = b[sortKey]; return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sortDir; });
    if (filter) ps = ps.filter((x) => x.name.toLowerCase().includes(filter));
    const head = `<tr>${cols.map(([k, t, c]) => `<th class="sortable ${c}" data-k="${k}">${t}${sortKey === k ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr>`;
    const body = (showAll || filter || ps.length <= 60) ? ps.map(row).join('')
      : ps.slice(0, 25).map(row).join('') + `<tr class="gapline"><td colspan="6">${n(ps.length - 50)} more artists</td></tr>` + ps.slice(-25).map(row).join('');
    tbl.innerHTML = head + body;
    $('#pick-all').textContent = showAll ? 'Show top and bottom 25' : `Show all ${n(A.length)}`;
    $('#pick-all').hidden = !!filter || A.length <= 60;
    tbl.querySelectorAll('th.sortable').forEach((th) => (th.onclick = () => { const k = th.dataset.k; if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === 'name' || k === 'm' ? 1 : -1; } draw(); }));
  }
  $('#pick-filter').oninput = (e) => { filter = e.target.value.trim().toLowerCase(); draw(); };
  $('#pick-all').onclick = () => { showAll = !showAll; draw(); };
  draw();
}

// local page tests: window.__render(result) renders a result object
window.__render = (r) => { META = META || window.__meta; render(r); };
window.__run = run;
