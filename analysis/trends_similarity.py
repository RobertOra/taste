"""How alike are people, and are tastes changing faster? Four similarity measures side by side (2026-10-14, exploratory; ListenBrainz)

People: each year 2010-2025, everyone with enough listening (>= 250 monthly-distinct songs that year, as trends_homog.py).
Each person-year is a vector over items; similarity between two vectors (1 = identical, 0 = nothing shared):
  top30:   their 30 most-played artists, shared share (the earlier measure; = cosine of 0/1 vectors of length 30)
  artists: cosine similarity of play shares over all artists (weighted: a favorite counts more than an artist played twice)
  scenes:  the same over the study's 200 yearly scenes (artist -> scene that year; robust to how many artists exist)
  genres:  the same over genre families (artists with MusicBrainz tags only; Other left out)
Pairs (average cosine within a group = (|sum of unit vectors|^2 - k) / (k (k - 1))):
  random: all pairs of people; niche: pairs with the same main scene (pooled over pairs); fans: pairs with the same most-played
  artist (each fan counted once; their vectors leave the shared favorite out). Ranges: the pool split into 5 random parts (random, niche) or a bootstrap over artists (fans).
Changing faster: each person's similarity with themselves the year before (both years in the pool; scenes use year Y's scene map
for both years), by year; at the same stage of listening (2-4 and 5-9 years since their first listen); and the same people
(in the pool in 2013-14, 2018-19, and 2023-24).
Intermediate: data/_tmp/sim/uay.parquet (user, artist, year, plays), deleted at the end. Writes analysis/out/trends_similarity.json.
"""
import json
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import family_expr  # noqa: E402

SM, X = ROOT / "data" / "derived" / "song_month", ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "sim"; TMP.mkdir(parents=True, exist_ok=True)
YEARS = range(2010, 2026)
MEAS = ["top30", "artists", "scenes", "genres"]
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
um = con.execute(f"SELECT user, month // 12 AS year, sum(songs) AS sm FROM read_parquet('{SM}/user_month_lb.parquet') GROUP BY ALL").pl()
pool = um.filter((pl.col("sm") >= 250) & pl.col("year").is_between(2009, 2025)).select("user", "year")
start = um.group_by("user").agg(y0=pl.col("year").min())
con.register("pool", pool.to_arrow())
if not (TMP / "uay.parquet").exists():
    for c in range(8):
        con.execute(f"""COPY (SELECT u.user, u.artist, (u.month // 12)::SMALLINT AS year, sum(u.plays)::BIGINT AS plays
                              FROM read_parquet('{X}/user_artist_month/lb/*.parquet') u SEMI JOIN pool p ON p.user = u.user AND p.year = u.month // 12
                              WHERE u.user % 8 = {c} GROUP BY ALL) TO '{TMP}/uay_{c}.parquet' (FORMAT parquet)""")
        print("pull slice", c, flush=True)
    con.execute(f"COPY (SELECT * FROM read_parquet('{TMP}/uay_*.parquet')) TO '{TMP}/uay.parquet' (FORMAT parquet)")
