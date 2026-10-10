"""Apply the frozen ListenBrainz bars (LB_PREREG.md) to the one-time run's outputs; writes analysis/out/lb_report.json.
Bars are the ones used on MLHD+ (SPEC.md), unchanged."""
import json
from pathlib import Path
from statistics import NormalDist

OUT = Path(__file__).resolve().parent / "out"
nd = NormalDist()
rows = []


def j(name):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


def get(d, path):
    for k in path:
        if d is None:
            return None
        d = d[k] if isinstance(d, dict) or isinstance(k, int) else None
    return d


def add(key, label, est, bound, bar, held):
    rows.append({"key": key, "label": label, "est": est, "bound": bound, "bar": bar, "held": held})


# Part 1: Holm within families (one-sided 5%) + corrected 3-year stability > 0 (SPEC.md, Confirmation)
FAM = {"primary (discernment)": [("D", u) for u in ("song", "artist", "scene")],
       "secondary": [(m, u) for m in ("A", "B") for u in ("song", "artist", "scene")]}
NAMES = {"A": "Prescience", "B": "Community-leading", "D": "Discernment"}
for fam, members in FAM.items():
    ps, cards = {}, {}
    for m, u in members:
        c = j(f"cand/lb_{m}_{u}_main/scorecard.json")
        if c and c.get("headline_adjusted_forward") is not None:
            cards[(m, u)] = c
            est = c["headline_adjusted_forward"]; lo, hi = c["headline_adjusted_forward_ci"]
            se = (hi - lo) / (2 * 1.96)
            ps[(m, u)] = 1 - nd.cdf(est / se) if se > 0 else 0.0
    order = sorted(ps, key=ps.get)
    passed, stop = {}, False
    for i, k in enumerate(order):
        ok = (not stop) and ps[k] <= 0.05 / (len(order) - i)
        stop = stop or not ok
        passed[k] = ok
    for m, u in members:
        c = cards.get((m, u))
        if not c:
            add(f"main_{m}_{u}", f"{NAMES[m]}, {u}s", None, None, "Holm + stability", None); continue
        stab = (c.get("stability_3y_corrected_ci") or [None])[0]
        add(f"main_{m}_{u}", f"{NAMES[m]}, {u}s ({fam})", c["headline_adjusted_forward"], c["headline_adjusted_forward_ci"][0],
            "Holm p <= family threshold and 3-year stability 95% low > 0", bool(passed[(m, u)] and stab is not None and stab > 0))

