"""ListenBrainz songs keyed by normalized name (2026-10-14; NOTES.md planned rebuild item 1), for the site's reference.

1. --map: every ListenBrainz song name (data/lb/names/names/part-*.parquet, from lb_names.py) -> a song id = name_hash(song_key(artist,
   track)) (site/normalize.py), so all spellings of one song share an id and a visitor's normalized name finds it.
   Writes data/site_v2/rec_map.parquet (rec_name_h, rec), the same columns the site builders read.
2. --songs: data/mlhd/user_recording/lb_norm/ (user, recording, first_week, span_weeks, plays), as lb_convert_songs.py's
   user_recording/lb but with the normalized ids. The study's own ListenBrainz song tables are left as they were.

Usage: lb_norm_songs.py --map | --songs
"""
import argparse
import hashlib
import shutil
import sys
from multiprocessing import Pool
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
from normalize import song_key  # noqa: E402

LB, D, V2 = ROOT / "data" / "lb", ROOT / "data" / "mlhd", ROOT / "data" / "site_v2"


def h(s):
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big", signed=True)


def batch(args):
    artists, tracks = args
    return [h(song_key(a, t)) for a, t in zip(artists, tracks)]


def build_map():
    """One name slice at a time (all 82M names at once would need ~10 GB of memory)."""
    V2.mkdir(exist_ok=True)
    parts = sorted((LB / "names" / "names").glob("part-*.parquet"))
    out_parts, total = [], 0
    with Pool(6) as pool:
        for k, f in enumerate(parts):
            names = pl.read_parquet(f, columns=["rec_name_h", "artist", "track"])
            step = 200_000
            jobs = [(names["artist"][i:i + step].to_list(), names["track"][i:i + step].to_list()) for i in range(0, names.height, step)]
            ids = [x for part in pool.imap(batch, jobs) for x in part]
            fp = V2 / f"_rec_map_{k:02d}.parquet"
            pl.DataFrame({"rec_name_h": names["rec_name_h"], "rec": pl.Series(ids, dtype=pl.Int64)}).write_parquet(fp)
            out_parts.append(fp); total += names.height
            print(f"slice {k}: {names.height:,} names", flush=True)
            del names, jobs, ids
    con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6")
    con.execute(f"COPY (SELECT * FROM read_parquet('{V2}/_rec_map_*.parquet')) TO '{V2}/rec_map.parquet' (FORMAT parquet, COMPRESSION zstd)")
    for fp in out_parts:
        fp.unlink()
    print("rec_map:", con.execute(f"SELECT count(*), count(DISTINCT rec) FROM read_parquet('{V2}/rec_map.parquet')").fetchone(), flush=True)


def build_songs():
    out = D / "user_recording" / "lb_norm"; out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / "lbnorm"; tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='20GB'")
    lo, hi = int(1104537600 // 604800), int(1790812800 // 604800)   # as lb_convert_songs.py
    for c in "0123456789abcdef":
        i = int(c, 16)
        con.execute(f"""COPY (SELECT w.user::BIGINT AS user, m.rec AS recording, min(w.week)::INT AS first_week,
                                     (max(w.week) - min(w.week))::INT AS span_weeks, sum(w.plays)::INT AS plays
                              FROM read_parquet('{LB}/user_rec_week/*.parquet') w JOIN read_parquet('{V2}/rec_map.parquet') m USING (rec_name_h)
                              WHERE w.user % 16 = {i} AND w.week BETWEEN {lo} AND {hi}
                              GROUP BY w.user, m.rec ORDER BY recording, user)
                        TO '{out}/mlhdplus-complete-{c}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        print("chunk", c, con.execute(f"SELECT count(*), count(DISTINCT recording) FROM read_parquet('{out}/mlhdplus-complete-{c}.parquet')").fetchone(), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--songs", action="store_true")
    a = ap.parse_args()
    if a.map:
        build_map()
    if a.songs:
        build_songs()
