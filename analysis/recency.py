"""Recent form vs history: does taste drift? (post-freeze; one run per half)

Artist picks, frozen prescience score (per-bet excess e), shrunk per person: sum e / (n + 20), >= 20 picks per period.
Outcome: later picks' 10x takeoffs vs similar artists (same month and size), and growth vs similar.
- Old vs recent: rated separately on 2005-06 (old) and 2007-08 (recent); fifths of each; judged on 2010-11 picks (>= 10).
  P10a: (recent top fifth, old bottom fifth) beats (old top fifth, recent bottom fifth): ratio of 10x odds > 1.
  P10b: the recent record separates people more than the old one: average over old fifths of log(odds recent top /
        recent bottom) minus average over recent fifths of log(odds old top / old bottom) > 0.
- Going stale: top 10% rated on a single year (2006 or 2007, >= 20 picks), the same people judged on each later year
  (>= 10 picks in every later year through 2011). P10c: odds 2 years later / odds 4 years later > 1 (pooled 2006, 2007).
Bootstrap over people (1,000 draws).

Usage: recency.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1212)
B = 1000
FIFTHS = ("top", "middle", "bottom")


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    exp = b.group_by("m", "bin").agg(ve=pl.col("v").mean(), s10=pl.col("x10").mean())
    yr = (b.join(exp, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
          .group_by("user", "year").agg(s=pl.col("e").sum(), n=pl.len(), h=pl.col("x10").sum(), ex=pl.col("s10").sum(), g=pl.col("gx").sum()))

    # --- old vs recent
    def rate(lo, hi):
        return (yr.filter(pl.col("year").is_between(lo, hi)).group_by("user")
                .agg(s=pl.col("s").sum() / (pl.col("n").sum() + 20), n=pl.col("n").sum()).filter(pl.col("n") >= 20))
    fut = (yr.filter(pl.col("year").is_between(2010, 2011)).group_by("user")
           .agg(h=pl.col("h").sum(), ex=pl.col("ex").sum(), g=pl.col("g").sum(), n=pl.col("n").sum()).filter(pl.col("n") >= 10))
    d = rate(2005, 2006).rename({"s": "s1", "n": "n1"}).join(rate(2007, 2008).rename({"s": "s2", "n": "n2"}), on="user").join(fut, on="user")
    N = d.height
    d = d.with_columns(q1=pl.col("s1").rank("average") / N, q2=pl.col("s2").rank("average") / N)
    lab = lambda c: pl.when(pl.col(c) > 0.8).then(pl.lit("top")).when(pl.col(c) <= 0.2).then(pl.lit("bottom")).otherwise(pl.lit("middle"))
    d = d.with_columns(old=lab("q1"), new=lab("q2"))
    W = RNG.poisson(1.0, (B, N)).astype(float)
    h, ex, g, n = (d[c].to_numpy().astype(float) for c in ("h", "ex", "g", "n"))
    cells, boot = [], {}
    for o in FIFTHS:
        for r in FIFTHS:
            sel = ((d["old"] == o) & (d["new"] == r)).to_numpy()
            ob = (W[:, sel] @ h[sel]) / (W[:, sel] @ ex[sel])
            boot[(o, r)] = ob
            cells.append({"key": f"{o}:{r}", "old": o, "recent": r, "people": int(sel.sum()), "odds": float(h[sel].sum() / ex[sel].sum()),
                          "lo": pct(ob, 2.5), "hi": pct(ob, 97.5), "growth": float(np.expm1(g[sel].sum() / n[sel].sum()))})
    a = boot[("bottom", "top")] / boot[("top", "bottom")]
    est_a = [c for c in cells if c["key"] == "bottom:top"][0]["odds"] / [c for c in cells if c["key"] == "top:bottom"][0]["odds"]
    lr = lambda o, r: np.log(boot[(o, r)])
    rec = np.mean([lr(o, "top") - lr(o, "bottom") for o in FIFTHS], axis=0)
    old = np.mean([lr("top", r) - lr("bottom", r) for r in FIFTHS], axis=0)
    pt = {(c["old"], c["recent"]): np.log(c["odds"]) for c in cells}
    est_b = np.mean([pt[(o, "top")] - pt[(o, "bottom")] for o in FIFTHS]) - np.mean([pt[("top", r)] - pt[("bottom", r)] for r in FIFTHS])
    tests = {"P10a": {"est": float(est_a), "lo": pct(a, 2.5), "hi": pct(a, 97.5), "lo99": pct(a, 0.5)},
             "P10b": {"est": float(est_b), "recent_spread": float(np.exp(np.mean([pt[(o, "top")] - pt[(o, "bottom")] for o in FIFTHS]))),
                      "old_spread": float(np.exp(np.mean([pt[("top", r)] - pt[("bottom", r)] for r in FIFTHS]))),
                      "lo": pct(rec - old, 2.5), "hi": pct(rec - old, 97.5), "lo99": pct(rec - old, 0.5)}}

    # --- going stale
    decay, lag_parts = [], {}
    for ry in (2006, 2007):
        r = yr.filter((pl.col("year") == ry) & (pl.col("n") >= 20)).with_columns(sc=pl.col("s") / (pl.col("n") + 20))
        later = yr.filter(pl.col("year").is_between(ry + 1, 2011) & (pl.col("n") >= 10))
        keep = later.group_by("user").agg(k=pl.len()).filter(pl.col("k") == 2011 - ry)
        r = r.join(keep, on="user").with_columns(q=pl.col("sc").rank("average") / pl.len())
        top = r.filter(pl.col("q") > 0.9).select("user")
        for L in range(1, 2011 - ry + 1):
            x = later.filter(pl.col("year") == ry + L).join(top, on="user").sort("user")
            lag_parts.setdefault(L, []).append(x.select("user", "h", "ex", pl.lit(ry).alias("ry")))
    users = sorted(set(u for parts in lag_parts.values() for p_ in parts for u in p_["user"].to_list()))
    uidx = {u: i for i, u in enumerate(users)}
    Wd = RNG.poisson(1.0, (B, len(users))).astype(float)
    lag_boot = {}
    for L, parts in sorted(lag_parts.items()):
        x = pl.concat(parts)
        ix = np.array([uidx[u] for u in x["user"].to_list()])
        hh, ee = x["h"].to_numpy().astype(float), x["ex"].to_numpy().astype(float)
        ob = (Wd[:, ix] @ hh) / (Wd[:, ix] @ ee)
        lag_boot[L] = ob
        decay.append({"key": str(L), "years_later": L, "people": int(x["user"].n_unique()), "odds": float(hh.sum() / ee.sum()),
                      "lo": pct(ob, 2.5), "hi": pct(ob, 97.5), "rating_years": sorted(set(x["ry"].to_list()))})
    c_ = lag_boot[2] / lag_boot[4]
    tests["P10c"] = {"est": float(decay[1]["odds"] / decay[3]["odds"]), "lo": pct(c_, 2.5), "hi": pct(c_, 97.5), "lo99": pct(c_, 0.5)}
    print(f"people in old-vs-recent: {N:,}")
    for c in cells:
        print(f"  old {c['old']:7s} recent {c['recent']:7s} n {c['people']:>5}  10x odds {c['odds']:.2f} [{c['lo']:.2f}, {c['hi']:.2f}]  growth {c['growth']:+.1%}")
    for dd in decay:
        print(f"  {dd['years_later']} years later: {dd['odds']:.2f} [{dd['lo']:.2f}, {dd['hi']:.2f}] ({dd['people']} people)")
    print(json.dumps(tests, indent=1))
    (ROOT / "analysis" / "out" / f"recency_{half}.json").write_text(json.dumps({"cells": cells, "decay": decay, "tests": tests}, indent=1))


if __name__ == "__main__":
    main()
