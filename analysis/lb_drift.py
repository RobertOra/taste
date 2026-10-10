"""Is the decade fade real drift or noise? (ListenBrainz, exploratory.)

People rated on picks up to 2015 (>= 20); their score on each later year's picks (>= 10). Scores = weighted mean per-bet
excess (scorecard agg tables: user x year x random half). For each later year: Spearman correlation between the 2015
score and that year's score, the split-half reliability of each score (Spearman-Brown), and the noise-corrected
correlation r / sqrt(rel_2015 * rel_year). Bootstrap over people (500 draws). Measures: discernment songs (the write-up's
repeat chart measure) and prescience artists (the decade chart's measure). Writes analysis/out/lb_drift.json.
"""
import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(8181)
B = 500


def corr(a, b, w=None):
    a, b = rankdata(a), rankdata(b)
    if w is None:
        return np.corrcoef(a, b)[0, 1]
    m = lambda x: (w * x).sum() / w.sum()
    ca, cb = a - m(a), b - m(b)
    return (w * ca * cb).sum() / np.sqrt((w * ca * ca).sum() * (w * cb * cb).sum())


def sb(r):
    return 2 * r / (1 + r)


out = {}
for name, label in (("lb_D_song_main", "Discernment, songs"), ("lb_A_artist_main", "Prescience, artists")):
    a = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / name / "agg.parquet", columns=["user", "year", "half", "n", "sw", "swe"])

    def score(f, by_half=False):
        g = ["user", "half"] if by_half else ["user"]
        return f.group_by(g).agg(pl.col("n").sum(), (pl.col("swe").sum() / pl.col("sw").sum()).alias("s"))

    base = score(a.filter(pl.col("year") <= 2015)).filter(pl.col("n") >= 20).select("user", s0="s")
    bh = score(a.filter(pl.col("year") <= 2015), True).pivot(on="half", index="user", values="s").rename({"0": "b0", "1": "b1"})
    rows = []
    for y in range(2017, 2026):
        later = score(a.filter(pl.col("year") == y)).filter(pl.col("n") >= 10).select("user", s1="s", n1="n")
        lh = score(a.filter(pl.col("year") == y), True).pivot(on="half", index="user", values="s").rename({"0": "l0", "1": "l1"})
        d = base.join(later, on="user").join(bh, on="user").join(lh, on="user").drop_nulls()
        v = {c: d[c].to_numpy() for c in ("s0", "s1", "b0", "b1", "l0", "l1")}
        est = lambda w=None: (corr(v["s0"], v["s1"], w), sb(corr(v["b0"], v["b1"], w)), sb(corr(v["l0"], v["l1"], w)))
        r, r0, r1 = est()
        bs = []
        for _ in range(B):
            w = RNG.poisson(1.0, d.height).astype(float)
            rr, a0, a1 = est(w)
            bs.append(rr / np.sqrt(max(a0, 1e-3) * max(a1, 1e-3)))
        rows.append({"year": y, "years_later": y - 2015, "people": d.height, "median_picks": float(np.median(d["n1"].to_numpy())),
                     "r": float(r), "rel_2015": float(r0), "rel_year": float(r1), "corrected": float(r / np.sqrt(r0 * r1)),
                     "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5))})
        q = rows[-1]
        print(f"{label:20} +{q['years_later']:>2}y: {q['people']:>5,} people, median {q['median_picks']:.0f} picks | raw r {q['r']:.3f} | "
              f"reliability 2015 {q['rel_2015']:.2f}, that year {q['rel_year']:.2f} | corrected {q['corrected']:.2f} [{q['lo']:.2f}, {q['hi']:.2f}]")
    out[label] = rows
(ROOT / "analysis" / "out" / "lb_drift.json").write_text(json.dumps(out, indent=1))
