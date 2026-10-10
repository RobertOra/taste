"""Is taste general? Predicting a genre from the person's other genres only (post-freeze; one run per half).

Genres as in analysis/genre.py. Same people rated two ways up to cutoff C (2007..2009): on their picks in genre G only
(>= 15 picks) and on their picks in all other genres only (>= 20). Their later picks (C+2..C+3) in genre G, each compared
with similar same-genre picks (same month and size). Top fifth on each ranking; also everyone in the group. If taste were
fully general, the other-genres ranking would predict genre G as well as the genre-G ranking.
Also, per genre: share of picks of artists already in the data by April 2005 ("established"), popularity percentile.
Bootstrap over people (500 draws).

Usage: genre4.py --half explore|sealed
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1919)
B = 500
MAIN = [n for n, _ in FAMILIES]


def pct(x, q):
    return float(np.percentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    g = pl.read_parquet(X / "scenes_genre" / "all.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr())
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e", "pen0"]).with_columns(year=pl.col("m") // 12)
    b = b.join(g.select("artist", "fam"), on="artist", how="left").with_columns(pl.col("fam").fill_null("Untagged"))
    con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6")
    fs = con.execute(f"SELECT artist, min(month) AS fm FROM read_parquet('{X}/user_artist_month/{half}/*.parquet') GROUP BY artist").pl()
    b = b.join(fs, on="artist", how="left").with_columns(pq=pl.col("pen0").rank("average").over("m") / pl.len().over("m"),
                                                        established=(pl.col("fm") <= 2005 * 12 + 3))
    tagged = b.filter(~pl.col("fam").is_in(["Untagged", "Other"]))
    exp = tagged.group_by("m", "bin", "fam").agg(ve=pl.col("v").mean())
    tagged = tagged.join(exp, on=["m", "bin", "fam"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    rows, diffs = [], []
    for fam in MAIN:
        parts = []
        for c in (2007, 2008, 2009):
            pg = b.filter((pl.col("year") <= c) & (pl.col("fam") == fam)).group_by("user").agg(sg=pl.col("e").sum() / (pl.len() + 20), ng=pl.len())
            po = b.filter((pl.col("year") <= c) & (pl.col("fam") != fam)).group_by("user").agg(so=pl.col("e").sum() / (pl.len() + 20), no=pl.len())
            ppl = pg.join(po, on="user").filter((pl.col("ng") >= 15) & (pl.col("no") >= 20))
            ppl = ppl.with_columns(qg=pl.col("sg").rank("average") / pl.len(), qo=pl.col("so").rank("average") / pl.len())
            parts.append(tagged.filter(pl.col("year").is_between(c + 2, c + 3) & (pl.col("fam") == fam)).join(ppl.select("user", "qg", "qo"), on="user")
                         .with_columns(u=pl.col("user") * 10 + (c - 2000)))
        f = pl.concat(parts)
        x_all = tagged.filter(pl.col("fam") == fam)
        res = {"key": fam, "family": fam, "established": float(x_all["established"].mean()), "popularity_pct": float(x_all["pq"].median() * 100)}
        boots = {}
        for lab, cond in (("this_genre", pl.col("qg") > .8), ("other_genres", pl.col("qo") > .8), ("everyone", pl.lit(True))):
            per = f.filter(cond).group_by("u").agg(s=pl.col("gx").sum(), n=pl.len())
            sv, nv = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (B, per.height)).astype(float)
            bs = np.expm1((w @ sv) / (w @ nv)); boots[lab] = bs
            res[lab], res[f"{lab}_lo"], res[f"{lab}_hi"], res[f"{lab}_people"] = float(np.expm1(sv.sum() / nv.sum())), pct(bs, 2.5), pct(bs, 97.5), per.height
        diffs.append(boots["this_genre"] - boots["other_genres"])
        rows.append(res)
        print(f"  {fam:24s} this genre {res['this_genre']:+.1%}  other genres only {res['other_genres']:+.1%}  everyone {res['everyone']:+.1%}  "
              f"established {res['established']:.0%}")
    avg = np.mean(diffs, axis=0)
    summary = {"avg_this_minus_other": float(np.mean([r["this_genre"] - r["other_genres"] for r in rows])),
               "avg_this": float(np.mean([r["this_genre"] for r in rows])), "avg_other": float(np.mean([r["other_genres"] for r in rows])),
               "lo": pct(avg, 2.5), "hi": pct(avg, 97.5), "hi99": pct(avg, 99.5)}
    summary["share_general"] = summary["avg_other"] / summary["avg_this"]
    print("  summary:", summary)
    (ROOT / "analysis" / "out" / f"genre4_{half}.json").write_text(json.dumps({"families": rows, "summary": summary}, indent=1))


if __name__ == "__main__":
    main()
