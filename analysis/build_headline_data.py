"""Data for the write-up's headline sections (analysis/writeup/*.json; see also analysis/charts_data.py).

headlines.json  P1-P3 as confirmed on the sealed half (SPEC.md, "Headline confirmation"), with explore values.
takeoff.json    explore half: best vs worst fifth of pickers, chance of growing at least 1.5x ... 40x (descriptive).
agree.json      explore half: artists newly picked only by good, ordinary, or poor pickers (1, 2, 3+), vs similar artists.
obsession.json  explore half: each person's most-hooked quarter of picks vs least-hooked (exploratory).
"""

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
OUT = ROOT / "analysis" / "out"
W = ROOT / "analysis" / "writeup"


def headlines(H="sealed"):  # H: the half reported as 'hidden' (sealed, or lb for ListenBrainz)
    hs, he = (json.loads((OUT / f"headlines_{h}.json").read_text()) for h in (H, "explore"))
    ps, pe = (json.loads((OUT / f"pickers_A{s}.json").read_text()) for s in (f"_{H}", ""))
    rows = []
    for key, claim, k, t in (("P1a", "Best vs worst pickers' picks: grew 10× or more", "H3", "10x"),
                             ("P1b", "Best vs worst pickers' picks: grew 4× or more", "H3", "4x")):
        r, e = hs[k], he[k]
        rows.append({"key": key, "claim": claim, "unit": "times as often", "hidden": r[f"ratio_{t}"], "lo": r[f"ratio_{t}_ci"][0],
                     "hi": r[f"ratio_{t}_ci"][1], "lo99": r[f"ratio_{t}_ci"][2], "first_half": e[f"ratio_{t}"],
                     "rate": r["best"][f"rate_{t}"], "rate_compared": r["worst"][f"rate_{t}"], "confirmed": r[f"ratio_{t}_ci"][2] > 1})
    for key, claim, t in (("P2a", "3+ good pickers agree vs similar artists: grew 4× or more", "4x"),
                          ("P2b", "3+ good pickers agree vs similar artists: grew 10× or more", "10x")):
        r, e = hs["H2"], he["H2"]
        ci = r[f"best_vs_similar_{t}_ci"]
        rows.append({"key": key, "claim": claim, "unit": "times as often", "hidden": r[f"best_vs_similar_{t}"], "lo": ci[0], "hi": ci[1],
                     "lo99": ci[2], "first_half": e[f"best_vs_similar_{t}"], "rate": r["best"][f"rate_{t}"],
                     "rate_compared": r["best"][f"rate_{t}_similar"], "confirmed": ci[2] > 1})
    for key, claim, v in (("P3a", "One ordinary picker swapped for a good one: extra growth", "no_scene"),
                          ("P3b", "The same, compared within the same scene", "scene")):
        g, ge = ps[v]["g"], pe[v]["g"]
        rows.append({"key": key, "claim": claim, "unit": "more growth", "hidden": float(np.expm1(g["good_vs_ordinary"])),
                     "lo": float(np.expm1(g["good_ci"][0])), "hi": float(np.expm1(g["good_ci"][1])), "lo99": float(np.expm1(g["good_ci"][2])),
                     "first_half": float(np.expm1(ge["good_vs_ordinary"])), "rate": None, "rate_compared": None,
                     "confirmed": g["good_ci"][2] > 0})
    ls, le = (json.loads((OUT / f"ladder_{h}.json").read_text()) for h in (H, "explore"))
    su, se = ls["summary"], le["summary"]
    rows.append({"key": "P4a", "claim": "Top 1% of pickers' picks vs similar artists: grew 10× or more", "unit": "times as often",
                 "hidden": su["top1_odds_10x"], "lo": su["top1_lo"], "hi": su["top1_hi"], "lo99": su["top1_lo99"],
                 "first_half": se["top1_odds_10x"], "rate": None, "rate_compared": None, "confirmed": su["top1_lo99"] > 2})
    rows.append({"key": "P4b", "claim": "Top 1% vs the 90–95% band: chance of growing 10×", "unit": "times as often",
                 "hidden": su["top1_vs_90_95"], "lo": su["top1_vs_90_95_lo"], "hi": su["top1_vs_90_95_hi"], "lo99": su["top1_vs_90_95_lo99"],
                 "first_half": se["top1_vs_90_95"], "rate": None, "rate_compared": None, "confirmed": su["top1_vs_90_95_lo99"] > 1})
    cs, ce = ls["crowd_summary"], le["crowd_summary"]
    rows.append({"key": "P5a", "claim": "Niche artist found by 2 good pickers vs none: extra growth", "unit": "more growth",
                 "hidden": cs["niche_2_vs_0"], "lo": cs["niche_2_vs_0_lo"], "hi": cs["niche_2_vs_0_hi"], "lo99": cs["niche_2_vs_0_lo99"],
                 "first_half": ce["niche_2_vs_0"], "rate": None, "rate_compared": None, "confirmed": cs["niche_2_vs_0_lo99"] > 0})
    for k, lab in (("niche", "niche"), ("crowded", "crowded")):
        rows.append({"key": f"slope_{k}", "claim": f"Each good picker, {lab} artists (descriptive)", "unit": "more growth",
                     "hidden": cs["slopes"][k]["per_picker"], "lo": cs["slopes"][k]["lo"], "hi": cs["slopes"][k]["hi"], "lo99": None,
                     "first_half": ce["slopes"][k]["per_picker"], "rate": None, "rate_compared": None, "confirmed": None})
    rows.append({"key": "P5b", "claim": "Each good picker adds more for niche than crowded artists (difference)", "unit": "more growth",
                 "hidden": float(np.expm1(cs["slope_niche_minus_crowded"])), "lo": float(np.expm1(cs["slope_diff_lo"])),
                 "hi": float(np.expm1(cs["slope_diff_hi"])), "lo99": float(np.expm1(cs["slope_diff_lo99"])),
                 "first_half": float(np.expm1(ce["slope_niche_minus_crowded"])), "rate": None, "rate_compared": None,
                 "confirmed": cs["slope_diff_lo99"] > 0})
    gs, ge = ls["count_vs_share"], le["count_vs_share"]
    rows.append({"key": "P5c", "claim": "Each good new fan vs each ordinary new fan: extra growth", "unit": "more growth",
                 "hidden": gs["good_minus_ordinary"]["effect"], "lo": gs["good_minus_ordinary"]["lo"], "hi": gs["good_minus_ordinary"]["hi"],
                 "lo99": gs["good_minus_ordinary"]["lo99"], "first_half": ge["good_minus_ordinary"]["effect"], "rate": None,
                 "rate_compared": None, "confirmed": gs["good_minus_ordinary"]["lo99"] > 0})
    for k, lab in (("n_ord", "Each ordinary new fan (descriptive)"), ("n_poor", "Each poor new fan (descriptive)"), ("n_good", "Each good new fan (descriptive)")):
        rows.append({"key": k, "claim": lab, "unit": "more growth", "hidden": gs[k]["effect"], "lo": gs[k]["lo"], "hi": gs[k]["hi"],
                     "lo99": None, "first_half": ge[k]["effect"], "rate": None, "rate_compared": None, "confirmed": None})
    fv = json.loads((OUT / f"fan_value_{H}.json").read_text())
    fe = json.loads((OUT / "fan_value_explore.json").read_text())
    pick = lambda d, k: next(r for r in d["rows"] if r["key"] == k)
    for key, claim, k, t in (("P6a", "Small artist: a good new fan vs an ordinary one, extra growth", "size:small:good_minus_ordinary", "P6a_small_good_minus_ordinary"),
                             ("P6b", "That gap, small artists minus big artists", None, "P6b_gap_small_minus_big")):
        if k:
            r, e = pick(fv, k), pick(fe, k)
            hidden, lo, hi, first = r["effect"], r["lo"], r["hi"], e["effect"]
        else:
            hidden, lo, hi, first = fv["tests"][t]["est"], None, None, fe["tests"][t]["est"]
        rows.append({"key": key, "claim": claim, "unit": "more growth", "hidden": float(np.expm1(hidden)),
                     "lo": None if lo is None else float(np.expm1(lo)), "hi": None if hi is None else float(np.expm1(hi)),
                     "lo99": float(np.expm1(fv["tests"][t]["lo99"])), "first_half": float(np.expm1(first)), "rate": None,
                     "rate_compared": None, "confirmed": fv["tests"][t]["lo99"] > 0})
    ts, te = (json.loads((OUT / f"top_pickers_{h}.json").read_text()) for h in (H, "explore"))
    for key, claim, unit, k in (("P7a", "Top 1%'s artists vs the same size and scene: tenfold takeoffs", "times as often", "top1_within_scene"),
                                ("P7b", "Top 1%'s scenes vs size alone: tenfold takeoffs", "times as often", "top1_scene_quality"),
                                ("P7c", "Top 1%'s picks less popular than the bottom half's", "points", "pick_popularity_bottom_minus_top")):
        est, fe = ts[k], te[k]
        rows.append({"key": key, "claim": claim, "unit": unit, "hidden": est["est"], "lo": est["lo"], "hi": est["hi"], "lo99": est["lo99"],
                     "first_half": fe["est"], "rate": None, "rate_compared": None, "confirmed": est["lo99"] > (0 if unit == "points" else 1)})
    ob = json.loads((OUT / f"obsession_{H}.json").read_text())["A_artist"]["within_plays"]
    obe = json.loads((OUT / "obsession.json").read_text())["A_artist"]["within_plays"]
    rows.append({"key": "P8", "claim": "Each person's most-hooked quarter of artist picks vs their least-hooked: extra growth", "unit": "more growth",
                 "hidden": float(np.expm1(ob["diff"])), "lo": float(np.expm1(ob["ci"][0])), "hi": float(np.expm1(ob["ci"][1])),
                 "lo99": float(np.expm1(ob["lo99"])), "first_half": float(np.expm1(obe["diff"])), "rate": None, "rate_compared": None,
                 "confirmed": ob["lo99"] > 0})
    t9, t9e = (json.loads((OUT / f"obs_taste_{h}.json").read_text())["test"] for h in (H, "explore"))
    rows.append({"key": "P9", "claim": "Getting hooked pays off more for top-fifth than bottom-fifth pickers (difference)", "unit": "points",
                 "hidden": t9["diff"], "lo": t9["lo"], "hi": t9["hi"], "lo99": t9["lo99"], "first_half": t9e["diff"], "rate": None,
                 "rate_compared": None, "confirmed": t9["lo99"] > 0})
    rs, re_ = (json.loads((OUT / f"recency_{h}.json").read_text())["tests"] for h in (H, "explore"))
    for key, claim, unit, est, fe, bar in (
            ("P10a", "Recent top fifth with a poor old record vs old top fifth with a poor recent record: tenfold takeoffs", "times as often", rs["P10a"], re_["P10a"], 1),
            ("P10b", "Recent record separates people more than the old one (log spread difference)", "log", rs["P10b"], re_["P10b"], 0),
            ("P10c", "Same top pickers, 2 years later vs 4 years later: tenfold takeoffs", "times as often", rs["P10c"], re_["P10c"], 1)):
        rows.append({"key": key, "claim": claim, "unit": unit, "hidden": est["est"], "lo": est["lo"], "hi": est["hi"], "lo99": est["lo99"],
                     "first_half": fe["est"], "rate": None, "rate_compared": None, "confirmed": est["lo99"] > bar})
    rows.append({"key": "P10b_recent", "claim": "Recent record: top vs bottom fifth, tenfold takeoffs (descriptive)", "unit": "times as often",
                 "hidden": rs["P10b"]["recent_spread"], "lo": None, "hi": None, "lo99": None, "first_half": re_["P10b"]["recent_spread"],
                 "rate": None, "rate_compared": None, "confirmed": None})
    rows.append({"key": "P10b_old", "claim": "Old record, once the recent one is known: top vs bottom fifth (descriptive)", "unit": "times as often",
                 "hidden": rs["P10b"]["old_spread"], "lo": None, "hi": None, "lo99": None, "first_half": re_["P10b"]["old_spread"],
                 "rate": None, "rate_compared": None, "confirmed": None})
    bs_, be_ = (json.loads((OUT / f"bad_taste_{h}.json").read_text())["tests"] for h in (H, "explore"))
    for key, claim, unit, k, bar in (("P11a", "Bottom-fifth pickers' picks vs middle-fifth pickers': flops", "times as often", "P11a_bottom_flop_vs_middle", 1),
                                     ("P11c", "Top-fifth pickers' picks vs middle-fifth pickers': flops (bolder bets)", "times as often", "P11c_top_flop_vs_middle", 1),
                                     ("P11b", "Good taste helps more than bad taste hurts (difference in growth)", "points", "P11b_asymmetry", 0)):
        rows.append({"key": key, "claim": claim, "unit": unit, "hidden": bs_[k]["est"], "lo": bs_[k]["lo"], "hi": bs_[k]["hi"], "lo99": bs_[k]["lo99"],
                     "first_half": be_[k]["est"], "rate": None, "rate_compared": None, "confirmed": bs_[k]["lo99"] > bar})
    ls_, le_ = (json.loads((OUT / f"learning_{h}.json").read_text())["years 1-2 vs 3-4"] for h in (H, "explore"))
    rows.append({"key": "P12", "claim": "Same people, experience years 3-4 vs 1-2: extra growth of their new artists", "unit": "points",
                 "hidden": ls_["change"], "lo": ls_["lo"], "hi": ls_["hi"], "lo99": ls_["lo99"], "first_half": le_["change"],
                 "rate": None, "rate_compared": None, "confirmed": ls_["lo99"] > 0})
    gs_ = json.loads((OUT / f"genre_{H}.json").read_text())["tests"]
    ge_ = {r["family"]: r["gap"] for r in json.loads((OUT / "genre_explore.json").read_text())["families"]}
    for key, t in zip(("P13a", "P13b"), gs_):
        rows.append({"key": key, "claim": f"Taste matters more in {t['top']} than in {t['bottom']} (gap difference)", "unit": "points",
                     "hidden": t["est"], "lo": t["lo"], "hi": t["hi"], "lo99": t["lo99"], "first_half": ge_[t["top"]] - ge_[t["bottom"]],
                     "rate": None, "rate_compared": None, "confirmed": t["lo99"] > 0})
    g2s, g2e = (json.loads((OUT / f"genre2_{h}.json").read_text()) for h in (H, "explore"))
    rows.append({"key": "P14a", "claim": "Rated on one genre, people separate on later picks in other genres (average gap)", "unit": "points",
                 "hidden": g2s["general_summary"]["other_avg"], "lo": g2s["general_summary"]["other_lo"], "hi": None,
                 "lo99": g2s["general_summary"]["other_lo99"], "first_half": g2e["general_summary"]["other_avg"], "rate": None,
                 "rate_compared": None, "confirmed": g2s["general_summary"]["other_lo99"] > 0})
    rows.append({"key": "P14b", "claim": "The same-genre gap exceeds the other-genre gap (average)", "unit": "points",
                 "hidden": g2s["general_summary"]["same_minus_other"], "lo": g2s["general_summary"]["smo_lo"], "hi": g2s["general_summary"]["smo_hi"],
                 "lo99": g2s["general_summary"]["smo_lo99"], "first_half": g2e["general_summary"]["same_minus_other"], "rate": None,
                 "rate_compared": None, "confirmed": g2s["general_summary"]["smo_lo99"] > 0})
    rows.append({"key": "P14c", "claim": "Scaled by each genre's spread, taste matters more in Indie & alternative than in Rock & punk", "unit": "log",
                 "hidden": g2s["spread_test"]["est"], "lo": g2s["spread_test"]["lo"], "hi": g2s["spread_test"]["hi"], "lo99": g2s["spread_test"]["lo99"],
                 "first_half": g2e["spread_test"]["est"], "rate": None, "rate_compared": None, "confirmed": g2s["spread_test"]["lo99"] > 0})
    g3s, g3e = (json.loads((OUT / f"genre3_{h}.json").read_text())["summary"] for h in (H, "explore"))
    rows.append({"key": "P15", "claim": "Within genres, genre specialists don't beat good-in-general pickers by more than 1 point (average difference)",
                 "unit": "points", "hidden": g3s["avg_spec_minus_gen"], "lo": g3s["lo"], "hi": g3s["hi"], "lo99": None,
                 "first_half": g3e["avg_spec_minus_gen"], "rate": None, "rate_compared": None, "confirmed": g3s["hi99"] < 0.01})
    g4s, g4e = (json.loads((OUT / f"genre4_{h}.json").read_text())["summary"] for h in (H, "explore"))
    rows.append({"key": "P16", "claim": "Rated on other genres only, people predict a genre within 1 point of their record in that genre (average)",
                 "unit": "points", "hidden": g4s["avg_this_minus_other"], "lo": g4s["lo"], "hi": g4s["hi"], "lo99": None,
                 "first_half": g4e["avg_this_minus_other"], "rate": None, "rate_compared": None, "confirmed": g4s["hi99"] < 0.01})
    rows.append({"key": "H2growth", "claim": "3+ good pickers agree: growth vs similar artists (descriptive)", "unit": "more growth",
                 "hidden": hs["H2"]["best"]["growth_vs_similar"], "lo": None, "hi": None, "lo99": None,
                 "first_half": he["H2"]["best"]["growth_vs_similar"], "rate": None, "rate_compared": None, "confirmed": None})
    return rows