# Part 2: the plain-language findings, MLHD+ bars
P = [("P1a", "Best vs worst fifth: tenfold takeoffs", "headlines_lb.json", ["H3", "ratio_10x"], ["H3", "ratio_10x_ci", 2], ">", 1),
     ("P1b", "Best vs worst fifth: fourfold takeoffs", "headlines_lb.json", ["H3", "ratio_4x"], ["H3", "ratio_4x_ci", 2], ">", 1),
     ("P2a", "3+ good pickers vs similar: fourfold", "headlines_lb.json", ["H2", "best_vs_similar_4x"], ["H2", "best_vs_similar_4x_ci", 2], ">", 1),
     ("P2b", "3+ good pickers vs similar: tenfold", "headlines_lb.json", ["H2", "best_vs_similar_10x"], ["H2", "best_vs_similar_10x_ci", 2], ">", 1),
     ("P3a", "One ordinary picker swapped for a good one", "pickers_A_lb.json", ["no_scene", "g", "good_vs_ordinary"], ["no_scene", "g", "good_ci", 2], ">", 0),
     ("P3b", "The same, within the same scene", "pickers_A_lb.json", ["scene", "g", "good_vs_ordinary"], ["scene", "g", "good_ci", 2], ">", 0),
     ("P4a", "Top 1% vs similar: tenfold", "ladder_lb.json", ["summary", "top1_odds_10x"], ["summary", "top1_lo99"], ">", 2),
     ("P4b", "Top 1% vs 90-95% band: tenfold", "ladder_lb.json", ["summary", "top1_vs_90_95"], ["summary", "top1_vs_90_95_lo99"], ">", 1),
     ("P5a", "Niche: 2 good pickers vs none", "ladder_lb.json", ["crowd_summary", "niche_2_vs_0"], ["crowd_summary", "niche_2_vs_0_lo99"], ">", 0),
     ("P5b", "Each good picker adds more for niche than crowded", "ladder_lb.json", ["crowd_summary", "slope_niche_minus_crowded"], ["crowd_summary", "slope_diff_lo99"], ">", 0),
     ("P5c", "Good new fan vs ordinary new fan", "ladder_lb.json", ["count_vs_share", "good_minus_ordinary", "effect"], ["count_vs_share", "good_minus_ordinary", "lo99"], ">", 0),
     ("P6a", "Small artist: good vs ordinary new fan", "fan_value_lb.json", ["tests", "P6a_small_good_minus_ordinary", "est"], ["tests", "P6a_small_good_minus_ordinary", "lo99"], ">", 0),
     ("P6b", "That gap larger for small than big artists", "fan_value_lb.json", ["tests", "P6b_gap_small_minus_big", "est"], ["tests", "P6b_gap_small_minus_big", "lo99"], ">", 0),
     ("P7a", "Top 1%: beat same-scene, same-size artists", "top_pickers_lb.json", ["top1_within_scene", "est"], ["top1_within_scene", "lo99"], ">", 1),
     ("P7b", "Top 1%: their scenes take off more", "top_pickers_lb.json", ["top1_scene_quality", "est"], ["top1_scene_quality", "lo99"], ">", 1),
     ("P7c", "Top 1%'s picks less popular than bottom half's", "top_pickers_lb.json", ["pick_popularity_bottom_minus_top", "est"], ["pick_popularity_bottom_minus_top", "lo99"], ">", 0),
     ("P8", "Most- vs least-replayed quarter, within person", "obsession_lb.json", ["A_artist", "within_plays", "diff"], ["A_artist", "within_plays", "lo99"], ">", 0),
     ("P9", "Hooked pays off more for top- than bottom-fifth", "obs_taste_lb.json", ["test", "diff"], ["test", "lo99"], ">", 0),
     ("P10a", "Recent star, poor history beats old star, poor recent", "recency_lb.json", ["tests", "P10a", "est"], ["tests", "P10a", "lo99"], ">", 1),
     ("P10b", "Recent record separates more than old", "recency_lb.json", ["tests", "P10b", "est"], ["tests", "P10b", "lo99"], ">", 0),
     ("P10c", "One-year record goes stale (2 vs 4 years)", "recency_lb.json", ["tests", "P10c", "est"], ["tests", "P10c", "lo99"], ">", 1),
     ("P11a", "Bottom-fifth picks flop more than middle-fifth", "bad_taste_lb.json", ["tests", "P11a_bottom_flop_vs_middle", "est"], ["tests", "P11a_bottom_flop_vs_middle", "lo99"], ">", 1),
     ("P11b", "Good taste helps more than bad taste hurts", "bad_taste_lb.json", ["tests", "P11b_asymmetry", "est"], ["tests", "P11b_asymmetry", "lo99"], ">", 0),
     ("P11c", "Top-fifth picks also flop more (bolder bets)", "bad_taste_lb.json", ["tests", "P11c_top_flop_vs_middle", "est"], ["tests", "P11c_top_flop_vs_middle", "lo99"], ">", 1),
     ("P12", "Same people, years 3-4 vs 1-2", "learning_lb.json", ["years 1-2 vs 3-4", "change"], ["years 1-2 vs 3-4", "lo99"], ">", 0),
     ("P13a", "Gap larger in Indie than Jazz, blues & classical", "genre_lb.json", ["tests", 0, "est"], ["tests", 0, "lo99"], ">", 0),
     ("P13b", "Gap larger in Indie than Rock & punk", "genre_lb.json", ["tests", 1, "est"], ["tests", 1, "lo99"], ">", 0),
     ("P14a", "Rated on one genre, separate on others", "genre2_lb.json", ["general_summary", "other_avg"], ["general_summary", "other_lo99"], ">", 0),
     ("P14b", "Same-genre gap exceeds other-genre gap", "genre2_lb.json", ["general_summary", "same_minus_other"], ["general_summary", "smo_lo99"], ">", 0),
     ("P14c", "Scaled by spread: Indie above Rock & punk", "genre2_lb.json", ["spread_test", "est"], ["spread_test", "lo99"], ">", 0),
     ("P15", "Genre specialists don't beat good-in-general by > 1 point", "genre3_lb.json", ["summary", "avg_spec_minus_gen"], ["summary", "hi99"], "<", 0.01),
     ("P16", "Other genres predict a genre within 1 point", "genre4_lb.json", ["summary", "avg_this_minus_other"], ["summary", "hi99"], "<", 0.01)]
for key, label, f, ep, bp, cmp, bar in P:
    d = j(f)
    est, bound = get(d, ep), get(d, bp)
    held = None if bound is None else (bound > bar if cmp == ">" else bound < bar)
    add(key, label, est, bound, f"99% {'low' if cmp == '>' else 'high'} {cmp} {bar}", held)

# Part 3: eras (E1, E2) for prescience and discernment, artists
for m in ("A", "D"):
    c = j(f"cand/lb_{m}_artist_main/scorecard.json")
    if not c or "eras" not in c:
        continue
    for era in ("2007-2012", "2013-2018", "2019-2023"):
        e = c["eras"].get(era)
        if e:
            add(f"E1_{m}_{era}", f"{NAMES[m]}, artists, era {era}: predicts", e["adjusted_forward"], e["ci"][0], "95% low > 0", e["ci"][0] > 0)
    r = c["eras"].get("ratio_late_to_early")
    if r:
        add(f"E2_{m}", f"{NAMES[m]}, artists: 2019-2023 at least half as strong as 2007-2012", r["est"], r["lo99"], "99% low of ratio > 0.5", r["lo99"] > 0.5)

(OUT / "lb_report.json").write_text(json.dumps(rows, indent=1))
for r in rows:
    h = "MISSING" if r["held"] is None else ("HELD" if r["held"] else "not held")
    fmt = lambda v: "-" if v is None else f"{v:.4g}"
    print(f"{r['key']:<18} {h:<9} est {fmt(r['est']):>9}  bound {fmt(r['bound']):>9}  ({r['bar']})  {r['label']}")
