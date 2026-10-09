"""Data tables for the write-up page (analysis/out/writeup/*.json).

example        Florence + the Machine vs the 868 artists with the same listener count in July 2008:
               monthly share of the fixed panel listening (explore half), Jan 2008 - Dec 2009
results        the 12 models: sealed and explore headline with 95% intervals, top-20% repeat rate, stability, ...
justx          "is it just X?": headline with all controls vs without one control (explore)
robustness     each model's headline range across its setting variations (explore)
revisions      the SPEC.md revisions log
"""

import json
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
OUT = ROOT / "analysis" / "out" / "writeup"
OUT.mkdir(parents=True, exist_ok=True)
NAMES = {"A": "Prescience", "B": "Community-leading", "C_lb": "Durability", "D": "Discernment"}
PLAIN = {"A": "Your picks grow more than comparable ones", "B": "People like you adopt your picks later",
         "C_lb": "Your picks are still listened to in 2026", "D": "Others who try your picks stick with them"}
LEVEL = {"song": "Songs", "artist": "Artists", "scene": "Scenes"}


def card(n):
    return json.loads((CAND / n / "scorecard.json").read_text())


def write(name, rows):
    (OUT / f"{name}.json").write_text(json.dumps(rows, indent=0))
    print(name, len(rows))


# --- example -------------------------------------------------------------------------------------------
con = duckdb.connect()
con.execute(f"""CREATE TABLE pen AS SELECT l.artist, l.month, 100.0 * l.l0 / p.n_panel AS pct, l.l0
    FROM read_parquet('{X}/market/explore/listeners_h12.parquet') l
    JOIN read_parquet('{X}/market/explore/panel.parquet') p ON p.month = l.month AND p.h = 12""")
flo, m0 = int("5fee3020513b48c2b1f74681b01db0c6"[-15:], 16), 2008 * 12 + 6
l0 = con.execute(f"SELECT l0 FROM pen WHERE artist = {flo} AND month = {m0}").fetchone()[0]
con.execute(f"CREATE TABLE peers AS SELECT artist FROM pen WHERE month = {m0} AND l0 BETWEEN {l0 * 0.9} AND {l0 * 1.1}")
n_peers = con.execute("SELECT count(*) FROM peers").fetchone()[0]
ex = con.sql(f"""
    WITH months AS (SELECT range AS month FROM range({2008 * 12}, {2009 * 12 + 12})),
         grid AS (SELECT p.artist, m.month FROM peers p CROSS JOIN months m),
         peer AS (SELECT g.month, median(coalesce(x.pct, 0)) AS peers_median, quantile_cont(coalesce(x.pct, 0), 0.9) AS peers_p90
                  FROM grid g LEFT JOIN pen x USING (artist, month) GROUP BY g.month)
    SELECT printf('%04d-%02d', (p.month // 12)::INT, (p.month % 12 + 1)::INT) AS month,
           round(coalesce(f.pct, 0), 3) AS florence, round(p.peers_median, 3) AS peers_median,
           round(p.peers_p90, 3) AS peers_p90, {n_peers} AS n_peers, (p.month = {m0}) AS bet_month
    FROM peer p LEFT JOIN (SELECT month, pct FROM pen WHERE artist = {flo}) f USING (month) ORDER BY p.month""").pl()
write("example", ex.to_dicts())

# --- results -------------------------------------------------------------------------------------------
conf = {r["candidate"]: r for r in json.loads((ROOT / "analysis" / "out" / "confirmation.json").read_text())}
res = []
for m in ("D", "B", "A", "C_lb"):
    for u in ("song", "artist", "scene"):
        s, e, c = card(f"sealed_{m}_{u}_main"), card(f"{m}_{u}_main"), conf[f"{m}_{u}"]
        res.append({
            "key": f"{m}_{u}", "model": NAMES[m], "plain": PLAIN[m], "level": LEVEL[u],
            "family": "Main (discernment)" if m == "D" else "Other",
            "sealed": round(s["headline_adjusted_forward"], 3),
            "sealed_lo": round(s["headline_adjusted_forward_ci"][0], 3), "sealed_hi": round(s["headline_adjusted_forward_ci"][1], 3),
            "explore": round(e["headline_adjusted_forward"], 3),
            "explore_lo": round(e["headline_adjusted_forward_ci"][0], 3), "explore_hi": round(e["headline_adjusted_forward_ci"][1], 3),
            "repeat_top20": round(s["forward"]["repeat_rate_top20"], 3),
            "stability_3y": round(s["stability_3y_corrected"], 3), "reliability": round(s["reliability"], 3),
            "impostor_share": round(s["impostor_r2"], 3), "people": s["users_scored"],
            "confirmed": c["confirmed"], "size_replicates": c["size_replicates"],
            # 80% range of the true percentile for someone observed at the 75th percentile (from reliability)
            "pctl75_lo": round(s["percentile_range_for_observed_75th"][0]), "pctl75_hi": round(s["percentile_range_for_observed_75th"][1]),
        })
