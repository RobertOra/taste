# Is good taste real?

## Question
Do some people reliably have "better taste" in music than others, beyond luck,
how much they listen, or how mainstream they are? If so, what predicts it?
"There's no such thing as taste" is an acceptable answer.

## Approach (agreed 2026-10-07)
- Main framing: listens as investments. A "bet" = a user's first committed listen
  to an artist/track; its "price" = the artist's listener count at that time
  (excluding the user); the "return" = later growth, measured relative to similar
  artists at the same popularity in the same period (excess return).
- Is it skill or luck? (1) Is the spread of user scores wider than a shuffled baseline that
  keeps each user's number of bets and entry popularity? (2) Does someone's early score
  predict their later score? (3) Does it replicate on the sealed half?
- Other definitions to compare (do they agree = one "taste factor"?):
  durability (still listened to in 2026, via ListenBrainz popularity API),
  leading indicator (predicts peers' later listening), critical consensus.
- Robustness: multiverse / specification-curve analysis over all reasonable
  parameter choices; explicit controls for activity, exploration rate,
  mainstreamness, genre, tenure, survivorship, leave-one-out popularity.
- Anti-p-hacking: users are split by salted hash into `explore` / `sealed`.
  Explore freely on `explore`; freeze definitions in a committed file before
  ever analysing `sealed`; report every model tried.
- Later: ListenBrainz (2015-2026) as an outside check on a different group and era,
  and the basis for any website (Spotify users listen to modern music).

## Data: MLHD+ (Last.fm scrobbles, ~2005-2013, ~583k users)
Streamed by `pipeline/mlhd_ingest.py` straight from MetaBrainz; raw archives
never stored. See the module docstring for table schemas. Summary:
- all users: user x artist x week plays; user x recording first week/span/plays;
  artist-level listens that MLHD+ couldn't match to a recording (`*_partial`)
- 1/8 of users: full raw history (exact timestamps, releases)
- id = last 15 hex digits of the MBID as int64; `*_map` tables map back.

Storage: short-term cap 150 GB (raised 2026-10-08), long-term <= 50 GB. Projected peak ~110-125 GB (sealed tables, ListenBrainz, temp space); trim to ~40-55 GB after the analysis. Plan after ingest: re-encode
ids densely (~20-30% saving), derive what we need from raw, trim raw sample.

## Operating the ingest
    ops/ingest.sh status   # progress, throughput, ETA, disk, errors
    ops/ingest.sh stop     # pause (progress kept)
    ops/ingest.sh start    # start/resume (launchd; restarts on crash/reboot)
Output: `data/mlhd/`, log: `data/mlhd/_logs/ingest.log`.

## Ingest log (2026-10-07/08)
Ran 23:23 -> 06:41 (~7.3 h, 277 GiB streamed). Output 59 GB in `data/mlhd/`.
- 594,415 users; 21.08B recording-matched listens + 6.22B unmatched ("partial") listens,
  of which ~28% carry no id at all (counted per user in `users_partial.n_nothing`).
- 613k artists, 955k releases (raw sample only), 6.69M recordings; no id collisions.
- Rows: user_artist_week 4.78B, user_recording 3.69B, user_artist_week_partial 1.45B.
- Raw sample: 74,660 users (12.56%). Explore share: 50.03%.
- `pipeline/validate_mlhd.py`: all 25 integrity checks pass (exact per-user accounting
  between tables, sorted/unique keys, raw sample == summaries, totals == ingest state).

Incidents, both fixed:
1. Concurrent DuckDB compactions shared a temp dir and clobbered each other's spill files
   (one crashed; others could have been silently mixed). Fixed with per-process temp dirs;
   all 9 archives finished before the fix were deleted and re-ingested.
2. Size check raced with another worker's tmp-file rename -> harmless crash, resumed from checkpoint.

## Next
1. Shrink storage toward <= 50 GB (dense ids; ~20-30%) — not yet done, needs a decision
   on deleting the current files afterwards.
2. Exploration on the `explore` half only: build the artist "market" from user_artist_week
   (+ _partial), define bets, compare taste models.
3. ListenBrainz ingest (outside check, 2015-2026).

## Step 1 findings (explore half; full output in analysis/out/)
- Sample is a ~2012-13 snapshot of active Last.fm users with backfilled history: active users
  grow 19.6k (2005) -> 295k (2012); 97% of histories end 2012-13; data ends ~mid-2013.
  => measure popularity as penetration (share of active users), ideally within a fixed panel
  (composition of the user base changes a lot); 2-year forward windows only for bets <= mid-2011.
- Median history 4.3 y (76% >= 3 y, 38% >= 5 y): early-vs-late persistence test is feasible.
- 22.8% of listens unmatched (6.3% no id at all); per-user unmatched share median 20%, p90 39%.
  16.6% of user-artist pairs exist only in unmatched listens.
- Onboarding: new-artist rate is ~40/wk in a user's first week, ~8/wk at 3-6 months, ~4/wk later
  -> exclude roughly the first 26-52 weeks of each history from bets.
- After first listen: 32% of new artists get a single play, 41% one week only; 34% active >= 4 weeks.
  Median user: ~190 new artists/yr, ~68 committed (>= 4 weeks); ~200 committed bets in total.
- 581k artists; top 1% get 76% of plays.
- Strict breakouts (<0.1% -> >=1% penetration in 2 y): ~250-290 artists/yr. 93% of users have
  zero committed early bets on one -> hit-counting is far too sparse; use continuous returns on all bets.

## Step 2 status (2026-10-08, explore half only)
Report page: https://claude.ai/artifact/GLyaqWkJrEnJKPJNeG2zPt (source: analysis/report/index.html, data: analysis/out/report/).
- Model A (prescience), all controls: persistence across separate periods 0.16, ~45% of spread not luck, impostors ~1%.
  Stable 0.14-0.19 across all settings; scene control removes ~1/3 of the raw signal.
- B (community, with month x community fix) 0.26 and D (discernment) 0.25, but impostors explain 16% / 11%.
- C (durability, LB 2026) weak after controls (0.09).
- Agreement: A-D 0.45, A-C 0.25, A-B 0.18, C-D -0.12; first factor 41% (chance 25%).
Open: community-level momentum for B; music-news/release timing; influence; finer D confounds; ListenBrainz era comparison.

## Sealed-half confirmation (2026-10-09, frozen plan in SPEC.md)
Run once at 09:19-09:57 (two earlier attempts stopped before producing any sealed result: a too-strict
reproducibility check, then an out-of-scratch-space failure in the community-popularity step).
**All 12 candidates confirmed** under the frozen rules (Holm within families, 3-year stability).
Size replicated (sealed estimate inside the explore 95% interval) for 11 of 12; community-leading/scenes came
in lower (0.035 vs 0.053). Durability/scenes is borderline (0.006, two-sided 95% interval includes zero; passes
the frozen one-sided Holm test). Full table: analysis/out/sealed_run.log, analysis/out/confirmation.json.
| Model | Sealed (95%) | Explore (95%) |
|---|---|---|
| Discernment, songs (primary) | 0.230 [0.219, 0.243] | 0.241 [0.229, 0.254] |
| Discernment, artists (primary) | 0.163 [0.159, 0.168] | 0.161 [0.157, 0.166] |
| Discernment, scenes (primary) | 0.104 [0.098, 0.112] | 0.110 [0.103, 0.118] |
| Community-leading, songs | 0.244 [0.230, 0.257] | 0.249 [0.236, 0.262] |
| Community-leading, artists | 0.214 [0.209, 0.219] | 0.214 [0.209, 0.219] |
| Prescience, songs | 0.211 [0.197, 0.224] | 0.219 [0.206, 0.230] |
| Durability, songs | 0.191 [0.179, 0.203] | 0.186 [0.173, 0.200] |
| Prescience, artists | 0.148 [0.144, 0.154] | 0.144 [0.140, 0.150] |
| Durability, artists | 0.069 [0.064, 0.074] | 0.066 [0.062, 0.071] |
| Prescience, scenes | 0.061 [0.055, 0.069] | 0.061 [0.055, 0.069] |
| Community-leading, scenes | 0.035 [0.027, 0.043] | 0.053 [0.046, 0.061] |
| Durability, scenes | 0.006 [-0.001, 0.013] | 0.012 [0.004, 0.019] |
