"""Individual songs or song groups? (NOTES.md planned rebuild item 4; exploratory, ListenBrainz reference finds.)

The site (and the study) count songs by one artist found the same month as one find (plays-weighted mean excess). The
alternative counts every song. Same reference people, same per-song results (data/site_v2/_pack_ex_song_A_items.parquet from
build_pack_ref.py), compared on:
  stability: each person's finds split into two halves by artist (an artist's songs all land in one half, so an album can't
    sit in both), score per half (shrunk sum / (n + 10)), Spearman between halves, people with >= 20 finds in each half;
  prediction: score from finds up to 2020 vs score from finds from 2022 on (people with >= 30 finds in each), Spearman.
Usage: SITE_REF=data/site_v2 songs_vs_groups.py [song_A|song_As]
"""
import os
import sys
from pathlib import Path

import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
REF = Path(os.environ.get("SITE_REF", ROOT / "data" / "site"))
key = sys.argv[1] if len(sys.argv) > 1 else "song_A"
items = pl.read_parquet(REF / f"_pack_ex_{key}_items.parquet").with_columns(year=pl.col("m") // 12)
groups = (items.group_by("user", "artist", "m").agg(excess=(pl.col("excess") * pl.col("w")).sum() / pl.col("w").sum())
          .with_columns(year=pl.col("m") // 12))


def shrunk(d, k):
    return d.agg(s=pl.col("excess").sum() / (pl.len() + k), n=pl.len())


def stability(d):
    d = d.with_columns(half=(pl.col("artist").hash(7) % 2))
    h = shrunk(d.group_by("user", "half"), 10).pivot(on="half", index="user", values=["s", "n"]).drop_nulls()
    h = h.filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
    return spearmanr(h["s_0"], h["s_1"]).statistic, h.height


def prediction(d):
    a = shrunk(d.filter(pl.col("year") <= 2020).group_by("user"), 20).filter(pl.col("n") >= 30)
    b = shrunk(d.filter(pl.col("year") >= 2022).group_by("user"), 20).filter(pl.col("n") >= 30)
    j = a.join(b, on="user", suffix="_b")
    return spearmanr(j["s"], j["s_b"]).statistic, j.height


for label, d in (("individual songs", items), ("song groups (current)", groups)):
    st, n1 = stability(d); pr, n2 = prediction(d)
    print(f"{label:24s} stability (halves by artist) {st:.3f} ({n1:,} people) | prediction 2016-2020 -> 2022+ {pr:.3f} ({n2:,} people)"
          f" | finds per person {d.group_by('user').len()['len'].median():.0f}")
