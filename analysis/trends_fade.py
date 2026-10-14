"""Trend 1: do songs fade faster than they used to? (2026-10-14, exploratory; ListenBrainz songs)

Songs whose first LB listener came 2010-2022 (birth F); peak = the month with the most listeners within F..F+35 (earliest if tied);
songs with >= 20 listeners at the peak. Grouped by the peak's year (peaks through 2024, so 24 months follow).
  share kept (whole audience): listeners as a share of all active LB users that month, k = 3, 6, 12, 24 months after the peak,
    divided by the peak month's share (median over songs).
  still playing (same people): of the users who played the song in its peak month and played anything k months later, the share
    who played this song then (pooled over songs).
Both for all songs and for new songs (the song's artist had a release in the 2 months up to F), and by peak size (20-49, 50+).
Prints a table; writes analysis/out/trends_fade.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
TMP = ROOT / "data" / "_tmp" / "fade"; TMP.mkdir(parents=True, exist_ok=True)
K = [3, 6, 12, 24]
LASTP = 2024 * 12 + 7   # peak + 24 <= Aug 2026
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
sm, um = f"read_parquet('{SM}/lb/*.parquet')", f"read_parquet('{SM}/user_month_lb.parquet')"
con.execute(f"CREATE TABLE act AS SELECT month, count(*)::DOUBLE AS active FROM {um} GROUP BY month")
first = True
for f in sorted((SM / "lb").glob("part-*.parquet")):   # one file of whole songs at a time
    q = f"""WITH s AS (SELECT * FROM read_parquet('{f}')),
                 b AS (SELECT recording, min(month) AS F, any_value(artist) AS artist FROM s GROUP BY recording
                       HAVING min(month) BETWEEN {2010 * 12} AND {2022 * 12 + 11})
            SELECT s.recording, b.F, b.artist, arg_min(s.month, -s.listeners * 10000 + s.month) AS P, max(s.listeners) AS Lp
            FROM s JOIN b USING (recording) WHERE s.month BETWEEN b.F AND b.F + 35 GROUP BY s.recording, b.F, b.artist HAVING max(s.listeners) >= 20"""
    con.execute(f"CREATE TABLE peak AS {q}" if first else f"INSERT INTO peak {q}"); first = False
con.execute(f"DELETE FROM peak WHERE P > {LASTP}")
con.execute(f"""ALTER TABLE peak ADD COLUMN newsong INT; UPDATE peak SET newsong = (artist IN (SELECT a.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a
                WHERE a.artist = peak.artist AND a.rm BETWEEN peak.F - 2 AND peak.F))::INT""")
print("songs:", con.execute("SELECT count(*), sum(newsong) FROM peak").fetchone(), flush=True)
# whole audience: share kept
cols = ", ".join(f"max(CASE WHEN s.month = p.P + {k} THEN s.listeners / a.active END) / max(CASE WHEN s.month = p.P THEN s.listeners / a.active END) AS r{k}" for k in K)
whole = con.execute(f"""SELECT p.recording, p.P // 12 AS year, p.Lp, p.newsong, {cols} FROM peak p JOIN {sm} s ON s.recording = p.recording
                        AND s.month IN (p.P, {', '.join(f'p.P + {k}' for k in K)}) JOIN act a ON a.month = s.month GROUP BY ALL""").pl()
whole = whole.with_columns([pl.col(f"r{k}").fill_null(0) for k in K])
# same people: users in the peak month, active k months later, still playing the song
raw = f"read_parquet('{ROOT}/data/mlhd/raw/lb/*.parquet')"
MON = "(year(to_timestamp(r.ts)) * 12 + month(to_timestamp(r.ts)) - 1)::SMALLINT"
parts = []
for c in range(16):   # one scan per slice of users: their plays of peaked songs at the peak and k months later
    con.execute(f"""CREATE OR REPLACE TABLE x AS SELECT DISTINCT r.user, p.recording, p.P, ({MON} - p.P)::INT AS d FROM {raw} r JOIN peak p ON p.recording = r.recording
                    WHERE r.user % 16 = {c} AND {MON} - p.P IN (0, {', '.join(map(str, K))})""")
    for k in K:
        parts.append(con.execute(f"""
            WITH pu AS (SELECT user, recording, P FROM x WHERE d = 0),
                 alive AS (SELECT pu.* FROM pu JOIN {um} u ON u.user = pu.user AND u.month = pu.P + {k})
            SELECT a.recording, {k} AS k, count(*) AS alive, count(s.user) AS still FROM alive a
            LEFT JOIN (SELECT user, recording FROM x WHERE d = {k}) s USING (user, recording) GROUP BY a.recording""").pl())
    print("people slice", c, flush=True)
same = pl.concat(parts).group_by("recording", "k").agg(pl.col("alive").sum(), pl.col("still").sum())
meta = con.execute("SELECT recording, P // 12 AS year, Lp, newsong FROM peak").pl()
same = same.join(meta, on="recording")
out = []
for pop, flt in (("all songs", pl.lit(True)), ("new songs", pl.col("newsong") == 1)):
    for band, bf in (("all sizes", pl.lit(True)), ("20-49 at peak", pl.col("Lp") < 50), ("50+ at peak", pl.col("Lp") >= 50)):
        print(f"\n== {pop}, {band}: year | songs | share kept (whole audience) at +3/+6/+12/+24 months | still playing (same people) at +3/+6/+12/+24")
        for y in range(2010, 2025):
            w = whole.filter(flt & bf & (pl.col("year") == y))
            s = same.filter(flt & bf & (pl.col("year") == y))
            if w.height < 200:
                continue
            row = {"pop": pop, "band": band, "year": y, "songs": w.height}
            for k in K:
                row[f"kept{k}"] = float(w[f"r{k}"].median())
                sk = s.filter(pl.col("k") == k)
                row[f"still{k}"] = float(sk["still"].sum() / max(sk["alive"].sum(), 1))
            out.append(row)
            print(f"{y} | {w.height:>7,} | " + " ".join(f"{row[f'kept{k}']:5.0%}" for k in K) + " | " + " ".join(f"{row[f'still{k}']:5.0%}" for k in K), flush=True)
(ROOT / "analysis" / "out" / "trends_fade.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
