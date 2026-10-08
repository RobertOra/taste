"""Derive per-archive tables needed for bets and the popularity market (one half at a time).

Matched and unmatched weekly listens are merged first (summing plays per user/artist/week).

    data/derived/user_artist_month/<half>/mlhdplus-<c>.parquet
        user, artist, month, plays, n_weeks          month = year*12 + month-1 of the week's midpoint
    data/derived/bets/<half>/mlhdplus-<c>.parquet
        user, artist, first_week, last_week, n_weeks, plays,
        w2, w4, w8      week in which the user's 2nd/4th/8th distinct listening week occurred (null if never)
        w_p10           week in which cumulative plays reached 10 (null if never)
        plays_26w       plays in the 26 weeks starting at the first listen

Usage: derive_bets.py <half> [--only <hex digits>] [--force]
"""

import argparse
import os
import shutil
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "mlhd"
DST = ROOT / "data" / "derived"
MONTH = "(year(make_timestamp(week::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp(week::BIGINT * 604800000000 + 302400000000)) - 1)::SMALLINT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    ap.add_argument("--only", default="0123456789abcdef")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    tmp = ROOT / "data" / "_tmp" / f"bets-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='7GB'; SET threads=8; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    for c in args.only:
        comp = SRC / "user_artist_week" / args.half / f"mlhdplus-complete-{c}.parquet"
        part = SRC / "user_artist_week_partial" / args.half / f"mlhdplus-partial-{c}.parquet"
        weekly = f"""(SELECT user, artist, week, sum(plays) AS plays FROM (
            SELECT * FROM read_parquet('{comp}') UNION ALL SELECT * FROM read_parquet('{part}')) GROUP BY ALL)"""
        queries = {
            "user_artist_month": f"""
                SELECT user, artist, {MONTH} AS month, sum(plays)::INT AS plays, count(*)::SMALLINT AS n_weeks
                FROM {weekly} GROUP BY ALL ORDER BY user, artist, month""",
            "bets": f"""
                WITH r AS (
                    SELECT user, artist, week, plays,
                           row_number() OVER w AS rn,
                           sum(plays) OVER (w ROWS UNBOUNDED PRECEDING) AS cp,
                           min(week) OVER (PARTITION BY user, artist) AS fw
                    FROM {weekly} WINDOW w AS (PARTITION BY user, artist ORDER BY week))
                SELECT user, artist, min(week) AS first_week, max(week) AS last_week, max(rn)::INT AS n_weeks,
                       sum(plays)::INT AS plays,
                       min(week) FILTER (WHERE rn = 2) AS w2, min(week) FILTER (WHERE rn = 4) AS w4,
                       min(week) FILTER (WHERE rn = 8) AS w8, min(week) FILTER (WHERE cp >= 10) AS w_p10,
                       coalesce(sum(plays) FILTER (WHERE week < fw + 26), 0)::INT AS plays_26w
                FROM r GROUP BY user, artist ORDER BY user, artist""",
        }
        for name, sql in queries.items():
            dest = DST / name / args.half / f"mlhdplus-{c}.parquet"
            if dest.exists() and not args.force:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            part_file = dest.with_name(f".{dest.name}.tmp")
            con.execute(f"COPY ({sql}) TO '{part_file}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, "
                        "ROW_GROUP_SIZE 1000000)")
            os.replace(part_file, dest)
            n = con.execute(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0]
            print(f"{name}/{c}: {n:,} rows, {dest.stat().st_size / 1e9:.2f} GB, {time.time() - t0:.0f}s", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
