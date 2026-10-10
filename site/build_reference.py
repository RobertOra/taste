"""Reference data for the taste-scoring site (from ListenBrainz, half lb).

    data/site/artist_adopt.parquet   artist, month, adopters   (listeners whose first listen to the artist fell in that month)
    data/site/rec_adopt.parquet      rec, month, adopters      (same for recordings; month of first listen week)
    data/site/artist_map.parquet     artist_name_h, artist     (lowercased trimmed name hash -> artist id, as in pipeline/lb_convert.py)
    data/site/rec_map.parquet        rec_name_h, rec           ("artist\\ttrack" hash -> recording id, as in pipeline/lb_convert_songs.py)
    data/site/month_active.parquet   month, users              (listeners active that month)
Months are LB month indexes (year * 12 + month - 1). One heavy job at a time (DuckDB 5 GB, 6 threads).
Usage: build_reference.py
"""
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
D, X, LB, OUT = ROOT / "data" / "mlhd", ROOT / "data" / "derived", ROOT / "data" / "lb", ROOT / "data" / "site"
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / "site"; tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='60GB'")
    uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
    print("artists...", flush=True)
    con.execute(f"""COPY (SELECT artist, fm AS month, count(*)::INT AS adopters
                          FROM (SELECT user, artist, min(month) AS fm FROM {uam} GROUP BY user, artist) GROUP BY ALL ORDER BY artist, month)
                    TO '{OUT}/artist_adopt.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"COPY (SELECT month, count(DISTINCT user)::INT AS users FROM {uam} GROUP BY month ORDER BY month) TO '{OUT}/month_active.parquet' (FORMAT parquet)")
    print("recordings...", flush=True)
    con.execute(f"""COPY (SELECT recording AS rec, {MONTH.format(w='first_week')}::SMALLINT AS month, count(*)::INT AS adopters
                          FROM read_parquet('{D}/user_recording/lb/*.parquet') GROUP BY ALL ORDER BY rec, month)
                    TO '{OUT}/rec_adopt.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    print("maps...", flush=True)
    con.execute(f"COPY (SELECT artist_name_h, artist FROM read_parquet('{LB}/artist_id_map.parquet')) TO '{OUT}/artist_map.parquet' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"""CREATE TABLE rmap AS SELECT rec_name_h, arg_max(rec_mbid_id, listens) AS mbid FROM
                       (SELECT rec_name_h, rec_mbid_id, sum(listens) AS listens FROM read_parquet('{LB}/rec_mbid/*.parquet') GROUP BY ALL)
                     GROUP BY rec_name_h HAVING max(listens) / sum(listens) >= 0.8""")
    con.execute(f"""COPY (SELECT n.rec_name_h, coalesce(r.mbid, n.rec_name_h) AS rec
                          FROM (SELECT DISTINCT rec_name_h FROM read_parquet('{LB}/user_rec_week/*.parquet')) n LEFT JOIN rmap r USING (rec_name_h))
                    TO '{OUT}/rec_map.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    for f in ("artist_adopt", "rec_adopt", "artist_map", "rec_map", "month_active"):
        n = con.execute(f"SELECT count(*) FROM read_parquet('{OUT}/{f}.parquet')").fetchone()[0]
        print(f"{f}: {n:,} rows, {(OUT / f'{f}.parquet').stat().st_size / 1e6:,.0f} MB", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
