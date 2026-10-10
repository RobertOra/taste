"""Do any measures stand the test of time? (ListenBrainz, exploratory.) analysis/lb_drift.py for all nine LB measures.
Rated on picks up to 2015 (>= 20); later score on two-year windows [Y, Y+1], Y = 2016..2024 (>= 10 picks); noise-corrected
Spearman correlation r / sqrt(rel_2015 * rel_window) with split-half reliabilities (Spearman-Brown). Bootstrap 300 draws.
Writes analysis/out/lb_drift_all.json."""
import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(8282)
B = 300


def corr(a, b, w):
    a, b = rankdata(a), rankdata(b)
    m = lambda x: (w * x).sum() / w.sum()
    ca, cb = a - m(a), b - m(b)
    return (w * ca * cb).sum() / np.sqrt((w * ca * ca).sum() * (w * cb * cb).sum())


sb = lambda r: 2 * r / (1 + r)
out = {}
for m, mn in (("D", "Discernment"), ("A", "Prescience"), ("B", "Community-leading")):
    for u in ("song", "artist", "scene"):
        a = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / f"lb_{m}_{u}_main" / "agg.parquet", columns=["user", "year", "half", "n", "sw", "swe"])
        sc = lambda f, h=False: f.group_by(["user", "half"] if h else ["user"]).agg(pl.col("n").sum(), (pl.col("swe").sum() / pl.col("sw").sum()).alias("s"))
        base = sc(a.filter(pl.col("year") <= 2015)).filter(pl.col("n") >= 20).select("user", s0="s")
        bh = sc(a.filter(pl.col("year") <= 2015), True).pivot(on="half", index="user", values="s").rename({"0": "b0", "1": "b1"})
        rows = []
        for y in range(2016, 2025):
            f = a.filter(pl.col("year").is_between(y, y + 1))
            later = sc(f).filter(pl.col("n") >= 10).select("user", s1="s")
            lh = sc(f, True).pivot(on="half", index="user", values="s").rename({"0": "l0", "1": "l1"})
            d = base.join(later, on="user").join(bh, on="user").join(lh, on="user").drop_nulls()
            if d.height < 200:
                continue
            v = {c: d[c].to_numpy() for c in ("s0", "s1", "b0", "b1", "l0", "l1")}
            est = lambda w: corr(v["s0"], v["s1"], w) / np.sqrt(max(sb(corr(v["b0"], v["b1"], w)), 1e-3) * max(sb(corr(v["l0"], v["l1"], w)), 1e-3))
            one = np.ones(d.height)
            bs = [est(RNG.poisson(1.0, d.height).astype(float)) for _ in range(B)]
            rows.append({"years_later": y - 2015, "people": d.height, "corrected": float(est(one)), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5))})
        out[f"{mn}, {u}s"] = rows
        print(f"{mn + ', ' + u + 's':26} " + "  ".join(f"+{r['years_later']}y {r['corrected']:.2f}[{r['lo']:.2f},{r['hi']:.2f}]" for r in rows)
              + (f"  (n {rows[0]['people']:,}->{rows[-1]['people']:,})" if rows else ""), flush=True)
(ROOT / "analysis" / "out" / "lb_drift_all.json").write_text(json.dumps(out, indent=1))
