"""Can we score someone today? (ListenBrainz, exploratory.) Reliability of taste scores on recent listening only.

For each main measure, people's picks made 2019-2025 (frozen per-bet excess, weighted as in the scorecards), split into the
stored random halves (agg.parquet 'half'): split-half Spearman correlation among people with >= 10 picks in each half,
converted to a single pick's reliability with Spearman-Brown at the median half size, then to the reliability of a score
built from 50 / typical / 500 / 1,500 picks and the 80% range of the true percentile for someone measured at the 75th
(build_writeup_data.true_range). Typical = median recent picks among people with >= 20. Same for MLHD+'s hidden half
(all years) for comparison. Writes analysis/out/lb_today.json.
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from statistics import NormalDist  # noqa: E402

nd = NormalDist()


def true_range(rho, observed=0.75):
    rho = max(min(rho, 0.999), 0.0)
    z, sd = nd.inv_cdf(observed) * rho ** 0.5, (1 - rho) ** 0.5
    return 100 * nd.cdf(z - 1.2816 * sd), 100 * nd.cdf(z + 1.2816 * sd)


def reliability(name, years=None):
    a = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / name / "agg.parquet", columns=["user", "year", "half", "n", "sw", "swe"])
    if years:
        a = a.filter(pl.col("year").is_between(*years))
    h = a.group_by("user", "half").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum()).with_columns(s=pl.col("swe") / pl.col("sw"))
    w = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls()
    w = w.filter((pl.col("n_0") >= 10) & (pl.col("n_1") >= 10))
    r = spearmanr(w["s_0"], w["s_1"]).statistic
    nh = float(np.median(np.concatenate([w["n_0"].to_numpy(), w["n_1"].to_numpy()])))
    r1 = r / (nh - (nh - 1) * r)
    tot = a.group_by("user").agg(pl.col("n").sum()).filter(pl.col("n") >= 20)
    typ = int(round(float(tot["n"].median())))
    rows = []
    for n in (50, typ, 500, 1500):
        rn = n * r1 / (1 + (n - 1) * r1)
        lo, hi = true_range(rn)
        rows.append({"picks": n, "typical": n == typ, "reliability": round(rn, 3), "lo": round(lo), "hi": round(hi)})
    return {"split_half": float(r), "people": w.height, "median_half_picks": nh, "per_pick": float(r1), "typical_picks": typ, "people_20": tot.height, "rows": rows}


out = {}
for m in ("D_song", "A_song", "D_artist", "A_artist"):
    out[m] = {"lb_recent": reliability(f"lb_{m}_main", (2019, 2025)), "mlhd_hidden": reliability(f"sealed_{m}_main")}
    for k, v in out[m].items():
        print(f"{m:8} {k:11}: split-half {v['split_half']:.3f} ({v['people']:,} people), per pick {v['per_pick']:.4f}, typical {v['typical_picks']} picks -> "
              + "  ".join(f"{r['picks']} picks: {r['lo']}-{r['hi']}" for r in v["rows"]))
(ROOT / "analysis" / "out" / "lb_today.json").write_text(json.dumps(out, indent=1))
