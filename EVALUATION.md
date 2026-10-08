# Evaluation framework (DRAFT for Robert's review)

Goal: find the taste model that works **best**, with every decision behind it justified, then
confirm it once on the sealed half and later test it in another era (ListenBrainz).

Step 2 was a first pass that evaluated candidates piecemeal. This framework replaces that with
one pipeline and one scorecard applied identically to every candidate. Data, bets, popularity
tables, scenes and controls from steps 1-2 are reused.

Status: **approved with Robert's decisions (2026-10-08)**, see §9.

---

## 1. What "best" means

A taste model gives each person a score. The best model is the one whose scores are:

| # | Criterion | Question it answers | How measured |
|---|---|---|---|
| 1 | **Predictive** | If we had scored people earlier, would it have predicted how well their *later* bets do? | Forward test (§3.1) |
| 2 | **Valid** | Is it measuring taste, not something else? | Impostor share, luck baseline (§3.2) |
| 3 | **Stable** | Is it a lasting trait, and how fast does it drift? | Year-by-year persistence curve (§3.3) |
| 4 | **Reliable** | How precise is one person's score? | Split-half reliability (§3.4) |
| 5 | **Robust** | Does it depend on fragile setting choices? | Spread across the settings grid (§3.5) |
| 6 | **Practical** | How many people can be scored, with how much history? | Coverage (§3.6) |
| 7 | **Sensible** | Does every choice have a plain-language reason? | Judgment, written in this file |

Criterion 1 is the headline "accuracy" measure because it is exactly how a score would be used:
score someone on their past, predict their future. Criteria 2 and 3 are gates: a model that fails
them is not measuring taste, however well it predicts. (Order approved.)

## 2. Candidates

### 2.1 Constructs (what "good taste" means)
| Construct | A pick is good if… | Notes |
|---|---|---|
| **Prescience** | the artist/song/scene grows more afterwards than comparable ones | Step 2's model A |
| **Community-leading** | people with similar taste adopt it later | Model B; needs community-trend fix (§5) |
| **Discernment** | other people who try it stick with it | Model D; needs scene-loyalty fix (§5) |
| **Durability** | it is still listened to years later (2026) | Model C; weak in step 2, kept for completeness |

### 2.2 Units (what a "bet" is on)
Every construct at every unit: 4 x 3 = **12 candidates**, plus combined scores later (§6).
Robert's rule: keep a candidate unless there is a good reason not to; the scorecard decides.

| Unit | Prescience | Community-leading | Discernment | Durability |
|---|---|---|---|---|
| Artist | grows vs peers | community adopts later | triers stick with it | 2026 ListenBrainz listeners |
| Song | grows vs peers (by song age too) | community adopts later (expected sparse/noisy) | triers keep playing it | 2026 ListenBrainz listeners (per recording) |
| Scene | scene grows | community moves into a *different* scene you entered first (own home scene excluded: circular) | people who try the scene stay in it | scene's artists' 2026 listeners |

Scenes are handled two ways, answering the fairness question:
- **Scene picking** (scene unit): one bet per scene a person gets into, dated when they got into
  it, judged by how much the scene grows afterwards. Each scene counts once, however many of
  its artists the person plays. Long payoffs are allowed (horizon up to 24 months).
- **Picking within a scene** (artist/song units): bets compared with bets in the same scene.
Both are reported; neither is thrown away.

### 2.3 Settings per candidate
Defaults in bold. Each is swept one at a time around the defaults; the three that matter most
conceptually (commitment, horizon, weight) also get a small full grid.

| Setting | Values |
|---|---|
| Onboarding cutoff | 13 / **26** / 52 weeks |
| What counts as committed | 2 / **4** / 8 separate weeks; 10 plays |
| Time window (horizon) | 6 / **12** / 24 months |
| Bet weight (plays ^ power) | **0** / 0.5 / 1 |
| Return measure | **log growth** / rank among peers |
| Minimum bets to score a person | 10 / **20** / 50 |

## 3. Scorecard (computed identically for every candidate)

Every number gets a 95% interval from a bootstrap over users (200 resamples), so we know when a
difference between candidates is real.

### 3.1 Predictive (headline)
For each cutoff year Y (2007-2010): score each person on bets up to Y, then measure their bets in
Y+2 and Y+3 (a full year gap, so no shared return windows).
- **Forward correlation**: past score vs future average excess return (rank correlation).
- **Top-vs-bottom spread**: future excess return of the top 20% by past score minus the bottom 20%.
- **Repeat rate**: share of the top 20% who are top 20% again (chance = 20%). The plain-language
  number for the report.
Averaged over cutoff years, weighted by people scored.

### 3.2 Valid (gate)
- **Luck baseline**: spread of scores vs the same scores with every bet's result shuffled among
  comparable bets. Gate: the excess spread's interval excludes zero.
- **Impostors**: share of the score explained by activity, exploration, obscurity, mainstreamness,
  history length, join year, data quality and scene mix (in plain terms: from someone's listening
  habits alone, how much of their taste score could you predict?). Gate: under 10%, and the forward
  correlation of the impostor-adjusted score still excludes zero. Always reported, with its interval.

