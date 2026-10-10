"""Baselines, correction effects and reference scores for the site, from ListenBrainz users' own picks (site/features.py).

Picks: artists from data/derived/bet_outcomes/A_artist_lb.parquet (first listen week from bets/lb), songs from
data/derived/song_bets/lb.parquet (first listen week from user_recording/lb); judged picks only (m <= last month - 12).
The picker's own first listen is removed from a0 (a site visitor isn't in ListenBrainz).
    data/site/baseline_{unit}.parquet, effects_{unit}_{factor}.parquet
    data/site/reference.json   last_month; per unit: sorted reference scores (people with >= MIN_PICKS judged picks in their last
                               five judged years), per-pick reliability (split-half), people
Prints agreement with the project's frozen prescience score (artists) for the same people and window.
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
import score as S  # noqa: E402

X, D, REF = ROOT / "data" / "derived", ROOT / "data" / "mlhd", ROOT / "data" / "site"
LAST = 2026 * 12 + 8   # pipeline/periods.py, half lb
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
tmp = ROOT / "data" / "_tmp" / "site_base"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false; SET max_temp_directory_size='60GB'")

meta = {"last_month": LAST, "built": "2026-10-10", "min_picks": S.MIN_PICKS}
for unit in ("artist", "song"):
    if unit == "artist":
        con.execute(f"""CREATE OR REPLACE TABLE pk AS SELECT o.user, o.artist AS key, o.artist, o.m::INT AS m, o.plays_26w, o.e,
              ({MONTH.format(w='b.first_week')})::INT AS fm
            FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') o JOIN read_parquet('{X}/bets/lb/*.parquet') b ON b.user = o.user AND b.artist = o.artist
            WHERE o.m <= {LAST - 12}""")
    else:
        con.execute(f"""CREATE OR REPLACE TABLE pk AS SELECT s.user, s.recording AS key, s.artist, s.m::INT AS m, s.plays_26w, NULL::DOUBLE AS e,
              ({MONTH.format(w='u.first_week')})::INT AS fm
            FROM read_parquet('{X}/song_bets/lb.parquet') s JOIN read_parquet('{D}/user_recording/lb/*.parquet') u ON u.user = s.user AND u.recording = s.recording
            WHERE s.m <= {LAST - 12}""")
    feats = F.raw_features(con, "pk", unit)
    df = con.execute("SELECT user, key, artist, m, plays_26w, e, fm FROM pk").pl().join(feats, on=["key", "artist", "m"])
    df = df.with_columns(a0=(pl.col("a0") - pl.col("fm").is_between(pl.col("m") - 5, pl.col("m")).cast(pl.Int64)).clip(0))
    df = F.derive(df)
    base, eff, r = F.fit_effects(df)
    base.write_parquet(REF / f"baseline_{unit}.parquet")
    for name, t in eff.items():
        t.write_parquet(REF / f"effects_{unit}_{name}.parquet")
    df = df.with_columns(excess=pl.Series(r))
    chk = F.apply_effects(df.select("m", "bin", "g", *{c for f in F.FACTORS for c in (f if isinstance(f, list) else [f])}), unit)
    assert np.allclose(chk["excess"].to_numpy(), r, atol=1e-9), "stored effects don't reproduce the fit"
    if unit == "song":   # songs by one artist in the same month count as one pick, weighted by plays
        df = df.group_by("user", "artist", "m").agg(excess=(pl.col("excess") * pl.col("plays_26w")).sum() / pl.col("plays_26w").sum(), e=pl.lit(None, pl.Float64).first())
    df = df.with_columns(last=pl.col("m").max().over("user")).filter(pl.col("m") > pl.col("last") - 12 * S.WINDOW_YEARS)
    per = df.group_by("user").agg(s=pl.col("excess").sum() / (pl.len() + S.SHRINK), n=pl.len())
    refp = per.filter(pl.col("n") >= S.MIN_PICKS)
    per.write_parquet(REF / f"_ref_scores_{unit}.parquet")   # per person, for engine tests (not used by the site)
    h = (df.sort("user", "m").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
         .group_by("user", "half").agg(s=pl.col("excess").sum() / (pl.len() + S.SHRINK / 2), n=pl.len()))
    h = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls().filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
    rr = spearmanr(h["s_0"], h["s_1"]).statistic
    nh = float(np.median(h["n_0"].to_numpy()))
    r1 = rr / (nh - (nh - 1) * rr)
    meta[unit] = {"scores": sorted(round(float(v), 6) for v in refp["s"].to_list()), "per_pick": float(r1), "people": refp.height,
                  "split_half": float(rr), "median_half_picks": nh}
    print(f"{unit}: {df.height:,} window picks; reference people {refp.height:,}; split-half {rr:.3f} (median half {nh:.0f}) -> per pick {r1:.4f}; "
          f"reliability at {S.MIN_PICKS} / {S.SOLID_PICKS} picks {S.MIN_PICKS * r1 / (1 + (S.MIN_PICKS - 1) * r1):.2f} / "
          f"{S.SOLID_PICKS * r1 / (1 + (S.SOLID_PICKS - 1) * r1):.2f}", flush=True)
    if unit == "artist":
        fz = df.group_by("user").agg(f=pl.col("e").sum() / (pl.len() + S.SHRINK))
        j = refp.join(fz, on="user")
        print(f"  agreement with the project's frozen prescience score (same people, same window): Spearman {spearmanr(j['s'], j['f']).statistic:.3f}", flush=True)
(REF / "reference.json").write_text(json.dumps(meta))
shutil.rmtree(tmp, ignore_errors=True)
