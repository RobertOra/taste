"""Do niche-only, new-only, or tilted scores beat the current one (all finds, equal weight)? Reference finds (prescience, songs and
artists) from data/site/_pack_ex_*.parquet with each find's size when found (new listeners in the 6 months before), age, and plays.
Criteria: split-half stability (alternate finds in time order, Spearman-Brown) and prediction (score from finds up to 2020 vs from 2022
on, people with >= 30 finds in each). Exploratory."""
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from scipy.stats import spearmanr

REF = Path(__file__).resolve().parent.parent / "data" / "site"
con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6")
out = []
for unit, rows, first in (("artist", "pack_artist_rows.parquet", "SELECT artist AS item, first_month AS fm FROM read_parquet('{R}/artist_info.parquet')"),
                          ("song", "pack_song_rows.parquet", "SELECT rec AS item, first_month AS fm FROM read_parquet('{R}/pack_song_first.parquet')")):
    ex = pl.read_parquet(REF / f"_pack_ex_{unit}_A.parquet")
    pk = pl.read_parquet(REF / f"_pack_picks_{unit}.parquet", columns=["user", "key", "artist", "m", "w"])
    if unit == "artist":
        ex = ex.join(pk.rename({"key": "item"}).select("user", "item", "m", "w"), on=["user", "item", "m"], how="left")
    else:   # songs were merged per artist and month: total plays of the group
        g = pk.group_by("user", "artist", "m").agg(w=pl.col("w").sum(), item=pl.col("key").min())
        ex = ex.join(g.select("user", "item", "m", "w"), on=["user", "item", "m"], how="left")
    con.register("k", ex.select("item", "m").unique().to_arrow())
    key = "artist" if unit == "artist" else "rec"
    sz = con.execute(f"""SELECT k.item, k.m, coalesce(sum(r.a), 0)::BIGINT AS a0 FROM k LEFT JOIN read_parquet('{REF}/{rows}') r
                         ON r.{key} = k.item AND r.month BETWEEN k.m - 5 AND k.m GROUP BY k.item, k.m""").pl()
    fm = con.execute(first.format(R=REF)).pl()
    d = ex.join(sz, on=["item", "m"], how="left").join(fm, on="item", how="left").with_columns(
        age=(pl.col("m") - pl.col("fm")), w=pl.col("w").fill_null(1).cast(pl.Float64))
    d = d.with_columns(niche=pl.col("a0") <= pl.col("a0").median(), new=pl.col("age") < 12,
                       hooked=pl.col("w") >= pl.col("w").median().over("user"))
    variants = {
        "all finds, equal (current)": pl.lit(1.0),
        "niche only (smaller half)": pl.col("niche").cast(pl.Float64),
        "new only (under a year old)": pl.col("new").cast(pl.Float64),
        "favorites only (more-played half)": pl.col("hooked").cast(pl.Float64),
        "tilt: niche counts double": 1 + pl.col("niche").cast(pl.Float64),
        "tilt: new counts double": 1 + pl.col("new").cast(pl.Float64),
        "tilt: sqrt of plays": pl.col("w").sqrt(),
        "tilt: smaller = more (1/log size)": 1 / (1 + (pl.col("a0") + 1).log(2)),
    }
    for name, wexpr in variants.items():
        x = d.with_columns(wt=wexpr).filter(pl.col("wt") > 0).sort("user", "m", "item")
        sc = lambda f: f.group_by("user").agg(s=(pl.col("wt") * pl.col("excess")).sum() / (pl.col("wt").sum() + 20 * pl.col("wt").mean()), n=pl.len())
        h = x.with_columns(half=pl.int_range(pl.len()).over("user") % 2)
        a, b = sc(h.filter(pl.col("half") == 0)), sc(h.filter(pl.col("half") == 1))
        j = a.join(b, on="user").filter((pl.col("n") >= 30) & (pl.col("n_right") >= 30))
        r = spearmanr(j["s"], j["s_right"]).statistic; stab = 2 * r / (1 + r)
        e, l = sc(x.filter(pl.col("m") < 2021 * 12)), sc(x.filter(pl.col("m") >= 2022 * 12))
        jj = e.join(l, on="user").filter((pl.col("n") >= 30) & (pl.col("n_right") >= 30))
        pred = spearmanr(jj["s"], jj["s_right"]).statistic
        finds = x.group_by("user").agg(n=pl.len())["n"].median()
        out.append((unit, name, stab, pred, finds, j.height, jj.height))
        print(f"{unit:6} {name:36} stability {stab:.3f} ({j.height:,} people)   prediction {pred:.3f} ({jj.height:,} people)   median finds {finds:.0f}", flush=True)
