"""Taste models A / C / D on the explore half: score users and run tests 1-3 for one variant.

Same bets, popularity bins, controls and tests as analysis/prescience.py; only the per-bet outcome differs:
  A     prescience: fixed-panel listener growth over H months (leave-one-out)
  C_lb  durability: ln(1 + ListenBrainz listeners in 2026) of the artist (artists absent on LB = 0)
  B     community-leading: ln((k + 0.5) / n) where k = other members of your taste community (home scene in the
        previous 12 months) who commit to the artist in the H months after you, n = community members active
        throughout (pipeline/derive_community.py); always adjusted (additively) for the artist's prior popularity
        within the community (decile of c_pen) and for the community's overall adoption rate that month
        (month x community), so a community that adopts a lot doesn't make its members look prescient
  D     discernment: conversion of *other* users' trials of the artist in the H months after the bet
        (share of post-onboarding first listens reaching commitment within 26 weeks), beta-smoothed
        (C + 2 * p0) / (N + 2) with p0 = overall conversion rate

(Original model A description follows.)

Bet: committed adoption after onboarding, dated at commitment (or first listen for the contrast).
Return: r = ln(l1' + s) - ln(l0' + s), where l0'/l1' are fixed-panel listeners of the artist in the bet
month m and in m+H, leave-one-out (the bettor's own presence removed).
Excess: e = r - mean r of all other bets in the same month x popularity bin [x scene].
User score: mean e (also empirical-Bayes shrunk).

Tests: (1) luck baseline — shuffle e within benchmark cells; (2) persistence — early vs late halves,
disjoint periods with non-overlapping return windows, and random split-halves; (3) impostor regression.

Writes analysis/out/prescience/<variant>/{summary.json, users.parquet} and bets to data/derived/scores/.
"""

import argparse
import atexit
import signal
import sys
import json
import os
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
LAST = 2012 * 12 + 11
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 " \
        "+ month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
RULES = {"w2": "w2", "w4": "w4", "w8": "w8", "p10": "w_p10", "all": "first_week"}


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["A", "B", "C_lb", "D"], default="A")
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], default="explore",
                    help="which half's bets and tables to use (MLHD+ scenes are built from explore listening; lb uses its own)")
    ap.add_argument("--unit", choices=["artist", "song", "scene"], default="artist",
                    help="artist: bets from data/derived/bets; song: raw-sample users' song bets (song_bets); "
                         "scene: scene entries (scene_bets). Song/scene bets use the primary bet rule only.")
    ap.add_argument("--onboarding", type=int, default=26, help="weeks")
    ap.add_argument("--rule", choices=RULES, default="w4")
    ap.add_argument("--window", type=int, default=26, help="weeks allowed to reach commitment")
    ap.add_argument("--date", choices=["commit", "first"], default="commit")
    ap.add_argument("--horizon", type=int, default=12, help="months")
    ap.add_argument("--smooth", type=float, default=1.0)
    ap.add_argument("--bins", type=int, default=20)
    ap.add_argument("--scene", choices=["none", "yearly50", "yearly200", "yearly1000", "allyears200", "genre200"],
                    default="none")
    ap.add_argument("--age", action="store_true", help="benchmark also by artist age (months since first listened)")
    ap.add_argument("--momentum", type=int, default=0, help="benchmark also by N quantiles of prior 6-month growth")
    ap.add_argument("--country", action="store_true", help="benchmark also by artist country (MusicBrainz)")
    ap.add_argument("--release", action="store_true",
                    help="benchmark also by release timing: did the artist release an album/EP/single in the 3 months "
                         "before the bet, the 3 months after, both, neither, or is there no release data")
    ap.add_argument("--adjust", choices=["cells", "additive"], default="cells",
                    help="cells: one benchmark cell per month x bin x scene x age x momentum; additive: month x bin cell "
                         "plus separate leave-one-out month x scene / month x age / month x momentum adjustments (backfitted)")
    ap.add_argument("--metric", choices=["log", "rank", "rawcap", "hit"], default="log")
    ap.add_argument("--weight", type=float, default=0.0, help="alpha in plays_26w^alpha")
    ap.add_argument("--user-sample", type=int, default=1, help="keep users with hash(user) %% N = 0 (for huge variants)")
    ap.add_argument("--min-bets", type=int, default=20)
    ap.add_argument("--perms", type=int, default=20)
    ap.add_argument("--name", default=None)
    ap.add_argument("--mem", default="5GB", help="DuckDB memory limit")
    ap.add_argument("--bets-out", default=None, help="also write per-bet excess outcomes (before any song collapsing) here")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--cand", default=None,
                    help="write per-user/year aggregates for analysis/evaluate.py to analysis/out/cand/<cand>/ and stop")
    return ap.parse_args()