def best_worst(b):
    b = b.with_columns(year=pl.col("m") // 12)
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        past = past.with_columns(grp=pl.when(pl.col("q") > 0.8).then(pl.lit("best")).when(pl.col("q") <= 0.2).then(pl.lit("worst"))
                                 .otherwise(None)).drop_nulls("grp").select("user", "grp")
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past, on="user"))
    return pl.concat(parts)


def takeoff():
    b = pl.read_parquet(X / "bet_outcomes" / "A_artist_explore.parquet", columns=["user", "m", "bin", "v", "e"])
    f = best_worst(b)
    rows = []
    for t in (1.5, 2, 3, 4, 6, 10, 20, 40):
        lt = float(np.log(t))
        exp = b.group_by("m", "bin").agg(sim=(pl.col("v") >= lt).mean())
        g = f.join(exp, on=["m", "bin"]).with_columns(hit=(pl.col("v") >= lt).cast(pl.Float64))
        bb, ww = g.filter(pl.col("grp") == "best"), g.filter(pl.col("grp") == "worst")
        rows.append({"threshold": t, "label": f"{t:g}×", "best": float(bb["hit"].mean()), "worst": float(ww["hit"].mean()),
                     "similar": float(bb["sim"].mean()), "vs_worst": float(bb["hit"].mean() / ww["hit"].mean()),
                     "vs_similar": float(bb["hit"].mean() / bb["sim"].mean()), "best_events": int(bb["hit"].sum())})
    return rows


