# Taste: models, parameters, tests

Living spec. Exploration on the `explore` half may use any variant below (and new ones —
add them here). Before anything touches the `sealed` half, the variants to confirm are
listed in a "Confirmation" section and committed; that commit is the freeze.

Notation: **[P]** marks the primary setting of a parameter; others are variants.

Revisions are welcome but must be explicit: every non-trivial change goes in the Revisions log at
the bottom with the date, what changed, why, and whether it was prompted by seeing results.

**Continuous parameters** (onboarding cutoff, commitment threshold, horizon, weight exponent, number of
bins/scenes) are swept on a fine grid one at a time around the primary settings (others fixed), plus a
coarse full grid for interactions. We read the *shape* of each curve: a plateau means the choice doesn't
matter; a sharp peak suggests noise; a steady trend is itself a finding (e.g. signal growing with horizon).
Peaks found on `explore` are inflated by noise (winner's curse), so any setting chosen for being best
is only believed after it is confirmed on `sealed`.

---

## 0. Corrections applied in every variant
These prevent known biases rather than define taste, so they are not varied freely.

| Correction | Why | Allowed range |
|---|---|---|
| Ignore bets in each user's onboarding period | early "first listens" are mostly music the user already knew | 13 / **26 [P]** / 52 weeks |
| Popularity = share of a fixed panel of users | the active user base grows ~15x 2005-2012 and changes composition | panel = users active at both t and t+H **[P]**; all active users (contrast only) |
| Leave-one-out | a user's own listening must not count toward the popularity they're scored on | always |
| Bet dated at commitment, not first listen | otherwise growth while the user was deciding (trend-following) counts as foresight | first-listen dating run only as a contrast, to measure that bias |
| Only bets with a full horizon of data after them | data ends mid-2013; panels thin out during 2013 | market observed to 2012-12-31 **[P]** |

## 1. Units
| Unit | Role | Notes |
|---|---|---|
| **Artist [P]** | main unit | weekly per-user detail for all users (matched + unmatched listens) |
| Song (recording) | second unit | benchmark also by song age (weeks since first appearance in data); popularity = adoption (new listeners per period) since weekly per-user plays aren't stored; commitment from plays + span |
| Scene | unit and control | clusters of artists from co-listening; also used as a benchmark dimension to split *scene timing* from *within-scene picking* |

Scene parameters: clustering method (co-listening embedding + k-means **[P]**; graph community detection),
number of scenes (~50 / **~200 [P]** / ~1000), built on onboarding-period + pre-period listening only.

## 2. Shared building blocks

**Bet** = a user's committed adoption of an artist after onboarding.
| Parameter | Values |
|---|---|
| Commitment rule | listened in >= 2 / **>= 4 [P]** / >= 8 distinct weeks; or >= 10 plays; "every first listen" (no commitment) as contrast |
| Commitment window | must be met within **26 [P]** / 52 weeks of first listen |
| Bet date | **date commitment was reached [P]**; first listen (contrast) |
| Bet weight | plays-in-first-26-weeks ^ alpha: **alpha = 0, equal [P]**; sweep 0 to 1 (0.5 = square root, 1 = proportional); log(1 + plays) |
| Min bets per user to be scored | 10 / **20 [P]** / 50 |

**Popularity ("price")** of an artist at time t
| Parameter | Values |
|---|---|
| Measure | **listener penetration: share of panel active that month who played the artist [P]**; adoption penetration (share of panel who have ever played it); play share |
| Time resolution | weekly / **monthly [P]** / quarterly |

**Return** over horizon H
| Parameter | Values |
|---|---|
| Horizon H | 26 / **52 [P]** / 104 weeks |
| Return metric | **log growth of penetration with small-count smoothing [P]**; percentile of growth among benchmark peers (outlier-robust); raw growth ratio, capped (rewards rare huge wins more: "hit-seeking"); hit indicator (top-10% growth among peers) |

**Benchmark** ("expected return" for a bet)
| Parameter | Values |
|---|---|
| Peer group | **same popularity bin x same month [P]**; + same scene; + same artist age (time since first appearance) |
| Popularity bins | 10 / **20 [P]** / 50 quantile bins of log penetration |

**Score aggregation**: weighted mean of a user's excess returns, shrunk toward the population mean
by the number of bets (empirical Bayes) **[P]**; median (robust contrast).

## 3. Taste models

### Family 1: ahead of the curve
**A. Prescience (investment model)**
Score = average excess return of the user's bets (building blocks above).
- Variants: all of section 2; plus **portfolio version** (each month's listening shares treated as holdings,
  return = growth of what you hold) as a contrast — expected to measure loyalty more than foresight.
- Side questions (not taste definitions): **sizing** — do a user's heavier bets earn more than their
  lighter ones? **exit timing** — do users leave artists shortly before they decline more than chance?

**B. Leading your taste community**
Do people with similar taste later adopt what you adopted?
- Community: **k nearest users by listening similarity in a pre-period [P]**; same scene (variant).
- k = 50 / **200 [P]** / 1000; similarity = **cosine on log plays [P]**; Jaccard on artist sets.
- Score = share of your bets later adopted by your community within H, minus the expected share for
  artists of the same popularity among that community.
- H as in section 2.

### Family 2: recognizing quality
**C. Durability**
Are the artists you committed to still listened to years later?
- Outcome: **2026 listeners on ListenBrainz (popularity API) [P]**; within MLHD, share of the artist's
  other adopters still listening 2+ years after adopting.
- Benchmark: same popularity bin x same month at bet time (as section 2).

**D. Discernment (conversion)**
When other people try the artists you like, do they stick with them?
- Artist conversion = share of other users whose first listen leads to commitment (same commitment
  rule as bets), leave-one-out.
- Timing: **only others' trials after your bet [P]**; all trials (variant).
- Score = average of (conversion - expected conversion for same popularity bin x month) over your bets.

(E. Critical consensus — dropped.)

## 4. Impostors and controls
Computed for every user; a taste score that is mostly one of these is reported as that, not as taste.
- Exploration: new artists per year; committed bets per year
- Obscurity: mean log popularity of bets at bet time
- Mainstreamness: share of plays to top-1% artists
- Activity: listens per active week; history length; join year (cohort)
- Data quality: unmatched share; no-id share
- Scene mix: share of bets in each scene; scene diversity

## 5. Tests (every variant)
1. **Luck baseline.** Shuffle excess returns across bets within the same benchmark cell (keeps each user's
   number of bets, popularity and timing). Compare spread of user scores to the shuffled spread.
   Report the share of variance not explained by luck.
2. **Persistence.** Score each user on the first vs second half of their bets (by time); correlate.
   Also random split-halves (reliability ceiling). Real taste => positive correlation across time.
3. **Impostor check.** Regress score on impostors; report R^2; repeat test 2 on the residual score.
4. **Model agreement.** Correlations among A-D (raw and residualized); is there one general factor?
5. **Robustness.** Run 1-4 across the parameter grid; show the distribution of results (specification curve).
6. **Confirmation** on `sealed` for the variants listed below.

## 6. Later questions (after the taste answer)
- What predicts taste: exploration style, scene breadth, listening intensity, cohort, discovery patterns (raw sample).
- Eras (needs ListenBrainz): do individuals lead or follow the crowd in each era; are discoveries becoming
  more alike; do hits rise and fade faster; does measurable taste exist in both eras.

## Confirmation (FROZEN 2026-10-09, before any `sealed` analysis; see FREEZE_MEMO.md)
Approved by Robert. Implementation: analysis/taste_models.py, analysis/evaluate.py, analysis/confirm.py,
run on the sealed half with exactly the settings below. Nothing here changes after seeing sealed results.

**Candidates (12), all at main settings** (EVALUATION.md; all controls: scene yearly-200, artist/song age,
momentum (artist/scene), country, release timing, additive; onboarding 26 weeks; commitment 4 distinct weeks
within 26 weeks, dated at commitment; horizon 12 months; equal weights; log-growth/level outcomes; 20 popularity
bins; min 20 bets; song bets collapsed per artist-month; community-leading with community prior-popularity and
community-month adjustments; impostor adjustment with past-period features):
- Primary family: discernment at song, artist, scene level.
- Secondary family: prescience, community-leading, durability at song, artist, scene level.

**Headline statistic:** impostor-adjusted forward rank correlation (EVALUATION.md §3.1), bootstrap SE from the
95% interval width.

**Confirmed** if both:
1. Headline > 0 under Holm-Bonferroni correction within its family at family-wise 5% (one-sided p from the
   bootstrap z = estimate / SE), and
2. Corrected 3-year stability's 95% interval excludes zero.
Also reported for every candidate (not part of the pass/fail): plain 95% intervals, whether the sealed estimate
falls inside the explore 95% interval (size replicates), all other scorecard numbers.
Facets reported separately; no combined score in this confirmation.

## Headline confirmation (written 2026-10-09 12:29, before any sealed run of these analyses)
Post-freeze, plain-language headlines chosen on the explore half (analysis/headlines.py, analysis/pickers.py). Each is
tested once on the sealed half with the exact code committed with this section. Growth = fixed-panel listeners over
12 months, picker excluded. "Similar" = same month and size (and momentum and number of pickers for P2/P3); these
comparisons do NOT remove scene, so they include being early to rising scenes (the frozen confirmation above covers
the scene-adjusted question). Confirmed = the 99% bootstrap lower bound is above 1 (ratios) or 0 (differences),
roughly Bonferroni for six tests at 5% overall.
- P1a, P1b. Best-fifth pickers' later picks (track record from earlier years, frozen prescience score) grow 10x, and 4x,
  more often than worst-fifth pickers' (ratio > 1). Explore: 10x 2.17 [2.08, 2.26]; 4x 1.87 [1.83, 1.93].
- P2a, P2b. Artists newly picked by 3+ rated pickers who are all good grow 4x, and 10x, more often than similar artists
  (ratio > 1). Explore: 4x 2.59 [1.92, 3.44]; 10x 3.06 [1.67, 5.27].
- P3a, P3b. Swapping one ordinary picker for a good one adds growth (coefficient > 0), without and with the same-scene
  comparison. Explore: +2.0% [1.9, 2.1]; same scene +1.2% [1.1, 1.3].
Descriptive only: favorites (H1), the all-poor comparison (too few events), and growth gaps.

**Sealed results (run once, 12:29-12:37, 2026-10-09): all six confirmed** (95% interval; 99% lower bound).
- P1a 10x ratio 2.19 [2.10, 2.29; 2.07]. P1b 4x ratio 1.92 [1.87, 1.97; 1.86].
- P2a 4x vs similar 2.84 [2.15, 3.66; 1.97]. P2b 10x vs similar 2.48 [1.35, 4.23; 1.11] (narrowest; 24 vs ~10 expected events).
- P3a +2.0% [1.8, 2.1; 1.8]. P3b same scene +1.3% [1.2, 1.4; 1.1].
Descriptive: favorites ratio 10x 2.11, 4x 1.89 (no sharper than all picks); 3+ good pickers' artists grew +20% vs similar.

## How much taste matters (written 2026-10-09 16:32, before any sealed run of analysis/ladder.py)
Exploratory on the explore half, tested once on the sealed half with the code committed with this section. Same growth
definitions and "similar" comparisons as the headline section (scenes not removed). Confirmed = 99% bootstrap lower bound
above the stated value.
- P4a. Top 1% of pickers (earlier years): their later picks grow 10x more than twice as often as similar artists (lower
  bound > 2). Explore: 5.22 [4.65, 5.85].
- P4b. The ladder is steep: top 1% vs the 90-95% band, ratio of their 10x odds > 1. Explore: 2.91 [2.57, 3.31].
- P5a. Niche artists (0-2 other rated new fans): 2 good pickers vs none, growth difference > 0. Explore: +12.6% [11.8, 13.5].
- P5b. Each good picker adds more for niche than for crowded artists (6+ other rated new fans): slope difference > 0.
  Explore: niche +7.3%, crowded +2.1% per picker.
- P5c. Each good new fan adds more growth than each ordinary new fan (difference > 0). Explore: good +2.0%, ordinary +0.1%.
Descriptive only: the fine ladder bands (top 0.5%, 0.2%, 0.1% get wide), the full crowding curves, and count vs share.

**Sealed results (run once, 2026-10-09): all five confirmed** (95% interval; 99% lower bound).
- P4a top 1% 10x odds 4.70 [4.17, 5.26; 4.04]. P4b vs 90-95% band 2.58 [2.25, 2.94; 2.17].
- P5a niche 2 good vs none +12.3% [11.4, 13.1; 11.1]. P5b slope niche - crowded +0.049 [0.047, 0.053; 0.046]
  (niche +7.1%, middle +3.6%, crowded +2.0% per good picker). P5c good - ordinary +1.60% [1.38, 1.80; 1.33].
Descriptive: bands finer than the top 0.5% overlap (99.8-99.9% 4.1 [3.2, 5.3]; top 0.1% 7.1 [4.7, 9.7]).
Correction to an earlier exploratory claim (chat only, never on the page): "the count of good pickers matters, not their
share" came from a quick check that dropped artists with poor pickers and didn't hold other fans fixed; with them held
fixed, share also matters and the effect depends on crowding.

## What a new fan is worth (written 2026-10-09 16:52, before any sealed run of analysis/fan_value.py)
Exploratory on the explore half; tested once on the sealed half with the committed code. Confirmed = 99% bootstrap lower
bound above 0 (log-growth units).
- P6a. For small artists (<= 20 outcome-panel listeners at the time), a good new fan adds more growth than an ordinary new
  fan. Explore: good +19.6%, ordinary +7.5% (gap +0.106 log, 99% low +0.077).
- P6b. That gap is larger for small than for big artists (> 100 listeners). Explore: +0.088 (99% low +0.059).
Descriptive: each fan type by size and by artist age; the share of good fans (inconsistent sign across stages).

**Sealed results (run once, 2026-10-09): both confirmed.** P6a gap +0.121 log (99% low +0.094): small artists, good fan
+20.2%, ordinary +6.5%, poor +2.6%. P6b +0.105 (99% low +0.078): big artists, good +1.7%, ordinary +0.0%, poor -1.4%.

## What makes the best pickers good (written 2026-10-09 17:26, before any sealed run of analysis/top_pickers.py)
Exploratory on the explore half; tested once on the sealed half with the committed code. Confirmed = 99% bootstrap lower
bound above the stated value.
- P7a. The top 1%'s later picks beat artists of the same size in the same scene: 10x odds > 1. Explore 2.15 (99% low 1.94).
- P7b. The scenes they pick from take off more than size alone predicts: scene quality > 1. Explore 2.43 (99% low 2.21).
- P7c. Their earlier picks are less popular than the bottom half's (popularity percentile difference > 0). Explore 0.115.
Descriptive: the style profile by band; variance in later results explained by style traits (explore 0.8%) vs the track
record (4.3%); top 1% chosen by traits alone (explore 1.5x) vs by track record (5.2x).

**Sealed results (run once, 2026-10-09): all three confirmed.** P7a within scene 2.08 [1.92, 2.24; 99% low 1.87].
P7b scene quality 2.26 [2.10, 2.41; 2.05]. P7c popularity difference 0.119 [0.112, 0.126; 0.110]. Descriptive: traits
explain 0.8% of later results vs 4.5% for the track record; top 1% by traits 1.6x vs by track record 4.7x; overlap 1%.

## Trust your obsessions (written 2026-10-09 17:49, before any sealed run of analysis/obsession.py)
Exploratory on the explore half; tested once on the sealed half (artists only; per-bet song outcomes exist only for the
explore half). Outcome: each pick's excess growth under the frozen prescience measure (all controls).
- P8. Within a person, their most-hooked quarter of artist picks (plays before committing) beats their least-hooked
  quarter: difference > 0 (99% lower bound). Explore +0.0272 [0.0267, 0.0277; 99% low 0.0266].
Descriptive: deciles of plays before committing across all picks.

**Sealed result (run once, 2026-10-09): confirmed.** P8 +0.0261 [0.0256, 0.0265; 99% low 0.0255] (most-hooked quarter
+1.5%, least-hooked -1.1%). Deciles: -1.5% (about 4 plays) to +2.2% (about 92 plays), as on the explore half.

## Obsession and taste (written 2026-10-09 18:05, before any sealed run of analysis/obs_taste.py)
Exploratory on the explore half; tested once on the sealed half with the committed code (artists).
- P9. Getting hooked pays off more for top-fifth pickers than for bottom-fifth pickers: (picks with 10+ plays before
  committing minus picks with 1-4) for the top fifth, minus the same for the bottom fifth, > 0 (99% lower bound).
  Explore: top +4.4 points, bottom +2.2, difference +0.022 [0.018, 0.025; 99% low 0.017].
Descriptive: the curves by plays bin for each group and for all picks.

**Sealed result (run once, 2026-10-10): confirmed.** P9 +0.024 [0.020, 0.028; 99% low 0.019] (top fifth +4.4 points,
bottom fifth +2.0).

## Recent form vs history (written 2026-10-09 18:35, before any sealed run of analysis/recency.py)
Exploratory on the explore half; tested once on the sealed half with the committed code. Confirmed = 99% bootstrap lower
bound above the stated value.
- P10a. Recent top fifth with an old bottom-fifth record beats old top fifth with a recent bottom-fifth record: ratio of
  later 10x odds > 1. Explore 2.36 [1.48, 3.70; 99% low 1.31].
- P10b. The recent record separates people more than the old one (log spread difference > 0). Explore: recent 2.51x,
  old 1.07x, difference 0.85 [0.52, 1.16; 99% low 0.44].
- P10c. A one-year record goes stale: the same top-10% people's 10x odds 2 years later / 4 years later > 1.
  Explore 1.24 [1.12, 1.39; 99% low 1.09].

**Sealed results (run once, 2026-10-10): P10b confirmed; P10a and P10c not confirmed.**
- P10b recent spread 2.20x vs old 1.31x, difference 0.52 [0.19, 0.82; 99% low 0.11]. Confirmed.
- P10a 1.76 [1.12, 2.77; 99% low 0.97]. Same direction, misses the 99% bar. Not confirmed.
- P10c 1.13 [1.00, 1.26; 99% low 0.97]. Same direction, weaker than explore. Not confirmed.
Reading: the recent record matters more than the old one, but the old record still adds something (more on the sealed half
than the explore half suggested), and a one-year record goes stale only slowly.

## Revisions
| Date | Change | Why | Prompted by results? |
|---|---|---|---|
| 2026-10-08 | Initial spec | — | no (only step-1 descriptives seen) |
| 2026-10-08 | Weight as power family plays^alpha; added raw-capped and hit-indicator return metrics; continuous-parameter sweep policy | Robert asked about log/exponent transforms and continuous vs discrete parameters | no |
| 2026-10-08 | Benchmark peers = other users' bets in the same month x popularity bin (all computed leave-one-out), rather than "random artists of that popularity" | Clarification while implementing: makes leave-one-out symmetric for the bet and its peers; excess return = how your bets did vs everyone else's comparable bets | no |
| 2026-10-08 | Weeks map to months by their midpoint; market observed only to 2012-12 | Implementation detail; data thin out in 2013 | no |
| 2026-10-08 | Durability (C): artists not found on ListenBrainz count as 0 listeners [P]; dropping them is a variant | 12% of artists missing, almost all tiny (30% of 1-4-listener artists, 0.4% of 5000+), so missing ~ never listened | no (coverage check) |
| 2026-10-08 | Scenes: co-listening clusters partly encode *when* artists got popular (scene explains 10-29% of variance in artists' peak year; e.g. Skrillex, Gotye, Foster the People grouped — all 2011 breakouts). Proposed: genre-based scenes (MusicBrainz genres; 86% of plays covered, but only 9-18% of small artists) with untagged artists assigned by their listeners' earlier listening; current clusters kept as a contrast | Within-scene benchmarks would otherwise compare breakouts to breakouts and hide foresight | no (sanity check) — pending Robert's input |
| 2026-10-08 | Scenes: **year-by-year co-listening, 200 scenes [P]** (each year's relatedness uses only earlier listening; artists existing before the year keep their pre-period co-listening position, new/small artists are placed by their listeners' earlier taste). Variants: 50 / 1000 scenes; all-years co-listening and genre-tag scenes as contrasts. Replaces the genre-tag proposal above | Robert preferred relatedness (co-listening) over labels; the actual problem was using future listening. Chosen on taste-independent quality criteria (analysis/out/scene_quality.txt): relatedness lift 9.0x vs 8.5x for the leaky all-years version (which was even fitted in-sample), with ~half the timing leak (0.11 vs 0.20); genre tags cover only 57% of bets. A first version had one catch-all scene holding 20-63% of listening (popular artists' diverse audiences average to a generic point) — fixed before comparison. Bets in 2005 have no scene (no earlier data) | no (scene-quality checks only) |
| 2026-10-08 | Added **momentum** control: benchmark cells also by quintile of the artist's prior 6-month fixed-panel growth (leave-one-out). Artist-age cells (months since first listened; pre-2005 artists censored as one group) implemented as already specified | Standard factor control from finance (Carhart momentum) that should have been in the spec: adopting artists that are already rising earns returns without foresight. Together with scene and age controls, tests whether the primary signal is "style exposure" rather than skill | **yes** — the primary run showed a strong signal (skill share 0.62, cross-period persistence 0.25), which prompted a search for mechanical explanations |
| 2026-10-08 | Controls (scene, age, momentum) applied **additively** [P]: month x popularity-bin cells, then leave-one-out month x scene / month x age / month x momentum adjustments, backfitted. Fully crossed cells kept as a contrast only | Crossing all controls made cells tiny (8 artists per cell; 26% of bets in cells with a single artist), so bets were compared mostly to other people adopting the *same* artist, which mechanically erases artist-choice signal (persistence 0.13 crossed vs 0.23 additive). Each run now reports cell diagnostics | **yes** — the unexpectedly large drop with all controls crossed prompted the diagnosis |
| 2026-10-08 | Model B uses **taste communities** instead of each user's k nearest neighbours: a user's community in year Y = users sharing their home scene, the scene they are most over-represented in during the previous 12 months (share of their plays / everyone's share, among scenes with >= 5% of their plays). Outcome = ln((later community adopters + 0.5) / community members active throughout); always adjusted additively for the artist's prior popularity within the community (deciles) | k-NN over 297k users x 36M bets (~7B lookups) was impractical. A first version used plain argmax of plays and put most users into a few big mainstream scenes (bet-weighted mean community ~26k users vs ~1.5k intended), so communities reflected popularity rather than taste; fixed before any B results | no |
| 2026-10-08 | Variants with ~2-8x more bets (no onboarding cutoff, 2-week commitment, every first listen) run on a random half of users (hash), compared against the main controlled version on the same half | They exceed the machine's memory/disk budget at full size; half the users (~120k scored) is ample for persistence estimates | no |
| 2026-10-08 | Sweep results so far (explore): persistence across separate periods stays 0.14-0.19 across onboarding, commitment window, horizon, weights, smoothing, bins and scene definitions; dating at first listen inflates it to 0.23 (trend-following credited as foresight, as predicted); a yes/no "hit" metric shows ~0.01 | Logged as findings, not changes | — |
| 2026-10-08 | Model B also adjusted (additively) for **month x community**: the community's overall adoption rate that month | First B run showed very high persistence (0.33 across separate periods) that the impostors explained more of after controls (R^2 0.08 -> 0.21) — consistent with B rewarding membership in communities that adopt a lot, a stable trait of where you sit rather than foresight. B's outcome counts later adopters in *your* community, so the community's own rate must be the benchmark. Earlier B results kept as model_B/*_v1_no_community_fx | **yes** |
| 2026-10-08 | **Evaluation framework adopted** (EVALUATION.md): 12 construct x unit candidates, one pipeline, one scorecard (forward prediction first; luck, impostors and 3-year stability as gates; reliability, robustness, coverage), bootstrap intervals, pre-declared selection rules. Step-2 numbers are superseded by the pipeline's | Robert: the goal is the *best* model with every decision justified; step 2 evaluated candidates piecemeal | no |
| 2026-10-08 | Persistence measured as a **year-by-year stability curve** (lags 1-5, corrected for yearly measurement noise; lags shorter than the horizon flagged), plus the forward test with a gap of horizon/12 + 1 years | Robert: two fixed periods were arbitrary | no |
| 2026-10-08 | **Scene-level bets**: one bet per scene a person newly enters (no earlier committed artist there, < 5% of plays in it the previous year), dated at the first committed artist, judged by the scene's growth; each scene counts once. Scene universes per year; later artists mapped to the most-overlapping scene | Robert questioned whether removing "being in a growing scene" is fair; scene picking becomes its own candidate instead of only a control | no |
| 2026-10-08 | **Song-level bettors = raw-sample users** (1/8): dating a song commitment needs weekly listening, stored only for them. Song popularity = new listeners (first plays) in the trailing 6 months within the fixed panel; song age replaces artist age; no song momentum control | Data limitation | no |
| 2026-10-08 | Discernment: compared with artists/songs/scenes with the same **prior track record** of keeping triers (analogue of popularity for prescience). Community-leading (artist): also adjusted for momentum *within the community*. Song/scene community-leading: share of your community adopting/entering after you, adjusted for the community's monthly rate | Weak spots identified in step 2 (EVALUATION.md §5) | yes, B and D's step-2 results motivated them (as logged earlier) |
| 2026-10-08 | New control: **release timing** (album/EP/single released in the 3 months before, after, both, neither, or no data; MusicBrainz release groups). New impostor: the person's **own commitment rate** (loyal listener) | "Is it just following music news?" and "is it just being a loyal listener?" | no |
| 2026-10-08 | Impostors: replaced the 10% impostor-share gate with **incremental validity**. Headline = forward prediction after removing impostors (residualized); rank by it; gate = its interval excludes zero; impostor share reported, not gated. Planned: impostor features from the past period only | Small-sample tests: durability (10.6% share) kept only 38% of its prediction after adjustment while community-leading (11.6%) kept 78%. A share cutoff is arbitrary and misclassifies; incremental validity is the standard approach | **yes** (small-sample tests, before any main-candidate results) |
| 2026-10-09 | Song unit: songs by the same artist adopted in the same month are **collapsed into one bet** (mean excess); split halves by artist | First song scorecards showed implausible reliability (0.88-0.98) and luck shares (up to 0.96): a person's song bets cluster by artist/album and move together, so per-song split halves and per-song luck shuffles treated correlated bets as independent. Same logic as scene bets counting each scene once. Superseded scorecards kept in analysis/out/cand/_superseded/ | **yes** |
| 2026-10-09 | Song unit: **finer song-age control** (months since first appearance 0 / 1 / 2 / 3-5 / 6-11 / 12-23 / 24+, previously one group for < 3 months) | After collapsing, community-leading for songs still showed implausible reliability (0.91) and luck share (0.93); likely "following new releases": songs gain most listeners right after release, so release-day listeners see many later community adopters without foresight | **yes** |
| 2026-10-09 | Community-leading for **songs and scenes** now also compared with songs/scenes equally popular *within the bettor's community* beforehand (deciles, additive), as the artist version already was | Omission found in the "is it just X" table: song-level community-leading barely moved when any control was removed (0.31 throughout), consistent with crediting picks already popular among similar people | **yes** |
| 2026-10-09 | Incident: a git history cleanup (approved by Robert) also deleted the tracked data files from disk; the 12 main candidates' aggregate files were rebuilt (identical except random luck shuffles). Scorecards and all data/ were unaffected | Process error | — |
| 2026-10-09 | **Freeze**: Confirmation section written and committed before any sealed-half analysis | Robert approved FREEZE_MEMO recommendations, with a primary *family* (discernment at three levels) instead of a single primary model, and Holm correction within families (instead of a flat 99.6%) | no |
| 2026-10-09 | Sealed-run pre-check (explore rerun reproduces the explore result) uses a tolerance of 0.001 instead of exact equality | First attempt stopped on a 1e-5 difference from non-deterministic tie-breaking in popularity bins and parallel floating-point sums; the headline's uncertainty is ~0.005. Implementation check only; frozen plan unchanged | no (no sealed results existed) |
| 2026-10-09 | Song unit: weight variants now apply to merged song bets (weight from the merged bet's total early plays) | Bug: merging same-artist songs set every bet's weight to 1, so the weight sweeps for songs were no-ops (main settings use equal weights, so frozen results are unaffected) | no |
| 2026-10-09 | Individual percentile range (descriptive, write-up only) now uses the true-score formula: mean sqrt(reliability) x z, SD sqrt(1 - reliability) | The earlier formula (mean reliability x z, SD sqrt(1 - reliability^2)) gave the range of a fresh sample of picks, not of the true standing: discernment-songs 75th percentile was shown as 31st-92nd, correct is about 42nd-90th. Not part of any confirmation rule | yes |
