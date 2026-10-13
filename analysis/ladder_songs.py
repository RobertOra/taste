"""The taste ladder for songs (exploratory, 2026-10-13; the study's ladder.py covers artists only).

People are rated on their song picks up to cutoff C (frozen prescience score for songs: songs by one artist found the same month
count as one pick, mean excess; shrunk sum e/(n+20), >= 20 picks) and ranked into percentile bands, finer at the top.
Outcome: each song they picked in C+2..C+3, chance of growing 10x (and 4x) in a year vs similar songs (same month and size),
plus growth vs similar. --per-group weights each song by 1/(songs by that artist the person found that month), so an album
that took off counts once. 95% intervals: bootstrap over people (1,000 draws). Same bands, cutoffs and bootstrap as ladder.py.
Input: data/derived/bet_outcomes/A_song_{half}.parquet (taste_models.py --unit song --bets-out, per song before collapsing).

Usage: ladder_songs.py --half explore|sealed|lb
"""
import argparse
import json
import sys as _sys
from pathlib import Path

import numpy as np
import polars as pl

_sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutoffs import cuts  # noqa: E402
from ladder import EDGES, B, pct  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1013)


def ladder_songs(half, per_group=False):
    b = pl.read_parquet(X / "bet_outcomes" / f"A_song_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"])
    b = b.with_columns(year=pl.col("m") // 12, x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), x4=(pl.col("v") >= np.log(4)).cast(pl.Float64))
    exp = b.group_by("m", "bin").agg(ve=pl.col("v").mean(), s10=pl.col("x10").mean(), s4=pl.col("x4").mean())
    groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)   # one pick per artist-month
    parts = []
    for c in cuts(half):
        past = (groups.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user").with_columns(cut=pl.lit(c)))
    f = pl.concat(parts).join(exp, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    f = f.with_columns(wt=(1.0 / pl.len().over("cut", "user", "artist", "m")) if per_group else pl.lit(1.0))
    f = f.with_columns(gx=pl.col("gx") * pl.col("wt"), x10=pl.col("x10") * pl.col("wt"), s10=pl.col("s10") * pl.col("wt"),
                       x4=pl.col("x4") * pl.col("wt"), s4=pl.col("s4") * pl.col("wt"))
    rows = []
    for lo, hi in zip(EDGES[:-1], EDGES[1:]):
        per = f.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(
            n=pl.col("wt").sum(), g=pl.col("gx").sum(), h10=pl.col("x10").sum(), e10=pl.col("s10").sum(), h4=pl.col("x4").sum(), e4=pl.col("s4").sum())
        A = {k: per[k].to_numpy().astype(float) for k in ("n", "g", "h10", "e10", "h4", "e4")}
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        r10, r4, gb = (w @ A["h10"]) / (w @ A["e10"]), (w @ A["h4"]) / (w @ A["e4"]), np.expm1((w @ A["g"]) / (w @ A["n"]))
        rows.append({"band": f"{lo * 100:g}–{min(hi, 1) * 100:g}%", "lo_pct": lo, "hi_pct": min(hi, 1.0), "people": per.height,
                     "songs": round(float(A["n"].sum())), "events_10x": round(float(A["h10"].sum()), 1), "odds_10x": float(A["h10"].sum() / A["e10"].sum()),
                     "odds_10x_lo": pct(r10, 2.5), "odds_10x_hi": pct(r10, 97.5), "odds_4x": float(A["h4"].sum() / A["e4"].sum()),
                     "odds_4x_lo": pct(r4, 2.5), "odds_4x_hi": pct(r4, 97.5), "growth": float(np.expm1(A["g"].sum() / A["n"].sum())),
                     "growth_lo": pct(gb, 2.5), "growth_hi": pct(gb, 97.5)})
    summ = {}
    for name, lo in (("top1", 0.99), ("top0_1", 0.999)):
        per = f.filter(pl.col("q") > lo).group_by("user").agg(h10=pl.col("x10").sum(), e10=pl.col("s10").sum(), n=pl.col("wt").sum())
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        r = (w @ per["h10"].to_numpy()) / (w @ per["e10"].to_numpy())
        summ[name] = {"odds_10x": float(per["h10"].sum() / per["e10"].sum()), "lo": pct(r, 2.5), "hi": pct(r, 97.5),
                      "people": per.height, "songs": round(float(per["n"].sum())), "events_10x": round(float(per["h10"].sum()), 1)}
    return rows, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    ap.add_argument("--per-group", action="store_true")
    a = ap.parse_args(); half = a.half
    rows, summ = ladder_songs(half, a.per_group)
    print(f"SONG LADDER [{half}]{' per artist-month' if a.per_group else ''} (exploratory)")
    for r in rows:
        print(f"  {r['band']:>12} people {r['people']:>6,} songs {r['songs']:>9,} 10x events {r['events_10x']:>7,.1f}  10x odds {r['odds_10x']:.2f}"
              f" [{r['odds_10x_lo']:.2f}, {r['odds_10x_hi']:.2f}]  4x {r['odds_4x']:.2f}  growth {r['growth']:+.1%}")
    for k, v in summ.items():
        print(f"  {k}: {v['odds_10x']:.2f} [{v['lo']:.2f}, {v['hi']:.2f}]  people {v['people']:,}  10x events {v['events_10x']:,.1f}")
    (ROOT / "analysis" / "out" / f"ladder_songs_{half}{'_group' if a.per_group else ''}.json").write_text(json.dumps({"ladder": rows, "summary": summ}, indent=1))


if __name__ == "__main__":
    main()
