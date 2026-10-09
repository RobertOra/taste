"""What makes good pickers good, how far the takeoff ladder goes, and where each fifth ends up (post-freeze).

1. Transitions (sealed, descriptive): the frozen main candidates' forward test (evaluate.py design: past score up to a
   cutoff, future score 2-3 years later, >= 10 bets in each), full 5x5 table of past fifth -> future fifth.
2. Takeoff thresholds (sealed, descriptive): per band of pickers (ladder.py design), how many of every 1,000 new artists
   grew 2x, 3x, 5x, 10x, 20x, 50x, 100x within a year, vs similar artists (same month and size).
3. Explaining the best pickers (explore, exploratory): past-period profile by band; their later picks' 10x odds vs similar
   artists by size, then by size and scene; by listening volume; and their own track-record odds (regression to the mean).
"""

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
THRESH = [2, 3, 5, 10, 20, 50, 100]
BANDS = [("0–50", 0, .5), ("50–75", .5, .75), ("75–90", .75, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0001)]


def rank(x):
    return (pl.Series(x).rank("average") / len(x)).to_numpy()


def transitions(name):
    agg = pl.read_parquet(CAND / name / "agg.parquet")
    years = sorted(agg["year"].unique().to_list())
    per = lambda d: d.group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    M = np.zeros((5, 5))
    for cut in [y for y in years if y + 2 in years and y >= 2006]:
        past = per(agg.filter(pl.col("year") <= cut)).filter(pl.col("n") >= 10)
        fut = per(agg.filter(pl.col("year").is_between(cut + 2, cut + 3))).filter(pl.col("n") >= 10)
        j = past.select("user", p=pl.col("swe") / pl.col("sw")).join(fut.select("user", f=pl.col("swe") / pl.col("sw")), on="user")
        if j.height < 500:
            continue
        qp = np.minimum((rank(j["p"]) * 5 - 1e-9).astype(int), 4)
        qf = np.minimum((rank(j["f"]) * 5 - 1e-9).astype(int), 4)
        np.add.at(M, (qp, qf), 1)
    return (M / M.sum(1, keepdims=True)).tolist(), M.sum(1).tolist()


def bets_with_bands(half, extra_cols=()):
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "artist", "m", "bin", "v", "e", "pen0", *extra_cols])
    b = b.with_columns(year=pl.col("m") // 12)
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        band = pl.lit(None, pl.String)
        for lab, lo, hi in BANDS:
            band = pl.when((pl.col("q") > lo) & (pl.col("q") <= hi)).then(pl.lit(lab)).otherwise(band)
        past = past.with_columns(band=band, cut=pl.lit(c)).select("user", "q", "band", "cut", n_past="n")
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past, on="user").with_columns(period=pl.lit("future")))
        parts.append(b.filter(pl.col("year") <= c).join(past, on="user").with_columns(period=pl.lit("past")))
    return b, pl.concat(parts)


def thresholds(half):
    b, f = bets_with_bands(half)
    f = f.filter(pl.col("period") == "future")
    out = []
    for t in THRESH:
        lt = float(np.log(t))
        exp = b.group_by("m", "bin").agg(sim=(pl.col("v") >= lt).mean())
        g = f.join(exp, on=["m", "bin"]).with_columns(hit=(pl.col("v") >= lt).cast(pl.Float64))
        for lab, _, _ in BANDS:
            x = g.filter(pl.col("band") == lab)
            out.append({"fold": t, "band": lab, "picks": x.height, "events": int(x["hit"].sum()),
                        "per_1000": float(x["hit"].mean() * 1000), "similar_per_1000": float(x["sim"].mean() * 1000),
                        "times_similar": float(x["hit"].mean() / x["sim"].mean())})
    return out


