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

## Results
(to be added after the runs, unchanged above this line)