def agree():
    df = pl.read_parquet(X / "pickers" / "rate_A_explore.parquet")
    df = df.with_columns(n_rated=pl.col("n_good") + pl.col("n_poor") + pl.col("n_ord")).filter(pl.col("n_rated") >= 1)
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(),
                         sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         nb=pl.col("n_rated").clip(1, 6), ub=pl.col("n_unrated").clip(0, 4))
    df = df.with_columns(x4=(pl.col("g") >= np.log(4)).cast(pl.Float64))
    cell = ["m", "sz", "mo", "nb", "ub"]
    df = df.with_columns(cs=pl.len().over(cell)).filter(pl.col("cs") >= 2)
    df = df.with_columns([((pl.col(v).sum().over(cell) - pl.col(v)) / (pl.col("cs") - 1)).alias(v + "_exp") for v in ("g", "x4")])
    rows = []
    for k, lab in ((1, "1 person"), (2, "2 people"), (3, "3 or more")):
        dk = df.filter(pl.col("n_rated") == k) if k < 3 else df.filter(pl.col("n_rated") >= 3)
        for kind, col in (("good", "n_good"), ("ordinary", "n_ord"), ("poor", "n_poor")):
            x = dk.filter(pl.col(col) == pl.col("n_rated"))
            rows.append({"key": f"{k}-{kind}", "pickers": lab, "kind": kind, "artist_months": x.height,
                         "growth": float(np.expm1((x["g"] - x["g_exp"]).mean())),
                         "takeoff4": float(x["x4"].mean()), "takeoff4_similar": float(x["x4_exp"].mean())})
    return rows


