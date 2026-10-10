"""Careers or one-hit wonders? (ListenBrainz, exploratory; after the frozen LB run.)

Picks made 2012-2019 by people rated on picks up to two years before (frozen prescience score, shrunk, >= 20 picks; best
= top fifth, worst = bottom fifth, also top 5%). For each pick, the artist's distinct listeners in each calendar year
(picker excluded), growth after k = 1..6 years: ln((L[Y+k] + 1) / (L[Y] + 1)), Y = the pick's year, compared with all
picks in the same month and size bin ("similar artists"). Bootstrap over people (1,000 draws).
Also: how often a pick's listeners k years on were >= 10x the pick year's, vs similar picks (best, top 5%, top 1%, worst).
Writes analysis/out/lb_careers.json, lb_careers_tenfold.json and analysis/writeup/careers.json.
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
    p = p.with_columns((pl.col(f"g{k}") - pl.col(f"g{k}").mean().over("m", "bin")).alias(f"x{k}"),
                       (pl.col(f"g{k}") >= np.log(10)).cast(pl.Float64).alias(f"t{k}"))
    p = p.with_columns(pl.col(f"t{k}").mean().over("m", "bin").alias(f"te{k}"))

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
ten = []
for g, cond in (("best", pl.col("q") > .8), ("top5", pl.col("q") > .95), ("top1", pl.col("q") > .99), ("worst", pl.col("q") <= .2)):
    x = f.filter(cond)
    per = x.group_by("user").agg([pl.col(f"t{k}").sum().alias(f"h{k}") for k in K] + [pl.col(f"te{k}").sum().alias(f"e{k}") for k in K] + [pl.len().alias("n")])
    w = RNG.poisson(1.0, (B, per.height)).astype(float)
    for k in K:
        h, e = per[f"h{k}"].to_numpy(), per[f"e{k}"].to_numpy()
        bs = (w @ h) / (w @ e)
        ten.append({"key": f"{g}:{k}", "group": g, "years": k, "times_similar": float(h.sum() / e.sum()), "lo": pc(bs, 2.5), "hi": pc(bs, 97.5),
                    "per_1000": float(h.sum() / per["n"].sum() * 1000), "similar_per_1000": float(e.sum() / per["n"].sum() * 1000), "events": int(h.sum()),
                    "people": per.height})
    print("tenfold", g, "  ".join(f"+{r['years']}y {r['times_similar']:.2f}x [{r['lo']:.2f},{r['hi']:.2f}] ({r['per_1000']:.1f} vs {r['similar_per_1000']:.1f}/1000, {r['events']})"
                                  for r in ten if r["group"] == g))
(ROOT / "analysis" / "out" / "lb_careers_tenfold.json").write_text(json.dumps(ten, indent=1))
(ROOT / "analysis" / "out" / "lb_careers.json").write_text(json.dumps(rows, indent=1))
(ROOT / "analysis" / "writeup" / "careers.json").write_text(json.dumps(rows, indent=1))
