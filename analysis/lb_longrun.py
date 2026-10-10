"""ListenBrainz long-run questions (exploratory; after the frozen LB run). Prescience, artists (frozen per-bet excess e).

A. Same people, different eras. Each year Y (new artists found), people rated on picks up to Y-2 (shrunk score, >= 20
   picks), ranked among everyone rated that year; their picks in Y vs similar artists (same month and size). Panel = people
   with rated picks in both 2010-2014 ("early") and 2021-2025 ("recent"); newcomers = recent-only. For each group and
   period: best and worst fifth growth vs similar and the gap; top 10% and 5% tenfold takeoffs vs similar. Bootstrap over
   people (paired within the panel), 1,000 draws.
B. A decade later. People rated on picks up to 2015 (>= 20), percentile within that group. Each later year 2017-2025,
   people with >= 10 picks that year: share of each 2015 band in that year's top / bottom fifth (ranked within the year),
   and best- vs worst-fifth growth gap. Plus 2015 -> 2024-25 (>= 10 picks) by band, like the write-up's repeat chart.
Writes analysis/out/lb_longrun.json.
"""

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(6161)
B = 1000
pc = lambda a, q: float(np.percentile(a, q))
BANDS = [("0–50", 0, .5), ("50–75", .5, .75), ("75–90", .75, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.01)]

