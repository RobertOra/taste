// Run the browser engine in Node on local files: node site/static/test_node.mjs <files...>   (prints a JSON summary)
import { readFileSync, existsSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { scoreHistory } from './engine.js';

const here = dirname(fileURLToPath(import.meta.url));
const meta = JSON.parse(readFileSync(join(here, 'data', 'meta.json'), 'utf8'));
const fetchShard = async (i) => { const p = join(here, 'data', 's', `${i.toString(16).padStart(4, '0')}.bin`); return existsSync(p) ? readFileSync(p) : null; };
const files = process.argv.slice(2).map((p) => ({ name: basename(p), bytes: new Uint8Array(readFileSync(p)) }));
const t0 = Date.now();
const r = await scoreHistory(files, meta, fetchShard);
const u = r.units?.artist || {};
console.log(JSON.stringify({ ok: r.ok, kind: r.kind, checks: r.checks.map((c) => c.id + (c.warn ? '(warn)' : '')), history: r.history,
  picks: u.picks, too_recent: u.too_recent, score: u.score, percentile: u.percentile, range: u.range, took_off: r.took_off,
  best: (r.best_calls || []).map((c) => c.artist), seconds: (Date.now() - t0) / 1000 }, null, 1));
