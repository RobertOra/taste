"""Can taste be learned? Do people pick better as they gain experience? (post-freeze; one run per half)

Artist picks scored with the frozen prescience measure (per-bet excess e, every correction; each pick is compared with
same-month picks, so calendar-wide shifts are removed). Experience = years since the person's first listen (user_features
start_week). Within-person comparison, so the result isn't driven by who stays on the platform:
- change: for people with >= 20 picks in experience years 1-2 and >= 20 in years 3-4, mean growth vs similar in years 3-4
  minus years 1-2 (and the same for years 1-2 vs 5-6 where available);
- curve: average growth vs similar by experience year, for a fixed group of people active (>= 10 picks) in each of years
  1 through 5.
- by starting level: the change for people who started in the bottom, middle, and top third (ranked on odd-numbered picks
  in years 1-2, change measured on even-numbered picks, so regression to the mean doesn't masquerade as learning).
Bootstrap over people (1,000 draws).

Usage: learning.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1414)
B = 1000


def pct(x, q):
    return float(np.percentile(x, q))


def boot_mean(v):
    w = RNG.poisson(1.0, (B, len(v))).astype(float)
    bs = (w @ v) / w.sum(1)
    return float(v.mean()), pct(bs, 2.5), pct(bs, 97.5), pct(bs, 0.5), pct(bs, 99.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "m", "e"])
    uf = pl.read_parquet(X / "user_features" / f"{half}.parquet", columns=["user", "start_week"])
    uf = uf.with_columns(start_m=(pl.from_epoch(pl.col("start_week").cast(pl.Int64) * 604800, time_unit="s").dt.year() * 12
                                  + pl.from_epoch(pl.col("start_week").cast(pl.Int64) * 604800, time_unit="s").dt.month() - 1))
    b = b.join(uf.select("user", "start_m"), on="user").with_columns(exp_year=((pl.col("m") - pl.col("start_m")) // 12 + 1).cast(pl.Int16))
    b = b.with_columns(rn=pl.int_range(pl.len()).over("user", order_by="m"))
    res = {}

    def change(a, c, label):
        w = b.with_columns(win=pl.when(pl.col("exp_year").is_between(*a)).then(pl.lit("early"))
                           .when(pl.col("exp_year").is_between(*c)).then(pl.lit("late")).otherwise(None)).drop_nulls("win")
        per = w.group_by("user", "win").agg(g=pl.col("e").mean(), n=pl.len()).pivot(on="win", index="user", values=["g", "n"])
        per = per.filter((pl.col("n_early") >= 20) & (pl.col("n_late") >= 20))
        d = np.expm1(per["g_late"].to_numpy()) - np.expm1(per["g_early"].to_numpy())
        m, lo, hi, lo99, hi99 = boot_mean(d)
        res[label] = {"change": m, "lo": lo, "hi": hi, "lo99": lo99, "hi99": hi99, "people": per.height,
                      "early": float(np.expm1(per["g_early"].to_numpy()).mean()), "late": float(np.expm1(per["g_late"].to_numpy()).mean())}
        print(f"  {label}: {per.height:,} people; early {res[label]['early']:+.2%} -> late {res[label]['late']:+.2%}; change {m:+.2%} [{lo:+.2%}, {hi:+.2%}]")
    change((1, 2), (3, 4), "years 1-2 vs 3-4")
    change((1, 2), (5, 6), "years 1-2 vs 5-6")

    # curve for a fixed group active in each of years 1..5
    yrs = b.filter(pl.col("exp_year").is_between(1, 5)).group_by("user", "exp_year").agg(g=pl.col("e").mean(), n=pl.len())
    keep = yrs.filter(pl.col("n") >= 10).group_by("user").agg(k=pl.len()).filter(pl.col("k") == 5).select("user")
    cy = yrs.join(keep, on="user").pivot(on="exp_year", index="user", values="g")
    curve = []
    for yv in range(1, 6):
        v = np.expm1(cy[str(yv)].to_numpy())
        m, lo, hi, _, _ = boot_mean(v)
        curve.append({"key": str(yv), "year": yv, "growth": m, "lo": lo, "hi": hi, "people": int(len(v))})
    res["curve"] = curve
    print("  curve (same people, years 1-5): " + "  ".join(f"y{c['year']} {c['growth']:+.2%}" for c in curve) + f"  ({curve[0]['people']:,} people)")

    # by starting level, split-half (odd picks rank, even picks measure)
    w = b.filter(pl.col("exp_year").is_between(1, 4)).with_columns(odd=(pl.col("rn") % 2 == 1), early=pl.col("exp_year") <= 2)
    st = w.filter(pl.col("early") & pl.col("odd")).group_by("user").agg(s=pl.col("e").mean(), n=pl.len()).filter(pl.col("n") >= 10)
    ev = w.filter(~pl.col("odd")).group_by("user", "early").agg(g=pl.col("e").mean(), n=pl.len())
    ev = ev.pivot(on="early", index="user", values=["g", "n"]).rename({"g_true": "g_e", "g_false": "g_l", "n_true": "n_e", "n_false": "n_l"})
    dd = st.join(ev, on="user").filter((pl.col("n_e") >= 10) & (pl.col("n_l") >= 10)).with_columns(q=pl.col("s").rank("average") / pl.len())
    by = []
    for lab, lo_, hi_ in (("bottom third", 0, 1 / 3), ("middle third", 1 / 3, 2 / 3), ("top third", 2 / 3, 1.01)):
        x = dd.filter((pl.col("q") > lo_) & (pl.col("q") <= hi_))
        d = np.expm1(x["g_l"].to_numpy()) - np.expm1(x["g_e"].to_numpy())
        m, lo, hi, _, _ = boot_mean(d)
        by.append({"key": lab, "start": lab, "change": m, "lo": lo, "hi": hi, "people": x.height})
        print(f"  started in the {lab}: change {m:+.2%} [{lo:+.2%}, {hi:+.2%}] ({x.height:,} people)")
    res["by_start"] = by
    (ROOT / "analysis" / "out" / f"learning_{half}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
