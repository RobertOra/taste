"""What makes the best pickers good (post-freeze; one run per half).

Design as analysis/ladder.py / explain.py: people rated on artist picks up to cutoff C (2007..2009), banded by rank; their
picks made in C+2..C+3. Bootstrap over people (500 draws; a person rated at several cutoffs is resampled as one).
- Right scenes vs right picks (top 1%): later picks' 10x odds vs similar artists of the same size (month x size), then vs
  artists of the same size in the same scene (month x size x scene). "Scene quality" = the 10x rate expected from the
  picks' scenes (month x size x scene) over that expected from size alone (month x size).
- Style: past-period pick popularity (percentile within month), focus (share of picks in their main scene), plays
  before committing, picks per year, listens per month. Top 1% vs bottom half.
- Do style traits add up? Person-level later growth vs similar artists predicted from traits alone, from the track
  record alone, and from both (variance explained); and the later 10x odds of the top 1% chosen by traits alone.

Usage: top_pickers.py --half explore|sealed
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from explain import bets_with_bands  # noqa: E402

X = ROOT / "data" / "derived"
RNG = np.random.default_rng(77)
B = 500
TRAITS = ["pick_popularity", "top_scene_share", "scenes", "plays_to_commit", "picks_per_year", "listens_per_month", "mainstream_share", "commit_rate"]


def pct(x, q):
    return float(np.nanpercentile(x, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed", "lb"], required=True)
    half = ap.parse_args().half
    b, f = bets_with_bands(half)
    sc = pl.read_parquet(X / "scenes_yearly" / ("lb.parquet" if half == "lb" else "explore.parquet"), columns=["artist", "year", "scene_200"])
    ob = pl.read_parquet(X / "obsession" / f"{half}_artist.parquet", columns=["user", "artist", "plays_to_commit"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1),
                                                                  x10=(pl.col("v") >= np.log(10)).cast(pl.Float64),
                                                                  pq=pl.col("pen0").rank("average").over("m") / pl.len().over("m"))
    e1 = b.group_by("m", "bin").agg(s10=pl.col("x10").mean(), ve=pl.col("v").mean())
    e2 = b.group_by("m", "bin", "scene_200").agg(s10_sc=pl.col("x10").mean(), ve_sc=pl.col("v").mean())
    f = (f.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1))
         .join(b.select("user", "artist", "m", "pq"), on=["user", "artist", "m"], how="left")
         .join(e1, on=["m", "bin"]).join(e2, on=["m", "bin", "scene_200"])
         .with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), gx=pl.col("v") - pl.col("ve"))
         .join(ob, on=["user", "artist"], how="left"))
    fut, past = f.filter(pl.col("period") == "future"), f.filter(pl.col("period") == "past")

    # Right scenes vs right picks, top 1% (bootstrap over people)
    t = fut.filter(pl.col("band") == "99–100").group_by("user").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), esc=pl.col("s10_sc").sum())
    h, e, esc = (t[c].to_numpy().astype(float) for c in ("h", "e", "esc"))
    w = RNG.poisson(1.0, (B, t.height)).astype(float)
    within, scene_q, total = (w @ h) / (w @ esc), (w @ esc) / (w @ e), (w @ h) / (w @ e)
    res = {"top1_total": {"est": float(h.sum() / e.sum()), "lo": pct(total, 2.5), "hi": pct(total, 97.5)},
           "top1_within_scene": {"est": float(h.sum() / esc.sum()), "lo": pct(within, 2.5), "hi": pct(within, 97.5), "lo99": pct(within, 0.5)},
           "top1_scene_quality": {"est": float(esc.sum() / e.sum()), "lo": pct(scene_q, 2.5), "hi": pct(scene_q, 97.5), "lo99": pct(scene_q, 0.5)}}

    # Style profile (past period): one row per person-cutoff
    uy = pl.read_parquet(X / "user_year_features" / f"{half}.parquet")
    feats = pl.concat([uy.filter(pl.col("year") <= c).group_by("user").agg(
        pl.col("listens").sum(), pl.col("active_months").sum(), pl.col("new_artists").sum(), pl.col("committed").sum(),
        (pl.col("mainstream_plays").sum() / pl.col("artist_plays").sum()).alias("mainstream_share"),
        pl.col("year").n_unique().alias("years")).with_columns(cut=pl.lit(c)) for c in (2007, 2008, 2009)])
    feats = feats.with_columns(listens_per_month=pl.col("listens") / pl.col("active_months"),
                               commit_rate=pl.col("committed") / pl.col("new_artists").clip(1))
    prof = past.group_by("user", "cut", "band", "q").agg(
        picks=pl.len(), pick_popularity=pl.col("pq").mean(), scenes=pl.col("scene_200").n_unique(),
        top_scene_share=pl.col("scene_200").value_counts(sort=True).first().struct.field("count") / pl.len(),
        plays_to_commit=pl.col("plays_to_commit").fill_null(0).log1p().mean())
    prof = prof.join(feats, on=["user", "cut"], how="inner").with_columns(picks_per_year=pl.col("picks") / pl.col("years"))
    res["profile"] = {}
    for lab in ("0–50", "50–75", "75–90", "90–95", "95–99", "99–100"):
        x = prof.filter(pl.col("band") == lab)
        res["profile"][lab] = {"people": x.height, **{c: float(x[c].mean()) for c in TRAITS}}
    res["profile_note"] = "means; plays_to_commit is the mean of log(1 + plays)"
    top, bot = prof.filter(pl.col("band") == "99–100"), prof.filter(pl.col("band") == "0–50")
    tu, bu = top.group_by("user").agg(s=pl.col("pick_popularity").sum(), n=pl.len()), bot.group_by("user").agg(s=pl.col("pick_popularity").sum(), n=pl.len())
    wt, wb = RNG.poisson(1.0, (B, tu.height)), RNG.poisson(1.0, (B, bu.height))
    d = (wb @ bu["s"].to_numpy()) / (wb @ bu["n"].to_numpy()) - (wt @ tu["s"].to_numpy()) / (wt @ tu["n"].to_numpy())
    res["pick_popularity_bottom_minus_top"] = {"est": float(bot["pick_popularity"].mean() - top["pick_popularity"].mean()),
                                               "lo": pct(d, 2.5), "hi": pct(d, 97.5), "lo99": pct(d, 0.5)}

    # Do style traits add up? Person-level later growth vs similar (and 10x hits vs expected)
    pf = fut.group_by("user", "cut").agg(g=pl.col("gx").mean(), n=pl.len(), h=pl.col("x10").sum(), e=pl.col("s10").sum())
    dd = prof.join(pf, on=["user", "cut"]).filter(pl.col("n") >= 10).drop_nulls(TRAITS)
    Z = dd.select(TRAITS).to_numpy().astype(float)
    Z = (Z - Z.mean(0)) / Z.std(0)
    y, q = dd["g"].to_numpy(), dd["q"].to_numpy()

    def r2(M):
        M = np.column_stack([np.ones(len(M)), M])
        coef = np.linalg.lstsq(M, y, rcond=None)[0]
        return float(1 - ((y - M @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()), M @ coef
    r_tr, pred_tr = r2(Z)
    r_q, _ = r2(np.column_stack([q, q ** 2, q ** 3]))
    r_both, _ = r2(np.column_stack([Z, q, q ** 2, q ** 3]))
    res["variance_explained"] = {"traits": r_tr, "track_record": r_q, "both": r_both, "people": int(len(y))}
    sel = pred_tr >= np.quantile(pred_tr, 0.99)
    res["top1_by_traits_odds_10x"] = float(dd["h"].to_numpy()[sel].sum() / dd["e"].to_numpy()[sel].sum())
    selq = q > 0.99
    res["top1_by_record_odds_10x_same_people"] = float(dd["h"].to_numpy()[selq].sum() / dd["e"].to_numpy()[selq].sum())
    res["overlap_top1_traits_record"] = float((sel & selq).sum() / max(selq.sum(), 1))

    print(json.dumps({k: v for k, v in res.items() if k != "profile"}, indent=1))
    for lab, v in res["profile"].items():
        print(f"  {lab:>7} " + "  ".join(f"{k} {x:.3g}" for k, x in v.items()))
    (ROOT / "analysis" / "out" / f"top_pickers_{half}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
