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

## What was done

1. **Last.fm data (MLHD+).** `pipeline/mlhd_ingest.py` streamed MLHD+ from data.metabrainz.org into compact weekly tables (about 7
   hours; run and monitored with `ops/ingest.sh`, checked with `pipeline/validate_mlhd.py`). Listeners were split by a salted hash into an
   `explore` half and a `sealed` half that stayed untouched until the method was frozen.
2. **MusicBrainz metadata.** `pipeline/fetch_mb_artists.py` and `fetch_mb_release_groups.py` added artist countries, genre tags, and
   release dates.
3. **Derived tables.** The `pipeline/derive_*.py` scripts built, per half, everything the analysis uses: each listener's finds and how
   they did (`derive_user_artist`, `derive_bets`, `derive_market`, `derive_song_bets`), scenes (`derive_scenes`, `derive_scenes_yearly`,
   `derive_scenes_genre`), how hooked people were (`derive_obsession`), control features (`derive_user_features`,
   `derive_user_year_features`), and community-leading inputs (`derive_community`, `derive_comm_prior`, `derive_scene_bets`).
4. **Choosing and confirming the measures.** On the explore half, `analysis/taste_models.py` scored 12 candidate measures and
   `analysis/evaluate.py` and `scoreboard.py` compared them (EVALUATION.md). The frozen plan (SPEC.md, FREEZE_MEMO.md) was then run
   once on the sealed half and judged by `analysis/confirm.py`: all 12 passed.
5. **Plain-language findings.** `analysis/headlines.py`, `ladder.py`, `pickers.py`, `fan_value.py`, and the other post-freeze scripts
   logged in NOTES.md produced the takeoff, good-picker, and fan-value numbers, each written down in advance and checked once on the
   sealed half (29 of 32 held).
6. **ListenBrainz replication.** `pipeline/lb_ingest.py` streamed ListenBrainz dump 2692 (2026-10-01); `pipeline/lb_convert.py` and
   `lb_convert_songs.py` put it in the same layout as a third half, `lb`; the frozen plan in LB_PREREG.md was run once and judged by
   `analysis/lb_report.py` (8 of 9 measures, 24 of 32 findings). Exploratory follow-ups came after: `lb_*.py`, `eras_*.py`, and others.
7. **Songs.** Nine song predictions (SONG_PREREG.md: `ladder_songs.py`, `scene_split_songs.py`, `three_way_songs.py`,
   `song_pickers.py`, `song_fans.py`, and others), all held on the sealed half and eight on ListenBrainz.
8. **Music over time** (exploratory, outside the taste question): `trends_*.py`, `why_fade.py`; results in NOTES.md.
9. **Write-up.** `analysis/build_headline_data.py`, `charts_data.py`, `build_lb_extra_data.py`, `build_trends_data.py`, and several
   analysis scripts wrote the page's data (`analysis/writeup/*.json`); `site/build_study_page.py` turned `analysis/writeup/index.html`
   into the published `site/static/study.html`.
10. **The site.** `pipeline/lb_names.py` re-streamed the dump for song-name text and `lb_norm_songs.py` matched spellings of the same
    song. The `site/build_pack_*` scripts built the reference data from ListenBrainz (the commands, with their settings, are in
    `ops/runs/` and NOTES.md: "Site reference rebuild", "Site requests"). `site/test_pack.py` and `site/test_node.mjs` checked that the
    site scores exactly as the reference does. `bash site/deploy.sh "message"` publishes `site/static` to the public repo
    RobertOra/taste-test; test changes on the local server (`uv run python -I site/serve.py`, http://127.0.0.1:8777) rather than with
    repeated runs on the live site, which GitHub rate-limits.

## Data

The data (about 150 GB) was deleted on 2026-10-14 to save space; the results, code, and site are all here. Running the steps above in
order rebuilds it from public sources: MLHD+ from data.metabrainz.org, and the newest ListenBrainz full dump (only the two newest stay
online, so a rebuild would use a later dump than 2692). Results would match closely but not exactly: a newer dump has more listens and
some deleted ones, MusicBrainz tags and dates keep being edited, and some charts' 95% ranges shift slightly between runs. None of this
should change a conclusion.
