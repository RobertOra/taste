"""Static-site reference data (artists only, browser-sized): baselines, effects and reference scores refit on eligible picks,
plus sharded per-artist binary files the browser fetches on demand. Works on GitHub Pages and Cloudflare Pages
(16,384 shard files, each a few kB).

Eligible artists: at least 2 ListenBrainz listeners first played them since 2011 (excluding the picker; a visitor isn't in
ListenBrainz), i.e. shipped artists have >= 2 adopters since 2011. 97.8% of ListenBrainz artist picks qualify.
    site/static/data/meta.json          last month, baseline (m, bin), effects, reference scores, per-pick reliability, countries
    site/static/data/s/XXXX.bin         names (blake2b-8 of the lowercased trimmed name, low 14 bits = shard) -> artist records:
                                        country, first month, monthly new listeners since 2011, scene by year, release months
Binary layout (little endian), see site/static/engine.js decodeShard().
"""
import json
import shutil
import struct
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

X, REF, OUT = ROOT / "data" / "derived", ROOT / "data" / "site", ROOT / "site" / "static" / "data"
LAST, Y0 = 2026 * 12 + 8, 2011 * 12
SHARD_BITS = 14
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
tmp = ROOT / "data" / "_tmp" / "site_static"; tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
con.execute(f"CREATE TABLE tot AS SELECT artist, sum(adopters)::BIGINT AS t FROM read_parquet('{REF}/artist_adopt.parquet') WHERE month >= {Y0} GROUP BY artist")

# ---- 1. refit on eligible picks (others >= 2)
con.execute(f"""CREATE TABLE pk AS SELECT o.user, o.artist AS key, o.artist, o.m::INT AS m, o.plays_26w, o.e, ({MONTH.format(w='b.first_week')})::INT AS fm
    FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') o JOIN read_parquet('{X}/bets/lb/*.parquet') b ON b.user = o.user AND b.artist = o.artist
    JOIN tot ON tot.artist = o.artist
    WHERE o.m <= {LAST - 12} AND tot.t - ((({MONTH.format(w='b.first_week')})::INT >= {Y0})::INT) >= 2""")
feats = F.raw_features(con, "pk", "artist")
df = con.execute("SELECT user, key, artist, m, plays_26w, e, fm FROM pk").pl().join(feats, on=["key", "artist", "m"])
df = F.derive(df.with_columns(a0=(pl.col("a0") - pl.col("fm").is_between(pl.col("m") - 5, pl.col("m")).cast(pl.Int64)).clip(0)))
base, eff, r = F.fit_effects(df)
df = df.with_columns(excess=pl.Series(r)).with_columns(last=pl.col("m").max().over("user")).filter(pl.col("m") > pl.col("last") - 12 * S.WINDOW_YEARS)
per = df.group_by("user").agg(s=pl.col("excess").sum() / (pl.len() + S.SHRINK), n=pl.len(), f=pl.col("e").sum() / (pl.len() + S.SHRINK))
refp = per.filter(pl.col("n") >= S.MIN_PICKS)
h = (df.sort("user", "m").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
     .group_by("user", "half").agg(s=pl.col("excess").sum() / (pl.len() + S.SHRINK / 2), n=pl.len()))
h = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls().filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
rr = spearmanr(h["s_0"], h["s_1"]).statistic
nh = float(np.median(h["n_0"].to_numpy()))
r1 = rr / (nh - (nh - 1) * rr)
print(f"eligible picks {df.height:,}; reference people {refp.height:,}; per-pick reliability {r1:.4f} "
      f"(at 110 / 250: {110 * r1 / (1 + 109 * r1):.2f} / {250 * r1 / (1 + 249 * r1):.2f}); agreement with frozen {spearmanr(refp['s'], refp['f']).statistic:.3f}", flush=True)
per.select("user", "s", "n").write_parquet(REF / "_ref_scores_static.parquet")
meta = {"last_month": LAST, "y0": Y0, "shard_bits": SHARD_BITS, "min_picks": S.MIN_PICKS, "solid_picks": S.SOLID_PICKS, "shrink": S.SHRINK,
        "window_years": S.WINDOW_YEARS, "per_pick": r1, "people": refp.height, "scores": sorted(round(float(v), 6) for v in refp["s"].to_list()),
        "baseline": [[int(a), int(b), round(float(c), 6), round(float(d), 6), round(float(e), 6)] for a, b, c, d, e in base.select("m", "bin", "g_mean", "ten_rate", "up3_rate").iter_rows()],
        "effects": {name: [[*(list(row[:-1])), round(float(row[-1]), 6)] for row in t.iter_rows()] for name, t in eff.items()}}
