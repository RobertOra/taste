"""Reference scores for the static site, computed with exactly the site's procedure (site/static/engine.js, mirrored in
site/score_static.py) on ListenBrainz users: picks found by artist name from weekly listening (4 separate weeks, the 4th
within 26 weeks, after the first 26 weeks), judged picks from 2011 on, names matched to shipped (eligible) artists, one pick
per artist (earliest), the user's own first listen removed from a0, corrections from meta.json, last five judged years.
Updates site/static/data/meta.json: scores (people with >= MIN_PICKS), per_pick (split-half), people.
"""
import json
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import features as F  # noqa: E402

REF, LB, DATA = ROOT / "data" / "site", ROOT / "data" / "lb", ROOT / "site" / "static" / "data"
meta = json.loads((DATA / "meta.json").read_text())
LAST, Y0 = meta["last_month"], meta["y0"]
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
tmp = ROOT / "data" / "_tmp" / "site_sref"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
con.execute(f"CREATE TABLE ship AS SELECT artist FROM (SELECT artist, sum(adopters) AS t FROM read_parquet('{REF}/artist_adopt.parquet') WHERE month >= {Y0} GROUP BY artist) WHERE t >= 2")
con.execute(f"CREATE TABLE nm AS SELECT m.artist_name_h, m.artist FROM read_parquet('{REF}/artist_map.parquet') m SEMI JOIN ship USING (artist)")
# picks by name, as the engine
con.execute(f"""CREATE TABLE pk0 AS
    WITH w AS (SELECT user, artist_name_h AS h, week, sum(plays) AS n FROM read_parquet('{LB}/user_artist_week/*.parquet')
               WHERE week BETWEEN {1104537600 // 604800} AND {1790812800 // 604800} GROUP BY ALL),
         st AS (SELECT user, min(week) AS start FROM w GROUP BY user),
         r AS (SELECT w.*, row_number() OVER (PARTITION BY user, h ORDER BY week) AS rn, min(week) OVER (PARTITION BY user, h) AS fw FROM w),
         a AS (SELECT user, h, min(week) AS first_week, min(week) FILTER (WHERE rn = 4) AS w4, sum(n) FILTER (WHERE week < fw + 26) AS plays26 FROM r GROUP BY user, h)
    SELECT a.user, a.h, a.first_week, a.w4, a.plays26, ({MONTH.format(w='a.w4')})::INT AS m FROM a JOIN st USING (user)
    WHERE a.w4 IS NOT NULL AND a.w4 - a.first_week < 26 AND a.first_week >= st.start + 26""")
con.execute(f"""CREATE TABLE pk AS SELECT p.user, n.artist AS key, n.artist, p.m, p.plays26, ({MONTH.format(w='p.first_week')})::INT AS fm
    FROM pk0 p JOIN nm n ON n.artist_name_h = p.h WHERE p.m BETWEEN {Y0} AND {LAST - 12}
    QUALIFY row_number() OVER (PARTITION BY p.user, n.artist ORDER BY p.m, p.h::VARCHAR) = 1""")
print("picks:", con.execute("SELECT count(*), count(DISTINCT user) FROM pk").fetchone(), flush=True)
feats = F.raw_features(con, "pk", "artist")
df = con.execute("SELECT user, key, artist, m, fm FROM pk").pl().join(feats, on=["key", "artist", "m"])
df = F.derive(df.with_columns(a0=(pl.col("a0") - pl.col("fm").is_between(pl.col("m") - 5, pl.col("m")).cast(pl.Int64)).clip(0)))
# corrections from meta.json (the static baseline and effects), as the engine applies them
base = pl.DataFrame(meta["baseline"], schema=["m", "bin", "g_mean", "ten_rate", "up3_rate"], orient="row").with_columns(pl.col("m").cast(pl.Int32), pl.col("bin").cast(pl.Int8))
d = df.join(base.select("m", "bin", "g_mean"), on=["m", "bin"], how="inner")
ex = pl.col("g") - pl.col("g_mean")
for name, rows in meta["effects"].items():
    cols = name.split("_") if name == "year_scene" else [name]
    sch = {"year": pl.Int16, "scene": pl.Int64, "mo": pl.Int8, "age": pl.Int64, "relc": pl.Int64, "country": pl.String}
    t = pl.DataFrame(rows, schema=[*cols, f"eff_{name}"], orient="row").with_columns([pl.col(c).cast(sch[c]) for c in cols])
    d = d.with_columns([pl.col(c).cast(sch[c]) for c in cols]).join(t, on=cols, how="left").with_columns(pl.col(f"eff_{name}").fill_null(0))
    ex = ex - pl.col(f"eff_{name}")
d = d.with_columns(excess=ex).with_columns(last=pl.col("m").max().over("user")).filter(pl.col("m") > pl.col("last") - 12 * meta["window_years"])
per = d.group_by("user").agg(s=pl.col("excess").sum() / (pl.len() + meta["shrink"]), n=pl.len())
refp = per.filter(pl.col("n") >= meta["min_picks"])
h = (d.sort("user", "m", "artist").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
     .group_by("user", "half").agg(s=pl.col("excess").sum() / (pl.len() + meta["shrink"] / 2), n=pl.len()))
h = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls().filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
rr = spearmanr(h["s_0"], h["s_1"]).statistic
nh = float(np.median(h["n_0"].to_numpy()))
r1 = rr / (nh - (nh - 1) * rr)
meta.update(scores=sorted(round(float(v), 6) for v in refp["s"].to_list()), per_pick=float(r1), people=refp.height, reference="engine procedure (build_static_reference.py)")
(DATA / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
per.write_parquet(REF / "_ref_scores_static.parquet")
print(f"reference people {refp.height:,}; per-pick reliability {r1:.4f} (at 110 / 250: {110 * r1 / (1 + 109 * r1):.2f} / {250 * r1 / (1 + 249 * r1):.2f})", flush=True)
shutil.rmtree(tmp, ignore_errors=True)
