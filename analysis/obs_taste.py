"""Obsession and taste: does getting hooked mean more for good pickers? (post-freeze; one run per half)

People rated on artist picks up to cutoff C (2007..2009; frozen prescience score), grouped into bottom fifth, middle, top
fifth. Their picks made in C+2..C+3, with plays before committing (pipeline/derive_obsession.py). Outcome: each pick's
excess growth under the frozen measure (all controls). Bins of plays: 1-4, 5-6, 7-9, 10-14, 15-24, 25-49, 50-99, 100+.
Gain from getting hooked = mean outcome of picks with 10+ plays minus picks with 1-4 plays, within a group.
Test: top fifth's gain minus bottom fifth's gain > 0. Also the all-picks curve by the same bins. Bootstrap over people.

Usage: obs_taste.py --half explore|sealed
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from explain import bets_with_bands  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(909)
B = 1000
BINS = [(1, 4), (5, 6), (7, 9), (10, 14), (15, 24), (25, 49), (50, 99), (100, 10**9)]


def label(lo, hi):
    return f"{lo}–{hi}" if hi < 10**9 else f"{lo}+"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    _, f = bets_with_bands(half)
    ob = pl.read_parquet(X / "obsession" / f"{half}_artist.parquet", columns=["user", "artist", "plays_to_commit"])
    f = f.filter(pl.col("period") == "future").join(ob, on=["user", "artist"], how="inner").filter(pl.col("plays_to_commit") > 0)
    f = f.with_columns(grp=pl.when(pl.col("q") > 0.8).then(pl.lit("top")).when(pl.col("q") <= 0.2).then(pl.lit("bottom")).otherwise(pl.lit("middle")))
    lab = pl.lit(None, pl.String)
    for lo, hi in BINS:
        lab = pl.when(pl.col("plays_to_commit").is_between(lo, hi)).then(pl.lit(label(lo, hi))).otherwise(lab)
    f = f.with_columns(pb=lab, hooked=(pl.col("plays_to_commit") >= 10), casual=(pl.col("plays_to_commit") <= 4))

    curve = []
    for g in ("bottom", "middle", "top", "all"):
        d = f if g == "all" else f.filter(pl.col("grp") == g)
        for i, (lo, hi) in enumerate(BINS):
            x = d.filter(pl.col("pb") == label(lo, hi))
            per = x.group_by("user").agg(s=pl.col("e").sum(), n=pl.len())
            sv, nv = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (300, per.height)).astype(float)
            bs = (w @ sv) / (w @ nv)
            curve.append({"key": f"{g}:{label(lo, hi)}", "group": g, "bin": label(lo, hi), "order": i, "x": float(np.sqrt(lo * min(hi, 300))),
                          "growth": float(np.expm1(sv.sum() / nv.sum())), "lo": float(np.expm1(np.percentile(bs, 2.5))),
                          "hi": float(np.expm1(np.percentile(bs, 97.5))), "picks": int(nv.sum())})

    def gains(g):
        d = f.filter(pl.col("grp") == g)
        per = d.group_by("user").agg(sh=pl.col("e").filter(pl.col("hooked")).sum(), nh=pl.col("hooked").sum(),
                                     sc=pl.col("e").filter(pl.col("casual")).sum(), nc=pl.col("casual").sum())
        A = {k: per[k].to_numpy().astype(float) for k in ("sh", "nh", "sc", "nc")}
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        est = A["sh"].sum() / A["nh"].sum() - A["sc"].sum() / A["nc"].sum()
        return est, (w @ A["sh"]) / (w @ A["nh"]) - (w @ A["sc"]) / (w @ A["nc"])
    gt, bt = gains("top")
    gb, bb = gains("bottom")
    diff = bt - bb
    test = {"top_gain": float(gt), "bottom_gain": float(gb), "diff": float(gt - gb), "lo": float(np.percentile(diff, 2.5)),
            "hi": float(np.percentile(diff, 97.5)), "lo99": float(np.percentile(diff, 0.5))}
    print(json.dumps(test, indent=1))
    for g in ("bottom", "middle", "top", "all"):
        print(f"  {g:7s} " + "  ".join(f"{r['bin']} {r['growth']:+.1%}" for r in curve if r["group"] == g))
    (ROOT / "analysis" / "out" / f"obs_taste_{half}.json").write_text(json.dumps({"curve": curve, "test": test}, indent=1))


if __name__ == "__main__":
    main()
