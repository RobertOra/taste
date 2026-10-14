"""Trend 3, part 2: tribes or eclectics? Overlap within and across niches (2026-10-14, exploratory; ListenBrainz, artists)

Niches = the study's yearly scenes (data/site/artist_scene.parquet: 200 groups of artists the same people listen to, rebuilt each
year from earlier listening). Each year 2010-2025, R = 5 random samples of N = 2,000 people (as trends_homog.py), each person's 30
most-played artists that year, and their main scene (the scene that got most of their plays that year).
  within: overlap (share of one person's 30 artists that another person also has) between two people with the same main scene;
  across: the same between two people with different main scenes;
  spread of people: how evenly people's main scenes are spread over the 200 (effective number of scenes, exp of entropy);
  breadth per person: how many scenes a person's own listening spans (effective number, exp of entropy of their plays by scene);
  in main scene: the share of a person's plays in their main scene.
Same people: those qualifying in 2014, 2019, and 2024 (they also aged 10 years).
Writes analysis/out/trends_niches.json.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
YEARS = range(2010, 2026)
R, N, n = 5, 2000, 30
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
um = con.execute(f"SELECT user, month // 12 AS year, sum(songs) AS sm FROM read_parquet('{SM}/user_month_lb.parquet') GROUP BY ALL").pl()
pool = um.filter(pl.col("sm") >= 250)
scene = pl.read_parquet(ROOT / "data" / "site" / "artist_scene.parquet")


def fetch(users, y):
    con.register("su", pl.DataFrame({"user": users}).to_arrow())
    d = con.execute(f"""SELECT user, artist, sum(plays)::BIGINT AS p FROM read_parquet('{ROOT}/data/derived/user_artist_month/lb/*.parquet') SEMI JOIN su USING (user)
                        WHERE month // 12 = {y} GROUP BY ALL""").pl()
    return d.join(scene.filter(pl.col("year") == y).select("artist", "scene"), on="artist", how="left")


def per_person(d):
    """top-30 artist sets, main scene, breadth, share in main scene."""
    top = d.sort(["user", "p", "artist"], descending=[False, True, False]).group_by("user", maintain_order=True).head(n)
    sets = top.group_by("user").agg(pl.col("artist")).filter(pl.col("artist").list.len() == n)
    sc = d.filter(pl.col("scene").is_not_null()).group_by("user", "scene").agg(p=pl.col("p").sum())
    sc = sc.with_columns(sh=pl.col("p") / pl.col("p").sum().over("user"))
    main = sc.sort(["user", "p", "scene"], descending=[False, True, False]).group_by("user", maintain_order=True).first().select("user", "scene", insc="sh")
    br = sc.group_by("user").agg(breadth=(-(pl.col("sh") * pl.col("sh").log()).sum()).exp())
    return sets.join(main, on="user").join(br, on="user")


def measures(P):
    items = P.explode("artist")
    c_all = items.group_by("artist").len()["len"].to_numpy().astype(float)
    k = P.height
    tot = (c_all * (c_all - 1)).sum()
    cw = items.group_by("scene", "artist").len()["len"].to_numpy().astype(float)
    within_sum = (cw * (cw - 1)).sum()
    g = P.group_by("scene").len()["len"].to_numpy().astype(float)
    wpairs, apairs = (g * (g - 1)).sum(), k * (k - 1) - (g * (g - 1)).sum()
    share = g / g.sum()
    return {"within": float(within_sum / wpairs / n), "across": float((tot - within_sum) / apairs / n), "all": float(tot / (k * (k - 1)) / n),
            "spread": float(np.exp(-(share * np.log(share)).sum())), "breadth": float(P["breadth"].mean()), "in_main": float(P["insc"].mean())}


out = []
print("year | overlap within a niche | across niches | all pairs | spread of people (eff. scenes of 200) | breadth per person (eff. scenes) | share in main scene")
for y in YEARS:
    cand = pool.filter(pl.col("year") == y)["user"].to_numpy()
    draws = [np.random.default_rng(2000 * y + r).choice(cand, size=min(len(cand), int(N * 1.6)), replace=False).tolist() for r in range(R)]
    P_all = per_person(fetch(sorted(set().union(*draws)), y))
    have = set(P_all["user"].to_list())
    res = [measures(P_all.filter(pl.col("user").is_in([u for u in dr if u in have][:N]))) for dr in draws]
    row = {"year": y, **{k: float(np.mean([r[k] for r in res])) for k in res[0]}, **{f"{k}_lo": float(min(r[k] for r in res)) for k in res[0]},
           **{f"{k}_hi": float(max(r[k] for r in res)) for k in res[0]}}
    out.append(row)
    print(f"{y} | {row['within']:.2%} [{row['within_lo']:.2%}-{row['within_hi']:.2%}] | {row['across']:.2%} | {row['all']:.2%} | {row['spread']:.0f} | {row['breadth']:.1f} | {row['in_main']:.0%}", flush=True)
panel = sorted(set(pool.filter(pl.col("year") == 2014)["user"].to_list()) & set(pool.filter(pl.col("year") == 2019)["user"].to_list())
               & set(pool.filter(pl.col("year") == 2024)["user"].to_list()))
Ps = {y: per_person(fetch(panel, y)) for y in (2014, 2019, 2024)}
common = set.intersection(*[set(P["user"].to_list()) for P in Ps.values()])
print(f"\nsame people ({len(common):,}):")
for y, P in Ps.items():
    m = measures(P.filter(pl.col("user").is_in(list(common))))
    out.append({"panel_year": y, "people": len(common), **m})
    print(f"{y} | within {m['within']:.2%} | across {m['across']:.2%} | all {m['all']:.2%} | spread {m['spread']:.0f} | breadth {m['breadth']:.1f} | in main {m['in_main']:.0%}", flush=True)
(ROOT / "analysis" / "out" / "trends_niches.json").write_text(json.dumps(out, indent=1))