### 3.3 Stable (gate + description)
Each person scored separately per calendar year. Correlations between years 1, 2, 3, 4, 5 apart,
corrected for each year's measurement noise (estimated from within-year split halves). Reported as
a curve, summarized by **corrected 3-year stability** and **drift per year**. Lag 1 is shown but
flagged: adjacent years share return windows. Gate: corrected 3-year stability's interval excludes zero.

### 3.4 Reliable
Split each person's bets in two at random; correlate; correct to full length. Translated into a
typical percentile range for one person (what the website would show).

### 3.5 Robust
Range of the forward correlation across the settings grid. A candidate whose result only holds at
one setting is marked fragile.

### 3.6 Practical
Share of users scoreable; median history needed to reach the minimum bets.

### 3.7 "Is it just X?"
One row per alternative explanation, for every candidate, each with its answer and interval:
| Is it just… | How it's answered |
|---|---|
| luck? | luck baseline (§3.2) |
| listening a lot / exploring a lot? | impostor regression, single-feature correlations |
| liking obscure or mainstream music? | impostor regression; popularity-matched comparisons |
| having joined early / long history? | impostor regression (join year, history length) |
| data quality (unmatched listens)? | impostor regression |
| being in a scene that grew? | scene-adjusted vs unadjusted scores; scene-level candidate |
| following trends (momentum)? | with vs without momentum control; first-listen vs commitment dating |
| following new releases? | with vs without artist-age control |
| local scenes (country)? | with vs without country control |
| being early right before album releases (music news)? | with vs without release-timing control (§5) |
| Last.fm radio choosing for you? | strict 8-week commitment rule |
| sharing with friends (influence)? | not testable here; stated |

### 3.8 Also reported
Correlation with every other candidate (are they the same thing?).

## 4. Corrections applied to every candidate
Not tuned; each prevents a known bias. Unchanged from step 2 unless noted.
- Ignore each person's onboarding period (their old favorites show up as "new").
- Popularity measured within a fixed panel of users active at both ends of the window.
- Each person excluded from the popularity numbers they're scored on.
- Bets dated at commitment, not first listen (otherwise trend-following counts as foresight).
- Compared with bets at the same popularity, in the same month, adjusted (side by side) for
  scene, artist age, momentum and country.
- Bets need a full window of data after them (to 2012-12).

## 5. Known weak spots to fix before scoring
| Issue | Fix | Applies to |
|---|---|---|
| Trend-following inside your own community | Control for the artist's prior growth *within the community* | Community-leading |
| Some scenes' fans are loyal to everything | Compare conversion with the scene's own conversion rate that month | Discernment |
| Music news: being early right before an album release | Control for time since the artist's latest release (MusicBrainz release dates; ~1-2 h to fetch). Included | All |
| Last.fm radio/recommendations chose some "discoveries" | Can't be seen in the data. Check: does the result hold with the strict 8-week commitment rule? | All |
| Influence (sharing music with friends) | Not testable here. Stated as a limitation | All |
| Who's in the data (Last.fm users active until 2012-13) | Stated as a limitation; ListenBrainz is the out-of-sample test | All |

## 6. Combined score
If candidates correlate, test a combined score (average of standardized scores; and first
principal component) through the same scorecard. It wins only if it predicts better than the best
single candidate by more than the interval. Decision: start with separate facets; consider combining
at the freeze review (combining is ~1 h; to be confirmed on the sealed half it must be chosen before freezing).

## 7. How we choose (fixed before running)
1. Run every candidate at default settings plus sweeps. Compute scorecards.
2. Drop candidates that fail a gate (§3.2, §3.3).
3. Settings within a candidate: keep the default unless another setting beats it on the forward
   correlation by more than its interval **and** its neighbouring settings are similar (a plateau,
   not a spike).
4. Across candidates: the one with the best forward correlation is the **primary** model; other
   passing candidates are reported as facets of taste. Ties (overlapping intervals) go to the simpler one.
5. Write the exact frozen choices into SPEC.md's Confirmation section, with pass criteria for the
   sealed half: forward correlation's interval excludes zero, and the estimate falls within the explore
   half's interval (or the miss is reported).
6. Run the sealed half once.

## 8. Work and time
Reused from steps 1-2: all data, bets, monthly tables, popularity, scenes, communities, controls,
model code, impostor features. New: song/scene building blocks, release dates, B/D fixes, one
evaluation pipeline. Step 2's numbers are recomputed by the new pipeline.

| When | Step | Estimate |
|---|---|---|
| Evening, day 1 | Song and scene building blocks; B/D fixes; release dates | 4-5 h |
| Overnight 1 | Sealed-half building tables (no results looked at) | overnight |
| Day 2 | Evaluation pipeline + scorecard + bootstrap | 3-4 h |
| Day 2 to overnight 2 | Run all 12 candidates x settings (song level heaviest; may need a user sample) | 6-12 h |
| Day 3 | Review scorecards together, decide, freeze; sealed run; report rewrite | ~4-6 h |

Disk: song-level tables ~3-5 GB, release dates < 1 GB, sealed tables ~12 GB; peak stays under the 150 GB cap.

## 9. Decisions (Robert, 2026-10-08)
1. Criteria order: approved (predictive first; validity and stability as gates).
2. Impostor gate: 10%, always reported with its interval (Claude's call, as delegated).
3. Candidates: keep everything unless there is a good reason not to -> all 12 construct x unit combinations.
4. Release-timing check: included.
5. Combined score: start separate; revisit at the freeze review.
