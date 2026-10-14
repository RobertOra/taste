"""How early can you tell a song will break out? (2026-10-14, exploratory; the song version of early_signal.py. ListenBrainz.)

Songs (the study's LB song ids, data/mlhd/raw/lb) whose first-ever listener came in 2012-2020 ("born" in month F). Breakout =
top 1% of the birth-year cohort by distinct listeners in the third year (F+25..F+36). Checkpoints t = 0, 1, 3, 6, 12, 24 months:
listeners so far, new listeners in the latest month, committed fans so far (song bet table), good-picker fans so far
(pickers/song_rate_A_lb), and whether the song's artist had a release in the 2 months up to F (a proxy for a new song; there are
no song release dates). Logistic regression on a random half, scored on the other: AUC, and the 1% rated most promising.
Two populations: new songs (the release proxy) and a 2M random sample of all songs born then.
Births are found in 32 slices of songs and listener counts in 32 slices of people (users split by id), so memory and temp space stay small.
Writes analysis/out/early_signal_songs.json; intermediates in data/_tmp/early_songs (deleted at the end).
"""
import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "early_songs"; TMP.mkdir(parents=True, exist_ok=True)
Y0, Y1 = 2012, 2020
TS = [0, 1, 3, 6, 12, 24]
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
raw = f"read_parquet('{ROOT}/data/mlhd/raw/lb/*.parquet')"
MON = "(year(to_timestamp(ts)) * 12 + month(to_timestamp(ts)) - 1)::SMALLINT"

# 1. birth month and main artist per song
for c in range(32):   # in slices of songs (all at once overflows temp space)
    con.execute(f"""COPY (SELECT recording, min({MON}) AS F, any_value(artists[1]) AS artist FROM {raw} WHERE ((recording % 32) + 32) % 32 = {c}
                          GROUP BY recording HAVING min({MON}) BETWEEN {Y0 * 12} AND {Y1 * 12 + 11}) TO '{TMP}/birth_{c:02d}.parquet' (FORMAT parquet)""")
con.execute(f"COPY (SELECT * FROM read_parquet('{TMP}/birth_*.parquet')) TO '{TMP}/birth.parquet' (FORMAT parquet)")
for f in TMP.glob("birth_*.parquet"):
    f.unlink()
print("songs born", Y0, "-", Y1, con.execute(f"SELECT count(*) FROM read_parquet('{TMP}/birth.parquet')").fetchone()[0], flush=True)
# 2. per slice of people: each listener's first month (months since birth) and whether they listened in year 3; summed per song
cols = ", ".join(f"count(*) FILTER (WHERE d <= {t})::INT AS L{t}, count(*) FILTER (WHERE d = {t})::INT AS N{t}" for t in TS)
for c in range(32):
    con.execute(f"""COPY (WITH x AS (SELECT r.user, r.recording, {MON.replace('ts', 'r.ts')} - b.F AS dm FROM {raw} r
                                     JOIN read_parquet('{TMP}/birth.parquet') b USING (recording) WHERE r.user % 32 = {c}),
                               u AS (SELECT recording, min(dm) AS d, max((dm BETWEEN 25 AND 36)::INT) AS y3 FROM x GROUP BY user, recording)
                          SELECT recording, {cols}, sum(y3)::INT AS y3 FROM u GROUP BY recording)
                    TO '{TMP}/part_{c:02d}.parquet' (FORMAT parquet)""")
    print("slice", c, flush=True)
