"""One table of every candidate's scorecard (analysis/out/cand/*/scorecard.json).

Usage: scoreboard.py [substring ...]   (filter candidate names)
Writes analysis/out/cand/scoreboard.csv as well.
"""

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "out" / "cand"


def fmt_ci(v, c):
    if v is None:
        return ""
    if not c or c[0] is None:
        return f"{v:.3f}"
    return f"{v:.3f} [{c[0]:.3f}, {c[1]:.3f}]"


rows = []
for f in sorted(OUT.glob("*/scorecard.json")):
    d = json.loads(f.read_text())
    if d["candidate"].startswith("test_"):
        continue
    if len(sys.argv) > 1 and not any(k in d["candidate"] for k in sys.argv[1:]):
        continue
    fw = d.get("forward", {})
    rows.append({
        "candidate": d["candidate"],
        "forward": fw.get("rank_corr"), "forward_ci": fmt_ci(fw.get("rank_corr"), fw.get("rank_corr_ci")),
        "repeat_top20": fw.get("repeat_rate_top20"),
        "imp_adj_forward": fw.get("impostor_adjusted_rank_corr"),
        "stability_3y": d.get("stability_3y_corrected"),
        "reliability": d.get("reliability"),
        "impostor_r2": d.get("impostor_r2"),
        "not_luck": d.get("not_luck_share"),
        "users": d.get("users_scored"), "coverage": d.get("coverage"),
        "gates": "pass" if d.get("passes_gates") else "FAIL: " + ", ".join(k for k, v in d.get("gates", {}).items() if not v),
    })
df = pd.DataFrame(rows).sort_values("forward", ascending=False)
df.to_csv(OUT / "scoreboard.csv", index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 60)
print(df.drop(columns=["forward"]).round(3).to_string(index=False))
