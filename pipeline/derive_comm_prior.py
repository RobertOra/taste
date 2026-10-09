"""Prior popularity within the bettor's taste community, for community-leading at the song and scene level
(the artist level already has it in community/<half>_h12.parquet as c_pen). One half at a time.

Songs: members of the bettor's community (as of the bet year) who first played the song in the 24 months up to
and including the bet month, excluding the bettor, divided by community members active in m and m+12.
Scenes: members who listened to any of the scene's artists in the bet month, excluding the bettor, divided by
the same community panel.

    data/derived/comm_prior/<half>_song.parquet    user, recording, m, c_prior
    data/derived/comm_prior/<half>_scene.parquet   user, year, scene, m, c_prior
Usage: derive_comm_prior.py <half>
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
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    half = ap.parse_args().half
    out = X / "comm_prior"
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"commprior-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='30GB'")
    con.execute(f"CREATE TABLE home AS SELECT * FROM read_parquet('{X}/community/{half}_home.parquet')")

    # --- songs ---------------------------------------------------------------------------------------------
    con.execute(f"""CREATE TABLE sb AS SELECT s.user, s.recording, s.m, h.g, s.n_comm_h12 AS n_comm
        FROM read_parquet('{X}/song_bets/{half}.parquet') s JOIN home h ON h.user = s.user AND h.year = s.m // 12""")
    con.execute("CREATE TABLE need AS SELECT DISTINCT (m // 12)::SMALLINT AS year, g, recording FROM sb")
    con.execute("CREATE TABLE cnt (year SMALLINT, g SMALLINT, recording BIGINT, t SMALLINT, k BIGINT)")
    con.execute("CREATE TABLE songs AS SELECT DISTINCT recording FROM need")
    for c in "0123456789abcdef":
        # Keep only bet songs first, then attach the adopter's community for each year (bounded by the window).
        con.execute(f"""INSERT INTO cnt
            WITH ad AS (SELECT ur.user, ur.recording, {MONTH.format(w='ur.first_week')}::SMALLINT AS t
                        FROM read_parquet('{D}/user_recording/{half}/mlhdplus-complete-{c}.parquet') ur
                        SEMI JOIN songs USING (recording))
            SELECT h.year, h.g, ad.recording, ad.t, count(*)
            FROM ad JOIN home h ON h.user = ad.user AND ad.t BETWEEN h.year * 12 - 24 AND h.year * 12 + 11
            SEMI JOIN need n ON n.year = h.year AND n.g = h.g AND n.recording = ad.recording
            GROUP BY ALL""")
        con.execute("CREATE OR REPLACE TABLE cnt AS SELECT year, g, recording, t, sum(k) AS k FROM cnt GROUP BY ALL")
    con.execute("CREATE OR REPLACE TABLE cnt AS SELECT year, g, recording, t, sum(k) AS k FROM cnt GROUP BY ALL")
    # The bettor's own first play is at or before m and inside the window if within 24 months: remove it.
    con.execute(f"""CREATE TABLE own AS SELECT ur.user, ur.recording, {MONTH.format(w='ur.first_week')}::SMALLINT AS t
        FROM read_parquet('{D}/user_recording/{half}/*.parquet') ur SEMI JOIN sb USING (user, recording)""")
    con.execute(f"""COPY (
        WITH p AS (SELECT sb.user, sb.recording, sb.m, sum(c.k) AS k FROM sb
                   JOIN cnt c ON c.year = sb.m // 12 AND c.g = sb.g AND c.recording = sb.recording
                    AND c.t BETWEEN sb.m - 24 AND sb.m GROUP BY ALL)
        SELECT sb.user, sb.recording, sb.m,
               (coalesce(p.k, 0) - (o.t BETWEEN sb.m - 24 AND sb.m)::INT) / greatest(sb.n_comm, 1) AS c_prior
        FROM sb LEFT JOIN p USING (user, recording, m) LEFT JOIN own o USING (user, recording)
        WHERE sb.n_comm IS NOT NULL
    ) TO '{out / f"{half}_song.parquet"}' (FORMAT parquet)""")
    print(con.sql(f"SELECT count(*), avg(c_prior), min(c_prior) FROM read_parquet('{out / f'{half}_song.parquet'}')").fetchall(), flush=True)

    # --- scenes --------------------------------------------------------------------------------------------
    con.execute(f"""CREATE TABLE eb AS SELECT e.user, e.year, e.scene AS s, e.m, h.g, e.n_comm_h12 AS n_comm
        FROM read_parquet('{X}/scene_bets/{half}.parquet') e JOIN home h ON h.user = e.user AND h.year = e.year""")
    con.execute(f"CREATE TABLE amap AS SELECT * FROM read_parquet('{X}/scene_bets/{half}_amap.parquet')")
    con.execute("CREATE TABLE keys AS SELECT DISTINCT year, g, s, m FROM eb")
    con.execute("CREATE TABLE sc (year SMALLINT, g SMALLINT, s SMALLINT, m SMALLINT, l BIGINT)")
    for c in "0123456789abcdef":
        con.execute(f"""INSERT INTO sc
            WITH lm AS (SELECT DISTINCT a.year, h.g, a.scene AS s, u.month AS m, u.user
                        FROM read_parquet('{X}/user_artist_month/{half}/mlhdplus-{c}.parquet') u
                        JOIN amap a ON a.artist = u.artist
                        JOIN home h ON h.user = u.user AND h.year = a.year
                        WHERE u.month BETWEEN a.year * 12 AND a.year * 12 + 11)
            SELECT lm.year, lm.g, lm.s, lm.m, count(*) FROM lm SEMI JOIN keys k USING (year, g, s, m) GROUP BY ALL""")
    con.execute(f"""COPY (
        WITH t AS (SELECT year, g, s, m, sum(l) AS l FROM sc GROUP BY ALL)
        SELECT eb.user, eb.year, eb.s AS scene, eb.m,
               (coalesce(t.l, 0) - 1) / greatest(eb.n_comm, 1) AS c_prior   -- the bettor listened to the scene in m
        FROM eb LEFT JOIN t USING (year, g, s, m) WHERE eb.n_comm IS NOT NULL
    ) TO '{out / f"{half}_scene.parquet"}' (FORMAT parquet)""")
    print(con.sql(f"SELECT count(*), avg(c_prior), min(c_prior) FROM read_parquet('{out / f'{half}_scene.parquet'}')").fetchall(), flush=True)


if __name__ == "__main__":
    main()
