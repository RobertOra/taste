"""ListenBrainz year by year for songs (exploratory, 2026-10-13): the song versions of eras_yearly.py's parts 1 and 2.

For each year Y the songs were found: people rated on their song picks up to Y-2 (the study's song measure: songs by one artist
found the same month count as one pick, mean excess; shrunk, >= 20 picks); each song they picked in year Y, compared with
similar songs (same month and size).
1. Best and worst fifth: growth of their songs vs similar songs, and the gap; single years 2010-2025.
2. Top 20%, 10%, 5%, 1%: tenfold takeoffs vs similar songs; each point pools years Y-1..Y+1, Y = 2011-2024.
Plus pooled "early" (2010-2013) and "recent" (2021-2025) rows. 95% ranges: bootstrap over people.
Adds rows keyed "songs:..." (unit "songs") to analysis/writeup/yeargrowth.json and yeartakeoff.json; artist rows untouched.
"""
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
W = ROOT / "analysis" / "writeup"
RNG = np.random.default_rng(5152)
B = 1000
POOLS = {"early": (2010, 2013), "recent": (2021, 2025)}
pc = lambda a, q: float(np.percentile(a, q))

b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / "A_song_lb.parquet", columns=["user", "artist", "m", "bin", "v", "e"])
b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(s10=pl.col("x10").mean(), ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)
fy = []
for y in range(2009, 2026):
    past = (groups.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
F = pl.concat(fy)


def growth_row(f, key):
    row, gb = {"key": key, "unit": "songs"}, {}
    for g, cond in (("best", pl.col("q") > 0.8), ("worst", pl.col("q") <= 0.2)):
        p = f.filter(cond).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        s, n = p["s"].to_numpy(), p["n"].to_numpy().astype(float)
        w = RNG.poisson(1.0, (B, p.height)).astype(float)
        gb[g] = np.expm1((w @ s) / (w @ n))
        row.update({f"{g}_growth": float(np.expm1(s.sum() / n.sum())), f"{g}_lo": pc(gb[g], 2.5), f"{g}_hi": pc(gb[g], 97.5), f"{g}_people": p.height})
    gap = gb["best"] - gb["worst"]
    row.update({"gap_growth": row["best_growth"] - row["worst_growth"], "gap_lo": pc(gap, 2.5), "gap_hi": pc(gap, 97.5)})
    return row


def takeoff_row(f, top, key):
    x = f.filter(pl.col("q") > 1 - top / 100).group_by("user").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), n=pl.len())
    h, e = x["h"].to_numpy(), x["e"].to_numpy()
    w = RNG.poisson(1.0, (B, x.height)).astype(float)
    bs = (w @ h) / np.maximum(w @ e, 1e-12)
    return {"key": key, "unit": "songs", "top": top, "times_similar": float(h.sum() / e.sum()), "lo": pc(bs, 2.5), "hi": pc(bs, 97.5),
            "per_1000": float(h.sum() / x["n"].sum() * 1000), "similar_per_1000": float(e.sum() / x["n"].sum() * 1000),
            "events": int(h.sum()), "people": x.height}


growth = [{**growth_row(F.filter(pl.col("year") == y), f"songs:{y}"), "year": y} for y in range(2010, 2026)]
growth += [growth_row(F.filter(pl.col("year").is_between(*v)), f"songs:{k}") for k, v in POOLS.items()]
for r in growth:
    print(f"{r['key']:>12}: best {r['best_growth']:+.1%} worst {r['worst_growth']:+.1%} gap {r['gap_growth']:+.1%} [{r['gap_lo']:+.1%}, {r['gap_hi']:+.1%}]"
          f"  people {r['best_people']}/{r['worst_people']}")
takeoff = []
for top in (20, 10, 5, 1):
    takeoff += [{**takeoff_row(F.filter(pl.col("year").is_between(y - 1, y + 1)), top, f"songs:{top}:{y}"), "year": y} for y in range(2011, 2025)]
    takeoff += [takeoff_row(F.filter(pl.col("year").is_between(*v)), top, f"songs:{top}:{k}") for k, v in POOLS.items()]
for top in (20, 10, 5, 1):
    print(f"top {top:>2}%: " + "  ".join(f"{r['key'].split(':')[2]} {r['times_similar']:.2f}[{r['lo']:.1f},{r['hi']:.1f}]" for r in takeoff if r["top"] == top))
for name, rows in (("yeargrowth", growth), ("yeartakeoff", takeoff)):
    old = [r for r in json.loads((W / f"{name}.json").read_text()) if r.get("unit", "artists") != "songs"]
    (W / f"{name}.json").write_text(json.dumps(old + rows, indent=1))
