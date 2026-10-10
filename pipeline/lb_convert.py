"""Convert the ListenBrainz weekly tables into the MLHD+ layout as a third "half" named lb, so the frozen builders run
unchanged in logic.

Artist ids: a name that maps to one MBID in >= 80% of its MBID-tagged listens gets that MBID's id (last 15 hex digits as
int64, the MLHD+ scheme, which also merges spelling variants); other names keep their 64-bit name hash.
Users are split into 16 chunks by user_id % 16 (the "archive" digit in MLHD+ file names).
    data/mlhd/user_artist_week/lb/mlhdplus-complete-<c>.parquet       user, artist, week, plays
    data/mlhd/user_artist_week_partial/lb/mlhdplus-partial-<c>.parquet (empty: every listen has an artist id)
    data/mlhd/users/lb/mlhdplus-complete-<c>.parquet                  listens linked to an MBID-based artist, first/last ts
    data/mlhd/users_partial/lb/mlhdplus-partial-<c>.parquet           n_rows = listens whose artist name is not linked
    data/lb/artist_id_map.parquet                                      artist_name_h, artist (id used), linked
"""

import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
LB = ROOT / "data" / "lb"
D = ROOT / "data" / "mlhd"


def main():
    for sub in ("user_artist_week", "user_artist_week_partial", "users", "users_partial"):
        p = D / sub / "lb"
        shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True)
    tmp = ROOT / "data" / "_tmp" / "lbconv"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    con.execute(f"""CREATE TABLE best AS
        SELECT artist_name_h, arg_max(artist_mbid_id, listens) AS mbid, max(listens) / sum(listens) AS share
        FROM (SELECT artist_name_h, artist_mbid_id, sum(listens) AS listens FROM read_parquet('{LB}/name_mbid/*.parquet') GROUP BY ALL)
        GROUP BY artist_name_h""")
    con.execute("CREATE TABLE amap AS SELECT artist_name_h, mbid FROM best WHERE share >= 0.8")
    con.execute(f"""COPY (SELECT n.artist_name_h, coalesce(a.mbid, n.artist_name_h) AS artist, a.mbid IS NOT NULL AS linked
                         FROM read_parquet('{LB}/artist_names.parquet') n LEFT JOIN amap a USING (artist_name_h))
                   TO '{LB}/artist_id_map.parquet' (FORMAT parquet)""")
    for i in range(16):
        c = "0123456789abcdef"[i]
        con.execute(f"""CREATE OR REPLACE TABLE w AS
            SELECT w.user::BIGINT AS user, coalesce(a.mbid, w.artist_name_h) AS artist, a.mbid IS NOT NULL AS linked, w.week, w.plays
            FROM read_parquet('{LB}/user_artist_week/*.parquet') w LEFT JOIN amap a USING (artist_name_h)
            WHERE w.user % 16 = {i} AND w.week BETWEEN {int(1104537600 // 604800)} AND {int(1790812800 // 604800)}""")
        con.execute(f"""COPY (SELECT user, artist, week, sum(plays)::INT AS plays FROM w GROUP BY ALL ORDER BY user, artist, week)
                       TO '{D}/user_artist_week/lb/mlhdplus-complete-{c}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        con.execute(f"""COPY (SELECT * FROM w WHERE false) TO '{D}/user_artist_week_partial/lb/mlhdplus-partial-{c}.parquet' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT user, NULL::VARCHAR AS mbid, false AS raw_sample, sum(plays) FILTER (WHERE linked)::BIGINT AS n_listens,
                                    0::BIGINT AS n_bad, min(week)::BIGINT * 604800 AS first_ts, (max(week)::BIGINT + 1) * 604800 - 1 AS last_ts,
                                    0::UINTEGER AS n_recordings, count(DISTINCT artist)::INT AS n_artists
                             FROM w GROUP BY user ORDER BY user)
                       TO '{D}/users/lb/mlhdplus-complete-{c}.parquet' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT user, coalesce(sum(plays) FILTER (WHERE NOT linked), 0)::BIGINT AS n_rows, 0::BIGINT AS n_artist,
                                    0::BIGINT AS n_release_only, 0::BIGINT AS n_nothing, 0::BIGINT AS n_bad,
                                    min(week)::BIGINT * 604800 AS first_ts, (max(week)::BIGINT + 1) * 604800 - 1 AS last_ts
                             FROM w GROUP BY user ORDER BY user)
                       TO '{D}/users_partial/lb/mlhdplus-partial-{c}.parquet' (FORMAT parquet)""")
        n = con.execute("SELECT count(*), count(DISTINCT user), sum(plays) FROM w").fetchone()
        print(f"chunk {c}: {n[0]:,} user-artist-weeks, {n[1]:,} users, {n[2]:,} plays", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