def explain():
    b, f = bets_with_bands("explore")
    sc = pl.read_parquet(X / "scenes_yearly" / "explore.parquet", columns=["artist", "year", "scene_200"])
    ob = pl.read_parquet(X / "obsession" / "explore_artist.parquet", columns=["user", "artist", "plays_to_commit", "weeks_to_commit"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1))
    f = f.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1))
    b = b.with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64), pq=pl.col("pen0").rank("average").over("m") / pl.len().over("m"))
    e1 = b.group_by("m", "bin").agg(s10=pl.col("x10").mean(), ve=pl.col("v").mean())
    e2 = b.group_by("m", "bin", "scene_200").agg(s10_sc=pl.col("x10").mean(), ve_sc=pl.col("v").mean(), nsc=pl.len())
    f = (f.join(b.select("user", "artist", "m", "pq"), on=["user", "artist", "m"], how="left")
         .join(e1, on=["m", "bin"]).join(e2, on=["m", "bin", "scene_200"])
         .with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64)).join(ob, on=["user", "artist"], how="left"))
    fut, past = f.filter(pl.col("period") == "future"), f.filter(pl.col("period") == "past")

    # Profile (past period, as of the cutoff): one row per person-cutoff, then medians by band.
    uy = pl.read_parquet(X / "user_year_features" / "explore.parquet")
    feats = []
    for c in (2007, 2008, 2009):
        u = uy.filter(pl.col("year") <= c).group_by("user").agg(
            pl.col("listens").sum(), pl.col("active_months").sum(), pl.col("new_artists").sum(), pl.col("committed").sum(),
            (pl.col("mainstream_plays").sum() / pl.col("artist_plays").sum()).alias("mainstream_share"), pl.col("year").n_unique().alias("years"))
        feats.append(u.with_columns(cut=pl.lit(c)))
    feats = pl.concat(feats).with_columns(listens_per_month=pl.col("listens") / pl.col("active_months"),
                                          new_artists_per_year=pl.col("new_artists") / pl.col("years"),
                                          commit_rate=pl.col("committed") / pl.col("new_artists").clip(1))
    pp = past.group_by("user", "cut", "band").agg(
        picks=pl.len(), pick_popularity=pl.col("pq").median(), scenes=pl.col("scene_200").n_unique(),
        top_scene_share=pl.col("scene_200").value_counts(sort=True).first().struct.field("count") / pl.len(),
        plays_to_commit=pl.col("plays_to_commit").median(), weeks_to_commit=pl.col("weeks_to_commit").median())
    prof = pp.join(feats, on=["user", "cut"], how="left").with_columns(picks_per_year=pl.col("picks") / pl.col("years"))
    cols = ["picks_per_year", "listens_per_month", "new_artists_per_year", "commit_rate", "mainstream_share", "pick_popularity",
            "scenes", "top_scene_share", "plays_to_commit", "weeks_to_commit", "years"]
    profile = prof.group_by("band").agg([pl.len().alias("people")] + [pl.col(c).median() for c in cols]).to_dicts()

    # Outcomes: 10x odds vs similar by size, then by size and scene; growth likewise; past odds (regression to the mean).
    dec = []
    for lab, _, _ in BANDS:
        x, xp = fut.filter(pl.col("band") == lab), past.filter(pl.col("band") == lab)
        dec.append({"band": lab, "odds_size": float(x["x10"].sum() / x["s10"].sum()),
                    "odds_size_scene": float(x["x10"].sum() / x["s10_sc"].sum()),
                    "growth_size": float(np.expm1((x["v"] - x["ve"]).mean())), "growth_size_scene": float(np.expm1((x["v"] - x["ve_sc"]).mean())),
                    "past_odds_size": float(xp["x10"].sum() / xp["s10"].sum())})
    # Volume: odds for each band within thirds of past picks per year
    pv = prof.select("user", "cut", "picks_per_year").with_columns(vol=(pl.col("picks_per_year").rank("average") / pl.len() * 3).ceil().clip(1, 3))
    fv = fut.join(pv, on=["user", "cut"])
    vol = []
    for v in (1, 2, 3):
        for lab, _, _ in BANDS:
            x = fv.filter((pl.col("vol") == v) & (pl.col("band") == lab))
            vol.append({"volume_third": v, "band": lab, "people": x.select("user", "cut").unique().height,
                        "odds_size": float(x["x10"].sum() / x["s10"].sum()) if x.height else None})
    # Scene skill vs pick skill: does the top 1% pick better scenes? scene-level expected 10x rate vs size-level
    scen = [{"band": lab, "scene_vs_size": float(fut.filter(pl.col("band") == lab)["s10_sc"].sum() / fut.filter(pl.col("band") == lab)["s10"].sum())}
            for lab, _, _ in BANDS]
    return {"profile": profile, "decomposition": dec, "volume": vol, "scene_quality": scen}


def main():
    out = {"transitions": {}, "thresholds": thresholds("sealed")}
    for n in ("sealed_D_song_main", "sealed_A_artist_main"):
        M, sizes = transitions(n)
        out["transitions"][n] = {"matrix": M, "people_per_row": sizes}
        print(n, "top fifth ->", [f"{v:.1%}" for v in M[4]], " bottom fifth ->", [f"{v:.1%}" for v in M[0]])
    print("\nTHRESHOLDS (sealed): per 1,000 new artists, their / similar (events)")
    for t in THRESH:
        print(f"  {t:>3}x: " + "  ".join(f"{r['band']} {r['per_1000']:.2f}/{r['similar_per_1000']:.2f} ({r['events']})"
                                         for r in out["thresholds"] if r["fold"] == t))
    ex = explain()
    out["explain"] = ex
    print("\nPROFILE (explore, past period, medians)")
    for r in sorted(ex["profile"], key=lambda r: r["band"] or ""):
        print("  " + "  ".join(f"{k} {v:.3g}" if isinstance(v, float) else f"{k} {v}" for k, v in r.items()))
    print("\nDECOMPOSITION (explore): 10x odds vs similar size | + same scene ; growth ; their own past odds")
    for r in ex["decomposition"]:
        print(f"  {r['band']:>7}: {r['odds_size']:.2f} | {r['odds_size_scene']:.2f}   growth {r['growth_size']:+.1%} | {r['growth_size_scene']:+.1%}"
              f"   past odds {r['past_odds_size']:.2f}")
    print("\nSCENE QUALITY: expected 10x rate of their picks' scenes vs size alone")
    print("  " + "  ".join(f"{r['band']} {r['scene_vs_size']:.2f}" for r in ex["scene_quality"]))
    print("\nVOLUME (explore): 10x odds by band within thirds of picks per year")
    for v in (1, 2, 3):
        print(f"  third {v}: " + "  ".join(f"{r['band']} {r['odds_size']:.2f} (n{r['people']})" for r in ex["volume"] if r["volume_third"] == v and r["odds_size"]))
    (ROOT / "analysis" / "out" / "explain.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