def obsession():
    """Artists: hidden half (P8 confirmed); songs: first half only."""
    os_, oe = json.loads((OUT / "obsession_sealed.json").read_text()), json.loads((OUT / "obsession.json").read_text())
    rows = []
    for k, lab, src, half in (("A_artist", "Artists", os_, "Hidden half"), ("A_song", "Songs", oe, "First half")):
        w = src[k]["within_plays"]
        rows.append({"level": lab, "half": half, "most_vs_least": float(np.expm1(w["diff"])), "lo": float(np.expm1(w["ci"][0])),
                     "hi": float(np.expm1(w["ci"][1])), "people": w["people"],
                     "least_quarter": float(np.expm1(w["quarter_means"][0])), "most_quarter": float(np.expm1(w["quarter_means"][3]))})
    return rows


def recency():
    r = json.loads((OUT / "recency_sealed.json").read_text())
    return [{"kind": "fifth", **m} for m in r["marginal"]] + [{"kind": "top", **t} for t in r["topshares"]]


def fanrel():
    rows = json.loads((OUT / "fan_value_sealed.json").read_text())["rows"]
    out = []
    for r in rows:
        if r["stage_type"] == "size" and r["fan"] in ("good_minus_ordinary", "poor_minus_ordinary"):
            out.append({"key": f"{r['stage']}:{r['fan'].split('_')[0]}", "stage": r["stage"], "fan": r["fan"].split("_")[0],
                        "effect": float(np.expm1(r["effect"])), "lo": float(np.expm1(r["lo"])), "hi": float(np.expm1(r["hi"]))})
    return out


