"""ListenBrainz era test in plain units (E3, descriptive; LB_PREREG.md Part 3).

Same design as headlines.py H3 on LB: people rated on artist picks up to cutoff C (frozen prescience score, shrunk, >= 20
picks), best = top fifth, worst = bottom fifth; their picks in C+2..C+3; tenfold rate vs similar artists (same month, size).
Also average growth vs similar artists (same month, size) for each fifth, and the gap. Eras by cutoff: 2007-2012,
2013-2018, 2019-2023. Bootstrap over person-cutoffs (2,000 draws). Writes analysis/out/eras_plain_lb.json and the
write-up's analysis/writeup/eras.json (plus the formal era test, E2, from the scorecards).
"""

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(2027)
B = 2000
L10 = float(np.log(10))
ERAS = (("2007–2012", 2007, 2012), ("2013–2018", 2013, 2018), ("2019–2023", 2019, 2023))

b = pl.read_parquet(X / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m", "bin", "v", "e"])
b = b.with_columns(x10=(pl.col("v") >= L10).cast(pl.Float64), year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(x10_exp=pl.col("x10").mean(), ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
parts = []
for c in range(2007, 2024):
    past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    past = past.with_columns(grp=pl.when(pl.col("q") > 0.8).then(pl.lit("best")).when(pl.col("q") <= 0.2).then(pl.lit("worst"))).drop_nulls("grp")
    parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "grp"), on="user")
                 .with_columns(cut=pl.lit(c), u=pl.col("user") * 100 + (c - 2000)))
f = pl.concat(parts)
rows = []
for lab, lo, hi in ERAS:
    x = f.filter(pl.col("cut").is_between(lo, hi))
    per = {g: x.filter(pl.col("grp") == g).group_by("u").agg(h=pl.col("x10").sum(), gs=pl.col("gx").sum(), n=pl.len()) for g in ("best", "worst")}
    rate = {g: per[g]["h"].sum() / per[g]["n"].sum() for g in per}
    grow = {g: float(np.expm1(per[g]["gs"].sum() / per[g]["n"].sum())) for g in per}
    bs, bg = [], {"best": [], "worst": [], "gap": []}
    for _ in range(B):
        r, q = {}, {}
        for g, p in per.items():
            w = RNG.poisson(1.0, p.height)
            r[g] = (w * p["h"].to_numpy()).sum() / (w * p["n"].to_numpy()).sum()
            q[g] = np.expm1((w * p["gs"].to_numpy()).sum() / (w * p["n"].to_numpy()).sum())
        bs.append(r["best"] / r["worst"])
        bg["best"].append(q["best"]); bg["worst"].append(q["worst"]); bg["gap"].append(q["best"] - q["worst"])
    rows.append({"key": lab, "era": lab, "ratio_10x": float(rate["best"] / rate["worst"]), "lo": float(np.percentile(bs, 2.5)),
                 "hi": float(np.percentile(bs, 97.5)), "best_per_1000": float(rate["best"] * 1000), "worst_per_1000": float(rate["worst"] * 1000),
                 "people": int(per["best"].height + per["worst"].height), "best_events": int(per["best"]["h"].sum()),
                 **{f"{k}_growth": (grow[k] if k != "gap" else grow["best"] - grow["worst"]) for k in ("best", "worst", "gap")},
                 **{f"{k}_{e}": float(np.percentile(bg[k], pc)) for k in ("best", "worst", "gap") for e, pc in (("lo", 2.5), ("hi", 97.5))}})
    print(f"{lab}: best {rate['best']*1000:.2f} vs worst {rate['worst']*1000:.2f} per 1,000 -> {rows[-1]['ratio_10x']:.2f}x "
          f"[{rows[-1]['lo']:.2f}, {rows[-1]['hi']:.2f}]  ({rows[-1]['people']:,} person-cutoffs, {rows[-1]['best_events']} best-fifth tenfold)")
    print(f"   growth vs similar: best {grow['best']:+.1%}, worst {grow['worst']:+.1%}, gap {rows[-1]['gap_growth']:+.1%} "
          f"[{rows[-1]['gap_lo']:+.1%}, {rows[-1]['gap_hi']:+.1%}]")
(ROOT / "analysis" / "out" / "eras_plain_lb.json").write_text(json.dumps(rows, indent=1))
for m, name in (("A", "Prescience"), ("D", "Discernment")):
    e = json.loads((ROOT / "analysis" / "out" / "cand" / f"lb_{m}_artist_main" / "scorecard.json").read_text())["eras"]
    r = e["ratio_late_to_early"]
    rows.append({"key": f"formal_{m}", "era": name, "ratio": r["est"], "ratio_lo99": r["lo99"],
                 **{f"strength_{k[:4]}": e[k]["adjusted_forward"] for k in ("2007-2012", "2013-2018", "2019-2023")}})
(ROOT / "analysis" / "writeup" / "eras.json").write_text(json.dumps(rows, indent=1))
