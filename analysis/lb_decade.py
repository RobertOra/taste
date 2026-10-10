"""A decade later (ListenBrainz, exploratory): prescience for songs (the most lasting measure) and discernment for songs
(the write-up's repeat-chart measure).

People ranked on their song picks up to 2015 (>= 20; score = weighted mean per-bet excess, shrunk by 20 average-weight
picks, from the scorecard agg table), percentile among them. Each later year 2016-2025: people from that group with >= 10
picks that year, ranked on that year's picks; share of the 2015 top fifth in that year's top fifth and of the 2015 bottom
fifth in the bottom fifth. 1 year later is marked: its picks' outcome window overlaps the 2015 picks'. 2025 covers picks
through August only. Bootstrap over people (1,000 draws). Writes analysis/writeup/decade.json.
"""
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(9191)
B = 1000
pc = lambda a, q: float(np.percentile(a, q))


def share(x, cond):
    v = x.select(cond.cast(pl.Float64)).to_series().to_numpy()
    w = RNG.poisson(1.0, (B, len(v))).astype(float)
    bs = (w @ v) / w.sum(1)
    return float(v.mean()), pc(bs, 2.5), pc(bs, 97.5)


def decade(cand, measure):
    a = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / cand / "agg.parquet", columns=["user", "year", "n", "sw", "swe"])
    base = (a.filter(pl.col("year") <= 2015).group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
            .filter(pl.col("n") >= 20).with_columns(s=pl.col("swe") / (pl.col("sw") + 20 * pl.col("sw") / pl.col("n")))
            .with_columns(q=pl.col("s").rank("average") / pl.len())
            .with_columns(fifth=pl.when(pl.col("q") > .8).then(pl.lit("top")).when(pl.col("q") <= .2).then(pl.lit("bottom")).otherwise(pl.lit("middle"))))
    rows = []
    for y in range(2016, 2026):
        later = (a.filter(pl.col("year") == y).group_by("user").agg(pl.col("n").sum(), (pl.col("swe").sum() / pl.col("sw").sum()).alias("ls"))
                 .filter(pl.col("n") >= 10))
        p = later.join(base.select("user", "fifth"), on="user").with_columns(lq=pl.col("ls").rank("average") / pl.len())
        r = {"key": f"{measure}:{y - 2015}", "measure": measure, "year": y, "years_later": y - 2015, "people": p.height, "overlap": y == 2016}
        t, bt = p.filter(pl.col("fifth") == "top"), p.filter(pl.col("fifth") == "bottom")
        r["top_in_top"], r["top_in_top_lo"], r["top_in_top_hi"] = share(t, pl.col("lq") > .8)
        r["bottom_in_bottom"], r["bottom_in_bottom_lo"], r["bottom_in_bottom_hi"] = share(bt, pl.col("lq") <= .2)
        r["top_n"], r["bottom_n"] = t.height, bt.height
        rows.append(r)
        print(f"{measure:11} +{r['years_later']:>2}y ({y}): {p.height:,} people | top fifth still top {r['top_in_top']:.0%} "
              f"[{r['top_in_top_lo']:.0%},{r['top_in_top_hi']:.0%}] | bottom still bottom {r['bottom_in_bottom']:.0%}")
    return rows


rows = decade("lb_A_song_main", "prescience") + decade("lb_D_song_main", "discernment")
(ROOT / "analysis" / "writeup" / "decade.json").write_text(json.dumps(rows, indent=1))
