"""Exploration (explore half, post-freeze): taste measured on each person's *underground favorites*.

Underground: a bet whose popularity at the time was in the lower U share of all bets that month.
Favorites: among a person's underground bets, the top C share by plays before committing (no look-ahead).
For each (U, C) and each of prescience/discernment x artists/songs, this writes the same per-user aggregates the
main pipeline uses (with 10 luck shuffles within month x popularity cells) to analysis/out/cand/uc_<...>/ and runs
analysis/evaluate.py, so scorecards are directly comparable to the original measures.

Plain units (prescience only): "breakout" = the pick's listeners grew 4x or more within 12 months (fixed panel,
bettor excluded). Forward test: people ranked by their underground-favorites score up to a cutoff year; breakout
rate of their underground favorites 2+ years later, top fifth vs bottom fifth vs comparable picks (same month and
popularity group).
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
RNG = np.random.default_rng(9)
K = 10
GRID = [(0.25, 0.25), (0.25, 1.0), (0.5, 0.25), (0.5, 0.5), (0.5, 1.0), (1.0, 0.25), (1.0, 1.0)]
BREAKOUT = float(np.log(4))


def load(key):
    unit = "artist" if key.endswith("artist") else "song"
    bets = pl.read_parquet(X / "bet_outcomes" / f"{key}_explore.parquet")
    obs = pl.read_parquet(X / "obsession" / f"explore_{unit}.parquet")
    if unit == "song":
        bets = bets.rename({"item": "recording"}).with_columns(item=pl.col("recording"))
        on = ["user", "recording"]
    else:
        on = ["user", "artist"]
    df = bets.join(obs, on=on, how="left").with_columns(pl.col("plays_to_commit").fill_null(1))
    # Popularity rank among all bets that month (0 = least popular), and the breakout flag.
    return df.with_columns(pq=pl.col("pen0").rank("average").over("m") / pl.len().over("m"),
                           brk=(pl.col("v") >= BREAKOUT).cast(pl.Float64)), unit


def select(df, U, C):
    d = df.filter(pl.col("pq") <= U)
    if C < 1.0:
        d = d.with_columns(r=pl.col("plays_to_commit").rank("ordinal", descending=True).over("user") / pl.len().over("user"))
        d = d.filter(pl.col("r") <= C).drop("r")
    return d


def write_cand(name, d, key):
    out = CAND / name
    out.mkdir(parents=True, exist_ok=True)
    d = d.with_columns(year=(pl.col("m") // 12).cast(pl.Int16), half=(pl.col("item").hash() % 2).cast(pl.Int8))
    agg = d.group_by("user", "year", "half").agg(n=pl.len(), sw=pl.len().cast(pl.Float64), swe=pl.col("e").sum(),
                                                 swe2=(pl.col("e") ** 2).sum())
    cells = d.select("user", "year", "half", "m", "bin", "e")
    for k in range(K):
        sh = cells.with_columns(ep=pl.col("e").shuffle(seed=int(RNG.integers(1 << 30))).over("m", "bin"))
        p = sh.group_by("user", "year", "half").agg(pl.col("ep").sum().alias(f"swe_p{k}"))
        agg = agg.join(p, on=["user", "year", "half"])
    agg.write_parquet(out / "agg.parquet")
    (out / "meta.json").write_text(json.dumps({"name": name, "model": key.split("_")[0], "unit": key.split("_")[1],
                                               "horizon": 12, "half": "explore", "bets": d.height,
                                               "users_with_bets": d["user"].n_unique()}))
    subprocess.run([sys.executable, "-I", str(ROOT / "analysis" / "evaluate.py"), name], check=True, capture_output=True)
    return json.loads((out / "scorecard.json").read_text())


def breakout_forward(df_all, d, min_past=5, min_fut=5):
    """Forward test in breakout units: top/bottom fifth by past score; their later picks' breakout rates."""
    exp = df_all.group_by("m", "bin").agg(exp_brk=pl.col("brk").mean())
    d = d.join(exp, on=["m", "bin"]).with_columns(year=(pl.col("m") // 12))
    rows = []
    for cut in (2007, 2008, 2009, 2010):
        past = d.filter(pl.col("year") <= cut).group_by("user").agg(s=pl.col("e").mean(), n=pl.len()).filter(pl.col("n") >= min_past)
        fut = d.filter(pl.col("year").is_between(cut + 2, cut + 3))
        nf = fut.group_by("user").agg(nf=pl.len()).filter(pl.col("nf") >= min_fut)
        past = past.join(nf, on="user").with_columns(rk=pl.col("s").rank("average") / pl.len())
        f = fut.join(past.select("user", "rk"), on="user")
        rows.append(f.with_columns(grp=pl.when(pl.col("rk") > 0.8).then(pl.lit("top")).when(pl.col("rk") <= 0.2)
                                   .then(pl.lit("bottom")).otherwise(pl.lit("middle"))))
    f = pl.concat(rows)
    users = f["user"].unique()
    res = {}
    for g in ("top", "bottom", "middle"):
        x = f.filter(pl.col("grp") == g)
        res[g] = {"breakout_rate": float(x["brk"].mean()), "comparable_rate": float(x["exp_brk"].mean()), "bets": x.height}
    # Bootstrap the top/bottom breakout ratio over people.
    per = f.filter(pl.col("grp").is_in(["top", "bottom"])).group_by("user", "grp").agg(b=pl.col("brk").sum(), n=pl.len())
    tops, bots = per.filter(pl.col("grp") == "top"), per.filter(pl.col("grp") == "bottom")
    ratios = []
    for _ in range(200):
        wt = RNG.poisson(1.0, tops.height); wb = RNG.poisson(1.0, bots.height)
        rt = (wt * tops["b"].to_numpy()).sum() / max((wt * tops["n"].to_numpy()).sum(), 1)
        rb = (wb * bots["b"].to_numpy()).sum() / max((wb * bots["n"].to_numpy()).sum(), 1)
        ratios.append(rt / rb if rb > 0 else np.nan)
    res["top_over_bottom"] = res["top"]["breakout_rate"] / res["bottom"]["breakout_rate"]
    res["top_over_bottom_ci"] = [float(np.nanpercentile(ratios, 2.5)), float(np.nanpercentile(ratios, 97.5))]
    res["people"] = int(users.len())
    return res


def main():
    summary = []
    for key in ("A_artist", "A_song", "D_artist", "D_song"):
        df, unit = load(key)
        for U, C in GRID:
            name = f"uc_{key}_U{int(U * 100)}_C{int(C * 100)}"
            d = select(df, U, C)
            sc = write_cand(name, d, key)
            row = {"candidate": name, "key": key, "U": U, "C": C, "bets": d.height,
                   "people_scored": sc["users_scored"], "adj_forward": sc.get("headline_adjusted_forward"),
                   "adj_forward_ci": sc.get("headline_adjusted_forward_ci"),
                   "repeat_top20": sc.get("forward", {}).get("repeat_rate_top20"),
                   "stability_3y": sc.get("stability_3y_corrected"), "reliability": sc.get("reliability"),
                   "impostor_r2": sc.get("impostor_r2")}
            if key.startswith("A"):
                row["breakout"] = breakout_forward(df, d)
            summary.append(row)
            b = row.get("breakout")
            print(f"{name:26s} bets {d.height:>10,} people {row['people_scored']:>7,} adj {row['adj_forward'] or float('nan'):.3f} "
                  f"repeat {row['repeat_top20'] or float('nan'):.2f}" +
                  (f"  breakout top {b['top']['breakout_rate']:.1%} / bottom {b['bottom']['breakout_rate']:.1%} / comparable "
                   f"{b['top']['comparable_rate']:.1%}  ratio {b['top_over_bottom']:.2f} [{b['top_over_bottom_ci'][0]:.2f}, "
                   f"{b['top_over_bottom_ci'][1]:.2f}]" if b else ""), flush=True)
    (ROOT / "analysis" / "out" / "underground.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
