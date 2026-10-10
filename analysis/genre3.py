"""Within a genre, who picks better: people good at that genre, or people good in general? (post-freeze; one run per half)

Genres as in analysis/genre.py. Same people for both rankings: rated (up to cutoff C, 2007..2009) both on their picks in
genre G only (>= 15 picks) and on all their picks (>= 20). Their later picks (C+2..C+3) in genre G, each compared with
similar same-genre picks (same month and size). Groups: top fifth on the genre-G ranking ("genre specialists"), top fifth
on the overall ranking ("good in general"), and everyone in the group (the average picker, which sits near zero by
construction only if the group is typical). Bootstrap over people (500 draws).

Usage: genre3.py --half explore|sealed [--test]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1818)
B = 500
MAIN = [n for n, _ in FAMILIES]


def pct(x, q):
    return float(np.percentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    g = pl.read_parquet(X / "scenes_genre" / "all.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr())
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    b = b.join(g.select("artist", "fam"), on="artist", how="left").with_columns(pl.col("fam").fill_null("Untagged"))
    tagged = b.filter(~pl.col("fam").is_in(["Untagged", "Other"]))
    exp = tagged.group_by("m", "bin", "fam").agg(ve=pl.col("v").mean())
    tagged = tagged.join(exp, on=["m", "bin", "fam"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    rows, diffs = [], []
    test = "--test" in __import__("sys").argv
    for fam in MAIN:
        parts = []
        for c in (2007, 2008, 2009):
            past_all = b.filter(pl.col("year") <= c).group_by("user").agg(sa=pl.col("e").sum() / (pl.len() + 20), na=pl.len())
            past_g = b.filter((pl.col("year") <= c) & (pl.col("fam") == fam)).group_by("user").agg(sg=pl.col("e").sum() / (pl.len() + 20), ng=pl.len())
            ppl = past_all.join(past_g, on="user").filter((pl.col("na") >= 20) & (pl.col("ng") >= 15))
            ppl = ppl.with_columns(qa=pl.col("sa").rank("average") / pl.len(), qg=pl.col("sg").rank("average") / pl.len())
            fut = tagged.filter(pl.col("year").is_between(c + 2, c + 3) & (pl.col("fam") == fam)).join(ppl.select("user", "qa", "qg"), on="user")
            parts.append(fut.with_columns(u=pl.col("user") * 10 + (c - 2000)))
        f = pl.concat(parts)
        res = {"key": fam, "family": fam}
        boots = {}
        for lab, cond in (("specialist", pl.col("qg") > .8), ("general", pl.col("qa") > .8), ("everyone", pl.lit(True))):
            per = f.filter(cond).group_by("u").agg(s=pl.col("gx").sum(), n=pl.len())
            sv, nv = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (B, per.height)).astype(float)
            bs = np.expm1((w @ sv) / (w @ nv)); boots[lab] = bs
            res[lab], res[f"{lab}_lo"], res[f"{lab}_hi"], res[f"{lab}_people"] = float(np.expm1(sv.sum() / nv.sum())), pct(bs, 2.5), pct(bs, 97.5), per.height
        # paired difference specialist - general (people overlap, bootstrap draws are not paired, so this range is conservative)
        res["spec_minus_gen"] = res["specialist"] - res["general"]
        diffs.append(boots["specialist"] - boots["general"])
        res["overlap"] = float(f.filter((pl.col("qg") > .8) & (pl.col("qa") > .8)).select("u").n_unique() / max(1, f.filter(pl.col("qg") > .8).select("u").n_unique()))
        rows.append(res)
        print(f"  {fam:24s} specialists {res['specialist']:+.1%} [{res['specialist_lo']:+.1%},{res['specialist_hi']:+.1%}]  "
              f"good in general {res['general']:+.1%} [{res['general_lo']:+.1%},{res['general_hi']:+.1%}]  everyone {res['everyone']:+.1%}  "
              f"(overlap {res['overlap']:.0%}, {res['everyone_people']:,} person-periods)")
    avg = np.mean(diffs, axis=0)
    summary = {"avg_spec_minus_gen": float(np.mean([r["spec_minus_gen"] for r in rows])), "lo": pct(avg, 2.5), "hi": pct(avg, 97.5), "hi99": pct(avg, 99.5)}
    print("  average specialist minus general:", summary)
    (ROOT / "analysis" / "out" / f"genre3_{half}.json").write_text(json.dumps({"families": rows, "summary": summary}, indent=1))


if __name__ == "__main__":
    main()
