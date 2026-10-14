// Taste Test scoring engine (runs in the browser, and in Node for tests). Mirrored by site/score_pack.py.
// Four measures from the study, for songs and artists: prescience (do your finds gain new listeners, compared with similar
// finds the same month) and discernment (do people who try your finds stick with them), with the study's corrections.
// Reference data: data/meta.json, data/index.bin and data/p/NN.bin, read by byte range (site/build_pack_*.py).

const WEEK = 604800;
const YEAR_MIN_SHOW = 5;
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

// ---------- normalized song names (site/normalize.py mirrors this exactly; site/test_normalize.mjs checks it)
const NDROP = 'feat|ft|featuring|with|remaster|remastered|remasterd|version|edit|explicit|clean|radio|mono|stereo|deluxe|bonus|single|album|official|lyric|lyrics|audio|video|visualizer|visualiser|hd|4k|mv|m/v';
const NKEEP = 'remix|mix|live|acoustic|slowed|sped|reverb|instrumental|demo|cover|karaoke|orchestral|piano|unplugged|session';
const NBRACKET = /\s*[([]([^)\]]*)[)\]]/g, NDASH = /\s+-\s+([^-]*)$/, NFEAT = /\s+(?:feat\.?|ft\.?|featuring)\s.*$/;
const NWDROP = new RegExp(`(?<![a-z0-9])(?:${NDROP})(?![a-z0-9])`), NWKEEP = new RegExp(`(?<![a-z0-9])(?:${NKEEP})`), NLN = /[\p{L}\p{N}]/u;
const labelDrop = (t) => NWDROP.test(t) && !NWKEEP.test(t);
export function normName(s) {
  let t = (s || '').normalize('NFKC').toLowerCase().trim();
  const base = t;
  t = t.replace(NBRACKET, (m, g) => (labelDrop(g) ? '' : m));
  const m = t.match(NDASH);
  if (m && labelDrop(m[1])) t = t.slice(0, m.index);
  t = t.replace(NFEAT, '');
  let out = ''; for (const c of t) if (NLN.test(c)) out += c;
  return out || base;
}
export const songKey = (artist, track) => `${normName(artist)}\t${normName(track)}`;
// a song's key for a pack: "artist\ttrack" as given, or the normalized name if the pack is keyed that way (meta.song_keys)
const skey = (meta, an, tn) => (meta && meta.song_keys === 'norm' ? songKey(an, tn) : `${an}\t${tn}`);

// ---------- reading Spotify exports (JSON, or a .zip of them)
async function inflateRaw(bytes) {
  const ds = new DecompressionStream('deflate-raw');
  const out = await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer();
  return new Uint8Array(out);
}
// src: bytes, or a Blob/File read in pieces (so a big Takeout zip never has to fit in memory); want(name) picks the entries to inflate
export async function unzip(src, want = (name) => /\.(json|html)$/i.test(name)) {   // -> [{name, bytes}]
  const isBytes = src instanceof Uint8Array, size = isBytes ? src.length : src.size;
  const read = async (a, b) => (isBytes ? src.subarray(a, b) : new Uint8Array(await src.slice(a, b).arrayBuffer()));
  const t0 = Math.max(0, size - 65557), tail = await read(t0, size), tv = new DataView(tail.buffer, tail.byteOffset, tail.byteLength);
  let eocd = -1;
  for (let i = tail.length - 22; i >= 0; i--) if (tv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('not a zip file');
  const n = tv.getUint16(eocd + 10, true), cdSize = tv.getUint32(eocd + 12, true), cdOff = tv.getUint32(eocd + 16, true);
  if (cdOff === 0xffffffff || n === 0xffff) throw new Error('this zip is too big to read here; unzip it and drop the folder instead');
  const cd = await read(cdOff, cdOff + cdSize), dv = new DataView(cd.buffer, cd.byteOffset, cd.byteLength);
  const dec = new TextDecoder(), out = [];
  let p = 0;
  for (let k = 0; k < n; k++) {
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nlen = dv.getUint16(p + 28, true);
    const xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true), loff = dv.getUint32(p + 42, true);
    const name = dec.decode(cd.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (!want(name)) continue;
    const lh = await read(loff, loff + 30), lv = new DataView(lh.buffer, lh.byteOffset, lh.byteLength);
    const lstart = loff + 30 + lv.getUint16(26, true) + lv.getUint16(28, true);
    const raw = await read(lstart, lstart + csize);
    out.push({ name, bytes: method === 0 ? raw : await inflateRaw(raw) });
  }
  return out;
}
// inside a zip, only Spotify histories and YouTube files are opened (a full Takeout holds much else)
export const WANT = (n) => (/\.json$/i.test(n) && /history|youtube/i.test(n)) || (/\.html$/i.test(n) && /youtube|watch-history/i.test(n));
// ---------- reading YouTube watch history (Google Takeout: watch-history.html or .json). No play length is given, so every watch counts.
// A song is certain when it comes from an auto-generated "Artist - Topic" channel; an "Artist - Song" title is a guess, checked in resolveYouTube.
const YT_TAGS = /\s*[([][^)\]]*(official|lyric|audio|video|visualizer|(?<![A-Za-z0-9_])mv(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])m\/v(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])hd(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])4k(?![A-Za-z0-9_]))[^)\]]*[)\]]/gi;
const MON = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
const TZ = { UTC: 0, GMT: 0, EST: -5, EDT: -4, CST: -6, CDT: -5, MST: -7, MDT: -6, PST: -8, PDT: -7, AKST: -9, AKDT: -8, HST: -10, BST: 1, CET: 1, CEST: 2,
  EET: 2, EEST: 3, MSK: 3, IST: 5.5, JST: 9, KST: 9, AEST: 10, AEDT: 11, NZST: 12, NZDT: 13 };