def variant_name(a):
    return a.name or (f"on{a.onboarding}_{a.rule}_win{a.window}_{a.date}_h{a.horizon}_s{a.smooth:g}_b{a.bins}"
                      f"_{a.scene}{'_age' if a.age else ''}{f'_mom{a.momentum}' if a.momentum else ''}{'_ctry' if a.country else ''}{'_rel' if a.release else ''}_{a.adjust}_{a.metric}_w{a.weight:g}")


def main():
    a = parse()
    global LAST
    LAST = 2026 * 12 + 8 if a.half == "lb" else 2012 * 12 + 11  # see pipeline/periods.py
    if a.half == "lb" and a.model == "C_lb":
        raise SystemExit("durability (C_lb) is circular on ListenBrainz data; not run for half=lb")
    name = variant_name(a)
    out = ROOT / "analysis" / "out" / f"model_{a.model}" / name
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"models-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    atexit.register(shutil.rmtree, tmp, True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # run cleanup when stopped  # also on failure
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{a.mem}'; SET threads={a.threads}; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='18GB'")
    H = a.horizon
    datecol = "first_week" if a.date == "first" or a.rule == "all" else RULES[a.rule]
    commit = "TRUE" if a.rule == "all" else f"b.{RULES[a.rule]} IS NOT NULL AND b.{RULES[a.rule]} - b.first_week < {a.window}"

    con.execute(f"""CREATE TABLE act AS SELECT DISTINCT user, month FROM read_parquet('{X}/user_artist_month/{a.half}/*.parquet')""")
    if a.unit == "artist":
        con.execute(f"""CREATE TABLE b AS
            SELECT b.user, b.artist, {MONTH.format(w='b.' + datecol)}::SMALLINT AS m, b.plays_26w,
                   regexp_extract(b.filename, 'mlhdplus-(.)[.]parquet', 1) AS arch
            FROM read_parquet('{X}/bets/{a.half}/*.parquet', filename=true) b
            JOIN read_parquet('{X}/user_features/{a.half}.parquet') f USING (user)
            WHERE b.first_week >= f.start_week + {a.onboarding} AND {commit} AND hash(b.user) % {a.user_sample} = 0
              AND {MONTH.format(w='b.' + datecol)} BETWEEN {2005 * 12} AND {LAST - H}""")
        # Joins against the 1.8B-row monthly table are done per archive (users never span archives) to bound memory.
        parts = []
        for c in "0123456789abcdef":
            con.execute(f"""CREATE TABLE r_{c} AS
                SELECT b.*, b.artist AS item, coalesce(mk.l0, 0) - (a1.user IS NOT NULL)::INT AS l0,
                       coalesce(mk.l1, 0) - (u1.user IS NOT NULL)::INT AS l1, p.n_panel
                FROM (SELECT * FROM b WHERE arch = '{c}') b
                LEFT JOIN read_parquet('{X}/market/{a.half}/listeners_h{H}.parquet') mk ON mk.artist = b.artist AND mk.month = b.m
                JOIN read_parquet('{X}/market/{a.half}/panel.parquet') p ON p.month = b.m AND p.h = {H}
                LEFT JOIN act a1 ON a1.user = b.user AND a1.month = b.m + {H}
                LEFT JOIN read_parquet('{X}/user_artist_month/{a.half}/mlhdplus-{c}.parquet') u1
                       ON u1.user = b.user AND u1.artist = b.artist AND u1.month = b.m + {H}""")
            parts.append(f"SELECT * FROM r_{c}")
        con.execute(f"CREATE TABLE r AS {' UNION ALL '.join(parts)}")
        for c in "0123456789abcdef":
            con.execute(f"DROP TABLE r_{c}")
        con.execute("DROP TABLE b")
    elif a.unit == "song":
        con.execute(f"""CREATE TABLE r AS
            SELECT user, recording AS item, artist, m, plays_26w, song_first_m, l0_h{H} AS l0, l1_h{H} AS l1,
                   n_panel_h{H} AS n_panel, tr_later_h{H} AS tr_later, kept_later_h{H} AS kept_later, tr_prior, kept_prior,
                   g, k_comm_h{H} AS k_comm, n_comm_h{H} AS n_comm
            FROM read_parquet('{X}/song_bets/{a.half}.parquet')
            WHERE l0_h{H} IS NOT NULL AND hash(user) % {a.user_sample} = 0""")
    else:
        con.execute(f"""CREATE TABLE r AS
            SELECT user, scene::BIGINT * 10000 + year AS item, artist, m, plays_26w, l0_h{H} AS l0, l1_h{H} AS l1,
                   n_panel_h{H} AS n_panel, mom_g, tr_later_h{H} AS tr_later, kept_later_h{H} AS kept_later,
                   tr_prior, kept_prior, lb_scene, g, k_comm_h{H} AS k_comm, n_comm_h{H} AS n_comm
            FROM read_parquet('{X}/scene_bets/{a.half}.parquet')
            WHERE l0_h{H} IS NOT NULL AND hash(user) % {a.user_sample} = 0""")
    bad = con.execute("SELECT count(*) FROM r WHERE l0 < 0 OR l1 < 0").fetchone()[0]
    assert bad == 0, f"{bad} bets with negative leave-one-out counts"

    if a.scene == "none" or a.unit == "scene":  # a scene bet is already about the scene itself
        scene_sql, scene_join = "0", ""
    elif a.scene.startswith("yearly"):
        k = a.scene.removeprefix("yearly")
        scene_sql = f"coalesce(sc.scene_{k}, -1)"
        scene_join = (f"LEFT JOIN read_parquet('{X}/scenes_yearly/{'lb' if a.half == 'lb' else 'explore'}.parquet') sc "
                      f"ON sc.artist = r.artist AND sc.year = r.m // 12")
    elif a.scene == "allyears200":
        scene_sql, scene_join = "sc.scene_200", f"LEFT JOIN read_parquet('{X}/scenes/explore.parquet') sc USING (artist)"
    else:
        scene_sql, scene_join = "sc.scene_200", f"JOIN read_parquet('{X}/scenes_genre/all.parquet') sc USING (artist)"

    # Artist age: months since the artist first appears in this half's listening (censored at 2005-01).
    con.execute(f"""CREATE TABLE first_seen AS SELECT artist, min(month) AS fm
                    FROM read_parquet('{X}/user_artist_month/{a.half}/*.parquet') GROUP BY artist""")
    age_sql = ("CASE WHEN fs.fm <= 2005 * 12 THEN 9 WHEN r.m - fs.fm < 3 THEN 0 WHEN r.m - fs.fm < 6 THEN 1 "
               "WHEN r.m - fs.fm < 12 THEN 2 WHEN r.m - fs.fm < 24 THEN 3 ELSE 4 END") if a.age else "0"
    if a.age and a.unit == "song":  # song age instead of artist age; fine early bins (songs gain most listeners
        # in their first months, so following new releases must not count as foresight)
        age_sql = ("CASE WHEN r.song_first_m <= 2005 * 12 THEN 9 WHEN r.m - r.song_first_m <= 2 THEN r.m - r.song_first_m "
                   "WHEN r.m - r.song_first_m < 6 THEN 3 WHEN r.m - r.song_first_m < 12 THEN 4 "
                   "WHEN r.m - r.song_first_m < 24 THEN 5 ELSE 6 END")
    if a.unit == "scene":
        age_sql = "0"
    # Momentum: fixed-panel growth over the 6 months before the bet (panel = active at m-6 and m), leave-one-out.
    if a.momentum and a.unit == "scene":  # scene growth over the 6 months before entry (from scene_bets)
        mom_sql, mom_join = f"coalesce(ntile({a.momentum}) OVER (PARTITION BY r.m ORDER BY r.mom_g), 0)", ""
    elif a.momentum and a.unit == "song":  # not available for songs (no monthly song listening for all users)
        mom_sql, mom_join = "0", ""
    elif a.momentum:
        # The bettor's own listening at m-6 and m, in one pass over the monthly table.
        con.execute("CREATE TABLE selfl (user BIGINT, artist BIGINT, bm SMALLINT, l6 BOOLEAN, lm BOOLEAN)")
        for c in "0123456789abcdef":
            con.execute(f"""INSERT INTO selfl
                SELECT r.user, r.artist, r.m, bool_or(u.month = r.m - 6), bool_or(u.month = r.m)
                FROM (SELECT * FROM r WHERE arch = '{c}') r JOIN read_parquet('{X}/user_artist_month/{a.half}/mlhdplus-{c}.parquet') u
                  ON u.user = r.user AND u.artist = r.artist AND u.month BETWEEN r.m - 6 AND r.m
                GROUP BY ALL""")
        con.execute(f"""CREATE TABLE mom AS
            SELECT r.user, r.artist, r.m AS bm,
                   ln(greatest(coalesce(mk.l1, 0) - (coalesce(s.lm, false) AND a0.user IS NOT NULL)::INT, 0) + 1)
                 - ln(greatest(coalesce(mk.l0, 0) - (coalesce(s.l6, false) AND a6.user IS NOT NULL)::INT, 0) + 1) AS g
            FROM r
            LEFT JOIN read_parquet('{X}/market/{a.half}/listeners_h6.parquet') mk ON mk.artist = r.artist AND mk.month = r.m - 6
            LEFT JOIN act a0 ON a0.user = r.user AND a0.month = r.m - 6
            LEFT JOIN act a6 ON a6.user = r.user AND a6.month = r.m
            LEFT JOIN selfl s ON s.user = r.user AND s.artist = r.artist AND s.bm = r.m""")
        mom_sql = f"coalesce(ntile({a.momentum}) OVER (PARTITION BY r.m ORDER BY mo.g), 0)"
        mom_join = "LEFT JOIN mom mo ON mo.user = r.user AND mo.artist = r.artist AND mo.bm = r.m"
    else:
        mom_sql, mom_join = "0", ""

    if a.release and a.unit != "scene":
        con.execute(f"""CREATE TABLE relm AS
            SELECT DISTINCT artist, (substr(first_release_date, 1, 4)::INT * 12 + substr(first_release_date, 6, 2)::INT - 1)::SMALLINT AS rm
            FROM read_parquet('{X}/mb_release_groups{"_lb" if a.half == "lb" else ""}.parquet')
            WHERE regexp_matches(first_release_date, '^[0-9]{{4}}-[0-9]{{2}}') AND first_release_date < '2700'  -- typo dates past a SMALLINT month
              AND primary_type IN ('Album', 'EP', 'Single') AND secondary_types NOT LIKE '%Compilation%'""")
        con.execute("""CREATE TABLE rel AS
            WITH k AS (SELECT DISTINCT artist, m FROM r)
            SELECT k.artist AS rel_artist, k.m AS rel_m,
                   CASE WHEN count(x.rm) = 0 THEN 4
                        ELSE 2 * (count(*) FILTER (WHERE x.rm > k.m AND x.rm <= k.m + 3) > 0)::INT
                           + (count(*) FILTER (WHERE x.rm >= k.m - 3 AND x.rm <= k.m) > 0)::INT END AS relc
            FROM k LEFT JOIN relm x ON x.artist = k.artist GROUP BY k.artist, k.m""")
        rel_sql, rel_join = "rel.relc", "LEFT JOIN rel ON rel.rel_artist = r.artist AND rel.rel_m = r.m"
    else:
        rel_sql, rel_join = "0", ""
    outcome_join = ""
    xb_sql, cg_sql = "0", None
    if a.model == "B" and a.unit in ("song", "scene"):
        # Community-leading for songs/scenes: share of your community adopting/entering after you, adjusted
        # (additively) for the community's overall rate that month.
        con.execute("DELETE FROM r WHERE g IS NULL OR k_comm IS NULL OR n_comm IS NULL OR n_comm <= 0")
        ret = "ln((r.k_comm + 0.5) / r.n_comm)"
        cg_sql = "r.g"
        # Prior popularity within the bettor's community (pipeline/derive_comm_prior.py), as for artists.
        if a.unit == "song":
            outcome_join = (f"LEFT JOIN (SELECT user AS pu, recording AS pr, m AS pm, c_prior FROM "
                            f"read_parquet('{X}/comm_prior/{a.half}_song.parquet')) cp ON cp.pu = r.user AND cp.pr = r.item AND cp.pm = r.m")
        else:
            outcome_join = (f"LEFT JOIN (SELECT user AS pu, scene::BIGINT * 10000 + year AS pi, m AS pm, c_prior FROM "
                            f"read_parquet('{X}/comm_prior/{a.half}_scene.parquet')) cp ON cp.pu = r.user AND cp.pi = r.item AND cp.pm = r.m")
    elif a.model == "C_lb" and a.unit == "scene":
        ret = "ln(1 + coalesce(r.lb_scene, 0))"
    elif a.model == "D" and a.unit in ("song", "scene"):
        con.execute("DELETE FROM r WHERE tr_later IS NULL")
        p0 = con.execute("SELECT sum(kept_later) / sum(tr_later) FROM r").fetchone()[0]
        ret = f"(r.kept_later + 2 * {p0}) / (r.tr_later + 2)"
        xb_sql = f"ntile(5) OVER (PARTITION BY r.m ORDER BY (r.kept_prior + 2 * {p0}) / (r.tr_prior + 2))"
    elif a.model == "C_lb" and a.unit == "song":
        ret = "ln(1 + coalesce(lb.lb_users, 0))"
        outcome_join = f"LEFT JOIN read_parquet('{X}/lb_recording_popularity.parquet') lb ON lb.recording = r.item"
    elif a.model == "A":
        ret = f"ln(l1 + {a.smooth}) - ln(l0 + {a.smooth})"
    elif a.model == "B":
        ret = "ln((cmt.k_later + 0.5) / greatest(cmt.cn_panel, 1))"
        outcome_join = (f"JOIN (SELECT user AS cu, artist AS ca, m AS cm, g AS cg, k_later, n_panel AS cn_panel, c_pen, c_mom "
                        f"FROM read_parquet('{X}/community/{a.half}_h{H}.parquet')) cmt "
                        f"ON cmt.cu = r.user AND cmt.ca = r.artist AND cmt.cm = r.m")
    elif a.model == "C_lb":
        ret = "ln(1 + coalesce(lb.lb_users, 0))"
        outcome_join = f"LEFT JOIN read_parquet('{X}/lb_artist_popularity.parquet') lb ON lb.artist = r.artist"
    else:
        con.execute(f"""CREATE TABLE trials AS
            SELECT b.artist, {MONTH.format(w='b.first_week')}::SMALLINT AS t, count(*) AS n,
                   count(*) FILTER (WHERE b.w4 IS NOT NULL AND b.w4 - b.first_week < 26) AS c
            FROM read_parquet('{X}/bets/{a.half}/*.parquet') b
            JOIN read_parquet('{X}/user_features/{a.half}.parquet') f USING (user)
            WHERE b.first_week >= f.start_week + 26 GROUP BY ALL""")
        p0 = con.execute("SELECT sum(c) / sum(n) FROM trials").fetchone()[0]
        con.execute("""CREATE TABLE cum AS SELECT artist, t, sum(n) OVER w AS cn, sum(c) OVER w AS cc FROM trials
                       WINDOW w AS (PARTITION BY artist ORDER BY t ROWS UNBOUNDED PRECEDING)""")
        con.execute(f"""CREATE TABLE dd AS
            WITH q AS (SELECT DISTINCT artist, m, (m + {H})::SMALLINT AS mh FROM r)
            SELECT q.artist AS dd_artist, q.m AS dd_m, coalesce(c1.cn, 0) - coalesce(c0.cn, 0) AS n_later,
                   coalesce(c1.cc, 0) - coalesce(c0.cc, 0) AS c_later,
                   (coalesce(c0.cc, 0) + 2 * {p0}) / (coalesce(c0.cn, 0) + 2) AS conv_prior
            FROM q ASOF LEFT JOIN cum c0 ON q.artist = c0.artist AND q.m >= c0.t
                   ASOF LEFT JOIN cum c1 ON q.artist = c1.artist AND q.mh >= c1.t""")
        ret = f"(dd.c_later + 2 * {p0}) / (dd.n_later + 2)"
        outcome_join = "JOIN dd ON dd.dd_artist = r.artist AND dd.dd_m = r.m"
    con.execute(f"""CREATE TABLE r2 AS
        SELECT r.*, {ret} AS ret, l0 / n_panel AS pen0, {scene_sql} AS scene,
               CASE WHEN l0 = 0 THEN 0 ELSE 1 + ntile({a.bins}) OVER (PARTITION BY m, l0 = 0 ORDER BY l0) END AS bin,
               pow(greatest(plays_26w, 1), {a.weight}) AS wt, {age_sql} AS age, {mom_sql} AS mq,
               {"coalesce(mb.country, 'XX')" if a.country and a.unit != "scene" else "'-'"} AS ctry, {rel_sql} AS relc,
               {"ntile(10) OVER (PARTITION BY r.m ORDER BY cmt.c_pen)" if a.model == "B" and a.unit == "artist" else
                 "ntile(10) OVER (PARTITION BY r.m ORDER BY coalesce(cp.c_prior, 0))" if a.model == "B" else "0"} AS cpb,
               {cg_sql if cg_sql else "cmt.cg" if a.model == "B" else "0"} AS cg,
               {(xb_sql if a.unit in ("song", "scene") else
                 "ntile(5) OVER (PARTITION BY r.m ORDER BY cmt.c_mom)" if a.model == "B" else
                 "ntile(5) OVER (PARTITION BY r.m ORDER BY dd.conv_prior)" if a.model == "D" else "0")} AS xb
        FROM r {scene_join} LEFT JOIN first_seen fs ON fs.artist = r.artist {mom_join} {outcome_join} {rel_join}
        {f"LEFT JOIN read_parquet('{X}/mb_artists{'_lb' if a.half == 'lb' else ''}.parquet') mb ON mb.artist = r.artist" if a.country and a.unit != "scene" else ""}""")
    for t in ("r", "first_seen", "mom", "selfl", "dd", "trials", "cum", "rel", "relm"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    cell = "m, bin, scene, age, mq, ctry, cpb, cg, xb, relc" if a.adjust == "cells" else "m, bin"
    extra_fx = [] if a.adjust == "cells" else [g for g, on in (("scene", a.scene != "none"), ("age", a.age),
                                                                   ("mq", a.momentum > 0), ("ctry", a.country), ("relc", a.release)) if on]
    if a.adjust != "cells" and a.model == "B" and a.unit != "artist":
        extra_fx += ["cpb", "cg"]  # prior popularity within the community; the community's monthly rate
    elif a.adjust != "cells" and a.model == "B":
        extra_fx += ["cpb", "cg", "xb"]  # prior popularity in the community; the community's own adoption rate
                                         # that month; momentum within the community
    if a.adjust != "cells" and a.model == "D":
        extra_fx.append("xb")  # the artist's track record of converting triers before the bet
    if a.metric == "log":
        val = "ret"
    elif a.metric == "rawcap":
        assert a.model == "A", "rawcap only makes sense for growth returns"
        val = "least(exp(ret), 20)"
    elif a.metric == "rank":
        val = "percent_rank() OVER (PARTITION BY m, bin, scene, age, mq, ctry, cpb, cg, xb, relc ORDER BY ret)"
    else:
        val = "(percent_rank() OVER (PARTITION BY m, bin, scene, age, mq, ctry, cpb, cg, xb, relc ORDER BY ret) >= 0.9)::INT"
    con.execute(f"""CREATE TABLE e AS
        WITH v AS (SELECT user, artist, item, m, bin, scene, age, mq, ctry, cpb, cg, xb, relc, pen0, wt, plays_26w, {val} AS v FROM r2)
        SELECT user, artist, item, m, bin, scene, age, mq, ctry, cpb, cg, xb, relc, pen0, wt, plays_26w, v,
               v - (sum(v) OVER c - v) / nullif(count(*) OVER c - 1, 0) AS e
        FROM v WINDOW c AS (PARTITION BY {cell})""")
    con.execute("DELETE FROM e WHERE e IS NULL")
    con.execute("DROP TABLE r2")
    # Additive adjustment: remove leave-one-out month x factor means of the excess, cycling until stable.
    for _ in range(4 if extra_fx else 0):
        for g in extra_fx:
            con.execute(f"""CREATE OR REPLACE TABLE e AS SELECT * REPLACE (
                e - (sum(e) OVER w - e) / nullif(count(*) OVER w - 1, 0) AS e) FROM e WINDOW w AS (PARTITION BY m, {g})""")
            con.execute("DELETE FROM e WHERE e IS NULL")
    if a.bets_out:
        con.execute(f"COPY (SELECT user, item, artist, m, bin, pen0, plays_26w, v, e FROM e) TO '{a.bets_out}' (FORMAT parquet)")
    if a.unit == "song":
        # Songs by the same artist adopted in the same month move together; treating them as independent bets
        # inflates reliability and the luck test. Collapse them into one bet (their weighted mean excess), with
        # the artist as the item for split halves. With --weight, the merged bet is weighted by its total early plays.
        con.execute(f"""CREATE OR REPLACE TABLE e AS
            SELECT user, artist, artist AS item, m, min(bin) AS bin, 0 AS scene, 0 AS age, 0 AS mq, '-' AS ctry,
                   0 AS cpb, 0 AS cg, 0 AS xb, 0 AS relc, avg(pen0) AS pen0,
                   pow(greatest(sum(plays_26w), 1), {a.weight}) AS wt, avg(v) AS v,
                   sum(wt * e) / sum(wt) AS e, count(*) AS songs
            FROM e GROUP BY user, artist, m""")
    diag = con.execute(f"""WITH c AS (SELECT {cell}, count(*) AS n, count(DISTINCT item) AS na FROM e GROUP BY ALL)
        SELECT sum(n * n) / sum(n), sum(n) FILTER (WHERE na = 1) / sum(n), sum(n * na) / sum(n) FROM c""").fetchone()
    n_bets, n_users = con.execute("SELECT count(*), count(DISTINCT user) FROM e").fetchone()
    if a.cand:
        # Compact aggregates for the evaluator: per user x bet year x random half of their bets (by item),
        # plus the same sums after shuffling excess outcomes among comparable bets (luck baseline).
        cdir = ROOT / "analysis" / "out" / "cand" / a.cand
        cdir.mkdir(parents=True, exist_ok=True)
        key = "(m // 12)::SMALLINT AS year, (hash(item) % 2)::TINYINT AS half"
        con.execute(f"""CREATE TABLE agg AS SELECT user, {key}, count(*)::INT AS n, sum(wt) AS sw,
                        sum(wt * e) AS swe, sum(wt * e * e) AS swe2 FROM e GROUP BY ALL""")
        for k in range(a.perms):
            con.execute(f"""CREATE OR REPLACE TEMP TABLE pk AS
                WITH o AS (SELECT user, m, item, wt, {cell}, row_number() OVER (PARTITION BY {cell} ORDER BY random()) AS k FROM e),
                     sh AS (SELECT e AS ep, {cell}, row_number() OVER (PARTITION BY {cell} ORDER BY random()) AS k FROM e)
                SELECT o.user, (o.m // 12)::SMALLINT AS year, (hash(o.item) % 2)::TINYINT AS half, sum(o.wt * sh.ep) AS v
                FROM o JOIN sh USING ({cell}, k) GROUP BY ALL""")
            con.execute(f"ALTER TABLE agg ADD COLUMN swe_p{k} DOUBLE")
            con.execute(f"UPDATE agg SET swe_p{k} = pk.v FROM pk WHERE pk.user = agg.user AND pk.year = agg.year AND pk.half = agg.half")
        con.execute(f"COPY agg TO '{cdir}/agg.parquet' (FORMAT parquet, COMPRESSION zstd)")
        (cdir / "meta.json").write_text(json.dumps({
            "name": a.cand, "model": a.model, "unit": a.unit, "horizon": a.horizon, "half": a.half,
            "bets": n_bets, "users_with_bets": n_users, "args": vars(a),
            "cells": {"bets_per_cell": diag[0], "share_single_item_cells": diag[1], "items_per_cell": diag[2]}}, indent=1))
        print(f"wrote {cdir}/agg.parquet ({n_bets:,} bets, {n_users:,} users)")
        return

    def user_means(col="e", where="TRUE", min_n=a.min_bets):
        return con.sql(f"""SELECT user, sum(wt * {col}) / sum(wt) AS score, count(*) AS n,
                                 var_samp({col}) AS var FROM e WHERE {where} GROUP BY user HAVING count(*) >= {min_n}""").pl()

    users = user_means()
    # Empirical Bayes shrinkage (method of moments).
    noise = (users["var"] / users["n"]).mean()
    tau2 = max(users["score"].var() - noise, 0.0)
    users = users.with_columns(shrunk=pl.col("score") * tau2 / (tau2 + pl.col("var") / pl.col("n")))

    # Test 1: luck baseline — shuffle e within cells, recompute the spread of user means.
    obs_var = users["score"].var()
    null_vars = []
    for i in range(a.perms):
        con.execute(f"""CREATE OR REPLACE TEMP TABLE pe AS
            WITH o AS (SELECT user, wt, {cell}, row_number() OVER (PARTITION BY {cell} ORDER BY random()) AS k FROM e),
                 s AS (SELECT e AS ep, {cell}, row_number() OVER (PARTITION BY {cell} ORDER BY random()) AS k FROM e)
            SELECT o.user, o.wt, s.ep FROM o JOIN s USING ({cell}, k)""")
        null_vars.append(con.sql(f"""SELECT var_samp(sc) FROM (SELECT sum(wt * ep) / sum(wt) AS sc FROM pe GROUP BY user
                                     HAVING count(*) >= {a.min_bets})""").fetchone()[0])
    null_vars = np.array(null_vars)

    # Test 2: persistence.
    def corr(df):
        if df.height < 30:
            return None, None, df.height
        return (float(np.corrcoef(df["s1"], df["s2"])[0, 1]),
                float(df.select(pl.corr("s1", "s2", method="spearman")).item()), df.height)

    def split(where1, where2, min_n=10):
        u1 = user_means(where=where1, min_n=min_n).select("user", s1="score")
        u2 = user_means(where=where2, min_n=min_n).select("user", s2="score")
        return u1.join(u2, on="user")

    con.execute("""CREATE OR REPLACE TEMP TABLE med AS SELECT user, median(m) AS mm FROM e GROUP BY user""")
    con.execute("CREATE OR REPLACE TEMP TABLE e2 AS SELECT e.*, med.mm FROM e JOIN med USING (user)")
    con.execute("ALTER TABLE e RENAME TO e_full; ALTER TABLE e2 RENAME TO e")
    halves = split("m <= mm", "m > mm")
    gap = split(f"m < mm - {H} / 2", f"m > mm + {H} / 2")  # return windows of the two halves don't overlap
    p1_end = 2008 * 12 + 11 - H + 12  # P1 returns end by 2009-12 (for H=12: bets to 2008-12)
    periods = split(f"m BETWEEN {2006 * 12} AND {p1_end}", f"m BETWEEN {2010 * 12} AND {LAST - H}")
    randsplit = split("hash(artist) % 2 = 0", "hash(artist) % 2 = 1")
    pers = {"halves": corr(halves), "halves_with_gap": corr(gap), "periods_2006_08_vs_2010_11": corr(periods),
            "random_split": corr(randsplit)}

    # Test 3: impostors.
    feats = pl.read_parquet(X / "user_features" / f"{a.half}.parquet")
    extra = con.sql("""SELECT user, avg(ln(pen0 + 1e-6)) AS obscurity_logpen,
                              -sum(q * ln(q)) AS scene_entropy FROM (
                           SELECT user, pen0, count(*) OVER (PARTITION BY user, scene) / count(*) OVER (PARTITION BY user) AS q
                           FROM e) GROUP BY user""").pl()
    df = users.join(feats, on="user").join(extra, on="user").drop_nulls()
    cols = ["listens", "history_years", "join_year", "listens_per_active_month", "unmatched_share", "no_id_share",
            "new_artists_per_year", "committed_per_year", "mainstream_share", "obscurity_logpen", "scene_entropy", "n",
            "commit_rate"]
    cols = [c for c in cols if df[c].cast(pl.Float64).std() > 0]  # e.g. scene_entropy is constant without scenes
    Z = df.select([pl.col(c).cast(pl.Float64) for c in cols]).with_columns(
        pl.col("listens").log(), pl.col("listens_per_active_month").log(), pl.col("n").log()).to_numpy()
    Z = np.column_stack([np.ones(len(Z)), (Z - Z.mean(0)) / Z.std(0)])
    y = df["score"].to_numpy()
    beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
    r2 = 1 - ((y - Z @ beta) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    single = {c: float(np.corrcoef(df[c].cast(pl.Float64).to_numpy() if c not in ("listens", "n") else
                                   np.log(df[c].to_numpy()), y)[0, 1]) for c in cols}
    # Persistence of the residual: residualize each half's score on the (whole-history) impostors.
    hz = halves.join(df.select("user", *cols), on="user")
    Zh = hz.select([pl.col(c).cast(pl.Float64) for c in cols]).with_columns(
        pl.col("listens").log(), pl.col("listens_per_active_month").log(), pl.col("n").log()).to_numpy()
    Zh = np.column_stack([np.ones(len(Zh)), (Zh - Zh.mean(0)) / Zh.std(0)])
    res = {}
    for s in ("s1", "s2"):
        yy = hz[s].to_numpy()
        bb, *_ = np.linalg.lstsq(Zh, yy, rcond=None)
        res[s] = yy - Zh @ bb
    resid_persistence = float(np.corrcoef(res["s1"], res["s2"])[0, 1])

    summary = {
        "variant": name, "model": a.model, "args": vars(a), "bets": n_bets, "users_with_bets": n_users, "users_scored": users.height,
        "median_bets_per_scored_user": float(users["n"].median()),
        "cells": {"bets_per_cell_bet_weighted": diag[0], "share_bets_in_single_artist_cells": diag[1],
                  "artists_per_cell_bet_weighted": diag[2]},
        "luck": {"observed_var": obs_var, "null_var_mean": float(null_vars.mean()), "null_var_max": float(null_vars.max()),
                 "skill_share_of_variance": float(1 - null_vars.mean() / obs_var)},
        "empirical_bayes": {"tau2": tau2, "noise_var_mean": float(noise),
                            "reliability_mean": float((tau2 / (tau2 + users["var"] / users["n"])).mean())},
        "persistence": {k: {"pearson": v[0], "spearman": v[1], "users": v[2]} for k, v in pers.items()},
        "impostors": {"r2_all": float(r2), "corr_with_score": single, "residual_persistence_halves": resid_persistence},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    users.write_parquet(out / "users.parquet")
    print(json.dumps(summary, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