b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m", "bin", "v", "e"])
b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(s10=pl.col("x10").mean(), ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
res = {}

# ---------- A. same people
fy = []
for y in range(2010, 2026):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
F = pl.concat(fy).with_columns(period=pl.when(pl.col("year") <= 2014).then(pl.lit("early")).when(pl.col("year") >= 2021).then(pl.lit("recent")))
F = F.drop_nulls("period")
both = F.group_by("user").agg(np_=pl.col("period").n_unique()).filter(pl.col("np_") == 2).select("user").with_columns(panel=pl.lit(True))
F = F.join(both, on="user", how="left").with_columns(pl.col("panel").fill_null(False))
groups = {"everyone": pl.lit(True), "panel": pl.col("panel"), "newcomers": ~pl.col("panel")}
users = F["user"].unique().sort().to_numpy()
W = RNG.poisson(1.0, (B, len(users))).astype(float)  # one weight per person, shared across periods (paired)
uidx = {u: i for i, u in enumerate(users)}


def stat(f, cond, val, den=None):
    """Per-person sums -> point estimate and bootstrap draws of sum(val)/sum(den or count)."""
    p = f.filter(cond).group_by("user").agg(a=pl.col(val).sum(), d=(pl.col(den).sum() if den else pl.len().cast(pl.Float64)))
    idx = np.array([uidx[u] for u in p["user"].to_list()], dtype=int)
    a, d = p["a"].to_numpy(), p["d"].to_numpy().astype(float)
    w = W[:, idx]
    return float(a.sum() / d.sum()), (w @ a) / (w @ d), p.height


A = {}
for g, gc in groups.items():
    for per in ("early", "recent"):
        f = F.filter(gc & (pl.col("period") == per))
        if f.height == 0:
            continue
        bg, bb, nb = stat(f, pl.col("q") > .8, "gx")
        wg, wb, nw = stat(f, pl.col("q") <= .2, "gx")
        t10, t10b, n10 = stat(f, pl.col("q") > .9, "x10", "s10")
        t5, t5b, n5 = stat(f, pl.col("q") > .95, "x10", "s10")
        A[(g, per)] = {"gap": (np.expm1(bg) - np.expm1(wg), np.expm1(bb) - np.expm1(wb)), "best": (np.expm1(bg), np.expm1(bb)),
                       "worst": (np.expm1(wg), np.expm1(wb)), "top10": (t10, t10b), "top5": (t5, t5b)}
        A[(g, per)]["people"] = {"best": nb, "worst": nw, "top10": n10, "top5": n5}
rows = []
for (g, per), d in A.items():
    r = {"group": g, "period": per, **{f"{k}_people": v for k, v in d["people"].items()}}
    for k in ("gap", "best", "worst", "top10", "top5"):
        est, bs = d[k]
        r.update({k: float(est), f"{k}_lo": pc(bs, 2.5), f"{k}_hi": pc(bs, 97.5)})
    rows.append(r)
    print(f"{g:9} {per:6}: best {r['best']:+.1%} worst {r['worst']:+.1%} gap {r['gap']:+.1%} [{r['gap_lo']:+.1%},{r['gap_hi']:+.1%}] | "
          f"top10 {r['top10']:.2f}x [{r['top10_lo']:.2f},{r['top10_hi']:.2f}]  top5 {r['top5']:.2f}x [{r['top5_lo']:.2f},{r['top5_hi']:.2f}]  "
          f"(best {r['best_people']:,}, top5 {r['top5_people']:,})")
change = []
for g in ("everyone", "panel"):
    for k in ("gap", "best", "worst", "top10", "top5"):
        e0, b0 = A[(g, "early")][k]; e1, b1 = A[(g, "recent")][k]
        d = (b1 - b0) if k in ("gap", "best", "worst") else (b1 / b0)
        change.append({"group": g, "measure": k, "kind": "difference" if k in ("gap", "best", "worst") else "ratio",
                       "est": float(e1 - e0 if k in ("gap", "best", "worst") else e1 / e0), "lo": pc(d, 2.5), "hi": pc(d, 97.5)})
        c = change[-1]
        print(f"  change {g:9} {k:5} ({c['kind']}): {c['est']:+.3f} [{c['lo']:+.3f}, {c['hi']:+.3f}]")
res["same_people"] = {"rows": rows, "change": change, "panel_people": both.height}

# ---------- B. a decade later
past = (b.filter(pl.col("year") <= 2015).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
        .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
band = pl.lit(None, pl.String)
for lab, lo, hi in BANDS:
    band = pl.when((pl.col("q") > lo) & (pl.col("q") <= hi)).then(pl.lit(lab)).otherwise(band)
past = past.with_columns(band=band, fifth=pl.when(pl.col("q") > .8).then(pl.lit("top")).when(pl.col("q") <= .2).then(pl.lit("bottom")).otherwise(pl.lit("middle")))


def later(f):
    """Per-person later score on picks f (>= 10), ranked within; joined to the 2015 groups."""
    p = f.group_by("user").agg(ls=pl.col("e").mean(), n=pl.len()).filter(pl.col("n") >= 10)
    p = p.join(past.select("user", "band", "fifth", "q"), on="user")
    return p.with_columns(lq=pl.col("ls").rank("average") / pl.len())


def boot_share(x, cond):
    v = x.select(cond.cast(pl.Float64)).to_series().to_numpy()
    w = RNG.poisson(1.0, (B, len(v))).astype(float)
    bs = (w @ v) / w.sum(1)
    return float(v.mean()), pc(bs, 2.5), pc(bs, 97.5)


curve = []
for y in range(2017, 2026):
    f = b.filter(pl.col("year") == y)
    p = later(f)
    r = {"year": y, "years_later": y - 2015, "people": p.height}
    for fifth in ("top", "bottom"):
        x = p.filter(pl.col("fifth") == fifth)
        r[f"{fifth}_n"] = x.height
        r[f"{fifth}_in_top"], r[f"{fifth}_in_top_lo"], r[f"{fifth}_in_top_hi"] = boot_share(x, pl.col("lq") > .8)
        r[f"{fifth}_in_bottom"], r[f"{fifth}_in_bottom_lo"], r[f"{fifth}_in_bottom_hi"] = boot_share(x, pl.col("lq") <= .2)
    gg = f.join(past.select("user", "fifth"), on="user")
    gb = {}
    for fifth in ("top", "bottom"):
        q = gg.filter(pl.col("fifth") == fifth).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        w = RNG.poisson(1.0, (B, q.height)).astype(float)
        gb[fifth] = (float(np.expm1(q["s"].sum() / q["n"].sum())), np.expm1((w @ q["s"].to_numpy()) / (w @ q["n"].to_numpy())))
    gap = gb["top"][1] - gb["bottom"][1]
    r.update({"gap": gb["top"][0] - gb["bottom"][0], "gap_lo": pc(gap, 2.5), "gap_hi": pc(gap, 97.5), "top_growth": gb["top"][0], "bottom_growth": gb["bottom"][0]})
    curve.append(r)
    print(f"{y} (+{y-2015}y): {p.height:,} people | 2015 top fifth now top {r['top_in_top']:.0%} [{r['top_in_top_lo']:.0%},{r['top_in_top_hi']:.0%}] "
          f"bottom {r['top_in_bottom']:.0%} | 2015 bottom fifth now bottom {r['bottom_in_bottom']:.0%} top {r['bottom_in_top']:.0%} | "
          f"growth gap {r['gap']:+.1%} [{r['gap_lo']:+.1%},{r['gap_hi']:+.1%}]")
p = later(b.filter(pl.col("year").is_between(2024, 2025)))
dec = []
for lab, _, _ in BANDS:
    x = p.filter(pl.col("band") == lab)
    t = boot_share(x, pl.col("lq") > .8)
    bt = boot_share(x, pl.col("lq") <= .2)
    lqv = x["lq"].to_numpy()
    dec.append({"band": lab, "people": x.height, "later_mean": float(lqv.mean() * 100), "later_p25": float(np.percentile(lqv, 25) * 100),
                "later_p75": float(np.percentile(lqv, 75) * 100), "later_top_fifth": t[0], "top_lo": t[1], "top_hi": t[2],
                "later_bottom_fifth": bt[0], "bottom_lo": bt[1], "bottom_hi": bt[2]})
    d = dec[-1]
    print(f"  2015 {lab:>7} -> 2024-25: mean pct {d['later_mean']:.0f}, top fifth {d['later_top_fifth']:.0%} [{d['top_lo']:.0%},{d['top_hi']:.0%}], "
          f"bottom fifth {d['later_bottom_fifth']:.0%} ({x.height:,} people)")
res["decade"] = {"curve": curve, "bands_2024_25": dec}
(ROOT / "analysis" / "out" / "lb_longrun.json").write_text(json.dumps(res, indent=1))