export function ytTime(s) {   // "Oct 5, 2026, 11:49:22 AM EDT" or "5 Oct 2026, 11:49:22 BST" -> unix seconds (unknown zones as UTC)
  const m = s.match(/^(?:([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})|(\d{1,2}) ([A-Za-z]{3})[A-Za-z]*\.? (\d{4})),? (\d{1,2}):(\d{2}):(\d{2}) ?(AM|PM)? ?(?:GMT([+-])(\d{1,2}):?(\d{2})|([A-Z]{2,5}))?$/i);
  if (!m) return NaN;
  const mon = MON[(m[1] || m[5]).toLowerCase()]; if (mon === undefined) return NaN;
  let h = +m[7]; if (m[10]) h = (h % 12) + (m[10].toUpperCase() === 'PM' ? 12 : 0);
  const off = m[11] ? (m[11] === '-' ? -1 : 1) * (+m[12] + +m[13] / 60) : (TZ[(m[14] || '').toUpperCase()] ?? 0);
  return Date.UTC(+(m[3] || m[6]), mon, +(m[2] || m[4]), h, +m[8], +m[9]) / 1000 - off * 3600;
}
const unescapeHtml = (s) => s.replace(/&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);/gi, (_, e) => {
  const k = e.toLowerCase(); return k === 'amp' ? '&' : k === 'lt' ? '<' : k === 'gt' ? '>' : k === 'quot' ? '"' : k === 'apos' ? "'" : String.fromCodePoint(k[1] === 'x' ? parseInt(k.slice(2), 16) : +k.slice(1));
});
const FEAT = /(?:\s+|\s*[([])\s*(feat\.?|ft\.?|featuring|prod\.?(?: by)?)\s[^)\]]*[)\]]?/gi;
const SPLIT = /\s*(?:,|&| x | X |(?<![A-Za-z0-9_])feat\.?|(?<![A-Za-z0-9_])ft\.?)\s*/;
const QUOTED = /^(.+?)\s+["'‘“「『]([^"'’”」』]+)["'’”」』]/;
const HANGUL = /[ᄀ-ᇿ㄰-㆏가-힯]+/g;
const trimDash = (s) => s.replace(/^[\s\-|]+|[\s\-|]+$/g, '');
const cleanSong = (s) => trimDash(s.replace(YT_TAGS, '').replace(FEAT, ''));
// readings of one watch as [rule, artist, song], most reliable first. 'a': counts if the artist is confirmed; 'av': same, and the
// reading also counts toward confirming its artist; 's'/'sv': needs the exact song in ListenBrainz too (resolveYouTube).
// Channel-name and quoted readings never confirm an artist on their own, which keeps out YouTubers.
function ytCands(header, title, channel) {
  const out = []; title = title.replace(/ [–—] /g, ' - ');
  if (title.includes(' - ')) {
    const i = title.indexOf(' - '), a = title.slice(0, i), s = title.slice(i + 3);
    out.push(['av', a, s.replace(YT_TAGS, '')], ['sv', a.split(SPLIT)[0], cleanSong(s)], ['sv', cleanSong(s), a]);
  }
  const m = title.match(QUOTED);
  if (m) out.push(['s', m[1].replace(/\s*\([^)]*\)/g, '').replace(HANGUL, ''), m[2]]);
  const ch = channel.replace(/(VEVO|\s*-?\s*Official(\s+(Channel|YouTube))?)$/i, '').trim();
  const rest = ch && title.toLowerCase().startsWith(ch.toLowerCase() + ' - ') ? title.slice(ch.length + 3) : title;
  out.push([header === 'YouTube Music' ? 'av' : 's', ch, cleanSong(rest)]);
  return out.map(([k, a, s]) => [k, a.trim(), s.trim()]).filter(([, a, s]) => a && s);
}
function ytPlay(header, title, channel, ts) {
  if (!Number.isFinite(ts)) return null;
  const base = { week: Math.floor(ts / WEEK), ts, how: 'youtube', key: `${Math.floor(ts)}\t${title}\t${channel}` };
  if (channel.endsWith(' - Topic')) {
    const artist = channel.slice(0, -8).trim(), track = title.trim(), an = artist.toLowerCase();
    if (EXCLUDE.has(an) || !track) return null;
    return { ...base, an, name: artist, track, tn: track.toLowerCase(), src: 'yt' };
  }
  const cands = ytCands(header, title, channel);
  return cands.length ? { ...base, src: 'yt?', cands } : null;
}
function readYouTubeHtml(text, watchFile) {   // watchFile: a watch-history file (every entry a watch, in any language); else only "Watched" entries count
  const out = [];
  text = text.replace(/[  ]/g, ' ');
  for (const cell of text.split('outer-cell').slice(1)) {
    if (cell.includes('From Google Ads')) continue;
    const h = cell.match(/mdl-typography--title">([^<]*)</), c = cell.match(/mdl-typography--body-1">([^<]*)<a href="([^"]*)">([^<]*)<\/a><br><a href="[^"]*">([^<]*)<\/a><br>([^<]*)<br>/);
    if (!c || !c[2].includes('watch?v=') || !(watchFile || c[1].trim() === 'Watched')) continue;
    const p = ytPlay(h ? h[1].trim() : '', unescapeHtml(c[3]).trim(), unescapeHtml(c[4]).trim(), ytTime(c[5].trim()));
    if (p) out.push(p);
  }
  return out;
}

