# Is good taste in music real?

Do some people consistently get into music before it takes off, or is it luck? This project tests that on two platforms: Last.fm
(MLHD+, 594,415 listeners, 2005–2013) with half the listeners held back until the method was frozen, and ListenBrainz (95,770
listeners, 2005–2026) as an independent replication. It also produced a public site that scores your own Spotify or YouTube history
the same way: https://robertora.github.io/taste-test/ (the study is at /study.html).

## Documents

| File | What it is |
|---|---|
| `SPEC.md` | The study design: what a "find" (bet) is, the four kinds of taste, the controls, and the frozen confirmation rules, with the reasons for each choice. |
| `EVALUATION.md` | How the 12 candidate taste measures were scored and compared on the explore half. |
| `FREEZE_MEMO.md` | What was frozen before the hidden ("sealed") half was opened, and the follow-up questions. |
| `LB_PREREG.md` | The ListenBrainz replication, written down before it was run, and its results. |
| `SONG_PREREG.md` | The song-level predictions (S1–S9), written down before they were run, and their results. |
| `NOTES.md` | A dated running log: every later decision and why, every exploratory result (including dropped ones), the site's data rebuilds, and housekeeping. Start here for "why did we do X instead of Y". |

## Code

- `pipeline/` — downloads and converts the sources, then derives the tables everything else uses (finds, outcomes, scenes, features).
- `analysis/` — the tests and every number in the write-up. `analysis/out/` holds results; `analysis/writeup/` holds the write-up page source (`index.html`) and its data (`*.json`).
- `site/` — the scoring site: `static/` is what gets published; the `build_pack_*` scripts build its reference data; `engine.js` (browser) and `score_pack.py` (a Python copy used for testing) do the scoring.

Python via `uv run python -I ...`; heavy steps use DuckDB with a 5 GB memory limit. Data lives in `data/` (not in git; about 150 GB when complete).

## Rebuilding from scratch

The raw data was deleted after the project (2026-10-14) to save space. Everything can be rebuilt from public sources with the
scripts here; results will match closely but not exactly (see the end of this section). Steps, in order:

1. **Last.fm (MLHD+).** `pipeline/mlhd_ingest.py` streams MLHD+ from data.metabrainz.org into compact weekly tables in `data/mlhd/`
   (about 7 hours; `ops/ingest.sh` runs and monitors it; `pipeline/validate_mlhd.py` checks the result). Listeners are split by a
   salted hash into `explore` and `sealed` halves.
2. **MusicBrainz metadata.** `pipeline/fetch_mb_artists.py` and `pipeline/fetch_mb_release_groups.py` (artist countries, genre tags, release dates).
3. **Derived tables.** The `pipeline/derive_*.py` scripts, per half: `derive_user_artist`, `derive_bets`, `derive_market`,
   `derive_scenes` / `derive_scenes_yearly` / `derive_scenes_genre`, `derive_song_bets`, `derive_obsession`, `derive_user_features`,
   `derive_user_year_features`, and (for community-leading) `derive_community` / `derive_comm_prior` / `derive_scene_bets`. Each
   script's docstring gives its inputs and outputs.
4. **The main study.** `analysis/taste_models.py` scores each candidate measure; `analysis/evaluate.py` and `analysis/scoreboard.py`
   compare them (explore half); `analysis/confirm.py` applies the frozen rules to the sealed half (SPEC.md, FREEZE_MEMO.md).
   The plain-language findings: `analysis/headlines.py`, `ladder.py`, `pickers.py`, `fan_value.py`, and the other post-freeze scripts named in NOTES.md.
5. **ListenBrainz.** `pipeline/lb_ingest.py` streams a full ListenBrainz listens dump (the study used dump 2692, 2026-10-01; only the
   two newest dumps stay online, so use the current one) into `data/lb/`; `pipeline/lb_convert.py` and `lb_convert_songs.py` put it in the
   same layout as a third half, `lb`; rerun step 3 for `lb`, then the frozen run and `analysis/lb_report.py` (LB_PREREG.md). The
   exploratory ListenBrainz analyses (`lb_*.py`, `eras_*.py`, `trends_*.py`, `why_fade.py`, …) follow, as logged in NOTES.md.
6. **Songs (S1–S9).** As SONG_PREREG.md: `analysis/ladder_songs.py`, `scene_split_songs.py`, `three_way_songs.py`, `song_pickers.py`, `song_fans.py`, and others it names.
7. **Write-up data.** `analysis/build_headline_data.py`, `charts_data.py`, `build_lb_extra_data.py`, `build_trends_data.py`, and the
   analysis scripts that write `analysis/writeup/*.json` directly; then `site/build_study_page.py` turns `analysis/writeup/index.html`
   into `site/static/study.html`.
8. **Site reference data.** `pipeline/lb_names.py` (re-streams the dump for song-name text), `pipeline/lb_norm_songs.py --map --songs`,
   then with `SITE_REF=data/site_v2 LB_SONGS=lb_norm SONG_KEYS=norm`: `site/build_pack_items.py`, `build_pack_ref.py`,
   `build_pack_scores.py`, `build_pack_slots.py`; then with `SITE_OUT=site/static/data SHARD_BY=artist` also set:
   `build_pack_files.py` (needs `uv run --with numba`), `compress_pack.py`, `build_pack_meta.py` (with `SETTLED=1`), `check_pack.py`.
   Tests: `site/test_pack.py` (Python copy vs the reference scores), `site/test_node.mjs` (browser engine). NOTES.md
   ("Site reference rebuild", "Site requests") explains each setting.
9. **Publish.** `bash site/deploy.sh "message"` pushes `site/static` to the public repo RobertOra/taste-test (GitHub Pages). Test on
   the local server (`uv run python -I site/serve.py`, http://127.0.0.1:8777) rather than with repeated runs on the live site,
   which GitHub rate-limits.

**Expected small differences on a rebuild:** a newer ListenBrainz dump has more listens and some deleted ones; MusicBrainz genre tags
and release dates keep being edited; and some charts' 95% ranges shift slightly between runs (a few write-up tables kept earlier runs'
ranges, noted in NOTES.md). None of these should change a conclusion.
