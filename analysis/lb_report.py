"""Apply the frozen ListenBrainz bars (LB_PREREG.md) to the one-time run's outputs; writes analysis/out/lb_report.json."""
import json
from pathlib import Path
from statistics import NormalDist

OUT = Path(__file__).resolve().parent / "out"
nd = NormalDist()


def j(name):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


rows = []


def add(key, label, est, bound, bar, passed):
    rows.append({"key": key, "label": label, "est": est, "bound": bound, "bar": bar, "held": bool(passed) if passed is not None else None})


# Part 1: Holm across A and D (one-sided, 5%) + corrected 3-year stability > 0
cards = {m: j(f"cand/lb_{m}_artist_main/scorecard.json") for m in ("A", "D")}
ps = {}
for m, c in cards.items():
    if c:
        est = c["headline_adjusted_forward"]; lo, hi = c["headline_adjusted_forward_ci"]
        se = (hi - lo) / (2 * 1.96)
        ps[m] = 1 - nd.cdf(est / se) if se > 0 else 0.0
order = sorted(ps, key=ps.get)
holm = {m: ps[m] <= 0.05 / (len(order) - i) for i, m in enumerate(order)}
for i, m in enumerate(order):  # step-down: stop at first failure
    if not holm[m]:
        for m2 in order[i:]:
            holm[m2] = False
        break
for m, c in cards.items():
    if c:
        stab = c.get("stability_3y_corrected_ci", [None])[0]
        add(f"main_{m}", f"{'Prescience' if m == 'A' else 'Discernment'}, artists: forward prediction (Holm) and 3-year stability",
            c["headline_adjusted_forward"], c["headline_adjusted_forward_ci"][0], "Holm p and stability > 0", holm.get(m) and (stab or 0) > 0)

# Part 2
def t(key, label, file, path, bar_val, bar_text, est_path=None, cmp=">"):
    d = j(file)
    if d is None:
        add(key, label, None, None, bar_text, None); return
    cur = d
    for k in path:
        cur = cur[k] if not isinstance(k, int) else cur[k]
    est = d
    for k in (est_path or []):
        est = est[k]
    add(key, label, est if est_path else None, cur, bar_text, cur > bar_val if cmp == ">" else cur < bar_val)

t("P1a", "Best vs worst fifth: tenfold takeoffs", "headlines_lb.json", ["H3", "ratio_10x_ci", 2], 1, "99% low > 1", ["H3", "ratio_10x"])
t("P4a", "Top 1% vs similar artists: tenfold takeoffs", "ladder_lb.json", ["summary", "top1_lo99"], 1, "99% low > 1", ["summary", "top1_odds_10x"])
t("P5a", "Niche artists: 2 good pickers vs none", "ladder_lb.json", ["crowd_summary", "niche_2_vs_0_lo99"], 0, "99% low > 0", ["crowd_summary", "niche_2_vs_0"])
t("P5c", "Good new fan vs ordinary new fan", "ladder_lb.json", ["count_vs_share", "good_minus_ordinary", "lo99"], 0, "99% low > 0", ["count_vs_share", "good_minus_ordinary", "effect"])
t("P6a", "Small artists: good vs ordinary new fan", "fan_value_lb.json", ["tests", "P6a_small_good_minus_ordinary", "lo99"], 0, "99% low > 0", ["tests", "P6a_small_good_minus_ordinary", "est"])
t("P8", "Most- vs least-replayed quarter (within person)", "obsession_lb.json", ["A_artist", "within_plays", "lo99"], 0, "99% low > 0", ["A_artist", "within_plays", "diff"])
t("P9", "Hooked pays off more for top- than bottom-fifth pickers", "obs_taste_lb.json", ["test", "lo99"], 0, "99% low > 0", ["test", "diff"])
t("P10b", "Recent record separates more than old record", "recency_lb.json", ["tests", "P10b", "lo99"], 0, "99% low > 0", ["tests", "P10b", "est"])
t("P11a", "Bottom-fifth picks flop more than middle-fifth picks", "bad_taste_lb.json", ["tests", "P11a_bottom_flop_vs_middle", "lo99"], 1, "99% low > 1", ["tests", "P11a_bottom_flop_vs_middle", "est"])
t("P11b", "Good taste helps more than bad taste hurts", "bad_taste_lb.json", ["tests", "P11b_asymmetry", "lo99"], 0, "99% low > 0", ["tests", "P11b_asymmetry", "est"])
t("P13a", "Gap larger in Indie than in Jazz, blues & classical", "genre_lb.json", ["tests", 0, "lo99"], 0, "99% low > 0", ["tests", 0, "est"])
t("P14a", "Rated on one genre, separate on other genres", "genre2_lb.json", ["general_summary", "other_lo99"], 0, "99% low > 0", ["general_summary", "other_avg"])
t("P12", "Same people, years 3-4 vs 1-2", "learning_lb.json", ["years 1-2 vs 3-4", "lo99"], 0, "99% low > 0", ["years 1-2 vs 3-4", "change"])

# Part 3: eras
for m, c in cards.items():
    if not c or "eras" not in c:
        continue
    for era in ("2007-2012", "2013-2018", "2019-2023"):
        e = c["eras"].get(era)
        if e:
            add(f"E1_{m}_{era}", f"{m} artists, era {era}: forward prediction > 0", e["adjusted_forward"], e["ci"][0], "95% low > 0", e["ci"][0] > 0)
    r = c["eras"].get("ratio_late_to_early")
    if r:
        add(f"E2_{m}", f"{m} artists: algorithm era at least half as strong as 2007-2012", r["est"], r["lo99"], "99% low of ratio > 0.5", r["lo99"] > 0.5)

(OUT / "lb_report.json").write_text(json.dumps(rows, indent=1))
for r in rows:
    print(f"{r['key']:<22} {('HELD' if r['held'] else 'not held') if r['held'] is not None else 'MISSING':<9} est {r['est'] if r['est'] is None else round(r['est'], 4)}  "
          f"bound {r['bound'] if r['bound'] is None else round(r['bound'], 4)}  ({r['bar']})  {r['label']}")