write("results", res)

# --- is it just X ----------------------------------------------------------------------------------------
CHECKS = [("no_scene", "Being in a scene that grew"), ("first_listen", "Following trends (credit from the first listen)"),
          ("no_momentum", "Picking what was already rising"), ("no_age", "Following new releases"),
          ("no_release", "Hearing about albums before release"), ("no_country", "Being early to local acts"),
          ("nocontrols", "All of the above at once")]
jx = []
for m in ("D", "B", "A", "C_lb"):
    for u in ("song", "artist", "scene"):
        key = f"{m}_{u}"
        base = card(f"{key}_main")["headline_adjusted_forward"]
        jx.append({"model": f"{NAMES[m]}, {LEVEL[u].lower()}", "check": "With every correction", "value": round(base, 3)})
        for sfx, label in CHECKS:
            f = CAND / f"{key}_{sfx}" / "scorecard.json"
            if f.exists():
                jx.append({"model": f"{NAMES[m]}, {LEVEL[u].lower()}", "check": label,
                           "value": round(json.loads(f.read_text())["headline_adjusted_forward"], 3)})
write("justx", jx)

# --- more findings: big hits, time windows, overlap -------------------------------------------------------------
more = []
for u in ("artist", "song"):
    more.append({"finding": "hits", "level": LEVEL[u], "label": "Steady outperformance (all bets)",
                 "value": round(card(f"A_{u}_main")["headline_adjusted_forward"], 3)})
    more.append({"finding": "hits", "level": LEVEL[u], "label": "Catching big hits only",
                 "value": round(card(f"A_{u}_hit")["headline_adjusted_forward"], 3)})
for m in ("D", "B", "A", "C_lb"):
    for u in ("song", "artist", "scene"):
        for sfx, label in (("h6", "6 months"), ("main", "12 months"), ("h24", "24 months")):
            f = CAND / f"{m}_{u}_{sfx}" / "scorecard.json"
            if f.exists():
                more.append({"finding": "window", "level": LEVEL[u], "label": f"{NAMES[m]}, {LEVEL[u].lower()}: {label}",
                             "model": f"{NAMES[m]}, {LEVEL[u].lower()}", "window": label,
                             "value": round(json.loads(f.read_text())["headline_adjusted_forward"], 3)})
write("more", more)

import numpy as np
import polars as pl
ov = []
for u in ("artist", "song"):
    names = [f"{m}_{u}_main" for m in ("D", "B", "A", "C_lb")]
    df = None
    for n in names:
        a = pl.read_parquet(CAND / n / "agg.parquet").group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
        a = a.filter(pl.col("n") >= 20).select("user", (pl.col("swe") / pl.col("sw")).alias(n))
        df = a if df is None else df.join(a, on="user")
    C = np.corrcoef(df.select(names).to_numpy().T)
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            ov.append({"level": LEVEL[u], "a": NAMES[a.split("_" + u)[0]], "b": NAMES[b.split("_" + u)[0]], "r": round(float(C[i, j]), 2)})
write("overlap", ov)

# --- robustness ------------------------------------------------------------------------------------------
SWEEPS = {"h6": "6-month window", "h24": "24-month window", "w0.5": "Square-root weights", "w1": "Weighted by plays",
          "rank": "Ranked outcomes", "bins10": "10 popularity groups", "bins50": "50 popularity groups",
          "on13": "13-week onboarding", "on52": "52-week onboarding", "rule_w8": "8 weeks to commit",
          "rule_p10": "10 plays to commit", "rule_w2": "2 weeks to commit"}
rob = []
for m in ("D", "B", "A", "C_lb"):
    for u in ("song", "artist", "scene"):
        for sfx, label in [("main", "Main settings")] + list(SWEEPS.items()):
            f = CAND / f"{m}_{u}_{sfx}" / "scorecard.json"
            # Community data is built for the main commitment rule, so commitment-rule variants don't apply to B.
            if m == "B" and sfx.startswith("rule_"):
                continue
            if f.exists() and "headline_adjusted_forward" in json.loads(f.read_text()):
                rob.append({"model": f"{NAMES[m]}, {LEVEL[u].lower()}", "setting": label,
                            "headline": round(json.loads(f.read_text())["headline_adjusted_forward"], 3), "is_main": sfx == "main"})
write("robustness", rob)

# --- revisions -------------------------------------------------------------------------------------------
revs = []
spec = (ROOT / "SPEC.md").read_text().split("## Revisions")[1]
for line in spec.splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 4 and re.match(r"\d{4}-\d{2}-\d{2}", cells[0]) and cells[3] != "—":
        clean = lambda t: t.replace("**", "").replace("[P]", "(main)")
        revs.append({"n": len(revs) + 1, "date": cells[0], "change": clean(cells[1]), "why": clean(cells[2]),
                     "after_seeing_results": "yes" if cells[3].lower().startswith("yes") else "no"})
write("revisions", revs)