def badtaste():
    r = json.loads((OUT / "bad_taste_sealed.json").read_text())
    rows = [{"kind": "group", **g} for g in r["groups"]]
    rows.append({"kind": "summary", "key": "persistence", "band": None, "mid": None, "people": None,
                 "top_stays_top": r["persistence"]["top_stays_top"], "bottom_stays_bottom": r["persistence"]["bottom_stays_bottom"],
                 "top_above": r["tests"]["P11b_asymmetry"]["top_minus_all"], "bottom_below": -r["tests"]["P11b_asymmetry"]["all_minus_bottom"]})
    return rows


def learning():
    r = json.loads((OUT / "learning_sealed.json").read_text())
    rows = [{"kind": "year", **c} for c in r["curve"]]
    c = r["years 1-2 vs 3-4"]
    rows.append({"kind": "summary", "key": "change", "year": None, "growth": c["change"], "lo": c["lo"], "hi": c["hi"], "people": c["people"],
                 "early": c["early"], "late": c["late"]})
    return rows


def genre():
    rows = json.loads((OUT / "genre_sealed.json").read_text())["families"]
    g2 = json.loads((OUT / "genre2_sealed.json").read_text())
    sd = {r["family"]: r for r in g2["spread"]}
    fav = {r["family"]: r for r in g2["favourites"]}
    gen = {r["family"]: r for r in g2["general"]}
    for r in rows:
        if r["family"] in sd:
            r.update(gap_in_sd=sd[r["family"]]["gap_in_sd"], fav_ratio=fav[r["family"]]["ratio"],
                     gap_same=gen[r["family"]]["gap_same"], gap_same_lo=gen[r["family"]]["gap_same_lo"], gap_same_hi=gen[r["family"]]["gap_same_hi"],
                     gap_other=gen[r["family"]]["gap_other"], gap_other_lo=gen[r["family"]]["gap_other_lo"], gap_other_hi=gen[r["family"]]["gap_other_hi"])
    gs = g2["general_summary"]
    rows.append({"key": "summary", "family": None, "same_avg": gs["same_avg"], "other_avg": gs["other_avg"], "carryover": gs["carryover"]})
    # songs (genre.py --unit song, descriptive): rows keyed "songs:<family>"
    rows += [{**r, "key": "songs:" + r["family"], "unit": "songs"} for r in json.loads((OUT / "genre_sealed_song.json").read_text())["families"]]
    return rows


