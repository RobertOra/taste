"""Per-user "impostor" / control features that don't depend on a taste-model variant (one half at a time).

    data/derived/user_features/<half>.parquet
        user, start_week, end_week, history_years, join_year, active_months,
        listens, listens_per_active_month, unmatched_share, no_id_share,
        artists_tried, new_artists_per_year, committed_per_year   (after 26-week onboarding; committed = 4 distinct
                                                                     weeks within 26 weeks of first listen)
        mainstream_share   share of plays going to the top 1% of artists by plays in this half
Variant-dependent controls (obscurity of bets, scene mix) are computed with the scores.
"""

import argparse
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    h = ap.parse_args().half
    D, X = ROOT / "data" / "mlhd", ROOT / "data" / "derived"
    out = X / "user_features" / f"{h}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"features-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='7GB'; SET threads=8; SET temp_directory='{tmp}'")
    bets = f"read_parquet('{X}/bets/{h}/*.parquet')"
    uam = f"read_parquet('{X}/user_artist_month/{h}/*.parquet')"
    con.execute(f"""COPY (
        WITH span AS (SELECT user, min(first_week) AS start_week, max(last_week) AS end_week,
                             count(*) AS artists_tried, sum(plays) AS artist_plays FROM {bets} GROUP BY user),
             post AS (SELECT b.user,
                             count(*) AS n_new,
                             count(*) FILTER (WHERE b.w4 IS NOT NULL AND b.w4 - b.first_week < 26) AS n_committed
                      FROM {bets} b JOIN span s USING (user) WHERE b.first_week >= s.start_week + 26 GROUP BY b.user),
             act AS (SELECT user, count(DISTINCT month) AS active_months FROM {uam} GROUP BY user),
             top AS (SELECT artist FROM (SELECT artist, sum(plays) AS p FROM {bets} GROUP BY artist)
                     QUALIFY percent_rank() OVER (ORDER BY p DESC) < 0.01),
             ms AS (SELECT b.user, sum(b.plays) FILTER (WHERE t.artist IS NOT NULL) / sum(b.plays) AS mainstream_share
                    FROM {bets} b LEFT JOIN top t USING (artist) GROUP BY b.user),
             q AS (SELECT c.user, c.n_listens + coalesce(p.n_rows, 0) AS listens,
                          coalesce(p.n_rows, 0) / (c.n_listens + coalesce(p.n_rows, 0)) AS unmatched_share,
                          coalesce(p.n_nothing, 0) / (c.n_listens + coalesce(p.n_rows, 0)) AS no_id_share
                   FROM read_parquet('{D}/users/{h}/*.parquet') c
                   LEFT JOIN read_parquet('{D}/users_partial/{h}/*.parquet') p USING (user))
        SELECT s.user, s.start_week, s.end_week, (s.end_week - s.start_week + 1) / 52.18 AS history_years,
               year(make_timestamp(s.start_week::BIGINT * 604800000000)) AS join_year, a.active_months,
               q.listens, q.listens / a.active_months AS listens_per_active_month, q.unmatched_share, q.no_id_share,
               s.artists_tried,
               coalesce(p.n_new, 0) / greatest((s.end_week - s.start_week + 1 - 26) / 52.18, 0.25) AS new_artists_per_year,
               coalesce(p.n_committed, 0) / greatest((s.end_week - s.start_week + 1 - 26) / 52.18, 0.25) AS committed_per_year,
               m.mainstream_share
        FROM span s JOIN act a USING (user) JOIN q USING (user) JOIN ms m USING (user) LEFT JOIN post p USING (user)
        ORDER BY s.user
    ) TO '{out}' (FORMAT parquet)""")
    print(con.sql(f"SELECT count(*) AS users, avg(history_years), median(new_artists_per_year), "
                  f"median(committed_per_year), median(mainstream_share) FROM read_parquet('{out}')").df().to_string())
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
