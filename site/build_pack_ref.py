"""Step 2 of the packed site data: reference picks, baselines, corrections and reference scores for the four site measures,
computed with exactly the site's procedure (mirrored by site/static/engine.js) on ListenBrainz users.

Picks: found by name from weekly listening (artists: user_artist_week by artist name; songs: user_rec_week by "artist\ttrack"
name): 4 separate weeks, the 4th within 26 weeks, not within the first 26 weeks of the person's listening (one warm-up, as the
study; until 2026-10-14 also after any 26+ week gap); dated at the 4th
week's month; judged picks from 2016 (m >= Y0) to last month - 12. Names matched to shipped items (artists: >= 2 new
listeners since 2015; songs: >= 3) and the song's artist to a shipped artist; eligible if at least 2 (artists) / 3 (songs)
*other* people first played it since 2015; one pick per item (earliest).
Measures (per pick, from the item's monthly rows since 2015; site/static/engine.js features()):
    prescience  g = ln((A1+1)/(A0+1)), A0 = new listeners m-5..m (minus the picker), A1 = m+7..m+12
    discernment d = (K + 2 p0) / (T + 2), T = post-onboarding new listeners m+1..m+12, K = of them kept
                corrections add xb = quintile (within month) of the prior conversion (Kp + 2 p0)/(Tp + 2), months <= m
                (minus the picker)
    excess = outcome - mean of reference picks in the same month and size bin (log2 A0) - additive effects
             (momentum, scene x year, age, release timing, country [, xb]) fitted by backfitting
Songs by one artist found in the same month count as one pick (plays-weighted mean excess), as in the study.
Writes data/site/pack_meta.json (baselines and corrections) and every reference find's excess (_pack_ex_*.parquet); scores, reliability
and the yearly reference come from site/build_pack_scores.py.
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
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

# SITE_REF / SITE_OUT / LB_SONGS override the folders (the 2026-10-14 rebuild writes data/site_v2 and site/static/data_v2)
import os
REF, LB, X = Path(os.environ.get("SITE_REF", ROOT / "data" / "site")), ROOT / "data" / "lb", ROOT / "data" / "derived"
LAST, Y0, M0 = 2026 * 12 + 8, 2016 * 12, 2015 * 12
SHRINK, MIN_PICKS = 20, 110
FACT = ["mo", ["year", "scene"], "age", "relc", "country"]
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
W0, W1 = 1104537600 // 604800, 1790812800 // 604800
tmp = ROOT / "data" / "_tmp" / "pack_ref"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
CHUNKS = 16   # users processed in batches (user % CHUNKS) so temporary space stays small

# shipped items and their tables
con.execute(f"CREATE VIEW arows AS SELECT artist AS key, month, a, t, k FROM read_parquet('{REF}/pack_artist_rows.parquet')")
con.execute(f"CREATE VIEW srows AS SELECT rec AS key, month, a, t, k FROM read_parquet('{REF}/pack_song_rows.parquet')")
con.execute("CREATE TABLE atot AS SELECT key, sum(a) AS tot FROM arows GROUP BY key")
con.execute("CREATE TABLE stot AS SELECT key, sum(a) AS tot FROM srows GROUP BY key")
con.execute(f"CREATE TABLE amap AS SELECT m.artist_name_h, m.artist FROM read_parquet('{REF}/artist_map.parquet') m SEMI JOIN atot ON atot.key = m.artist")
con.execute(f"CREATE TABLE smap AS SELECT m.rec_name_h, m.rec FROM read_parquet('{REF}/rec_map.parquet') m SEMI JOIN stot ON stot.key = m.rec")
fam = pl.read_parquet(X / "scenes_genre" / "lb.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr())
FAMS = [n for n, _ in FAMILIES] + ["Other"]
fam = fam.with_columns(fam_i=pl.col("fam").replace_strict({f: i for i, f in enumerate(FAMS)}, return_dtype=pl.Int8)).select("artist", "fam_i")
con.register("famdf", fam.to_arrow()); con.execute("CREATE TABLE afam AS SELECT * FROM famdf")
print("tables ready", flush=True)


def picks(unit, c):
    """Reference picks by name for users with user % CHUNKS == c, as the engine finds them -> table pk_{unit}: user, key, artist, m, w, fm."""
    uf = f"user % {CHUNKS} = {c} AND week BETWEEN {W0} AND {W1}"
    if unit == "artist":
        src = f"SELECT user, artist_name_h AS nh, artist_name_h AS ah, week, sum(plays) AS n FROM read_parquet('{LB}/user_artist_week/*.parquet') WHERE {uf} GROUP BY ALL"
    else:
        src = f"SELECT user, rec_name_h AS nh, any_value(artist_name_h) AS ah, week, sum(plays) AS n FROM read_parquet('{LB}/user_rec_week/*.parquet') WHERE {uf} GROUP BY user, rec_name_h, week"
    con.execute(f"CREATE OR REPLACE TABLE w_{unit} AS {src}")
    con.execute(f"""CREATE OR REPLACE TABLE p0_{unit} AS
        WITH aw AS (SELECT DISTINCT user, week FROM read_parquet('{LB}/user_artist_week/*.parquet') WHERE {uf}),
             seg AS (SELECT user, min(week) AS start FROM aw GROUP BY user),   -- one warm-up: the first 26 weeks of the history (as the study)
             r AS (SELECT w.*, row_number() OVER (PARTITION BY user, nh ORDER BY week) AS rn, min(week) OVER (PARTITION BY user, nh) AS fw FROM w_{unit} w),
             a AS (SELECT user, nh, any_value(ah) AS ah, min(week) AS first_week, min(week) FILTER (WHERE rn = 4) AS w4, sum(n) FILTER (WHERE week < fw + 26) AS w
                   FROM r GROUP BY user, nh)
        SELECT a.user, a.nh, a.ah, a.first_week, a.w, ({MONTH.format(w='a.w4')})::INT AS m FROM a ASOF JOIN seg ON a.user = seg.user AND a.first_week >= seg.start
        WHERE a.w4 IS NOT NULL AND a.w4 - a.first_week < 26 AND a.first_week >= seg.start + 26""")
    con.execute(f"DROP TABLE w_{unit}")
    if unit == "artist":
        con.execute(f"""CREATE OR REPLACE TABLE pk_{unit} AS SELECT p.user, n.artist AS key, n.artist, p.m, p.w, ({MONTH.format(w='p.first_week')})::INT AS fm
            FROM p0_{unit} p JOIN amap n ON n.artist_name_h = p.nh JOIN atot t ON t.key = n.artist
            WHERE p.m BETWEEN {Y0} AND {LAST - 12} AND t.tot - (({MONTH.format(w='p.first_week')}) >= {M0})::INT >= 2
            QUALIFY row_number() OVER (PARTITION BY p.user, n.artist ORDER BY p.m, p.nh::VARCHAR) = 1""")
    else:
        con.execute(f"""CREATE OR REPLACE TABLE pk_{unit} AS SELECT p.user, s.rec AS key, n.artist, p.m, p.w, ({MONTH.format(w='p.first_week')})::INT AS fm
            FROM p0_{unit} p JOIN smap s ON s.rec_name_h = p.nh JOIN stot t ON t.key = s.rec JOIN amap n ON n.artist_name_h = p.ah
            WHERE p.m BETWEEN {Y0} AND {LAST - 12} AND t.tot - (({MONTH.format(w='p.first_week')}) >= {M0})::INT >= 3
            QUALIFY row_number() OVER (PARTITION BY p.user, s.rec ORDER BY p.m, p.nh::VARCHAR) = 1""")
    con.execute(f"DROP TABLE p0_{unit}")


def features(unit):
    rows = "arows" if unit == "artist" else "srows"
    con.execute(f"CREATE OR REPLACE TABLE km AS SELECT DISTINCT key, artist, m FROM pk_{unit}")
    con.execute(f"""CREATE OR REPLACE TABLE ka AS SELECT k.key, k.m,
          coalesce(sum(r.a) FILTER (WHERE r.month BETWEEN k.m - 5 AND k.m), 0)::BIGINT AS a0,
          coalesce(sum(r.a) FILTER (WHERE r.month BETWEEN k.m + 7 AND k.m + 12), 0)::BIGINT AS a1,
          coalesce(sum(r.a) FILTER (WHERE r.month BETWEEN k.m - 11 AND k.m - 6), 0)::BIGINT AS ap,
          coalesce(sum(r.t) FILTER (WHERE r.month BETWEEN k.m - 5 AND k.m), 0)::BIGINT AS t0,
          coalesce(sum(r.t) FILTER (WHERE r.month BETWEEN k.m + 7 AND k.m + 12), 0)::BIGINT AS t1,
          coalesce(sum(r.t) FILTER (WHERE r.month BETWEEN k.m - 11 AND k.m - 6), 0)::BIGINT AS tq,
          coalesce(sum(r.t) FILTER (WHERE r.month BETWEEN k.m + 1 AND k.m + 12), 0)::BIGINT AS tl,
          coalesce(sum(r.k) FILTER (WHERE r.month BETWEEN k.m + 1 AND k.m + 12), 0)::BIGINT AS kl,
          coalesce(sum(r.t) FILTER (WHERE r.month <= k.m), 0)::BIGINT AS tp,
          coalesce(sum(r.k) FILTER (WHERE r.month <= k.m), 0)::BIGINT AS kp
        FROM (SELECT DISTINCT key, m FROM km) k LEFT JOIN {rows} r ON r.key = k.key AND r.month <= k.m + 12 GROUP BY k.key, k.m""")
    first = (f"SELECT artist AS key, first_month AS fmo FROM read_parquet('{REF}/artist_info.parquet')" if unit == "artist"
             else f"SELECT rec AS key, first_month AS fmo FROM read_parquet('{REF}/pack_song_first.parquet')")
    con.execute(f"CREATE OR REPLACE TABLE anyrel AS SELECT DISTINCT artist FROM read_parquet('{REF}/artist_release.parquet')")
    con.execute(f"""CREATE OR REPLACE TABLE rel AS SELECT k.artist, k.m,
          CASE WHEN k.artist NOT IN (SELECT artist FROM anyrel) THEN 4
               ELSE 2 * (count(x.rm) FILTER (WHERE x.rm > k.m AND x.rm <= k.m + 3) > 0)::INT + (count(x.rm) FILTER (WHERE x.rm >= k.m - 3 AND x.rm <= k.m) > 0)::INT END AS relc
        FROM (SELECT DISTINCT artist, m FROM km) k LEFT JOIN read_parquet('{REF}/artist_release.parquet') x ON x.artist = k.artist AND x.rm BETWEEN k.m - 3 AND k.m + 3
        GROUP BY k.artist, k.m""")
    age = ("CASE WHEN f.fmo <= 2005 * 12 THEN 9 WHEN k.m - f.fmo < 3 THEN 0 WHEN k.m - f.fmo < 6 THEN 1 WHEN k.m - f.fmo < 12 THEN 2 WHEN k.m - f.fmo < 24 THEN 3 ELSE 4 END"
           if unit == "artist" else
           "CASE WHEN f.fmo <= 2005 * 12 THEN 9 WHEN k.m - f.fmo <= 2 THEN k.m - f.fmo WHEN k.m - f.fmo < 6 THEN 3 WHEN k.m - f.fmo < 12 THEN 4 WHEN k.m - f.fmo < 24 THEN 5 ELSE 6 END")
    feats = con.execute(f"""SELECT k.key, k.artist, k.m, ka.*  EXCLUDE (key, m), coalesce({age}, 9) AS age, coalesce(s.scene, -1) AS scene, rel.relc,
          coalesce(i.country, '?') AS country, coalesce(af.fam_i, {len(FAMS) - 1}) AS fam
        FROM km k JOIN ka ON ka.key = k.key AND ka.m = k.m LEFT JOIN ({first}) f ON f.key = k.key
        LEFT JOIN read_parquet('{REF}/artist_scene.parquet') s ON s.artist = k.artist AND s.year = k.m // 12
        LEFT JOIN rel ON rel.artist = k.artist AND rel.m = k.m LEFT JOIN read_parquet('{REF}/artist_info.parquet') i ON i.artist = k.artist
        LEFT JOIN afam af ON af.artist = k.artist""").pl()
    return con.execute(f"SELECT user, key, artist, m, w, fm FROM pk_{unit}").pl().join(feats, on=["key", "artist", "m"])


def backfit(d, outcome, facts):
    base = d.group_by("m", "bin").agg(mean=pl.col(outcome).mean(), n=pl.len())
    dd = d.join(base.select("m", "bin", "mean"), on=["m", "bin"])
    r = (dd[outcome] - dd["mean"]).to_numpy().copy()
    eff = {}
    for _ in range(4):
        for f in facts:
            cols = f if isinstance(f, list) else [f]
            name = "_".join(cols)
            part = r + (dd.select(cols).join(eff[name], on=cols, how="left")["eff"].fill_null(0).to_numpy() if name in eff else 0)
            t = dd.select(cols).with_columns(v=pl.Series(part)).group_by(cols).agg(eff=pl.col("v").mean())
            eff[name] = t
            r = part - dd.select(cols).join(t, on=cols, how="left")["eff"].to_numpy()
    return base, eff, dd.with_columns(excess=pl.Series(r))


def reliability(d):
    h = (d.sort("user", "m", "item").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
         .group_by("user", "half").agg(s=pl.col("excess").sum() / (pl.len() + SHRINK / 2), n=pl.len()))
    h = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls().filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
    rr = spearmanr(h["s_0"], h["s_1"]).statistic
    nh = float(np.median(h["n_0"].to_numpy()))
    return float(rr / (nh - (nh - 1) * rr))


meta = {"last_month": LAST, "y0": Y0, "m0": M0, "shrink": SHRINK, "min_picks": MIN_PICKS, "families": FAMS, "measures": {}}
frozen = {"artist": {"A": "lb_A_artist_main", "D": "lb_D_artist_main"}, "song": {"A": "lb_A_song_main", "D": "lb_D_song_main"}}
for unit in ("artist", "song"):
    parts = []
    for c in range(CHUNKS):
        picks(unit, c)
        f = features(unit)
        fp = tmp / f"feat_{unit}_{c}.parquet"; f.write_parquet(fp); parts.append(fp)
        print(f"{unit} batch {c + 1}/{CHUNKS}: {f.height:,} picks", flush=True)
        del f
    df = pl.concat([pl.read_parquet(fp) for fp in parts])
    print(unit, "picks:", df.height, "people:", df["user"].n_unique(), flush=True)
    # the picker isn't in a visitor's comparison: remove their own first listen (prescience: from A0; discernment: from the prior)
    own0 = pl.col("fm").is_between(pl.col("m") - 5, pl.col("m")).cast(pl.Int64)
    ownp = (pl.col("fm") >= M0).cast(pl.Int64)
    df = df.with_columns(a0=(pl.col("a0") - own0).clip(0), t0=(pl.col("t0") - own0).clip(0), tp=(pl.col("tp") - ownp).clip(0), kp=(pl.col("kp") - ownp).clip(0))
    df = df.with_columns(g=((pl.col("a1") + 1) / (pl.col("a0") + 1)).log(), bin=(pl.col("a0") + 1).log(2).floor().clip(0, 14).cast(pl.Int8),
                         mo=(((pl.col("a0") + 1) / (pl.col("ap") + 1)).log(2) / 0.5).floor().clip(-3, 3).cast(pl.Int8), year=(pl.col("m") // 12).cast(pl.Int16),
                         up3=(((pl.col("a1") + 1) / (pl.col("a0") + 1)).log() >= np.log(3)).cast(pl.Float64), item=pl.col("key"))
    p0 = float(df["kl"].sum() / max(df["tl"].sum(), 1))
    df = df.with_columns(d=(pl.col("kl") + 2 * p0) / (pl.col("tl") + 2), cp=(pl.col("kp") + 2 * p0) / (pl.col("tp") + 2))
    cuts = df.group_by("m").agg([pl.col("cp").quantile(q, "linear").alias(f"q{i}") for i, q in enumerate((0.2, 0.4, 0.6, 0.8))]).sort("m")
    df = df.join(cuts, on="m").with_columns(xb=(pl.col("cp") > pl.col("q0")).cast(pl.Int8) + (pl.col("cp") > pl.col("q1")).cast(pl.Int8)
                                            + (pl.col("cp") > pl.col("q2")).cast(pl.Int8) + (pl.col("cp") > pl.col("q3")).cast(pl.Int8))
    # As: prescience among settled listeners (new listeners already 26+ weeks into their own listening), so a wave of people
    # joining ListenBrainz doesn't count as an artist taking off; size and momentum from the same counts (rebuild item 2)
    dfs = df.with_columns(g=((pl.col("t1") + 1) / (pl.col("t0") + 1)).log(), bin=(pl.col("t0") + 1).log(2).floor().clip(0, 14).cast(pl.Int8),
                          mo=(((pl.col("t0") + 1) / (pl.col("tq") + 1)).log(2) / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                          up3=(((pl.col("t1") + 1) / (pl.col("t0") + 1)).log() >= np.log(3)).cast(pl.Float64))
    for meas, outcome, facts, src in (("A", "g", FACT, df), ("As", "g", FACT, dfs), ("D", "d", FACT + ["xb"], df)):
        base, eff, dd = backfit(src, outcome, facts)
        if meas in ("A", "As"):
            base = base.join(src.group_by("m", "bin").agg(up3=pl.col("up3").mean()), on=["m", "bin"])
        dd = dd.with_columns(ex=pl.col("excess"))
        if unit == "song":   # each song's own result too, for the songs-vs-groups test (rebuild item 4)
            dd.select("user", "item", "artist", "m", "w", "excess").write_parquet(REF / f"_pack_ex_{unit}_{meas}_items.parquet")
        if unit == "song":   # one pick per artist and month, plays-weighted
            dd = dd.group_by("user", "artist", "m").agg(excess=(pl.col("ex") * pl.col("w")).sum() / pl.col("w").sum(), item=pl.col("item").min())
        key = f"{unit}_{meas}"
        dd.select("user", "item", "m", "excess").write_parquet(REF / f"_pack_ex_{key}.parquet")   # every reference find's result (site/build_pack_scores.py)
        meta["measures"][key] = {
            "unit": unit, "measure": "A" if meas == "As" else meas, "settled": meas == "As", "p0": p0,
            "baseline": [[int(r["m"]), int(r["bin"]), round(float(r["mean"]), 6)] + ([round(float(r["up3"]), 6)] if meas in ("A", "As") else []) for r in base.iter_rows(named=True)],
            "effects": {name: [[*(list(row[:-1])), round(float(row[-1]), 6)] for row in t.iter_rows()] for name, t in eff.items()},
            **({"xb_cuts": [[int(r[0]), *[round(float(v), 6) for v in r[1:]]] for r in cuts.iter_rows()]} if meas == "D" else {})}
        print(f"{key}: {dd.height:,} reference finds saved", flush=True)
    df.select("user", "key", "artist", "m", "w", "fm", "fam").write_parquet(REF / f"_pack_picks_{unit}.parquet")
countries = sorted(set(pl.read_parquet(REF / "artist_info.parquet", columns=["country"])["country"].to_list()) | {"?"})
meta["countries"] = countries
(REF / "pack_meta.json").write_text(json.dumps(meta, separators=(",", ":")))
print("pack_meta.json", (REF / "pack_meta.json").stat().st_size // 1000, "kB")
shutil.rmtree(tmp, ignore_errors=True)
