"""ListenBrainz year by year (E3 in LB_PREREG.md, descriptive), for the write-up's era charts.

For each year Y the new artists were found: people rated on their artist picks up to Y-2 (frozen prescience score,
shrunk, >= 20 picks); their picks made in year Y, compared with similar artists (same month and size).
1. Best and worst fifth: growth of their new artists vs similar artists, and the gap; single years 2010-2025.
2. Top 20%, 10%, 5%, 1%: tenfold takeoffs vs similar artists; each point pools years Y-1..Y+1 (takeoffs are rare),
   Y = 2011-2024.
3. One new fan's worth (analysis/fan_value.py's model) for artist-months in year Y (good-picker counts there already use
   cutoff Y-2; pickers.py), by artist size; single years 2010-2025.
Plus pooled "early" (2010-2013) and "recent" (2021-2025) rows for the text. Before 2010 there are too few listeners
(21 people in 2009's top 1%). 2025 covers picks through August (12 months of outcome). 95% ranges: bootstrap over
people (fan value: over artists). Writes analysis/writeup/yeargrowth.json, yeartakeoff.json, yearfan.json.
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
import fan_value as fv  # noqa: E402

W = ROOT / "analysis" / "writeup"
RNG = np.random.default_rng(5151)
B = 1000
POOLS = {"early": (2010, 2013), "recent": (2021, 2025)}
pc = lambda a, q: float(np.percentile(a, q))

b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m", "bin", "v", "e"])
b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(s10=pl.col("x10").mean(), ve=pl.col("v").mean()), on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
fy = []
for y in range(2009, 2026):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fy.append(b.filter(pl.col("year") == y).join(past.select("user", "q"), on="user"))
F = pl.concat(fy)


def growth_row(f, key):
    row, gb = {"key": key}, {}
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
    return {"key": key, "top": top, "times_similar": float(h.sum() / e.sum()), "lo": pc(bs, 2.5), "hi": pc(bs, 97.5),
            "per_1000": float(h.sum() / x["n"].sum() * 1000), "similar_per_1000": float(e.sum() / x["n"].sum() * 1000),
            "events": int(h.sum()), "people": x.height}


growth = [{**growth_row(F.filter(pl.col("year") == y), str(y)), "year": y} for y in range(2010, 2026)]
growth += [growth_row(F.filter(pl.col("year").is_between(*v)), k) for k, v in POOLS.items()]
for r in growth:
    print(f"{r['key']:>6}: best {r['best_growth']:+.1%} worst {r['worst_growth']:+.1%} gap {r['gap_growth']:+.1%} [{r['gap_lo']:+.1%}, {r['gap_hi']:+.1%}]")
takeoff = []
for top in (20, 10, 5, 1):
    takeoff += [{**takeoff_row(F.filter(pl.col("year").is_between(y - 1, y + 1)), top, f"{top}:{y}"), "year": y} for y in range(2011, 2025)]
    takeoff += [takeoff_row(F.filter(pl.col("year").is_between(*v)), top, f"{top}:{k}") for k, v in POOLS.items()]
for top in (20, 10, 5, 1):
    print(f"top {top:>2}%: " + "  ".join(f"{r['key'].split(':')[1]} {r['times_similar']:.2f}[{r['lo']:.1f},{r['hi']:.1f}]" for r in takeoff if r["top"] == top))
(W / "yeargrowth.json").write_text(json.dumps(growth, indent=1))
(W / "yeartakeoff.json").write_text(json.dumps(takeoff, indent=1))

fv.B = 500
df = fv.load("lb").with_columns(year=pl.col("m") // 12)
fan = []
for key, (y0, y1) in [(str(y), (y, y)) for y in range(2010, 2026)] + list(POOLS.items()):
    for size in ("small", "medium", "big"):
        d = df.filter(pl.col("year").is_between(y0, y1) & (pl.col("size") == size))
        est, bs = fv.fit(d)
        for i, c in enumerate(fv.COLS[:3]):
            fan.append({"key": f"{key}:{size}:{fv.NAMES[c]}", "year": y0 if y0 == y1 else None, "stage": size, "fan": fv.NAMES[c], "artist_months": d.height,
                        "effect": float(np.expm1(est[i])), "lo": float(np.expm1(pc(bs[:, i], 2.5))), "hi": float(np.expm1(pc(bs[:, i], 97.5)))})
for key in ("early", "recent"):
    print(key, "small:", "  ".join(f"{r['fan']} {r['effect']:+.1%}" for r in fan if r["key"].startswith(f"{key}:small:")))
(W / "yearfan.json").write_text(json.dumps(fan, indent=1))
