"""Exploration (explore half, post-freeze): the marginal value of one more good picker.

People in the explore half are split at random into raters and an outcome group.
  Track records (raters only): each rater's bets up to a cutoff year C, scored by the frozen main measure's per-bet
    excess e (prescience by default; --rate-by D for discernment), shrunk toward 0 (sum e / (n + 20)), raters with
    >= 20 bets. Good = top fifth, poor = bottom fifth, the rest = ordinary.
  New picks: raters' bets (commitment month m) in year C + 2, counted per artist-month: n_good, n_poor, n_ord, and
    n_unrated (raters with too little history).
  Outcome (outcome group only, so no rater's listening counts): a fixed panel of outcome-group users active in m-3, m,
    and m+12; l_pre, l0, l1 = panel users playing the artist in those months. Growth = log((l1+1)/(l0+1)).
  Comparison: artist-months in the same cell (month x size x momentum x number of rated pickers x number of unrated
    pickers; and, as a second version, also the artist's scene), so "one more good picker" is measured against
    "one more ordinary picker" with the same total number of pickers.
Cutoffs C = 2006..2009 (picks 2008..2011, outcomes through 2012). 95% intervals: bootstrap over artists (200 draws).

Usage: pickers.py [--rate-by A|D]
"""

import argparse
import json
import os
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutoffs import cuts, picker_cuts, genre_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(11)
B = 1000
LOG2, LOG4 = float(np.log(2)), float(np.log(4))


def build(con, rate_by, half="explore"):
    CUTS = picker_cuts(half)
    con.execute(f"""CREATE TABLE b AS SELECT user, artist, m, e, (hash(user + 7919) % 2 = 0) AS rater
                    FROM read_parquet('{X}/bet_outcomes/{rate_by}_artist_{half}.parquet')""")
    parts = []
    for c in CUTS:
        parts.append(f"""
            SELECT {c} AS cut, b.artist, b.m,
                   count(*) FILTER (WHERE t.grp = 'good') AS n_good, count(*) FILTER (WHERE t.grp = 'poor') AS n_poor,
                   count(*) FILTER (WHERE t.grp = 'ord') AS n_ord, count(*) FILTER (WHERE t.grp IS NULL) AS n_unrated
            FROM b LEFT JOIN (
                SELECT user, CASE WHEN q > 0.8 THEN 'good' WHEN q <= 0.2 THEN 'poor' ELSE 'ord' END AS grp
                FROM (SELECT user, percent_rank() OVER (ORDER BY sum(e) / (count(*) + 20)) AS q FROM b
                      WHERE rater AND m // 12 <= {c} GROUP BY user HAVING count(*) >= 20)) t USING (user)
            WHERE b.rater AND b.m // 12 = {c + 2}
            GROUP BY b.artist, b.m""")
    con.execute("CREATE TABLE tgt AS " + " UNION ALL ".join(parts))
    print("target artist-months", con.execute("SELECT count(*), sum(n_good), sum(n_ord), sum(n_poor), sum(n_unrated) FROM tgt").fetchone(), flush=True)

    # Outcome-group activity and the fixed panel for each target month.
    con.execute(f"""CREATE TABLE ou AS SELECT DISTINCT user FROM read_parquet('{X}/user_artist_month/{half}/*.parquet')
                    WHERE hash(user + 7919) % 2 = 1""")
    con.execute(f"""CREATE TABLE act AS SELECT DISTINCT user, month FROM read_parquet('{X}/user_artist_month/{half}/*.parquet')
                    WHERE hash(user + 7919) % 2 = 1 AND month >= {(CUTS[0] + 2) * 12 - 3}""")
    con.execute("""CREATE TABLE months AS SELECT DISTINCT m FROM tgt""")
    con.execute("""CREATE TABLE panel AS SELECT a0.user, mo.m FROM months mo
                   JOIN act a0 ON a0.month = mo.m
                   JOIN act ap ON ap.user = a0.user AND ap.month = mo.m - 3
                   JOIN act a1 ON a1.user = a0.user AND a1.month = mo.m + 12""")
    print("panel user-months", con.execute("SELECT count(*), count(DISTINCT m) FROM panel").fetchone(), flush=True)
    con.execute("CREATE TABLE ta AS SELECT DISTINCT artist, m FROM tgt")
    con.execute("CREATE TABLE cnt (artist BIGINT, m SMALLINT, l_pre INT, l0 INT, l1 INT)")
    for f in sorted((X / "user_artist_month" / half).glob("*.parquet")):
        con.execute(f"""INSERT INTO cnt
            WITH u AS (SELECT user, artist, month FROM read_parquet('{f}') WHERE hash(user + 7919) % 2 = 1),
                 hits AS (SELECT ta.artist, ta.m, u.user, (u.month - ta.m) AS off FROM ta
                          JOIN u ON u.artist = ta.artist AND u.month IN (ta.m - 3, ta.m, ta.m + 12))
            SELECT h.artist, h.m, count(*) FILTER (WHERE off = -3), count(*) FILTER (WHERE off = 0),
                   count(*) FILTER (WHERE off = 12)
            FROM hits h JOIN panel p ON p.user = h.user AND p.m = h.m GROUP BY h.artist, h.m""")
    con.execute("""CREATE TABLE outc AS SELECT artist, m, sum(l_pre)::INT AS l_pre, sum(l0)::INT AS l0, sum(l1)::INT AS l1
                   FROM cnt GROUP BY artist, m""")
    return con.execute(f"""
        SELECT t.*, coalesce(o.l_pre, 0) AS l_pre, coalesce(o.l0, 0) AS l0, coalesce(o.l1, 0) AS l1,
               coalesce(sc.scene_200, -1) AS scene
        FROM tgt t LEFT JOIN outc o USING (artist, m)
        LEFT JOIN read_parquet('{X}/scenes_yearly/{'lb' if half == 'lb' else 'explore'}.parquet') sc ON sc.artist = t.artist AND sc.year = t.m // 12
        """).pl()


