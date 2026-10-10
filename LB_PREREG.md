# ListenBrainz: what we expect, written before looking

**FROZEN 2026-10-10 09:27**, before any ListenBrainz analysis. Reproducibility check passed: the adapted code reproduces every
MLHD+ explore result it was compared against (analysis/check_repro.py).

ListenBrainz (LB) is our only dataset that has never been analysed: different platform, different people, 2005-2026.
Nothing below has been run on LB. This file and the adapted code are committed before the one-time run
(analysis/run_lb.sh); the bars are applied by analysis/lb_report.py. Robert approved the scope on 2026-10-10 ("run
basically all the tests the same way"; E2 threshold and other judgment calls left to Claude).

## What LB is
- 2.85 billion listens, Oct 2002 - Sep 2026 (MD5-verified). About 95,800 listeners; few before 2014 (1,400 in 2005,
  9,700 in 2013), tens of thousands from 2018 (66,700 in 2026).
- Artists: 86% of listening links to a MusicBrainz ID by name (a name maps to one MBID in >= 80% of its tagged listens);
  the rest keeps a name-based id. Recordings linked the same way.
- Converted to the MLHD+ layout as a third "half" (lb) and built with the same frozen code: same pick rule, fixed panel,
  leave-one-out, controls (scene, artist age, momentum, country, release timing), LB's own time-respecting scenes, LB's
  own taste communities. Every LB listener counts (MLHD+ songs used a 1/8 sample).
- Differences forced by the data: LB has weekly song counts, not one row per listen (the song pick rule only needs weeks);
  listens whose artist name can't be linked play the role of MLHD+'s "unmatched" listens in the data-quality control.

## Part 1 - Main replication: the frozen confirmation rule
Measures: Prescience (A), Discernment (D), Community-leading (B), each for songs, artists, scenes; main settings, 12-month
horizon. Durability (C) is not run: on LB its outcome is LB's own 2026 popularity, which is circular.
Rule (SPEC.md, Confirmation): Holm-Bonferroni within families at family-wise 5% (one-sided) on the impostor-adjusted
forward prediction; families: primary = Discernment x 3, secondary = Prescience x 3 + Community-leading x 3; and the
corrected 3-year stability's 95% interval above 0.

## Part 2 - The plain-language findings: all 32, same definitions and bars as on MLHD+
P1a-P16 exactly as in SPEC.md (including the three that missed on MLHD+: P10a, P10c, P16), each with its MLHD+ bar
(99% bootstrap bound). Same code, with LB's longer timeline: rating cutoffs C = 2007 ... 2023 (picks judged in
C+2 ... C+3; good-picker counts use C = 2006 ... 2023 with picks in C+2); recency uses old = C-3..C-2, recent = C-1..C,
judged on C+2..C+3, for every C from 2008 to 2023; the going-stale test (P10c) keeps its MLHD+ design (rating years 2006
and 2007, judged through 2011). Genres come from LB artists' MusicBrainz tags with the same keyword grouping.
The top-1% bar stays at > 2x: pooled over cutoffs, LB's top 1% is about as many person-years as MLHD+'s.

## Part 3 - The era test: does taste still work when algorithms recommend?
Eras by rating cutoff: 2007-2012 (before streaming took over), 2013-2018 (streaming and playlists), 2019-2023 (the
algorithm era). Measured for Prescience and Discernment, artists (computed inside analysis/evaluate.py with the same
bootstrap draws).
- E1. Taste predicts in every era: each era's impostor-adjusted forward prediction has a 95% interval above 0.
- E2. The algorithm era is at least half as strong as 2007-2012: 99% lower bound of the ratio (2019-2023 / 2007-2012)
  above 0.5, for each measure. This is the website condition ("era mismatch isn't a problem").
- E3 (descriptive): the plain-language findings by era where sample sizes allow; same-people comparisons across eras.
Stated in advance: the early era has few listeners, so its intervals will be wide. If E2 can't be decided because the
early era is too noisy, we say so rather than calling it.

## Before the run
The adapted code is checked to reproduce the MLHD+ results it already produced (explore half) before LB is touched.

## Changes after freezing (before the affected step ran)
- top_pickers.py built the style profile (used by P7c) only for cutoffs 2007-2009, though bands used every cutoff; fixed to
  use every cutoff, as this plan states. Found by rereading the code after the run started, before that step ran. No change
  for MLHD+ (its cutoffs are 2007-2009).
- The first launch (09:27) failed on its first two steps before producing any result: one LB release group is dated 3036,
  which overflows the month field. Release dates from year 2700 on are now ignored (MLHD+ has none, so its results are
  unchanged); the run was stopped and relaunched from the start.
- headlines.py stopped with a division by zero: on LB, artists picked only by 3+ poor pickers had no tenfold takeoffs, so the
  descriptive all-good / all-poor ratio is undefined. It is now recorded as undefined (not a pre-registered test; P2a/b
  compare with similar artists). MLHD+ unaffected. The step was rerun after the main run finished.

## Results (one-time run, 2026-10-10 09:29-09:46; headlines step rerun after the fix above). Full table: analysis/out/lb_report.txt / lb_report.json
**Part 1: 8 of 9 measures confirmed** (Holm within families + 3-year stability). Not confirmed: community-leading, scenes
(0.001, 95% low -0.014; MLHD+ sealed 0.035, its weakest). Sizes vs MLHD+ sealed: discernment songs 0.198 (0.230), artists
0.135 (0.163), scenes 0.042 (0.104); prescience songs 0.234 (0.211), artists 0.142 (0.148), scenes 0.042 (0.061);
community-leading songs 0.228 (0.244), artists 0.148 (0.214). Scenes are weaker on LB across the board.
**Part 2: 24 of 32 held** (MLHD+ sealed: 29 of 32). Not held:
- P2a/P2b (3+ all-good pickers vs similar): only ~1,190 such artist-months on LB (one tenfold event); 4x 1.15 (99% low 0.34),
  10x 2.57 (bound undefined). Too few cases to test.
- P4a top 1% tenfold 2.63x (99% low 1.73; bar > 2). Same direction; misses the stricter bar. Correction to the plan: LB's top 1%
  is 614 person-cutoffs, not ~2,500 as stated above (my estimate was wrong). P4b (top 1% vs 90-95% band) held: 1.94.
- P10a 1.01 (99% low 0.70), P10b recent spread 1.59x vs old 1.47x, difference 0.08 (99% low -0.20), P10c 1.11 (99% low 0.51):
  recency does not replicate. (MLHD+: P10b held, P10a and P10c missed.)
- P11b reversed: on LB bad taste hurts more than good taste helps (top fifth +2.7 points above all picks, bottom fifth -4.7
  below; difference -0.020, 95% [-0.029, -0.009]). MLHD+: +3.5 / -2.6.
- P11c top-fifth picks do not flop more (0.99; MLHD+ 1.10).
Newly held: P16 (other genres predict a genre within 1 point: -0.9 points, 99% high -0.5), which missed narrowly on MLHD+.
**Part 3: era test passed.** E1 all six era checks hold. E2: the algorithm era is stronger, not weaker: 2019-2023 / 2007-2012 =
1.25 for prescience (99% low 1.07) and 1.13 for discernment (99% low 0.93); bar 0.5. Prescience by era 0.121 / 0.143 / 0.152;
discernment 0.130 / 0.124 / 0.146 (23k / 43k / 53k person-cutoffs).
