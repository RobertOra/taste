"""Trend 2: are one-hit wonders more common? (2026-10-14, exploratory; ListenBrainz songs grouped by their main artist)

Artists whose first LB song listener came 2010-2022 (birth F). Over their first three years (F..F+35), listener-months per song
(a listener counted once per month per song). Artists with >= 100 listener-months in that window.
  top song's share: the biggest song's share of the artist's listener-months (median over artists);
  one-hit: share of artists whose top song holds >= 80% (and >= 50%);
  songs that mattered: songs with >= 10% of the artist's listener-months (mean).
For all artists and new artists (a MusicBrainz release in the 12 months before F), by birth year and by size (100-499, 500+).
Caveat: one song split across spellings would lower the top share; the study's song ids merge many but not all.
Writes analysis/out/trends_onehit.json.
"""
import json
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
sm = f"read_parquet('{SM}/lb/*.parquet')"
con.execute(f"""CREATE TABLE ab AS SELECT artist, min(month) AS F FROM {sm} WHERE artist IS NOT NULL GROUP BY artist
                HAVING min(month) BETWEEN {2010 * 12} AND {2022 * 12 + 11}""")
per = con.execute(f"""WITH s AS (SELECT s.artist, s.recording, sum(s.listeners) AS lm FROM {sm} s JOIN ab USING (artist)
                                 WHERE s.month BETWEEN ab.F AND ab.F + 35 GROUP BY ALL)
                      SELECT artist, sum(lm) AS total, max(lm) / sum(lm) AS top, sum((lm >= 0.1 * t)::INT) AS mattered
                      FROM (SELECT *, sum(lm) OVER (PARTITION BY artist) AS t FROM s) GROUP BY artist HAVING sum(lm) >= 100""").pl()
newa = con.execute(f"""SELECT DISTINCT ab.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a JOIN ab USING (artist)
                       WHERE a.rm BETWEEN ab.F - 12 AND ab.F""").pl().with_columns(new=pl.lit(1))
D = per.join(con.execute("SELECT artist, F // 12 AS year FROM ab").pl(), on="artist").join(newa, on="artist", how="left").fill_null(0)
out = []
for pop, flt in (("all artists", pl.lit(True)), ("new artists", pl.col("new") == 1)):
    for band, bf in (("all sizes", pl.lit(True)), ("100-499", pl.col("total") < 500), ("500+", pl.col("total") >= 500)):
        print(f"\n== {pop}, {band}: year | artists | top song's share (median) | one-hit >= 80% | >= 50% | songs with >= 10% (mean)")
        for y in range(2010, 2023):
            d = D.filter(flt & bf & (pl.col("year") == y))
            if d.height < 100:
                continue
            row = {"pop": pop, "band": band, "year": y, "artists": d.height, "top_median": float(d["top"].median()),
                   "onehit80": float((d["top"] >= 0.8).mean()), "onehit50": float((d["top"] >= 0.5).mean()), "mattered": float(d["mattered"].mean())}
            out.append(row)
            print(f"{y} | {d.height:>6,} | {row['top_median']:5.0%} | {row['onehit80']:5.0%} | {row['onehit50']:5.0%} | {row['mattered']:.1f}")
(ROOT / "analysis" / "out" / "trends_onehit.json").write_text(json.dumps(out, indent=1))
