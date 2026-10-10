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
