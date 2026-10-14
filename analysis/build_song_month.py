"""Shared table for the music-trends questions (2026-10-14, exploratory): each ListenBrainz song's listeners month by month.

From the study's LB song table (data/mlhd/raw/lb; study song ids): per (recording, month) the distinct listeners and plays, plus
the song's main artist. Built in 32 slices of songs (each slice holds whole songs, so counts are exact).
Also each user's activity per month (distinct songs, plays), for normalizing by who was active.
Writes data/derived/song_month/lb/part-XX.parquet (recording, artist, month, listeners, plays) and
data/derived/song_month/user_month_lb.parquet (user, month, songs, plays).
"""
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived" / "song_month"; (OUT / "lb").mkdir(parents=True, exist_ok=True)
TMP = ROOT / "data" / "_tmp" / "song_month"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
raw = f"read_parquet('{ROOT}/data/mlhd/raw/lb/*.parquet')"
MON = "(year(to_timestamp(ts)) * 12 + month(to_timestamp(ts)) - 1)::SMALLINT"
for c in range(32):
    f = OUT / "lb" / f"part-{c:02d}.parquet"
    if f.exists():
        continue
    con.execute(f"""COPY (SELECT recording, any_value(artists[1]) AS artist, {MON} AS month, count(DISTINCT user)::INT AS listeners, sum(plays)::INT AS plays
                          FROM {raw} WHERE ((recording % 32) + 32) % 32 = {c} GROUP BY recording, month)
                    TO '{f}' (FORMAT parquet, COMPRESSION zstd)""")
    print("slice", c, flush=True)
if not (OUT / "user_month_lb.parquet").exists():   # in slices of people (all at once overflows temp space)
    for c in range(16):
        con.execute(f"""COPY (SELECT user, {MON} AS month, count(DISTINCT recording)::INT AS songs, sum(plays)::INT AS plays FROM {raw}
                              WHERE user % 16 = {c} GROUP BY user, month) TO '{TMP}/um_{c:02d}.parquet' (FORMAT parquet)""")
    con.execute(f"COPY (SELECT * FROM read_parquet('{TMP}/um_*.parquet')) TO '{OUT}/user_month_lb.parquet' (FORMAT parquet, COMPRESSION zstd)")
print(con.execute(f"SELECT count(*), count(DISTINCT recording) FROM read_parquet('{OUT}/lb/*.parquet')").fetchone(), flush=True)
shutil.rmtree(TMP, ignore_errors=True)
