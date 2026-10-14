"""Step 1 of the packed site data: per item and month, from 2015 on (ListenBrainz, half lb):
    a  new listeners (first listen that month)
    t  of them past their own first 26 weeks of listening (post-onboarding), as in the study's discernment
    k  of those, kept: songs >= 4 plays over >= 3 weeks; artists: listened in 4 separate weeks within 26 weeks
    data/site/pack_song_rows.parquet    rec, month, a, t, k      (songs with >= 3 new listeners since 2015)
    data/site/pack_artist_rows.parquet  artist, month, a, t, k   (artists with >= 2 new listeners since 2015)
    data/site/pack_song_first.parquet   rec, first_month         (first month anyone played it, any year)
"""
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
# SITE_REF / SITE_OUT / LB_SONGS override the folders (the 2026-10-14 rebuild writes data/site_v2 and site/static/data_v2)
import os
D, X, REF = ROOT / "data" / "mlhd", ROOT / "data" / "derived", Path(os.environ.get("SITE_REF", ROOT / "data" / "site"))
LB_SONGS = os.environ.get("LB_SONGS", "lb")   # user_recording/<LB_SONGS>: lb, or lb_norm (normalized song names)
M0 = 2015 * 12
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
tmp = ROOT / "data" / "_tmp" / "pack_items"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='80GB'")
uf = f"read_parquet('{X}/user_features/lb.parquet')"
print("songs...", flush=True)
con.execute(f"""CREATE TABLE sr AS
    SELECT u.recording AS rec, ({MONTH.format(w='u.first_week')})::SMALLINT AS month, count(*)::INT AS a,
           count(*) FILTER (WHERE u.first_week >= f.start_week + 26)::INT AS t,
           count(*) FILTER (WHERE u.first_week >= f.start_week + 26 AND u.plays >= 4 AND u.span_weeks >= 3)::INT AS k
    FROM read_parquet('{D}/user_recording/{LB_SONGS}/*.parquet') u JOIN {uf} f USING (user)
    WHERE ({MONTH.format(w='u.first_week')}) >= {M0} GROUP BY ALL""")
con.execute(f"""COPY (SELECT s.* FROM sr s SEMI JOIN (SELECT rec FROM sr GROUP BY rec HAVING sum(a) >= 3) e USING (rec) ORDER BY rec, month)
                TO '{REF}/pack_song_rows.parquet' (FORMAT parquet, COMPRESSION zstd)""")
# first month anyone played the song (any year): from rec_adopt for the original ids; for normalized ids, from the song table itself
first_src = (f"SELECT rec, month FROM read_parquet('{REF}/rec_adopt.parquet')" if LB_SONGS == "lb" else
             f"SELECT recording AS rec, ({MONTH.format(w='first_week')})::SMALLINT AS month FROM read_parquet('{D}/user_recording/{LB_SONGS}/*.parquet')")
con.execute(f"""COPY (SELECT rec, min(month)::SMALLINT AS first_month FROM ({first_src})
                      SEMI JOIN (SELECT rec FROM sr GROUP BY rec HAVING sum(a) >= 3) e USING (rec) GROUP BY rec)
                TO '{REF}/pack_song_first.parquet' (FORMAT parquet, COMPRESSION zstd)""")
con.execute("DROP TABLE sr")
print("artists...", flush=True)
con.execute(f"""CREATE TABLE ar AS
    SELECT b.artist, ({MONTH.format(w='b.first_week')})::SMALLINT AS month, count(*)::INT AS a,
           count(*) FILTER (WHERE b.first_week >= f.start_week + 26)::INT AS t,
           count(*) FILTER (WHERE b.first_week >= f.start_week + 26 AND b.w4 IS NOT NULL AND b.w4 - b.first_week < 26)::INT AS k
    FROM read_parquet('{X}/bets/lb/*.parquet') b JOIN {uf} f USING (user)
    WHERE ({MONTH.format(w='b.first_week')}) >= {M0} GROUP BY ALL""")
con.execute(f"""COPY (SELECT r.* FROM ar r SEMI JOIN (SELECT artist FROM ar GROUP BY artist HAVING sum(a) >= 2) e USING (artist) ORDER BY artist, month)
                TO '{REF}/pack_artist_rows.parquet' (FORMAT parquet, COMPRESSION zstd)""")
for f in ("pack_song_rows", "pack_song_first", "pack_artist_rows"):
    print(f, con.execute(f"SELECT count(*) FROM read_parquet('{REF}/{f}.parquet')").fetchone()[0], flush=True)
print("rows with a=1:", con.execute(f"SELECT avg((a = 1)::INT), avg((a = 1 AND t <= 1)::INT) FROM read_parquet('{REF}/pack_song_rows.parquet')").fetchone())
shutil.rmtree(tmp, ignore_errors=True)
