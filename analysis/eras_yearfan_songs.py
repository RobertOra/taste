"""ListenBrainz, one new fan's worth year by year, for songs (2026-10-14, exploratory): eras_yearly.py part 3 on the song
new-fans table (song_pickers.py; fan_value.py --unit song model), by song size; single years 2010-2025 plus pooled "early"
(2010-2013) and "recent" (2021-2025). Bootstrap over songs (500 draws). Adds rows keyed "songs:..." (unit "songs") to
analysis/writeup/yearfan.json; artist rows untouched.
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
POOLS = {"early": (2010, 2013), "recent": (2021, 2025)}
pc = lambda a, q: float(np.percentile(a, q))
fv.B = 500
df = fv.load("lb", "song").with_columns(year=pl.col("m") // 12)
fan = []
for key, (y0, y1) in [(str(y), (y, y)) for y in range(2010, 2026)] + list(POOLS.items()):
    for size in ("small", "medium", "big"):
        d = df.filter(pl.col("year").is_between(y0, y1) & (pl.col("size") == size))
        if d.height < 1000:
            continue
        est, bs = fv.fit(d)
        for i, c in enumerate(fv.COLS[:3]):
            fan.append({"key": f"songs:{key}:{size}:{fv.NAMES[c]}", "unit": "songs", "year": y0 if y0 == y1 else None, "stage": size, "fan": fv.NAMES[c],
                        "artist_months": d.height, "effect": float(np.expm1(est[i])), "lo": float(np.expm1(pc(bs[:, i], 2.5))), "hi": float(np.expm1(pc(bs[:, i], 97.5)))})
for key in ("early", "recent"):
    print(key, "small:", "  ".join(f"{r['fan']} {r['effect']:+.1%}" for r in fan if r["key"].startswith(f"songs:{key}:small:")))
old = [r for r in json.loads((W / "yearfan.json").read_text()) if r.get("unit", "artists") != "songs"]
(W / "yearfan.json").write_text(json.dumps(old + fan, indent=1))
