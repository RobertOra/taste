"""Side-by-side table of model A variants (analysis/out/prescience/*/summary.json)."""

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "out" / "prescience"
rows = []
for f in sorted(OUT.glob("*/summary.json")):
    s = json.loads(f.read_text())
    if len(sys.argv) > 1 and not any(k in s["variant"] for k in sys.argv[1:]):
        continue
    p = s["persistence"]
    rows.append({
        "variant": s["variant"], "bets_M": round(s["bets"] / 1e6, 1), "users": s["users_scored"],
        "skill_share": round(s["luck"]["skill_share_of_variance"], 3),
        "halves": round(p["halves"]["pearson"], 3), "gap": round(p["halves_with_gap"]["pearson"], 3),
        "periods": round(p["periods_2006_08_vs_2010_11"]["pearson"] or float("nan"), 3),
        "random": round(p["random_split"]["pearson"], 3),
        "impostor_r2": round(s["impostors"]["r2_all"], 3),
        "resid_halves": round(s["impostors"]["residual_persistence_halves"], 3),
    })
pd.set_option("display.width", 200)
print(pd.DataFrame(rows).to_string(index=False))
