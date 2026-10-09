"""Data for the write-up's headline section (analysis/writeup/*.json).

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
    o = json.loads((OUT / "obsession.json").read_text())
    return [{"level": lab, "most_vs_least": float(np.expm1(o[k]["within_plays"]["diff"])),
             "lo": float(np.expm1(o[k]["within_plays"]["ci"][0])), "hi": float(np.expm1(o[k]["within_plays"]["ci"][1])),
             "people": o[k]["within_plays"]["people"]} for k, lab in (("A_song", "Songs"), ("A_artist", "Artists"))]


def ladder():
    rows = []
    for h, lab in (("sealed", "Hidden half"), ("explore", "First half")):
        for r in json.loads((OUT / f"ladder_{h}.json").read_text())["ladder"]:
            mid = (r["lo_pct"] + r["hi_pct"]) / 2
            rows.append({"key": f"{h}:{r['band']}", "half": lab, "band": r["band"], "top_share": 1 - mid, "people": r["people"],
                         "events_10x": r["events_10x"], "odds_10x": r["odds_10x"], "odds_10x_lo": r["odds_10x_lo"],
                         "odds_10x_hi": r["odds_10x_hi"], "growth": r["growth"]})
    return rows


def crowd():
    return [{"key": f"{r['crowd']}:{r['label']}", **r} for r in json.loads((OUT / "ladder_sealed.json").read_text())["crowd_curve"]]


if __name__ == "__main__":
    for name, fn in (("headlines", headlines), ("takeoff", takeoff), ("obsession", obsession), ("ladder", ladder), ("crowd", crowd)):
        rows = fn()
        (W / f"{name}.json").write_text(json.dumps(rows, indent=1))
        print(name, json.dumps(rows)[:600])
