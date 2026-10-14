"""Song versions of the new-fan charts (2026-10-13; SONG_PREREG.md round 5): the good-picker crowd curve (ladder.py
crowd_curve) and the poor-picker crowd curve (charts_data.py poor_crowd), on the song new-fans table
(data/derived/pickers/song_rate_A_<half>.parquet, analysis/song_pickers.py). The fan-value models run through
fan_value.py --unit song. Writes analysis/out/song_fans_<half>.json.

Usage: song_fans.py --half explore|sealed|lb
"""
import argparse
import json
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
import ladder  # noqa: E402
import charts_data  # noqa: E402

X = ROOT / "data" / "derived"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    df = pl.read_parquet(X / "pickers" / f"song_rate_A_{half}.parquet")
    good_rows, good_summary = ladder.crowd_curve(half, df)
    poor_rows = charts_data.poor_crowd(df)
    for r in good_rows:
        print(f"  good {r['crowd']:8s} {r['label']:>3}: n {r['artist_months']:>9,}  growth {r['growth']:+.1%} [{r['growth_lo']:+.1%}, {r['growth_hi']:+.1%}]")
    print("  good summary:", {k: v for k, v in good_summary.items() if not isinstance(v, dict)}, good_summary["slopes"])
    for r in poor_rows:
        if r["kind"] == "point":
            print(f"  poor {r['crowd']:8s} {r['label']:>3}: n {r['artist_months']:>9,}  growth {r['growth']:+.1%} [{r['growth_lo']:+.1%}, {r['growth_hi']:+.1%}]")
        else:
            print(f"  poor {r['crowd']:8s} slope {r['per_picker']:+.2%} [{r['lo']:+.2%}, {r['hi']:+.2%}]")
    (ROOT / "analysis" / "out" / f"song_fans_{half}.json").write_text(json.dumps({"good_curve": good_rows, "good_summary": good_summary,
                                                                                 "poor_curve": poor_rows}, indent=1))


if __name__ == "__main__":
    main()
