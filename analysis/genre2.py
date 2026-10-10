"""Genre, continued: is taste general or genre-specific, which genres do good pickers favour, and is the genre gap just
spread? (post-freeze; one run per half)

Genres as in analysis/genre.py (top MusicBrainz genre, grouped into families). Artist picks, frozen prescience score.
1. General vs specific: rate people separately on their earlier picks in genre A (>= 15 picks there, up to cutoff C,
   2007..2009), and judge their later picks (C+2..C+3) in genre A and in all other genres. Each pick compared with
   similar same-genre picks. Top fifth (by genre-A record) minus bottom fifth, later growth: in the same genre vs in other
   genres. If taste were fully general, the two gaps would match; if fully genre-specific, the other-genre gap would be 0.
2. Favourites: share of each genre among the later picks of the top fifth vs the bottom fifth (overall ranking).
3. Spread: each genre's gap (analysis/genre.py design) divided by the spread (SD) of its picks' growth vs similar.
Bootstrap over people (500 draws).

Usage: genre2.py --half explore|sealed
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutoffs import cuts, picker_cuts, genre_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1717)
B = 500
MAIN = [n for n, _ in FAMILIES]


def pct(x, q):
    return float(np.percentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    g = pl.read_parquet(genre_path(half), columns=["artist", "top_genre"]).with_columns(fam=family_expr())
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    bg = b.join(g.select("artist", "fam"), on="artist", how="inner").filter(pl.col("fam") != "Other")
    exp = bg.group_by("m", "bin", "fam").agg(ve=pl.col("v").mean())
    bg = bg.join(exp, on=["m", "bin", "fam"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    out = {}

    # 1. general vs specific
    rows, gboot = [], {"same": [], "other": []}
    for fam in MAIN:
        parts_same, parts_other = [], []
        for c in cuts(half):
            past = (bg.filter((pl.col("year") <= c) & (pl.col("fam") == fam)).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                    .filter(pl.col("n") >= 15).with_columns(q=pl.col("s").rank("average") / pl.len()))
            fut = bg.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user").with_columns(u=pl.col("user") * 100 + (c - 2000))
            parts_same.append(fut.filter(pl.col("fam") == fam)); parts_other.append(fut.filter(pl.col("fam") != fam))
        res = {"key": fam, "family": fam}
        for lab, dd in (("same", pl.concat(parts_same)), ("other", pl.concat(parts_other))):
            top = dd.filter(pl.col("q") > .8).group_by("u").agg(g=pl.col("gx").sum(), n=pl.len())
            bot = dd.filter(pl.col("q") <= .2).group_by("u").agg(g=pl.col("gx").sum(), n=pl.len())
            wt, wb = RNG.poisson(1.0, (B, top.height)).astype(float), RNG.poisson(1.0, (B, bot.height)).astype(float)
            gap = (np.expm1((wt @ top["g"].to_numpy()) / (wt @ top["n"].to_numpy().astype(float)))
                   - np.expm1((wb @ bot["g"].to_numpy()) / (wb @ bot["n"].to_numpy().astype(float))))
            est = float(np.expm1(top["g"].sum() / top["n"].sum()) - np.expm1(bot["g"].sum() / bot["n"].sum()))
            res[f"gap_{lab}"], res[f"gap_{lab}_lo"], res[f"gap_{lab}_hi"] = est, pct(gap, 2.5), pct(gap, 97.5)
            res[f"people_{lab}"] = top.height + bot.height
            gboot[lab].append(gap)
        rows.append(res)
        print(f"  rated on {fam:24s}: later picks in the same genre gap {res['gap_same']:+.1%} [{res['gap_same_lo']:+.1%}, {res['gap_same_hi']:+.1%}]"
              f"   in other genres {res['gap_other']:+.1%} [{res['gap_other_lo']:+.1%}, {res['gap_other_hi']:+.1%}]")
    out["general"] = rows
    sm = np.mean([r["gap_same"] for r in rows]); ot = np.mean([r["gap_other"] for r in rows])
    sb_, ob_ = np.mean(gboot["same"], axis=0), np.mean(gboot["other"], axis=0)
    out["general_summary"] = {"same_avg": float(sm), "other_avg": float(ot), "carryover": float(ot / sm),
                              "other_lo": pct(ob_, 2.5), "other_lo99": pct(ob_, 0.5),
                              "same_minus_other": float(sm - ot), "smo_lo": pct(sb_ - ob_, 2.5), "smo_hi": pct(sb_ - ob_, 97.5), "smo_lo99": pct(sb_ - ob_, 0.5)}
    print("  tests:", out["general_summary"])
    print(f"  average: same genre {sm:+.2%}, other genres {ot:+.2%}  -> {ot / sm:.0%} carries over")

    # 2. favourites (overall ranking)
    parts = []
    for c in cuts(half):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(bg.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", "q"), on="user"))
    f = pl.concat(parts)
    top, bot, allp = f.filter(pl.col("q") > .8), f.filter(pl.col("q") <= .2), f
    fav = []
    for fam in MAIN:
        st, sb, sa = (float((x["fam"] == fam).mean()) for x in (top, bot, allp))
        fav.append({"key": fam, "family": fam, "share_top": st, "share_bottom": sb, "share_all": sa, "ratio": st / sb})
    fav.sort(key=lambda r: -r["ratio"])
    out["favourites"] = fav
    print("\n  favourites (share of later picks, top fifth vs bottom fifth):")
    for r in fav:
        print(f"    {r['family']:24s} top {r['share_top']:5.1%}  bottom {r['share_bottom']:5.1%}  ratio {r['ratio']:.2f}")

    # 3. spread-adjusted gaps (genre.py design, overall ranking, same-genre comparison)
    sp, sboot = [], {}
    for fam in MAIN:
        x = f.filter(pl.col("fam") == fam)
        sd = float(x["gx"].std())
        top = x.filter(pl.col("q") > .8).group_by("user").agg(g=pl.col("gx").sum(), n=pl.len())
        bot = x.filter(pl.col("q") <= .2).group_by("user").agg(g=pl.col("gx").sum(), n=pl.len())
        wt, wb = RNG.poisson(1.0, (B, top.height)).astype(float), RNG.poisson(1.0, (B, bot.height)).astype(float)
        sboot[fam] = ((np.expm1((wt @ top["g"].to_numpy()) / (wt @ top["n"].to_numpy().astype(float)))
                       - np.expm1((wb @ bot["g"].to_numpy()) / (wb @ bot["n"].to_numpy().astype(float)))) / sd)
        gap = float(np.expm1(x.filter(pl.col("q") > .8)["gx"].mean()) - np.expm1(x.filter(pl.col("q") <= .2)["gx"].mean()))
        sp.append({"key": fam, "family": fam, "gap": gap, "spread_sd": sd, "gap_in_sd": gap / sd,
                   "gap_in_sd_lo": pct(sboot[fam], 2.5), "gap_in_sd_hi": pct(sboot[fam], 97.5)})
    est_sc = next(r["gap_in_sd"] for r in sp if r["family"] == "Indie & alternative") - next(r["gap_in_sd"] for r in sp if r["family"] == "Rock & punk")
    dd_ = sboot["Indie & alternative"] - sboot["Rock & punk"]
    out["spread_test"] = {"est": float(est_sc), "lo": pct(dd_, 2.5), "hi": pct(dd_, 97.5), "lo99": pct(dd_, 0.5)}
    print("  spread test (indie minus rock, in SDs):", out["spread_test"])
    sp.sort(key=lambda r: -r["gap_in_sd"])
    out["spread"] = sp
    print("\n  gap scaled by each genre's spread of outcomes:")
    for r in sp:
        print(f"    {r['family']:24s} gap {r['gap']:+.1%}  spread (SD) {r['spread_sd']:.2f}  gap in SDs {r['gap_in_sd']:.3f}")
    (ROOT / "analysis" / "out" / f"genre2_{half}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
