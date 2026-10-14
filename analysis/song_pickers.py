"""New fans of a song, by kind of picker (2026-10-13): the song version of analysis/pickers.py's build(), for the song
versions of "What one new fan is worth", the good- and poor-picker crowd curves, the yearly fan value and the fan-relative chart.

Users split at random into raters and an outcome group (hash(user + 7919) % 2, as pickers.py).
  Track records (raters): song picks up to cutoff C (data/derived/bet_outcomes/A_song_<half>.parquet; songs by one artist
    found the same month count as one pick, mean excess), shrunk sum e / (n + 20), >= 20 picks. Good = top fifth, poor =
    bottom fifth, the rest ordinary.
  New fans: raters' song picks (commitment month m) in year C + 2, counted per song-month: n_good, n_poor, n_ord, n_unrated.
  Outcome (outcome group only): a fixed panel of outcome-group users with any listening in m-3, m and m+12 (from the raw
    listening, data/mlhd/raw/<half>); l_pre, l0, l1 = panel users playing the song in those months.
Cutoffs: analysis/cutoffs.py picker_cuts. Writes data/derived/pickers/song_rate_A_<half>.parquet with pickers.py's columns
(the "artist" column holds the song id, so the artist-level analyses run unchanged; the song's artist is "song_artist").

Usage: song_pickers.py --half explore|sealed|lb
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from cutoffs import picker_cuts  # noqa: E402

X, D = ROOT / "data" / "derived", ROOT / "data" / "mlhd"
MO = "(year(make_timestamp(ts::BIGINT * 1000000)) * 12 + month(make_timestamp(ts::BIGINT * 1000000)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    tmp = ROOT / "data" / "_tmp" / f"song_pickers-{os.getpid()}"; tmp.mkdir(parents=True, exist_ok=True)
    try:
        con = duckdb.connect()
        con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='25GB'")
        con.execute(f"""CREATE TABLE b AS SELECT user, item, artist, m, e FROM read_parquet('{X}/bet_outcomes/A_song_{half}.parquet')
                        WHERE hash(user + 7919) % 2 = 0""")
        con.execute("CREATE TABLE grp AS SELECT user, artist, m, avg(e) AS e FROM b GROUP BY ALL")
        parts = []
        for c in picker_cuts(half):
            parts.append(f"""
                SELECT {c} AS cut, b.item AS artist, any_value(b.artist) AS song_artist, b.m,
                       count(*) FILTER (WHERE t.g = 'good') AS n_good, count(*) FILTER (WHERE t.g = 'poor') AS n_poor,
                       count(*) FILTER (WHERE t.g = 'ord') AS n_ord, count(*) FILTER (WHERE t.g IS NULL) AS n_unrated
                FROM b LEFT JOIN (
                    SELECT user, CASE WHEN q > 0.8 THEN 'good' WHEN q <= 0.2 THEN 'poor' ELSE 'ord' END AS g
                    FROM (SELECT user, percent_rank() OVER (ORDER BY sum(e) / (count(*) + 20)) AS q FROM grp
                          WHERE m // 12 <= {c} GROUP BY user HAVING count(*) >= 20)) t USING (user)
                WHERE b.m // 12 = {c + 2}
                GROUP BY b.item, b.m""")
        con.execute("CREATE TABLE tgt AS " + " UNION ALL ".join(parts))
        print("target song-months", con.execute("SELECT count(*), sum(n_good), sum(n_ord), sum(n_poor), sum(n_unrated) FROM tgt").fetchone(), flush=True)
        con.execute("CREATE TABLE ta AS SELECT DISTINCT artist AS recording, m FROM tgt")
        con.execute("CREATE TABLE tm AS SELECT DISTINCT m FROM tgt")
        lo = (picker_cuts(half)[0] + 2) * 12 - 3
        con.execute("CREATE TABLE act (user BIGINT, month INT)")
        con.execute("CREATE TABLE lis (user BIGINT, recording BIGINT, month INT)")
        for f in sorted((D / "raw" / half).glob("*.parquet")):
            src = f"(SELECT user, recording, {MO}::INT AS month FROM read_parquet('{f}') WHERE hash(user + 7919) % 2 = 1)"
            con.execute(f"INSERT INTO act SELECT DISTINCT user, month FROM {src} WHERE month >= {lo}")
            con.execute(f"""INSERT INTO lis SELECT DISTINCT s.user, s.recording, s.month FROM {src} s
                            JOIN ta ON ta.recording = s.recording AND s.month IN (ta.m - 3, ta.m, ta.m + 12)""")
            print(" ", f.name, flush=True)
        con.execute("""CREATE TABLE panel AS SELECT a0.user, tm.m FROM tm JOIN act a0 ON a0.month = tm.m
                       JOIN act ap ON ap.user = a0.user AND ap.month = tm.m - 3 JOIN act a1 ON a1.user = a0.user AND a1.month = tm.m + 12""")
        print("panel user-months", con.execute("SELECT count(*), count(DISTINCT m) FROM panel").fetchone(), flush=True)
        con.execute("""CREATE TABLE outc AS SELECT ta.recording, ta.m, count(*) FILTER (WHERE l.month = ta.m - 3)::INT AS l_pre,
                          count(*) FILTER (WHERE l.month = ta.m)::INT AS l0, count(*) FILTER (WHERE l.month = ta.m + 12)::INT AS l1
                       FROM ta JOIN lis l ON l.recording = ta.recording AND l.month IN (ta.m - 3, ta.m, ta.m + 12)
                       JOIN panel p ON p.user = l.user AND p.m = ta.m GROUP BY ta.recording, ta.m""")
        out = X / "pickers" / f"song_rate_A_{half}.parquet"
        con.execute(f"""COPY (SELECT t.*, coalesce(o.l_pre, 0) AS l_pre, coalesce(o.l0, 0) AS l0, coalesce(o.l1, 0) AS l1,
                                     coalesce(sc.scene_200, -1) AS scene
                              FROM tgt t LEFT JOIN outc o ON o.recording = t.artist AND o.m = t.m
                              LEFT JOIN read_parquet('{X}/scenes_yearly/{'lb' if half == 'lb' else 'explore'}.parquet') sc
                                ON sc.artist = t.song_artist AND sc.year = t.m // 12) TO '{out}' (FORMAT parquet)""")
        print("wrote", out, con.execute(f"SELECT count(*), avg(l0), median(l0), avg((l0 = 0 AND l1 = 0)::INT) FROM read_parquet('{out}')").fetchone(), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
