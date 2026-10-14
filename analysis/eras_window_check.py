"""Is the best fifth getting better, or just better measured? (2026-10-14, exploratory; Robert's question.)

eras_yearly(_songs).py rate people for year Y on ALL their picks up to Y-2, so later years rate people on longer histories
(more reliable ranks, so a wider best-minus-worst gap even if taste didn't change). Here the same yearly best/worst-fifth growth
with people rated on a fixed window instead: picks in Y-4..Y-2 only (>= 20 picks in it), next to the all-history version.
Also the mean number of rating picks per rated person, and how many people the top 10% holds each year.
Prints only; writes nothing.
"""
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent


def load(unit):
    cols = ["user", "m", "bin", "v", "e"] + (["artist"] if unit == "song" else [])
    b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / f"A_{unit}_lb.parquet", columns=cols).with_columns(year=pl.col("m") // 12)
    b = b.join(b.group_by("m", "bin").agg(ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    rate = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12) if unit == "song" else b
    return b, rate


def year_rows(b, rate, y, lo):
    past = (rate.filter(pl.col("year").is_between(lo, y - 2)).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    f = b.filter(pl.col("year") == y).join(past.select("user", "q", "n"), on="user")
    g = lambda c: float(np.expm1(f.filter(c)["gx"].mean())) if f.filter(c).height else float("nan")
    best, worst = g(pl.col("q") > 0.8), g(pl.col("q") <= 0.2)
    return best, worst, past["n"].mean(), f.filter(pl.col("q") > 0.9)["user"].n_unique()


for unit in ("artist", "song"):
    b, rate = load(unit)
    print(f"\n== {unit}s: year | ALL history: best, worst, gap, rating picks/person | FIXED Y-4..Y-2: best, worst, gap, picks/person | top 10% people")
    for y in range(2010, 2026):
        A = year_rows(b, rate, y, 0)
        Fx = year_rows(b, rate, y, y - 4)
        print(f"{y} | {A[0]:+6.1%} {A[1]:+6.1%} {A[0] - A[1]:+6.1%} {A[2]:5.0f} | {Fx[0]:+6.1%} {Fx[1]:+6.1%} {Fx[0] - Fx[1]:+6.1%} {Fx[2]:5.0f} | {Fx[3]:>5}")