export async function readHistory(files) {   // files: [{name, bytes} or {name, blob}] -> {plays: [{week, an, name, src}], kind, youtube, tsMin, tsMax}
  const dec = new TextDecoder(); const got = { extended: [], standard: [] }; const kinds = new Set(); const yt = [];
  const jsons = [];
  for (const f of files) {
    if (f.name.toLowerCase().endsWith('.zip')) jsons.push(...await unzip(f.blob || f.bytes, WANT));
    else if (/\.(json|html)$/i.test(f.name)) jsons.push(f.bytes ? f : { name: f.name, bytes: new Uint8Array(await f.blob.arrayBuffer()) });
  }
  for (const f of jsons) {
    const watchFile = /watch-history/i.test(f.name);
    if (f.name.toLowerCase().endsWith('.html')) { yt.push(...readYouTubeHtml(dec.decode(f.bytes), watchFile)); continue; }
    let data; try { data = JSON.parse(dec.decode(f.bytes)); } catch { continue; }
    if (!Array.isArray(data)) continue;
    for (const d of data) {
      if (!d || typeof d !== 'object') continue;
      let ts, artist, how = 'other', track = '';
      if ('time' in d && 'header' in d && typeof d.title === 'string' && typeof d.titleUrl === 'string') {   // YouTube (Takeout JSON)
        if (!d.titleUrl.includes('watch?v=') || !Array.isArray(d.subtitles) || !d.subtitles.length) continue;
        if (Array.isArray(d.details) && d.details.some((x) => x && x.name === 'From Google Ads')) continue;
        if (!watchFile && !d.title.startsWith('Watched ')) continue;
        const p = ytPlay(String(d.header).trim(), d.title.replace(/^Watched /, '').trim(), String(d.subtitles[0].name || '').trim(), Date.parse(d.time) / 1000);
        if (p) yt.push(p);
        continue;
      }
      if ('ts' in d && 'master_metadata_album_artist_name' in d) {
        kinds.add('extended');
        artist = d.master_metadata_album_artist_name; track = d.master_metadata_track_name || '';
        const rs = d.reason_start;
        how = rs === 'clickrow' || rs === 'playbtn' ? 'chose' : rs === 'trackdone' ? (d.shuffle ? 'shuffle' : 'next') : rs === 'fwdbtn' || rs === 'backbtn' ? 'skip' : 'other';
        if (!artist || !d.master_metadata_track_name || (d.ms_played || 0) < RULES.minPlayMs) continue;
        ts = Date.parse(d.ts) / 1000;
      } else if ('endTime' in d && 'artistName' in d) {
        kinds.add('standard');
        if ((d.msPlayed || 0) < RULES.minPlayMs) continue;
        artist = d.artistName; track = d.trackName || ''; ts = Date.parse(d.endTime.replace(' ', 'T') + ':00Z') / 1000;
      } else continue;
      if (!Number.isFinite(ts)) continue;
      const an = artist.trim().toLowerCase();
      if (EXCLUDE.has(an)) continue;
      got['ts' in d ? 'extended' : 'standard'].push({ week: Math.floor(ts / WEEK), an, name: artist, ts, how, track, tn: track.trim().toLowerCase(), src: 'spotify' });
    }
  }
  const kind = kinds.has('extended') ? 'extended' : (kinds.size ? 'standard' : null);
  const seen = new Set(), ytU = yt.filter((p) => { if (seen.has(p.key)) return false; seen.add(p.key); return true; });   // the same watch in two exports counts once
  const plays = (kind ? got[kind] : []).concat(ytU);   // with both Spotify exports present, only the extended history counts (no double counting)
  let tsMin = Infinity, tsMax = -Infinity; for (const p of plays) { if (p.ts < tsMin) tsMin = p.ts; if (p.ts > tsMax) tsMax = p.ts; }
  return { plays, kind, youtube: ytU.length, tsMin, tsMax };
}
// Settle each guessed YouTube watch on its first reading that passes (ytCands), preferring one whose artist you play elsewhere. An artist is confirmed if it's in the history some
// surer way (Spotify, a Topic channel), or (from 'av'/'sv' readings in 4+ separate weeks) ListenBrainz knows it and one of its
// three most-played songs. Watches with no passing reading are taken as not music.
export async function resolveYouTube(plays, pack) {
  const sure = new Set(plays.filter((p) => p.src !== 'yt?').map((p) => p.an)), by = new Map(), guessed = plays.filter((p) => p.src === 'yt?');
  for (const p of guessed) for (const [rule, a, s] of p.cands) {
    const an = a.toLowerCase(); if (!rule.endsWith('v') || sure.has(an)) continue;
    let g = by.get(an); if (!g) by.set(an, g = { weeks: new Set(), songs: new Map() });
    g.weeks.add(p.week); const tn = s.toLowerCase(); let w = g.songs.get(tn); if (!w) g.songs.set(tn, w = new Set()); w.add(p.week);
  }
  await pack.init();
  const cand = [...by.entries()].filter(([, g]) => g.weeks.size >= RULES.minWeeks), known = new Set(sure);
  await pack.load(cand.map(([an]) => pack.shardOf(nameHash(an))));
  const tops = cand.filter(([an]) => pack.artist(nameHash(an))).map(([an, g]) => [an, [...g.songs.entries()]
    .sort((x, y) => y[1].size - x[1].size || cmpName(x[0], y[0])).slice(0, 3).map(([tn]) => nameHash(skey(pack.meta, an, tn)))]);
  await pack.load(tops.flatMap(([, hs]) => hs.map((h) => pack.shardOf(h))));
  for (const [an, hs] of tops) if (hs.some((h) => pack.song(h))) known.add(an);
  // song checks, only for 's' readings that could still be picked: a passing 'a' reading of an artist you play elsewhere always wins,
  // and any passing 'a' reading wins over later ones. Skipped for an artist that could have fewer than 4 weeks in all (it can't be a find).
  const span = new Map(), addW = (an, w) => { let x = span.get(an); if (!x) span.set(an, x = new Set()); x.add(w); };
  for (const p of plays) { if (p.src === 'yt?') for (const [, a] of p.cands) addW(a.toLowerCase(), p.week); else addW(p.an, p.week); }
  const need = [], certain = (rule, an) => rule[0] === 'a' && known.has(an) && !EXCLUDE.has(an);
  for (const p of guessed) {
    const sureA = p.cands.some(([rule, a]) => certain(rule, a.toLowerCase()) && sure.has(a.toLowerCase()));
    let earlierA = false, earlierSureA = false;
    for (const [rule, a, s] of p.cands) {
      const an = a.toLowerCase();
      if (certain(rule, an)) { earlierA = true; if (sure.has(an)) earlierSureA = true; continue; }
      if (rule[0] === 'a' || !known.has(an) || EXCLUDE.has(an) || span.get(an).size < RULES.minWeeks) continue;
      if (sure.has(an) ? earlierSureA : (earlierA || sureA)) continue;
      need.push(nameHash(an), nameHash(skey(pack.meta, an, s.toLowerCase())));
    }
  }
  await pack.load(need.map((h) => pack.shardOf(h)));
  const passes = (rule, an, tn) => known.has(an) && !EXCLUDE.has(an) && (rule[0] === 'a' || (span.get(an).size >= RULES.minWeeks && pack.artist(nameHash(an)) !== null && pack.song(nameHash(skey(pack.meta, an, tn))) !== null));
  const out = [];
  for (const p of plays) {
    if (p.src !== 'yt?') { out.push(p); continue; }
    const ok = p.cands.filter(([rule, a, s]) => passes(rule, a.toLowerCase(), s.toLowerCase()));
    const pick = ok.find(([, a]) => sure.has(a.toLowerCase())) || ok[0];   // an artist you play elsewhere wins
    if (pick) { const [, a, s] = pick; out.push({ week: p.week, ts: p.ts, how: 'youtube', an: a.toLowerCase(), name: a, tn: s.toLowerCase(), track: s, src: 'yt?' }); }
  }
  return out;
}

