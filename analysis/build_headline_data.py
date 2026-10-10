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


def headlines():
    hs, he = (json.loads((OUT / f"headlines_{h}.json").read_text()) for h in ("sealed", "explore"))
    ps, pe = (json.loads((OUT / f"pickers_A{s}.json").read_text()) for s in ("_sealed", ""))
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
    ls, le = (json.loads((OUT / f"ladder_{h}.json").read_text()) for h in ("sealed", "explore"))
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
    fv = json.loads((OUT / "fan_value_sealed.json").read_text())
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
    ts, te = (json.loads((OUT / f"top_pickers_{h}.json").read_text()) for h in ("sealed", "explore"))
    for key, claim, unit, k in (("P7a", "Top 1%'s artists vs the same size and scene: tenfold takeoffs", "times as often", "top1_within_scene"),
                                ("P7b", "Top 1%'s scenes vs size alone: tenfold takeoffs", "times as often", "top1_scene_quality"),
                                ("P7c", "Top 1%'s picks less popular than the bottom half's", "points", "pick_popularity_bottom_minus_top")):
        est, fe = ts[k], te[k]
        rows.append({"key": key, "claim": claim, "unit": unit, "hidden": est["est"], "lo": est["lo"], "hi": est["hi"], "lo99": est["lo99"],
                     "first_half": fe["est"], "rate": None, "rate_compared": None, "confirmed": est["lo99"] > (0 if unit == "points" else 1)})
    ob = json.loads((OUT / "obsession_sealed.json").read_text())["A_artist"]["within_plays"]
    obe = json.loads((OUT / "obsession.json").read_text())["A_artist"]["within_plays"]
    rows.append({"key": "P8", "claim": "Each person's most-hooked quarter of artist picks vs their least-hooked: extra growth", "unit": "more growth",
                 "hidden": float(np.expm1(ob["diff"])), "lo": float(np.expm1(ob["ci"][0])), "hi": float(np.expm1(ob["ci"][1])),
                 "lo99": float(np.expm1(ob["lo99"])), "first_half": float(np.expm1(obe["diff"])), "rate": None, "rate_compared": None,
                 "confirmed": ob["lo99"] > 0})
    t9, t9e = (json.loads((OUT / f"obs_taste_{h}.json").read_text())["test"] for h in ("sealed", "explore"))
    rows.append({"key": "P9", "claim": "Getting hooked pays off more for top-fifth than bottom-fifth pickers (difference)", "unit": "points",
                 "hidden": t9["diff"], "lo": t9["lo"], "hi": t9["hi"], "lo99": t9["lo99"], "first_half": t9e["diff"], "rate": None,
                 "rate_compared": None, "confirmed": t9["lo99"] > 0})
    rs, re_ = (json.loads((OUT / f"recency_{h}.json").read_text())["tests"] for h in ("sealed", "explore"))
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
    bs_, be_ = (json.loads((OUT / f"bad_taste_{h}.json").read_text())["tests"] for h in ("sealed", "explore"))
    for key, claim, unit, k, bar in (("P11a", "Bottom-fifth pickers' picks vs middle-fifth pickers': flops", "times as often", "P11a_bottom_flop_vs_middle", 1),
                                     ("P11c", "Top-fifth pickers' picks vs middle-fifth pickers': flops (bolder bets)", "times as often", "P11c_top_flop_vs_middle", 1),
                                     ("P11b", "Good taste helps more than bad taste hurts (difference in growth)", "points", "P11b_asymmetry", 0)):
        rows.append({"key": key, "claim": claim, "unit": unit, "hidden": bs_[k]["est"], "lo": bs_[k]["lo"], "hi": bs_[k]["hi"], "lo99": bs_[k]["lo99"],
                     "first_half": be_[k]["est"], "rate": None, "rate_compared": None, "confirmed": bs_[k]["lo99"] > bar})
    ls_, le_ = (json.loads((OUT / f"learning_{h}.json").read_text())["years 1-2 vs 3-4"] for h in ("sealed", "explore"))
    rows.append({"key": "P12", "claim": "Same people, experience years 3-4 vs 1-2: extra growth of their new artists", "unit": "points",
                 "hidden": ls_["change"], "lo": ls_["lo"], "hi": ls_["hi"], "lo99": ls_["lo99"], "first_half": le_["change"],
                 "rate": None, "rate_compared": None, "confirmed": ls_["lo99"] > 0})
    gs_ = json.loads((OUT / "genre_sealed.json").read_text())["tests"]
    ge_ = {r["family"]: r["gap"] for r in json.loads((OUT / "genre_explore.json").read_text())["families"]}
    for key, t in zip(("P13a", "P13b"), gs_):
        rows.append({"key": key, "claim": f"Taste matters more in {t['top']} than in {t['bottom']} (gap difference)", "unit": "points",
                     "hidden": t["est"], "lo": t["lo"], "hi": t["hi"], "lo99": t["lo99"], "first_half": ge_[t["top"]] - ge_[t["bottom"]],
                     "rate": None, "rate_compared": None, "confirmed": t["lo99"] > 0})
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
    return json.loads((OUT / "genre_sealed.json").read_text())["families"]


def obstaste():
    return json.loads((OUT / "obs_taste_sealed_deciles.json").read_text())["curve"]


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


if __name__ == "__main__":
    for name, fn in (("headlines", headlines), ("obsession", obsession), ("obstaste", obstaste), ("recency", recency), ("badtaste", badtaste), ("fanrel", fanrel), ("learning", learning), ("genre", genre), ("ladder", ladder), ("crowd", crowd), ("fanvalue", fanvalue)):
        rows = fn()
        (W / f"{name}.json").write_text(json.dumps(rows, indent=1))
        print(name, json.dumps(rows)[:600])
