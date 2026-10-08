"""Derive one row per (user, artist) from the weekly tables, merging matched and unmatched listens.

    data/derived/user_artist/<half>/<archive>.parquet
        user, artist, first_week, last_week, n_weeks, plays, plays_matched

Each archive's complete and partial files hold the same users, so archives are processed
independently. Usage: derive_user_artist.py <half> [--force]
"""

import argparse
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "mlhd"
DST = ROOT / "data" / "derived" / "user_artist"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = DST / args.half
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"derive-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'")
    for c in "0123456789abcdef":
        dest = out / f"mlhdplus-{c}.parquet"
        if dest.exists() and not args.force:
            continue
        complete = SRC / "user_artist_week" / args.half / f"mlhdplus-complete-{c}.parquet"
        partial = SRC / "user_artist_week_partial" / args.half / f"mlhdplus-partial-{c}.parquet"
        part = dest.with_name(f".{dest.name}.tmp")
        con.execute(f"""
            COPY (
                SELECT user, artist,
                       min(week) AS first_week, max(week) AS last_week, count(DISTINCT week)::INT AS n_weeks,
                       sum(plays)::INT AS plays, coalesce(sum(plays) FILTER (WHERE matched), 0)::INT AS plays_matched
                FROM (SELECT *, true AS matched FROM read_parquet('{complete}')
                      UNION ALL SELECT *, false AS matched FROM read_parquet('{partial}'))
                GROUP BY user, artist
                ORDER BY user, artist
            ) TO '{part}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, ROW_GROUP_SIZE 1000000)""")
        os.replace(part, dest)
        print(f"{dest.name}: {con.execute(f'SELECT count(*) FROM read_parquet(\'{dest}\')').fetchone()[0]:,} rows",
              flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
