"""Version-stamp the site's file references so a browser never mixes a new page with older cached files (GitHub Pages lets
browsers cache for 10 minutes). One version for the whole site: a hash of the code, styles and reference-data index, written
as ?v=<hash> on style.css and app.js (index.html), and on engine.js, data/meta.json, data/index.bin and data/p/NN.bin (app.js).
Run by deploy.sh before publishing; idempotent (re-running with unchanged content changes nothing)."""
import hashlib
import re
from pathlib import Path

S = Path(__file__).resolve().parent / "static"
V = r"(?:\?v=[0-9a-f]+)?"
unstamp = lambda t: re.sub(r"\?v=[0-9a-f]+", "", t)
h = hashlib.sha1()
for f in ("index.html", "app.js", "engine.js", "style.css", "data/meta.json"):
    h.update(unstamp((S / f).read_text()).encode())
h.update(str((S / "data" / "index.bin").stat().st_size).encode())
ver = h.hexdigest()[:10]

edits = {"index.html": [(rf'href="style\.css{V}"', f'href="style.css?v={ver}"'), (rf'src="app\.js{V}"', f'src="app.js?v={ver}"')],
         "app.js": [(rf"from '\./engine\.js{V}'", f"from './engine.js?v={ver}'"), (rf"'data/meta\.json{V}'", f"'data/meta.json?v={ver}'"),
                    (rf"'data/index\.bin{V}'", f"'data/index.bin?v={ver}'"), (rf"'data/slots\.bloom{V}'", f"'data/slots.bloom?v={ver}'"),
                    (rf"\.bin{V}`", f".bin?v={ver}`")]}
for f, subs in edits.items():
    t = (S / f).read_text()
    for pat, rep in subs:
        t, n = re.subn(pat, rep, t)
        assert n == 1, (f, pat, n)
    (S / f).write_text(t)
print("site version", ver)
