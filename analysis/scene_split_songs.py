"""Right scenes and right songs (2026-10-13; see SONG_PREREG.md round 3): the song version of the study's scene split
(P7a/P7b; charts_data.py scene_split).

People rated on their song picks up to cutoff C (songs by one artist found the same month count as one pick; shrunk, >= 20),
banded by rank; each song they picked in C+2..C+3, with its artist's scene that year (scenes_yearly, 200 scenes). Tenfold
odds vs similar songs (month x size) split into: scene quality = the tenfold rate expected from the songs' scenes
(month x size x scene) over that from size alone; within scene = their songs' tenfold rate over the scene-and-size
expectation. Overall = scene quality x within scene. Bootstrap over people (1,000 draws).
Writes analysis/out/scene_split_songs_<half>.json (bands and top-1% summary).

Usage: scene_split_songs.py --half explore|sealed|lb
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from cutoffs import cuts  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1717)
B = 1000
BANDS = (("0–25", 0, .25), ("25–50", .25, .5), ("50–75", .5, .75), ("75–90", .75, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0001))
pc = lambda a, q: float(np.percentile(a, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    b = pl.read_parquet(X / "bet_outcomes" / f"A_song_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    sc = pl.read_parquet(X / "scenes_yearly" / ("lb.parquet" if half == "lb" else "explore.parquet"), columns=["artist", "year", "scene_200"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1), x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    b = b.join(b.group_by("m", "bin").agg(s10=pl.col("x10").mean()), on=["m", "bin"]).join(
        b.group_by("m", "bin", "scene_200").agg(s10_sc=pl.col("x10").mean()), on=["m", "bin", "scene_200"])
    groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)
    parts = []
    for c in cuts(half):
        past = (groups.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user"))
    f = pl.concat(parts)
    rows, summ = [], None
    for lab, lo, hi in BANDS:
        per = f.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), es=pl.col("s10_sc").sum())
        h, e, es = (per[c].to_numpy().astype(float) for c in ("h", "e", "es"))
        w = RNG.poisson(1.0, (B, per.height)).astype(float)
        sq, ws, tot = (w @ es) / (w @ e), (w @ h) / (w @ es), (w @ h) / (w @ e)
        r = {"key": lab, "band": f"{lab}%", "mid": (lo + min(hi, 1)) / 2 * 100, "people": per.height, "total": float(h.sum() / e.sum()),
             "total_lo": pc(tot, 2.5), "total_hi": pc(tot, 97.5),
             "scenes": float(es.sum() / e.sum()), "scenes_lo": pc(sq, 2.5), "scenes_hi": pc(sq, 97.5), "scenes_lo99": pc(sq, 0.5),
             "artists": float(h.sum() / es.sum()), "artists_lo": pc(ws, 2.5), "artists_hi": pc(ws, 97.5), "artists_lo99": pc(ws, 0.5)}
        rows.append(r)
        print(f"  {lab:>7}: scenes {r['scenes']:.2f} [{r['scenes_lo']:.2f},{r['scenes_hi']:.2f}] x within {r['artists']:.2f} [{r['artists_lo']:.2f},{r['artists_hi']:.2f}]"
              f" = {r['total']:.2f}  ({per.height:,} people)")
    t = rows[-1]
    print(f"top 1%: scene quality {t['scenes']:.2f} (99% low {t['scenes_lo99']:.2f}); within scene {t['artists']:.2f} (99% low {t['artists_lo99']:.2f}); total {t['total']:.2f}")
    (ROOT / "analysis" / "out" / f"scene_split_songs_{half}.json").write_text(json.dumps({"bands": rows}, indent=1))


if __name__ == "__main__":
    main()