sums = ", ".join(f"sum(L{t})::INT AS L{t}, sum(N{t})::INT AS N{t}" for t in TS)
A = con.execute(f"SELECT recording, {sums}, sum(y3)::INT AS y3 FROM read_parquet('{TMP}/part_*.parquet') GROUP BY recording").pl()
B_ = pl.read_parquet(TMP / "birth.parquet").with_columns(cohort=pl.col("F") // 12)
picks = con.execute(f"""SELECT p.item AS recording, (p.m - b.F)::INT AS d, count(*)::BIGINT AS c FROM read_parquet('{X}/bet_outcomes/A_song_lb.parquet') p
                        JOIN read_parquet('{TMP}/birth.parquet') b ON b.recording = p.item WHERE p.m - b.F BETWEEN 0 AND 24 GROUP BY ALL""").pl()
good = con.execute(f"""SELECT r.artist AS recording, (r.m - b.F)::INT AS d, sum(r.n_good)::BIGINT AS g, sum(r.n_good + r.n_ord + r.n_poor)::BIGINT AS r
                       FROM read_parquet('{X}/pickers/song_rate_A_lb.parquet') r JOIN read_parquet('{TMP}/birth.parquet') b ON b.recording = r.artist
                       WHERE r.m - b.F BETWEEN 0 AND 24 GROUP BY ALL""").pl()
rel = con.execute(f"""SELECT DISTINCT b.recording FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a
                      JOIN read_parquet('{TMP}/birth.parquet') b ON b.artist = a.artist WHERE a.rm BETWEEN b.F - 2 AND b.F""").pl().with_columns(newrel=pl.lit(1))
for t in TS:
    A = A.join(picks.filter(pl.col("d") <= t).group_by("recording").agg(pl.col("c").sum().alias(f"C{t}")), on="recording", how="left")
    A = A.join(good.filter(pl.col("d") <= t).group_by("recording").agg(pl.col("g").sum().alias(f"G{t}"), pl.col("r").sum().alias(f"R{t}")), on="recording", how="left")
D0 = B_.join(A, on="recording").join(rel, on="recording", how="left").fill_null(0)
print(f"{D0.height:,} songs; {int(D0['newrel'].sum()):,} by an artist with a release in the 2 months up to the song's first listener", flush=True)


def evaluate(Xm, y, test, label):
    m = LogisticRegression(max_iter=2000).fit(Xm[~test], y[~test])
    p = m.predict_proba(Xm[test])[:, 1]; yt = y[test]
    k = max(1, int(round(0.01 * len(p)))); top = np.argsort(-p)[:k]
    return {"model": label, "auc": float(roc_auc_score(yt, p)), "top1_hit_rate": float(yt[top].mean()), "base_rate": float(yt.mean()),
            "share_caught": float(yt[top].sum() / max(yt.sum(), 1)), "n_test": int(len(p))}


out = {}
rng = np.random.default_rng(4243)
for pop in ("new songs", "all songs (2M sample)"):
    D = D0.filter(pl.col("newrel") == 1) if pop == "new songs" else D0.sample(min(2_000_000, D0.height), seed=7)
    cut = D.group_by("cohort").agg(thr=pl.col("y3").quantile(0.99, "higher"))
    D = D.join(cut, on="cohort").with_columns(hit=(pl.col("y3") >= pl.col("thr")) & (pl.col("y3") > 0))
    D = D.with_columns(test=pl.Series(rng.random(D.height) < 0.5))
    print(f"\n== {pop}: {D.height:,} songs, breakouts {int(D['hit'].sum()):,} ({D['hit'].mean():.2%}); year-3 listeners needed:",
          dict(sorted(zip(cut["cohort"].to_list(), cut["thr"].to_list()))), flush=True)
    coh = D.select(pl.col("cohort").cast(pl.Utf8)).to_dummies(drop_first=True).to_numpy().astype(float)
    y, test = D["hit"].to_numpy(), D["test"].to_numpy()
    out[pop] = []
    for t in TS:
        lis = np.column_stack([np.log1p(D[f"L{t}"].to_numpy()), np.log1p(D[f"N{t}"].to_numpy())])
        com = np.column_stack([np.log1p(D[f"C{t}"].to_numpy()), np.log1p(D[f"R{t}"].to_numpy())] + ([D["newrel"].to_numpy()] if pop != "new songs" else []))
        gd = np.log1p(D[f"G{t}"].to_numpy())[:, None]
        for label, Xm in (("listeners", np.column_stack([lis, coh])), ("+ committed fans", np.column_stack([lis, com, coh])),
                          ("+ good pickers", np.column_stack([lis, com, gd, coh]))):
            r = {"t": t, **evaluate(Xm, y, test, label)}; out[pop].append(r)
            print(f"t={t:>2} {label:16s} AUC {r['auc']:.3f} | top 1% flagged: {r['top1_hit_rate']:.1%} breakouts (base {r['base_rate']:.1%}), "
                  f"{r['share_caught']:.0%} of all breakouts", flush=True)
(ROOT / "analysis" / "out" / "early_signal_songs.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
