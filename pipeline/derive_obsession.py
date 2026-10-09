"""How hooked a listener was on a pick *at the moment of the bet* (no look-ahead), one half at a time.

Obsession is measured only up to the commitment week (the bet date), so later popularity can't feed back into it:
    plays_to_commit   plays from the first listen through the commitment week (4th distinct listening week)
    weeks_to_commit   weeks from the first listen to the commitment week (fewer = hooked faster)

    data/derived/obsession/<half>_artist.parquet   user, artist, plays_to_commit, weeks_to_commit
    data/derived/obsession/<half>_song.parquet     user, recording, plays_to_commit, weeks_to_commit   (raw sample)
Usage: derive_obsession.py <half>
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    ap.add_argument("--artists-only", action="store_true")
    args = ap.parse_args()
    half = args.half
    out = X / "obsession"
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"obsession-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='20GB'")

    con.execute("CREATE TABLE oa (user BIGINT, artist BIGINT, plays_to_commit INTEGER, weeks_to_commit INTEGER)")
    for c in "0123456789abcdef":
        con.execute(f"""INSERT INTO oa
            WITH b AS (SELECT user, artist, first_week, w4 FROM read_parquet('{X}/bets/{half}/mlhdplus-{c}.parquet')
                       WHERE w4 IS NOT NULL AND w4 - first_week < 26),
                 w AS (SELECT user, artist, week, plays FROM read_parquet('{D}/user_artist_week/{half}/mlhdplus-complete-{c}.parquet')
                       UNION ALL
                       SELECT user, artist, week, plays FROM read_parquet('{D}/user_artist_week_partial/{half}/mlhdplus-partial-{c}.parquet'))
            SELECT b.user, b.artist, sum(w.plays)::INT, (b.w4 - b.first_week)::INT
            FROM b JOIN w ON w.user = b.user AND w.artist = b.artist AND w.week BETWEEN b.first_week AND b.w4
            GROUP BY b.user, b.artist, b.w4, b.first_week""")
    con.execute(f"COPY oa TO '{out / f'{half}_artist.parquet'}' (FORMAT parquet)")
    print("artists", con.execute("SELECT count(*), median(plays_to_commit), median(weeks_to_commit) FROM oa").fetchone(), flush=True)
    if args.artists_only:
        return

    con.execute("CREATE TABLE os (user BIGINT, recording BIGINT, plays_to_commit INTEGER, weeks_to_commit INTEGER)")
    for c in "0123456789abcdef":
        con.execute(f"""INSERT INTO os
            WITH w AS (SELECT user, recording, (ts::BIGINT // 604800)::INT AS week, count(*) AS plays
                       FROM read_parquet('{D}/raw/{half}/mlhdplus-complete-{c}.parquet') GROUP BY ALL),
                 r AS (SELECT *, row_number() OVER (PARTITION BY user, recording ORDER BY week) AS rn,
                              min(week) OVER (PARTITION BY user, recording) AS fw FROM w),
                 c4 AS (SELECT user, recording, min(fw) AS fw, min(week) FILTER (WHERE rn = 4) AS w4 FROM r GROUP BY ALL)
            SELECT r.user, r.recording, sum(r.plays)::INT, (c4.w4 - c4.fw)::INT
            FROM r JOIN c4 USING (user, recording)
            WHERE c4.w4 IS NOT NULL AND c4.w4 - c4.fw < 26 AND r.week <= c4.w4
            GROUP BY r.user, r.recording, c4.w4, c4.fw""")
    con.execute(f"COPY os TO '{out / f'{half}_song.parquet'}' (FORMAT parquet)")
    print("songs", con.execute("SELECT count(*), median(plays_to_commit), median(weeks_to_commit) FROM os").fetchone(), flush=True)


if __name__ == "__main__":
    main()
