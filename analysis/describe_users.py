"""Step 1 descriptives (explore half only): time coverage, user activity, unmatched listens."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "mlhd"
H = "explore"
con = duckdb.connect()
tmp = ROOT / "data" / "_tmp" / "describe"
tmp.mkdir(parents=True, exist_ok=True)
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'")


def t(table):
    return f"read_parquet('{D}/{table}/{H}/*.parquet')"


def show(title, sql):
    print(f"\n## {title}")
    print(con.sql(sql).df().to_string(index=False))


YEAR = "year(to_timestamp(week::BIGINT * 604800))"

con.execute(f"""CREATE TEMP TABLE u AS
    SELECT c.user, c.n_listens, coalesce(p.n_rows, 0) AS n_unmatched, coalesce(p.n_artist, 0) AS n_unmatched_artist,
           coalesce(p.n_nothing, 0) AS n_no_id, least(c.first_ts, p.first_ts) AS first_ts,
           greatest(c.last_ts, p.last_ts) AS last_ts, c.n_artists, c.n_recordings
    FROM {t('users')} c LEFT JOIN {t('users_partial')} p USING (user)""")

show("Users", """SELECT count(*) AS users, sum(n_listens + n_unmatched) AS listens,
    round(sum(n_unmatched) / sum(n_listens + n_unmatched), 3) AS unmatched_share,
    round(sum(n_no_id) / sum(n_listens + n_unmatched), 3) AS no_id_share FROM u""")

show("Listens per user (matched + unmatched)", """SELECT
    quantile_cont(n_listens + n_unmatched, [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]) AS q_1_10_25_50_75_90_99,
    round(avg(n_listens + n_unmatched)) AS mean FROM u""")

show("History span per user (years from first to last listen)", """SELECT
    quantile_cont((last_ts - first_ts) / 31557600, [0.1, 0.25, 0.5, 0.75, 0.9]) AS q_10_25_50_75_90,
    round(avg(((last_ts - first_ts) / 31557600 >= 3)::INT), 3) AS share_3y_plus,
    round(avg(((last_ts - first_ts) / 31557600 >= 5)::INT), 3) AS share_5y_plus FROM u""")

show("First and last listen year", """SELECT y, sum(starts) AS users_starting, sum(ends) AS users_ending FROM (
    SELECT year(to_timestamp(first_ts)) AS y, 1 AS starts, 0 AS ends FROM u
    UNION ALL SELECT year(to_timestamp(last_ts)), 0, 1 FROM u) GROUP BY y ORDER BY y""")

show("Artist plays and active users per year (matched + unmatched)", f"""
    WITH w AS (SELECT user, week, plays FROM {t('user_artist_week')}
               UNION ALL SELECT user, week, plays FROM {t('user_artist_week_partial')})
    SELECT {YEAR} AS year, sum(plays) AS artist_plays, count(DISTINCT user) AS active_users
    FROM w GROUP BY year ORDER BY year""")

show("Unmatched share per user", """SELECT
    quantile_cont(n_unmatched / (n_listens + n_unmatched), [0.1, 0.25, 0.5, 0.75, 0.9]) AS unmatched_q_10_25_50_75_90,
    quantile_cont(n_no_id / (n_listens + n_unmatched), [0.1, 0.25, 0.5, 0.75, 0.9]) AS no_id_q_10_25_50_75_90
    FROM u WHERE n_listens + n_unmatched > 0""")

show("Distinct artists / recordings per user", """SELECT
    quantile_cont(n_artists, [0.1, 0.5, 0.9]) AS artists_q_10_50_90,
    quantile_cont(n_recordings, [0.1, 0.5, 0.9]) AS recordings_q_10_50_90 FROM u""")
