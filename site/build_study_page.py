"""The full write-up ("Is good taste real?") as a normal static page: site/static/study.html + study/*.json.
Takes analysis/writeup/index.html unchanged and supplies what the claude.ai dashboard runtime provided: design tokens (CSS
variables, light and dark), d3, and a small `dash` stand-in that loads the same JSON datasets from study/."""
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "analysis" / "writeup", ROOT / "site" / "static"
page = (SRC / "index.html").read_text()
ids = sorted(set(re.findall(r'data-source="([a-z_]+)"', page)) | set(re.findall(r"dash\.data\('([a-z_]+)'\)", page)))
ids = [i for i in ids if i != "summary"]   # summary is computed in the page (dash.calc)
(OUT / "study").mkdir(exist_ok=True)
for i in ids:
    shutil.copy2(SRC / f"{i}.json", OUT / "study" / f"{i}.json")
head = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Is Good Taste Real?</title>
<meta name="description" content="A study of whether good taste in music is real: 600,000 Last.fm listeners, checked again on ListenBrainz.">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
:root {
  --font-anthropic-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; --font-anthropic-serif: Georgia, "Iowan Old Style", "Times New Roman", serif;
  --cds-gap-xs: 6px; --cds-gap-sm: 12px; --cds-gap-md: 18px; --cds-gap-lg: 28px; --cds-gap-xl: 40px;
  --cds-pad-xs: 6px; --cds-pad-sm: 10px; --cds-pad-lg: 20px; --cds-radius: 14px;
  --cds-font-size-title: clamp(32px, 5vw, 44px); --cds-font-size-heading: 26px; --cds-font-size-body: 16.5px; --cds-font-size-caption: 13px; --cds-font-weight-medium: 600;
  --cds-dur-slow: .3s; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.12);
  --color-bg: #fbfaf7; --color-panel: #ffffff; --color-fg: #1c1b19; --color-fg-muted: #6b6862; --color-border-line: #e6e2da; --color-bad: #c2453b;
  --cds-text-secondary: #57544e; --cds-surface-popover: #ffffff; --cds-border: #e6e2da;
  --cds-chart-grid: #efece6; --cds-chart-axis: #b9b4ab; --cds-chart-muted: #b5b0a7; --cds-chart-reference: #8b877f;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --color-bg: #141412; --color-panel: #1c1c1a; --color-fg: #edebe6; --color-fg-muted: #a29e96; --color-border-line: #33322e;
    --color-bad: #ec7a6f; --cds-text-secondary: #b4b0a8; --cds-surface-popover: #262623; --cds-border: #3a3935; --cds-chart-grid: #2a2926; --cds-chart-axis: #5e5b55;
    --cds-chart-muted: #6c6862; --cds-chart-reference: #8b877f; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.5); }
}
:root[data-theme="dark"] { --color-bg: #141412; --color-panel: #1c1c1a; --color-fg: #edebe6; --color-fg-muted: #a29e96; --color-border-line: #33322e;
  --color-bad: #ec7a6f; --cds-text-secondary: #b4b0a8; --cds-surface-popover: #262623; --cds-border: #3a3935; --cds-chart-grid: #2a2926; --cds-chart-axis: #5e5b55;
  --cds-chart-muted: #6c6862; --cds-chart-reference: #8b877f; }
html, body { background: var(--color-bg); color: var(--color-fg); margin: 0; }
body { padding: 0 16px 64px; font-family: var(--font-anthropic-sans); -webkit-font-smoothing: antialiased; }
.site-top { max-width: 48rem; margin: 0 auto; padding: 18px 0 8px; display: flex; justify-content: space-between; align-items: baseline; font-size: 15px; }
.site-top a { color: #2f5bd3; text-decoration: none; } .site-top .brand { font-weight: 700; font-size: 18px; color: var(--color-fg); }
.dash-skeleton { animation: pulse 1.4s ease-in-out infinite; } @keyframes pulse { 50% { opacity: .45; } }
.wu-fail { color: var(--color-fg-muted); font-size: 13px; padding: 20px 0; }
</style>
<script>
// stand-in for the dashboard runtime: datasets come from study/<id>.json
window.dash = (() => {
  const store = {}, calcs = {}, cbs = [];
  const ids = %IDS%;
  const api = {
    colors: ['#2f5bd3', '#d9622b', '#1f8a5b', '#8e5bd3', '#c99a2e', '#2a9d9d', '#b4508a', '#6b7a8f'],
    data: (id) => store[id] || { status: 'loading' },
    calc: (id, o) => { calcs[id] = o; },
    onData: (cb) => { cbs.push(cb); },
  };
  const run = () => {
    for (const [id, o] of Object.entries(calcs)) {
      const inputs = o.inputs.map((i) => store[i]);
      store[id] = inputs.every((s) => s && s.status === 'ok') ? { status: 'ok', data: o.fn(...inputs.map((s) => s.data)) } : { status: 'loading' };
    }
    cbs.forEach((cb) => { try { cb(); } catch (e) { console.error(e); } });
  };
  Promise.all(ids.map((id) => fetch(`study/${id}.json?v=%VER%`).then((r) => r.ok ? r.json() : Promise.reject(new Error(id)))
    .then((data) => { store[id] = { status: 'ok', data }; }, () => { store[id] = { status: 'error' }; })))
    .then(() => { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run(); });
  let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(run, 150); });
  return api;
})();
</script>
</head>
<body>
<nav class="site-top"><a class="brand" href="./">Taste Test</a><a href="./">Score your own taste →</a></nav>
""".replace("%IDS%", json.dumps(ids)).replace("%VER%", hashlib.sha1(b"".join((OUT / "study" / f"{i}.json").read_bytes() for i in ids)).hexdigest()[:10])
(OUT / "study.html").write_text(head + page + "\n</body>\n</html>\n")
print("study.html written;", len(ids), "datasets:", ", ".join(ids))