// ---------- picks: artists by name, songs by "artist\ttrack" (as Spotify gives them)
// warm-up: no find counts in the 26 weeks after the start of the listening, or after a return from a gap of 26+ weeks
export function segmentStarts(plays, single = false) {   // single: one warm-up per history (as the study; packs with meta.warmup 'single')
  const ws = [...new Set(plays.map((p) => p.week))].sort((a, b) => a - b), out = [];
  if (single) return ws.slice(0, 1);
  for (let i = 0; i < ws.length; i++) if (i === 0 || ws[i] - ws[i - 1] >= RULES.onboardWeeks) out.push(ws[i]);
  return out;
}
function inWarmup(starts, fw) {   // latest start <= fw, and fw within 26 weeks of it
  let lo = 0, hi = starts.length - 1, s = -Infinity;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (starts[mid] <= fw) { s = starts[mid]; lo = mid + 1; } else hi = mid - 1; }
  return fw < s + RULES.onboardWeeks;
}
export function findPicks(plays, keyOf, notPicked = null, starts = null) {
  starts = starts || segmentStarts(plays);
  const by = new Map();
  for (const p of plays) {
    const key = keyOf(p);
    let a = by.get(key); if (!a) { a = { key, p, weeks: new Map(), first: p, total: 0 }; by.set(key, a); }
    a.weeks.set(p.week, (a.weeks.get(p.week) || 0) + 1); a.total++;
    if (p.ts < a.first.ts) a.first = p;
  }
  const picks = [];
  for (const a of by.values()) {
    const ws = [...a.weeks.keys()].sort((x, y) => x - y);
    const fw = ws[0];
    if (inWarmup(starts, fw)) { if (notPicked) notPicked.warmup.push(a.p.name); continue; }
    if (ws.length < RULES.minWeeks || ws[RULES.minWeeks - 1] - fw >= RULES.windowWeeks) { if (notPicked) notPicked.tried.push(a.p.name); continue; }
    const w4 = ws[RULES.minWeeks - 1];
    let plays26 = 0; for (const [w, n] of a.weeks) if (w < fw + RULES.windowWeeks) plays26 += n;
    picks.push({ key: a.key, an: a.p.an, name: a.p.name, track: a.p.track, firstWeek: fw, m: monthOfWeek(w4), plays26, total: a.total, how: a.first.how, firstTrack: a.first.track });
  }
  return picks;
}

// ---------- packed reference data, read by byte range
function readVarint(b, o) { let x = 0, s = 0, c; do { c = b[o.p++]; x += (c & 0x7f) * 2 ** s; s += 7; } while (c & 0x80); return x; }
function readRows(b, o, m0) {
  const n = readVarint(b, o), month = new Int32Array(n), a = new Int32Array(n), t = new Int32Array(n), k = new Int32Array(n);
  let prev = m0 - 1;
  for (let i = 0; i < n; i++) {
    const v = readVarint(b, o), code = v & 3; prev += Math.floor(v / 4); month[i] = prev;
    if (code === 0) { a[i] = 1; } else if (code === 1) { a[i] = 1; t[i] = 1; } else if (code === 2) { a[i] = 1; t[i] = 1; k[i] = 1; }
    else { a[i] = readVarint(b, o); t[i] = readVarint(b, o); k[i] = readVarint(b, o); }
  }
  return { month, a, t, k };
}
export function decodeShard(buf, meta) {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf), dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const nAN = dv.getUint16(0, true), nAR = dv.getUint16(2, true), nSN = dv.getUint16(4, true), nSR = dv.getUint16(6, true);
  let p = 8; const artistNames = new Map(), songNames = new Map();
  for (let i = 0; i < nAN; i++) { artistNames.set(dv.getBigInt64(p, true), dv.getUint16(p + 8, true)); p += 10; }
  const o = { p }; const artists = [];
  for (let i = 0; i < nAR; i++) {
    const id = dv.getUint32(o.p, true), country = meta.countries[dv.getUint16(o.p + 4, true)], fm = dv.getUint16(o.p + 6, true) - 1000 + 24000;
    const fam = b[o.p + 8], anyRel = b[o.p + 9] === 1; o.p += 10;
    const scene = new Map(); let n = readVarint(b, o);
    for (let j = 0; j < n; j++) { const y = b[o.p++] + 2000, s = b[o.p++]; scene.set(y, s === 255 ? -1 : s); }
    const rel = []; n = readVarint(b, o); let prev = meta.m0 - 12;
    for (let j = 0; j < n; j++) { prev += readVarint(b, o); rel.push(prev); }
    artists.push({ id, country, fm, fam, anyRel, scene, rel, rows: readRows(b, o, meta.m0) });
  }
  p = o.p;
  for (let i = 0; i < nSN; i++) { songNames.set(dv.getBigInt64(p, true), dv.getUint16(p + 8, true)); p += 10; }
  o.p = p; const songs = [];
  for (let i = 0; i < nSR; i++) {
    const id = dv.getUint32(o.p, true), fm = dv.getUint16(o.p + 4, true) - 1000 + 24000; o.p += 6;
    songs.push({ id, fm, rows: readRows(b, o, meta.m0) });
  }
  return { artistNames, artists, songNames, songs };
}
// Pack: index + range reader. fetchRange(fileNo, start, endInclusive) -> Uint8Array; fetchIndex() -> ArrayBuffer
export class Pack {
  constructor(meta, fetchIndex, fetchRange) { Object.assign(this, { meta, fetchIndex, fetchRange, shards: new Map(), bytes: 0, requests: 0 }); }
  async init() {
    if (this.loc) return;
    const b = new Uint8Array(await this.fetchIndex()), dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const S = dv.getUint32(4, true), F = dv.getUint16(8, true); let p = 10;
    this.compressed = dv.getUint32(0, true) === 0x54535432;
    const fileSizes = []; for (let i = 0; i < F; i++) { fileSizes.push(dv.getUint32(p, true)); p += 4; }
    this.S = S; this.bits = Math.round(Math.log2(S));
    this.loc = new Array(S); let file = 0, off = 0;
    for (let s = 0; s < S; s++) {
      const len = dv.getUint32(p, true); p += 4;
      if (len && off + len > fileSizes[file]) { file++; off = 0; }
      this.loc[s] = [file, off, len]; off += len;
    }
  }
  shardOf(h) { return Number(BigInt.asUintN(64, h) & BigInt(this.S - 1)); }
  async load(ids, onProgress = () => {}) {
    await this.init();
    const need = [...new Set(ids)].filter((s) => !this.shards.has(s) && this.loc[s][2] > 0);
    for (const s of ids) if (!this.shards.has(s) && this.loc[s][2] === 0) this.shards.set(s, decodeShard(new Uint8Array(8), this.meta));
    const byFile = new Map();
    for (const s of need) { const [f] = this.loc[s]; if (!byFile.has(f)) byFile.set(f, []); byFile.get(f).push(s); }
    const ranges = [];
    for (const [f, ss] of byFile) {
      ss.sort((x, y) => this.loc[x][1] - this.loc[y][1]);
      let cur = null;
      for (const s of ss) {
        const [, off, len] = this.loc[s];
        if (cur && off - cur.end <= 16384) { cur.end = off + len; cur.shards.push(s); } else { cur = { f, start: off, end: off + len, shards: [s] }; ranges.push(cur); }
      }
    }
    let done = 0; const queue = [...ranges];
    const worker = async () => {
      while (queue.length) {
        const r = queue.shift();
        const data = await this.fetchRange(r.f, r.start, r.end - 1);
        this.bytes += data.length; this.requests++;
        for (const s of r.shards) {
          const [, off, len] = this.loc[s]; let part = data.subarray(off - r.start, off - r.start + len);
          if (this.compressed) part = await inflateRaw(part);
          this.shards.set(s, decodeShard(part, this.meta));
        }
        done++; if (done % 10 === 0 || done === ranges.length) onProgress(done / ranges.length);
      }
    };
    await Promise.all(Array.from({ length: Math.min(16, ranges.length) }, worker));
  }
  artist(h) { const s = this.shards.get(this.shardOf(h)); const i = s && s.artistNames.get(h); return i === undefined ? null : s.artists[i]; }
  song(h) { const s = this.shards.get(this.shardOf(h)); const i = s && s.songNames.get(h); return i === undefined ? null : s.songs[i]; }
}

