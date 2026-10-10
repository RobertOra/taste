"""Careers or one-hit wonders? (ListenBrainz, exploratory; after the frozen LB run.)

Picks made 2012-2019 by people rated on picks up to two years before (frozen prescience score, shrunk, >= 20 picks; best
= top fifth, worst = bottom fifth, also top 5%). For each pick, the artist's distinct listeners in each calendar year
(picker excluded), growth after k = 1..6 years: ln((L[Y+k] + 1) / (L[Y] + 1)), Y = the pick's year, compared with all
picks in the same month and size bin ("similar artists"). Bootstrap over people (1,000 draws).
Writes analysis/out/lb_careers.json and analysis/writeup/careers.json.
"""

import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(7171)
B = 1000
K = range(1, 7)
pc = lambda a, q: float(np.percentile(a, q))

b = pl.read_parquet(X / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "artist", "m", "bin", "e"]).with_columns(year=pl.col("m") // 12)
picks = b.filter(pl.col("year").is_between(2012, 2019))
tmp = ROOT / "data" / "_tmp" / "careers"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
con.register("pk", picks.select("user", "artist", "year").to_arrow())
con.execute("CREATE TABLE arts AS SELECT DISTINCT artist FROM pk")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
ay = con.execute(f"""SELECT u.artist, (u.month // 12)::SMALLINT AS y, count(DISTINCT u.user) AS L FROM {uam} u SEMI JOIN arts USING (artist)
                     WHERE u.month BETWEEN {2012 * 12} AND {2025 * 12 + 11} GROUP BY ALL""").pl()
own = con.execute(f"""SELECT DISTINCT u.user, u.artist, (u.month // 12)::SMALLINT AS y FROM {uam} u
                      SEMI JOIN (SELECT DISTINCT user, artist FROM pk) p ON p.user = u.user AND p.artist = u.artist
                      WHERE u.month BETWEEN {2012 * 12} AND {2025 * 12 + 11}""").pl().with_columns(own=pl.lit(1))
shutil.rmtree(tmp, ignore_errors=True)
print(f"artist-years {ay.height:,}, picker-years {own.height:,}", flush=True)


def listeners(df, k):
    yk = (pl.col("year") + k).cast(pl.Int16)
    return (df.with_columns(yk=yk).join(ay.rename({"y": "yk", "L": f"L{k}"}), on=["artist", "yk"], how="left")
            .join(own.rename({"y": "yk", "own": f"o{k}"}), on=["user", "artist", "yk"], how="left")
            .with_columns((pl.col(f"L{k}").fill_null(0) - pl.col(f"o{k}").fill_null(0)).clip(0).alias(f"L{k}")).drop("yk", f"o{k}"))


p = listeners(picks, 0)
for k in K:
    p = listeners(p, k)
for k in K:
    p = p.with_columns(((pl.col(f"L{k}") + 1) / (pl.col("L0") + 1)).log().alias(f"g{k}"))
    p = p.with_columns((pl.col(f"g{k}") - pl.col(f"g{k}").mean().over("m", "bin")).alias(f"x{k}"))

# rate people (cutoff = pick year - 2)
parts = []
for y in range(2012, 2020):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    parts.append(p.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
f = pl.concat(parts)
rows = []
for g, cond in (("best", pl.col("q") > .8), ("worst", pl.col("q") <= .2), ("top5", pl.col("q") > .95)):
    x = f.filter(cond)
    per = x.group_by("user").agg([pl.col(f"x{k}").sum().alias(f"s{k}") for k in K] + [pl.len().alias("n")])
    w = RNG.poisson(1.0, (B, per.height)).astype(float)
    n = per["n"].to_numpy().astype(float)
    for k in K:
        s = per[f"s{k}"].to_numpy()
        bs = np.expm1((w @ s) / (w @ n))
        rows.append({"key": f"{g}:{k}", "group": g, "years": k, "growth": float(np.expm1(s.sum() / n.sum())), "lo": pc(bs, 2.5), "hi": pc(bs, 97.5),
                     "picks": int(n.sum()), "people": per.height})
    print(g, "  ".join(f"+{r['years']}y {r['growth']:+.1%} [{r['lo']:+.1%},{r['hi']:+.1%}]" for r in rows if r["group"] == g), f"({per.height:,} people)")
(ROOT / "analysis" / "out" / "lb_careers.json").write_text(json.dumps(rows, indent=1))
(ROOT / "analysis" / "writeup" / "careers.json").write_text(json.dumps(rows, indent=1))
