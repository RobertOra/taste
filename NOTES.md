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

### Site reference rebuild (decided 2026-10-13; done 2026-10-14, now the live local pack)
1. Song identity by normalized name (case, spacing, punctuation; drop feat./remaster/edit/explicit/version/video labels; keep
   remix/live/acoustic/slowed separate). Needs song-name text: re-stream the LB dump (~253 GB, ~10 h) saving rec_name_h -> text.
   Fixes spelling splits (e.g. "Weird Fishes/ Arpeggi" -> "Weird Fishes / Arpeggi" in Dec 2024 faked +699%) and rare-variant 0 -> 0 finds.
2. Prescience among settled listeners (t, on LB 26+ weeks), as the study's fixed panel did; the 2025 LB newcomer wave inflates
   all-listener growth for established artists (LE SSERAFIM 2.34x all vs 1.10x settled). Check reliability before switching.
3. One warm-up only: the first 26 weeks of a history, no restarts after gaps, even for sparse starts (Robert's call). Same rule for
   reference listeners. Expect histories with a few stray early plays to score differently (those plays no longer end the warm-up early).
4. Store each song's own excess as well as the artist-month group's, to test empirically whether individual songs or groups
   make the better score (split-half stability and predicting later years' scores).
Done 2026-10-14 (data/site_v2, site/static/data; old pack kept in data/_site_static_data_v1, outside the deployed folder):
- LB dump 2692 re-streamed for names (pipeline/lb_names.py; one dropped connection at 69% recovered by reconnecting; MD5 matches
  the published one). 82.2M spellings -> 70.7M normalized songs (pipeline/lb_norm_songs.py; site/normalize.py = engine.js normName).
  A normalized song's artist is the smallest artist key among its spellings (deterministic).
- Settled prescience shipped as song_A / artist_A (SETTLED=1 in build_pack_meta.py): reliability at 110 finds 0.71 vs 0.72 (songs),
  0.58 vs 0.60 (artists); agreement with the study 0.884 vs 0.869 (songs), 0.733 vs 0.727 (artists). Kept for matching the study.
- One warm-up per history (meta warmup "single"); reference people now 16,223 (artists) / 18,921 (songs); intro says "about 16,000".
- Item 4, individual songs vs artist-month groups (site/songs_vs_groups.py, settled prescience): stability between artist halves
  0.618 vs 0.732, predicting 2022+ from 2016-2020 0.391 vs 0.411. Groups win on both: kept.
- Checks: every shard decodes (check_pack); mirror vs reference 40 people, 100% exact finds, Spearman 1.000 on all four measures;
  engine.js = score_pack.py on a test history (Spotify, YouTube, and both); full page upload in headless Chrome, no errors.
- A test history's scores moved by a few points (settled listeners, one warm-up); artists it played before a long gap
  now count (the warm-up fix); slow burns and too-recent artists still don't, by design.

### Songs added to the write-up (2026-10-13; SONG_PREREG.md for the tested ones)
Tested before running (hidden half / ListenBrainz): S1 top 1% songs tenfold 13.2x / 4.4x (held, held); S2 songs vs artists,
same people 2.9x / 1.7x (held, missed narrowly); S3 getting hooked pays off more for top song pickers +4.2 / +3.7 points
(held, held; LB song plays input fixed first, disclosed). Descriptive song versions with Songs/Artists switches: ladder
thresholds and growth, eras (LB), habits vs track record (13.7x vs 1.7x), careers (LB), genre gap and genre-vs-others.
Song data is the 1-in-8 raw sample on MLHD+ (~34k people per half), everyone on ListenBrainz.
- 2026-10-13: freed 8.5 GB (Robert approved): deleted data/_ckpt (finished LB song checkpoint), data/derived/community,
  comm_prior (community-leading inputs) and scene_bets (scene-measure inputs). Results are saved; all are rebuildable with the
  pipeline scripts. data/derived/market was kept: the artist prescience outcome reads it. Project now 136 GB.
- 2026-10-13, exploratory (rough: LB 1-in-10 users, artists, month x size [+ momentum] only): counting "slow burns" (artists
  first reaching 4 weeks within 26 later than 26 weeks after the first-ever play) adds ~50% more finds (Robert +55% artists,
  +34% songs; LB sample +28%). Slow burns grow +4.7% vs similar (size + momentum), only 8% picked while rising fast (regular
  finds 22%), but separate people slightly less: best-minus-worst-fifth growth gap 8.8 -> 7.2 points; top-1% tenfold 1.91x ->
  2.16x (1.79x -> 1.42x without momentum). Conclusion: the first-listen clock costs coverage, not correctness. Not adopted.
  Also tried on Robert only: "4 weeks or 10 plays" adds ~5% finds (+27 artists, +16 songs); kept 4 weeks (site must match study).

### Era gap: better pickers or better measurement? (2026-10-14, exploratory; analysis/eras_window_check.py)
eras_yearly rates people for year Y on all picks up to Y-2, so later years rate on longer histories (artists: 138 -> 382 rating
picks per person, 2010 -> 2025). Rated instead on a fixed window (Y-4..Y-2; 125-183 picks), the best-minus-worst gap follows the
same path: songs +9.7% (2010), +20.6% (2015), +27.3% (2020), +31.6% (2025) vs +10.1 / +19.9 / +25.2 / +29.5 on all history;
artists +5.3 / +6.7 / +8.2 / +8.9 vs +5.4 / +5.8 / +8.5 / +9.2. Not a measurement artifact. Who uses ListenBrainz still changed.
Tried and removed (Robert, 2026-10-14): top 10% on the year-by-year growth chart (close to the best fifth) and top 1% on the
career growth chart. Top 1% vs the rest of the best fifth (analysis/careers_top1_check.py): no difference beyond noise at any
year (artists 6 years: -4.6%, range -12.0 to +2.4; songs -3.6%, -11.0 to +4.5). Hint for artists only: the top 1%'s finds lost
half their listeners 1.13-1.18x as often as similar ones (rest of best fifth ~1.0x) while hitting tenfold far more often: a bit
more boom-or-bust.
Why the best fifth's songs do better over the years (analysis/eras_why.py): not the same people improving. People rated in both
2010-13 and 2021-25 (4,512): best fifth +3.1% -> 0.0%, worst -10.6% -> -25.6%; everyone else: best +0.8% -> +10.6%, worst -10.8%
-> -13.1%. (Correction below: the panel's drop is aging, not a sign that the rise is only newcomers.) Outcome spread grew only modestly
(sd 0.58 -> 0.73), not enough to explain it. Artists: same people best +1.8% -> +0.7%, worst -2.9% -> -7.5%.

### How early can you tell an artist will break out? (2026-10-14, exploratory; analysis/early_signal.py)
LB artists whose first listener came 2012-2020. Breakout = top 1% of the birth-year cohort by listeners in year 3. Logistic
model on half the artists, scored on the other half; "flag the 1% rated most promising". Genuinely new artists (MusicBrainz
release in the 12 months before their first LB listener; 35,639 artists, 362 breakouts, 360-640 year-3 listeners needed):
after 1 month, the flagged 1% held 13% breakouts (base 0.9%), 14% of all breakouts caught (AUC 0.69); 3 months 16% / 17%
(0.78); 6 months 25% / 27% (0.84); 12 months 43% / 46% (0.93); 24 months 66% / 71% (0.99). Mostly wait-and-see: a year in,
you catch about half. Who the fans are (committed fans, good pickers) adds almost nothing beyond listener counts and speed for
these top breakouts, although good-picker fans go with more growth on average (fan value). All LB-born artists (incl. older
artists new to LB) are much easier (AUC 0.74 at month 0, 0.92 at 6 months, top 0.1% bar) because many arrive already big.
Top 0.1% among new artists: only 40 breakouts, not used.
Songs (analysis/early_signal_songs.py; study LB song ids; new song = its artist had a release in the 2 months up to its first
listener; 4.9M songs, breakout = top 1% of cohort, 41-68 listeners in year 3): far more predictable early. Flagged 1% after
month 0: 43% breakouts, 42% of all breakouts caught (AUC 0.89); 1 month 52% / 51%; 6 months 62% / 61%; 12 months 67% / 67%.
Likely because a new song's first-month audience mostly reflects its artist's existing fans (songs by already-popular artists),
not because song breakouts are easier to spot. Not run: songs by brand-new artists only. Good pickers add nothing here either.

### Best fifth by tenure (2026-10-14, exploratory; analysis/eras_tenure.py, eras_tenure_window.py)
Corrects the panel reading above: the yearly rise in the best fifth's song growth happens for newer users (2-4 years on LB:
+2.8% in 2012 -> +15.1% in 2025) and longer-time users (5+ years: -0.4% -> +9.0%) alike, so it is not who joined. The panel's
best fifth fell because the same people aged a decade (taste fades). At any year, newer users' best fifth beat longer-time users'
on songs by ~4-9 points, also when everyone is rated on only Y-4..Y-2 (so not stale ratings). Long-time users' worst fifth got much
worse on songs (-13.6% -> -20.9%; newer users' worst fifth stayed ~-8 to -11%). Artists: no steady tenure difference in the best
fifth; newer users' best fifth a little ahead since 2021. Why the best fifth's songs do better over time: unexplained (not
measurement, not newcomers, not noise: steady with tight yearly ranges; outcome spread grew only ~25%).

## Music trends (2026-10-14, exploratory; ListenBrainz; outside the taste question)
Shared table: data/derived/song_month/ (analysis/build_song_month.py; each song's listeners and plays per month, 7.9 GB; plus
user_month_lb). Keep while trends 5/6 are open; delete in the disk trim.
1. Do songs fade faster? (trends_fade.py; 275k songs peaking 2010-2022 with >= 20 listeners). Whole audience: a song's share of
   active listeners a year after its peak fell from 22% of the peak (2010) to 12% (2021-22). Same people (of those who played it at
   the peak and were still listening, how many still played it): a year on ~7% (2010) -> ~6% (2022), flat since ~2013; 3 months on
   17% -> 12-13%, flat since ~2016. So most of the faster fade is LB's changing crowd, not people dropping songs faster. Peak years
   2023-24 left out (only late-peaking songs).
2. One-hit wonders (trends_onehit.py, trends_onehit_check.py). New artists' biggest song's share of their first three years:
   median 11% (2010) -> 20% (2019-22); artists with >= 50% on one song 1% -> 13-15%. Per listener (spelling-proof): songs by the
   artist played per listener-month 3.4 -> 1.65; months with just one of their songs 57% -> 83%. A real shift from albums to single
   songs (in LB's crowd, which also changed).
3. Niche or homogeneous? (trends_homog.py; 5 samples of 2,000 people a year; top 100 songs / top 30 artists each). More niche:
   artist overlap between two random people 1.69% (2010) -> ~1.0% (2020s); song overlap ~0.17% -> ~0.12% (2024 bump 0.15%);
   concentration in the most common items down too. Same people (4,942, 2014/2019/2024): artists 1.45% -> 1.15% -> 1.06%, songs
   0.21% -> 0.14% -> 0.14%. New finds' overlap small and roughly flat (0.03-0.05% -> 0.02-0.04%). Part may be ever more music released.
4. Do people stop discovering? (trends_discovery.py). Same 2,918 people (started 2008-14, listening every year 1-9): new artists got
   into per year 74 (year 1) -> 45 (year 9), discovery share of plays 40% -> 22%, plays flat (~8,700). Steepest in years 1-3, then a
   slow steady decline; it never stops. Later starters (2016-18) get into more artists (86 vs 61 in year 1) but decline the same
   way, so it's a listening-life pattern, not the era. Tenure, not age.
3b. Tribes or eclectics? (trends_niches.py; yearly scenes, 5 x 2,000 people, top 30 artists). Overlap within a niche (same main
   scene) 6.1% (2010) -> ~4% (2020s, noisy); across niches 1.5% -> ~0.85%; within/across ratio ~4 -> ~4.6. People grew apart both
   inside and across niches, so no tighter tribes. Breadth per person 22.7 -> 16.8 effective scenes, share in main scene 24% -> 32%,
   but the same 4,942 people stayed flat (21 -> 22 -> 21; 25% -> 26%), so that's the changing crowd. Caveat: 200 scenes a year while
   LB's artists grew ~5x (0.6M -> 3.2M), which by itself lowers within-scene overlap; the same-people panel also fell (5.0% -> 3.2%).
5. Hidden gems (trends_gems.py; artists first on LB 2015-22 with >= 10 people who tried them in year 1). Loved = top 10% of the year
   for "kept playing" (29% kept vs 8%). Never spread = no more listeners in year 3 than year 1. Ordinary artists reweighted to the
   same birth year and starting size. All artists: loved 65% never spread (ordinary 83%), grew 3x 9% (4%); loved by good pickers
   57% / 13%. New artists (release in the year before): loved 24% never spread (43%), grew 3x 33% (20%); with good pickers 20% / 37%.
   Over time (all artists) loved never spread 54% (2015) -> 72% (2022), ordinary 73% -> 89%; new artists' loved flat ~21-29% while
   ordinary rose 38% -> 51%. Being loved roughly doubles the chance to grow, but most loved music still never spreads.
Write-up: section "Music over time" (#overtime, after Bad taste, before How sure we are), built 2026-10-14 from these results
(analysis/build_trends_data.py -> analysis/writeup/trends.json): fading (indexed to 2010), albums to single songs, niches (indexed),
discovery over a listening life, hidden gems (All / New artists). Gems over time folded into the text.
3c. Two fans of the same artist (trends_fans.py; same most-played artist that year, overlap of their other 29 artists, each fan
   counted once): ~6% flat 2010-2025 (6.3% -> 5.5% in 2021-22 -> 6.3%). Counting each pair once rises 5.2% -> 8.6% (giant fandoms
   supply most pairs); each artist once falls 7.5% -> 5.7%. On the chart as share of all 30 (shared favorite counted): 9.4% -> 9.4%.
   Write-up: niche chart now in real percentages with this third line; title "People grew apart, except fans of the same artist".
   Song-fading chart removed (Robert, 2026-10-14); the eras sentence says songs fade only a little faster for the same listeners.
3d. Four similarity measures (trends_similarity.py; everyone with enough listening each year; cosine of play shares over artists /
   200 yearly scenes / genre families (tagged artists, 74% -> 61% of plays); top30 = the earlier overlap). Random pairs 2010 -> 2025:
   top30 .017 -> .010, artists .028 -> .015 (-45%), scenes .17 -> ~.145 (-15%, noisy: scenes rebuilt yearly), genres .51 -> .47 (-8%).
   So people drifted apart mostly in exact artists, much less in kinds of music: mostly more choice within similar broad tastes.
   Same niche: top30 .062 -> .039, artists .095 -> .064, genres .75 -> .69 (scenes .61 -> .66, partly by construction).
   Fans of the same artist: top30 flat .094, genres flat .77 -> .76, but artists .32 -> .38 and scenes .49 -> .54 (weighted vectors
   include the shared favorite; fans may have concentrated more on it).
   Changing faster? Similarity with oneself the year before (weighted artists): .52 (2011) -> .48 (2016) -> .54 (2025); at 2-4 years
   of listening .52 -> .49 -> .57; same 3,979 people .504 -> .511 -> .509. Scenes ~.85 -> .87, genres ~.94 flat. Tastes are not
   changing faster; if anything a bit steadier since 2016.
   Fans recomputed with their shared favorite left out (2026-10-14): artists .097 -> .097 (flat), scenes .385 -> .436, genres .727 -> .707.
   Write-up: niche chart replaced by "People drifted apart in artists, much less in kinds of music" (weighted similarity, Artists /
   Scenes / Genres switch, fans / same niche / random, 2010 = 100; no niche line in the scenes view, as niches are scenes), plus a
   sentence that tastes don't change faster year to year (no chart; Robert agreed).
   Similarity chart removed (Robert, 2026-10-14): the artist-level drop is mostly the bigger catalog; replaced by one paragraph
   ("Are we all in our own bubbles now? Not really": genres 92% of 2010, fans flat, tastes not changing faster).
   Gems additions (2026-10-14): loved + 2+ good pickers: all 49% never spread / 18% tripled; new 18% / 41%. Top 1% loved (kept ~45%):
   all 53% / 15%; new 15% / 44%; top 1% + good picker: all 45% / 22%; new 12% / 50%. By tenth of kept rate (not size-matched),
   tripling rises steadily from the middle up (all 4% -> 9%; new 18% -> 33%). Dose-response: more love, better odds.
   Gems chart redesigned (2026-10-14): five rows (ordinary, loved, + good picker, + 2+ good pickers, top 1%), four bands (none, some,
   3-10x, 10x+), title "The more loved, the better an artist's odds of spreading". 10x: all loved 1.3% vs 0.4%, 2+ good pickers 3.5%;
   new top 1% 10%, ordinary new 3%.
5b. Are hidden gems good? Overhyped? (trends_gems_quality.py; same artists; gems = loved (top 10% kept rate) and never spread).
   Fans (rated, first 2 years): gems 25% good / 26% poor pickers, same as ordinary artists (25/24); loved-and-spread 33/17.
   Of rated people who tried them in year 1, the share who got into them: gems good pickers 27%, poor 27% (ordinary 11% / 10%;
   loved-and-spread 31% / 28%). Fans still listening 24-35 months later (among those still listening to music): gems 35%,
   ordinary that never spread 25%, ordinary 31%, loved-and-spread 64% (growth may itself keep fans).
   So gems are not bad music loved by bad taste: broadly liked, about equally by good and poor pickers, and their love lasts longer
   than comparable artists'. What sets loved-and-spread apart is more good pickers among the fans (fits the fan-value results).
   Overhyped: of 6,535 artists that tripled, 19% were in the bottom 30% by kept rate (kept ~1% of people who tried them vs ~9%);
   21% were loved (top 10%). Splitting gems by whether a good picker got into them is circular (not used).
   New-artist share: hidden gems 5%, loved-and-spread 51%, ordinary 7%, overhyped 30% (new = MB release in the year before; many
   artists lack dates). Write-up: paragraph "What makes a hidden gem?" under the gems chart (no new chart; Robert).

6. Genres (trends_genres.py): share of new finds (tagged artists) 2010 -> 2025: pop 9.7% -> 18.1%, hip hop 6.8% -> 13.8% (2020) -> 10.4%,
   electronic peak 25% (2015) -> 19.5%, rock 17.5% -> 12.8%, indie 20% -> 17.5%. Plays: pop 8.6% -> 23.9%, rock 22% -> 11.7%.
   Same 2,510 people 2012-14 -> 2022-24: nearly unchanged (pop 11.2 -> 12.4, rock 14.0 -> 12.4). So the crowd changed, not people.
7. Old vs new music (trends_catalog.py): by MusicBrainz first release, artists under 3 years old fell 12.5% (2010) -> 5.3% (2025) of
   plays, but dated coverage fell 89% -> 80% of plays, and by first appearance on LB, artists new in the last 3 years were a flat
   8-9% of plays 2012-2025 (undated among them 4.2% -> 6.7%). No solid evidence new music is losing ground; not charted.
8. Loved by a few or liked by many? (trends_divisive.py; artists with >= 3 keepers; split at medians of kept rate and plays per
   keeper; size-matched). New artists: liked by many 32% never spread / 22% tripled / 2.8% tenfold; loved by a few 46% / 16% / 1.7%;
   both 27% / 28% / 3.7%; neither 49% / 12% / 0.6%. All artists: many 80/3, few 80/4, both 65/9, neither 87/2. For new artists it is
   better to be liked by many than loved by a few; divisive is only a little better than forgettable.
9. How far ahead (trends_ahead.py; 6,101 LB breakout artists 2012-21: peak >= 50 monthly listeners and >= 10x their first half-year;
   breakout = first month at half the peak). Median months before the breakout: top 1% -6, rest of top fifth -12, middle -15, bottom
   -15, everyone -17; got in before it 26% / 19% / 14% / 13% / 14%; a year or more before 10% / 7% / 6% / 5% / 5%.
   Examples (top-1% picker >= a year early): Dominic Fike (48 months), Halsey, Cardi B, BLACKPINK, Joji, Martin Garrix, black midi...

## Why good taste fades (2026-10-14, exploratory; analysis/why_fade.py)
Top fifth on 2011-15 finds (1,188 rated again on 2020-24): stayed top fifth 294, faded to the bottom half 565. Same habit changes
for both: finds a year 36 -> 37 vs 29 -> 31; brand-new share 14% -> 15% both; plays up for both; genre mix similarity to their own
earlier mix 0.78 both; their early genres' growth 1.01x both. Stayed-good shifted to smaller artists (mainstream ratio 1.00 -> 0.65 vs
faded 1.09 -> 1.02) but per-person correlation with the later score ~0. Habit changes explain R2 0.003 of the later score (early
score alone 0.003). Not exploring less, listening less, ignoring new music, or genre loyalty: judgment itself drifts.
- 2026-10-14: deleted data/derived/song_month (8.0 GB; rebuild: analysis/build_song_month.py, ~20-30 min) and
  data/_site_static_data_v1 (0.8 GB; old site pack, also in the taste-test repo). Robert approved.
- 2026-10-14: site live at https://robertora.github.io/taste-test/ (repo RobertOra/taste-test made public with Robert's OK; it holds
  only the published site files). Research repo pushed by Robert to RobertOra/taste (private). Live check: a test history scores the same as locally;
  the study renders with no errors on desktop and phone. Updates: bash site/deploy.sh "message".

## Site requests (2026-10-14)
GitHub Pages rate-limited the live site after my test runs (~4,600-5,200 range requests per scoring; ~20k in 30 min). Cause: every
name filed by its own hash, so ~7,500 lookups hit ~5,000 shards. Fix (exact, results identical): file everything about an artist in
the shard of slot = name_hash(norm_name(artist)) (site/build_pack_slots.py; SHARD_BY=artist in build_pack_files/meta), plus a 4.6 MB
Bloom filter of slots so unknown artists cost no request. A test history: 5,246 -> 1,487 requests, same scores (JS old vs new output
identical except timing; mirror vs reference 100% exact picks). Largest shard 864 kB (one artist with ~23,700 songs). Hashed-layout
pack kept in data/_site_static_data_hashed (outside the published folder) until the new one is confirmed live.
Live (2026-10-14, one run): 13.6 s for all three views, 1,487 requests, 19.8 MB + the 4.6 MB filter, scores 71 / 67 / 85. Testing rule:
never run repeated scorings against the live site; test locally (site/serve.py) and do at most one live run per deploy.
Step 1 was ~1 minute in Robert's browser: Chrome's HTTP cache lets one request at a time write a given file, so ~1,500 cached range
requests to the same 16 files queued (reproduced locally with GH_CACHE=1 serve.py: 45 s vs 19 s). Fix: fetch ranges with cache 'no-store'.
Also: progress bar covers the YouTube matching (was stuck at 0% ~11 s), index and artist filter download at the same time.
Live after the fix (one run, browser cache on, this machine's network): step 1 done at 12.6 s, report at 14.5 s.
- 2026-10-14: personal listening details generalized in NOTES across all history (git filter-repo), the old GitHub repo deleted by Robert,
  and RobertOra/taste re-created as a public repo with the cleaned history. Links added between the two repos, in the site footer,
  and in the study's What's next.