def genrespec():
    return json.loads((OUT / "genre3_sealed.json").read_text())["families"]


def genregeneral():
    r = json.loads((OUT / "genre4_sealed.json").read_text())
    son = json.loads((OUT / "genre4_sealed_song.json").read_text())   # genre4.py --unit song, descriptive
    return (r["families"] + [{"key": "summary", "family": None, **r["summary"]}]
            + [{**x, "key": "songs:" + x["family"], "unit": "songs"} for x in son["families"]]
            + [{"key": "songs:summary", "family": None, "unit": "songs", **son["summary"]}])


def obstaste():
    """Artists, plus songs (obs_taste.py --unit song, SONG_PREREG.md round 2): song rows keyed "songs:..." with unit "songs"."""
    art = json.loads((OUT / "obs_taste_sealed_deciles.json").read_text())["curve"]
    son = [{**r, "key": "songs:" + r["key"], "unit": "songs"} for r in json.loads((OUT / "obs_taste_sealed_song_deciles.json").read_text())["curve"]]
    return art + son


def obsdeciles():
    r = json.loads((OUT / "obsession_sealed.json").read_text())["A_artist"]["deciles_plays_ci"]
    return [{"key": str(d["decile"]), "decile": d["decile"], "median_plays": d["median_plays"], "growth": float(np.expm1(d["e"])),
             "lo": float(np.expm1(d["lo"])), "hi": float(np.expm1(d["hi"])), "picks": d["picks"]} for d in r]


def ladder():
    """Hidden half, merged into bands for a plain percentile axis; plus the finest top bands as detail rows."""
    lad = json.loads((OUT / "ladder_sealed.json").read_text())["ladder"]
    merge = [("0–10", 0, .1), ("10–20", .1, .2), ("20–30", .2, .3), ("30–40", .3, .4), ("40–50", .4, .5), ("50–60", .5, .6),
             ("60–70", .6, .7), ("70–80", .7, .8), ("80–90", .8, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0)]
    rows = []
    for lab, lo, hi in merge:
        rs = [r for r in lad if r["lo_pct"] >= lo - 1e-9 and r["hi_pct"] <= hi + 1e-9]
        ev = sum(r["events_10x"] for r in rs); picks = sum(r["picks"] for r in rs)
        exp_ev = sum(r["events_10x"] / r["odds_10x"] for r in rs)
        rows.append({"key": lab, "band": f"{lab}%", "mid": (lo + hi) / 2 * 100, "people": sum(r["people"] for r in rs), "picks": picks,
                     "events_10x": ev, "rate": ev / picks, "similar_rate": exp_ev / picks, "odds": ev / exp_ev, "detail": False})
    for r in lad:
        if r["lo_pct"] >= 0.99:
            rows.append({"key": "detail:" + r["band"], "band": r["band"], "mid": None, "people": r["people"], "picks": r["picks"],
                         "events_10x": r["events_10x"], "rate": r["events_10x"] / r["picks"], "similar_rate": None, "odds": r["odds_10x"],
                         "odds_lo": r["odds_10x_lo"], "odds_hi": r["odds_10x_hi"], "detail": True})
    for r in rows:
        r["unit"] = "artists"
    # songs (analysis/ladder_songs.py, SONG_PREREG.md): same bands; keys prefixed "songs:"
    lad = json.loads((OUT / "ladder_songs_sealed.json").read_text())["ladder"]
    for lab, lo, hi in merge:
        rs = [r for r in lad if r["lo_pct"] >= lo - 1e-9 and r["hi_pct"] <= hi + 1e-9]
        ev = sum(r["events_10x"] for r in rs); picks = sum(r["songs"] for r in rs)
        exp_ev = sum(r["events_10x"] / r["odds_10x"] for r in rs)
        rows.append({"key": "songs:" + lab, "unit": "songs", "band": f"{lab}%", "mid": (lo + hi) / 2 * 100, "people": sum(r["people"] for r in rs),
                     "picks": picks, "events_10x": ev, "rate": ev / picks, "similar_rate": exp_ev / picks, "odds": ev / exp_ev, "detail": False})
    return rows


