"""What one new fan is worth to an artist, by kind of fan and by the artist's stage (post-freeze; one run per half).

Data: analysis/pickers.py (raters' new fans per artist-month; growth among the outcome group only). One model per
stage: next-year growth on the numbers of good, ordinary, poor, and unrated new fans and the share of rated new fans who
are good, within cells of month x size (log2 bins) x momentum. Stages: artist size at the time (panel listeners in the
outcome group: small <= 20, medium 21-100, big > 100; the explore half's thirds) and artist age (months since the
artist first appears in this half's listening). 95% intervals: bootstrap over artists (500 draws).

Usage: fan_value.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(4242)
B = 500
COLS = ["n_good", "n_ord", "n_poor", "n_unrated", "share"]
NAMES = {"n_good": "good", "n_ord": "ordinary", "n_poor": "poor", "n_unrated": "unrated", "share": "share_good"}


def load(half):
    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'; SET threads=6")
    fs = con.execute(f"SELECT artist, min(month) AS fm FROM read_parquet('{X}/user_artist_month/{half}/*.parquet') GROUP BY artist").pl()
    df = pl.read_parquet(X / "pickers" / f"rate_A_{half}.parquet").join(fs, on="artist", how="left")
    df = df.with_columns(n_rated=pl.col("n_good") + pl.col("n_ord") + pl.col("n_poor")).filter(pl.col("n_rated") >= 1)
    return df.with_columns(
        g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
        mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
        share=pl.col("n_good") / pl.col("n_rated"), age=pl.col("m") - pl.col("fm")).with_columns(
        size=pl.when(pl.col("l0") <= 20).then(pl.lit("small")).when(pl.col("l0") <= 100).then(pl.lit("medium")).otherwise(pl.lit("big")),
        newness=pl.when(pl.col("fm") <= 2005 * 12 + 3).then(pl.lit("old")).when(pl.col("age") <= 6).then(pl.lit("brand new"))
        .when(pl.col("age") <= 24).then(pl.lit("6-24 months")).otherwise(pl.lit("2+ years")))


def fit(d):
    cell = ["m", "sz", "mo"]
    for v in ["g"] + COLS:
        d = d.with_columns((pl.col(v) - pl.col(v).mean().over(cell)).alias(v + "_d"))
    Xm = d.select([c + "_d" for c in COLS]).to_numpy().astype(float)
    y = d["g_d"].to_numpy()
    est = np.linalg.lstsq(Xm, y, rcond=None)[0]
    ua, inv = np.unique(d["artist"].to_numpy(), return_inverse=True)
    bs = []
    for _ in range(B):
        w = np.sqrt(RNG.poisson(1.0, len(ua))[inv].astype(float))
        bs.append(np.linalg.lstsq(Xm * w[:, None], y * w, rcond=None)[0])
    return est, np.array(bs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    df = load(half)
    rows, boots = [], {}
    for dim, levels in (("size", ["small", "medium", "big"]), ("newness", ["brand new", "6-24 months", "2+ years", "old"]), ("all", ["all"])):
        for lev in levels:
            d = df if dim == "all" else df.filter(pl.col(dim) == lev)
            est, bs = fit(d)
            boots[(dim, lev)] = bs
            for i, c in enumerate(COLS):
                rows.append({"key": f"{dim}:{lev}:{NAMES[c]}", "stage_type": dim, "stage": lev, "fan": NAMES[c], "artist_months": d.height,
                             "effect": float(np.expm1(est[i])), "lo": float(np.expm1(np.percentile(bs[:, i], 2.5))),
                             "hi": float(np.expm1(np.percentile(bs[:, i], 97.5)))})
            gap = bs[:, 0] - bs[:, 1]
            rows.append({"key": f"{dim}:{lev}:good_minus_ordinary", "stage_type": dim, "stage": lev, "fan": "good_minus_ordinary",
                         "artist_months": d.height, "effect": float(est[0] - est[1]), "lo": float(np.percentile(gap, 2.5)),
                         "hi": float(np.percentile(gap, 97.5)), "lo99": float(np.percentile(gap, 0.5))})
    gs = boots[("size", "small")][:, 0] - boots[("size", "small")][:, 1]
    gb = boots[("size", "big")][:, 0] - boots[("size", "big")][:, 1]
    dd = gs - gb
    tests = {"P6a_small_good_minus_ordinary": {"est": float(np.median(gs)), "lo99": float(np.percentile(gs, 0.5))},
             "P6b_gap_small_minus_big": {"est": float(np.median(dd)), "lo99": float(np.percentile(dd, 0.5))}}
    for r in rows:
        if r["fan"] in ("good", "ordinary", "poor", "share_good", "good_minus_ordinary"):
            print(f"  {r['stage_type']:8s} {r['stage']:12s} {r['fan']:20s} {r['effect']:+7.2%} [{r['lo']:+.2%}, {r['hi']:+.2%}]")
    print("tests:", json.dumps(tests))
    (ROOT / "analysis" / "out" / f"fan_value_{half}.json").write_text(json.dumps({"rows": rows, "tests": tests}, indent=1))


if __name__ == "__main__":
    main()
