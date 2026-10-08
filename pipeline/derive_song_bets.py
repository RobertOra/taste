"""Song-level bets and the song-level outcomes / controls (one half at a time).

Bettors: raw-sample users only (1/8 of users), because dating a song commitment needs weekly listening,
which is stored only for them. Everything about the songs themselves (popularity, other people's trials,
song age) comes from all users in the half (user_recording: first week, span, plays per user and song).

Bet: a song the bettor listened to in >= 4 distinct weeks, the 4th within 26 weeks of the first listen,
first listen after the user's 26-week onboarding. Dated at the month of the 4th week (commitment).

Song popularity ("price") at month m, within the fixed panel of users active in both m and m+H:
    l0 = panel users whose first listen to the song fell in [m-5, m]     (recent adoption)
    l1 = panel users whose first listen fell in [m+H-5, m+H]
with the bettor removed (leave-one-out). Prescience growth = ln(l1+1) - ln(l0+1).
Discernment: other users' post-onboarding first listens in (m, m+H] and how many kept playing
(>= 4 plays over >= 3 weeks); prior conversion from trials up to m.
Song age: months since anyone in the half first played it (censored at 2005-01).

    data/derived/song_bets/<half>.parquet
        user, recording, artist, m, plays_26w, song_first_m,
        l0_h{H}, l1_h{H}, n_panel_h{H}, tr_later_h{H}, kept_later_h{H}   (H = 6, 12, 24)
        tr_prior, kept_prior
Usage: derive_song_bets.py <half>
"""

