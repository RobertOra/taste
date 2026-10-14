"""Best fifth's finds by how long people had been on ListenBrainz, year by year (2026-10-14, exploratory; Robert's question).

Same yearly setup as eras_yearly(_songs).py part 1 (rated on picks up to Y-2, >= 20 picks). Tenure in year Y = Y minus the year of
the person's first pick (ListenBrainz, any unit's table used here). Groups: newer (2-4 years) and longer (5+ years). Per year:
growth of the best and worst fifth's finds vs similar ones in each group, and the newer group's share of the best fifth.
Prints only.
"""
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
for unit in ("song", "artist"):
    cols = ["user", "m", "bin", "v", "e"] + (["artist"] if unit == "song" else [])
    b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / f"A_{unit}_lb.parquet", columns=cols).with_columns(year=pl.col("m") // 12)
    b = b.join(b.group_by("m", "bin").agg(ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    start = b.group_by("user").agg(y0=pl.col("year").min())
    rate = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12) if unit == "song" else b
    print(f"\n== {unit}s: year | best fifth: newer (2-4 yrs) / longer (5+) | worst fifth: newer / longer | newer share of best fifth")
    for y in range(2012, 2026):
        past = (rate.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        f = (b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user").join(start, on="user")
             .with_columns(new=(y - pl.col("y0")) <= 4))
        g = lambda c: float(np.expm1(f.filter(c)["gx"].mean())) if f.filter(c).height > 2000 else float("nan")
        B, W, N = pl.col("q") > .8, pl.col("q") <= .2, pl.col("new")
        share = f.filter(B)["new"].mean()
        print(f"{y} | {g(B & N):+6.1%} {g(B & ~N):+6.1%} | {g(W & N):+6.1%} {g(W & ~N):+6.1%} | {share:.0%}")
