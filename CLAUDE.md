# Working on this project

- Read `README.md` first (what was done, which file does what), then `NOTES.md` (dated log of every decision and result).
  `SPEC.md`, `FREEZE_MEMO.md`, `LB_PREREG.md`, and `SONG_PREREG.md` record plans frozen before tests were run: add to them, never rewrite them.
- `data/` was deleted on 2026-10-14 (only `data/_deploy.git`, the publishing copy of the site, remains). Anything that needs data
  means rebuilding it first, in the order given in README.md.
- Python: `uv run python -I <script>`. Heavy jobs one at a time; DuckDB with `memory_limit='5GB'` and `threads=6` (the laptop is shared with other work).
- The site: `site/static/` is exactly what gets published. `site/static/engine.js` (browser) and `site/score_pack.py` (Python copy)
  must score identically; after changing either, run `site/test_node.mjs` and `site/score_pack.py` on the same files and compare.
  Test on the local server (`uv run python -I site/serve.py`, http://127.0.0.1:8777). Do at most one scoring run against the live
  site per deploy: repeated runs got the site rate-limited by GitHub.
- Publishing: `bash site/deploy.sh "message"` pushes `site/static` to the public repo RobertOra/taste-test (GitHub Pages). This research
  repo, RobertOra/taste, is public too: never commit anything personal.
- Never commit, copy into the project, or publish anyone's own listening exports (Spotify or YouTube files); test with them in place.
