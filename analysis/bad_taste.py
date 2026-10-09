"""Is bad taste real too? (post-freeze; one run per half)

Ladder design (analysis/ladder.py): people rated on artist picks up to cutoff C (2007..2009; frozen prescience score,
shrunk, >= 20 picks), banded by rank; their picks made in C+2..C+3. Compared with similar picks (same month and size):
- growth: average growth vs similar;
- flops: share of picks that lost at least half their listeners within a year ((l1+1)/(l0+1) <= 1/2), vs similar; because
  rated people's picks flop slightly more than all picks, flop comparisons for groups are made against the middle fifth
  (40-60%) of rated pickers;
- takeoffs: share that grew tenfold, vs similar.
Persistence of bad taste: the frozen discernment-for-songs forward test (evaluate.py design), share of the bottom fifth
still in the bottom fifth 2+ years later, next to the top fifth's repeat rate.
Bootstrap over people (1,000 draws).

Usage: bad_taste.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
RNG = np.random.default_rng(1313)
B = 1000
BANDS = [("0–5", 0, .05), ("5–10", .05, .1), ("10–20", .1, .2), ("20–30", .2, .3), ("30–40", .3, .4), ("40–50", .4, .5), ("50–60", .5, .6),
         ("60–70", .6, .7), ("70–80", .7, .8), ("80–90", .8, .9), ("90–95", .9, .95), ("95–100", .95, 1.0001)]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    b = b.with_columns(flop=(pl.col("v") <= np.log(0.5)).cast(pl.Float64), x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    exp = b.group_by("m", "bin").agg(ve=pl.col("v").mean(), sf=pl.col("flop").mean(), s10=pl.col("x10").mean())
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user"))
    f = pl.concat(parts).join(exp, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    bands = []
    for lab, lo, hi in BANDS:
        per = f.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(
            n=pl.len(), g=pl.col("gx").sum(), fl=pl.col("flop").sum(), ef=pl.col("sf").sum(), h=pl.col("x10").sum(), eh=pl.col("s10").sum())
        A = {k: per[k].to_numpy().astype(float) for k in ("n", "g", "fl", "ef", "h", "eh")}
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        gb, fb, hb = np.expm1((w @ A["g"]) / (w @ A["n"])), (w @ A["fl"]) / (w @ A["ef"]), (w @ A["h"]) / (w @ A["eh"])
        bands.append({"key": lab, "band": f"{lab}%", "mid": (lo + min(hi, 1)) / 2 * 100, "people": per.height,
                      "growth": float(np.expm1(A["g"].sum() / A["n"].sum())), "growth_lo": pct(gb, 2.5), "growth_hi": pct(gb, 97.5),
                      "flop_rate": float(A["fl"].sum() / A["n"].sum()), "flop_similar": float(A["ef"].sum() / A["n"].sum()),
                      "flop_odds": float(A["fl"].sum() / A["ef"].sum()), "flop_lo": pct(fb, 2.5), "flop_hi": pct(fb, 97.5),
                      "takeoff_odds": float(A["h"].sum() / A["eh"].sum()), "takeoff_lo": pct(hb, 2.5), "takeoff_hi": pct(hb, 97.5)})

    def group(lo, hi):
        return f.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(
            n=pl.len(), g=pl.col("gx").sum(), fl=pl.col("flop").sum(), ef=pl.col("sf").sum())
    bot, top, allp, mid = group(0, .2), group(.8, 1.0001), group(0, 1.0001), group(.4, .6)
    wb, wt, wa, wm = (RNG.poisson(1.0, (B, x.height)).astype(float) for x in (bot, top, allp, mid))
    mean = lambda x, w, a, b_: (w @ x[a].to_numpy()) / (w @ x[b_].to_numpy())
    bot_flop = mean(bot, wb, "fl", "ef") / mean(mid, wm, "fl", "ef")
    top_flop = mean(top, wt, "fl", "ef") / mean(mid, wm, "fl", "ef")
    g_bot, g_top, g_all = mean(bot, wb, "g", "n"), mean(top, wt, "g", "n"), mean(allp, wa, "g", "n")
    asym = (g_top - g_all) - (g_all - g_bot)
    pe = lambda x, a, b_: x[a].sum() / x[b_].sum()
    tests = {"P11a_bottom_flop_vs_middle": {"est": float(pe(bot, "fl", "ef") / pe(mid, "fl", "ef")), "lo": pct(bot_flop, 2.5), "hi": pct(bot_flop, 97.5), "lo99": pct(bot_flop, 0.5)},
             "P11c_top_flop_vs_middle": {"est": float(pe(top, "fl", "ef") / pe(mid, "fl", "ef")), "lo": pct(top_flop, 2.5), "hi": pct(top_flop, 97.5), "lo99": pct(top_flop, 0.5)},
             "P11b_asymmetry": {"top_minus_all": float(pe(top, "g", "n") - pe(allp, "g", "n")), "all_minus_bottom": float(pe(allp, "g", "n") - pe(bot, "g", "n")),
                                "est": float((pe(top, "g", "n") - pe(allp, "g", "n")) - (pe(allp, "g", "n") - pe(bot, "g", "n"))),
                                "lo": pct(asym, 2.5), "hi": pct(asym, 97.5), "lo99": pct(asym, 0.5)}}

    # descriptive: what happened to each group's new artists (rates, with similar artists' rates)
    groups = []
    f2 = f.with_columns(dbl=(pl.col("v") >= np.log(2)).cast(pl.Float64))
    sd = b.with_columns(dbl=(pl.col("v") >= np.log(2)).cast(pl.Float64)).group_by("m", "bin").agg(sd=pl.col("dbl").mean())
    f2 = f2.join(sd, on=["m", "bin"])
    for lab, lo, hi in (("worst10", 0, .1), ("worst", 0, .2), ("middle", .4, .6), ("best", .8, 1.0001), ("best10", .9, 1.0001)):
        per = f2.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(
            n=pl.len(), fl=pl.col("flop").sum(), ef=pl.col("sf").sum(), db=pl.col("dbl").sum(), ed=pl.col("sd").sum())
        A = {k: per[k].to_numpy().astype(float) for k in ("n", "fl", "ef", "db", "ed")}
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        fr, dr = (w @ A["fl"]) / (w @ A["n"]), (w @ A["db"]) / (w @ A["n"])
        groups.append({"key": lab, "people": per.height, "flop": float(A["fl"].sum() / A["n"].sum()), "flop_lo": pct(fr, 2.5), "flop_hi": pct(fr, 97.5),
                       "flop_similar": float(A["ef"].sum() / A["n"].sum()), "double": float(A["db"].sum() / A["n"].sum()),
                       "double_lo": pct(dr, 2.5), "double_hi": pct(dr, 97.5), "double_similar": float(A["ed"].sum() / A["n"].sum())})

    # persistence (frozen discernment-for-songs candidate of this half)
    name = ("sealed_" if half == "sealed" else "") + "D_song_main"
    agg = pl.read_parquet(CAND / name / "agg.parquet")
    years = sorted(agg["year"].unique().to_list())
    per = lambda dd: dd.group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    st, sb, nt, nb = 0, 0, 0, 0
    for cut in [y for y in years if y + 2 in years and y >= 2006]:
        past = per(agg.filter(pl.col("year") <= cut)).filter(pl.col("n") >= 10)
        fut = per(agg.filter(pl.col("year").is_between(cut + 2, cut + 3))).filter(pl.col("n") >= 10)
        j = past.select("user", p=pl.col("swe") / pl.col("sw")).join(fut.select("user", f=pl.col("swe") / pl.col("sw")), on="user")
        if j.height < 500:
            continue
        j = j.with_columns(q=pl.col("p").rank("average") / pl.len(), rf=pl.col("f").rank("average") / pl.len())
        t, bb = j.filter(pl.col("q") > .8), j.filter(pl.col("q") <= .2)
        st += int((t["rf"] > .8).sum()); nt += t.height; sb += int((bb["rf"] <= .2).sum()); nb += bb.height
    persistence = {"top_stays_top": st / nt, "bottom_stays_bottom": sb / nb, "chance": 0.2}
    for r in bands:
        print(f"  {r['band']:>8} people {r['people']:>6,}  growth {r['growth']:+6.1%}  flops {r['flop_rate']:.1%} vs {r['flop_similar']:.1%} "
              f"({r['flop_odds']:.2f}x [{r['flop_lo']:.2f}, {r['flop_hi']:.2f}])  takeoffs {r['takeoff_odds']:.2f}x")
    print(json.dumps(tests, indent=1)); print("persistence:", persistence)
    (ROOT / "analysis" / "out" / f"bad_taste_{half}.json").write_text(json.dumps({"bands": bands, "tests": tests, "persistence": persistence, "groups": groups}, indent=1))


if __name__ == "__main__":
    main()
