"""Where does taste matter most? Taste by genre (post-freeze; one run per half).

Genres: each artist's top MusicBrainz genre (data/derived/scenes_genre/all.parquet; untagged artists are left out), grouped
into broad families by keyword (first match wins, in the order of FAMILIES). Ladder design (analysis/ladder.py): people
rated on all their artist picks up to cutoff C (frozen prescience score); their picks made in C+2..C+3, grouped by the
pick's genre family. Within a family, each pick is compared with similar picks of the same family (same month and size
bin), so a genre growing overall doesn't count. Per family: growth vs similar for the top and bottom fifth of pickers, the
gap between them, and the top fifth's tenfold-takeoff odds. Bootstrap over people (1,000 draws).

Usage: genre.py --half explore|sealed [--test "TOP|BOTTOM" ...]
"""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1515)
B = 1000
FAMILIES = [
    ("Metal", ["metal", "grindcore", "deathcore", "metalcore", "djent", "sludge", "doom"]),
    ("Hip hop", ["hip hop", "rap", "trap", "grime", "drill"]),
    ("Electronic", ["electronic", "techno", "house", "trance", "dubstep", "drum and bass", "edm", "electro", "ambient", "idm",
                    "downtempo", "synth", "dance", "breakbeat", "garage", "bass", "trip hop", "chillwave", "glitch"]),
    ("Indie & alternative", ["indie", "alternative", "shoegaze", "dream pop", "lo-fi", "post-rock", "emo", "math rock", "noise"]),
    ("Pop", ["pop"]),
    ("Rock & punk", ["rock", "punk", "grunge", "hardcore"]),
    ("Folk & country", ["folk", "country", "singer-songwriter", "americana", "bluegrass"]),
    ("R&B, soul & funk", ["r&b", "soul", "funk", "disco", "gospel", "rhythm and blues"]),
    ("Jazz, blues & classical", ["jazz", "blues", "classical", "baroque", "opera", "soundtrack", "orchestral", "chamber"]),
]


def family_expr():
    e = pl.lit("Other")
    for name, words in reversed(FAMILIES):
        cond = pl.lit(False)
        for w in words:
            cond = cond | pl.col("top_genre").str.contains(w, literal=True)
        e = pl.when(cond).then(pl.lit(name)).otherwise(e)
    return e


def pct(x, q):
    return float(np.percentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    ap.add_argument("--test", nargs="*", default=None, help='pre-registered pairs "TOP|BOTTOM": gap(TOP) - gap(BOTTOM) > 0')
    a = ap.parse_args()
    g = pl.read_parquet(X / "scenes_genre" / "all.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr())
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{a.half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    bg = b.join(g.select("artist", "fam"), on="artist", how="inner")
    bg = bg.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    exp = bg.group_by("m", "bin", "fam").agg(ve=pl.col("v").mean(), s10=pl.col("x10").mean())
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(bg.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user"))
    f = pl.concat(parts).join(exp, on=["m", "bin", "fam"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    print(f"picks with a genre: {f.height:,} of the later picks of rated people")
    rows, boots = [], {}
    for fam in [n for n, _ in FAMILIES] + ["Other"]:
        x = f.filter(pl.col("fam") == fam)
        def grp(lo, hi):
            return x.filter((pl.col("q") > lo) & (pl.col("q") <= hi)).group_by("user").agg(g=pl.col("gx").sum(), n=pl.len(), h=pl.col("x10").sum(), e=pl.col("s10").sum())
        top, bot = grp(.8, 1.01), grp(0, .2)
        if top.height < 200 or bot.height < 200:
            continue
        wt, wb = RNG.poisson(1.0, (B, top.height)).astype(float), RNG.poisson(1.0, (B, bot.height)).astype(float)
        gt = np.expm1((wt @ top["g"].to_numpy()) / (wt @ top["n"].to_numpy().astype(float)))
        gb = np.expm1((wb @ bot["g"].to_numpy()) / (wb @ bot["n"].to_numpy().astype(float)))
        ot = (wt @ top["h"].to_numpy()) / (wt @ top["e"].to_numpy())
        gap = gt - gb
        boots[fam] = gap
        est_t = float(np.expm1(top["g"].sum() / top["n"].sum())); est_b = float(np.expm1(bot["g"].sum() / bot["n"].sum()))
        rows.append({"key": fam, "family": fam, "picks": x.height, "top_people": top.height, "bottom_people": bot.height,
                     "top_growth": est_t, "bottom_growth": est_b, "gap": est_t - est_b, "gap_lo": pct(gap, 2.5), "gap_hi": pct(gap, 97.5),
                     "top_odds_10x": float(top["h"].sum() / top["e"].sum()), "top_odds_lo": pct(ot, 2.5), "top_odds_hi": pct(ot, 97.5)})
    rows.sort(key=lambda r: -r["gap"])
    for r in rows:
        print(f"  {r['family']:24s} picks {r['picks']:>9,}  top {r['top_growth']:+6.1%}  bottom {r['bottom_growth']:+6.1%}  gap {r['gap']:+6.1%} "
              f"[{r['gap_lo']:+.1%}, {r['gap_hi']:+.1%}]  top fifth 10x {r['top_odds_10x']:.2f}x")
    out = {"families": rows}
    if a.test:
        out["tests"] = []
        for pair in a.test:
            t_, b_ = pair.split("|")
            d = boots[t_] - boots[b_]
            est = next(r["gap"] for r in rows if r["family"] == t_) - next(r["gap"] for r in rows if r["family"] == b_)
            out["tests"].append({"top": t_, "bottom": b_, "est": est, "lo": pct(d, 2.5), "hi": pct(d, 97.5), "lo99": pct(d, 0.5)})
            print("test:", out["tests"][-1])
    (ROOT / "analysis" / "out" / f"genre_{a.half}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
