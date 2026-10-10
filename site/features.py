"""Shared pick features and corrections for the site (used by build_baselines.py and score.py, so visitors' picks and the
ListenBrainz reference picks are treated identically).

For a pick of item k (artist or recording) by artist a in month m:
    a0 = new ListenBrainz listeners of k in months m-5..m, a1 = in m+7..m+12, ap = in m-11..m-6
    g  = ln((a1 + 1) / (a0 + 1)); took off = g >= ln 3 (three times as many new listeners);  bin = floor(log2(a0 + 1)) (0-14);  mo = momentum bin of (a0 + 1) / (ap + 1), -3..3
    corrections (additive, as in the project's frozen measure): scene of a that year, item age, release timing of a
    (release in m-3..m and/or m+1..m+3, or none known), country of a.
excess = g - mean g of ListenBrainz picks in the same month and size bin - the correction effects.
"""
import math
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "site"
FACTORS = ["mo", ["year", "scene"], "age", "relc", "country"]


def raw_features(con, pk, unit):
    """pk: registered table/view name with columns key, artist, m. Returns key, artist, m, a0, a1, ap, scene, relc, age, country."""
    adopt, akey = (REF / "artist_adopt.parquet", "artist") if unit == "artist" else (REF / "rec_adopt.parquet", "rec")
    con.execute(f"CREATE OR REPLACE TEMP TABLE _km AS SELECT DISTINCT key, artist, m FROM {pk}")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _ka AS SELECT k.key, k.m,
          coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m - 5 AND k.m), 0)::BIGINT AS a0,
          coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m + 7 AND k.m + 12), 0)::BIGINT AS a1,
          coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m - 11 AND k.m - 6), 0)::BIGINT AS ap
        FROM (SELECT DISTINCT key, m FROM _km) k LEFT JOIN read_parquet('{adopt}') a ON a.{akey} = k.key AND a.month BETWEEN k.m - 11 AND k.m + 12
        GROUP BY k.key, k.m""")
    if unit == "artist":
        first = f"SELECT artist AS key, first_month AS fm FROM read_parquet('{REF}/artist_info.parquet') SEMI JOIN (SELECT DISTINCT key FROM _km) s ON s.key = artist"
    else:
        first = f"SELECT rec AS key, min(month) AS fm FROM read_parquet('{adopt}') SEMI JOIN (SELECT DISTINCT key FROM _km) s ON s.key = rec GROUP BY rec"
    con.execute(f"CREATE OR REPLACE TEMP TABLE _fi AS {first}")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _rel AS SELECT k.artist, k.m,
          CASE WHEN count(x.rm) = 0 THEN 4 ELSE 2 * (count(*) FILTER (WHERE x.rm > k.m AND x.rm <= k.m + 3) > 0)::INT
               + (count(*) FILTER (WHERE x.rm >= k.m - 3 AND x.rm <= k.m) > 0)::INT END AS relc
        FROM (SELECT DISTINCT artist, m FROM _km) k LEFT JOIN read_parquet('{REF}/artist_release.parquet') x ON x.artist = k.artist GROUP BY k.artist, k.m""")
    age = ("CASE WHEN fi.fm <= 2005 * 12 THEN 9 WHEN k.m - fi.fm < 3 THEN 0 WHEN k.m - fi.fm < 6 THEN 1 WHEN k.m - fi.fm < 12 THEN 2 "
           "WHEN k.m - fi.fm < 24 THEN 3 ELSE 4 END") if unit == "artist" else \
          ("CASE WHEN fi.fm <= 2005 * 12 THEN 9 WHEN k.m - fi.fm <= 2 THEN k.m - fi.fm WHEN k.m - fi.fm < 6 THEN 3 WHEN k.m - fi.fm < 12 THEN 4 "
           "WHEN k.m - fi.fm < 24 THEN 5 ELSE 6 END")
    return con.execute(f"""SELECT k.key, k.artist, k.m, ka.a0, ka.a1, ka.ap, coalesce(s.scene, -1) AS scene, coalesce(rel.relc, 4) AS relc,
          coalesce({age}, 9) AS age, coalesce(i.country, '?') AS country
        FROM _km k JOIN _ka ka ON ka.key = k.key AND ka.m = k.m LEFT JOIN _fi fi ON fi.key = k.key
        LEFT JOIN read_parquet('{REF}/artist_scene.parquet') s ON s.artist = k.artist AND s.year = k.m // 12
        LEFT JOIN _rel rel ON rel.artist = k.artist AND rel.m = k.m
        LEFT JOIN read_parquet('{REF}/artist_info.parquet') i ON i.artist = k.artist""").pl()


def derive(df):
    """Add g, bin, mo, year, ten from a0, a1, ap (a0 already adjusted for the picker where needed)."""
    return df.with_columns(g=((pl.col("a1") + 1) / (pl.col("a0") + 1)).log(), bin=(pl.col("a0") + 1).log(2).floor().clip(0, 14).cast(pl.Int8),
                           mo=(((pl.col("a0") + 1) / (pl.col("ap") + 1)).log(2) / 0.5).floor().clip(-3, 3).cast(pl.Int8), year=(pl.col("m") // 12).cast(pl.Int16),
                           ten=(((pl.col("a1") + 1) / (pl.col("a0") + 1)).log() >= math.log(10)).cast(pl.Float64),
                           up3=(((pl.col("a1") + 1) / (pl.col("a0") + 1)).log() >= math.log(3)).cast(pl.Float64))


def fit_effects(df, iters=4):
    """Baseline (m, bin) and additive correction effects by backfitting. Returns (baseline, {factor_name: effect table}, excess)."""
    base = df.group_by("m", "bin").agg(g_mean=pl.col("g").mean(), ten_rate=pl.col("ten").mean(), up3_rate=pl.col("up3").mean(), n=pl.len())
    d = df.join(base.select("m", "bin", "g_mean"), on=["m", "bin"])
    r = (d["g"] - d["g_mean"]).to_numpy().copy()
    eff = {}
    for _ in range(iters):
        for f in FACTORS:
            cols = f if isinstance(f, list) else [f]
            name = "_".join(cols)
            prev = eff[name] if name in eff else None
            part = r + (d.select(cols).join(prev, on=cols, how="left")["eff"].fill_null(0).to_numpy() if prev is not None else 0)
            t = d.select(cols).with_columns(v=pl.Series(part)).group_by(cols).agg(eff=pl.col("v").mean())
            eff[name] = t
            r = part - d.select(cols).join(t, on=cols, how="left")["eff"].to_numpy()
    return base, eff, r


def apply_effects(df, unit):
    """excess for new picks using the stored baseline and effects (data/site/baseline_{unit}.parquet, effects_{unit}_*.parquet)."""
    base = pl.read_parquet(REF / f"baseline_{unit}.parquet")
    d = df.join(base.select("m", "bin", "g_mean", "ten_rate", "up3_rate"), on=["m", "bin"], how="left")
    ex = pl.col("g") - pl.col("g_mean")
    for f in FACTORS:
        cols = f if isinstance(f, list) else [f]
        name = "_".join(cols)
        t = pl.read_parquet(REF / f"effects_{unit}_{name}.parquet").rename({"eff": f"eff_{name}"})
        d = d.join(t, on=cols, how="left").with_columns(pl.col(f"eff_{name}").fill_null(0))
        ex = ex - pl.col(f"eff_{name}")
    return d.with_columns(excess=ex)
