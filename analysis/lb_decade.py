"""A decade later, on discernment for songs (the write-up's repeat-chart measure), ListenBrainz, exploratory.

People ranked on their song picks up to 2015 (>= 20; score = weighted mean per-bet excess, shrunk by 20 average-weight
picks, from the scorecard agg table), percentile among them. Each later year 2016-2025: people from that group with >= 10
picks that year, ranked on that year's picks; share of the 2015 top fifth in that year's top fifth and of the 2015 bottom
fifth in the bottom fifth. 1 year later is marked: its picks' outcome window overlaps the 2015 picks' (shared shocks).
Bootstrap over people (1,000 draws). Writes analysis/writeup/decade.json.
Also: the same-people gap year by year for the era chart (analysis/writeup/samepeople_year.json).
"""
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(9191)
B = 1000
pc = lambda a, q: float(np.percentile(a, q))

a = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / "lb_D_song_main" / "agg.parquet", columns=["user", "year", "n", "sw", "swe"])
base = (a.filter(pl.col("year") <= 2015).group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum()).filter(pl.col("n") >= 20)
        .with_columns(s=pl.col("swe") / (pl.col("sw") + 20 * pl.col("sw") / pl.col("n"))).with_columns(q=pl.col("s").rank("average") / pl.len())
        .with_columns(fifth=pl.when(pl.col("q") > .8).then(pl.lit("top")).when(pl.col("q") <= .2).then(pl.lit("bottom")).otherwise(pl.lit("middle"))))


def share(x, cond):
    v = x.select(cond.cast(pl.Float64)).to_series().to_numpy()
    w = RNG.poisson(1.0, (B, len(v))).astype(float)
    bs = (w @ v) / w.sum(1)
    return float(v.mean()), pc(bs, 2.5), pc(bs, 97.5)


rows = []
for y in range(2016, 2026):
    later = a.filter(pl.col("year") == y).group_by("user").agg(pl.col("n").sum(), (pl.col("swe").sum() / pl.col("sw").sum()).alias("ls")).filter(pl.col("n") >= 10)
    p = later.join(base.select("user", "fifth"), on="user").with_columns(lq=pl.col("ls").rank("average") / pl.len())
    r = {"key": str(y - 2015), "year": y, "years_later": y - 2015, "people": p.height, "overlap": y == 2016}
    t, bt = p.filter(pl.col("fifth") == "top"), p.filter(pl.col("fifth") == "bottom")
    r["top_in_top"], r["top_in_top_lo"], r["top_in_top_hi"] = share(t, pl.col("lq") > .8)
    r["bottom_in_bottom"], r["bottom_in_bottom_lo"], r["bottom_in_bottom_hi"] = share(bt, pl.col("lq") <= .2)
    r["top_n"], r["bottom_n"] = t.height, bt.height
    rows.append(r)
    print(f"+{r['years_later']:>2}y ({y}): {p.height:,} people | top fifth still top {r['top_in_top']:.0%} [{r['top_in_top_lo']:.0%},{r['top_in_top_hi']:.0%}] | "
          f"bottom still bottom {r['bottom_in_bottom']:.0%} [{r['bottom_in_bottom_lo']:.0%},{r['bottom_in_bottom_hi']:.0%}]")
(ROOT / "analysis" / "writeup" / "decade.json").write_text(json.dumps(rows, indent=1))

# same people, year by year (prescience, artists; design as analysis/eras_yearly.py)
b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
fy = []
for y in range(2010, 2026):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
F = pl.concat(fy)
yrs = F.group_by("user").agg(e=(pl.col("year") <= 2014).any(), r=(pl.col("year") >= 2021).any())
panel = yrs.filter(pl.col("e") & pl.col("r")).select("user")
out = []
for grp, f in (("everyone", F), ("same", F.join(panel, on="user"))):
    for y in range(2010, 2026):
        x = f.filter(pl.col("year") == y)
        gb = {}
        for g, cond in (("best", pl.col("q") > .8), ("worst", pl.col("q") <= .2)):
            pp = x.filter(cond).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
            w = RNG.poisson(1.0, (B, pp.height)).astype(float)
            gb[g] = (np.expm1(pp["s"].sum() / pp["n"].sum()), np.expm1((w @ pp["s"].to_numpy()) / (w @ pp["n"].to_numpy())), pp.height)
        gap = gb["best"][1] - gb["worst"][1]
        out.append({"key": f"{grp}:{y}", "group": grp, "year": y, "gap": float(gb["best"][0] - gb["worst"][0]), "lo": pc(gap, 2.5), "hi": pc(gap, 97.5),
                    "best_people": gb["best"][2], "worst_people": gb["worst"][2]})
    print(grp, " ".join(f"{r['year']}:{r['gap']:+.1%}" for r in out if r["group"] == grp), f"(panel {panel.height:,})" if grp == "same" else "")
(ROOT / "analysis" / "writeup" / "samepeople_year.json").write_text(json.dumps(out, indent=1))
