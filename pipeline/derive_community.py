"""Inputs for model B (leading your taste community), explore half.

Community: for bets in year Y, a user's home scene = the yearly scene (scenes_yearly, 200 scenes, built from
pre-Y listening) they are most over-represented in during the 12 months before Y (among scenes with >= 5% of
their plays). Members of a community = users with
that home scene in year Y. Approximates "your k most similar users" (communities average ~1,500 users).

For every committed adoption (user u, artist a, commitment month m) with m in year Y:
    k_later  = other members of u's community who commit to a in months (m, m+H]
    n_panel  = members of the community active (any listen) in both m and m+H, excluding u
    c_pen    = members (excluding u) who listened to a in month m, / n_panel   (prior community popularity)
    c_mom    = community momentum: ln(1 + members listening in m) - ln(1 + members listening in m-6), among members
               active in both months, excluding u (is the artist already rising among people like you?)

    data/derived/community/explore_h<H>.parquet   user, artist, m, g (community), k_later, n_panel, c_pen, c_mom
    data/derived/community/explore_home.parquet   user, year, g   (each user's community per year; reused for songs)
Commitment = 4 distinct weeks within 26 weeks of first listen, after the adopter's 26-week onboarding
(the primary bet definition); used for both bettors and later adopters.

Usage: derive_community.py [--horizon 12]
"""

