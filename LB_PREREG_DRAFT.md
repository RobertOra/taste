# ListenBrainz: what we expect, written before looking (DRAFT for Robert's review)

ListenBrainz (LB) is our only dataset that has never been analysed: different platform, different people, 2005-2026.
Nothing below has been run on LB. Once Robert approves this draft it is frozen (committed), the adapted code is
committed, and each test runs once.

## What LB is
- 2.85 billion listens, Oct 2002 - Sep 2026 (MD5-verified). About 95,800 listeners; few before 2014
  (1,400 in 2005, 9,700 in 2013), tens of thousands from 2018 (66,700 in 2026).
- Artists: 86% of listening links to a MusicBrainz ID by name; the rest keeps a name-based id.
- Converted to the MLHD+ layout as a third "half" (lb) and built with the same frozen code (same pick rule, fixed panel,
  leave-one-out, controls: scene, artist age, momentum, country, release timing), with LB's own time-respecting scenes.
- Scope: artist level. Songs and community-leading need separate heavier pipelines (later, if wanted). Durability is
  circular on LB (its outcome is LB's own 2026 popularity), so it is not run.

## Part 1 - Main replication (the frozen confirmation rule, applied to LB)
Measures: Prescience (A) and Discernment (D) for artists, main settings, horizon 12 months.
Rule (as frozen for MLHD+): the impostor-adjusted forward prediction's 95% interval is above 0, Holm-corrected across
the two (one-sided, 5%), and the corrected 3-year stability is above 0.
Expectation from MLHD+ (sealed): A artist 0.15, D artist 0.16. LB is smaller, so wider intervals are expected.

## Part 2 - Plain-language findings, replicated
Same code and definitions as on MLHD+, with LB's longer timeline: rating cutoffs C = 2007 ... 2023, picks judged in
C+2 ... C+3 (outcomes end by Sep 2026). Each confirmed if its 99% bootstrap bound clears the same bar as on MLHD+
(stated per item). Thirteen tests:
1. Best fifth vs worst fifth: their later new artists grow tenfold more often (ratio > 1). [P1a]
2. Top 1%: tenfold takeoffs vs similar artists > 1 (lowered from > 2: the LB top 1% is a few hundred people). [P4a]
3. Niche artists: 2 good pickers vs none, extra growth > 0. [P5a]
4. Each good new fan adds more growth than each ordinary new fan. [P5c]
5. Small artists: a good new fan vs an ordinary one, extra growth > 0. [P6a]
6. Within a person, most-replayed quarter of picks beats least-replayed. [P8]
7. Getting hooked pays off more for top-fifth than bottom-fifth pickers. [P9]
8. The recent record separates people more than the old one (old = C-3..C-2, recent = C-1..C). [P10b]
9. Bottom-fifth pickers' new artists flop more often than middle-fifth pickers'. [P11a]
10. Good taste helps more than bad taste hurts (asymmetry > 0). [P11b]
11. The gap is larger in Indie & alternative than in Jazz, blues & classical. [P13a]
12. Rated on one genre, people separate on their other genres (average gap > 0). [P14a]
13. Same people, years 3-4 of listening vs years 1-2: extra growth > 0. [P12]
Multiple testing: 99% bounds, roughly Bonferroni for 13 tests at 5% overall.

## Part 3 - The era test (does taste still work when algorithms recommend?)
Eras by rating cutoff: 2007-2012 (before streaming took over), 2013-2018 (streaming and playlists),
2019-2023 (the algorithm era). Measures: A and D for artists, and the best-vs-worst tenfold ratio.
- E1. Taste predicts in every era: in each era, the forward prediction's 95% interval is above 0 (A and D).
- E2. The algorithm era is not much weaker: forward prediction in 2019-2023 is at least half of 2007-2012's (99% lower
  bound of the ratio > 0.5), for A and for D. This is the website condition ("era mismatch isn't a problem").
- E3 (descriptive, same people): for listeners rated in both an early and a late era, how much of their rank carries
  over across eras, so changes in who uses LB can't masquerade as a change in taste.
Caveat stated in advance: the early era has few listeners (a few thousand), so its intervals will be wide; if E2 is
undecidable because the early era is too noisy, we say so rather than calling it.

## Decisions for Robert
- E2's threshold ("at least half as strong") is a judgment call: it decides the website condition. Alternatives: at
  least two-thirds, or "not significantly weaker". I propose one half.
- Scope (artist level only) and the lowered top-1% bar (test 2) are judgment calls too.
- Anything you'd add or drop?
