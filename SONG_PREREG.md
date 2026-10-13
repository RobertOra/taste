# Song ladder: predictions written before the sealed and ListenBrainz runs (2026-10-13)

The study's ladder (P4a: the top 1% of pickers' new artists grew tenfold 4.70x as often as similar artists on the hidden half,
2.63x on ListenBrainz) covered artists only. The same ladder for songs was run once on the explore half
(analysis/ladder_songs.py; analysis/out/ladder_songs_explore*.json), exploratory:

- Top 1% of song pickers (rated on songs; songs by one artist found the same month count as one pick): their songs grew tenfold
  9.34x as often as similar songs [95% 6.13, 13.66; 99% low 5.30], 239 people. Counting each artist-month once: 9.46x.
- Same people's top 1% on artists: 4.37x. Songs / artists: 2.14x [1.45, 3.22; 99% low 1.29].

Nothing about song takeoffs has been looked at on the sealed half or on ListenBrainz. Before running either, these are fixed:

## Predictions (each run once per dataset; passing = the 99% bootstrap bound clears the bar, as the study's predictions)
- **S1 sealed / S1 lb.** Top 1% of song pickers' songs grow tenfold more than 2x as often as similar songs: 99% lower bound > 2
  (P4a's bar).
- **S2 sealed / S2 lb.** Among the same people, the songs' top-1% tenfold rate is higher than the artists': songs / artists
  ratio, 99% lower bound > 1.

Reported without a bar: the full ladder, the top 0.1%, the per-artist-month version (--per-group), and 4x odds and growth.
Expectation: both pass on the sealed half; on ListenBrainz, where the artist edge was smaller (2.63x), S1 may be closer to the bar.

## Exactly what runs
1. Song outcome files with the study's settings (as analysis/out/cand/obs_A_song/meta.json, explore):
   `taste_models.py --half {sealed,lb} --model A --unit song --cand obs_A_song_{half} --perms 1 --scene yearly200 --age
   --momentum 5 --country --release --adjust additive --bets-out data/derived/bet_outcomes/A_song_{half}.parquet`
2. `ladder_songs.py --half {sealed,lb}` and `--per-group`, with the code committed alongside this file (bands, cutoffs from
   analysis/cutoffs.py, bootstrap of 1,000 draws over people, seed 1013).

## Results (each run once, 2026-10-13 12:33-12:40; outcome files matched the study's runs: sealed 7,649,897 song bets,
ListenBrainz 18,710,617 bets / 31,134 people)
| | Top 1%: songs vs similar songs | S1 (99% low > 2) | Same people, artists' top 1% | Songs / artists | S2 (99% low > 1) |
|---|---|---|---|---|---|
| Explore (exploratory) | 9.34x [6.13, 13.66; 99% low 5.30] | - | 4.37x | 2.14x [1.45, 3.22; 1.29] | - |
| **Sealed** | **13.24x** [8.67, 18.08; **99% low 8.02**] | **held** | 4.60x | **2.88x** [1.86, 4.26; **1.66**] | **held** |
| **ListenBrainz** | **4.39x** [2.34, 7.53; **99% low 2.08**] | **held** (narrowly) | 2.63x | **1.67x** [1.04, 2.28; **0.96**] | **missed** (95% low > 1) |

Without a bar: per artist-month (each album-month once) sealed 13.81x, songs/artists 3.00x; ListenBrainz 5.08x, 1.93x
[99% low 0.98]. Top 0.1%: sealed 28.5x (25 people), ListenBrainz 16.6x (93 people, 462 of the top 1%'s 953 tenfold
songs, range 2.2-28.3): on ListenBrainz half of the top 1%'s takeoffs come from the top 0.1%; the 99-99.9% bands are 2.3-3.0x
(artists 1.9-3.2x there), so most of ListenBrainz's song-over-artist edge sits in a few people at the very top.

# Round 2: getting hooked, for songs (written 2026-10-13, before the sealed and ListenBrainz runs)
The study's P9 (getting hooked pays off more for top-fifth than bottom-fifth pickers) used artists. Song version, explore half
(analysis/obs_taste.py --unit song, exploratory): rated on songs; gain from 1-4 to 10+ plays before committing, for each
song picked in C+2..C+3: top fifth +9.9 points, bottom fifth +6.3, difference +3.6 points [2.3, 5.1; 99% low 1.8].
Song plays-before-committing for sealed and ListenBrainz were built with pipeline/derive_obsession.py --songs-only (the
study's code, unchanged apart from the flag).

- **S3 sealed / S3 lb.** Top fifth's gain minus bottom fifth's gain > 0: 99% lower bound > 0 (P9's bar).

Run once each: `obs_taste.py --half {sealed,lb} --unit song` (and `--deciles` for the chart, no bar).

## Round 2 results (2026-10-13)
| | Top fifth's gain | Bottom fifth's gain | Difference [95%; 99% low] | S3 (99% low > 0) |
|---|---|---|---|---|
| Explore (exploratory) | +9.9 points | +6.3 | +3.6 [2.3, 5.1; 1.8] | - |
| **Sealed** | +9.8 | +5.6 | **+4.2** [99% low **2.2**] | **held** |
| **ListenBrainz** (corrected run, see below) | +5.5 | +1.9 | **+3.7** [2.7, 4.8; **2.3**] | **held** |

Deviation, disclosed: the first ListenBrainz run used a broken input. ListenBrainz's converted song data
(lb_convert_songs.py) has one row per user, song and week with a plays column, while MLHD+ raw has one row per listen, so
derive_obsession.py's song step (counting rows, never run on ListenBrainz songs before) counted listening weeks as plays.
That run produced empty bins (no picks with 15+ "plays") and an impossible +90% gain, not a test result. Fixed to sum plays
for ListenBrainz (MLHD+ unchanged), rebuilt the input, and ran S3 once more; that run is the one above.