// ---------- features, outcomes, excess
function sums(rows, m) {
  let a0 = 0, a1 = 0, ap = 0, tl = 0, kl = 0, tp = 0, kp = 0, t0 = 0, t1 = 0, tq = 0;
  const { month, a, t, k } = rows;
  for (let i = 0; i < month.length; i++) {
    const x = month[i];
    if (x > m + 12) break;
    if (x <= m) { tp += t[i]; kp += k[i]; if (x >= m - 5) { a0 += a[i]; t0 += t[i]; } else if (x >= m - 11 && x <= m - 6) { ap += a[i]; tq += t[i]; } }
    else { tl += t[i]; kl += k[i]; if (x >= m + 7) { a1 += a[i]; t1 += t[i]; } }
  }
  return { a0, a1, ap, tl, kl, tp, kp, t0, t1, tq };
}
export function features(unit, item, art, m) {
  const f = sums(item.rows, m);
  const d = m - item.fm;
  f.age = unit === 'artist'
    ? (item.fm <= 2005 * 12 ? 9 : d < 3 ? 0 : d < 6 ? 1 : d < 12 ? 2 : d < 24 ? 3 : 4)
    : (item.fm <= 2005 * 12 ? 9 : d <= 2 ? d : d < 6 ? 3 : d < 12 ? 4 : d < 24 ? 5 : 6);
  f.scene = art.scene.has(Math.floor(m / 12)) ? art.scene.get(Math.floor(m / 12)) : -1;
  f.relc = art.anyRel ? 2 * (art.rel.some((r) => r > m && r <= m + 3) ? 1 : 0) + (art.rel.some((r) => r >= m - 3 && r <= m) ? 1 : 0) : 4;
  f.country = art.country; f.fam = art.fam;
  return f;
}
function lookups(M) {
  if (M._lk) return M._lk;
  const base = new Map(M.baseline.map((r) => [r[0] * 16 + r[1], r]));
  const eff = {}; for (const [name, rows] of Object.entries(M.effects)) eff[name] = new Map(rows.map((r) => [r.slice(0, -1).join('|'), r[r.length - 1]]));
  const cuts = M.xb_cuts ? new Map(M.xb_cuts.map((r) => [r[0], r.slice(1)])) : null;
  M._lk = { base, eff, cuts }; return M._lk;
}
export function excess(M, f, m) {
  const { base, eff, cuts } = lookups(M);
  const bin = Math.min(14, Math.max(0, Math.floor(Math.log(f.a0 + 1) / Math.log(2))));
  const mo = Math.min(3, Math.max(-3, Math.floor((Math.log((f.a0 + 1) / (f.ap + 1)) / Math.log(2)) / 0.5)));
  const b = base.get(m * 16 + bin); if (!b) return null;
  const g = Math.log((f.a1 + 1) / (f.a0 + 1));
  let y;
  const keys = { mo: String(mo), year_scene: `${Math.floor(m / 12)}|${f.scene}`, age: String(f.age), relc: String(f.relc), country: f.country };
  if (M.measure === 'A') y = g;
  else {
    y = (f.kl + 2 * M.p0) / (f.tl + 2);
    const cp = (f.kp + 2 * M.p0) / (f.tp + 2), q = cuts.get(m);
    if (!q) return null;
    keys.xb = String((cp > q[0]) + (cp > q[1]) + (cp > q[2]) + (cp > q[3]));
  }
  let e = 0; for (const [name, k] of Object.entries(keys)) e += eff[name] ? (eff[name].get(k) || 0) : 0;
  return { y, g, mean: b[2], up3Rate: b[3] ?? null, up3: g >= Math.log(3), excess: y - b[2] - e, sceneEff: eff.year_scene ? (eff.year_scene.get(keys.year_scene) || 0) : 0 };
}