U = pl.read_parquet(TMP / "uay.parquet")
scene = pl.read_parquet(ROOT / "data" / "site" / "artist_scene.parquet")
gen = pl.read_parquet(X / "scenes_genre" / "lb.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr()).filter(pl.col("fam") != "Other").select("artist", "fam")


def vectors(d, y_map):
    """d: (user, artist, plays) for one year -> {measure: long table (user, item, w)} with unit-length vectors per user."""
    out = {}
    top = d.sort(["user", "plays", "artist"], descending=[False, True, False]).group_by("user", maintain_order=True).head(30)
    full = top.group_by("user").len().filter(pl.col("len") == 30)["user"]
    out["top30"] = top.filter(pl.col("user").is_in(full.to_list())).select("user", item="artist", w=pl.lit(1 / np.sqrt(30)))
    out["artists"] = d.select("user", item="artist", w="plays")
    sc = d.join(scene.filter(pl.col("year") == y_map).select("artist", "scene"), on="artist")
    out["scenes"] = sc.group_by("user", "scene").agg(w=pl.col("plays").sum()).rename({"scene": "item"})
    gf = d.join(gen, on="artist")
    out["genres"] = gf.group_by("user", "fam").agg(w=pl.col("plays").sum()).rename({"fam": "item"})
    for k in ("artists", "scenes", "genres"):
        v = out[k].with_columns(pl.col("w").cast(pl.Float64))
        out[k] = v.with_columns(w=pl.col("w") / (pl.col("w") ** 2).sum().over("user").sqrt())
    return out


def group_cos(v, groups):
    """v: (user, item, w unit vectors); groups: (user, g). -> per group: S = |sum|^2, k."""
    j = v.join(groups, on="user")
    s = j.group_by("g", "item").agg(t=pl.col("w").sum()).group_by("g").agg(S=(pl.col("t") ** 2).sum())
    k = groups.join(v.select("user").unique(), on="user").group_by("g").len().rename({"len": "k"})
    return s.join(k, on="g").filter(pl.col("k") >= 2)


def pooled(gc):
    return float((gc["S"] - gc["k"]).sum() / (gc["k"] * (gc["k"] - 1)).sum())


rng = np.random.default_rng(77)
pairs, change = [], []
print("year | pairs: random / same niche / fans of the same artist, for top30 | artists | scenes | genres", flush=True)
for y in YEARS:
    d = U.filter(pl.col("year") == y).select("user", "artist", "plays")
    V = vectors(d, y)
    users = d["user"].unique().sort()
    part = pl.DataFrame({"user": users, "g": rng.integers(0, 5, len(users))})
    sc = d.join(scene.filter(pl.col("year") == y).select("artist", "scene"), on="artist").group_by("user", "scene").agg(p=pl.col("plays").sum())
    main = sc.sort(["user", "p", "scene"], descending=[False, True, False]).group_by("user", maintain_order=True).first().select("user", g="scene")
    fav = d.sort(["user", "plays", "artist"], descending=[False, True, False]).group_by("user", maintain_order=True).first().select("user", g="artist")
    # fans: vectors without the shared favorite, so their likeness isn't just how much they play it
    VF = vectors(d.join(fav.rename({"g": "artist"}), on=["user", "artist"], how="anti"), y)
    row = {"year": y, "people": len(users), "genre_cover": float(d.join(gen, on="artist")["plays"].sum() / d["plays"].sum())}
    for m in MEAS:
        v = V[m]
        r5 = [pooled(group_cos(v, part.filter(pl.col("g") == i).with_columns(g=pl.lit(0)))) for i in range(5)]
        row[f"random_{m}"], row[f"random_{m}_lo"], row[f"random_{m}_hi"] = float(np.mean(r5)), float(min(r5)), float(max(r5))
        n5 = [pooled(group_cos(v, main.join(part.filter(pl.col("g") == i).select("user"), on="user"))) for i in range(5)]
        row[f"niche_{m}"], row[f"niche_{m}_lo"], row[f"niche_{m}_hi"] = float(np.mean(n5)), float(min(n5)), float(max(n5))
        fc = group_cos(VF[m], fav); g = ((fc["S"] - fc["k"]) / (fc["k"] * (fc["k"] - 1))).to_numpy(); k = fc["k"].to_numpy().astype(float)
        bs = [float((g[i] * k[i]).sum() / k[i].sum()) for i in (rng.integers(0, len(g), len(g)) for _ in range(200))]
        row[f"fans_{m}"], row[f"fans_{m}_lo"], row[f"fans_{m}_hi"] = float((g * k).sum() / k.sum()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
    pairs.append(row)
    print(f"{y} ({len(users):,}; genres cover {row['genre_cover']:.0%}) | " + " | ".join(f"{row[f'random_{m}']:.3f} / {row[f'niche_{m}']:.3f} / {row[f'fans_{m}']:.3f}" for m in MEAS), flush=True)
    # changing: the same person vs themselves the year before
    dp = U.filter(pl.col("year") == y - 1).select("user", "artist", "plays")
    both = set(d["user"].to_list()) & set(dp["user"].to_list())
    if not both:
        continue
    Vp = vectors(dp.filter(pl.col("user").is_in(list(both))), y)
    Vc = {m: V[m].filter(pl.col("user").is_in(list(both))) for m in MEAS}
    selfsim = None
    for m in MEAS:
        s = Vc[m].join(Vp[m], on=["user", "item"], suffix="_p").group_by("user").agg((pl.col("w") * pl.col("w_p")).sum().alias(m))
        selfsim = s if selfsim is None else selfsim.join(s, on="user", how="full", coalesce=True)
    selfsim = selfsim.fill_null(0).join(start, on="user").with_columns(year=pl.lit(y), tenure=y - pl.col("y0"))
    change.append(selfsim)
C = pl.concat(change, how="diagonal")
out_change = []
print("\nchanging: similarity with themselves the year before (top30 | artists | scenes | genres)", flush=True)
for y in range(2011, 2026):
    c = C.filter(pl.col("year") == y)
    r = {"year": y, "people": c.height, **{m: float(c[m].mean()) for m in MEAS}}
    for lab, (a, b) in (("t2_4", (2, 4)), ("t5_9", (5, 9))):
        cc = c.filter(pl.col("tenure").is_between(a, b))
        r.update({f"{m}_{lab}": (float(cc[m].mean()) if cc.height >= 200 else None) for m in MEAS}); r[f"people_{lab}"] = cc.height
    out_change.append(r)
    f = lambda v: "  -  " if v is None else f"{v:.3f}"
    print(f"{y} ({c.height:,}) all: " + " ".join(f"{r[m]:.3f}" for m in MEAS) + " | 2-4 yrs: " + " ".join(f(r[f'{m}_t2_4']) for m in MEAS)
          + " | 5-9 yrs: " + " ".join(f(r[f'{m}_t5_9']) for m in MEAS), flush=True)
panel = None
for y in (2014, 2019, 2024):
    s = set(C.filter(pl.col("year") == y)["user"].to_list()); panel = s if panel is None else panel & s
print(f"\nsame people ({len(panel):,}):", flush=True)
for y in (2014, 2019, 2024):
    c = C.filter((pl.col("year") == y) & pl.col("user").is_in(list(panel)))
    r = {"panel_year": y, "people": c.height, **{m: float(c[m].mean()) for m in MEAS}}; out_change.append(r)
    print(f"{y}: " + " ".join(f"{m} {r[m]:.3f}" for m in MEAS), flush=True)
(ROOT / "analysis" / "out" / "trends_similarity.json").write_text(json.dumps({"pairs": pairs, "change": out_change}, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
