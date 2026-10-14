"""Why do the best fifth's finds do better over the years, not just the worst fifth's worse? (2026-10-14, exploratory)

Same yearly setup as eras_yearly(_songs).py part 1 (rated on picks up to Y-2). Per year:
  spread: the standard deviation of all finds' growth vs similar finds (how far apart outcomes are);
  best and worst fifth's growth, and the same divided by the spread;
  same people: a panel rated in both 2010-2013 and 2021-2025 (finds in both periods), best/worst fifth growth in each period.
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
    rate = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12) if unit == "song" else b
    fy = []
    for y in range(2010, 2026):
        past = (rate.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
    F = pl.concat(fy)
    print(f"\n== {unit}s: year | spread (sd of growth vs similar) | best, worst | best / spread, worst / spread | share of finds by best fifth")
    for y in range(2010, 2026):
        d = b.filter(pl.col("year") == y); f = F.filter(pl.col("year") == y)
        sd = float(d["gx"].std()); bst = float(f.filter(pl.col("q") > .8)["gx"].mean()); wst = float(f.filter(pl.col("q") <= .2)["gx"].mean())
        print(f"{y} | {sd:5.2f} | {np.expm1(bst):+6.1%} {np.expm1(wst):+6.1%} | {bst / sd:+.3f} {wst / sd:+.3f}")
    early, late = F.filter(pl.col("year").is_between(2010, 2013)), F.filter(pl.col("year").is_between(2021, 2025))
    panel = set(early["user"].unique().to_list()) & set(late["user"].unique().to_list())
    for name, d in (("2010-2013", early), ("2021-2025", late)):
        d = d.filter(pl.col("user").is_in(list(panel)))
        g = lambda c: float(np.expm1(d.filter(c)["gx"].mean()))
        print(f"same {len(panel):,} people, {name}: best fifth {g(pl.col('q') > .8):+.1%}, worst fifth {g(pl.col('q') <= .2):+.1%}")
    for name, d in (("2010-2013", early), ("2021-2025", late)):
        d = d.filter(~pl.col("user").is_in(list(panel)))
        g = lambda c: float(np.expm1(d.filter(c)["gx"].mean()))
        print(f"everyone else, {name}: best fifth {g(pl.col('q') > .8):+.1%}, worst fifth {g(pl.col('q') <= .2):+.1%}")