def nbin(c, cap_bins=((1, 1), (2, 2), (3, 3), (4, 4), (5, 6), (7, 9), (10, 15), (16, 10**9))):
    e = pl.lit(len(cap_bins))
    for i, (lo, hi) in reversed(list(enumerate(cap_bins))):
        e = pl.when(pl.col(c).is_between(lo, hi)).then(i).otherwise(e)
    return e


def analyze(df, with_scene):
    df = df.with_columns(n_rated=pl.col("n_good") + pl.col("n_poor") + pl.col("n_ord")).filter(pl.col("n_rated") >= 1)
    df = df.with_columns(
        g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(),
        sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
        mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
        nb=nbin("n_rated"), ub=pl.col("n_unrated").clip(0, 4))
    df = df.with_columns(dbl=(pl.col("g") >= LOG2).cast(pl.Float64), brk=(pl.col("g") >= LOG4).cast(pl.Float64))
    cell = ["m", "sz", "mo", "nb", "ub"] + (["scene"] if with_scene else [])
    df = df.with_columns(csize=pl.len().over(cell)).filter(pl.col("csize") >= 2)
    for v in ("g", "dbl", "brk", "n_good", "n_poor"):
        df = df.with_columns((pl.col(v) - pl.col(v).mean().over(cell)).alias(f"{v}_x"),
                             pl.col(v).mean().over(cell).alias(f"{v}_exp"))

    def coefs(d, w=None):
        X_ = d.select("n_good_x", "n_poor_x").to_numpy()
        out = {}
        for v in ("g", "dbl", "brk"):
            y = d[f"{v}_x"].to_numpy()
            if w is None:
                b = np.linalg.lstsq(X_, y, rcond=None)[0]
            else:
                sw = np.sqrt(w)
                b = np.linalg.lstsq(X_ * sw[:, None], y * sw, rcond=None)[0]
            out[v] = b
        return out

    est = coefs(df)
    arts = df["artist"].to_numpy()
    ua, inv = np.unique(arts, return_inverse=True)
    boots = {v: [] for v in est}
    for _ in range(B):
        w = RNG.poisson(1.0, len(ua))[inv].astype(float)
        bb = coefs(df, w)
        for v in bb:
            boots[v].append(bb[v])
    res = {"artist_months": df.height, "artists": len(ua), "with_scene": with_scene}
    for v in est:
        bs = np.array(boots[v])
        res[v] = {"good_vs_ordinary": float(est[v][0]), "good_ci": [float(x) for x in np.percentile(bs[:, 0], [2.5, 97.5, 0.5])],
                  "poor_vs_ordinary": float(est[v][1]), "poor_ci": [float(x) for x in np.percentile(bs[:, 1], [2.5, 97.5, 0.5])]}
    res["base_rates"] = {"doubling": float(df["dbl"].mean()), "breakout_4x": float(df["brk"].mean()),
                         "median_l0": float(df["l0"].median())}
    # Plain table: for a fixed number of rated pickers, outcomes by how many of them are good.
    rows = []
    for k in (1, 2, 3, 4, 5):
        dk = df.filter(pl.col("n_rated") == k)
        for ng in range(0, k + 1):
            x = dk.filter(pl.col("n_good") == ng)
            if x.height < 200:
                continue
            rows.append({"pickers": k, "good": ng, "artist_months": x.height,
                         "excess_growth": float(x["g_x"].mean()), "doubling": float(x["dbl"].mean()),
                         "doubling_expected": float(x["dbl_exp"].mean()), "breakout": float(x["brk"].mean()),
                         "breakout_expected": float(x["brk_exp"].mean())})
    res["table"] = rows
    # Many pickers: total rated pickers 5+, by count of good pickers.
    d5 = df.filter(pl.col("n_rated") >= 5).with_columns(gb=pl.col("n_good").clip(0, 4))
    res["five_plus"] = d5.group_by("gb").agg(n=pl.len(), excess_growth=pl.col("g_x").mean(), doubling=pl.col("dbl").mean(),
                                            doubling_expected=pl.col("dbl_exp").mean(), breakout=pl.col("brk").mean(),
                                            breakout_expected=pl.col("brk_exp").mean()).sort("gb").to_dicts()
    return res


