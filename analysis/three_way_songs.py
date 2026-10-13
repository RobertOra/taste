"""Right scenes x right artists x right songs, for the top 1% of song pickers (2026-10-13; SONG_PREREG.md round 4).

People rated on their song picks up to cutoff C (songs by one artist found the same month count as one pick; shrunk, >= 20),
top 1%; each song they picked in C+2..C+3. Tenfold rates expected from:
  e1 = songs of the same size, same month;  e2 = same size and month in the artist's scene;
  e3 = other people's picked songs by the same artist that year (the person's own picks left out; needs >= 5 of them).
right scenes = e2/e1, right artists = e3/e2, right songs = observed/e3; they multiply to observed/e1 (on the songs with
an e3). Bootstrap over people (1,000 draws). Writes analysis/out/three_way_songs_<half>.json.

Usage: three_way_songs.py --half explore|sealed|lb
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from cutoffs import cuts  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1919)
B = 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    b = pl.read_parquet(X / "bet_outcomes" / f"A_song_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    sc = pl.read_parquet(X / "scenes_yearly" / ("lb.parquet" if half == "lb" else "explore.parquet"), columns=["artist", "year", "scene_200"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1), x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    b = b.join(b.group_by("m", "bin").agg(s1=pl.col("x10").mean()), on=["m", "bin"]).join(
        b.group_by("m", "bin", "scene_200").agg(s2=pl.col("x10").mean()), on=["m", "bin", "scene_200"])
    tot = b.group_by("artist", "year").agg(H=pl.col("x10").sum(), N=pl.len())
    own = b.group_by("user", "artist", "year").agg(h_own=pl.col("x10").sum(), n_own=pl.len())
    b = b.join(tot, on=["artist", "year"]).join(own, on=["user", "artist", "year"]).with_columns(
        n_oth=pl.col("N") - pl.col("n_own"), s3=(pl.col("H") - pl.col("h_own")) / (pl.col("N") - pl.col("n_own")))
    groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)
    parts = []
    for c in cuts(half):
        past = (groups.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user"))
    top = pl.concat(parts).filter(pl.col("q") > 0.99)
    cov = top.filter(pl.col("n_oth") >= 5)
    per = cov.group_by("user").agg(h=pl.col("x10").sum(), e1=pl.col("s1").sum(), e2=pl.col("s2").sum(), e3=pl.col("s3").sum())
    A = {k: per[k].to_numpy().astype(float) for k in ("h", "e1", "e2", "e3")}
    w = RNG.poisson(1.0, (B, per.height)).astype(float)
    out = {"songs": top.height, "covered": cov.height, "people": per.height}
    for name, a, b_ in (("scenes", "e2", "e1"), ("artists", "e3", "e2"), ("songs_within_artist", "h", "e3"), ("overall", "h", "e1")):
        bs = (w @ A[a]) / (w @ A[b_])
        out[name] = {"est": float(A[a].sum() / A[b_].sum()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
                     "lo99": float(np.percentile(bs, 0.5))}
        print(f"  {name:22s} {out[name]['est']:5.2f}x [{out[name]['lo']:.2f}, {out[name]['hi']:.2f}; 99% low {out[name]['lo99']:.2f}]")
    print(f"  top 1% songs {top.height:,}, covered {cov.height:,}, people {per.height:,}")
    (ROOT / "analysis" / "out" / f"three_way_songs_{half}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