def song_predictions():
    """SONG_PREREG.md: S1 (top 1% of song pickers' songs vs similar songs, tenfold; 99% low > 2) and S2 (songs vs artists for the
    same people; 99% low > 1), hidden half and ListenBrainz."""
    lj = {h: json.loads((OUT / f"ladder_songs_{h}.json").read_text())["summary"] for h in ("explore", "sealed", "lb")}
    rows = []
    for key, claim, get, bar in (("S1", "Top 1% of song pickers' songs vs similar songs: grew 10× or more",
                                  lambda s: (s["top1"]["odds_10x"], s["top1"]["lo"], s["top1"]["hi"], s["top1"]["lo99"]), 2),
                                 ("S2", "Same people: top 1%'s songs vs their artists, chance of growing 10×",
                                  lambda s: (s["vs_artists"]["ratio"], s["vs_artists"]["ratio_lo"], s["vs_artists"]["ratio_hi"], s["vs_artists"]["ratio_lo99"]), 1)):
        v, lo, hi, lo99 = get(lj["sealed"]); lv, llo, lhi, llo99 = get(lj["lb"])
        rows.append({"key": key, "claim": claim, "unit": "times as often", "hidden": v, "lo": lo, "hi": hi, "lo99": lo99,
                     "first_half": get(lj["explore"])[0], "rate": None, "rate_compared": None, "confirmed": lo99 > bar,
                     "lb": lv, "lb_lo": llo, "lb_hi": lhi, "lb_held": llo99 > bar})
    t = {h: json.loads((OUT / f"obs_taste_{h}_song.json").read_text())["test"] for h in ("explore", "sealed", "lb")}
    ss = {h: json.loads((OUT / f"scene_split_songs_{h}.json").read_text())["bands"][-1] for h in ("explore", "sealed", "lb")}
    for key, claim, f in (("S4", "Top 1%'s songs vs the same size and scene: tenfold takeoffs", "artists"),
                          ("S5", "Top 1%'s songs' scenes vs size alone: tenfold takeoffs", "scenes")):
        rows.append({"key": key, "claim": claim, "unit": "times as often", "hidden": ss["sealed"][f], "lo": ss["sealed"][f"{f}_lo"],
                     "hi": ss["sealed"][f"{f}_hi"], "lo99": ss["sealed"][f"{f}_lo99"], "first_half": ss["explore"][f], "rate": None, "rate_compared": None,
                     "confirmed": ss["sealed"][f"{f}_lo99"] > 1, "lb": ss["lb"][f], "lb_lo": ss["lb"][f"{f}_lo"], "lb_hi": ss["lb"][f"{f}_hi"],
                     "lb_held": ss["lb"][f"{f}_lo99"] > 1})
    rows.append({"key": "S3", "claim": "Getting hooked pays off more for top-fifth than bottom-fifth song pickers (difference)", "unit": "points",
                 "hidden": t["sealed"]["diff"], "lo": t["sealed"]["lo"], "hi": t["sealed"]["hi"], "lo99": t["sealed"]["lo99"],
                 "first_half": t["explore"]["diff"], "rate": None, "rate_compared": None, "confirmed": t["sealed"]["lo99"] > 0,
                 "lb": t["lb"]["diff"], "lb_lo": t["lb"]["lo"], "lb_hi": t["lb"]["hi"], "lb_held": t["lb"]["lo99"] > 0})
    return rows


