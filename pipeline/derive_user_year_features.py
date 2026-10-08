"""Per-user, per-calendar-year impostor features, so the forward test can adjust for impostors measured on the
past period only (EVALUATION.md §3.2 refinement). One half at a time.

    data/derived/user_year_features/<half>.parquet
        user, year, listens, unmatched_listens, active_months, new_artists, committed, mainstream_plays, artist_plays
New artists / committed count first listens after the user's 26-week onboarding (commitment = 4 distinct weeks
within 26 weeks). Mainstream = plays of the top 1% of artists by plays in this half (as in user_features).
The evaluator sums years up to a cutoff and forms the same features as user_features from those sums
(history length and join year from the user's first listen; no-id share stays whole-history: not stored per year).

Usage: derive_user_year_features.py <half>
"""

import argparse
import atexit
import os
import shutil
import signal
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
D = ROOT / "data" / "mlhd"
YEAR = "year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000))"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    h = ap.parse_args().half
    out = X / "user_year_features" / f"{h}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"uyf-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET max_temp_directory_size='20GB'")
    bets = f"read_parquet('{X}/bets/{h}/*.parquet')"
    con.execute(f"""CREATE TABLE top AS SELECT artist FROM (SELECT artist, sum(plays) AS p FROM {bets} GROUP BY artist)
                    QUALIFY percent_rank() OVER (ORDER BY p DESC) < 0.01""")
    con.execute(f"""CREATE TABLE ya AS  -- listening by year (matched + unmatched artist plays), mainstream plays
        SELECT u.user, (u.month // 12)::SMALLINT AS year, sum(u.plays) AS artist_plays,
               sum(u.plays) FILTER (WHERE t.artist IS NOT NULL) AS mainstream_plays, count(DISTINCT u.month) AS active_months
        FROM read_parquet('{X}/user_artist_month/{h}/*.parquet') u LEFT JOIN top t USING (artist) GROUP BY ALL""")
    # Listens per year: user_recording has no per-week detail, so use weekly artist plays from the complete
    # (matched) and partial (unmatched) weekly tables; multi-artist listens count once per artist (as in the
    # artist tables), which is what "activity" means elsewhere in the analysis.
    con.execute(f"""CREATE TABLE yl AS
        SELECT user, year, sum(p) FILTER (WHERE NOT unmatched) AS listens_matched, sum(p) FILTER (WHERE unmatched) AS unmatched
        FROM (SELECT user, {YEAR.format(w='week')} AS year, plays AS p, false AS unmatched
              FROM read_parquet('{D}/user_artist_week/{h}/*.parquet')
              UNION ALL
              SELECT user, {YEAR.format(w='week')} AS year, plays AS p, true AS unmatched
              FROM read_parquet('{D}/user_artist_week_partial/{h}/*.parquet'))
        GROUP BY ALL""")
    con.execute(f"""CREATE TABLE yn AS  -- new and committed artists after onboarding, by year of first listen
        SELECT b.user, {YEAR.format(w='b.first_week')} AS year, count(*) AS new_artists,
               count(*) FILTER (WHERE b.w4 IS NOT NULL AND b.w4 - b.first_week < 26) AS committed
        FROM {bets} b JOIN read_parquet('{X}/user_features/{h}.parquet') f USING (user)
        WHERE b.first_week >= f.start_week + 26 GROUP BY ALL""")
    con.execute(f"""COPY (
        SELECT ya.user, ya.year, coalesce(yl.listens_matched, 0) + coalesce(yl.unmatched, 0) AS listens,
               coalesce(yl.unmatched, 0) AS unmatched_listens, ya.active_months,
               coalesce(yn.new_artists, 0) AS new_artists, coalesce(yn.committed, 0) AS committed,
               coalesce(ya.mainstream_plays, 0) AS mainstream_plays, ya.artist_plays
        FROM ya LEFT JOIN yl USING (user, year) LEFT JOIN yn USING (user, year) ORDER BY user, year
    ) TO '{out}' (FORMAT parquet)""")
    print(con.sql(f"SELECT count(*), count(DISTINCT user), min(year), max(year) FROM read_parquet('{out}')").fetchall())


if __name__ == "__main__":
    main()
