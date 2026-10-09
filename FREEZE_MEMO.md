# Freeze decision memo (2026-10-09)

**What we're deciding:** which taste models and settings get locked in before the one-time test on the sealed
half, and what counts as "confirmed". Everything below is from the explore half only.

## The evidence

Headline = how well someone's taste score from earlier years predicts how their later picks do (years later,
no overlapping time windows), after removing the impostors (listening volume, exploration, mainstreamness,
history length, join year, data quality, own loyalty). 0 = no prediction. 95% intervals in brackets.

| Candidate | Headline | Top 20% stay top 20% (chance 20%) | 3-year stability | Reliability (one person) | Impostor share | People | Passes tests |
|---|---|---|---|---|---|---|---|
| Community-leading, songs | 0.25 [0.24, 0.26] | 40% | 0.30 | 0.90 (see caveat) | 9% | 31k | yes |
| Discernment, songs | 0.24 [0.23, 0.25] | 34% | 0.40 | 0.67 | 9% | 31k | yes |
| Prescience, songs | 0.22 [0.21, 0.23] | 30% | 0.36 | 0.63 | 3% | 31k | yes |
| Community-leading, artists | 0.21 [0.21, 0.22] | 35% | 0.26 | 0.84 | 11% | 234k | yes |
| Durability, songs | 0.19 [0.17, 0.20] | 29% | 0.28 | 0.67 | 14% | 31k | yes |
| Discernment, artists | 0.16 [0.16, 0.17] | 30% | 0.28 | 0.58 | 5% | 240k | yes |
| Prescience, artists | 0.14 [0.14, 0.15] | 29% | 0.29 | 0.53 | 1% | 240k | yes |
| Discernment, scenes | 0.11 [0.10, 0.12] | 25% | 0.19 | 0.54 | 8% | 177k | yes |
| Durability, artists | 0.07 [0.06, 0.07] | 29% | 0.22 | 0.44 | 11% | 240k | yes |
| Prescience, scenes | 0.06 [0.05, 0.07] | 22% | 0.18 | 0.35 | 3% | 177k | yes |
| Community-leading, scenes | 0.05 [0.05, 0.06] | 23% | 0.07 | 0.49 | 6% | 167k | yes |
| Durability, scenes | 0.01 [0.00, 0.02] | 21% | 0.12 | 0.17 | 8% | 177k | barely |

Song-level candidates are scored on the 1/8 of people with full listening detail (31k); the sealed half has
about the same number.

**Is it just X?** For every candidate, removing any one control changes the headline only modestly, except:
being in a growing scene (prescience/discernment artists: 0.14 -> 0.21 and 0.16 -> 0.33 without the scene
control), song age for songs (following new releases), and trend-following (dating bets at first listen
inflates prescience 0.14 -> 0.18). All of those are controlled in the numbers above.

**Robustness:** each candidate's headline stays in a narrow band across its settings, with two patterns:
- A 6-month window scores higher than 12 months for every candidate. 6 months is the edge of the tested range,
  so the rules keep 12 (see follow-ups).
- The "rank" return measure collapses community-leading and discernment (to ~0.02): their outcomes are mostly
  zeros (no later adopters/triers), so ranks are mostly ties. That's a measurement mismatch, not fragility.

**Do they agree?** Moderately. One shared factor explains ~45% of the variation across the four models
(25% if unrelated). Strongest links: prescience & discernment at the artist level (0.55); prescience &
durability at the song level (0.66).

## How the pre-declared rules apply (EVALUATION.md §7)

1. **Tests:** 11 of 12 pass clearly; durability at the scene level passes only barely.
2. **Settings:** keep the main settings everywhere (no alternative beats them on a plateau).
3. **Primary model:** the top candidate is community-leading/songs (0.25). Its interval overlaps
   discernment/songs (0.24), which is the simpler model (no communities needed), so by the tie rule the
   **primary model is discernment at the song level**. The others are reported as facets.

## Recommendations

1. **Freeze all 12 candidates** at their main settings. The sealed run costs about an hour, and confirming
   (or not) every facet is more informative than picking a few. The primary is named in advance.
2. **Primary: discernment, songs** (by the tie rule above).
3. **Confirmation bar, stated now:** a candidate is *confirmed* if on the sealed half
   (a) its headline's interval excludes zero at **99.6%** (95% split across 12 candidates, so testing many
   doesn't let one pass by luck), and (b) its 3-year stability's interval excludes zero.
   Also reported: whether the sealed estimate falls inside the explore interval (did the size replicate?).
4. **Keep facets separate** for now; revisit a combined score after the sealed results.

## Open caveats (not blocking the freeze)

- Community-leading/songs has much higher reliability (0.90) than everything else (0.5-0.7). That could be a
  real "consistently ahead of my community" trait or a stable factor we haven't controlled. Its sealed result
  should be read with that in mind.
- Influence (sharing music with friends) can't be separated from foresight in this data.
- Everyone here was an active Last.fm user until 2012-13, mostly before algorithmic playlists.

## Follow-up questions (after the sealed run, not frozen)
- Is taste mostly short-term? (6-month windows score higher everywhere.)
- What predicts good taste? Does it hold in the modern era (ListenBrainz)?

## Decisions needed from Robert
1. Freeze all 12 (recommended) or a subset?
2. Primary = discernment at the song level (per the tie rule): OK?
3. Confirmation bar: 99.6% intervals (recommended) or 95%?
4. Keep facets separate for now (recommended)?
