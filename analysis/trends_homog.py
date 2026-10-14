"""Trend 3: is listening becoming more niche or more homogeneous? (2026-10-14, exploratory; ListenBrainz)

Each year 2010-2025, R = 5 random samples of N people (the same N every year, so the growing user base doesn't matter). Each person
is represented by a fixed-size set, so heavy and light listeners count equally:
  songs: their 100 most-played songs that year (people with >= 100 distinct songs);
  artists: their 30 most-played artists (>= 30 distinct artists);
  new finds: 20 of their committed new songs that year, picked at random (>= 20 finds; the study's bet table).
Measures (c_s = how many sampled people have item s in their set, size n):
  overlap = sum c_s (c_s - 1) / (N (N - 1) n): the share of one person's set that a random other person also has;
  concentration = the share of all N n slots held by the most common items (top 100 songs or finds, top 30 artists).
Same people: a panel of people who qualify for songs in 2014, 2019, and 2024, measured in those three years (they also aged 10 years).
Writes analysis/out/trends_homog.json.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SM = ROOT / "data" / "derived" / "song_month"
YEARS = range(2010, 2026)
R = 5
TOPC = {"songs": 100, "artists": 30, "finds": 100}
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
raw = f"read_parquet('{ROOT}/data/mlhd/raw/lb/*.parquet')"
YR = "year(to_timestamp(r.ts))"
um = con.execute(f"SELECT user, month // 12 AS year, sum(songs) AS sm FROM read_parquet('{SM}/user_month_lb.parquet') GROUP BY ALL").pl()
pool = um.filter(pl.col("sm") >= 250)   # proxy for >= 100 distinct songs; checked exactly after loading
counts = pool.group_by("year").len().sort("year")
print("people per year (proxy):", dict(zip(counts["year"].to_list(), counts["len"].to_list())), flush=True)
N = int(min(2000, min(c for y, c in zip(counts["year"].to_list(), counts["len"].to_list()) if y in YEARS) // 2))
print("N =", N, flush=True)


def measures(sets, n, topc):
    c = pl.DataFrame({"item": np.concatenate(sets)}).group_by("item").len()["len"].to_numpy().astype(float)
    k = len(sets)
    return float((c * (c - 1)).sum() / (k * (k - 1) * n)), float(np.sort(c)[::-1][:topc].sum() / (k * n))


def song_sets(users, y):
    con.register("su", pl.DataFrame({"user": users}).to_arrow())
    d = con.execute(f"""SELECT r.user, r.recording, sum(r.plays) AS p FROM {raw} r SEMI JOIN su USING (user) WHERE {YR} = {y} GROUP BY ALL""").pl()
    d = d.sort(["user", "p", "recording"], descending=[False, True, False]).group_by("user", maintain_order=True).head(100)
    g = d.group_by("user").agg(pl.col("recording")).filter(pl.col("recording").list.len() == 100)
    return {u: np.array(s) for u, s in zip(g["user"].to_list(), g["recording"].to_list())}


def artist_sets(users, y):
    con.register("su", pl.DataFrame({"user": users}).to_arrow())
    d = con.execute(f"""SELECT user, artist, sum(plays) AS p FROM read_parquet('{ROOT}/data/derived/user_artist_month/lb/*.parquet') SEMI JOIN su USING (user)
                        WHERE month // 12 = {y} GROUP BY ALL""").pl()
    d = d.sort(["user", "p", "artist"], descending=[False, True, False]).group_by("user", maintain_order=True).head(30)
    g = d.group_by("user").agg(pl.col("artist")).filter(pl.col("artist").list.len() == 30)
    return {u: np.array(s) for u, s in zip(g["user"].to_list(), g["artist"].to_list())}


finds = con.execute(f"SELECT user, item, m // 12 AS year FROM read_parquet('{ROOT}/data/derived/bet_outcomes/A_song_lb.parquet')").pl()
fpool = finds.group_by("user", "year").len().filter(pl.col("len") >= 20)
NF = int(min(2000, min(fpool.filter(pl.col("year") == y).height for y in YEARS) // 2))
print("N for finds =", NF, flush=True)
out = []
print("\nyear | songs: overlap, concentration | artists: overlap, concentration | new finds: overlap, concentration   (mean of 5 samples; range)")
for y in YEARS:
    res = {"songs": [], "artists": [], "finds": []}
    cand = pool.filter(pl.col("year") == y)["user"].to_numpy()
    draws = [np.random.default_rng(1000 * y + r).choice(cand, size=min(len(cand), int(N * 1.6)), replace=False).tolist() for r in range(R)]
    allu = sorted(set().union(*draws))
    ss = song_sets(allu, y); aa = artist_sets(allu, y)   # one scan per year for all five samples
    for r in range(R):
        rng = np.random.default_rng(1000 * y + r + 500)
        keep = [u for u in draws[r] if u in ss][:N]
        res["songs"].append(measures([ss[u] for u in keep], 100, TOPC["songs"]))
        res["artists"].append(measures([aa[u] for u in keep if u in aa], 30, TOPC["artists"]))
        fu = fpool.filter(pl.col("year") == y)["user"].to_numpy()
        fu = rng.choice(fu, size=NF, replace=False)
        fs = finds.filter((pl.col("year") == y) & pl.col("user").is_in(fu.tolist())).group_by("user").agg(pl.col("item"))
        res["finds"].append(measures([rng.choice(np.array(s), 20, replace=False) for s in fs["item"].to_list()], 20, TOPC["finds"]))
    row = {"year": y}
    for k, v in res.items():
        v = np.array(v)
        row.update({f"{k}_overlap": float(v[:, 0].mean()), f"{k}_overlap_lo": float(v[:, 0].min()), f"{k}_overlap_hi": float(v[:, 0].max()),
                    f"{k}_conc": float(v[:, 1].mean()), f"{k}_conc_lo": float(v[:, 1].min()), f"{k}_conc_hi": float(v[:, 1].max())})
    out.append(row)
    print(f"{y} | " + " | ".join(f"{row[f'{k}_overlap']:.2%} [{row[f'{k}_overlap_lo']:.2%}-{row[f'{k}_overlap_hi']:.2%}], {row[f'{k}_conc']:.1%}"
                                  for k in ("songs", "artists", "finds")), flush=True)
# same people
panel = set(pool.filter(pl.col("year") == 2014)["user"].to_list()) & set(pool.filter(pl.col("year") == 2019)["user"].to_list()) & set(pool.filter(pl.col("year") == 2024)["user"].to_list())
panel = sorted(panel)
print(f"\nsame people ({len(panel)} qualifying in 2014, 2019 and 2024):", flush=True)
sets = {y: (song_sets(panel, y), artist_sets(panel, y)) for y in (2014, 2019, 2024)}
common = [u for u in panel if all(u in sets[y][0] and u in sets[y][1] for y in sets)]
for y in (2014, 2019, 2024):
    ss, aa = sets[y]
    s_ = measures([ss[u] for u in common], 100, 100); a_ = measures([aa[u] for u in common], 30, 30)
    out.append({"panel_year": y, "panel_people": len(common), "songs_overlap": s_[0], "songs_conc": s_[1], "artists_overlap": a_[0], "artists_conc": a_[1]})
    print(f"{y} ({len(common)} people) | songs: overlap {s_[0]:.2%}, concentration {s_[1]:.1%} | artists: overlap {a_[0]:.2%}, concentration {a_[1]:.1%}", flush=True)
(ROOT / "analysis" / "out" / "trends_homog.json").write_text(json.dumps(out, indent=1))
