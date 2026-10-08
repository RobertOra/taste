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
        stayed                         this entrant still listened to the scene in >= 3 of months m+3..m+8
        tr_later_h{H}, kept_later_h{H} other people entering the same scene in (m, m+H], and how many stayed
        tr_prior, kept_prior           other entrants before m (window starts the year before), and how many stayed
        lb_scene                       2026 ListenBrainz listeners summed over the scene's artists
        g, k_comm_h{H}, n_comm_h{H}    the bettor's community that year; members entering the scene in (m, m+H];
                                       members active in both m and m+H (excluding the bettor)
    data/derived/scene_bets/<half>_amap.parquet   year, artist, scene   (artist -> scene, per scene universe)
Entries for "later" and "prior" entrants are computed in the same year's scene universe over months
[Y-1, Y+2], so scene ids stay consistent. Later/prior counts exclude the bettor.

Usage: derive_scene_bets.py <half>
"""

import argparse
import atexit
import signal
import sys
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
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # run cleanup when stopped
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
        con.execute(f"CREATE TABLE IF NOT EXISTS amap_all (year SMALLINT, artist BIGINT, scene SMALLINT)")
        con.execute(f"INSERT INTO amap_all SELECT {y}, artist, s FROM amap")
        m_lo, m_hi = y * 12 - 12, min(y * 12 + 11 + 24, LAST)
        # 2. user x scene x month listening (per archive to bound memory).
        con.execute("CREATE OR REPLACE TABLE usm (user BIGINT, s SMALLINT, month SMALLINT, plays INTEGER)")
        for c in "0123456789abcdef":
            con.execute(f"""INSERT INTO usm SELECT u.user, a.s, u.month, sum(u.plays)::INT
                FROM read_parquet('{X}/user_artist_month/{half}/mlhdplus-{c}.parquet') u JOIN amap a USING (artist)
                WHERE u.month BETWEEN {m_lo} AND {m_hi} GROUP BY ALL""")
        # 3. Scene entries in year y.
        con.execute(f"""CREATE OR REPLACE TABLE allent AS
            WITH sb AS (SELECT b.user, a.s, b.m, b.artist, b.plays_26w FROM abets b JOIN amap a USING (artist)
                        WHERE b.m <= {m_hi}),
                 first AS (SELECT user, s, arg_min(artist, m) AS artist, min(m) AS m,
                                  arg_min(plays_26w, m) AS plays_26w FROM sb GROUP BY user, s)
            SELECT * FROM first WHERE m BETWEEN {y * 12 - 12} AND {m_hi}""")
        con.execute(f"""CREATE OR REPLACE TABLE allent AS
            WITH prior AS (SELECT e.user, e.s, sum(u.plays) FILTER (WHERE u.s = e.s) AS ps, sum(u.plays) AS pt
                           FROM allent e JOIN usm u ON u.user = e.user AND u.month BETWEEN e.m - 12 AND e.m - 1
                           GROUP BY e.user, e.s),
                 st AS (SELECT e.user, e.s, count(DISTINCT u.month) AS months FROM allent e
                        JOIN usm u ON u.user = e.user AND u.s = e.s AND u.month BETWEEN e.m + 3 AND e.m + 8
                        GROUP BY e.user, e.s)
            SELECT e.*, CASE WHEN e.m + 8 <= {LAST} THEN coalesce(st.months, 0) >= 3 END AS stayed
            FROM allent e LEFT JOIN prior p USING (user, s) LEFT JOIN st USING (user, s)
            WHERE coalesce(p.ps, 0) < 0.05 * greatest(coalesce(p.pt, 0), 1)""")
        con.execute(f"CREATE OR REPLACE TABLE entries AS SELECT * FROM allent WHERE m BETWEEN {y * 12} AND {y * 12 + 11}")
        # Other entrants of the same scene: later (by horizon) and prior; the bettor is never among them
        # (one entry per person and scene, at m).
        # Running totals of entrants (and of those who stayed) per scene and month, looked up by window.
        con.execute("""CREATE OR REPLACE TABLE cum AS
            SELECT s, m, sum(n) OVER w AS cn, sum(k) OVER w AS ck FROM (
                SELECT s, m, count(*) FILTER (WHERE stayed IS NOT NULL) AS n, count(*) FILTER (WHERE stayed) AS k
                FROM allent GROUP BY s, m)
            WINDOW w AS (PARTITION BY s ORDER BY m ROWS UNBOUNDED PRECEDING)""")
        con.execute("""CREATE OR REPLACE TABLE entries AS
            WITH q AS (SELECT DISTINCT s, m, (m - 1)::SMALLINT AS mprev FROM entries)
            SELECT e.*, coalesce(c.cn, 0) AS tr_prior, coalesce(c.ck, 0) AS kept_prior
            FROM entries e JOIN q USING (s, m) ASOF LEFT JOIN cum c ON c.s = q.s AND q.mprev >= c.m""")
        home_ok = (X / "community" / f"{half}_home.parquet").exists()
        if home_ok:
            con.execute(f"""CREATE OR REPLACE TABLE home AS SELECT user, g FROM read_parquet('{X}/community/{half}_home.parquet')
                            WHERE year = {y}""")
            # Running totals of entrants per (community, scene, month), communities as of year y.
            con.execute("""CREATE OR REPLACE TABLE cumg AS
                SELECT g, s, m, sum(k) OVER w AS ck FROM (
                    SELECT h.g, x.s, x.m, count(*) AS k FROM allent x JOIN home h USING (user) GROUP BY ALL)
                WINDOW w AS (PARTITION BY g, s ORDER BY m ROWS UNBOUNDED PRECEDING)""")
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
            ok = f"e.m + {h} <= {LAST}"
            con.execute(f"""CREATE OR REPLACE TABLE entries AS
                WITH q AS (SELECT DISTINCT s, m, (m + {h})::SMALLINT AS mh FROM entries),
                     lat AS (SELECT q.s, q.m, coalesce(c1.cn, 0) - coalesce(c0.cn, 0) AS tr, coalesce(c1.ck, 0) - coalesce(c0.ck, 0) AS kp
                             FROM q ASOF LEFT JOIN cum c0 ON c0.s = q.s AND q.m >= c0.m
                                    ASOF LEFT JOIN cum c1 ON c1.s = q.s AND q.mh >= c1.m)
                SELECT e.*, CASE WHEN {ok} THEN lat.tr END AS tr_later_h{h},
                       CASE WHEN {ok} THEN lat.kp END AS kept_later_h{h}
                FROM entries e LEFT JOIN lat USING (s, m)""")
            cols += [f"tr_later_h{h}", f"kept_later_h{h}"]
            if home_ok:
                con.execute(f"""CREATE OR REPLACE TABLE entries AS
                    WITH q AS (SELECT DISTINCT he.g, e.s, e.m, (e.m + {h})::SMALLINT AS mh FROM entries e JOIN home he USING (user)),
                         ek AS (SELECT q.g, q.s, q.m, coalesce(c1.ck, 0) - coalesce(c0.ck, 0) AS k
                                FROM q ASOF LEFT JOIN cumg c0 ON c0.g = q.g AND c0.s = q.s AND q.m >= c0.m
                                       ASOF LEFT JOIN cumg c1 ON c1.g = q.g AND c1.s = q.s AND q.mh >= c1.m),
                         cp AS (SELECT hm.g, a.month AS m, count(*) AS n FROM act a JOIN act b ON b.user = a.user
                                AND b.month = a.month + {h} JOIN home hm ON hm.user = a.user
                                WHERE a.month BETWEEN {y * 12} AND {y * 12 + 11} GROUP BY ALL)
                    SELECT e.*, CASE WHEN {ok} AND he.g IS NOT NULL THEN coalesce(ek.k, 0) END AS k_comm_h{h},
                           CASE WHEN {ok} AND he.g IS NOT NULL THEN cp.n - (f.user IS NOT NULL)::INT END AS n_comm_h{h}
                    FROM entries e LEFT JOIN home he ON he.user = e.user
                    LEFT JOIN ek ON ek.g = he.g AND ek.s = e.s AND ek.m = e.m
                    LEFT JOIN cp ON cp.g = he.g AND cp.m = e.m
                    LEFT JOIN act f ON f.user = e.user AND f.month = e.m + {h}""")
                cols += [f"k_comm_h{h}", f"n_comm_h{h}"]
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
        con.execute(f"""CREATE OR REPLACE TABLE entries AS
            WITH lbs AS (SELECT a.s, sum(coalesce(lb.lb_users, 0)) AS lb_scene FROM amap a
                         LEFT JOIN read_parquet('{X}/lb_artist_popularity.parquet') lb USING (artist) GROUP BY a.s)
            SELECT e.*, lbs.lb_scene FROM entries e LEFT JOIN lbs USING (s)""")
        con.execute(f"""CREATE TABLE part_{y} AS SELECT user, {y}::SMALLINT AS year, s::SMALLINT AS scene, m, artist,
                        plays_26w, {', '.join(cols)}, mom_g, stayed, tr_prior, kept_prior, lb_scene
                        {", home.g" if home_ok else ""} FROM entries {"LEFT JOIN home USING (user)" if home_ok else ""}""")
        n, nu = con.execute(f"SELECT count(*), count(DISTINCT user) FROM part_{y}").fetchone()
        print(f"{y}: {n:,} scene entries by {nu:,} users", flush=True)
        parts.append(f"SELECT * FROM part_{y}")
    con.execute(f"COPY (SELECT * FROM ({' UNION ALL '.join(parts)}) ORDER BY user, m) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY amap_all TO '{out.parent / f'{half}_amap.parquet'}' (FORMAT parquet)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
