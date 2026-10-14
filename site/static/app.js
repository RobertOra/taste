// Taste Test page: reads Spotify and/or YouTube (Google Takeout) files, scores them with engine.js in the browser (reference data read by byte range), renders the report.
import { scoreHistory, monthLabel, Pack, WANT } from './engine.js?v=e4ba81ff0d';

const $ = (s) => document.querySelector(s);
let META = null;
const metaReady = fetch('data/meta.json?v=e4ba81ff0d').then((r) => r.json()).then((m) => (META = m));
const fetchIndex = () => fetch('data/index.bin?v=e4ba81ff0d').then((r) => r.arrayBuffer());
const fetchBloom = () => fetch('data/slots.bloom?v=e4ba81ff0d').then((r) => r.arrayBuffer());   // packs filed by artist (meta.slots)
async function fetchRange(file, start, end) {
  const r = await fetch(`data/p/${String(file).padStart(2, '0')}.bin?v=e4ba81ff0d`, { headers: { Range: `bytes=${start}-${end}` }, cache: 'no-store' });   // no-store: Chrome lets one request at a time write a file to its cache, so cached ranges of the same file queue up (3x slower)
  const b = new Uint8Array(await r.arrayBuffer());
  return r.status === 206 ? b : b.subarray(start, end + 1);   // a server without range support sends the whole file
}

// ---------- input
async function readEntries(entry, out) {
  if (entry.isFile) { if (/\.(zip|json|html)$/i.test(entry.name)) { const f = await new Promise((res, rej) => entry.file(res, rej)); f._path = entry.fullPath; out.push(f); } return; }
  const reader = entry.createReader(); let batch;
  do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); for (const e of batch) await readEntries(e, out); } while (batch.length);
}
function status(msg, { err = false, progress = null } = {}) {
  const s = $('#status'); s.hidden = false; s.classList.toggle('error', err);
  s.innerHTML = `<div></div>${progress === null ? '' : '<div class="bar"><i></i></div>'}`;
  s.firstChild.textContent = msg;
  if (progress !== null) s.querySelector('.bar i').style.width = `${Math.round(progress * 100)}%`;
}
const inFolder = (f) => f._path || f.webkitRelativePath || '';   // from a folder, open only Spotify histories and YouTube files (a full Takeout holds much else)
const usable = (fs) => [...fs].filter((f) => /\.zip$/i.test(f.name) || (/\.(json|html)$/i.test(f.name) && (!inFolder(f) || WANT(inFolder(f)))));
const SRC = { spotify: { label: 'Spotify', files: [] }, youtube: { label: 'YouTube', files: [] } };
function showSources() {
  for (const [k, v] of Object.entries(SRC)) {
    const el = document.querySelector(`.drop[data-src="${k}"]`), st = el.querySelector('.src-state');
    el.classList.toggle('has', v.files.length > 0);
    st.innerHTML = v.files.length ? `✓ ${v.files.length === 1 ? esc(v.files[0].name) : `${v.files.length} files`} <a href="#" data-clear="${k}">remove</a>` : 'Not added';
  }
  document.querySelectorAll('[data-clear]').forEach((x) => (x.onclick = (e) => { e.preventDefault(); e.stopPropagation(); SRC[x.dataset.clear].files = []; showSources(); }));
  $('#run').disabled = !SRC.spotify.files.length && !SRC.youtube.files.length;
}
function addFiles(k, fs) {
  const got = usable(fs);
  if (!got.length) return status(k === 'spotify' ? 'No Spotify files found there. Look for Streaming_History_Audio_….json, or the zip that contains them.'
    : 'No YouTube files found there. Look for the Google Takeout zip, MyActivity.html or watch-history.html.', { err: true });
  // each pick adds to what's there (Google can split one export into several zips or folders); the same file twice counts once
  const id = (f) => `${f.webkitRelativePath || f.name}|${f.size}|${f.lastModified}`, seen = new Set(SRC[k].files.map(id));
  $('#status').hidden = true; SRC[k].files = [...SRC[k].files, ...got.filter((f) => !seen.has(id(f)) && seen.add(id(f)))]; showSources();
}
for (const el of document.querySelectorAll('.drop[data-src]')) {
  const k = el.dataset.src;
  ['dragenter', 'dragover'].forEach((t) => el.addEventListener(t, (e) => { e.preventDefault(); el.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => el.addEventListener(t, (e) => { e.preventDefault(); el.classList.remove('over'); }));
  el.addEventListener('drop', async (e) => {
    const items = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (items.length) { const files = []; for (const it of items) await readEntries(it, files); addFiles(k, files); } else addFiles(k, [...e.dataTransfer.files]);
  });
  el.querySelectorAll('input[type=file]').forEach((inp) => inp.addEventListener('change', (e) => { addFiles(k, [...e.target.files]); e.target.value = ''; }));
}

// score every combination given (both together, and each alone when there are two), sharing one cache of reference lookups
let VIEWS = [];
async function run(sources = SRC) {
  const given = Object.entries(sources).filter(([, v]) => v.files.length);
  if (!given.length) return;
  const combos = given.length > 1 ? [['both', 'Spotify + YouTube', given.flatMap(([, v]) => v.files)], ...given.map(([k, v]) => [k, `${v.label} only`, v.files])]
    : [[given[0][0], given[0][1].label, given[0][1].files]];
  try {
    $('#report').hidden = true;
    status('Reading your files…');
    await metaReady;
    const pack = new Pack(META, fetchIndex, fetchRange, fetchBloom);
    VIEWS = [];
    for (const [i, [key, label, fs]] of combos.entries()) {
      const msg = `Looking up the music you got into${combos.length > 1 ? ` (${label}, ${i + 1} of ${combos.length})` : ''}…`;
      status(msg, { progress: 0 });
      const data = await Promise.all(fs.map(async (f) => (/\.zip$/i.test(f.name) ? { name: f.name, blob: f } : { name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) })));   // zips are read in pieces
      VIEWS.push({ key, label, r: await scoreHistory(data, META, pack, (x) => status(msg, { progress: x })) });
    }
    const first = VIEWS.find((v) => v.r.ok);
    if (!first) return status(VIEWS.map((v) => (VIEWS.length > 1 ? `${v.label}: ` : '') + ((v.r.checks || []).filter((c) => !c.ok).map((c) => c.text).join(' ') || "we couldn't score these files.")).join(' '), { err: true });
    $('#status').hidden = true;
    show(first.key, true);
  } catch (e) { console.error(e); status(`Something went wrong reading these files: ${e.message || e}`, { err: true }); }
}
$('#run').addEventListener('click', () => run());
function show(key, scroll = false) {
  const v = VIEWS.find((x) => x.key === key);
  render(v.r, scroll);
  if (VIEWS.length < 2) return;
  const why = (x) => esc((x.r.checks || []).filter((c) => !c.ok).map((c) => c.text).join(' '));
  $('#report').insertAdjacentHTML('afterbegin', `<div class="views"><span class="label">Scored from</span>${VIEWS.map((x) => x.r.ok
    ? `<button class="btn small${x.key === key ? '' : ' ghost'}" data-view="${x.key}">${x.label} · ${x.r.measures[x.r.headline].percentile}%</button>`
    : `<button class="btn small ghost" disabled title="${why(x)}">${x.label} · can't score</button>`).join('')}</div>`);
  document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => show(b.dataset.view)));
}

