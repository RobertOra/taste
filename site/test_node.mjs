// Run the browser engine in Node on local files: node site/static/test_node.mjs <files...>   (JSON summary of all four measures)
import { readFileSync, openSync, readSync, closeSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { scoreHistory, Pack } from './static/engine.js';

const here = join(dirname(fileURLToPath(import.meta.url)), 'static');
const DATA = process.env.SITE_DATA || 'data';   // e.g. data_v2 to test another pack
const meta = JSON.parse(readFileSync(join(here, DATA, 'meta.json'), 'utf8'));
const fetchIndex = async () => readFileSync(join(here, DATA, 'index.bin'));
const fetchRange = async (f, start, end) => {
  const fd = openSync(join(here, DATA, 'p', `${String(f).padStart(2, '0')}.bin`), 'r'); const buf = Buffer.alloc(end - start + 1);
  readSync(fd, buf, 0, buf.length, start); closeSync(fd); return new Uint8Array(buf);
};
const files = process.argv.slice(2).map((p) => ({ name: basename(p), bytes: new Uint8Array(readFileSync(p)) }));
const t0 = Date.now();
const fetchBloom = async () => readFileSync(join(here, DATA, 'slots.bloom'));
const pack = new Pack(meta, fetchIndex, fetchRange, fetchBloom);
const r = await scoreHistory(files, meta, pack);
const M = Object.fromEntries(Object.entries(r.measures || {}).map(([k, m]) => [k, { picks: m.picks, score: m.score, percentile: m.percentile, range: m.range }]));
console.log(JSON.stringify({ ok: r.ok, checks: r.checks.map((c) => c.id + (c.warn ? '(warn)' : '')), headline: r.headline, measures: M,
  matched: r.history?.matched, download_mb: (pack.bytes / 1e6).toFixed(1), requests: pack.requests, seconds: (Date.now() - t0) / 1000 }, null, 1));
