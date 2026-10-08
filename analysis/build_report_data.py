"""Collect results into small JSON tables for the report page (analysis/out/report/)."""

import json
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).resolve().parent / "out"
REP = OUT / "report"
REP.mkdir(parents=True, exist_ok=True)


def load(path):
    return json.loads((OUT / path / "summary.json").read_text())


def row(s, **extra):
    p = s["persistence"]
    return {**extra, "users": s["users_scored"], "bets_m": round(s["bets"] / 1e6, 1),
            "not_luck": round(s["luck"]["skill_share_of_variance"], 3),
            "halves": round(p["halves"]["pearson"], 3), "gap": round(p["halves_with_gap"]["pearson"], 3),
            "periods": round(p["periods_2006_08_vs_2010_11"]["pearson"], 3),
            "periods_users": p["periods_2006_08_vs_2010_11"]["users"],
            "random_split": round(p["random_split"]["pearson"], 3),
            "impostor_r2": round(s["impostors"]["r2_all"], 3)}


MODELS = [("A", "Prescience", "prescience/primary", "prescience/add_all_country"),
          ("B", "Community-leading", "model_B/primary", "model_B/controlled"),
          ("C", "Durability", "model_C_lb/primary", "model_C_lb/controlled"),
          ("D", "Discernment", "model_D/primary", "model_D/controlled")]
models = []
for key, name, raw, ctrl in MODELS:
    models.append(row(load(raw), model=f"{key}. {name}", version="No controls"))
    models.append(row(load(ctrl), model=f"{key}. {name}", version="All controls"))

controls = [row(load(p), controls=label) for p, label in [
    ("prescience/primary", "None"), ("prescience/ctrl_age", "Artist age"), ("prescience/ctrl_mom", "Momentum"),
    ("prescience/add_scene", "Scene"), ("prescience/add_all", "Scene + age + momentum"),
    ("prescience/add_all_country", "All, incl. country"),
    ("prescience/ctrl_all", "All crossed (artifact)")]]

SWEEPS = {
    "Onboarding cutoff (weeks)": [("sw_onboarding_0", "0", True), ("sw_onboarding_13", "13", False),
                                  ("add_all_country", "26", False), ("sw_onboarding_39", "39", False),
                                  ("sw_onboarding_52", "52", False)],
    "Counts as committed": [("sw_rule_all", "Any first listen", True), ("sw_rule_w2", "2 weeks", True),
                            ("add_all_country", "4 weeks", False), ("sw_rule_w8", "8 weeks", False),
                            ("sw_rule_p10", "10 plays", False)],
    "Weeks allowed to commit": [("sw_window_13", "13", False), ("add_all_country", "26", False),
                                ("sw_window_52", "52", False)],
    "Bet dated at": [("add_all_country", "Commitment", False), ("sw_date_first", "First listen", False)],
    "Time window (months)": [("sw_horizon_6", "6", False), ("add_all_country", "12", False),
                             ("sw_horizon_24", "24", False)],
    "Weight = plays to the power": [("add_all_country", "0", False), ("sw_weight_0.25", "0.25", False),
                                    ("sw_weight_0.5", "0.5", False), ("sw_weight_0.75", "0.75", False),
                                    ("sw_weight_1", "1", False)],
    "Return measure": [("add_all_country", "Log growth", False), ("sw_metric_rank", "Rank", False),
                       ("sw_metric_rawcap", "Raw, capped", False), ("sw_metric_hit", "Top-10% hit", False)],
    "Popularity bins": [("sw_bins_10", "10", False), ("add_all_country", "20", False), ("sw_bins_50", "50", False)],
    "Scene definition": [("add_all_country", "Yearly, 200", False), ("sw_scene_yearly50", "Yearly, 50", False),
                         ("sw_scene_yearly1000", "Yearly, 1000", False), ("sw_scene_allyears200", "All years, 200", False),
                         ("sw_scene_genre200", "Genre tags", False)],
    "Minimum bets per user": [("sw_minbets_10", "10", False), ("add_all_country", "20", False),
                              ("sw_minbets_50", "50", False)],
}
sweeps = []
for param, items in SWEEPS.items():
    for i, (name, label, sampled) in enumerate(items):
        path = f"model_A/{name}" if sampled else f"prescience/{name}"
        if not (OUT / path / "summary.json").exists():
            continue
        sweeps.append(row(load(path), parameter=param, setting=label, order=i,
                          is_main=name == "add_all_country", half_users=sampled))
if (OUT / "model_A/primary_sample2/summary.json").exists():
    s = row(load("model_A/primary_sample2"), parameter="Reference", setting="Main, half of users", order=0,
            is_main=False, half_users=True)
    sweeps.append(s)

# Model agreement (shrunk scores, users scored by all four controlled models).
df = None
for key, name, _, ctrl in MODELS:
    u = pl.read_parquet(OUT / ctrl / "users.parquet").select("user", pl.col("shrunk").alias(key))
    df = u if df is None else df.join(u, on="user")
keys = [m[0] for m in MODELS]
C = np.corrcoef(df.select(keys).to_numpy().T)
agreement = [{"model_x": f"{a}. {MODELS[i][1]}", "model_y": f"{b}. {MODELS[j][1]}", "r": round(float(C[i, j]), 3)}
             for i, a in enumerate(keys) for j, b in enumerate(keys)]
Z = df.select(keys).to_numpy()
Z = (Z - Z.mean(0)) / Z.std(0)
ev = np.linalg.eigvalsh(np.cov(Z.T))[::-1]
agreement_meta = {"users": df.height, "first_factor_share": round(float(ev[0] / ev.sum()), 3)}

active = pl.read_csv(OUT / "active_users_by_year.csv").to_dicts() if (OUT / "active_users_by_year.csv").exists() else []

for name, data in [("models", models), ("controls", controls), ("sweeps", sweeps), ("agreement", agreement)]:
    (REP / f"{name}.json").write_text(json.dumps(data, indent=0))
(REP / "agreement_meta.json").write_text(json.dumps([agreement_meta]))
print({k: len(v) for k, v in [("models", models), ("controls", controls), ("sweeps", sweeps), ("agreement", agreement)]},
      agreement_meta)