const NORM = { cdf: (x) => 0.5 * (1 + erf(x / Math.SQRT2)), inv: (p) => { let lo = -10, hi = 10; for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (NORM.cdf(mid) < p) lo = mid; else hi = mid; } return (lo + hi) / 2; } };
function erf(x) {
  const s = Math.sign(x); x = Math.abs(x);
  if (x < 3) { let sum = x, term = x, n = 0; while (Math.abs(term) > 1e-16 * Math.abs(sum)) { n++; term *= -x * x / n; sum += term / (2 * n + 1); } return s * 2 / Math.sqrt(Math.PI) * sum; }
  const t = 1 / (1 + 0.3275911 * x); return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
}
export function trueRange(rho, observed) {
  rho = Math.max(Math.min(rho, 0.999), 0);
  const z = NORM.inv(Math.min(Math.max(observed, 0.005), 0.995)) * Math.sqrt(rho), sd = Math.sqrt(1 - rho);
  return [100 * NORM.cdf(z - 1.2816 * sd), 100 * NORM.cdf(z + 1.2816 * sd)];
}
function bisectLeft(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] < x) lo = mid + 1; else hi = mid; } return lo; }
const mean = (a) => (a.length ? a.reduce((t, x) => t + x, 0) / a.length : null);
const cmpName = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// score one measure from matched picks (each {m, item, art, w, ...}); songs merge per artist and month (plays-weighted)
export function scoreMeasure(meta, key, picks) {
  const M = meta.measures[key], unit = M.unit;
  const scored = [];
  for (const p of picks) {
    let f = features(unit, p.item, p.art, p.m);
    if (M.settled) f = { ...f, a0: f.t0, a1: f.t1, ap: f.tq };   // prescience among settled listeners (rebuild item 2)
    const x = excess(M, f, p.m); if (x) scored.push({ ...p, f, ...x });
  }
  let units = scored;
  if (unit === 'song') {
    const g = new Map();
    for (const p of scored) { const k = `${p.art.id}|${p.m}`; if (!g.has(k)) g.set(k, []); g.get(k).push(p); }
    units = [...g.values()].map((ps) => { const W = ps.reduce((t, p) => t + p.w, 0); return { m: ps[0].m, art: ps[0].art, songs: ps, excess: ps.reduce((t, p) => t + p.excess * p.w, 0) / W, w: W }; });
  }
  const last = Math.max(...units.map((p) => p.m), -Infinity);
  const win = meta.window_years ? units.filter((p) => p.m > last - 12 * meta.window_years) : units;   // window_years 0: all judged finds
  const n = win.length, r = { key, unit, measure: M.measure, picks: n, enough: n >= meta.min_picks, solid: n >= 250, win, scored, all: units };
  if (n) r.window = [Math.min(...win.map((p) => p.m)), last];
  if (n >= meta.min_picks) {
    const s = win.reduce((t, p) => t + p.excess, 0) / (n + meta.shrink);
    const pct = bisectLeft(M.scores, s) / M.scores.length, rel = n * M.per_pick / (1 + (n - 1) * M.per_pick);
    const [lo, hi] = trueRange(rel, pct);
    Object.assign(r, { score: s, percentile: Math.round(100 * pct), range: [Math.round(lo), Math.round(hi)], reliability: Math.round(rel * 100) / 100 });
  }
  // year by year: the same score from each year's finds, ranked among reference listeners' years (quantiles), with a range
  if (M.year_q) {
    const byY = new Map(); for (const p of win) { const y = Math.floor(p.m / 12); if (!byY.has(y)) byY.set(y, []); byY.get(y).push(p.excess); }
    r.years = [...byY.entries()].sort((a, b) => a[0] - b[0]).map(([year, xs]) => {
      const k = xs.length, out = { year, finds: k, avg: mean(xs), typical: M.year_typical ? M.year_typical[String(year)] ?? null : null };
      // a year needs 5 finds to show; under meta.min_year (20) it's marked as few: a wide range, not a solid rank
      out.few = k < meta.min_year;
      if (k >= YEAR_MIN_SHOW) {
        const sy = xs.reduce((t, x) => t + x, 0) / (k + meta.shrink), q = M.year_q;
        const i = bisectLeft(q, sy), pctY = i <= 0 ? 0 : i >= q.length ? 1 : (i - 1 + (sy - q[i - 1]) / (q[i] - q[i - 1] || 1)) / (q.length - 1);
        const relY = k * M.per_pick / (1 + (k - 1) * M.per_pick), [lo, hi] = trueRange(relY, pctY);
        Object.assign(out, { percentile: Math.round(100 * pctY), range: [Math.round(lo), Math.round(hi)] });
      }
      return out;
    });
  }
  // your average (prescience: % more new listeners than similar finds; discernment: points more of the people who tried it kept it)
  if (n) { r.avg = mean(win.map((p) => p.excess)); r.growth = M.measure === 'A' ? Math.expm1(r.avg) : r.avg; }
  // every find in the window with its numbers (songs listed one by one)
  const one = (p, extra) => ({ name: p.name, found: monthLabel(p.m), m: p.m, excess: p.excess, a0: p.f.a0, a1: p.f.a1, kept: p.f.kl, tried: p.f.tl,
    keepShare: p.y, simShare: p.y - p.excess, simGrowth: Math.exp(p.mean), ...extra });
  r.items = unit === 'song' ? win.flatMap((u) => u.songs.map((p) => one(p, { name: p.track, artist: p.name }))) : win.map((p) => one(p, {}));
  r.items.sort((x, y) => y.excess - x.excess);
  return r;
}