def fanvalue():
    fv = json.loads((OUT / "fan_value_sealed.json").read_text())
    return [{"key": f"{r['stage']}:{r['fan']}", "stage": r["stage"], "fan": r["fan"], "effect": r["effect"], "lo": r["lo"], "hi": r["hi"],
             "artist_months": r["artist_months"]} for r in fv["rows"]
            if r["stage_type"] == "size" and r["fan"] in ("good", "ordinary", "poor")]


def crowd():
    rows = [{"key": f"{r['crowd']}:{r['label']}", "kind": "point", **r} for r in json.loads((OUT / "ladder_sealed.json").read_text())["crowd_curve"]]
    means = json.loads((OUT / "crowd_means_sealed.json").read_text())  # analysis/charts_data.py --crowd-means
    return rows + [{"kind": "mean", **m} for m in means]


def headlines_with_lb():
    """Hidden-half rows plus the same predictions on ListenBrainz (LB_PREREG.md): lb, lb_lo, lb_hi, lb_held."""
    rows, lb = headlines("sealed"), {r["key"]: r for r in headlines("lb")}
    for r in rows:
        x = lb.get(r["key"])
        r.update({"lb": x["hidden"], "lb_lo": x["lo"], "lb_hi": x["hi"], "lb_held": x["confirmed"]} if x else
                 {"lb": None, "lb_lo": None, "lb_hi": None, "lb_held": None})
    return rows + song_predictions()


if __name__ == "__main__":
    for name, fn in (("headlines", headlines_with_lb), ("obsession", obsession), ("obstaste", obstaste), ("recency", recency), ("badtaste", badtaste), ("fanrel", fanrel), ("genre", genre), ("genrespec", genrespec), ("genregeneral", genregeneral), ("ladder", ladder), ("crowd", crowd), ("fanvalue", fanvalue)):
        rows = fn()
        clean = lambda v: None if isinstance(v, float) and v != v else v  # NaN (undefined range) is not valid JSON
        rows = [{k: clean(v) for k, v in r.items()} if isinstance(r, dict) else r for r in rows]
        (W / f"{name}.json").write_text(json.dumps(rows, indent=1))
        print(name, json.dumps(rows)[:600])
    # songs for "Picking the best pickers" (top_pickers.py --unit song): rows keyed "songs:..." added to toppickers.json
    tp = json.loads((OUT / "top_pickers_sealed_song.json").read_text())
    rows = [r for r in json.loads((W / "toppickers.json").read_text()) if r.get("unit") != "songs"]
    rows += [{"key": "songs:by_traits", "unit": "songs", "label": "Top 1% chosen by habits alone (songs)", "value": tp["top1_by_traits_odds_10x"], "lo": None, "hi": None},
             {"key": "songs:by_record", "unit": "songs", "label": "Top 1% chosen by song track record", "value": tp["top1_by_record_odds_10x"], "lo": None, "hi": None},
             {"key": "songs:r2_traits", "unit": "songs", "label": "Share of later song results explained by habits", "value": tp["variance_explained"]["traits"], "lo": None, "hi": None},
             {"key": "songs:r2_record", "unit": "songs", "label": "Share explained by song track record", "value": tp["variance_explained"]["track_record"], "lo": None, "hi": None}]
    t1 = json.loads((OUT / "scene_split_songs_sealed.json").read_text())["bands"][-1]   # scene_split_songs.py, SONG_PREREG.md round 3
    rows += [{"key": "songs:scene_quality", "unit": "songs", "label": "Their songs' scenes vs size alone", "value": t1["scenes"], "lo": t1["scenes_lo"], "hi": t1["scenes_hi"]},
             {"key": "songs:within_scene", "unit": "songs", "label": "Their songs vs the same scene", "value": t1["artists"], "lo": t1["artists_lo"], "hi": t1["artists_hi"]},
             {"key": "songs:total", "unit": "songs", "label": "Top 1%: tenfold takeoffs vs similar songs", "value": t1["total"], "lo": t1["total_lo"], "hi": t1["total_hi"]}]
    (W / "toppickers.json").write_text(json.dumps(rows, indent=1))
    # songs for "Right scenes and right artists, all the way up the ladder": rows keyed "songs:<band>" added to scenesplit.json
    rows = [r for r in json.loads((W / "scenesplit.json").read_text()) if r.get("unit") != "songs"]
    rows += [{**r, "key": "songs:" + r["key"], "unit": "songs"} for r in json.loads((OUT / "scene_split_songs_sealed.json").read_text())["bands"]]
    (W / "scenesplit.json").write_text(json.dumps(rows, indent=1))
