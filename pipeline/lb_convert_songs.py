"""ListenBrainz songs into the MLHD+ layout (half lb): weekly song listening and per-user song history.

Recording ids: a recording name key (artist + track) that maps to one recording MBID in >= 80% of its MBID-tagged listens
gets that MBID's id (last 15 hex digits, the MLHD+ scheme); others keep the 64-bit name hash. Song's artist: the artist
id from data/lb/artist_id_map.parquet.
    data/mlhd/raw/lb/mlhdplus-complete-<c>.parquet       user, ts (= week * 604800), artists [artist], release (null),
                                                         recording, plays   (one row per user, song, week; plays = listens)
    data/mlhd/user_recording/lb/mlhdplus-complete-<c>.parquet   user, recording, first_week, span_weeks, plays
Usage: lb_convert_songs.py [chunk hex digits, default all]
"""

import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
LB = ROOT / "data" / "lb"
D = ROOT / "data" / "mlhd"


def main():
    chunks = sys.argv[1] if len(sys.argv) > 1 else "0123456789abcdef"
    for sub in ("raw", "user_recording"):
        (D / sub / "lb").mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / "lbsongs"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    con.execute(f"""CREATE TABLE rmap AS
        SELECT rec_name_h, arg_max(rec_mbid_id, listens) AS mbid FROM
            (SELECT rec_name_h, rec_mbid_id, sum(listens) AS listens FROM read_parquet('{LB}/rec_mbid/*.parquet') GROUP BY ALL)
        GROUP BY rec_name_h HAVING max(listens) / sum(listens) >= 0.8""")
    con.execute(f"CREATE TABLE amap AS SELECT artist_name_h, artist FROM read_parquet('{LB}/artist_id_map.parquet')")
    lo, hi = int(1104537600 // 604800), int(1790812800 // 604800)
    for c in chunks:
        i = int(c, 16)
        con.execute(f"""CREATE OR REPLACE TABLE w AS
            SELECT w.user::BIGINT AS user, coalesce(r.mbid, w.rec_name_h) AS recording, coalesce(a.artist, w.artist_name_h) AS artist,
                   w.week, sum(w.plays)::INT AS plays
            FROM read_parquet('{LB}/user_rec_week/*.parquet') w
            LEFT JOIN rmap r USING (rec_name_h) LEFT JOIN amap a USING (artist_name_h)
            WHERE w.user % 16 = {i} AND w.week BETWEEN {lo} AND {hi}
            GROUP BY ALL""")
        con.execute(f"""COPY (SELECT user, (week::BIGINT * 604800)::INT AS ts, [artist] AS artists, NULL::BIGINT AS release, recording, plays
                             FROM w ORDER BY user, recording, ts)
                       TO '{D}/raw/lb/mlhdplus-complete-{c}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        con.execute(f"""COPY (SELECT user, recording, min(week)::INT AS first_week, (max(week) - min(week))::INT AS span_weeks, sum(plays)::INT AS plays
                             FROM w GROUP BY user, recording ORDER BY recording, user)
                       TO '{D}/user_recording/lb/mlhdplus-complete-{c}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        n = con.execute("SELECT count(*), count(DISTINCT recording), sum(plays) FROM w").fetchone()
        print(f"chunk {c}: {n[0]:,} user-song-weeks, {n[1]:,} songs, {n[2]:,} plays", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
