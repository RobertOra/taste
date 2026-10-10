"""ListenBrainz by era, two descriptive views for the write-up (E3 in LB_PREREG.md):

1. What one new fan is worth, by era: analysis/fan_value.py's model (next-year growth on the numbers of good, ordinary,
   poor, unrated new fans and the good share, within month x size x momentum cells), fitted separately per era and artist
   size. Era by rating cutoff (good-picker counts for artist-month year Y use cutoff Y-2; pickers.py).
2. Tenfold takeoffs by era for the top 20%, 10%, 5%, 1% of pickers (ladder.py design: rated on picks up to cutoff C,
   >= 20 picks, their picks in C+2..C+3, vs similar artists = same month and size), bootstrap over person-cutoffs.
Eras by cutoff: 2007-2012, 2013-2018, 2019-2023. Writes analysis/writeup/erasfan.json and erastakeoff.json.
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
ERAS = (("2007–2012", 2007, 2012), ("2013–2018", 2013, 2018), ("2019–2023", 2019, 2023))
RNG = np.random.default_rng(3131)

# 1. fan value by era x size
df = fv.load("lb").with_columns(cut=pl.col("m") // 12 - 2)
rows = []
for lab, lo, hi in ERAS:
    for size in ("small", "medium", "big"):
        d = df.filter(pl.col("cut").is_between(lo, hi) & (pl.col("size") == size))
        est, bs = fv.fit(d)
        for i, c in enumerate(fv.COLS[:3]):
            rows.append({"key": f"{lab}:{size}:{fv.NAMES[c]}", "era": lab, "stage": size, "fan": fv.NAMES[c], "artist_months": d.height,
                         "effect": float(np.expm1(est[i])), "lo": float(np.expm1(np.percentile(bs[:, i], 2.5))),
                         "hi": float(np.expm1(np.percentile(bs[:, i], 97.5)))})
        print(lab, size, d.height, "  ".join(f"{r['fan']} {r['effect']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}]" for r in rows[-3:]))
(W / "erasfan.json").write_text(json.dumps(rows, indent=1))

# 2. tenfold takeoffs by era x top band
b = pl.read_parquet(ROOT / "data" / "derived" / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m", "bin", "v", "e"])
b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), year=pl.col("m") // 12)
b = b.join(b.group_by("m", "bin").agg(s10=pl.col("x10").mean()), on=["m", "bin"])
parts = []
for c in range(2007, 2024):
    past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user")
                 .with_columns(cut=pl.lit(c), u=pl.col("user") * 100 + (c - 2000)))
f = pl.concat(parts)
out = []
for top in (0.20, 0.10, 0.05, 0.01):
    for lab, lo, hi in ERAS:
        x = f.filter(pl.col("cut").is_between(lo, hi) & (pl.col("q") > 1 - top)).group_by("u").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), n=pl.len())
        h, e = x["h"].to_numpy(), x["e"].to_numpy()
        w = RNG.poisson(1.0, (2000, x.height)).astype(float)
        bs = (w @ h) / (w @ e)
        out.append({"key": f"{int(top * 100)}:{lab}", "top": int(top * 100), "era": lab, "times_similar": float(h.sum() / e.sum()),
                    "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "per_1000": float(h.sum() / x["n"].sum() * 1000),
                    "similar_per_1000": float(e.sum() / x["n"].sum() * 1000), "events": int(h.sum()), "people": x.height})
        r = out[-1]
        print(f"top {r['top']:>2}% {lab}: {r['times_similar']:.2f}x [{r['lo']:.2f}, {r['hi']:.2f}]  {r['per_1000']:.2f} vs {r['similar_per_1000']:.2f} per 1,000"
              f"  ({r['events']} takeoffs, {r['people']:,} person-cutoffs)")
(W / "erastakeoff.json").write_text(json.dumps(out, indent=1))