// ---------- the whole thing
// pack: a Pack; meta: parsed data/meta.json
export async function scoreHistory(files, meta, pack, onProgress = () => {}) {
  const out = { kind: null, checks: [], ok: false };
  const read = await readHistory(files), { kind, youtube } = read;
  out.kind = kind; out.youtube = youtube;
  if (!read.plays.length) { out.checks.push({ id: 'format', ok: false, text: "We couldn't find Spotify or YouTube listening history in those files." }); return out; }
  if (kind === 'standard' && !youtube) { out.checks.push({ id: 'format', ok: false, text: "This is Spotify's one-year export (Account data). Each find needs a year of follow-up, so we need your Extended streaming history: in Spotify, Account → Privacy → request Extended streaming history (it can take a few weeks)." }); return out; }
  const plays = youtube ? await resolveYouTube(read.plays, pack) : read.plays;
  if (!plays.length) { out.checks.push({ id: 'format', ok: false, text: "We couldn't find any music in that YouTube history. We recognise songs from YouTube Music and \"Artist - Topic\" channels, and videos titled \"Artist - Song\"." }); return out; }
  let wMin = Infinity, wMax = -Infinity, tsMin = Infinity, tsMax = -Infinity;
  for (const p of plays) { if (p.week < wMin) wMin = p.week; if (p.week > wMax) wMax = p.week; if (p.ts < tsMin) tsMin = p.ts; if (p.ts > tsMax) tsMax = p.ts; }
  const span = wMax - wMin;
  const fmt = (t) => { const d = new Date(t * 1000); return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const ytPlays = plays.filter((p) => p.src !== 'spotify').length;
  out.history = { plays: plays.length, from: fmt(tsMin), to: fmt(tsMax), weeks: span, sources: { spotify: plays.length - ytPlays, youtube: ytPlays } };
  if (span < RULES.minHistoryWeeks) out.checks.push({ id: 'history', ok: false, text: `Your history covers ${Math.floor(span / 52)} year(s) (${out.history.from} to ${out.history.to}); we need at least two.`
    + (youtube ? ' Google may delete YouTube history after 3, 18, or 36 months; you can check Auto-delete at myactivity.google.com. Adding your Spotify history can help too.' : '') });
  if (out.checks.some((c) => !c.ok)) return out;

  const lastJ = meta.last_month - 12;
  const notPicked = { warmup: [], tried: [] };
  const starts = segmentStarts(plays, meta.warmup === 'single');
  const aPicks = findPicks(plays, (p) => p.an, notPicked, starts);
  const sPicks = findPicks(plays, (p) => skey(meta, p.an, p.tn), null, starts).filter((p) => p.key.slice(p.key.indexOf('\t') + 1));
  const judgedA = aPicks.filter((p) => p.m >= meta.y0 && p.m <= lastJ), judgedS = sPicks.filter((p) => p.m >= meta.y0 && p.m <= lastJ);
  const recentA = aPicks.filter((p) => p.m > lastJ).sort((a, b) => b.plays26 - a.plays26).slice(0, 15);
  for (const p of [...judgedA, ...recentA]) p.ah = nameHash(p.an);
  for (const p of judgedS) { p.sh = nameHash(p.key); p.ah = nameHash(p.an); }
  await pack.init();
  await pack.load([...judgedA, ...recentA, ...judgedS].flatMap((p) => [pack.shardOf(p.ah), ...(p.sh !== undefined ? [pack.shardOf(p.sh)] : [])]), onProgress);
  out.history.bytes = pack.bytes; out.history.requests = pack.requests;
  const dedup = (ps) => { const seen = new Map(); for (const p of ps.sort((a, b) => a.m - b.m || cmpName(a.key, b.key))) if (!seen.has(p.item.id)) seen.set(p.item.id, p); return [...seen.values()]; };
  for (const p of judgedA) { p.art = pack.artist(p.ah); p.item = p.art; p.w = p.plays26; }
  for (const p of recentA) p.art = pack.artist(p.ah);
  for (const p of judgedS) { p.art = pack.artist(p.ah); p.item = p.art ? pack.song(p.sh) : null; p.w = p.plays26; }
  const mA = dedup(judgedA.filter((p) => p.item)), mS = dedup(judgedS.filter((p) => p.item));
  const shareA = judgedA.length ? judgedA.filter((p) => p.item).length / judgedA.length : 0;
  const shareS = judgedS.length ? judgedS.filter((p) => p.item).length / judgedS.length : 0;
  out.history.matched = { artists: shareA, songs: shareS };
  if (Math.max(shareA, shareS) < RULES.minMatch) { out.checks.push({ id: 'match', ok: false, text: `We recognised only ${Math.round(100 * Math.max(shareA, shareS))}% of the music you got into. Your taste may be outside what we can judge.` }); return out; }
  if (shareA < RULES.warnMatch) out.checks.push({ id: 'match', ok: true, warn: true, text: `We recognised ${Math.round(100 * shareA)}% of the artists you got into, so your score rests on part of them.` });
  const R = {};
  for (const [key, ps] of [['song_A', mS], ['song_D', mS], ['artist_A', mA], ['artist_D', mA]]) R[key] = scoreMeasure(meta, key, ps);
  out.measures = R;
  out.headline = R.song_A.enough ? 'song_A' : R.artist_A.enough ? 'artist_A' : null;
  if (!out.headline) {
    out.checks.push({ id: 'picks', ok: false, text: `We found ${R.song_A.picks} groups of songs and ${R.artist_A.picks} artists you got into that we can judge; we need at least ${meta.min_picks} of one.`
      + (recentA.length ? ' Some of your finds are too recent to judge yet; come back in a few months.' : '') });
    return out;
  }
  if (!R[out.headline].solid) out.checks.push({ id: 'picks', ok: true, warn: true, text: `You have enough finds for a rough score; more history would narrow the range (${R[out.headline].picks} ${out.headline.startsWith('song') ? 'independent song finds' : 'artists'}; ${meta.min_picks} is the minimum, 250 or more is a solid score).` });
  out.report = buildReport({ meta, plays, aPicks, sPicks, judgedA, mA, R, recentA, lastJ, notPicked, wMin, wMax, pack, headline: out.headline });
  out.ok = true;
  return out;
}

// ---------- personal report (descriptive; the scores above don't depend on it)
function buildReport({ meta, plays, aPicks, sPicks, judgedA, mA, R, recentA, lastJ, notPicked, wMin, wMax, headline }) {
  const Rp = {}, A = R.artist_A, S = R.song_A;
  const years = (wMax - wMin) / 52.18;
  Rp.facts = { plays: plays.length, ytPlays: plays.filter((p) => p.src !== 'spotify').length, artists: new Set(plays.map((p) => p.an)).size, songs: new Set(plays.map((p) => `${p.an}\t${p.tn}`)).size,
    findsA: aPicks.length, findsS: sPicks.length, years: Math.round(years * 10) / 10, perYear: Math.round(aPicks.length / Math.max(years - 0.5, 1)) };
  // artists-level stories use artist prescience picks in its window (artists are what people recognise)
  const win = A.win || [];
  const ahead = [];
  for (const p of win) {
    if (p.art.fm < meta.m0) continue;
    let tot = 0, after = 0; const r = p.art.rows;
    for (let i = 0; i < r.month.length; i++) { if (r.month[i] > meta.last_month) break; tot += r.a[i]; if (r.month[i] > p.m) after += r.a[i]; }
    if (tot >= 5) ahead.push({ name: p.name, m: p.m, share: after / tot, fans: tot });
  }
  Rp.ahead = { share: mean(ahead.map((a) => a.share)), artists: ahead.length, best: ahead.filter((a) => a.fans >= 30).sort((a, b) => b.share - a.share || b.fans - a.fans).slice(0, 3) };
  // same unit as the headline (songs: each scored song counted, against the typical rate for similar songs)
  const sw = headline === 'artist_A' ? win : (S.win || []).flatMap((u) => u.songs);
  Rp.tookOff = sw.length ? { yours: sw.filter((p) => p.up3).length, expected: Math.round(sw.reduce((t, p) => t + (p.up3Rate || 0), 0)) } : null;
  Rp.edge = win.length ? { scenes: Math.expm1(mean(win.map((p) => p.sceneEff))), within: Math.expm1(mean(win.map((p) => p.excess))) } : null;
  const byY = new Map(); for (const p of A.all || []) { const y = Math.floor(p.m / 12); if (!byY.has(y)) byY.set(y, []); byY.get(y).push(p.excess); }
  const wlo = A.window ? A.window[0] : Infinity;
  Rp.byYear = [...byY.entries()].sort((a, b) => a[0] - b[0]).map(([y, xs]) => ({ year: y, finds: xs.length, growth: Math.expm1(mean(xs)), inScore: y * 12 + 11 >= wlo }));
  const bins = [[4, 9, 'Tried a few times'], [10, 24, 'Kept coming back'], [25, 59, 'Hooked'], [60, 1e9, 'Obsessed']];
  Rp.conviction = bins.map(([lo, hi, label]) => { const xs = win.filter((p) => p.plays26 >= lo && p.plays26 <= hi); return { label, lo, hi: hi >= 1e9 ? null : hi, finds: xs.length, growth: xs.length ? Math.expm1(mean(xs.map((p) => p.excess))) : null }; });
  const HOW = { chose: 'You chose it (clicked or pressed play)', next: 'Came up next (album, playlist or queue)', shuffle: 'Came up on shuffle', skip: 'You skipped to it', youtube: 'On YouTube', other: 'Other (app opened, another device…)' };
  Rp.how = Object.entries(HOW).map(([k, label]) => { const xs = win.filter((p) => p.how === k); return { key: k, label, finds: xs.length, growth: xs.length ? Math.expm1(mean(xs.map((p) => p.excess))) : null }; }).filter((h) => h.finds);
  // genres (headline measure's finds; a song's genre is its artist's)
  const H = R[R.song_A.enough ? 'song_A' : 'artist_A'];
  const famRows = meta.families.map((name, i) => {
    const xs = (H.win || []).filter((p) => p.art.fam === i);
    return { name, finds: xs.length, share: (H.win || []).length ? xs.length / H.win.length : 0, typical: meta.family_share ? meta.family_share[H.unit][i] : null,
      growth: xs.length >= 5 ? Math.expm1(mean(xs.map((p) => p.excess))) : null };
  }).filter((g) => g.finds || (g.typical && g.typical > 0.02));
  Rp.genres = famRows.sort((a, b) => b.finds - a.finds);
  const denomA = win.length + meta.shrink;
  Rp.findsA = win.map((p) => ({ name: p.name, m: p.m, found: monthLabel(p.m), a0: p.f.a0, a1: p.f.a1, vs: Math.expm1(p.excess), impact: p.excess / denomA, plays26: p.plays26, track: p.firstTrack, fam: meta.families[p.art.fam],
    extra: (p.f.a1 + 1) - (p.f.a0 + 1) * Math.exp(p.mean) }));
  const denomS = (S.win || []).length + meta.shrink;
  Rp.findsS = (S.win || []).flatMap((u) => u.songs.map((p) => ({ name: p.track, artist: p.name, m: p.m, found: monthLabel(p.m), a0: p.f.a0, a1: p.f.a1, vs: Math.expm1(p.excess), impact: (p.excess * p.w / u.w) / denomS, plays26: p.plays26 })));
  Rp.open = recentA.map((p) => {
    const art = p.art || null; if (!art) return null;
    const sum = (lo, hi) => { let s = 0; const r = art.rows; for (let i = 0; i < r.month.length; i++) if (r.month[i] >= lo && r.month[i] <= hi) s += r.a[i]; return s; };
    return { name: p.name, found: monthLabel(p.m), plays26: p.plays26, then: sum(p.m - 5, p.m), now: p.m <= meta.last_month - 6 ? sum(meta.last_month - 5, meta.last_month) : null };
  }).filter(Boolean);
  const winSet = new Set(win), mSet = new Set(mA);
  Rp.notCounted = { tried: notPicked.tried, warmup: notPicked.warmup, unrecognised: judgedA.filter((p) => !p.item).map((p) => p.name),
    tooRecent: aPicks.filter((p) => p.m > lastJ).map((p) => p.name), older: mA.filter((p) => !winSet.has(p)).map((p) => p.name).concat(judgedA.filter((p) => p.item && !mSet.has(p)).map((p) => p.name)),
    early: aPicks.filter((p) => p.m < meta.y0).map((p) => p.name) };
  return Rp;
}
