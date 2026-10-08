"""Scene-level bets and scene popularity (explore or sealed half).

A scene bet = a person getting into a scene that is new to them, dated at the month they committed to
their first artist there (primary artist-bet rule: 4 distinct weeks within 26 weeks, after the
26-week onboarding). "New to them": no earlier committed artist in that scene, and < 5% of their plays
in it during the previous 12 months. Each (person, scene) counts once.

Scene universe: bets committed in year Y use the year-Y scenes (scenes_yearly, 200 scenes, built
from pre-Y listening). Artists first appearing in Y+1 or Y+2 are mapped to the year-Y scene sharing
the most artists with their own later scene, so a scene's growth includes its new artists.

Scene popularity is measured like artist popularity: within the fixed panel of users active in both the
bet month m and m+H, the number listening to any of the scene's artists in m (l0) and m+H (l1).
Leave-one-out is applied here (the bettor is removed from l0/l1 where present).

    data/derived/scene_bets/<half>.parquet
        user, year, scene, m, artist (first artist), plays_26w,
        l0_h{H}, l1_h{H}, n_panel_h{H} for H in 6/12/24 (null where m+H is past 2012-12),
        mom_g   fixed-panel scene growth over the 6 months before the bet (leave-one-out)

Usage: derive_scene_bets.py <half>
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
HS = [6, 12, 24]
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    half = ap.parse_args().half
    out = X / "scene_bets" / f"{half}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"scenebets-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='20GB'")
    sy = f"read_parquet('{X}/scenes_yearly/explore.parquet')"  # scenes are built on explore listening only
    con.execute(f"""CREATE TABLE abets AS
        SELECT b.user, b.artist, {MONTH.format(w='b.w4')}::SMALLINT AS m, b.plays_26w,
               regexp_extract(b.filename, 'mlhdplus-(.)[.]parquet', 1) AS arch
        FROM read_parquet('{X}/bets/{half}/*.parquet', filename=true) b
        JOIN read_parquet('{X}/user_features/{half}.parquet') f USING (user)
        WHERE b.first_week >= f.start_week + 26 AND b.w4 IS NOT NULL AND b.w4 - b.first_week < 26""")
    con.execute(f"CREATE TABLE act AS SELECT DISTINCT user, month FROM read_parquet('{X}/user_artist_month/{half}/*.parquet')")
    con.execute(f"CREATE TABLE panel AS SELECT * FROM read_parquet('{X}/market/{half}/panel.parquet')")
    parts = []
    for y in range(2006, 2012):
        # 1. artist -> year-y scene, with later artists mapped through the most-overlapping scene.
        con.execute(f"CREATE OR REPLACE TABLE base AS SELECT artist, scene_200 AS s FROM {sy} WHERE year = {y}")
        maps = ["SELECT artist, s, 0 AS pri FROM base"]
        for k, y2 in enumerate([y + 1, y + 2], start=1):
            if y2 > 2012:
                continue
            con.execute(f"""CREATE OR REPLACE TABLE m{k} AS
                WITH ov AS (SELECT l.scene_200 AS s2, b.s, sum(l.n_listeners) AS w FROM {sy} l JOIN base b USING (artist)
                            WHERE l.year = {y2} GROUP BY ALL)
                SELECT s2, arg_max(s, w) AS s FROM ov GROUP BY s2""")
            maps.append(f"""SELECT l.artist, m.s, {k} AS pri FROM {sy} l JOIN m{k} m ON m.s2 = l.scene_200
                            WHERE l.year = {y2}""")
        con.execute(f"""CREATE OR REPLACE TABLE amap AS SELECT artist, arg_min(s, pri) AS s
                        FROM ({' UNION ALL '.join(maps)}) GROUP BY artist""")
        m_lo, m_hi = y * 12 - 12, min(y * 12 + 11 + 24, LAST)
        # 2. user x scene x month listening (per archive to bound memory).
        con.execute("CREATE OR REPLACE TABLE usm (user BIGINT, s SMALLINT, month SMALLINT, plays INTEGER)")
        for c in "0123456789abcdef":
            con.execute(f"""INSERT INTO usm SELECT u.user, a.s, u.month, sum(u.plays)::INT
                FROM read_parquet('{X}/user_artist_month/{half}/mlhdplus-{c}.parquet') u JOIN amap a USING (artist)
                WHERE u.month BETWEEN {m_lo} AND {m_hi} GROUP BY ALL""")
        # 3. Scene entries in year y.
        con.execute(f"""CREATE OR REPLACE TABLE entries AS
            WITH sb AS (SELECT b.user, a.s, b.m, b.artist, b.plays_26w FROM abets b JOIN amap a USING (artist)
                        WHERE b.m <= {y * 12 + 11}),
                 first AS (SELECT user, s, arg_min(artist, m) AS artist, min(m) AS m,
                                  arg_min(plays_26w, m) AS plays_26w FROM sb GROUP BY user, s)
            SELECT * FROM first WHERE m BETWEEN {y * 12} AND {y * 12 + 11}""")
        con.execute(f"""CREATE OR REPLACE TABLE entries AS
            WITH prior AS (SELECT e.user, e.s, sum(u.plays) FILTER (WHERE u.s = e.s) AS ps, sum(u.plays) AS pt
                           FROM entries e JOIN usm u ON u.user = e.user AND u.month BETWEEN e.m - 12 AND e.m - 1
                           GROUP BY e.user, e.s)
            SELECT e.* FROM entries e LEFT JOIN prior p USING (user, s)
            WHERE coalesce(p.ps, 0) < 0.05 * greatest(coalesce(p.pt, 0), 1)""")
        # 4. Scene popularity in the fixed panel, with the bettor removed.
        cols = []
        for h in HS:
            con.execute(f"""CREATE OR REPLACE TABLE mk AS
                WITH k AS (SELECT DISTINCT s, m FROM entries WHERE m + {h} <= {LAST}),
                     a0 AS (SELECT k.s, k.m, count(*) AS l0 FROM k JOIN usm u ON u.s = k.s AND u.month = k.m
                            JOIN act f ON f.user = u.user AND f.month = k.m + {h} GROUP BY ALL),
                     a1 AS (SELECT k.s, k.m, count(*) AS l1 FROM k JOIN usm u ON u.s = k.s AND u.month = k.m + {h}
                            JOIN act f ON f.user = u.user AND f.month = k.m GROUP BY ALL)
                SELECT k.s, k.m, coalesce(a0.l0, 0) AS l0, coalesce(a1.l1, 0) AS l1
                FROM k LEFT JOIN a0 USING (s, m) LEFT JOIN a1 USING (s, m)""")
            con.execute(f"""CREATE OR REPLACE TABLE entries AS
                SELECT e.*,
                       CASE WHEN e.m + {h} <= {LAST} THEN mk.l0 - (f.user IS NOT NULL)::INT END AS l0_h{h},
                       CASE WHEN e.m + {h} <= {LAST} THEN mk.l1 - (u.user IS NOT NULL)::INT END AS l1_h{h},
                       CASE WHEN e.m + {h} <= {LAST} THEN p.n_panel - (f.user IS NOT NULL)::INT END AS n_panel_h{h}
                FROM entries e
                LEFT JOIN mk ON mk.s = e.s AND mk.m = e.m
                LEFT JOIN act f ON f.user = e.user AND f.month = e.m + {h}
                LEFT JOIN usm u ON u.user = e.user AND u.s = e.s AND u.month = e.m + {h}
                LEFT JOIN panel p ON p.month = e.m AND p.h = {h}""")
            cols += [f"l0_h{h}", f"l1_h{h}", f"n_panel_h{h}"]
        # 5. Momentum: scene growth over the 6 months before the bet, panel = active at m-6 and m, leave-one-out.
        con.execute(f"""CREATE OR REPLACE TABLE entries AS
            WITH k AS (SELECT DISTINCT s, m FROM entries),
                 g0 AS (SELECT k.s, k.m, count(*) AS l FROM k JOIN usm u ON u.s = k.s AND u.month = k.m - 6
                        JOIN act f ON f.user = u.user AND f.month = k.m GROUP BY ALL),
                 g1 AS (SELECT k.s, k.m, count(*) AS l FROM k JOIN usm u ON u.s = k.s AND u.month = k.m
                        JOIN act f ON f.user = u.user AND f.month = k.m - 6 GROUP BY ALL)
            SELECT e.*,
                   ln(greatest(coalesce(g1.l, 0) - (a6.user IS NOT NULL)::INT, 0) + 1)
                 - ln(greatest(coalesce(g0.l, 0) - (u6.user IS NOT NULL)::INT, 0) + 1) AS mom_g
            FROM entries e LEFT JOIN g0 ON g0.s = e.s AND g0.m = e.m LEFT JOIN g1 ON g1.s = e.s AND g1.m = e.m
            LEFT JOIN act a6 ON a6.user = e.user AND a6.month = e.m - 6
            LEFT JOIN usm u6 ON u6.user = e.user AND u6.s = e.s AND u6.month = e.m - 6""")
        con.execute(f"""CREATE TABLE part_{y} AS SELECT user, {y}::SMALLINT AS year, s::SMALLINT AS scene, m, artist,
                        plays_26w, {', '.join(cols)}, mom_g FROM entries""")
        n, nu = con.execute(f"SELECT count(*), count(DISTINCT user) FROM part_{y}").fetchone()
        print(f"{y}: {n:,} scene entries by {nu:,} users", flush=True)
        parts.append(f"SELECT * FROM part_{y}")
    con.execute(f"COPY (SELECT * FROM ({' UNION ALL '.join(parts)}) ORDER BY user, m) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
