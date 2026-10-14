"""Check for trend 2 (2026-10-14, exploratory): is the rise in top-song share real, or spelling splits in older data?

Per listener and month, how many different songs by a new artist they played, for artists born on LB 2010-2022 (first three years,
artists with >= 100 listener-months, as trends_onehit.py). Spelling splits mostly can't inflate this (one listener usually sees one
spelling), so if listeners play fewer songs per artist over time, the shift toward single songs is real.
  songs per listener-month (mean), and the share of listener-months with just one of the artist's songs.
Built in 16 slices of people. Prints by birth year; writes analysis/out/trends_onehit_check.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
TMP = ROOT / "data" / "_tmp" / "onehit"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
sm, raw = f"read_parquet('{SM}/lb/*.parquet')", f"read_parquet('{ROOT}/data/mlhd/raw/lb/*.parquet')"
MON = "(year(to_timestamp(r.ts)) * 12 + month(to_timestamp(r.ts)) - 1)::SMALLINT"
con.execute(f"""CREATE TABLE ab AS SELECT artist, min(month) AS F FROM {sm} WHERE artist IS NOT NULL GROUP BY artist
                HAVING min(month) BETWEEN {2010 * 12} AND {2022 * 12 + 11}""")
con.execute(f"""CREATE TABLE keep AS SELECT ab.artist, ab.F FROM ab JOIN {sm} s USING (artist) WHERE s.month BETWEEN ab.F AND ab.F + 35
                GROUP BY ab.artist, ab.F HAVING sum(s.listeners) >= 100""")
parts = []
for c in range(16):
    parts.append(con.execute(f"""WITH x AS (SELECT r.user, k.artist, k.F, {MON} AS month, count(DISTINCT r.recording) AS n FROM {raw} r
                                           JOIN keep k ON k.artist = r.artists[1] WHERE r.user % 16 = {c} AND {MON} BETWEEN k.F AND k.F + 35 GROUP BY ALL)
                                 SELECT F // 12 AS year, count(*)::BIGINT AS lm, sum(n)::BIGINT AS songs, sum((n = 1)::INT)::BIGINT AS single FROM x GROUP BY ALL""").pl())
    print("slice", c, flush=True)
d = pl.concat(parts).group_by("year").agg(pl.col("lm").sum(), pl.col("songs").sum(), pl.col("single").sum()).sort("year")
out = []
print("birth year | listener-months | songs per listener-month | share with just one song")
for r in d.iter_rows(named=True):
    out.append({"year": r["year"], "listener_months": r["lm"], "songs_per": r["songs"] / r["lm"], "single_share": r["single"] / r["lm"]})
    print(f"{r['year']} | {r['lm']:>10,} | {r['songs'] / r['lm']:.2f} | {r['single'] / r['lm']:.0%}")
(ROOT / "analysis" / "out" / "trends_onehit_check.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