def report(label, r):
    g, d, k = r["g"], r["dbl"], r["brk"]
    print(f"\n== {label}: {r['artist_months']:,} artist-months, {r['artists']:,} artists; "
          f"base doubling {r['base_rates']['doubling']:.1%}, 4x breakout {r['base_rates']['breakout_4x']:.1%}")
    print(f"  swap one ordinary picker for a GOOD one: growth {np.expm1(g['good_vs_ordinary']):+.1%} "
          f"[{np.expm1(g['good_ci'][0]):+.1%}, {np.expm1(g['good_ci'][1]):+.1%}]; doubling {d['good_vs_ordinary'] * 100:+.2f} pts "
          f"[{d['good_ci'][0] * 100:+.2f}, {d['good_ci'][1] * 100:+.2f}]; breakout {k['good_vs_ordinary'] * 100:+.2f} pts "
          f"[{k['good_ci'][0] * 100:+.2f}, {k['good_ci'][1] * 100:+.2f}]")
    print(f"  swap one ordinary picker for a POOR one: growth {np.expm1(g['poor_vs_ordinary']):+.1%} "
          f"[{np.expm1(g['poor_ci'][0]):+.1%}, {np.expm1(g['poor_ci'][1]):+.1%}]; doubling {d['poor_vs_ordinary'] * 100:+.2f} pts")
    for row in r["table"]:
        print(f"    {row['pickers']} pickers, {row['good']} good: n {row['artist_months']:>8,}  excess growth {np.expm1(row['excess_growth']):+6.1%}  "
              f"doubling {row['doubling']:.1%} (expected {row['doubling_expected']:.1%})  breakout {row['breakout']:.2%} (expected {row['breakout_expected']:.2%})")
    print("  5+ rated pickers, by good pickers among them:")
    for row in r["five_plus"]:
        print(f"    {row['gb']}{'+' if row['gb'] == 4 else ' '} good: n {row['n']:>7,}  excess growth {np.expm1(row['excess_growth']):+6.1%}  "
              f"doubling {row['doubling']:.1%} (expected {row['doubling_expected']:.1%})  breakout {row['breakout']:.2%} (expected {row['breakout_expected']:.2%})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate-by", choices=["A", "D"], default="A")
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], default="explore")
    a = ap.parse_args()
    tmp = ROOT / "data" / "_tmp" / f"pickers-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        con = duckdb.connect()
        con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; "
                    "SET max_temp_directory_size='30GB'")
        cache = X / "pickers" / f"rate_{a.rate_by}_{a.half}.parquet"
        cache.parent.mkdir(exist_ok=True)
        if cache.exists():
            df = pl.read_parquet(cache)
        else:
            df = build(con, a.rate_by, a.half)
            df.write_parquet(cache)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = {}
    for with_scene in (False, True):
        r = analyze(df, with_scene)
        out["scene" if with_scene else "no_scene"] = r
        report(f"rated by {a.rate_by}, {'same scene too' if with_scene else 'month x size x momentum x pickers'}", r)
    (ROOT / "analysis" / "out" / f"pickers_{a.rate_by}{'' if a.half == 'explore' else '_' + a.half}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
