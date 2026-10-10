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
Report page (superseded by the write-up below): source analysis/report/index.html.
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

Write-up for a general reader: https://claude.ai/artifact/GLyaqWkJrEnJKPJNeG2zPt (source: analysis/writeup/; data built by analysis/build_writeup_data.py).

- 2026-10-10: freed 22.4 GB before the ListenBrainz ingest: deleted agg.parquet for 200 variant/sweep candidates and analysis/out/cand/_superseded. Kept every scorecard.json/meta.json and the full folders of the 12 main and 12 sealed candidates. Any deleted agg can be rebuilt with analysis/taste_models.py using the settings in its meta.json.

## ListenBrainz replication (2026-10-10, plan frozen in LB_PREREG.md before the run)
8 of 9 main measures confirmed (community-leading/scenes not). 24 of 32 plain-language findings held (MLHD+ 29): misses
P2a/b (too few cases), P4a (2.6x, bar 2x), P10a/b/c (recency), P11b (reversed: bad taste hurts more on LB), P11c. P16 held.
Era test passed: taste predicts as well or better in 2019-2023 than 2007-2012. Details: LB_PREREG.md, analysis/out/lb_report.txt.

## ListenBrainz long-run questions (2026-10-10, exploratory: after the frozen LB run, no untouched data left)
- Same people (analysis/lb_longrun.py A): panel active 2010-14 and 2021-25 (7.5k). Gap best-worst fifth widened within the
  panel too (+4.5 -> +9.0 points; worst fifth fell), so it is not just who joined. Top 10%/5% tenfold edge fell in the panel
  (1.97x -> 1.41x; 1.81x -> 1.30x; ranges wide), and people seen only early (left before 2021) had a very large edge (4-5x),
  which inflated the early-era takeoff numbers. (Script labels that group "newcomers" in both periods; early = left-before-2021.)
- A decade later (B): rated through 2015, followed 2017-2025. 2015 top fifth in that year's top fifth: 28% at 2 years ->
  22% at 10 (chance 20%); growth gap +7.9 points -> ~+2 (range includes 0). Top 1% (54 people) still 57th percentile, 33% top
  fifth at 9-10 years (wide). Taste mostly fades over a decade (prescience, artists; single-year later scores are noisy).
- Careers (analysis/lb_careers.py): picks 2012-19, artist's yearly listeners 1-6 years on vs similar picks. Best fifth's
  finds +1.5..1.9% at 1-3 years, fading to 0 by 6; worst fifth's keep falling, -3.6% -> -9.0%. Good pickers are early, not
  picking longer careers; bad pickers pick lasting losers.
- Score someone today (analysis/lb_today.py): split-half reliability on 2019-25 picks similar per pick to MLHD+; typical
  recent LB user has more picks (278 song picks vs 173), so a 75th-percentile person's true range is 46-89 (MLHD+ 41-90);
  1,500 picks: 63-84.
- Drift vs noise (analysis/lb_drift.py): later-year score reliability is flat, but the noise-corrected correlation with the
  2015 score falls steadily (discernment songs 0.44 at 2y, 0.30 at 3y, ~0.2 at 6-7y, ~0.04 at 10y): real drift.
- Decade chart now discernment songs (analysis/lb_decade.py), 1-10 years: top fifth still top 36% -> 19%; bottom fifth
  still bottom 34% -> 23% (bad taste persists a little longer).
- Careers tenfold: top 1%'s finds 10x bigger vs similar 3.1x at 1y -> 1.6x at 6y (20 vs 12 per 1,000); lead in counts grows.
- All measures over a decade (analysis/lb_drift_all.py, two-year later windows): songs/artists decay steadily but keep a
  small real remnant at 9 years (noise-corrected 0.09-0.21; prescience songs most lasting 0.50 -> 0.21); scenes too noisy.
  The single-year 10-year point (2025, Jan-Aug) understates. Decade chart: prescience songs default, discernment toggle;
  prescience bottom fifth still 31% bottom at 10 years (top fifth 22%).

## Taste-scoring site (site/, 2026-10-10)
Reference data in data/site (~3 GB, from LB). Score = prescience vs similar picks (same month, size) with the project's
corrections, simplified for outside visitors; agrees 0.71 with the frozen score (~0.95 disattenuated); reliability 0.65 / 0.81
(artists) and 0.74 / 0.87 (songs) at 110 / 250 judged finds. Engine reproduces builder scores exactly. Not deployed yet.
