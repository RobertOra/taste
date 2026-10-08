"""Inputs for model B (leading your taste community), explore half.

Community: for bets in year Y, a user's home scene = the yearly scene (scenes_yearly, 200 scenes, built from
pre-Y listening) they are most over-represented in during the 12 months before Y (among scenes with >= 5% of
their plays). Members of a community = users with
that home scene in year Y. Approximates "your k most similar users" (communities average ~1,500 users).

For every committed adoption (user u, artist a, commitment month m) with m in year Y:
    k_later  = other members of u's community who commit to a in months (m, m+H]
    n_panel  = members of the community active (any listen) in both m and m+H, excluding u
    c_pen    = members (excluding u) who listened to a in month m, / n_panel   (prior community popularity)

    data/derived/community/explore_h<H>.parquet   user, artist, m, k_later, n_panel, c_pen
Commitment = 4 distinct weeks within 26 weeks of first listen, after the adopter's 26-week onboarding
(the primary bet definition); used for both bettors and later adopters.

Usage: derive_community.py [--horizon 12]
"""

import argparse
import atexit
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
LAST = 2012 * 12 + 11
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=12)
    H = ap.parse_args().horizon
    out = X / "community" / f"explore_h{H}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"community-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='7GB'; SET threads=8; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='18GB'")
    uam = f"read_parquet('{X}/user_artist_month/explore/*.parquet')"
    con.execute(f"""CREATE TABLE adopt AS
        SELECT b.user, b.artist, {MONTH.format(w='b.w4')}::SMALLINT AS m
        FROM read_parquet('{X}/bets/explore/*.parquet') b JOIN read_parquet('{X}/user_features/explore.parquet') f USING (user)
        WHERE b.first_week >= f.start_week + 26 AND b.w4 IS NOT NULL AND b.w4 - b.first_week < 26""")
    con.execute(f"CREATE TABLE act AS SELECT DISTINCT user, month FROM {uam}")
    parts = []
    for y in range(2006, 2013):
        m0, m1 = y * 12, y * 12 + 11
        if m0 > LAST - H:
            break
        # Home scene = the scene the user is most over-represented in (their share / everyone's share),
        # among scenes holding >= 5% of their plays. Plain argmax of plays sends most users to a few big
        # mainstream scenes (everyone plays popular artists), making "communities" about popularity.
        con.execute(f"""CREATE OR REPLACE TABLE home AS
            WITH up AS (SELECT u.user, s.scene_200 AS scene, sum(u.plays) AS p FROM {uam} u
                        JOIN read_parquet('{X}/scenes_yearly/explore.parquet') s ON s.artist = u.artist AND s.year = {y}
                        WHERE u.month BETWEEN {m0 - 12} AND {m0 - 1} GROUP BY ALL),
                 us AS (SELECT user, scene, p / sum(p) OVER (PARTITION BY user) AS share FROM up),
                 gs AS (SELECT scene, sum(p) / (SELECT sum(p) FROM up) AS gshare FROM up GROUP BY scene)
            SELECT user, arg_max(scene, share / gshare) AS g FROM us JOIN gs USING (scene)
            WHERE share >= 0.05 GROUP BY user""")
        sizes = con.execute("SELECT quantile_cont(n, [0.1, 0.5, 0.9]), max(n), count(*) FROM (SELECT g, count(*) AS n FROM home GROUP BY g)").fetchone()
        print(f"{y}: community sizes q10/50/90 {[round(x) for x in sizes[0]]}, max {sizes[1]}, communities {sizes[2]}", flush=True)
        # Later community adoptions: cumulative counts per (community, artist) over commitment months.
        con.execute(f"""CREATE OR REPLACE TABLE cadopt AS
            WITH c AS (SELECT h.g, a.artist, a.m AS t, count(*) AS n FROM adopt a JOIN home h USING (user)
                       WHERE a.m BETWEEN {m0} AND {min(m1 + H, LAST)} GROUP BY ALL)
            SELECT g, artist, t, sum(n) OVER (PARTITION BY g, artist ORDER BY t ROWS UNBOUNDED PRECEDING) AS cn FROM c""")
        # Community panel sizes per bet month.
        con.execute(f"""CREATE OR REPLACE TABLE cpanel AS
            SELECT h.g, a.month AS m, count(*) AS n FROM act a JOIN act b ON b.user = a.user AND b.month = a.month + {H}
            JOIN home h ON h.user = a.user WHERE a.month BETWEEN {m0} AND {min(m1, LAST - H)} GROUP BY ALL""")
        # Prior community listening to the artist in the bet month (panel members only), for the bets' (g, a, m).
        con.execute(f"""CREATE OR REPLACE TABLE yb AS
            SELECT a.user, a.artist, a.m, h.g, (a.m + {H})::SMALLINT AS mh FROM adopt a JOIN home h USING (user)
            WHERE a.m BETWEEN {m0} AND {min(m1, LAST - H)}""")
        con.execute(f"""CREATE OR REPLACE TABLE cl AS
            WITH keys AS (SELECT DISTINCT g, artist, m FROM yb)
            SELECT k.g, k.artist, k.m, count(*) AS l FROM keys k
            JOIN {uam} u ON u.artist = k.artist AND u.month = k.m
            JOIN home h ON h.user = u.user AND h.g = k.g
            JOIN act f ON f.user = u.user AND f.month = k.m + {H}
            GROUP BY ALL""")
        con.execute(f"""CREATE OR REPLACE TABLE part_{y} AS
            SELECT yb.user, yb.artist, yb.m,
                   coalesce(c1.cn, 0) - coalesce(c0.cn, 0) AS k_later,
                   cp.n - (af.user IS NOT NULL)::INT AS n_panel,
                   (coalesce(cl.l, 0) - (af.user IS NOT NULL)::INT) / greatest(cp.n - (af.user IS NOT NULL)::INT, 1) AS c_pen
            FROM yb
            ASOF LEFT JOIN cadopt c0 ON c0.g = yb.g AND c0.artist = yb.artist AND yb.m >= c0.t
            ASOF LEFT JOIN cadopt c1 ON c1.g = yb.g AND c1.artist = yb.artist AND yb.mh >= c1.t
            JOIN cpanel cp ON cp.g = yb.g AND cp.m = yb.m
            LEFT JOIN act af ON af.user = yb.user AND af.month = yb.mh
            LEFT JOIN cl ON cl.g = yb.g AND cl.artist = yb.artist AND cl.m = yb.m""")
        n = con.execute(f"SELECT count(*), avg(k_later), avg(n_panel) FROM part_{y}").fetchone()
        print(f"{y}: {n[0]:,} bets, mean later community adopters {n[1]:.3f}, mean community panel {n[2]:.0f}", flush=True)
        parts.append(f"SELECT * FROM part_{y}")
    con.execute(f"COPY ({' UNION ALL '.join(parts)}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")


if __name__ == "__main__":
    main()