// ---------- formatting
const pct = (x, d = 0) => (x >= 0 ? '+' : '−') + Math.abs(100 * x).toFixed(d) + '%';
const ord = (n) => { n = Math.round(n); const s = (n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'); return n + s; };
const n = (x) => Math.round(x).toLocaleString();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const cls = (x) => (x >= 0 ? 'pos' : 'neg');
const card = (title, sub, body) => `<section class="card"><h2>${title}</h2>${sub ? `<p class="sub">${sub}</p>` : ''}${body}</section>`;
const tier = (p) => (p >= 90 ? 'Trendsetter' : p >= 75 ? 'Ahead of the curve' : p >= 50 ? 'Good ear' : p >= 25 ? 'In the mix' : 'Following the crowd');
const MEAS = {
  song_A: { title: 'Finding songs before they take off', short: 'Songs that take off', what: 'songs', verb: 'gained', of: 'new listeners than similar songs found the same month' },
  song_D: { title: 'Finding songs people stick with', short: 'Songs people stick with', what: 'songs', verb: 'kept', of: 'more of the people who tried them than similar songs' },
  artist_A: { title: 'Finding artists before they take off', short: 'Artists that take off', what: 'artists', verb: 'gained', of: 'new listeners than similar artists found the same month' },
  artist_D: { title: 'Finding artists people stick with', short: 'Artists people stick with', what: 'artists', verb: 'kept', of: 'more of the people who tried them than similar artists' },
};
const songsWord = (m) => `${n(m.items ? m.items.length : m.picks)} songs`;
const groupNote = (m) => ` (${n(m.picks)} independent finds: songs by one artist found in the same month count as one)`;
const win = (m) => (m.window ? `${monthLabel(m.window[0])} – ${monthLabel(m.window[1])}` : '');

function distChart(score, lo, hi, ref) {
  const W = 460, H = 130, pad = 18;
  const qs = (p) => ref[Math.min(ref.length - 1, Math.max(0, Math.round(p * (ref.length - 1))))];
  const L = Math.min(qs(0.01), score), U = Math.max(qs(0.99), score), bins = 48, bw = (U - L) / bins, cnt = new Array(bins).fill(0);
  for (const v of ref) if (v >= L && v <= U) cnt[Math.min(bins - 1, Math.floor((v - L) / bw))]++;
  const max = Math.max(...cnt), x = (v) => pad + (Math.min(U, Math.max(L, v)) - L) / (U - L) * (W - 2 * pad), base = H - 22;
  const bars = cnt.map((c, i) => `<rect class="barref" x="${x(L + i * bw) + 0.5}" y="${base - c / max * (base - 22)}" width="${(W - 2 * pad) / bins - 1}" height="${c / max * (base - 22)}"/>`).join('');
  const med = qs(0.5);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Your score among reference listeners">
    <rect class="bandref" x="${x(lo)}" y="18" width="${Math.max(2, x(hi) - x(lo))}" height="${base - 18}" rx="3"/>${bars}
    <line class="axis" x1="${pad}" x2="${W - pad}" y1="${base}" y2="${base}"/>
    <text x="${pad}" y="${H - 6}">worse finds</text><text x="${x(med)}" y="${H - 6}" text-anchor="middle">typical</text><text x="${W - pad}" y="${H - 6}" text-anchor="end">better finds</text>
    <line class="you" x1="${x(score)}" x2="${x(score)}" y1="14" y2="${base}"/><text class="youlabel" x="${x(score)}" y="11" text-anchor="middle">you</text></svg>`;
}
function signedBars(items) {
  const m = Math.max(0.02, ...items.filter((i) => i.v !== null).map((i) => Math.abs(i.v)));
  return `<table class="sbars">${items.map((i) => `<tr><td style="width:42%">${i.label}</td><td>${i.v === null ? '<span class="muted">too few</span>' : `<div class="impact"><div class="track">
    <div class="fill ${cls(i.v)}" style="${i.v >= 0 ? 'left:50%' : 'right:50%'};width:${Math.abs(i.v) / m * 50}%"></div></div><span class="val ${cls(i.v)}">${pct(i.v)}</span></div>`}</td>
    <td class="num muted">${i.note || ''}</td></tr>`).join('')}</table>`;
}
function rangeBar(m) {   // a small 0-100 bar with the likely range and the point
  if (!m.enough) return '<span class="muted">not enough finds yet</span>';
  return `<div class="rbar"><i style="left:${m.range[0]}%;width:${m.range[1] - m.range[0]}%"></i><b style="left:${m.percentile}%"></b></div>`;
}

// ---------- report
function render(r, scroll = true) {
  const M = r.measures, H = M[r.headline], hm = MEAS[r.headline], Rp = r.report;
  const ref = META.measures[r.headline].scores;
  const qs = (p) => ref[Math.min(ref.length - 1, Math.max(0, Math.round(p / 100 * (ref.length - 1))))];
  const warn = (r.checks || []).filter((c) => c.warn).map((c) => `<p class="warnline">${esc(c.text)}</p>`).join('');
  const hero = `<section class="card"><div class="hero">
      <div><span class="tier">${tier(H.percentile)}</span>
        <div class="big">${H.percentile}%<small>of listeners beaten</small></div>
        <p class="meaning">You're better than <b>${H.percentile}%</b> of listeners at <b>${hm.title.toLowerCase()}</b>. The ${hm.what} you got into ${hm.verb}
          <b class="${cls(H.growth)}">${pct(H.growth, 1)}</b> ${hm.of}.</p>
        <p class="meaning">Your true rank is most likely between the <b>${ord(H.range[0])}</b> and <b>${ord(H.range[1])}</b> percentile (80% confidence interval).</p>${warn}</div>
      <div>${distChart(H.score, qs(H.range[0]), qs(H.range[1]), ref)}
        <p class="note">Gray bars: ${n(ref.length)} ListenBrainz listeners scored the same way. Blue band: your likely range (80% confidence interval). Based on ${hm.what === 'songs' ? songsWord(H) : `${n(H.picks)} artists`} you got into, ${win(H)}${hm.what === 'songs' ? groupNote(H) : ''}.</p></div>
    </div></section>`;

  const F = Rp.facts;
  const facts = `<div class="facts" style="margin:16px 0">
    <div class="fact"><b>${n(F.plays)} plays</b><span>over ${F.years} years${F.ytPlays && F.ytPlays < F.plays ? ` (${n(F.ytPlays)} on YouTube)` : ''}</span></div>
    <div class="fact"><b>${n(F.findsS)} songs</b><span>you really got into (played in 4+ separate weeks, the 4th within 6 months of first hearing)${M.song_A.items ? `; ${n(M.song_A.items.length)} matched and scored` : ''}</span></div>
    <div class="fact"><b>${n(F.findsA)} artists</b><span>you really got into (about ${F.perYear} a year; same rule, any of their songs)${M.artist_A.picks ? `; ${n(M.artist_A.picks)} matched and scored` : ''}</span></div>
    ${Rp.tookOff ? `<div class="fact"><b style="line-height:1.25">${Rp.tookOff.yours} took off <span style="font-size:15px;color:var(--ink-3)">vs ${Rp.tookOff.expected} typical</span></b><span>of your scored ${hm.what} (3× the new listeners a year later)</span></div>` : ''}
  </div>`;

  const pts = (x) => `${x >= 0 ? '+' : '−'}${Math.abs(100 * x).toFixed(1)} points`;
  const detail = (k) => {
    const m = M[k], d = MEAS[k], typ = META.measures[k].typical_avg, A = k.endsWith('A');
    if (!m.picks) return '<p class="muted">No finds we could judge.</p>';
    const yours = A ? `Your finds gained <b class="${cls(m.growth)}">${pct(m.growth, 1)}</b> new listeners compared with similar ${d.what} found the same month; the typical listener's finds: <b>${pct(Math.expm1(typ), 1)}</b>.`
      : `People who tried your finds kept playing them <b class="${cls(m.growth)}">${pts(m.growth)}</b> ${m.growth >= 0 ? 'more' : 'less'} often than for similar ${d.what}; for the typical listener's finds: <b>${pts(typ)}</b>.`;
    const line = (x) => `<tr><td class="artist" title="${esc(x.name)}">${esc(x.name)}${x.artist ? `<div class="muted" style="font-size:12.5px;font-weight:400">${esc(x.artist)}</div>` : ''}</td>
      <td class="muted nowrap">${x.found}</td>
      <td class="num nowrap">${A ? `${n(x.a0)} → ${n(x.a1)}` : `${n(x.kept)} of ${n(x.tried)} kept it`}</td>
      <td class="num nowrap ${cls(x.excess)}">${A ? pct(Math.expm1(x.excess)) : pts(x.excess)}</td></tr>`;
    const best = m.items.slice(0, 5), worst = m.items.slice(-5).reverse();
    return `<p style="margin:4px 0 10px">${yours} Based on ${k.startsWith('song') ? songsWord(m) : `${n(m.picks)} artists`} you got into${m.window ? `, ${win(m)}` : ''}${k.startsWith('song') ? groupNote(m) : ''}${m.enough ? '' : `; we need ${META.min_picks} for a score`}.</p>
      <div class="tablewrap"><table class="bw">
        <tr><th>Your best ${d.what}</th><th>Found</th><th class="num">${A ? 'New listeners then → a year later' : 'Of those who tried it'}</th><th class="num">vs similar</th></tr>${best.map(line).join('')}
        <tr><th style="padding-top:16px">Your worst ${d.what}</th><th></th><th></th><th></th></tr>${worst.map(line).join('')}</table></div>
      <p class="note">${A ? 'New listeners: ListenBrainz listeners who first played it in the six months up to your find, and in the same six months a year later. The last column is compared with similar finds (same month, size, momentum, scene, age and release timing).'
        : 'Of the people who first tried it in the year after your find (past their own first six months of listening), how many kept playing it. The last column is compared with similar finds.'}</p>`;
  };
  const all = card('All four kinds of taste', 'The study measured taste a few ways; these are the ones we can score from a listening history. Songs are the strongest measure. Click a row for your numbers and your best and worst finds.',
    `<table class="mtable"><tr><th></th><th class="num">Better than</th><th>Likely range</th><th class="num hide-sm">Finds</th></tr>
    ${Object.entries(MEAS).map(([k, d]) => { const m = M[k]; return `<tr class="mrow${k === r.headline ? ' hl' : ''}" data-k="${k}" style="cursor:pointer"><td><b>${d.short}</b> <span class="muted">▸</span><div class="muted" style="font-size:13px">${k.endsWith('A') ? 'Prescience: your finds gained new listeners' : 'Discernment: people who tried your finds kept playing them'}</div></td>
      <td class="num"><b>${m.enough ? m.percentile + '%' : '–'}</b></td><td style="min-width:140px">${rangeBar(m)}${m.enough ? `<div class="muted" style="font-size:12.5px">${ord(m.range[0])}–${ord(m.range[1])}</div>` : ''}</td>
      <td class="num hide-sm muted">${n(m.picks)}</td></tr><tr class="mdetail" data-k="${k}" hidden><td colspan="4">${detail(k)}</td></tr>`; }).join('')}</table>`);

  const G = Rp.genres.filter((g) => g.finds > 0 || g.typical > 0.03);
  const gmax = Math.max(...G.map((g) => Math.max(g.share, g.typical || 0)), 0.01);
  const genres = card('Your genres', `Genres of the ${hm.what} you got into (from MusicBrainz tags of the artist), compared with the typical mix among other listeners' finds, and how your finds did in each.`,
    `<div class="tablewrap"><table><tr><th>Genre</th><th>Your mix <span class="muted">(gray: typical)</span></th><th class="num">How your finds did</th><th class="num hide-sm">Finds</th></tr>
    ${G.map((g) => `<tr><td>${esc(g.name === 'Other' ? 'Other or untagged' : g.name)}</td><td style="min-width:160px"><div class="mix"><i class="you" style="width:${g.share / gmax * 100}%"></i><i class="typ" style="width:${(g.typical || 0) / gmax * 100}%"></i></div>
      <span class="muted" style="font-size:12.5px">${Math.round(g.share * 100)}% vs ${Math.round((g.typical || 0) * 100)}%</span></td>
      <td class="num ${g.growth === null ? 'muted' : cls(g.growth)}">${g.growth === null ? 'too few' : pct(g.growth)}</td><td class="num hide-sm muted">${n(g.finds)}</td></tr>`).join('')}</table></div>`);

  const A = Rp.ahead;
  const ahead = A.share === null ? '' : card('Ahead of the crowd', null, `<div class="big">${Math.round(A.share * 100)}%</div>
    <p class="meaning">On average, ${Math.round(A.share * 100)}% of each artist's ListenBrainz fans got into them <b>after</b> you did (across ${n(A.artists)} artists that took off since 2015).</p>
    ${A.best.length ? `<div class="calls">${A.best.map((b) => `<div class="call"><b>${esc(b.name)}</b><span>you got into them in ${monthLabel(b.m)},<br>before ${Math.round(b.share * 100)}% of their ${n(b.fans)} fans</span></div>`).join('')}</div>` : ''}`);
  const sure = card('How sure is this?', null, `<div class="facts">
    <div class="fact"><b>${n(H.picks)}</b><span>${hm.what === 'songs' ? `independent song finds scored (from ${n(H.items.length)} songs; songs by one artist found in the same month count as one)` : 'artists scored'} (all your judged finds since 2016)</span></div>
    <div class="fact"><b>${ord(H.range[0])}–${ord(H.range[1])}</b><span>likely range of your rank (80%)</span></div>
    <div class="fact"><b>${H.reliability.toFixed(2)}</b><span>reliability with this much history (1 = perfectly repeatable)</span></div>
    <div class="fact"><b>${Math.round(r.history.matched.songs * 100)}% / ${Math.round(r.history.matched.artists * 100)}%</b><span>of your songs / artists were in the reference data</span></div></div>
    <p class="note">Any single find is mostly luck, so a score built from a few hundred is fuzzy; more history narrows the range. Taste also drifts:
      in the study, good taste faded over about a decade, so see how yours changed under Your taste over time.</p>`);
  const where = Rp.edge ? card('Where your edge comes from', 'Part of a score comes from being into scenes that were about to grow; the rest from picking better artists than others in the same scene. Your score counts only the second.',
    signedBars([{ label: 'Being in rising scenes', v: Rp.edge.scenes }, { label: 'Picking well within your scenes', v: Rp.edge.within }])) : '';
  const conv = card('Conviction', 'Artists you got into, grouped by how many times you played them in their first six months.',
    signedBars(Rp.conviction.map((c) => ({ label: `${c.label} <span class="muted">(${c.hi === null ? c.lo + '+' : c.lo + '–' + c.hi})</span>`, v: c.finds >= 5 ? c.growth : null, note: `${n(c.finds)} artists` }))));
  const years = `<section class="card"><h2>Your taste over time</h2>
    <p class="sub">Your percentile from each year's finds, with its likely range (years with fewer than 5 finds aren't scored; hollow points have under ${META.min_year}, so their ranges are wide). Single years rest on fewer finds,
      so their ranges are wider. Taste drifts: in the study, it faded over about a decade.</p>
    <div class="tablebar" id="tchips"></div><div id="tchart"></div><p class="note" id="tnote"></p></section>`;
  const how = Rp.how.length > 1 ? card('How you found them', 'How the first play of each artist started.',
    signedBars(Rp.how.map((h) => ({ label: h.label, v: h.finds >= 5 ? h.growth : null, note: `${n(h.finds)} artists` })))) : '';

  const big = [...Rp.findsA].sort((a, b) => b.extra - a.extra).slice(0, 10);
  const bigT = card('Biggest finds', 'Artists you got into that gained the most new listeners beyond what was typical for similar artists, in the year after.', `<div class="tablewrap"><table>
    <tr><th>Artist</th><th>Found</th><th class="num">New listeners then → a year later</th><th class="num hide-sm">Typical</th><th class="num">Beyond typical</th></tr>
    ${big.map((f) => `<tr><td class="artist" title="${esc(f.name)}">${esc(f.name)}</td><td class="muted">${f.found}</td><td class="num nowrap">${n(f.a0)} → ${n(f.a1)}</td>
      <td class="num muted hide-sm">${n(f.a1 - f.extra)}</td><td class="num pos">+${n(f.extra)}</td></tr>`).join('')}</table></div>
    <p class="note">New listeners: ListenBrainz listeners who first played the artist in the six months up to when you got into them, and in the same six months a year later.</p>`);
  const openT = Rp.open.length ? card('Open bets', 'Your newest finds, too recent to score (each needs a year). How they are doing so far.', `<div class="tablewrap"><table>
    <tr><th>Artist</th><th>Found</th><th class="num">New listeners then → lately</th><th class="num">So far</th><th class="num hide-sm">Your plays</th></tr>
    ${Rp.open.map((o) => `<tr><td class="artist">${esc(o.name)}</td><td class="muted">${o.found}</td><td class="num nowrap">${n(o.then)} → ${o.now === null ? '…' : n(o.now)}</td>
      <td class="num ${o.now === null ? 'muted' : cls(o.now - o.then)}">${o.now === null ? 'too new' : pct((o.now + 1) / (o.then + 1) - 1)}</td><td class="num hide-sm">${o.plays26}</td></tr>`).join('')}</table></div>`) : '';

  const NC = Rp.notCounted, reasons = [
    ['Only tried', NC.tried, 'Played in fewer than four separate weeks, or not four weeks within six months of first hearing them. A find counts once you play it in four different weeks.'],
    ['Warm-up', NC.warmup, 'First heard in your first six months of history: when a history starts, music you already loved shows up as "new". Reference listeners get the same warm-up.'],
    ['Too recent to judge', NC.tooRecent, 'Found less than a year before the reference data ends, so there\'s no year of follow-up yet. See Open bets.'],
    ['Not in the reference data', NC.unrecognised, 'Too few ListenBrainz listeners ever played them, or the name is spelled differently there.'],
    ['Before 2016', NC.early, 'The reference data for scoring starts in 2016.'],
  ].filter(([, l]) => l.length);
  const ncT = card('Not counted (artists)', 'The rest of your history, and why it isn\'t in the artist scores.', `<div class="reasons">
    ${reasons.map(([t, l, why]) => `<details><summary><b>${n(l.length)}</b> ${t}</summary><p class="why">${why}</p><div class="list">${l.slice(0, 300).map((d) => esc(d)).join('<br>')}${l.length > 300 ? `<br>… and ${n(l.length - 300)} more` : ''}</div></details>`).join('')}</div>`);

  const howScore = `<details class="howto" style="margin-top:16px"><summary>How your score works</summary>
    <p>A <b>find</b> is a song or artist you played in at least four separate weeks, the fourth within six months of first hearing it; your first six months of history are skipped.
      For each find we check what happened next on ListenBrainz, compared with other people's finds of songs or artists that were just as small that month, allowing for the
      things that aren't taste (a scene that was growing anyway, an artist already rising, a new release, how new the music was, where the artist is from). Songs by one artist that
      you found the same month count once.</p>
    <p><b>Prescience</b>: how many new listeners your finds gained over the next year. <b>Discernment</b>: how many of the people who tried your finds over the next year kept
      playing them. Your score is the average over all your judged finds since 2016, ranked against ListenBrainz listeners scored exactly the same way, with a range for how sure we can be.
      On ListenBrainz these scores agree closely with the study's own measures. <a href="study.html">Read the study</a>.</p></details>`;

  $('#report').innerHTML = hero + `<h2 style="margin:28px 0 4px">Explore more</h2>` + facts + all + genres + `<div class="cols">${ahead}${sure}</div>`
    + `<div class="cols">${where}${conv}</div>` + years + (how ? `<div class="cols">${how}</div>` : '') + picksCard() + bigT + openT + ncT + howScore
    + `<p class="note" style="text-align:center"><a href="study.html">Is good taste real? The study</a> · <a href="#" id="again">Score another history</a></p>`;
  $('#report').hidden = false;
  wirePicks(Rp);
  wireTime(M, r.headline);
  document.querySelectorAll('tr.mrow').forEach((tr) => (tr.onclick = () => {
    const d = document.querySelector(`tr.mdetail[data-k="${tr.dataset.k}"]`); d.hidden = !d.hidden;
    tr.querySelector('.muted').textContent = d.hidden ? '▸' : '▾';
  }));
  $('#again').onclick = (e) => { e.preventDefault(); $('#report').hidden = true; window.scrollTo(0, 0); };
  if (scroll) $('#report').scrollIntoView();
}

// every scored find, by impact (songs or artists)
let sortKey = 'impact', sortDir = -1, filter = '', showAll = false, mode = 'songs';
function picksCard() {
  return `<section class="card"><h2>Every find, by impact</h2>
    <p class="sub">How much each find moved your prescience score; together they add up to it. A find helps when it gained more new listeners than similar finds
      the same month (same size, momentum, scene, age and release timing).</p>
    <div class="tablebar"><button id="mode-songs" class="btn small"></button><button id="mode-artists" class="btn small ghost"></button>
      <input id="pick-filter" placeholder="Find…" autocomplete="off"><button id="pick-all" class="btn small ghost"></button></div>
    <div class="tablewrap"><table id="pick-table"></table></div></section>`;
}
function wirePicks(Rp) {
  const tbl = $('#pick-table');
  function draw() {
    const A = mode === 'songs' ? Rp.findsS : Rp.findsA;
    $('#mode-songs').textContent = `Songs (${n(Rp.findsS.length)})`; $('#mode-artists').textContent = `Artists (${n(Rp.findsA.length)})`;
    $('#mode-songs').className = `btn small${mode === 'songs' ? '' : ' ghost'}`; $('#mode-artists').className = `btn small${mode === 'artists' ? '' : ' ghost'}`;
    const maxC = Math.max(1e-9, ...A.map((x) => Math.abs(x.impact)));
    const rank = new Map([...A].sort((a, b) => b.impact - a.impact).map((x, i) => [x, i + 1]));
    const cols = [['impact', 'Impact', ''], ['name', mode === 'songs' ? 'Song' : 'Artist', ''], ['m', 'Found', ''], ['a0', 'New listeners then → a year later', 'num'], ['vs', 'vs similar', 'num'], ['plays26', 'Your plays', 'num hide-sm']];
    const row = (x) => `<tr><td><div class="impact"><span class="muted" style="width:34px;text-align:right">${rank.get(x)}</span><div class="track"><div class="fill ${cls(x.impact)}" style="${x.impact >= 0 ? 'left:50%' : 'right:50%'};width:${Math.abs(x.impact) / maxC * 50}%"></div></div></div></td>
      <td class="artist" title="${esc(x.name)}${x.artist ? ' — ' + esc(x.artist) : ''}">${esc(x.name)}${x.artist ? `<div class="muted" style="font-size:12.5px;font-weight:400">${esc(x.artist)}</div>` : ''}</td>
      <td class="muted nowrap">${x.found}</td><td class="num nowrap">${n(x.a0)} → ${n(x.a1)}</td><td class="num ${cls(x.vs)}">${pct(x.vs)}</td><td class="num hide-sm">${x.plays26}</td></tr>`;
    let ps = [...A].sort((a, b) => { const x = a[sortKey], y = b[sortKey]; return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sortDir; });
    if (filter) ps = ps.filter((x) => (x.name + ' ' + (x.artist || '')).toLowerCase().includes(filter));
    const head = `<tr>${cols.map(([k, t, c]) => `<th class="sortable ${c}" data-k="${k}">${t}${sortKey === k ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr>`;
    const body = (showAll || filter || ps.length <= 60) ? ps.map(row).join('')
      : ps.slice(0, 25).map(row).join('') + `<tr class="gapline"><td colspan="6">${n(ps.length - 50)} more</td></tr>` + ps.slice(-25).map(row).join('');
    tbl.innerHTML = head + body;
    $('#pick-all').textContent = showAll ? 'Show top and bottom 25' : `Show all ${n(A.length)}`;
    $('#pick-all').hidden = !!filter || A.length <= 60;
    tbl.querySelectorAll('th.sortable').forEach((th) => (th.onclick = () => { const k = th.dataset.k; if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === 'name' || k === 'm' ? 1 : -1; } draw(); }));
  }
  $('#mode-songs').onclick = () => { mode = 'songs'; draw(); };
  $('#mode-artists').onclick = () => { mode = 'artists'; draw(); };
  $('#pick-filter').oninput = (e) => { filter = e.target.value.trim().toLowerCase(); draw(); };
  $('#pick-all').onclick = () => { showAll = !showAll; draw(); };
  draw();
}

window.__render = (r) => { META = META || window.__meta; render(r); };   // local page tests
window.__run = (sources) => run(sources);

// your taste over time: yearly percentile with its range, one measure at a time
function wireTime(M, head) {
  let cur = head;
  const draw = () => {
    $('#tchips').innerHTML = Object.entries(MEAS).map(([k, d]) => `<button class="btn small${k === cur ? '' : ' ghost'}" data-k="${k}">${d.short}</button>`).join('');
    $('#tchips').querySelectorAll('button').forEach((b) => (b.onclick = () => { cur = b.dataset.k; draw(); }));
    const ys = (M[cur].years || []), sc = ys.filter((y) => y.percentile !== undefined);
    const el = $('#tchart'), W = Math.max(320, Math.min(900, el.clientWidth || 700)), H = 260, pad = { l: 40, r: 34, t: 24, b: 44 };
    if (!ys.length) { el.innerHTML = '<p class="muted">No judged finds.</p>'; return; }
    const y0 = ys[0].year, y1 = ys[ys.length - 1].year;
    const X = (y) => pad.l + (y1 === y0 ? 0.5 : (y - y0) / (y1 - y0)) * (W - pad.l - pad.r), Y = (v) => pad.t + (1 - v / 100) * (H - pad.t - pad.b);
    let g = [0, 25, 50, 75, 100].map((t) => `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${pad.l - 6}" y="${Y(t) + 4}" text-anchor="end">${t}</text>`).join('');
    g += `<line class="ref" x1="${pad.l}" x2="${W - pad.r}" y1="${Y(50)}" y2="${Y(50)}"/>`;
    ys.forEach((y) => { g += `<text x="${X(y.year)}" y="${H - 24}" text-anchor="middle">${y.year}</text><text x="${X(y.year)}" y="${H - 9}" text-anchor="middle" style="font-size:11px">${y.finds} finds</text>`; });
    if (sc.length) {
      g += `<path d="M${sc.map((y) => `${X(y.year)},${Y(y.range[1])}`).join('L')}L${[...sc].reverse().map((y) => `${X(y.year)},${Y(y.range[0])}`).join('L')}Z" class="bandref" opacity="0.8"/>`;
      g += `<path d="M${sc.map((y) => `${X(y.year)},${Y(y.percentile)}`).join('L')}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>`;
      g += `<text x="${pad.l + 4}" y="${Y(50) - 5}" style="fill:var(--ink-2)">average</text>`;
      g += sc.map((y) => `<circle cx="${X(y.year)}" cy="${Y(y.percentile)}" r="4" fill="${y.few ? 'var(--surface)' : 'var(--accent)'}" stroke="var(--accent)" stroke-width="${y.few ? 2 : 0}"><title>${y.year}: better than ${y.percentile}% (likely ${ord(y.range[0])}–${ord(y.range[1])}), ${y.finds} finds${y.few ? ' (few finds, wide range)' : ''}</title></circle>
        <text x="${X(y.year)}" y="${Y(y.percentile) - 9}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${y.percentile}</text>`).join('');
    }
    el.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="Your percentile by year">${g}</svg>`;
    const few = ys.filter((y) => y.percentile === undefined).map((y) => y.year);
    const thin = sc.filter((y) => y.few).map((y) => y.year);
    $('#tnote').textContent = `Percentile among ListenBrainz listeners' years with at least ${META.min_year} finds. Blue band: likely range.`
      + (thin.length ? ` Hollow points (${thin.join(', ')}): fewer than ${META.min_year} finds that year, so the range is wide.` : '') + (few.length ? ` Too few finds to score (under 5): ${few.join(', ')}.` : '');
  };
  draw();
}
