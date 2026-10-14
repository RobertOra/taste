"""Why does the top 1%'s typical find fall behind the rest of the best fifth after a few years? (2026-10-14, exploratory)

Runs lb_careers.py / lb_careers_songs.py up to the point where people are rated (same picks, listeners and ranks; exec of the
scripts' own code, nothing written), then for k = 1..6 years compares the top 1% with the rest of the best fifth (80-99%):
  gap in growth vs similar finds, with a 95% range from a paired bootstrap over people (1,000 draws);
  how often a find grew tenfold, and how often it lost half its listeners, each vs similar finds (same month and size).
Usage: careers_top1_check.py artist|song
"""
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
unit = sys.argv[1]
src = (HERE / ("lb_careers.py" if unit == "artist" else "lb_careers_songs.py")).read_text()
exec(compile(src[:src.index("\nrows = []")], "careers_prefix", "exec"))   # defines f (rated picks) and K
rng = np.random.default_rng(99)
f = f.with_columns(*[(pl.col(f"g{k}") <= np.log(0.5)).cast(pl.Float64).alias(f"h{k}") for k in K])
f = f.with_columns(*[pl.col(f"h{k}").mean().over("m", "bin").alias(f"he{k}") for k in K])
grp = f.filter(pl.col("q") > 0.8).with_columns(top=pl.col("q") > 0.99)
per = grp.group_by("user", "top").agg([pl.col(f"x{k}").sum().alias(f"s{k}") for k in K] + [pl.len().alias("n")]
                                     + [pl.col(f"t{k}").sum().alias(f"T{k}") for k in K] + [pl.col(f"te{k}").sum().alias(f"TE{k}") for k in K]
                                     + [pl.col(f"h{k}").sum().alias(f"H{k}") for k in K] + [pl.col(f"he{k}").sum().alias(f"HE{k}") for k in K])
a, b = per.filter(pl.col("top")), per.filter(~pl.col("top"))
wa, wb = rng.poisson(1.0, (1000, a.height)).astype(float), rng.poisson(1.0, (1000, b.height)).astype(float)
na, nb = a["n"].to_numpy().astype(float), b["n"].to_numpy().astype(float)
print(f"{unit}s: top 1% {a.height} people / {int(na.sum()):,} finds; rest of best fifth {b.height} people / {int(nb.sum()):,} finds")
for k in K:
    ga, gb = np.expm1(a[f"s{k}"].sum() / na.sum()), np.expm1(b[f"s{k}"].sum() / nb.sum())
    d = np.expm1((wa @ a[f"s{k}"].to_numpy()) / (wa @ na)) - np.expm1((wb @ b[f"s{k}"].to_numpy()) / (wb @ nb))
    r = lambda x, c: x[f"{c}{k}"].sum() / x[f"{c}E{k}"].sum()
    print(f"+{k}y growth: top 1% {ga:+.1%}, rest {gb:+.1%}, difference {ga - gb:+.1%} [{np.percentile(d, 2.5):+.1%}, {np.percentile(d, 97.5):+.1%}] | "
          f"tenfold vs similar: {r(a, 'T'):.2f}x / {r(b, 'T'):.2f}x | lost half vs similar: {r(a, 'H'):.2f}x / {r(b, 'H'):.2f}x")
