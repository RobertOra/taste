"""Top 10% of pickers on the year-by-year growth chart (2026-10-14, exploratory; Robert's request).

Same setup as eras_yearly.py / eras_yearly_songs.py part 1 (people rated on their picks up to Y-2, frozen prescience score,
shrunk, >= 20 picks; songs: songs by one artist found the same month count as one pick for the rating), for the top 10%
(q > 0.9): growth of their finds vs similar ones (same month and size), single years 2010-2025 plus the "early" and "recent"
pools. 95% ranges: bootstrap over people (own seed). Adds top10_growth / top10_lo / top10_hi / top10_people to the matching
rows of analysis/writeup/yeargrowth.json; every other field is left as it was.
"""
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
W = ROOT / "analysis" / "writeup"
RNG = np.random.default_rng(5153)
B = 1000
POOLS = {"early": (2010, 2013), "recent": (2021, 2025)}
pc = lambda a, q: float(np.percentile(a, q))
new = {}
for unit in ("artist", "song"):
    cols = ["user", "m", "bin", "v", "e"] + (["artist"] if unit == "song" else [])
    b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / f"A_{unit}_lb.parquet", columns=cols).with_columns(year=pl.col("m") // 12)
    b = b.join(b.group_by("m", "bin").agg(ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    rate = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12) if unit == "song" else b
    fy = []
    for y in range(2009, 2026):
        past = (rate.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
    F = pl.concat(fy).filter(pl.col("q") > 0.9)
    pre = "songs:" if unit == "song" else ""
    for key, (y0, y1) in [(str(y), (y, y)) for y in range(2010, 2026)] + list(POOLS.items()):
        p = F.filter(pl.col("year").is_between(y0, y1)).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        s, n = p["s"].to_numpy(), p["n"].to_numpy().astype(float)
        w = RNG.poisson(1.0, (B, p.height)).astype(float)
        bs = np.expm1((w @ s) / (w @ n))
        new[pre + key] = {"top10_growth": float(np.expm1(s.sum() / n.sum())), "top10_lo": pc(bs, 2.5), "top10_hi": pc(bs, 97.5), "top10_people": p.height}
        print(f"{pre + key:>13}: top 10% {new[pre + key]['top10_growth']:+.1%} [{new[pre + key]['top10_lo']:+.1%}, {new[pre + key]['top10_hi']:+.1%}] ({p.height} people)")
rows = json.loads((W / "yeargrowth.json").read_text())
for r in rows:
    r.update(new.get(r["key"], {}))
assert all("top10_growth" in r for r in rows), "a yeargrowth row got no top-10% value"
(W / "yeargrowth.json").write_text(json.dumps(rows, indent=1))
