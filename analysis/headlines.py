"""Plain-language headline numbers (post-freeze; written to be run once per half).

All growth is fixed-panel listener growth over 12 months with the picker excluded: (l1 + 1) / (l0 + 1).
"Similar picks" = all picks in the same month and popularity bin (the main model's size bins), so every comparison
is against artists of the same size at the same time. Track records use the frozen main prescience score (per-bet
excess e, which already adjusts for scene, age, momentum, country, and release timing), shrunk: sum e / (n + 20),
people with >= 20 picks. Best = top fifth, worst = bottom fifth.

H1  Favorite finds. Cutoff C in 2007..2009: rate people on picks through C. Their picks made in C+2..C+3; each
    person's 10 favorites = the 10 they played most before committing (needs >= 10 picks). Compare best vs worst
    pickers' favorites: rate of 10x and 4x growth, and growth vs similar picks. People appearing at several cutoffs
    count once per cutoff; 95% intervals: bootstrap over people (500 draws).
H2  Several good pickers agree (analysis/pickers.py, rated by prescience): artist-months newly picked by 3+ rated
    pickers who are all good, vs all poor; rates of 4x and 10x vs similar artists (same month x size x momentum x
    number of pickers); bootstrap over artists. Marginal value of one good picker comes from pickers.py.
H3  All picks: best vs worst fifth, 4x rate (the breakout check), same design as H1 without the favorites filter.

Usage: headlines.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutoffs import cuts, picker_cuts, genre_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(2026)
B = 2000
L4, L10 = float(np.log(4)), float(np.log(10))


def boot_ratio(d, col, by="user"):
    """Bootstrap the best/worst ratio of mean(col), resampling people (or artists) within each group."""
    out = []
    g = {k: d.filter(pl.col("grp") == k).group_by(by).agg(s=pl.col(col).sum(), n=pl.len()) for k in ("best", "worst")}
    arr = {k: (v["s"].to_numpy(), v["n"].to_numpy()) for k, v in g.items()}
    for _ in range(B):
        r = {}
        for k, (s, n) in arr.items():
            w = RNG.poisson(1.0, len(s))
            r[k] = (w * s).sum() / max((w * n).sum(), 1)
        out.append(r["best"] / r["worst"] if r["worst"] > 0 else np.nan)
    return [float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5)), float(np.nanpercentile(out, 0.5))]


def boot_diff(d, col, by="user"):
    out = []
    g = {k: d.filter(pl.col("grp") == k).group_by(by).agg(s=pl.col(col).sum(), n=pl.len()) for k in ("best", "worst")}
    arr = {k: (v["s"].to_numpy(), v["n"].to_numpy()) for k, v in g.items()}
    for _ in range(B):
        r = {}
        for k, (s, n) in arr.items():
            w = RNG.poisson(1.0, len(s))
            r[k] = (w * s).sum() / max((w * n).sum(), 1)
        out.append(r["best"] - r["worst"])
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)), float(np.percentile(out, 0.5))]


def summarize(d):
    res = {}
    for k in ("best", "worst"):
        x = d.filter(pl.col("grp") == k)
        res[k] = {"picks": x.height, "people": x["user"].n_unique(),
                  "rate_10x": float(x["x10"].mean()), "rate_10x_similar": float(x["x10_exp"].mean()),
                  "rate_4x": float(x["x4"].mean()), "rate_4x_similar": float(x["x4_exp"].mean()),
                  "growth_vs_similar": float(np.expm1(x["gx"].mean()))}
    res["ratio_10x"] = res["best"]["rate_10x"] / res["worst"]["rate_10x"]
    res["ratio_10x_ci"] = boot_ratio(d, "x10")
    res["ratio_4x"] = res["best"]["rate_4x"] / res["worst"]["rate_4x"]
    res["ratio_4x_ci"] = boot_ratio(d, "x4")
    gd = boot_diff(d, "gx")
    res["growth_gap"] = float(np.expm1(d.filter(pl.col("grp") == "best")["gx"].mean() - d.filter(pl.col("grp") == "worst")["gx"].mean()))
    res["growth_gap_ci"] = [float(np.expm1(gd[0])), float(np.expm1(gd[1]))]
    return res


def h1_h3(half):
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"])
    ob = pl.read_parquet(X / "obsession" / f"{half}_artist.parquet", columns=["user", "artist", "plays_to_commit"])
    b = b.join(ob, on=["user", "artist"], how="left").with_columns(pl.col("plays_to_commit").fill_null(0))
    b = b.with_columns(x4=(pl.col("v") >= L4).cast(pl.Float64), x10=(pl.col("v") >= L10).cast(pl.Float64), year=pl.col("m") // 12)
    exp = b.group_by("m", "bin").agg(v_exp=pl.col("v").mean(), x4_exp=pl.col("x4").mean(), x10_exp=pl.col("x10").mean())
    b = b.join(exp, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("v_exp"))
    fav, allp = [], []
    for c in cuts(half):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        past = past.with_columns(grp=pl.when(pl.col("q") > 0.8).then(pl.lit("best")).when(pl.col("q") <= 0.2)
                                 .then(pl.lit("worst")).otherwise(pl.lit("middle"))).select("user", "grp")
        fut = b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past, on="user").with_columns(cut=pl.lit(c))
        fut = fut.with_columns(user=pl.col("user") * 10 + (c - 2000))  # a person at several cutoffs counts once per cutoff
        allp.append(fut)
        f = fut.with_columns(tie=pl.struct("artist", "m").hash(c),
                             nf=pl.len().over("user")).filter(pl.col("nf") >= 10)
        f = f.sort(["user", "plays_to_commit", "tie"], descending=[False, True, False]).group_by("user", maintain_order=True).head(10)
        fav.append(f)
    return summarize(pl.concat(fav)), summarize(pl.concat(allp))


def h2(half):
    df = pl.read_parquet(X / "pickers" / f"rate_A_{half}.parquet")
    df = df.with_columns(n_rated=pl.col("n_good") + pl.col("n_poor") + pl.col("n_ord")).filter(pl.col("n_rated") >= 1)
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(),
                         sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         nb=pl.col("n_rated").clip(1, 6), ub=pl.col("n_unrated").clip(0, 4))
    df = df.with_columns(x4=(pl.col("g") >= L4).cast(pl.Float64), x10=(pl.col("g") >= L10).cast(pl.Float64))
    cell = ["m", "sz", "mo", "nb", "ub"]
    df = df.with_columns(cs=pl.len().over(cell)).filter(pl.col("cs") >= 2)
    df = df.with_columns([((pl.col(v).sum().over(cell) - pl.col(v)) / (pl.col("cs") - 1)).alias(v + "_exp") for v in ("g", "x4", "x10")])
    df = df.with_columns(gx=pl.col("g") - pl.col("g_exp"), user=pl.col("artist"),
                         grp=pl.when((pl.col("n_rated") >= 3) & (pl.col("n_good") == pl.col("n_rated"))).then(pl.lit("best"))
                         .when((pl.col("n_rated") >= 3) & (pl.col("n_poor") == pl.col("n_rated"))).then(pl.lit("worst"))
                         .otherwise(None)).filter(pl.col("grp").is_not_null())
    res = summarize(df)
    # Against similar artists (not only against the all-poor group): ratio of the all-good group's rate to expected.
    x = df.filter(pl.col("grp") == "best")
    res["best_vs_similar_4x"] = float(x["x4"].mean() / x["x4_exp"].mean())
    res["best_vs_similar_10x"] = float(x["x10"].mean() / x["x10_exp"].mean())
    a = x.group_by("artist").agg(o4=pl.col("x4").sum(), e4=pl.col("x4_exp").sum(), o10=pl.col("x10").sum(), e10=pl.col("x10_exp").sum())
    r4, r10 = [], []
    for _ in range(B):
        w = RNG.poisson(1.0, a.height)
        r4.append((w * a["o4"].to_numpy()).sum() / (w * a["e4"].to_numpy()).sum())
        r10.append((w * a["o10"].to_numpy()).sum() / (w * a["e10"].to_numpy()).sum())
    res["best_vs_similar_4x_ci"] = [float(np.percentile(r4, 2.5)), float(np.percentile(r4, 97.5)), float(np.percentile(r4, 0.5))]
    res["best_vs_similar_10x_ci"] = [float(np.percentile(r10, 2.5)), float(np.percentile(r10, 97.5)), float(np.percentile(r10, 0.5))]
    return res


def show(label, r):
    b, w = r["best"], r["worst"]
    print(f"\n== {label}")
    print(f"  best: {b['picks']:,} picks ({b['people']:,} people/artists)   worst: {w['picks']:,} picks ({w['people']:,})")
    print(f"  10x: best {b['rate_10x']:.2%} (similar {b['rate_10x_similar']:.2%})  worst {w['rate_10x']:.2%} (similar {w['rate_10x_similar']:.2%})"
          f"  ratio {r['ratio_10x']:.2f} [{r['ratio_10x_ci'][0]:.2f}, {r['ratio_10x_ci'][1]:.2f}]")
    print(f"   4x: best {b['rate_4x']:.2%} (similar {b['rate_4x_similar']:.2%})  worst {w['rate_4x']:.2%} (similar {w['rate_4x_similar']:.2%})"
          f"  ratio {r['ratio_4x']:.2f} [{r['ratio_4x_ci'][0]:.2f}, {r['ratio_4x_ci'][1]:.2f}]")
    print(f"  growth vs similar: best {b['growth_vs_similar']:+.1%}  worst {w['growth_vs_similar']:+.1%}  gap {r['growth_gap']:+.1%} "
          f"[{r['growth_gap_ci'][0]:+.1%}, {r['growth_gap_ci'][1]:+.1%}]")
    if "best_vs_similar_4x" in r:
        print(f"  all-good group vs similar artists: 4x {r['best_vs_similar_4x']:.2f}x [{r['best_vs_similar_4x_ci'][0]:.2f}, {r['best_vs_similar_4x_ci'][1]:.2f}], "
              f"10x {r['best_vs_similar_10x']:.2f}x [{r['best_vs_similar_10x_ci'][0]:.2f}, {r['best_vs_similar_10x_ci'][1]:.2f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    fav, allp = h1_h3(half)
    show(f"H1 [{half}] best vs worst pickers' 10 favorite finds", fav)
    show(f"H3 [{half}] best vs worst pickers, all picks", allp)
    m = h2(half)
    show(f"H2 [{half}] artists picked by 3+ good pickers (and nobody else rated) vs 3+ poor pickers", m)
    (ROOT / "analysis" / "out" / f"headlines_{half}.json").write_text(json.dumps({"H1": fav, "H2": m, "H3": allp}, indent=1))


if __name__ == "__main__":
    main()
