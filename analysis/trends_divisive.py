"""Loved by a few or liked by many? Divisive vs forgettable music (2026-10-14, exploratory; ListenBrainz, artists)

Artists as trends_gems.py (first on LB 2015-2022, >= 10 people who tried them in year 1). From year 1:
  widely liked: kept rate = the share of people who tried them that kept listening (the study's rule; pack rows t, k)
  deeply loved: median plays, over their first six months (from their first play), among the people who kept listening
Each split at its median within the artist's first year; artists need >= 3 people who kept listening (to judge depth).
Types: liked by many (wide, shallow), loved by a few (narrow, deep = divisive), both, neither (forgettable).
Outcomes by the third year (as trends_gems.py): never spread, tripled, tenfold; each type reweighted to the same mix of first year and
starting size (log2 bins of year-1 listeners). Also new artists only. Writes analysis/out/trends_divisive.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "div"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
con.execute(f"CREATE TABLE birth AS SELECT artist, min(month) AS F FROM {uam} GROUP BY artist HAVING min(month) BETWEEN {2015 * 12} AND {2022 * 12 + 11}")
tk = con.execute(f"""SELECT r.artist, sum(r.t)::BIGINT AS T, sum(r.k)::BIGINT AS K FROM read_parquet('{ROOT}/data/site/pack_artist_rows.parquet') r JOIN birth b USING (artist)
                     WHERE r.month BETWEEN b.F AND b.F + 11 GROUP BY r.artist HAVING sum(r.t) >= 10""").pl()
con.register("tk", tk.select("artist").to_arrow())
# keepers in year 1 and their plays over their first six months
depth = con.execute(f"""WITH k AS (SELECT DISTINCT p.user, p.artist FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') p JOIN birth b USING (artist)
                                   SEMI JOIN tk USING (artist) WHERE p.m BETWEEN b.F AND b.F + 11),
                             f AS (SELECT u.user, u.artist, min(u.month) AS fm FROM {uam} u SEMI JOIN k USING (user, artist) GROUP BY u.user, u.artist),
                             pl6 AS (SELECT u.user, u.artist, sum(u.plays) AS p FROM {uam} u JOIN f USING (user, artist) WHERE u.month BETWEEN f.fm AND f.fm + 5 GROUP BY ALL)
                        SELECT artist, median(p) AS depth, count(*) AS keepers FROM pl6 GROUP BY artist HAVING count(*) >= 3""").pl()
L = con.execute(f"""SELECT u.artist, count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F AND b.F + 11) AS L1,
                           count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F + 24 AND b.F + 35) AS L3
                    FROM {uam} u JOIN birth b USING (artist) SEMI JOIN tk USING (artist) GROUP BY u.artist""").pl()
new = con.execute(f"""SELECT DISTINCT b.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a JOIN birth b USING (artist)
                      WHERE a.rm BETWEEN b.F - 12 AND b.F""").pl().with_columns(new=pl.lit(1))
D = (tk.join(depth, on="artist").join(L, on="artist").join(con.execute("SELECT artist, F // 12 AS year FROM birth").pl(), on="artist")
     .join(new, on="artist", how="left").fill_null(0)
     .with_columns(rate=pl.col("K") / pl.col("T"), size=(pl.col("L1") + 1).log(2).floor().cast(pl.Int16),
                   never=(pl.col("L3") <= pl.col("L1")).cast(pl.Float64), grew=(pl.col("L3") >= 3 * pl.col("L1")).cast(pl.Float64),
                   ten=(pl.col("L3") >= 10 * pl.col("L1")).cast(pl.Float64)))
D = D.with_columns(wide=pl.col("rate") > pl.col("rate").median().over("year"), deep=pl.col("depth") > pl.col("depth").median().over("year"))
D = D.with_columns(type=pl.when(pl.col("wide") & ~pl.col("deep")).then(pl.lit("liked by many")).when(~pl.col("wide") & pl.col("deep")).then(pl.lit("loved by a few"))
                   .when(pl.col("wide") & pl.col("deep")).then(pl.lit("both")).otherwise(pl.lit("neither")))
out = []
for pop, pf in (("all artists", pl.lit(True)), ("new artists", pl.col("new") == 1)):
    d = D.filter(pf)
    w = d.group_by("year", "size").len().rename({"len": "w"})   # everyone's mix: each type reweighted to it
    print(f"\n== {pop}: {d.height:,} artists (>= 3 people kept listening) | kept rate / plays per keeper (medians) | never spread | tripled | tenfold")
    for t in ("liked by many", "loved by a few", "both", "neither"):
        x = d.filter(pl.col("type") == t)
        c = x.group_by("year", "size").agg(pl.col("never").mean(), pl.col("grew").mean(), pl.col("ten").mean()).join(w, on=["year", "size"])
        r = {"pop": pop, "type": t, "artists": x.height, "rate": float(x["rate"].median()), "depth": float(x["depth"].median()),
             **{k: float((c[k] * c["w"]).sum() / c["w"].sum()) for k in ("never", "grew", "ten")}}
        out.append(r)
        print(f"{t:15s} ({r['artists']:>6,}) | {r['rate']:.0%} / {r['depth']:.0f} plays | {r['never']:.0%} | {r['grew']:.0%} | {r['ten']:.1%}")
(ROOT / "analysis" / "out" / "trends_divisive.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
