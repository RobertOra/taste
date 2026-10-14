"""How much does taste matter? The taste ladder and the good-picker curve (post-freeze; one run per half).

Ladder: people rated on their artist picks up to cutoff C (2007..2009; frozen prescience score, shrunk sum e/(n+20),
  >= 20 picks), ranked into percentile bands, finer at the top. Outcome: their picks made in C+2..C+3, chance of growing
  10x (and 4x) in a year vs similar picks (same month and size), plus growth vs similar. 95% intervals: bootstrap over
  people (1,000 draws; a person rated at several cutoffs is resampled as one).
Good-picker curve (analysis/pickers.py data): artist-months by the number of good pickers among new fans (0, 1, 2, ...),
  compared with artists of the same month, size, momentum, and numbers of ordinary, poor, and unrated new fans. Growth
  among the outcome group only; bootstrap over artists.
Count vs share: one model with each good fan, each ordinary fan, and the share of rated new fans who are good.
Crowding curve: the good-picker curve with the exact numbers of ordinary and poor new fans held fixed (cells: month, size,
  momentum, unrated new fans, exact ordinary count, exact poor count; cells with only one good-picker count dropped), split
  by how crowded the artist is: niche (0-2 other rated new fans), middle (3-5), crowded (6+). Each count shown while it has
  >= 300 artist-months; the rest pooled. Per-picker slope in each group: least squares of growth on good pickers (capped
  at 6) within cells; bootstrap over artists.

Usage: ladder.py --half explore|sealed
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
RNG = np.random.default_rng(1009)
B = 1000
EDGES = [0, .1, .2, .3, .4, .5, .6, .7, .8, .85, .9, .93, .95, .97, .98, .99, .995, .998, .999, 1.0001]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def ladder(half):
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "m", "bin", "v", "e"])
    b = b.with_columns(year=pl.col("m") // 12, x10=(pl.col("v") >= np.log(10)).cast(pl.Float64),
                       x4=(pl.col("v") >= np.log(4)).cast(pl.Float64))
    exp = b.group_by("m", "bin").agg(ve=pl.col("v").mean(), s10=pl.col("x10").mean(), s4=pl.col("x4").mean())
    parts = []
    for c in cuts(half):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user").with_columns(cut=pl.lit(c)))
    f = pl.concat(parts).join(exp, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    rows = []
    for lo, hi in zip(EDGES[:-1], EDGES[1:]):
        d = f.filter((pl.col("q") > lo) & (pl.col("q") <= hi))
        per = d.group_by("user").agg(n=pl.len(), g=pl.col("gx").sum(), h10=pl.col("x10").sum(), e10=pl.col("s10").sum(),
                                     h4=pl.col("x4").sum(), e4=pl.col("s4").sum(), k=pl.col("cut").n_unique())
        A = {k: per[k].to_numpy().astype(float) for k in ("n", "g", "h10", "e10", "h4", "e4")}
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        r10, r4 = (w @ A["h10"]) / (w @ A["e10"]), (w @ A["h4"]) / (w @ A["e4"])
        gb = np.expm1((w @ A["g"]) / (w @ A["n"]))
        top = 1 - min(hi, 1.0)
        rows.append({"band": f"{lo * 100:g}–{min(hi, 1) * 100:g}%", "lo_pct": lo, "hi_pct": min(hi, 1.0),
                     "top_share_lo": top, "top_share_hi": 1 - lo, "people": per.height, "picks": int(A["n"].sum()),
                     "events_10x": int(A["h10"].sum()), "odds_10x": float(A["h10"].sum() / A["e10"].sum()),
                     "odds_10x_lo": pct(r10, 2.5), "odds_10x_hi": pct(r10, 97.5), "odds_10x_lo99": pct(r10, 0.5),
                     "odds_4x": float(A["h4"].sum() / A["e4"].sum()), "odds_4x_lo": pct(r4, 2.5), "odds_4x_hi": pct(r4, 97.5),
                     "growth": float(np.expm1(A["g"].sum() / A["n"].sum())), "growth_lo": pct(gb, 2.5), "growth_hi": pct(gb, 97.5),
                     "_boot10": r10})
    # Steepness: top 1% vs the 90-95% band, same bootstrap draws are independent groups, so compare by draw.
    top1 = [r for r in rows if r["lo_pct"] >= 0.99]
    per_top = f.filter(pl.col("q") > 0.99).group_by("user").agg(h10=pl.col("x10").sum(), e10=pl.col("s10").sum())
    per_mid = f.filter((pl.col("q") > 0.90) & (pl.col("q") <= 0.95)).group_by("user").agg(h10=pl.col("x10").sum(), e10=pl.col("s10").sum())
    wt = RNG.poisson(1.0, (B, per_top.height)); wm = RNG.poisson(1.0, (B, per_mid.height))
    rt = (wt @ per_top["h10"].to_numpy()) / (wt @ per_top["e10"].to_numpy())
    rm = (wm @ per_mid["h10"].to_numpy()) / (wm @ per_mid["e10"].to_numpy())
    summary = {"top1_odds_10x": float(per_top["h10"].sum() / per_top["e10"].sum()), "top1_lo": pct(rt, 2.5), "top1_hi": pct(rt, 97.5),
               "top1_lo99": pct(rt, 0.5), "top1_people": per_top.height, "top1_events": int(per_top["h10"].sum()),
               "top1_vs_90_95": float((per_top["h10"].sum() / per_top["e10"].sum()) / (per_mid["h10"].sum() / per_mid["e10"].sum())),
               "top1_vs_90_95_lo": pct(rt / rm, 2.5), "top1_vs_90_95_hi": pct(rt / rm, 97.5), "top1_vs_90_95_lo99": pct(rt / rm, 0.5)}
    for r in rows:
        r.pop("_boot10")
    del top1
    return rows, summary


def good_curve(half):
    df = pl.read_parquet(X / "pickers" / f"rate_A_{half}.parquet")
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), ob=pl.col("n_ord").clip(0, 6), pb=pl.col("n_poor").clip(0, 3))
    df = df.with_columns(x4=(pl.col("g") >= np.log(4)).cast(pl.Float64), x10=(pl.col("g") >= np.log(10)).cast(pl.Float64))
    cell = ["m", "sz", "mo", "ub", "ob", "pb"]
    df = df.with_columns(cs=pl.len().over(cell)).filter(pl.col("cs") >= 2)
    for v in ("g", "x4"):
        df = df.with_columns(((pl.col(v).sum().over(cell) - pl.col(v)) / (pl.col("cs") - 1)).alias(v + "_e"))
    df = df.with_columns(gx=pl.col("g") - pl.col("g_e"))
    counts = df.group_by("n_good").agg(n=pl.len()).sort("n_good")
    # Go up one good picker at a time while each count has >= 300 artist-months; pool the rest.
    kmax = 0
    for k, n in zip(counts["n_good"], counts["n"]):
        if n >= 300 and k == kmax + (0 if k == 0 else 1):
            kmax = k
        elif k > 0:
            break
    df = df.with_columns(G=pl.col("n_good").clip(0, kmax + 1))
    a = df.group_by("artist", "G").agg(s=pl.col("gx").sum(), n=pl.len(), o4=pl.col("x4").sum(), e4=pl.col("x4_e").sum())
    rows = []
    for G in range(0, kmax + 2):
        x = a.filter(pl.col("G") == G)
        if x.height == 0:
            continue
        s, n, o4, e4 = (x[c].to_numpy().astype(float) for c in ("s", "n", "o4", "e4"))
        w = RNG.poisson(1.0, (B, x.height)).astype(float)
        gb = np.expm1((w @ s) / (w @ n))
        rows.append({"good": G, "label": f"{G}+" if G == kmax + 1 else str(G), "artist_months": int(n.sum()),
                     "growth": float(np.expm1(s.sum() / n.sum())), "growth_lo": pct(gb, 2.5), "growth_hi": pct(gb, 97.5),
                     "takeoff4": float(o4.sum() / n.sum()), "takeoff4_similar": float(e4.sum() / n.sum())})
    return rows


def count_vs_share(half):
    df = pl.read_parquet(X / "pickers" / f"rate_A_{half}.parquet")
    df = df.with_columns(n_rated=pl.col("n_good") + pl.col("n_poor") + pl.col("n_ord")).filter(pl.col("n_rated") >= 1)
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), share=pl.col("n_good") / pl.col("n_rated"))
    cell = ["m", "sz", "mo", "ub"]
    cols = ["n_good", "n_ord", "n_poor", "share"]
    for v in ["g"] + cols:
        df = df.with_columns((pl.col(v) - pl.col(v).mean().over(cell)).alias(v + "_d"))
    Xm = df.select([c + "_d" for c in cols]).to_numpy(); y = df["g_d"].to_numpy()
    est = np.linalg.lstsq(Xm, y, rcond=None)[0]
    ua, inv = np.unique(df["artist"].to_numpy(), return_inverse=True)
    bs = []
    for _ in range(300):
        w = np.sqrt(RNG.poisson(1.0, len(ua))[inv].astype(float))
        bs.append(np.linalg.lstsq(Xm * w[:, None], y * w, rcond=None)[0])
    bs = np.array(bs)
    out = {c: {"effect": float(np.expm1(est[i])), "lo": float(np.expm1(pct(bs[:, i], 2.5))), "hi": float(np.expm1(pct(bs[:, i], 97.5))),
               "lo99": float(np.expm1(pct(bs[:, i], 0.5)))} for i, c in enumerate(cols)}
    diff = bs[:, 0] - bs[:, 1]
    out["good_minus_ordinary"] = {"effect": float(est[0] - est[1]), "lo": pct(diff, 2.5), "hi": pct(diff, 97.5), "lo99": pct(diff, 0.5)}
    return out


def crowd_curve(half, df=None):   # df: an alternative new-fans table with the same columns (song_pickers.py)
    df = pl.read_parquet(X / "pickers" / f"rate_A_{half}.parquet") if df is None else df
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), others=pl.col("n_ord") + pl.col("n_poor"))
    cell = ["m", "sz", "mo", "ub", "n_ord", "n_poor"]
    df = df.with_columns(cs=pl.len().over(cell), cg=pl.col("n_good").n_unique().over(cell)).filter((pl.col("cs") >= 2) & (pl.col("cg") >= 2))
    df = df.with_columns(gx=pl.col("g") - (pl.col("g").sum().over(cell) - pl.col("g")) / (pl.col("cs") - 1),
                         grp=pl.when(pl.col("others") <= 2).then(pl.lit("niche")).when(pl.col("others") <= 5).then(pl.lit("middle"))
                         .otherwise(pl.lit("crowded")), Gc=pl.col("n_good").clip(0, 6).cast(pl.Float64))
    df = df.with_columns(Gd=pl.col("Gc") - pl.col("Gc").mean().over(cell), yd=pl.col("g") - pl.col("g").mean().over(cell))
    rows, slopes, boots = [], {}, {}
    for grp in ("niche", "middle", "crowded"):
        d = df.filter(pl.col("grp") == grp)
        counts = d.group_by("n_good").agg(n=pl.len()).sort("n_good")
        kmax = 0
        for k, n in zip(counts["n_good"], counts["n"]):
            if k == kmax + 1 and n >= 300:
                kmax = k
            elif k > kmax + 1 or (k == kmax + 1 and n < 300):
                break
        d = d.with_columns(G=pl.col("n_good").clip(0, kmax + 1))
        a = d.group_by("artist", "G").agg(s=pl.col("gx").sum(), n=pl.len())
        for G in range(0, kmax + 2):
            x = a.filter(pl.col("G") == G)
            if x.height == 0:
                continue
            sv, nv = x["s"].to_numpy().astype(float), x["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (B, x.height)).astype(float)
            gb = np.expm1((w @ sv) / (w @ nv))
            rows.append({"crowd": grp, "good": G, "label": f"{G}+" if G == kmax + 1 else str(G), "artist_months": int(nv.sum()),
                         "growth": float(np.expm1(sv.sum() / nv.sum())), "growth_lo": pct(gb, 2.5), "growth_hi": pct(gb, 97.5)})
        ua, inv = np.unique(d["artist"].to_numpy(), return_inverse=True)
        xg, yg = d["Gd"].to_numpy(), d["yd"].to_numpy()
        slopes[grp] = float((xg @ yg) / (xg @ xg))
        bb = []
        for _ in range(B):
            w = RNG.poisson(1.0, len(ua))[inv].astype(float)
            bb.append(((w * xg) @ yg) / ((w * xg) @ xg))
        boots[grp] = np.array(bb)
    # Niche: 2 good pickers vs none (difference in growth vs similar), bootstrap over artists.
    nd = df.filter(pl.col("grp") == "niche")
    a = nd.filter(pl.col("n_good").is_in([0, 2])).group_by("artist", "n_good").agg(s=pl.col("gx").sum(), n=pl.len())
    a2, a0 = a.filter(pl.col("n_good") == 2), a.filter(pl.col("n_good") == 0)
    w2 = RNG.poisson(1.0, (B, a2.height)).astype(float); w0 = RNG.poisson(1.0, (B, a0.height)).astype(float)
    dd = (w2 @ a2["s"].to_numpy()) / (w2 @ a2["n"].to_numpy()) - (w0 @ a0["s"].to_numpy()) / (w0 @ a0["n"].to_numpy())
    est = a2["s"].sum() / a2["n"].sum() - a0["s"].sum() / a0["n"].sum()
    sd = boots["niche"] - boots["crowded"]
    summ = {"slopes": {g: {"per_picker": float(np.expm1(slopes[g])), "lo": float(np.expm1(pct(boots[g], 2.5))),
                           "hi": float(np.expm1(pct(boots[g], 97.5)))} for g in slopes},
            "niche_2_vs_0": float(np.expm1(est)), "niche_2_vs_0_lo": float(np.expm1(pct(dd, 2.5))), "niche_2_vs_0_hi": float(np.expm1(pct(dd, 97.5))),
            "niche_2_vs_0_lo99": float(np.expm1(pct(dd, 0.5))),
            "slope_niche_minus_crowded": float(slopes["niche"] - slopes["crowded"]), "slope_diff_lo": pct(sd, 2.5),
            "slope_diff_hi": pct(sd, 97.5), "slope_diff_lo99": pct(sd, 0.5)}
    return rows, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    rows, summ = ladder(half)
    print(f"LADDER [{half}]")
    for r in rows:
        print(f"  {r['band']:>12} people {r['people']:>6,} 10x events {r['events_10x']:>6,}  10x odds {r['odds_10x']:.2f} [{r['odds_10x_lo']:.2f}, {r['odds_10x_hi']:.2f}]"
              f"  4x {r['odds_4x']:.2f}  growth {r['growth']:+.1%}")
    print(f"  top 1%: {summ['top1_odds_10x']:.2f} [{summ['top1_lo']:.2f}, {summ['top1_hi']:.2f}; 99% low {summ['top1_lo99']:.2f}]"
          f"  vs 90-95% band: {summ['top1_vs_90_95']:.2f} [{summ['top1_vs_90_95_lo']:.2f}, {summ['top1_vs_90_95_hi']:.2f}; 99% low {summ['top1_vs_90_95_lo99']:.2f}]")
    gc = good_curve(half)
    print(f"\nGOOD-PICKER CURVE [{half}] (vs similar artists with the same ordinary/poor/unrated new fans)")
    for r in gc:
        print(f"  {r['label']:>3} good: n {r['artist_months']:>9,}  growth {r['growth']:+.1%} [{r['growth_lo']:+.1%}, {r['growth_hi']:+.1%}]"
              f"  grew 4x {r['takeoff4']:.1%} (similar {r['takeoff4_similar']:.1%})")
    cs = count_vs_share(half)
    print(f"\nCOUNT VS SHARE [{half}]")
    for k, v in cs.items():
        print(f"  {k:20s} {v['effect']:+.2%} [{v['lo']:+.2%}, {v['hi']:+.2%}; 99% low {v['lo99']:+.2%}]")
    cr, crs = crowd_curve(half)
    print(f"\nCROWDING CURVE [{half}] (exact ordinary and poor new fans held fixed)")
    for r in cr:
        print(f"  {r['crowd']:8s} {r['label']:>3} good: n {r['artist_months']:>9,}  growth {r['growth']:+.1%} [{r['growth_lo']:+.1%}, {r['growth_hi']:+.1%}]")
    for g, v in crs["slopes"].items():
        print(f"  per good picker, {g:8s}: {v['per_picker']:+.2%} [{v['lo']:+.2%}, {v['hi']:+.2%}]")
    print(f"  niche, 2 good vs none: {crs['niche_2_vs_0']:+.1%} [{crs['niche_2_vs_0_lo']:+.1%}, {crs['niche_2_vs_0_hi']:+.1%}; 99% low {crs['niche_2_vs_0_lo99']:+.1%}]")
    print(f"  slope niche minus crowded: {crs['slope_niche_minus_crowded']:+.4f} [{crs['slope_diff_lo']:+.4f}, {crs['slope_diff_hi']:+.4f}; 99% low {crs['slope_diff_lo99']:+.4f}]")
    (ROOT / "analysis" / "out" / f"ladder_{half}.json").write_text(json.dumps({"ladder": rows, "summary": summ, "good_curve": gc,
                                                                               "count_vs_share": cs, "crowd_curve": cr,
                                                                               "crowd_summary": crs}, indent=1))


if __name__ == "__main__":
    main()
