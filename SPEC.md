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

## Confirmation
(empty until we decide; committing this section freezes it before any `sealed` analysis)

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
