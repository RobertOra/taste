"""Does being hooked on a pick tell us anything? (explore half; exploratory, post-freeze)

Obsession at the bet date (pipeline/derive_obsession.py): plays from first listen through the commitment week, and
how many weeks it took to commit. Outcome e: the bet's excess outcome vs comparable bets (prescience: excess
log growth; discernment: excess share of later triers who stuck), from analysis/taste_models.py --bets-out.

(a) Within a person: average over people (>= 20 bets) of [their most-hooked quarter of bets] minus
    [their least-hooked quarter]. Do people bet harder on their better picks?
(b) Across everyone: excess outcome by decile of plays-to-commit (and of speed), all bets pooled.
95% intervals from a Poisson bootstrap over people (200 draws).
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(5)
B = 200
UNITS = {"A_artist": ("artist", "Prescience, artists"), "D_artist": ("artist", "Discernment, artists"),
         "A_song": ("song", "Prescience, songs"), "D_song": ("song", "Discernment, songs")}


def ci(v):
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def within(df, col, ascending):
    """Mean over people of (top quarter - bottom quarter) of e, quarters of `col` within each person."""
    d = df.with_columns(q=((pl.col(col).rank("ordinal", descending=not ascending).over("user") - 1) * 4
                           / pl.col(col).count().over("user")).floor().cast(pl.Int8))
    per = d.group_by("user", "q").agg(pl.col("e").mean()).pivot(on="q", index="user", values="e")
    per = per.drop_nulls(["0", "3"])
    diff = (per["3"] - per["0"]).to_numpy()
    w = RNG.poisson(1.0, (B, len(diff)))
    boots = (w * diff).sum(1) / w.sum(1)
    quart = [float(per[str(k)].mean()) for k in range(4) if str(k) in per.columns]
    return float(diff.mean()), ci(boots), quart, len(diff)


def deciles(df, col):
    d = df.with_columns(dec=(pl.col(col).rank("ordinal") * 10 / pl.len()).floor().clip(0, 9).cast(pl.Int8))
    g = d.group_by("dec").agg(pl.col("e").mean(), pl.col(col).median().alias("median_value"), pl.len()).sort("dec")
    return g.to_dicts()


def main(which):
    out = {}
    for key in which:
        unit, label = UNITS[key]
        bets = pl.read_parquet(X / "bet_outcomes" / f"{key}_explore.parquet")
        obs = pl.read_parquet(X / "obsession" / f"explore_{unit}.parquet")
        on = ["user", "artist"] if unit == "artist" else ["user", "recording"]
        if unit == "song":
            bets = bets.rename({"item": "recording"})
        df = bets.join(obs, on=on).filter(pl.col("plays_to_commit") > 0)
        df = df.filter(pl.len().over("user") >= 20).with_columns(lp=pl.col("plays_to_commit").log())
        res = {"label": label, "bets": df.height, "people": df["user"].n_unique()}
        res["within_plays"] = dict(zip(["diff", "ci", "quarter_means", "people"], within(df, "lp", True)))
        res["within_speed"] = dict(zip(["diff", "ci", "quarter_means", "people"], within(df, "weeks_to_commit", False)))
        res["deciles_plays"] = deciles(df, "plays_to_commit")
        res["deciles_speed"] = deciles(df, "weeks_to_commit")
        out[key] = res
        wp, ws = res["within_plays"], res["within_speed"]
        unit_note = "excess log growth" if key.startswith("A") else "excess share sticking"
        print(f"\n{label} ({res['bets']:,} bets, {res['people']:,} people; outcome = {unit_note})")
        print(f"  (a) most-hooked quarter minus least-hooked, within a person: {wp['diff']:+.4f} [{wp['ci'][0]:+.4f}, {wp['ci'][1]:+.4f}]"
              f"   quarters: {', '.join(f'{x:+.4f}' for x in wp['quarter_means'])}")
        print(f"      fastest-committed quarter minus slowest: {ws['diff']:+.4f} [{ws['ci'][0]:+.4f}, {ws['ci'][1]:+.4f}]")
        print("  (b) all bets, by decile of plays before committing: " +
              ", ".join(f"{d['median_value']:.0f}:{d['e']:+.3f}" for d in res["deciles_plays"]))
    (ROOT / "analysis" / "out" / "obsession.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or list(UNITS))