import argparse
import atexit
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "mlhd"
X = ROOT / "data" / "derived"
LAST = 2012 * 12 + 11
HS = [6, 12, 24]
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    half = ap.parse_args().half
    out = X / "song_bets" / f"{half}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"songbets-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                "SET max_temp_directory_size='25GB'")
    feats = f"read_parquet('{X}/user_features/{half}.parquet')"

    # 1. Bets from the raw sample: weekly listening per (user, song), commitment week, early plays.
    con.execute(f"""CREATE TABLE sb AS
        WITH w AS (SELECT user, recording, artists[1] AS artist, (ts::BIGINT // 604800)::INT AS week, count(*) AS plays
                   FROM read_parquet('{D}/raw/{half}/*.parquet') GROUP BY ALL),
             w2 AS (SELECT user, recording, week, sum(plays) AS plays, any_value(artist) AS artist FROM w GROUP BY ALL),
             r AS (SELECT *, row_number() OVER (PARTITION BY user, recording ORDER BY week) AS rn,
                          min(week) OVER (PARTITION BY user, recording) AS fw FROM w2),
             agg AS (SELECT user, recording, any_value(artist) AS artist, min(week) AS first_week,
                            min(week) FILTER (WHERE rn = 4) AS w4,
                            sum(plays) FILTER (WHERE week < fw + 26)::INT AS plays_26w
                     FROM r GROUP BY user, recording)
        SELECT a.user, a.recording, a.artist, {MONTH.format(w='a.w4')}::SMALLINT AS m, a.plays_26w
        FROM agg a JOIN {feats} f USING (user)
        WHERE a.first_week >= f.start_week + 26 AND a.w4 IS NOT NULL AND a.w4 - a.first_week < 26
          AND {MONTH.format(w='a.w4')} BETWEEN {2005 * 12} AND {LAST - 6}""")
    n_bets = con.execute("SELECT count(*), count(DISTINCT user), count(DISTINCT recording) FROM sb").fetchone()
    print(f"song bets: {n_bets[0]:,} by {n_bets[1]:,} users on {n_bets[2]:,} songs", flush=True)

    # 2. Adoption counts for those songs from everyone in the half, one archive at a time (users never span
    #    archives, so counts add up). An adoption = a user's first listen to the song (month t).
    con.execute("CREATE TABLE songs AS SELECT DISTINCT recording FROM sb")
    con.execute("CREATE TABLE keys AS SELECT DISTINCT recording, m FROM sb")
    con.execute(f"CREATE TABLE act AS SELECT DISTINCT user, month FROM read_parquet('{X}/user_artist_month/{half}/*.parquet')")
    con.execute(f"CREATE TABLE panel AS SELECT * FROM read_parquet('{X}/market/{half}/panel.parquet')")
    con.execute("""CREATE TABLE acc (h SMALLINT, recording BIGINT, m SMALLINT, l0 BIGINT, l1 BIGINT, tr BIGINT, kp BIGINT)""")
    con.execute("CREATE TABLE accp (recording BIGINT, m SMALLINT, tr_prior BIGINT, kept_prior BIGINT)")
    con.execute("CREATE TABLE accf (recording BIGINT, song_first_m SMALLINT)")
    con.execute("CREATE TABLE own (user BIGINT, recording BIGINT, t SMALLINT, kept BOOLEAN, post BOOLEAN)")
    for c in "0123456789abcdef":
        con.execute(f"""CREATE OR REPLACE TABLE ad AS
            SELECT ur.user, ur.recording, {MONTH.format(w='ur.first_week')}::SMALLINT AS t,
                   (ur.plays >= 4 AND ur.span_weeks >= 3) AS kept,
                   ur.first_week >= f.start_week + 26 AS post
            FROM read_parquet('{D}/user_recording/{half}/mlhdplus-complete-{c}.parquet') ur
            SEMI JOIN songs USING (recording) JOIN {feats} f USING (user)""")
        con.execute("INSERT INTO own SELECT a.* FROM ad a SEMI JOIN sb USING (user, recording)")
        con.execute("INSERT INTO accf SELECT recording, min(t) FROM ad GROUP BY recording")
        con.execute("""INSERT INTO accp SELECT k.recording, k.m, count(*) FILTER (WHERE ad.post),
                       count(*) FILTER (WHERE ad.post AND ad.kept)
                       FROM keys k JOIN ad ON ad.recording = k.recording AND ad.t <= k.m GROUP BY ALL""")
        for h in HS:
            con.execute(f"""INSERT INTO acc
                WITH k AS (SELECT * FROM keys WHERE m + {h} <= {LAST}),
                     a0 AS (SELECT k.recording, k.m, count(*) AS l0 FROM k JOIN ad ON ad.recording = k.recording
                            AND ad.t BETWEEN k.m - 5 AND k.m
                            JOIN act x ON x.user = ad.user AND x.month = k.m
                            JOIN act y ON y.user = ad.user AND y.month = k.m + {h} GROUP BY ALL),
                     a1 AS (SELECT k.recording, k.m, count(*) AS l1 FROM k JOIN ad ON ad.recording = k.recording
                            AND ad.t BETWEEN k.m + {h} - 5 AND k.m + {h}
                            JOIN act x ON x.user = ad.user AND x.month = k.m
                            JOIN act y ON y.user = ad.user AND y.month = k.m + {h} GROUP BY ALL),
                     tl AS (SELECT k.recording, k.m, count(*) AS tr, count(*) FILTER (WHERE ad.kept) AS kp
                            FROM k JOIN ad ON ad.recording = k.recording AND ad.t > k.m AND ad.t <= k.m + {h}
                            WHERE ad.post GROUP BY ALL),
                     u AS (SELECT recording, m FROM a0 UNION SELECT recording, m FROM a1 UNION SELECT recording, m FROM tl)
                SELECT {h}, u.recording, u.m, coalesce(a0.l0, 0), coalesce(a1.l1, 0), coalesce(tl.tr, 0), coalesce(tl.kp, 0)
                FROM u LEFT JOIN a0 USING (recording, m) LEFT JOIN a1 USING (recording, m) LEFT JOIN tl USING (recording, m)""")
        print(f"archive {c} done", flush=True)
    con.execute("CREATE TABLE tot AS SELECT h, recording, m, sum(l0) AS l0, sum(l1) AS l1, sum(tr) AS tr, sum(kp) AS kp FROM acc GROUP BY ALL")
    con.execute("CREATE TABLE totp AS SELECT recording, m, sum(tr_prior) AS tr_prior, sum(kept_prior) AS kept_prior FROM accp GROUP BY ALL")
    con.execute("CREATE TABLE firstm AS SELECT recording, min(song_first_m) AS song_first_m FROM accf GROUP BY recording")

    # 3. One row per bet; the bettor is removed from every count they are part of.
    sel, joins = [], []
    for h in HS:
        joins.append(f"""LEFT JOIN tot t{h} ON t{h}.h = {h} AND t{h}.recording = sb.recording AND t{h}.m = sb.m
        LEFT JOIN panel p{h} ON p{h}.month = sb.m AND p{h}.h = {h}
        LEFT JOIN act y{h} ON y{h}.user = sb.user AND y{h}.month = sb.m + {h}""")
        ok = f"sb.m + {h} <= {LAST}"
        sel.append(f"""CASE WHEN {ok} THEN coalesce(t{h}.l0, 0) - (own.t >= sb.m - 5 AND y{h}.user IS NOT NULL)::INT END AS l0_h{h},
               CASE WHEN {ok} THEN coalesce(t{h}.l1, 0) END AS l1_h{h},
               CASE WHEN {ok} THEN p{h}.n_panel - (y{h}.user IS NOT NULL)::INT END AS n_panel_h{h},
               CASE WHEN {ok} THEN coalesce(t{h}.tr, 0) END AS tr_later_h{h},
               CASE WHEN {ok} THEN coalesce(t{h}.kp, 0) END AS kept_later_h{h}""")
    con.execute(f"""COPY (
        SELECT sb.user, sb.recording, sb.artist, sb.m, sb.plays_26w, fm.song_first_m,
               {', '.join(sel)},
               coalesce(tp.tr_prior, 0) - coalesce(own.post, false)::INT AS tr_prior,
               coalesce(tp.kept_prior, 0) - coalesce(own.post AND own.kept, false)::INT AS kept_prior
        FROM sb
        LEFT JOIN own ON own.user = sb.user AND own.recording = sb.recording
        {' '.join(joins)}
        LEFT JOIN firstm fm ON fm.recording = sb.recording
        LEFT JOIN totp tp ON tp.recording = sb.recording AND tp.m = sb.m
        ORDER BY sb.user, sb.m
    ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    bad = con.execute(f"SELECT count(*) FROM read_parquet('{out}') WHERE l0_h12 < 0 OR tr_prior < 0 OR kept_prior < 0").fetchone()[0]
    print(f"rows with negative leave-one-out counts: {bad}", flush=True)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
