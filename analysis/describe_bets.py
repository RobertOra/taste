"""Step 1 descriptives (explore half only): what "bets" look like and how artist popularity moves.

Builds data/derived/market_year/explore.parquet: artist, year, listeners, plays, adopters (users whose
first listen to the artist fell in that year), active_users (users with any listen that year).
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "mlhd"
UA = ROOT / "data" / "derived" / "user_artist" / "explore"
MARKET = ROOT / "data" / "derived" / "market_year" / "explore.parquet"
con = duckdb.connect()
tmp = ROOT / "data" / "_tmp" / "describe"
tmp.mkdir(parents=True, exist_ok=True)
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'")


def show(title, sql):
    print(f"\n## {title}", flush=True)
    print(con.sql(sql).df().to_string(index=False), flush=True)


YEAR = "year(to_timestamp({}::BIGINT * 604800))"
ua = f"read_parquet('{UA}/*.parquet')"

if not MARKET.exists():
    MARKET.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for c in "0123456789abcdef":
        comp = D / "user_artist_week" / "explore" / f"mlhdplus-complete-{c}.parquet"
        part = D / "user_artist_week_partial" / "explore" / f"mlhdplus-partial-{c}.parquet"
        con.execute(f"""CREATE OR REPLACE TEMP TABLE m{c} AS
            SELECT artist, {YEAR.format('week')} AS year, count(DISTINCT user) AS listeners, sum(plays) AS plays
            FROM (SELECT * FROM read_parquet('{comp}') UNION ALL SELECT * FROM read_parquet('{part}'))
            GROUP BY ALL""")
        parts.append(f"SELECT * FROM m{c}")
    con.execute(f"""COPY (
        WITH m AS (SELECT artist, year, sum(listeners)::INT AS listeners, sum(plays)::BIGINT AS plays
                   FROM ({' UNION ALL '.join(parts)}) GROUP BY ALL),
             a AS (SELECT artist, {YEAR.format('first_week')} AS year, count(*)::INT AS adopters FROM {ua} GROUP BY ALL),
             act AS (SELECT {YEAR.format('week')} AS year, count(DISTINCT user)::INT AS active_users
                     FROM read_parquet('{D}/user_artist_week/explore/*.parquet') GROUP BY ALL)
        SELECT m.*, coalesce(a.adopters, 0) AS adopters, act.active_users
        FROM m LEFT JOIN a USING (artist, year) JOIN act USING (year)
        WHERE m.year BETWEEN 2005 AND 2013 ORDER BY artist, year
    ) TO '{MARKET}' (FORMAT parquet, COMPRESSION zstd)""")
mk = f"read_parquet('{MARKET}')"

# Per user: when they joined (first listen) so we can separate onboarding from later discovery.
con.execute(f"""CREATE TEMP TABLE bets AS
    SELECT ua.*, ua.first_week - s.start_week AS weeks_since_start, s.end_week - ua.first_week AS weeks_before_end
    FROM {ua} ua JOIN (SELECT user, min(first_week) AS start_week, max(last_week) AS end_week FROM {ua} GROUP BY user) s
    USING (user)""")

show("User-artist pairs", """SELECT count(*) AS pairs, count(DISTINCT user) AS users, count(DISTINCT artist) AS artists,
    round(avg((plays_matched = 0)::INT), 3) AS share_only_unmatched FROM bets""")

show("Onboarding: new artists per user-week, by weeks since the user's first listen", """
    SELECT CASE WHEN weeks_since_start < 1 THEN '0 (first week)' WHEN weeks_since_start < 4 THEN '1-3'
                WHEN weeks_since_start < 13 THEN '4-12' WHEN weeks_since_start < 26 THEN '13-25'
                WHEN weeks_since_start < 52 THEN '26-51' ELSE '52+' END AS weeks_since_start,
           count(*) AS first_listens, count(DISTINCT user) AS users
    FROM bets GROUP BY 1 ORDER BY min(weeks_since_start)""")

show("Commitment after first listen (first listens >= 26 weeks into a user's history)", """
    SELECT round(avg((plays = 1)::INT), 3) AS share_single_play,
           round(avg((n_weeks = 1)::INT), 3) AS share_one_week_only,
           round(avg((n_weeks >= 4)::INT), 3) AS share_4plus_weeks,
           round(avg((plays >= 10)::INT), 3) AS share_10plus_plays,
           round(avg((plays >= 50)::INT), 3) AS share_50plus_plays,
           quantile_cont(plays, [0.5, 0.9, 0.99]) AS plays_q50_90_99
    FROM bets WHERE weeks_since_start >= 26 AND weeks_before_end >= 52""")

show("Committed new artists per user per year (>=26w in, >=52w before end; committed = active in >=4 weeks)", """
    WITH per AS (SELECT user, count(*) AS n, count(*) FILTER (WHERE n_weeks >= 4) AS committed,
                        (max(first_week) - min(first_week) + 1) / 52.18 AS years
                 FROM bets WHERE weeks_since_start >= 26 AND weeks_before_end >= 52 GROUP BY user HAVING years >= 1)
    SELECT count(*) AS users,
           quantile_cont(n / years, [0.1, 0.5, 0.9]) AS new_artists_per_year_q10_50_90,
           quantile_cont(committed / years, [0.1, 0.5, 0.9]) AS committed_per_year_q10_50_90,
           quantile_cont(committed, [0.1, 0.5, 0.9]) AS committed_total_q10_50_90 FROM per""")

show("Artists by total listeners (explore half, 297k users)", f"""
    WITH a AS (SELECT artist, count(*) AS listeners FROM {ua} GROUP BY artist)
    SELECT count(*) AS artists, count(*) FILTER (WHERE listeners >= 5) AS ge5, count(*) FILTER (WHERE listeners >= 20) AS ge20,
           count(*) FILTER (WHERE listeners >= 100) AS ge100, count(*) FILTER (WHERE listeners >= 1000) AS ge1000,
           count(*) FILTER (WHERE listeners >= 10000) AS ge10000 FROM a""")

show("Concentration: share of all plays going to the top artists", f"""
    WITH a AS (SELECT artist, sum(plays) AS p FROM {mk} GROUP BY artist),
         r AS (SELECT p, percent_rank() OVER (ORDER BY p DESC) AS pr FROM a)
    SELECT round(sum(p) FILTER (WHERE pr < 0.001) / sum(p), 3) AS top_0_1pct, round(sum(p) FILTER (WHERE pr < 0.01) / sum(p), 3) AS top_1pct,
           round(sum(p) FILTER (WHERE pr < 0.1) / sum(p), 3) AS top_10pct FROM r""")

# Penetration = listeners / active users that year; growth is measured on penetration because the
# sample's active population grows ~15x from 2005 to 2012.
show("Breakouts: artists by penetration in year Y and growth to Y+2", f"""
    WITH p AS (SELECT artist, year, listeners, listeners / active_users AS pen FROM {mk}),
         g AS (SELECT a.year, a.artist, a.listeners, a.pen AS pen0, coalesce(b.pen, 0) AS pen2
               FROM p a LEFT JOIN p b ON a.artist = b.artist AND b.year = a.year + 2 WHERE a.year <= 2011)
    SELECT year, count(*) AS artists_present,
           count(*) FILTER (WHERE pen0 < 0.001) AS small_lt_0_1pct,
           count(*) FILTER (WHERE pen0 < 0.001 AND pen2 >= 10 * pen0 AND pen2 >= 0.001) AS small_then_10x,
           count(*) FILTER (WHERE pen0 < 0.001 AND pen2 >= 0.01) AS small_then_ge_1pct,
           count(*) FILTER (WHERE pen0 >= 0.01) AS big_ge_1pct,
           count(*) FILTER (WHERE pen0 >= 0.01 AND pen2 < pen0 / 2) AS big_then_halved
    FROM g GROUP BY year ORDER BY year""")

show("Early bets on breakouts: first listens in year Y to artists small in Y (<0.1%) that reach >=1% by Y+2", f"""
    WITH p AS (SELECT artist, year, listeners / active_users AS pen FROM {mk}),
         br AS (SELECT a.artist, a.year FROM p a JOIN p b ON a.artist = b.artist AND b.year = a.year + 2
                WHERE a.pen < 0.001 AND b.pen >= 0.01),
         fb AS (SELECT user, artist, year(to_timestamp(first_week::BIGINT * 604800)) AS year, n_weeks
                FROM bets WHERE weeks_since_start >= 26)
    SELECT fb.year, count(*) AS early_bets, count(DISTINCT fb.user) AS users_with_one,
           count(*) FILTER (WHERE n_weeks >= 4) AS committed_early_bets
    FROM fb JOIN br USING (artist, year) GROUP BY fb.year ORDER BY fb.year""")

show("Users by number of committed early bets on breakouts (all years)", f"""
    WITH p AS (SELECT artist, year, listeners / active_users AS pen FROM {mk}),
         br AS (SELECT a.artist, a.year FROM p a JOIN p b ON a.artist = b.artist AND b.year = a.year + 2
                WHERE a.pen < 0.001 AND b.pen >= 0.01),
         n AS (SELECT user, count(*) FILTER (WHERE br.artist IS NOT NULL AND n_weeks >= 4) AS k
               FROM (SELECT *, year(to_timestamp(first_week::BIGINT * 604800)) AS year FROM bets
                     WHERE weeks_since_start >= 26) b LEFT JOIN br USING (artist, year) GROUP BY user)
    SELECT k AS committed_early_bets, count(*) AS users FROM n GROUP BY k ORDER BY k LIMIT 15""")
