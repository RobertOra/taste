// Taste Test scoring engine (runs in the browser, and in Node for tests). Mirrors site/score_static.py exactly.
// Prescience for artists: do the artists you got into go on to gain new listeners, compared with similar picks the same
// month (same size), with the project's corrections (momentum, scene, artist age, release timing, country).
// Reference data: data/meta.json and data/s/XXXX.bin (site/build_static.py).

const WEEK = 604800;
export const RULES = { minPlayMs: 30000, onboardWeeks: 26, windowWeeks: 26, minWeeks: 4, minHistoryWeeks: 104, minMatch: 0.4, warnMatch: 0.6 };
const EXCLUDE = new Set(['various artists', 'unknown artist', '']);

export function monthOfWeek(w) { const d = new Date((w * WEEK + 302400) * 1000); return d.getUTCFullYear() * 12 + d.getUTCMonth(); }
export function monthLabel(m) { return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m % 12]} ${Math.floor(m / 12)}`; }

// ---------- BLAKE2b (digest 8 bytes), as Python hashlib.blake2b(s, digest_size=8); BigInt arithmetic
const M64 = (1n << 64n) - 1n;
const IV = [0x6a09e667f3bcc908n, 0xbb67ae8584caa73bn, 0x3c6ef372fe94f82bn, 0xa54ff53a5f1d36f1n, 0x510e527fade682d1n, 0x9b05688c2b3e6c1fn,
  0x1f83d9abfb41bd6bn, 0x5be0cd19137e2179n];
const SIGMA = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4], [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13], [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11], [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5], [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0]];
const rotr = (x, n) => ((x >> n) | (x << (64n - n))) & M64;
function compress(h, block, t, last) {
  const v = [...h, ...IV];
  v[12] ^= t & M64; v[13] ^= (t >> 64n) & M64;
  if (last) v[14] ^= M64;
  const m = [];
  for (let i = 0; i < 16; i++) { let x = 0n; for (let j = 7; j >= 0; j--) x = (x << 8n) | BigInt(block[i * 8 + j]); m.push(x); }
  const G = (a, b, c, d, x, y) => {
    v[a] = (v[a] + v[b] + x) & M64; v[d] = rotr(v[d] ^ v[a], 32n);
    v[c] = (v[c] + v[d]) & M64; v[b] = rotr(v[b] ^ v[c], 24n);
    v[a] = (v[a] + v[b] + y) & M64; v[d] = rotr(v[d] ^ v[a], 16n);
    v[c] = (v[c] + v[d]) & M64; v[b] = rotr(v[b] ^ v[c], 63n);
  };
  for (let r = 0; r < 12; r++) {
    const s = SIGMA[r % 10];
    G(0, 4, 8, 12, m[s[0]], m[s[1]]); G(1, 5, 9, 13, m[s[2]], m[s[3]]); G(2, 6, 10, 14, m[s[4]], m[s[5]]); G(3, 7, 11, 15, m[s[6]], m[s[7]]);
    G(0, 5, 10, 15, m[s[8]], m[s[9]]); G(1, 6, 11, 12, m[s[10]], m[s[11]]); G(2, 7, 8, 13, m[s[12]], m[s[13]]); G(3, 4, 9, 14, m[s[14]], m[s[15]]);
  }
  for (let i = 0; i < 8; i++) h[i] = h[i] ^ v[i] ^ v[i + 8];
}
const enc = new TextEncoder();
export function nameHash(s) {   // signed 64-bit BigInt of blake2b-8 digest read big-endian
  const data = enc.encode(s), outlen = 8;
  const h = IV.slice(); h[0] ^= 0x01010000n ^ BigInt(outlen);
  let t = 0n, i = 0;
  if (data.length === 0) { compress(h, new Uint8Array(128), 0n, true); }
  while (i < data.length) {
    const n = Math.min(128, data.length - i), block = new Uint8Array(128); block.set(data.subarray(i, i + n));
    i += n; t += BigInt(n);
    compress(h, block, t, i >= data.length);
  }
  let x = 0n; for (let j = 0; j < 8; j++) x = (x << 8n) | ((h[0] >> BigInt(8 * j)) & 0xffn);   // first 8 output bytes, little-endian words
  return BigInt.asIntN(64, x);
}

// ---------- reading Spotify exports (JSON, or a .zip of them)
async function inflateRaw(bytes) {
  const ds = new DecompressionStream('deflate-raw');
  const out = await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer();
  return new Uint8Array(out);
}
export async function unzip(bytes) {   // -> [{name, bytes}] for .json entries
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('not a zip file');
  const n = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true);
  const dec = new TextDecoder(), out = [];
  for (let k = 0; k < n; k++) {
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nlen = dv.getUint16(p + 28, true);
    const xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true), loff = dv.getUint32(p + 42, true);
    const name = dec.decode(bytes.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (!name.toLowerCase().endsWith('.json')) continue;
    const lstart = loff + 30 + dv.getUint16(loff + 26, true) + dv.getUint16(loff + 28, true);
    const raw = bytes.subarray(lstart, lstart + csize);
    out.push({ name, bytes: method === 0 ? raw : await inflateRaw(raw) });
  }
  return out;
}
export async function readHistory(files) {   // files: [{name, bytes}] -> {plays: [{week, an, name}], kind, tsMin, tsMax}
  const dec = new TextDecoder(); const got = { extended: [], standard: [] }; const kinds = new Set();
  const jsons = [];
  for (const f of files) {
    if (f.name.toLowerCase().endsWith('.zip')) jsons.push(...await unzip(f.bytes));
    else if (f.name.toLowerCase().endsWith('.json')) jsons.push(f);
  }
  for (const f of jsons) {
    let data; try { data = JSON.parse(dec.decode(f.bytes)); } catch { continue; }
    if (!Array.isArray(data)) continue;
    for (const d of data) {
      if (!d || typeof d !== 'object') continue;
      let ts, artist;
      if ('ts' in d && 'master_metadata_album_artist_name' in d) {
        kinds.add('extended');
        artist = d.master_metadata_album_artist_name;
        if (!artist || !d.master_metadata_track_name || (d.ms_played || 0) < RULES.minPlayMs) continue;
        ts = Date.parse(d.ts) / 1000;
      } else if ('endTime' in d && 'artistName' in d) {
        kinds.add('standard');
        if ((d.msPlayed || 0) < RULES.minPlayMs) continue;
        artist = d.artistName; ts = Date.parse(d.endTime.replace(' ', 'T') + ':00Z') / 1000;
      } else continue;
      if (!Number.isFinite(ts)) continue;
      const an = artist.trim().toLowerCase();
      if (EXCLUDE.has(an)) continue;
      got['ts' in d ? 'extended' : 'standard'].push({ week: Math.floor(ts / WEEK), an, name: artist, ts });
    }
  }
  const kind = kinds.has('extended') ? 'extended' : (kinds.size ? 'standard' : null);
  const plays = kind ? got[kind] : [];   // with both exports present, only the extended history counts (no double counting)
  let tsMin = Infinity, tsMax = -Infinity; for (const p of plays) { if (p.ts < tsMin) tsMin = p.ts; if (p.ts > tsMax) tsMax = p.ts; }
  return { plays, kind, tsMin, tsMax };
}

// ---------- picks (by artist name as Spotify gives it)
export function findPicks(plays) {
  let start = Infinity; for (const p of plays) if (p.week < start) start = p.week;
  const by = new Map();
  for (const p of plays) {
    let a = by.get(p.an); if (!a) { a = { an: p.an, name: p.name, weeks: new Map() }; by.set(p.an, a); }
    a.weeks.set(p.week, (a.weeks.get(p.week) || 0) + 1);
  }
  const picks = [];
  for (const a of by.values()) {
    const ws = [...a.weeks.keys()].sort((x, y) => x - y);
    if (ws.length < RULES.minWeeks) continue;
    const fw = ws[0], w4 = ws[RULES.minWeeks - 1];
    if (w4 - fw >= RULES.windowWeeks || fw < start + RULES.onboardWeeks) continue;
    let plays26 = 0; for (const [w, n] of a.weeks) if (w < fw + RULES.windowWeeks) plays26 += n;
    picks.push({ an: a.an, name: a.name, firstWeek: fw, w4, m: monthOfWeek(w4), plays26 });
  }
  return picks;
}

// ---------- reference data
function readVarint(b, o) { let x = 0, s = 0, c; do { c = b[o.p++]; x += (c & 0x7f) * 2 ** s; s += 7; } while (c & 0x80); return x; }
export function decodeShard(buf, meta) {
  const b = new Uint8Array(buf), dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const nNames = dv.getUint16(0, true), nArts = dv.getUint16(2, true);
  const names = new Map(); let p = 4;
  for (let i = 0; i < nNames; i++) { names.set(dv.getBigInt64(p, true), dv.getUint16(p + 8, true)); p += 10; }
  const arts = []; const o = { p };
  for (let i = 0; i < nArts; i++) {
    const id = dv.getUint32(o.p, true), country = meta.countries[dv.getUint16(o.p + 4, true)], fm = dv.getUint16(o.p + 6, true) - 1000 + 2000 * 12; o.p += 8;
    const adopt = new Map(); let k = readVarint(b, o), prev = meta.y0 - 12;
    for (let j = 0; j < k; j++) { prev += readVarint(b, o); adopt.set(prev, readVarint(b, o)); }
    const scene = new Map(); k = readVarint(b, o);
    for (let j = 0; j < k; j++) { const y = b[o.p++] + 2000, s = b[o.p++]; scene.set(y, s === 255 ? -1 : s); }
    const anyRel = b[o.p++] === 1; const rel = []; k = readVarint(b, o); prev = meta.y0 - 12;
    for (let j = 0; j < k; j++) { prev += readVarint(b, o); rel.push(prev); }
    arts.push({ id, country, fm, adopt, scene, anyRel, rel });
  }
  return { names, arts };
}

function features(art, m) {
  const sum = (lo, hi) => { let s = 0; for (let t = lo; t <= hi; t++) s += art.adopt.get(t) || 0; return s; };
  const a0 = sum(m - 5, m), a1 = sum(m + 7, m + 12), ap = sum(m - 11, m - 6);
  const d = m - art.fm;
  const age = art.fm <= 2005 * 12 ? 9 : d < 3 ? 0 : d < 6 ? 1 : d < 12 ? 2 : d < 24 ? 3 : 4;
  let relc = 4;
  if (art.anyRel) relc = 2 * (art.rel.some((r) => r > m && r <= m + 3) ? 1 : 0) + (art.rel.some((r) => r >= m - 3 && r <= m) ? 1 : 0);
  const sc = art.scene.has(Math.floor(m / 12)) ? art.scene.get(Math.floor(m / 12)) : -1;
  return { a0, a1, ap, age, relc, scene: sc, country: art.country };
}

function lookups(meta) {
  if (meta._lk) return meta._lk;
  const base = new Map(meta.baseline.map(([m, bin, g, ten, up3]) => [m * 16 + bin, { g, ten, up3 }]));
  const eff = {};
  for (const [name, rows] of Object.entries(meta.effects)) eff[name] = new Map(rows.map((r) => [r.slice(0, -1).join('|'), r[r.length - 1]]));
  meta._lk = { base, eff };
  return meta._lk;
}

export function excess(meta, f, m) {
  const { base, eff } = lookups(meta);
  const g = Math.log((f.a1 + 1) / (f.a0 + 1));
  const bin = Math.min(14, Math.max(0, Math.floor(Math.log(f.a0 + 1) / Math.log(2))));
  const mo = Math.min(3, Math.max(-3, Math.floor((Math.log((f.a0 + 1) / (f.ap + 1)) / Math.log(2)) / 0.5)));
  const b = base.get(m * 16 + bin);
  if (!b) return null;
  const year = Math.floor(m / 12);
  const e = (eff.mo.get(String(mo)) || 0) + (eff.year_scene.get(`${year}|${f.scene}`) || 0) + (eff.age.get(String(f.age)) || 0)
    + (eff.relc.get(String(f.relc)) || 0) + (eff.country.get(f.country) || 0);
  return { g, gMean: b.g, tenRate: b.ten, up3Rate: b.up3, excess: g - b.g - e, ten: g >= Math.log(10), up3: g >= Math.log(3) };
}

const NORM = { cdf: (x) => 0.5 * (1 + erf(x / Math.SQRT2)), inv: (p) => { let lo = -10, hi = 10; for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (NORM.cdf(mid) < p) lo = mid; else hi = mid; } return (lo + hi) / 2; } };
function erf(x) {   // Abramowitz-Stegun 7.1.26 refined by series; adequate for ranges shown as whole percentiles
  const s = Math.sign(x); x = Math.abs(x);
  if (x < 3) { let sum = x, term = x, n = 0; while (Math.abs(term) > 1e-16 * Math.abs(sum)) { n++; term *= -x * x / n; sum += term / (2 * n + 1); } return s * 2 / Math.sqrt(Math.PI) * sum; }
  const t = 1 / (1 + 0.3275911 * x), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return s * y;
}
export function trueRange(rho, observed) {
  rho = Math.max(Math.min(rho, 0.999), 0);
  const z = NORM.inv(Math.min(Math.max(observed, 0.005), 0.995)) * Math.sqrt(rho), sd = Math.sqrt(1 - rho);
  return [100 * NORM.cdf(z - 1.2816 * sd), 100 * NORM.cdf(z + 1.2816 * sd)];
}
function bisectLeft(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] < x) lo = mid + 1; else hi = mid; } return lo; }

// ---------- scoring
// fetchShard(i) -> ArrayBuffer of data/s/{i as 4 hex digits}.bin; meta = parsed data/meta.json
export async function scoreHistory(files, meta, fetchShard, onProgress = () => {}) {
  const out = { kind: null, checks: [], ok: false };
  const { plays, kind, tsMin, tsMax } = await readHistory(files);
  out.kind = kind;
  if (!kind || !plays.length) { out.checks.push({ id: 'format', ok: false, text: "We couldn't find Spotify listening history in those files." }); return out; }
  let wMin = Infinity, wMax = -Infinity; for (const p of plays) { if (p.week < wMin) wMin = p.week; if (p.week > wMax) wMax = p.week; }
  const span = wMax - wMin;
  const fmt = (t) => { const d = new Date(t * 1000); return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  out.history = { plays: plays.length, from: fmt(tsMin), to: fmt(tsMax), weeks: span };
  if (kind === 'standard') out.checks.push({ id: 'format', ok: false, text: "This is Spotify's one-year export (Account data). Each find needs a year of follow-up, so we need your Extended streaming history: in Spotify, Account → Privacy → request Extended streaming history (it can take a few weeks)." });
  if (span < RULES.minHistoryWeeks) out.checks.push({ id: 'history', ok: false, text: `Your history covers ${Math.floor(span / 52)} year(s); we need at least two.` });
  if (out.checks.some((c) => !c.ok)) return out;

  const lastJudgeable = meta.last_month - 12;
  const picks = findPicks(plays);
  const judged = picks.filter((p) => p.m <= lastJudgeable && p.m >= meta.y0);
  const tooRecent = picks.filter((p) => p.m > lastJudgeable).length;
  // look up names, newest judged finds first (enough to fill the five-year window; a second pass if matches run short)
  const lastAll = Math.max(...judged.map((p) => p.m), -Infinity);
  const need = (lo) => judged.filter((p) => p.m > lo && p.hash === undefined);
  const shards = new Map(); let fetched = 0;
  async function lookup(list) {
    for (const p of list) { p.hash = nameHash(p.an); p.shard = Number(BigInt.asUintN(64, p.hash) & BigInt((1 << meta.shard_bits) - 1)); }
    const ids = [...new Set(list.map((p) => p.shard))].filter((i) => !shards.has(i));
    let done = 0;
    await Promise.all(ids.map(async (i) => {
      const buf = await fetchShard(i); shards.set(i, buf ? decodeShard(buf, meta) : { names: new Map(), arts: [] });
      done++; fetched++; if (done % 20 === 0) onProgress(done / ids.length);
    }));
    for (const p of list) { const s = shards.get(p.shard); const ai = s.names.get(p.hash); p.art = ai === undefined ? null : s.arts[ai]; p.artKey = ai === undefined ? null : s.arts[ai].id; }
  }
  let lo = lastAll - 12 * (meta.window_years + 2);
  await lookup(need(lo));
  const matchedOf = () => judged.filter((p) => p.hash !== undefined && p.art);
  let last = Math.max(...matchedOf().map((p) => p.m), -Infinity);
  if (Number.isFinite(last) && last - 12 * meta.window_years < lo) { lo = last - 12 * meta.window_years; await lookup(need(lo)); }
  const looked = judged.filter((p) => p.hash !== undefined);
  // one pick per artist: two names for the same ListenBrainz artist keep the earliest find
  const seen = new Map();
  for (const p of looked.filter((q) => q.art).sort((a, b) => a.m - b.m || (a.an < b.an ? -1 : a.an > b.an ? 1 : 0))) if (!seen.has(p.artKey)) seen.set(p.artKey, p);
  const matched = [...seen.values()];
  const share = looked.length ? looked.filter((p) => p.art).length / looked.length : 0;
  out.history.matched_share = Math.round(share * 1000) / 1000;
  out.history.shards = fetched;
  if (share < RULES.minMatch) { out.checks.push({ id: 'match', ok: false, text: `We recognised only ${Math.round(share * 100)}% of the artists you got into. Your taste may be outside what we can judge.` }); return out; }
  if (share < RULES.warnMatch) out.checks.push({ id: 'match', ok: true, warn: true, text: `We recognised ${Math.round(share * 100)}% of the artists you got into, so your score rests on part of them.` });

  for (const p of matched) { const f = features(p.art, p.m); Object.assign(p, f, excess(meta, f, p.m) || { excess: null }); }
  const scored = matched.filter((p) => p.excess !== null);
  last = Math.max(...scored.map((p) => p.m), -Infinity);
  const win = scored.filter((p) => p.m > last - 12 * meta.window_years);
  const n = win.length;
  const u = { picks: n, too_recent: tooRecent, enough: n >= meta.min_picks, solid: n >= meta.solid_picks,
    window: n ? `${monthLabel(Math.min(...win.map((p) => p.m)))} – ${monthLabel(last)}` : null };
  if (n >= meta.min_picks) {
    const s = win.reduce((t, p) => t + p.excess, 0) / (n + meta.shrink);
    const pct = bisectLeft(meta.scores, s) / meta.scores.length;
    const rel = n * meta.per_pick / (1 + (n - 1) * meta.per_pick);
    const [rlo, rhi] = trueRange(rel, pct);
    Object.assign(u, { score: s, percentile: Math.round(100 * pct), range: [Math.round(rlo), Math.round(rhi)], reliability: Math.round(rel * 100) / 100 });
  }
  out.units = { artist: u };
  if (!u.enough) {
    out.checks.push({ id: 'picks', ok: false, text: `We found ${n} artists you got into that we can judge from your last ${meta.window_years} years of finds; we need at least ${meta.min_picks}.`
      + (tooRecent ? ` ${tooRecent} more are too recent to judge yet; come back in a few months.` : '') });
    return out;
  }
  if (!u.solid) out.checks.push({ id: 'picks', ok: true, warn: true, text: 'You have enough finds for a rough score; more history would narrow the range.' });
  out.best_calls = [...win].sort((a, b) => b.excess - a.excess).slice(0, 8).map((p) => ({ artist: p.name, found: monthLabel(p.m),
    grew: Math.round(Math.exp(p.g) * 10) / 10, similar_grew: Math.round(Math.exp(p.gMean) * 10) / 10 }));
  out.took_off = { yours: win.filter((p) => p.up3).length, expected: Math.round(win.reduce((t, p) => t + p.up3Rate, 0)), picks: n };
  const byHook = [...win].sort((a, b) => a.plays26 - b.plays26);
  const q = Math.floor(n / 4);
  const meanEx = (arr) => arr.length ? Math.expm1(arr.reduce((t, p) => t + p.excess, 0) / arr.length) : null;
  out.obsessions = { most_hooked: meanEx(byHook.slice(n - q)), least_hooked: meanEx(byHook.slice(0, q)) };
  out.ok = true;
  return out;
}
