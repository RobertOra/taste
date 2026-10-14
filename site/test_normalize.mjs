// Python vs JS name normalization: node site/test_normalize.mjs <names.json> <python_output.json>  (site/normalize.py writes the second)
import { readFileSync } from 'node:fs';
import { normName } from './static/engine.js';
const [names, py] = process.argv.slice(2).map((f) => JSON.parse(readFileSync(f, 'utf8')));
const bad = names.map((n, i) => [n, normName(n), py[i]]).filter(([, a, b]) => a !== b);
console.log(`compared ${names.length}, mismatches ${bad.length}`); bad.slice(0, 10).forEach((b) => console.log(JSON.stringify(b)));
process.exit(bad.length ? 1 : 0);