OUT.mkdir(parents=True, exist_ok=True)
for name, t in eff.items():   # also for the Python static engine
    t.write_parquet(REF / f"static_effects_artist_{name}.parquet")
base.write_parquet(REF / "static_baseline_artist.parquet")
# ---- 2. shards
con.execute("CREATE TABLE ship AS SELECT artist FROM tot WHERE t >= 2")
names = con.execute(f"SELECT m.artist_name_h AS h, m.artist FROM read_parquet('{REF}/artist_map.parquet') m SEMI JOIN ship USING (artist)").pl()
names = names.with_columns(shard=(pl.col("h") & ((1 << SHARD_BITS) - 1)).cast(pl.Int32))
print(f"names {names.height:,}, artists {names['artist'].n_unique():,}", flush=True)
info = con.execute(f"SELECT i.artist, i.country, i.first_month FROM read_parquet('{REF}/artist_info.parquet') i SEMI JOIN ship USING (artist)").pl()
countries = sorted(set(info["country"].to_list()) | {"?"})
cidx = {c: i for i, c in enumerate(countries)}
meta["countries"] = countries
(OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
print(f"meta.json {(OUT / 'meta.json').stat().st_size / 1e3:.0f} kB", flush=True)
adopt = con.execute(f"SELECT a.artist, a.month, a.adopters FROM read_parquet('{REF}/artist_adopt.parquet') a SEMI JOIN ship USING (artist) WHERE a.month >= {Y0 - 12} ORDER BY artist, month").pl()
scene = con.execute(f"SELECT s.artist, s.year, s.scene FROM read_parquet('{REF}/artist_scene.parquet') s SEMI JOIN ship USING (artist) WHERE s.year >= 2010 ORDER BY artist, year").pl()
rel = con.execute(f"SELECT r.artist, r.rm FROM read_parquet('{REF}/artist_release.parquet') r SEMI JOIN ship USING (artist) WHERE r.rm >= {Y0 - 12} ORDER BY artist, rm").pl()
anyrel = set(con.execute(f"SELECT DISTINCT r.artist FROM read_parquet('{REF}/artist_release.parquet') r SEMI JOIN ship USING (artist)").pl()["artist"].to_list())


def varint(n, out):
    while True:
        b = n & 0x7F; n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b); return


def group(d, cols):
    return {row[0]: row[1:] for row in d.group_by("artist", maintain_order=True).agg([pl.col(c) for c in cols]).iter_rows()}


gid = {a: i for i, a in enumerate(sorted(names["artist"].unique().to_list()))}   # global artist index: one pick per artist across shards
A = group(adopt, ["month", "adopters"]); SC = group(scene, ["year", "scene"]); R = group(rel, ["rm"])
I = {a: (c, f) for a, c, f in info.iter_rows()}
sd = OUT / "s"
if sd.exists():
    shutil.rmtree(sd)
sd.mkdir()
total = 0
for shard, g in names.sort("shard").group_by("shard", maintain_order=True):
    arts = g["artist"].unique(maintain_order=True).to_list()
    ai = {a: i for i, a in enumerate(arts)}
    buf = bytearray(struct.pack("<HH", g.height, len(arts)))
    for hh, a in zip(g["h"].to_list(), g["artist"].to_list()):
        buf += struct.pack("<qH", hh, ai[a])
    for a in arts:
        c, fmo = I.get(a, ("?", None))
        rec = bytearray(struct.pack("<IHH", gid[a], cidx.get(c, cidx["?"]), (fmo if fmo is not None else 0) - 2000 * 12 + 1000))
        months, counts = A.get(a, ([], []))
        varint(len(months), rec); prev = Y0 - 12
        for mo, n in zip(months, counts):
            varint(mo - prev, rec); varint(int(n), rec); prev = mo
        ys, ss = SC.get(a, ([], []))
        varint(len(ys), rec)
        for yy, s_ in zip(ys, ss):
            rec.append(yy - 2000); rec.append(int(s_) if s_ >= 0 else 255)
        rms = R.get(a, ([],))[0] if a in R else []
        rec.append(1 if a in anyrel else 0)   # has any known release (any year): "none known" is its own release category
        varint(len(rms), rec); prev = Y0 - 12
        for rm in rms:
            varint(rm - prev, rec); prev = rm
        buf += rec
    (sd / f"{shard[0]:04x}.bin").write_bytes(bytes(buf))
    total += len(buf)
files = list(sd.iterdir())
print(f"shards: {len(files):,} files, {total / 1e6:.0f} MB total, largest {max(f.stat().st_size for f in files) / 1e3:.0f} kB", flush=True)
shutil.rmtree(tmp, ignore_errors=True)
