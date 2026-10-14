"""Careers or one-hit wonders, for songs (ListenBrainz, exploratory, 2026-10-13): lb_careers.py with songs.

Songs picked 2012-2019 by people rated on their song picks up to two years before (the study's song measure: songs by one
artist found the same month count as one pick; shrunk, >= 20 picks; best = top fifth, worst = bottom fifth, also top 5% / 1%).
For each picked song, its distinct listeners in each calendar year (picker excluded), from data/mlhd/raw/lb (one row per
user, song and week); growth after k = 1..6 years ln((L[Y+k] + 1) / (L[Y] + 1)) vs all picked songs in the same month and
size bin; and how often listeners k years on were >= 10x the pick year's. Bootstrap over people (1,000 draws).
Adds rows keyed "songs:..." (unit "songs") to analysis/writeup/careers.json and careerten.json; artist rows untouched.
"""
import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X, D, W = ROOT / "data" / "derived", ROOT / "data" / "mlhd", ROOT / "analysis" / "writeup"
RNG = np.random.default_rng(7172)
B = 1000
K = range(1, 7)
pc = lambda a, q: float(np.percentile(a, q))

b = pl.read_parquet(X / "bet_outcomes" / "A_song_lb.parquet", columns=["user", "item", "artist", "m", "bin", "e"]).with_columns(year=pl.col("m") // 12)
groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)
picks = b.filter(pl.col("year").is_between(2012, 2019))
tmp = ROOT / "data" / "_tmp" / "careers_songs"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='20GB'")
con.register("pk", picks.select("user", "item", "year").to_arrow())
con.execute("CREATE TABLE recs AS SELECT DISTINCT item AS recording FROM pk")
con.execute("CREATE TABLE pairs AS SELECT DISTINCT user, item AS recording FROM pk")
YEAR = "year(make_timestamp(ts::BIGINT * 1000000))"
ay, own = [], []
for c in "0123456789abcdef":
    src = f"read_parquet('{D}/raw/lb/mlhdplus-complete-{c}.parquet')"
    ay.append(con.execute(f"""SELECT r.recording, ({YEAR})::SMALLINT AS y, count(DISTINCT r.user) AS L FROM {src} r SEMI JOIN recs USING (recording)
                              WHERE {YEAR} BETWEEN 2012 AND 2025 GROUP BY ALL""").pl())
    own.append(con.execute(f"""SELECT DISTINCT r.user, r.recording, ({YEAR})::SMALLINT AS y FROM {src} r SEMI JOIN pairs USING (user, recording)
                               WHERE {YEAR} BETWEEN 2012 AND 2025""").pl())
    print("chunk", c, flush=True)
# users are split across chunks, so a song's listeners are summed over chunks
ay = pl.concat(ay).group_by("recording", "y").agg(pl.col("L").sum()).rename({"recording": "item"})
own = pl.concat(own).rename({"recording": "item"}).with_columns(own=pl.lit(1))
shutil.rmtree(tmp, ignore_errors=True)
print(f"song-years {ay.height:,}, picker-years {own.height:,}", flush=True)


def listeners(df, k):
    yk = (pl.col("year") + k).cast(pl.Int16)
    return (df.with_columns(yk=yk).join(ay.rename({"y": "yk", "L": f"L{k}"}), on=["item", "yk"], how="left")
            .join(own.rename({"y": "yk", "own": f"o{k}"}), on=["user", "item", "yk"], how="left")
            .with_columns((pl.col(f"L{k}").fill_null(0) - pl.col(f"o{k}").fill_null(0)).clip(0).alias(f"L{k}")).drop("yk", f"o{k}"))


p = listeners(picks, 0)
for k in K:
    p = listeners(p, k)
for k in K:
    p = p.with_columns(((pl.col(f"L{k}") + 1) / (pl.col("L0") + 1)).log().alias(f"g{k}"))
    p = p.with_columns((pl.col(f"g{k}") - pl.col(f"g{k}").mean().over("m", "bin")).alias(f"x{k}"),
                       (pl.col(f"g{k}") >= np.log(10)).cast(pl.Float64).alias(f"t{k}"))
    p = p.with_columns(pl.col(f"t{k}").mean().over("m", "bin").alias(f"te{k}"))

parts = []
for y in range(2012, 2020):
    past = (groups.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    parts.append(p.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
f = pl.concat(parts)
rows = []
for g, cond in (("best", pl.col("q") > .8), ("worst", pl.col("q") <= .2), ("top5", pl.col("q") > .95), ("top1", pl.col("q") > .99)):
    x = f.filter(cond)
    per = x.group_by("user").agg([pl.col(f"x{k}").sum().alias(f"s{k}") for k in K] + [pl.len().alias("n")])
    # top 1% added 2026-10-14 with its own draws. Note: group_by order varies between runs, so reruns move the 95% ranges slightly;
    # the write-up keeps the earlier runs' rows and added only the top-1% rows from the 2026-10-14 run
    w = (RNG if g != "top1" else np.random.default_rng(7173)).poisson(1.0, (B, per.height)).astype(float)
    n = per["n"].to_numpy().astype(float)
    for k in K:
        s = per[f"s{k}"].to_numpy()
        bs = np.expm1((w @ s) / (w @ n))
        rows.append({"key": f"songs:{g}:{k}", "unit": "songs", "group": g, "years": k, "growth": float(np.expm1(s.sum() / n.sum())),
                     "lo": pc(bs, 2.5), "hi": pc(bs, 97.5), "picks": int(n.sum()), "people": per.height})
    print(g, "  ".join(f"+{r['years']}y {r['growth']:+.1%} [{r['lo']:+.1%},{r['hi']:+.1%}]" for r in rows if r["group"] == g), f"({per.height:,} people)")
ten = []
for g, cond in (("best", pl.col("q") > .8), ("top5", pl.col("q") > .95), ("top1", pl.col("q") > .99), ("worst", pl.col("q") <= .2)):
    x = f.filter(cond)
    per = x.group_by("user").agg([pl.col(f"t{k}").sum().alias(f"h{k}") for k in K] + [pl.col(f"te{k}").sum().alias(f"e{k}") for k in K] + [pl.len().alias("n")])
    w = RNG.poisson(1.0, (B, per.height)).astype(float)
    for k in K:
        h, e = per[f"h{k}"].to_numpy(), per[f"e{k}"].to_numpy()
        bs = (w @ h) / (w @ e)
        ten.append({"key": f"songs:{g}:{k}", "unit": "songs", "group": g, "years": k, "times_similar": float(h.sum() / e.sum()), "lo": pc(bs, 2.5),
                    "hi": pc(bs, 97.5), "per_1000": float(h.sum() / per["n"].sum() * 1000), "similar_per_1000": float(e.sum() / per["n"].sum() * 1000),
                    "events": int(h.sum()), "people": per.height})
    print("tenfold", g, "  ".join(f"+{r['years']}y {r['times_similar']:.2f}x [{r['lo']:.2f},{r['hi']:.2f}] ({r['events']})" for r in ten if r["group"] == g))
for name, new in (("careers", rows), ("careerten", ten)):
    old = [r for r in json.loads((W / f"{name}.json").read_text()) if r.get("unit", "artists") != "songs"]
    (W / f"{name}.json").write_text(json.dumps(old + new, indent=1))
(ROOT / "analysis" / "out" / "lb_careers_songs.json").write_text(json.dumps({"growth": rows, "tenfold": ten}, indent=1))
