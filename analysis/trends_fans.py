"""Trend 3, part 3: two fans of the same artist: how much else do they share? (2026-10-14, exploratory; ListenBrainz)

One level closer than a niche: two people whose most-played artist that year is the same. Each year 2010-2025, everyone in the
trends_homog.py pool (>= 250 monthly-distinct songs that year; pairwise overlap doesn't depend on how many people are sampled),
each person's 30 most-played artists. Overlap = the share of one fan's 29 other artists (the shared favorite left out) that the
other fan also has. Each fan counts once (each favorite artist's average overlap, weighted by its number of fans); also shown with each artist once and
each pair once (where giant fandoms dominate). 95% range from a bootstrap over favorite artists (200 draws).
Writes analysis/out/trends_fans.json.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
um = con.execute(f"SELECT user, month // 12 AS year, sum(songs) AS sm FROM read_parquet('{SM}/user_month_lb.parquet') GROUP BY ALL").pl()
pool = um.filter(pl.col("sm") >= 250)
rng = np.random.default_rng(31)
out = []
print("year | people | favorite artists shared by 2+ | pairs | overlap of their other artists [95% range]")
for y in range(2010, 2026):
    users = pool.filter(pl.col("year") == y)["user"].to_list()
    con.register("su", pl.DataFrame({"user": users}).to_arrow())
    d = con.execute(f"""SELECT user, artist, sum(plays)::BIGINT AS p FROM read_parquet('{ROOT}/data/derived/user_artist_month/lb/*.parquet') SEMI JOIN su USING (user)
                        WHERE month // 12 = {y} GROUP BY ALL""").pl()
    top = d.sort(["user", "p", "artist"], descending=[False, True, False]).group_by("user", maintain_order=True).head(30)
    top = top.with_columns(rank=pl.int_range(pl.len()).over("user"))
    full = top.group_by("user").len().filter(pl.col("len") == 30)["user"]
    top = top.filter(pl.col("user").is_in(full.to_list()))
    fav = top.filter(pl.col("rank") == 0).select("user", fav="artist")
    rest = top.filter(pl.col("rank") > 0).join(fav, on="user")
    # per favorite artist g: sum over items of c(c-1) among its fans' other artists, and the number of ordered pairs
    c = rest.group_by("fav", "artist").len()
    per = c.group_by("fav").agg(s=(pl.col("len") * (pl.col("len") - 1)).sum()).join(fav.group_by("fav").len().rename({"len": "k"}), on="fav")
    per = per.filter(pl.col("k") >= 2).with_columns(pairs=pl.col("k") * (pl.col("k") - 1))
    s, pr = per["s"].to_numpy().astype(float), per["pairs"].to_numpy().astype(float)
    k = per["k"].to_numpy().astype(float); g = s / pr / 29                 # each favorite artist's own average overlap
    est = float((g * k).sum() / k.sum())                                   # each fan counts once (not each pair)
    eq = float(g.mean())                                                   # each favorite artist counts once
    pooled = s.sum() / pr.sum() / 29                                       # each pair counts once (big fandoms dominate)
    big = float(k.max() / k.sum())
    bs = [((g[i] * k[i]).sum() / k[i].sum()) for i in (rng.integers(0, len(s), len(s)) for _ in range(200))]
    row = {"year": y, "people": len(full), "favorites": per.height, "pairs": int(pr.sum() / 2), "fans": est, "fans_artist_eq": eq, "fans_pairs": float(pooled), "biggest_fandom_share": big,
           "fans_lo": float(np.percentile(bs, 2.5)), "fans_hi": float(np.percentile(bs, 97.5))}
    out.append(row)
    print(f"{y} | {row['people']:,} | {row['favorites']:,} | each fan once {est:.1%} [{row['fans_lo']:.1%}-{row['fans_hi']:.1%}] | each artist once {eq:.1%} | each pair once {pooled:.1%} | biggest fandom {big:.0%} of fans", flush=True)
(ROOT / "analysis" / "out" / "trends_fans.json").write_text(json.dumps(out, indent=1))