import argparse
import atexit
import signal
import sys
import os
import shutil
import time
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
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # run cleanup when stopped
    con = duckdb.connect()

    def ex(sql, *args):  # run a statement, logging which step and how long it took
        t0 = time.time()
        label = " ".join(sql.split())[:90]
        r = con.execute(sql, *args)
        print(f"  {time.time() - t0:6.1f}s  {label}", flush=True)
        return r

    ex(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='18GB'")
    uam = f"read_parquet('{X}/user_artist_month/explore/*.parquet')"
    ex(f"""CREATE TABLE adopt AS
        SELECT b.user, b.artist, {MONTH.format(w='b.w4')}::SMALLINT AS m
        FROM read_parquet('{X}/bets/explore/*.parquet') b JOIN read_parquet('{X}/user_features/explore.parquet') f USING (user)
        WHERE b.first_week >= f.start_week + 26 AND b.w4 IS NOT NULL AND b.w4 - b.first_week < 26""")
    ex(f"CREATE TABLE act AS SELECT DISTINCT user, month FROM {uam}")
    parts = []
    for y in range(2006, 2013):
        m0, m1 = y * 12, y * 12 + 11
        if m0 > LAST - H:
            break
        # Home scene = the scene the user is most over-represented in (their share / everyone's share),
        # among scenes holding >= 5% of their plays. Plain argmax of plays sends most users to a few big
        # mainstream scenes (everyone plays popular artists), making "communities" about popularity.
        ex(f"""CREATE OR REPLACE TABLE home AS
            WITH up AS (SELECT u.user, s.scene_200 AS scene, sum(u.plays) AS p FROM {uam} u
                        JOIN read_parquet('{X}/scenes_yearly/explore.parquet') s ON s.artist = u.artist AND s.year = {y}
                        WHERE u.month BETWEEN {m0 - 12} AND {m0 - 1} GROUP BY ALL),
                 us AS (SELECT user, scene, p / sum(p) OVER (PARTITION BY user) AS share FROM up),
                 gs AS (SELECT scene, sum(p) / (SELECT sum(p) FROM up) AS gshare FROM up GROUP BY scene)
            SELECT user, arg_max(scene, share / gshare) AS g FROM us JOIN gs USING (scene)
            WHERE share >= 0.05 GROUP BY user""")
        ex(f"CREATE TABLE IF NOT EXISTS home_all AS SELECT user, {y}::SMALLINT AS year, g FROM home LIMIT 0")
        ex(f"INSERT INTO home_all SELECT user, {y}, g FROM home")
        sizes = ex("SELECT quantile_cont(n, [0.1, 0.5, 0.9]), max(n), count(*) FROM (SELECT g, count(*) AS n FROM home GROUP BY g)").fetchone()
        print(f"{y}: community sizes q10/50/90 {[round(x) for x in sizes[0]]}, max {sizes[1]}, communities {sizes[2]}", flush=True)
        # Later community adoptions: cumulative counts per (community, artist) over commitment months.
        ex(f"""CREATE OR REPLACE TABLE cadopt AS
            WITH c AS (SELECT h.g, a.artist, a.m AS t, count(*) AS n FROM adopt a JOIN home h USING (user)
                       WHERE a.m BETWEEN {m0} AND {min(m1 + H, LAST)} GROUP BY ALL)
            SELECT g, artist, t, sum(n) OVER (PARTITION BY g, artist ORDER BY t ROWS UNBOUNDED PRECEDING) AS cn FROM c""")
        # Community panel sizes per bet month.
        ex(f"""CREATE OR REPLACE TABLE cpanel AS
            SELECT h.g, a.month AS m, count(*) AS n FROM act a JOIN act b ON b.user = a.user AND b.month = a.month + {H}
            JOIN home h ON h.user = a.user WHERE a.month BETWEEN {m0} AND {min(m1, LAST - H)} GROUP BY ALL""")
        # Prior community listening to the artist in the bet month (panel members only), for the bets' (g, a, m).
        ex(f"""CREATE OR REPLACE TABLE yb AS
            SELECT a.user, a.artist, a.m, h.g, (a.m + {H})::SMALLINT AS mh FROM adopt a JOIN home h USING (user)
            WHERE a.m BETWEEN {m0} AND {min(m1, LAST - H)}""")
        # Community listening per (community, artist, month), aggregated first (one pass per archive), then
        # looked up for the bets. Joining bets to raw listening directly multiplies rows by every community
        # sharing an artist-month and blows up.
        ex("CREATE OR REPLACE TABLE gl (g SMALLINT, artist BIGINT, month SMALLINT, l_h BIGINT, l_6 BIGINT, l_m6 BIGINT)")
        ex("CREATE OR REPLACE TABLE karts AS SELECT DISTINCT artist FROM yb")
        # Only the (community, artist, month) combinations the bets need: the bet month and 6 months before.
        ex("""CREATE OR REPLACE TABLE need AS SELECT DISTINCT g, artist, m AS month FROM yb
              UNION SELECT DISTINCT g, artist, (m - 6)::SMALLINT FROM yb""")
        for c in "0123456789abcdef":
            ex(f"""INSERT INTO gl
                SELECT h.g, u.artist, u.month,
                       count(*) FILTER (WHERE fh.user IS NOT NULL),   -- listening in month, active H months later
                       count(*) FILTER (WHERE f6.user IS NOT NULL),   -- listening in month, active 6 months later
                       count(*) FILTER (WHERE fm6.user IS NOT NULL)   -- listening in month, active 6 months earlier
                FROM read_parquet('{X}/user_artist_month/explore/mlhdplus-{c}.parquet') u
                SEMI JOIN karts USING (artist)
                JOIN home h ON h.user = u.user
                SEMI JOIN need nd ON nd.g = h.g AND nd.artist = u.artist AND nd.month = u.month
                LEFT JOIN act fh ON fh.user = u.user AND fh.month = u.month + {H}
                LEFT JOIN act f6 ON f6.user = u.user AND f6.month = u.month + 6
                LEFT JOIN act fm6 ON fm6.user = u.user AND fm6.month = u.month - 6
                WHERE u.month BETWEEN {m0 - 6} AND {min(m1, LAST - H)}
                GROUP BY ALL""")
        ex("CREATE OR REPLACE TABLE gl AS SELECT g, artist, month, sum(l_h) AS l_h, sum(l_6) AS l_6, sum(l_m6) AS l_m6 FROM gl GROUP BY ALL")
        ex("""CREATE OR REPLACE TABLE cl AS
            SELECT k.g, k.artist, k.m, coalesce(x.l_h, 0) AS l FROM (SELECT DISTINCT g, artist, m FROM yb) k
            LEFT JOIN gl x ON x.g = k.g AND x.artist = k.artist AND x.month = k.m""")
        # Community momentum: members listening at m (active at m-6) vs at m-6 (active at m), excluding the bettor.
        ex("""CREATE OR REPLACE TABLE cm AS
            SELECT k.g, k.artist, k.m, coalesce(now.l_m6, 0) AS l_now, coalesce(bef.l_6, 0) AS l_before
            FROM (SELECT DISTINCT g, artist, m FROM yb) k
            LEFT JOIN gl now ON now.g = k.g AND now.artist = k.artist AND now.month = k.m
            LEFT JOIN gl bef ON bef.g = k.g AND bef.artist = k.artist AND bef.month = k.m - 6""")
        # The bettor's own listening 6 months before the bet (only the bettors' rows, per archive).
        ex("CREATE OR REPLACE TABLE self6 (user BIGINT, artist BIGINT, m SMALLINT)")
        for c in "0123456789abcdef":
            ex(f"""INSERT INTO self6 SELECT DISTINCT yb.user, yb.artist, yb.m
                FROM read_parquet('{X}/user_artist_month/explore/mlhdplus-{c}.parquet') u
                JOIN yb ON yb.user = u.user AND yb.artist = u.artist AND u.month = yb.m - 6""")
        ex(f"""CREATE OR REPLACE TABLE part_{y} AS
            SELECT yb.user, yb.artist, yb.m, yb.g,
                   coalesce(c1.cn, 0) - coalesce(c0.cn, 0) AS k_later,
                   cp.n - (af.user IS NOT NULL)::INT AS n_panel,
                   (coalesce(cl.l, 0) - (af.user IS NOT NULL)::INT) / greatest(cp.n - (af.user IS NOT NULL)::INT, 1) AS c_pen,
                   ln(greatest(cm.l_now - (a6.user IS NOT NULL)::INT, 0) + 1)
                 - ln(greatest(cm.l_before - (u6.user IS NOT NULL)::INT, 0) + 1) AS c_mom
            FROM yb
            ASOF LEFT JOIN cadopt c0 ON c0.g = yb.g AND c0.artist = yb.artist AND yb.m >= c0.t
            ASOF LEFT JOIN cadopt c1 ON c1.g = yb.g AND c1.artist = yb.artist AND yb.mh >= c1.t
            JOIN cpanel cp ON cp.g = yb.g AND cp.m = yb.m
            LEFT JOIN act af ON af.user = yb.user AND af.month = yb.mh
            LEFT JOIN cl ON cl.g = yb.g AND cl.artist = yb.artist AND cl.m = yb.m
            LEFT JOIN cm ON cm.g = yb.g AND cm.artist = yb.artist AND cm.m = yb.m
            LEFT JOIN act a6 ON a6.user = yb.user AND a6.month = yb.m - 6
            LEFT JOIN self6 u6 ON u6.user = yb.user AND u6.artist = yb.artist AND u6.m = yb.m""")
        n = ex(f"SELECT count(*), avg(k_later), avg(n_panel) FROM part_{y}").fetchone()
        print(f"{y}: {n[0]:,} bets, mean later community adopters {n[1]:.3f}, mean community panel {n[2]:.0f}", flush=True)
        parts.append(f"SELECT * FROM part_{y}")
    ex(f"COPY ({' UNION ALL '.join(parts)}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    ex(f"COPY home_all TO '{out.parent / 'explore_home.parquet'}' (FORMAT parquet)")


if __name__ == "__main__":
    main()
