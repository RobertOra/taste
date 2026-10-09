"""Apply the frozen confirmation rules (SPEC.md, Confirmation) to the sealed-half scorecards.

For each family, Holm-Bonferroni at family-wise 5% on one-sided p-values for "headline > 0", where
p comes from the bootstrap z = estimate / SE and SE = (95% interval width) / (2 * 1.96).
Confirmed = passes Holm AND corrected 3-year stability's 95% interval excludes zero.
Also reports whether each sealed estimate falls inside the explore 95% interval.

Writes analysis/out/confirmation.json and prints a table.
"""

import json
from pathlib import Path
from statistics import NormalDist

OUT = Path(__file__).resolve().parent / "out"
CAND = OUT / "cand"
FAMILIES = {
    "primary (discernment)": [("D", u) for u in ("song", "artist", "scene")],
    "secondary": [(m, u) for m in ("A", "B", "C_lb") for u in ("song", "artist", "scene")],
}
NAMES = {"A": "Prescience", "B": "Community-leading", "C_lb": "Durability", "D": "Discernment"}
nd = NormalDist()


def card(name):
    return json.loads((CAND / name / "scorecard.json").read_text())


rows = []
for fam, members in FAMILIES.items():
    items = []
    for m, u in members:
        s, e = card(f"sealed_{m}_{u}_main"), card(f"{m}_{u}_main")
        est, ci = s["headline_adjusted_forward"], s["headline_adjusted_forward_ci"]
        se = (ci[1] - ci[0]) / (2 * 1.96)
        p = 1 - nd.cdf(est / se) if se > 0 else (0.0 if est > 0 else 1.0)
        stab_ci = s.get("stability_3y_corrected_ci") or [None, None]
        e_ci = e["headline_adjusted_forward_ci"]
        items.append({"family": fam, "model": f"{NAMES[m]}, {u}s", "candidate": f"{m}_{u}",
                      "sealed": est, "sealed_ci95": ci, "p_one_sided": p,
                      "explore": e["headline_adjusted_forward"], "explore_ci95": e_ci,
                      "size_replicates": e_ci[0] <= est <= e_ci[1],
                      "stability_3y": s.get("stability_3y_corrected"), "stability_3y_ci95": stab_ci,
                      "stable": stab_ci[0] is not None and stab_ci[0] > 0,
                      "people": s.get("users_scored")})
    # Holm: sort by p; the k-th smallest (0-based) must be below alpha / (n - k); stop at the first failure.
    n, alpha, still = len(items), 0.05, True
    for k, it in enumerate(sorted(items, key=lambda x: x["p_one_sided"])):
        thr = alpha / (n - k)
        it["holm_threshold"] = thr
        it["passes_holm"] = still and it["p_one_sided"] < thr
        still = it["passes_holm"]
    for it in items:
        it["confirmed"] = it["passes_holm"] and it["stable"]
    rows += items

(OUT / "confirmation.json").write_text(json.dumps(rows, indent=1))
print(f"{'family':22s} {'model':28s} {'sealed [95%]':22s} {'explore [95%]':22s} {'size?':6s} {'3y stab':8s} {'Holm':5s} CONFIRMED")
for r in rows:
    print(f"{r['family']:22s} {r['model']:28s} {r['sealed']:.3f} [{r['sealed_ci95'][0]:.3f}, {r['sealed_ci95'][1]:.3f}]  "
          f"{r['explore']:.3f} [{r['explore_ci95'][0]:.3f}, {r['explore_ci95'][1]:.3f}]  "
          f"{'yes' if r['size_replicates'] else 'no':6s} {r['stability_3y'] or float('nan'):7.3f}  "
          f"{'pass' if r['passes_holm'] else 'fail':5s} {'YES' if r['confirmed'] else 'no'}")
