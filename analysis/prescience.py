"""Model A (prescience / investment) on the explore half: score users and run tests 1-3 for one variant.

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
    ap.add_argument("--adjust", choices=["cells", "additive"], default="cells",
                    help="cells: one benchmark cell per month x bin x scene x age x momentum; additive: month x bin cell "
                         "plus separate leave-one-out month x scene / month x age / month x momentum adjustments (backfitted)")
    ap.add_argument("--metric", choices=["log", "rank", "rawcap", "hit"], default="log")
    ap.add_argument("--weight", type=float, default=0.0, help="alpha in plays_26w^alpha")
    ap.add_argument("--min-bets", type=int, default=20)
    ap.add_argument("--perms", type=int, default=20)
    ap.add_argument("--name", default=None)
    return ap.parse_args()


def variant_name(a):
    return a.name or (f"on{a.onboarding}_{a.rule}_win{a.window}_{a.date}_h{a.horizon}_s{a.smooth:g}_b{a.bins}"
                      f"_{a.scene}{'_age' if a.age else ''}{f'_mom{a.momentum}' if a.momentum else ''}{'_ctry' if a.country else ''}_{a.adjust}_{a.metric}_w{a.weight:g}")


def main():
    a = parse()
    name = variant_name(a)
    out = ROOT / "analysis" / "out" / "prescience" / name
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"prescience-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='8GB'; SET threads=8; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    H = a.horizon
    datecol = "first_week" if a.date == "first" or a.rule == "all" else RULES[a.rule]
    commit = "TRUE" if a.rule == "all" else f"b.{RULES[a.rule]} IS NOT NULL AND b.{RULES[a.rule]} - b.first_week < {a.window}"

    con.execute(f"""CREATE TABLE b AS
        SELECT b.user, b.artist, {MONTH.format(w='b.' + datecol)}::SMALLINT AS m, b.plays_26w
        FROM read_parquet('{X}/bets/explore/*.parquet') b
        JOIN read_parquet('{X}/user_features/explore.parquet') f USING (user)
        WHERE b.first_week >= f.start_week + {a.onboarding} AND {commit}
          AND {MONTH.format(w='b.' + datecol)} BETWEEN {2005 * 12} AND {LAST - H}""")
    con.execute(f"""CREATE TABLE act AS SELECT DISTINCT user, month FROM read_parquet('{X}/user_artist_month/explore/*.parquet')""")
    con.execute(f"""CREATE TABLE r AS
        SELECT b.*, coalesce(mk.l0, 0) - (a1.user IS NOT NULL)::INT AS l0,
               coalesce(mk.l1, 0) - (u1.user IS NOT NULL)::INT AS l1, p.n_panel
        FROM b
        LEFT JOIN read_parquet('{X}/market/explore/listeners_h{H}.parquet') mk ON mk.artist = b.artist AND mk.month = b.m
        JOIN read_parquet('{X}/market/explore/panel.parquet') p ON p.month = b.m AND p.h = {H}
        LEFT JOIN act a1 ON a1.user = b.user AND a1.month = b.m + {H}
        LEFT JOIN read_parquet('{X}/user_artist_month/explore/*.parquet') u1
               ON u1.user = b.user AND u1.artist = b.artist AND u1.month = b.m + {H}""")
    bad = con.execute("SELECT count(*) FROM r WHERE l0 < 0 OR l1 < 0").fetchone()[0]
    assert bad == 0, f"{bad} bets with negative leave-one-out counts"

    if a.scene == "none":
        scene_sql, scene_join = "0", ""
    elif a.scene.startswith("yearly"):
        k = a.scene.removeprefix("yearly")
        scene_sql = f"coalesce(sc.scene_{k}, -1)"
        scene_join = (f"LEFT JOIN read_parquet('{X}/scenes_yearly/explore.parquet') sc "
                      f"ON sc.artist = r.artist AND sc.year = r.m // 12")
    elif a.scene == "allyears200":
        scene_sql, scene_join = "sc.scene_200", f"LEFT JOIN read_parquet('{X}/scenes/explore.parquet') sc USING (artist)"
    else:
        scene_sql, scene_join = "sc.scene_200", f"JOIN read_parquet('{X}/scenes_genre/all.parquet') sc USING (artist)"

    # Artist age: months since the artist first appears in this half's listening (censored at 2005-01).
    con.execute(f"""CREATE TABLE first_seen AS SELECT artist, min(month) AS fm
                    FROM read_parquet('{X}/user_artist_month/explore/*.parquet') GROUP BY artist""")
    age_sql = ("CASE WHEN fs.fm <= 2005 * 12 THEN 9 WHEN r.m - fs.fm < 3 THEN 0 WHEN r.m - fs.fm < 6 THEN 1 "
               "WHEN r.m - fs.fm < 12 THEN 2 WHEN r.m - fs.fm < 24 THEN 3 ELSE 4 END") if a.age else "0"
    # Momentum: fixed-panel growth over the 6 months before the bet (panel = active at m-6 and m), leave-one-out.
    if a.momentum:
        con.execute(f"""CREATE TABLE mom AS
            SELECT r.user, r.artist, r.m AS bm,
                   ln(greatest(coalesce(mk.l1, 0) - (u0.user IS NOT NULL AND a0.user IS NOT NULL)::INT, 0) + 1)
                 - ln(greatest(coalesce(mk.l0, 0) - (u6.user IS NOT NULL AND a6.user IS NOT NULL)::INT, 0) + 1) AS g
            FROM r
            LEFT JOIN read_parquet('{X}/market/explore/listeners_h6.parquet') mk ON mk.artist = r.artist AND mk.month = r.m - 6
            LEFT JOIN act a0 ON a0.user = r.user AND a0.month = r.m - 6
            LEFT JOIN read_parquet('{X}/user_artist_month/explore/*.parquet') u0
                   ON u0.user = r.user AND u0.artist = r.artist AND u0.month = r.m
            LEFT JOIN act a6 ON a6.user = r.user AND a6.month = r.m
            LEFT JOIN read_parquet('{X}/user_artist_month/explore/*.parquet') u6
                   ON u6.user = r.user AND u6.artist = r.artist AND u6.month = r.m - 6""")
        mom_sql = f"coalesce(ntile({a.momentum}) OVER (PARTITION BY r.m ORDER BY mo.g), 0)"
        mom_join = "LEFT JOIN mom mo ON mo.user = r.user AND mo.artist = r.artist AND mo.bm = r.m"
    else:
        mom_sql, mom_join = "0", ""

    ret = f"ln(l1 + {a.smooth}) - ln(l0 + {a.smooth})"
    con.execute(f"""CREATE TABLE r2 AS
        SELECT r.*, {ret} AS ret, l0 / n_panel AS pen0, {scene_sql} AS scene,
               CASE WHEN l0 = 0 THEN 0 ELSE 1 + ntile({a.bins}) OVER (PARTITION BY m, l0 = 0 ORDER BY l0) END AS bin,
               pow(greatest(plays_26w, 1), {a.weight}) AS wt, {age_sql} AS age, {mom_sql} AS mq,
               {"coalesce(mb.country, 'XX')" if a.country else "'-'"} AS ctry
        FROM r {scene_join} LEFT JOIN first_seen fs ON fs.artist = r.artist {mom_join}
        {f"LEFT JOIN read_parquet('{X}/mb_artists.parquet') mb ON mb.artist = r.artist" if a.country else ""}""")
    cell = "m, bin, scene, age, mq, ctry" if a.adjust == "cells" else "m, bin"
    extra_fx = [] if a.adjust == "cells" else [g for g, on in (("scene", a.scene != "none"), ("age", a.age),
                                                                   ("mq", a.momentum > 0), ("ctry", a.country)) if on]
    if a.metric == "log":
        val = "ret"
    elif a.metric == "rawcap":
        val = "least(exp(ret), 20)"
    elif a.metric == "rank":
        val = "percent_rank() OVER (PARTITION BY m, bin, scene, age, mq, ctry ORDER BY ret)"
    else:
        val = "(percent_rank() OVER (PARTITION BY m, bin, scene, age, mq, ctry ORDER BY ret) >= 0.9)::INT"
    con.execute(f"""CREATE TABLE e AS
        WITH v AS (SELECT *, {val} AS v FROM r2)
        SELECT user, artist, m, bin, scene, age, mq, ctry, pen0, wt, v,
               v - (sum(v) OVER c - v) / nullif(count(*) OVER c - 1, 0) AS e
        FROM v WINDOW c AS (PARTITION BY {cell})""")
    con.execute("DELETE FROM e WHERE e IS NULL")
    # Additive adjustment: remove leave-one-out month x factor means of the excess, cycling until stable.
    for _ in range(4 if extra_fx else 0):
        for g in extra_fx:
            con.execute(f"""CREATE OR REPLACE TABLE e AS SELECT * REPLACE (
                e - (sum(e) OVER w - e) / nullif(count(*) OVER w - 1, 0) AS e) FROM e WINDOW w AS (PARTITION BY m, {g})""")
            con.execute("DELETE FROM e WHERE e IS NULL")
    diag = con.execute(f"""WITH c AS (SELECT {cell}, count(*) AS n, count(DISTINCT artist) AS na FROM e GROUP BY ALL)
        SELECT sum(n * n) / sum(n), sum(n) FILTER (WHERE na = 1) / sum(n), sum(n * na) / sum(n) FROM c""").fetchone()
    n_bets, n_users = con.execute("SELECT count(*), count(DISTINCT user) FROM e").fetchone()

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
    feats = pl.read_parquet(X / "user_features" / "explore.parquet")
    extra = con.sql("""SELECT user, avg(ln(pen0 + 1e-6)) AS obscurity_logpen,
                              -sum(q * ln(q)) AS scene_entropy FROM (
                           SELECT user, pen0, count(*) OVER (PARTITION BY user, scene) / count(*) OVER (PARTITION BY user) AS q
                           FROM e) GROUP BY user""").pl()
    df = users.join(feats, on="user").join(extra, on="user").drop_nulls()
    cols = ["listens", "history_years", "join_year", "listens_per_active_month", "unmatched_share", "no_id_share",
            "new_artists_per_year", "committed_per_year", "mainstream_share", "obscurity_logpen", "scene_entropy", "n"]
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
        "variant": name, "args": vars(a), "bets": n_bets, "users_with_bets": n_users, "users_scored": users.height,
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
