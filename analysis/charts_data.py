"""Descriptive chart data from already-confirmed sealed measures (no new tests).

thresholds: per band of pickers (ladder.py design, 12 bands), how many of every 1,000 new artists grew 2x..100x within a
  year, vs similar artists (same month and size).
growth: per band, average growth of their new artists vs similar artists, with 95% intervals (bootstrap over people).
scatter: one dot per listener (hidden half, prescience for artists, rated on picks through 2008, >= 20 picks): earlier
  percentile vs how their new artists in 2010-2011 (>= 10 picks) grew compared with similar artists; plus 5% bands.
repeat: the frozen discernment-for-songs candidate's forward test (evaluate.py design): for each band of earlier rank, the
  average later rank, its middle 50%, and the share in the top fifth later.
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
RNG = np.random.default_rng(3)
BANDS = [("0–10", 0, .1), ("10–20", .1, .2), ("20–30", .2, .3), ("30–40", .3, .4), ("40–50", .4, .5), ("50–60", .5, .6),
         ("60–70", .6, .7), ("70–80", .7, .8), ("80–90", .8, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0001)]
THRESH = [2, 3, 5, 10, 20, 50, 100]


def band_expr(col="q"):
    e = pl.lit(None, pl.String)
    for lab, lo, hi in BANDS:
        e = pl.when((pl.col(col) > lo) & (pl.col(col) <= hi)).then(pl.lit(lab)).otherwise(e)
    return e


def mid(lab):
    lo, hi = next((lo, hi) for l, lo, hi in BANDS if l == lab)
    return (lo + min(hi, 1.0)) / 2 * 100


def ladder_data():
    b = pl.read_parquet(X / "bet_outcomes" / "A_artist_sealed.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", band=band_expr()), on="user"))
    f = pl.concat(parts)
    thr = []
    for t in THRESH:
        lt = float(np.log(t))
        exp = b.group_by("m", "bin").agg(sim=(pl.col("v") >= lt).mean())
        g = f.join(exp, on=["m", "bin"]).with_columns(hit=(pl.col("v") >= lt).cast(pl.Float64))
        for lab, _, _ in BANDS:
            x = g.filter(pl.col("band") == lab)
            thr.append({"key": f"{t}x:{lab}", "fold": t, "band": f"{lab}%", "mid": mid(lab), "events": int(x["hit"].sum()),
                        "per_1000": float(x["hit"].mean() * 1000), "similar_per_1000": float(x["sim"].mean() * 1000),
                        "times_similar": float(x["hit"].mean() / x["sim"].mean())})
    ve = b.group_by("m", "bin").agg(ve=pl.col("v").mean())
    g = f.join(ve, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    gro = []
    for lab, _, _ in BANDS:
        per = g.filter(pl.col("band") == lab).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        s_, n_ = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
        w = RNG.poisson(1.0, (500, per.height)).astype(float)
        bs = np.expm1((w @ s_) / (w @ n_))
        gro.append({"key": lab, "band": f"{lab}%", "mid": mid(lab), "growth": float(np.expm1(s_.sum() / n_.sum())),
                    "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "people": per.height})
    return thr, gro


def repeat_data(name="sealed_D_song_main"):
    agg = pl.read_parquet(CAND / name / "agg.parquet")
    years = sorted(agg["year"].unique().to_list())
    per = lambda d: d.group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    rows = []
    for cut in [y for y in years if y + 2 in years and y >= 2006]:
        past = per(agg.filter(pl.col("year") <= cut)).filter(pl.col("n") >= 10)
        fut = per(agg.filter(pl.col("year").is_between(cut + 2, cut + 3))).filter(pl.col("n") >= 10)
        j = past.select("user", p=pl.col("swe") / pl.col("sw")).join(fut.select("user", f=pl.col("swe") / pl.col("sw")), on="user")
        if j.height < 500:
            continue
        rows.append(j.with_columns(q=pl.col("p").rank("average") / pl.len(), rf=pl.col("f").rank("average") / pl.len()))
    d = pl.concat(rows).with_columns(band=band_expr())
    out = []
    for lab, _, _ in BANDS:
        x = d.filter(pl.col("band") == lab)["rf"].to_numpy() * 100
        out.append({"key": lab, "band": f"{lab}%", "mid": mid(lab), "people": int(len(x)), "later_mean": float(x.mean()),
                    "later_p25": float(np.percentile(x, 25)), "later_p75": float(np.percentile(x, 75)),
                    "later_top_fifth": float((x > 80).mean()), "later_bottom_fifth": float((x <= 20).mean())})
    return out


def scatter(cut=2008):
    b = pl.read_parquet(X / "bet_outcomes" / "A_artist_sealed.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    ve = b.group_by("m", "bin").agg(ve=pl.col("v").mean())
    past = (b.filter(pl.col("year") <= cut).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fut = (b.filter(pl.col("year").is_between(cut + 2, cut + 3)).join(ve, on=["m", "bin"])
           .group_by("user").agg(g=(pl.col("v") - pl.col("ve")).mean(), nf=pl.len()).filter(pl.col("nf") >= 10))
    d = past.join(fut, on="user").with_columns(x=(pl.col("q") * 100).round(2), y=pl.col("g").exp() - 1).sort("user")
    dots = [{"x": float(x), "y": round(float(y), 4)} for x, y in zip(d["x"], d["y"])]
    lines = []
    for lo in range(0, 100, 5):
        sel = d.filter((pl.col("x") > lo) & (pl.col("x") <= lo + 5))
        lines.append({"key": f"b{lo}", "kind": "band", "lo": lo, "mid": lo + 2.5, "people": sel.height, "mean": float(sel["y"].mean()),
                      "median": float(sel["y"].median()), "above_zero": float((sel["y"] > 0).mean())})
    for key, lo, hi in (("bottom10", 0, 10), ("top10", 90, 100), ("all", 0, 100)):
        sel = d.filter((pl.col("x") > lo) & (pl.col("x") <= hi))
        lines.append({"key": key, "kind": "summary", "lo": lo, "mid": None, "people": sel.height, "mean": float(sel["y"].mean()),
                      "median": float(sel["y"].median()), "above_zero": float((sel["y"] > 0).mean())})
    return dots, lines


def scene_split():
    """Hidden half, descriptive: for each band of pickers, 10x odds vs similar size, split into scene choice x picks within scenes."""
    sys.path.insert(0, str(ROOT / "analysis"))
    from explain import bets_with_bands
    b, f = bets_with_bands("sealed")
    sc = pl.read_parquet(X / "scenes_yearly" / "explore.parquet", columns=["artist", "year", "scene_200"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1), x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    e1 = b.group_by("m", "bin").agg(s10=pl.col("x10").mean())
    e2 = b.group_by("m", "bin", "scene_200").agg(s10_sc=pl.col("x10").mean())
    f = (f.filter(pl.col("period") == "future").join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1))
         .join(e1, on=["m", "bin"]).join(e2, on=["m", "bin", "scene_200"]).with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64)))
    rows = []
    f = f.with_columns(band2=pl.when(pl.col("q") <= .25).then(pl.lit("0–25")).when(pl.col("q") <= .5).then(pl.lit("25–50")).otherwise(pl.col("band")))
    for lab, lo, hi in (("0–25", 0, .25), ("25–50", .25, .5), ("50–75", .5, .75), ("75–90", .75, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0)):
        per = f.filter(pl.col("band2") == lab).group_by("user").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), es=pl.col("s10_sc").sum())
        h, e, es = (per[c].to_numpy().astype(float) for c in ("h", "e", "es"))
        w = RNG.poisson(1.0, (500, per.height)).astype(float)
        sq, ws = (w @ es) / (w @ e), (w @ h) / (w @ es)
        rows.append({"key": lab, "band": f"{lab}%", "mid": (lo + hi) / 2 * 100, "people": per.height, "total": float(h.sum() / e.sum()),
                     "scenes": float(es.sum() / e.sum()), "scenes_lo": float(np.percentile(sq, 2.5)), "scenes_hi": float(np.percentile(sq, 97.5)),
                     "artists": float(h.sum() / es.sum()), "artists_lo": float(np.percentile(ws, 2.5)), "artists_hi": float(np.percentile(ws, 97.5))})
    return rows


if __name__ == "__main__":
    W = ROOT / "analysis" / "writeup"
    if "--scene-split" in sys.argv:
        rows = scene_split()
        (W / "scenesplit.json").write_text(json.dumps(rows, indent=1))
        for r in rows:
            print(f"  {r['band']:>8}: scenes {r['scenes']:.2f} x artists {r['artists']:.2f} = {r['total']:.2f}")
        raise SystemExit
    dots, lines = scatter()
    (W / "scatter.json").write_text(json.dumps(dots, separators=(",", ":")))
    (W / "scatterline.json").write_text(json.dumps(lines, indent=1))
    print("scatter", len(dots), "dots;", [(r["key"], round(r["mean"], 3), round(r["above_zero"], 2)) for r in lines if r["kind"] == "summary"])
    if "--scatter-only" in sys.argv:
        raise SystemExit
    thr, gro = ladder_data()
    rep = repeat_data()
    for name, rows in (("thresholds", thr), ("growthband", gro), ("repeat", rep)):
        (W / f"{name}.json").write_text(json.dumps(rows, indent=1))
    for r in rep:
        print(f"  {r['band']:>8} n {r['people']:>6} later mean {r['later_mean']:.0f} (mid 50% {r['later_p25']:.0f}-{r['later_p75']:.0f}) top fifth later {r['later_top_fifth']:.0%}")
    for r in gro:
        print(f"  {r['band']:>8} growth {r['growth']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}]")
