"""How early can you tell an artist will break out? (2026-10-14, exploratory; Robert's question. ListenBrainz, artists.)

Artists whose first-ever ListenBrainz listener came in 2012-2020 ("born" that month, F). Outcome: a breakout = in the top 1% (argument 0.99) or 0.1% (0.999) of
its birth-year cohort by distinct listeners in its third year (months F+25..F+36). Checkpoints t = 0, 1, 3, 6, 12, 24 months after F;
at each, what was known by then (months F..F+t):
  listeners so far (distinct), new listeners in the latest month, committed fans so far (the study's 4-week rule; bet table),
  committed fans with a proven good track record (rated on picks up to two years before; pickers/rate_A_lb), and whether
  MusicBrainz has a release within 12 months before F (a genuinely new artist rather than an old one new to ListenBrainz).
Logistic regression trained on a random half of artists, scored on the other half:
  AUC (0.5 = coin flip, 1 = perfect), and for the 1% of artists the model rates most promising: how many were breakouts
  (vs 1% by chance) and what share of all breakouts they include. Model "listeners" uses listener counts only; "+ fans" adds
  committed fans and good pickers.
Also a fan-count view: artists that reached k = 1, 3, 10 committed fans, scored on what was known at the k-th fan's month.
Writes analysis/out/early_signal.json; prints a summary. Intermediate tables in data/_tmp/early (deleted at the end).
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
TMP = ROOT / "data" / "_tmp" / "early"; TMP.mkdir(parents=True, exist_ok=True)
Y0, Y1 = 2012, 2020
TS = [0, 1, 3, 6, 12, 24]
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='30GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"

# 1. birth month per artist; keep 2012-2020 births
con.execute(f"""CREATE TABLE birth AS SELECT artist, min(month) AS F FROM {uam} GROUP BY artist
                HAVING min(month) BETWEEN {Y0 * 12} AND {Y1 * 12 + 11}""")
print("artists born", Y0, "-", Y1, con.execute("SELECT count(*) FROM birth").fetchone()[0], flush=True)
# 2. each listener's first month with the artist (months since birth), and year-3 listeners
con.execute(f"""COPY (SELECT u.artist, (min(u.month) - b.F)::INT AS d FROM {uam} u JOIN birth b USING (artist) GROUP BY u.user, u.artist, b.F)
                TO '{TMP}/first.parquet' (FORMAT parquet)""")
con.execute(f"""COPY (SELECT u.artist, count(DISTINCT u.user) AS y3 FROM {uam} u JOIN birth b USING (artist)
                      WHERE u.month BETWEEN b.F + 25 AND b.F + 36 GROUP BY u.artist) TO '{TMP}/y3.parquet' (FORMAT parquet)""")
print("listener tables done", flush=True)
first = f"read_parquet('{TMP}/first.parquet')"
cols = []
for t in TS:
    cols += [f"count(*) FILTER (WHERE d <= {t}) AS L{t}", f"count(*) FILTER (WHERE d = {t}) AS N{t}"]
A = con.execute(f"SELECT artist, {', '.join(cols)} FROM {first} GROUP BY artist").pl()
# committed fans (bet table) and good-picker fans (rate table), by months since birth
picks = con.execute(f"""SELECT p.artist, (p.m - b.F)::INT AS d, count(*) AS c FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') p
                        JOIN birth b USING (artist) WHERE p.m - b.F BETWEEN 0 AND 24 GROUP BY ALL""").pl()
good = con.execute(f"""SELECT r.artist, (r.m - b.F)::INT AS d, sum(r.n_good)::BIGINT AS g, sum(r.n_good + r.n_ord + r.n_poor)::BIGINT AS r
                       FROM read_parquet('{X}/pickers/rate_A_lb.parquet') r JOIN birth b USING (artist) WHERE r.m - b.F BETWEEN 0 AND 24 GROUP BY ALL""").pl()
rel = con.execute(f"""SELECT DISTINCT b.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') r JOIN birth b USING (artist)
                      WHERE r.rm BETWEEN b.F - 12 AND b.F""").pl().with_columns(newrel=pl.lit(1))
B_ = con.execute("SELECT * FROM birth").pl().with_columns(cohort=pl.col("F") // 12)
y3 = pl.read_parquet(TMP / "y3.parquet")
for t in TS:
    A = A.join(picks.filter(pl.col("d") <= t).group_by("artist").agg(pl.col("c").sum().alias(f"C{t}")), on="artist", how="left")
    A = A.join(good.filter(pl.col("d") <= t).group_by("artist").agg(pl.col("g").sum().alias(f"G{t}"), pl.col("r").sum().alias(f"R{t}")), on="artist", how="left")
D = (B_.join(A, on="artist").join(y3, on="artist", how="left").join(rel, on="artist", how="left").fill_null(0))
import sys
Q = float(sys.argv[1]) if len(sys.argv) > 1 else 0.99   # 0.99: top 1% of the cohort; 0.999: top 0.1%
NEW = len(sys.argv) > 2 and sys.argv[2] == "new"          # only genuinely new artists (a release in the 12 months before F)
if NEW:
    D = D.filter(pl.col("newrel") == 1)
cut = D.group_by("cohort").agg(thr=pl.col("y3").quantile(Q, "higher"))
D = D.join(cut, on="cohort").with_columns(hit=(pl.col("y3") >= pl.col("thr")) & (pl.col("y3") > 0))
print(f"{D.height:,} artists; breakouts {D['hit'].sum():,} ({D['hit'].mean():.2%}); year-3 listeners needed by cohort:",
      dict(sorted(zip(cut["cohort"].to_list(), cut["thr"].to_list()))), flush=True)
rng = np.random.default_rng(4242)
D = D.with_columns(test=pl.Series(rng.random(D.height) < 0.5))
coh = D.select(pl.col("cohort").cast(pl.Utf8)).to_dummies(drop_first=True).to_numpy().astype(float)


def evaluate(Xm, y, test, label):
    m = LogisticRegression(max_iter=2000, C=1.0).fit(Xm[~test], y[~test])
    p = m.predict_proba(Xm[test])[:, 1]; yt = y[test]
    k = max(1, int(round(0.01 * len(p)))); top = np.argsort(-p)[:k]
    return {"model": label, "auc": float(roc_auc_score(yt, p)), "top1_hit_rate": float(yt[top].mean()), "base_rate": float(yt.mean()),
            "share_caught": float(yt[top].sum() / max(yt.sum(), 1)), "n_test": int(len(p))}


out = {"by_month": [], "by_fans": []}
y = D["hit"].to_numpy(); test = D["test"].to_numpy()
for t in TS:
    lis = np.column_stack([np.log1p(D[f"L{t}"].to_numpy()), np.log1p(D[f"N{t}"].to_numpy())])
    com = np.column_stack([np.log1p(D[f"C{t}"].to_numpy()), np.log1p(D[f"R{t}"].to_numpy()), D["newrel"].to_numpy()])
    gd = np.log1p(D[f"G{t}"].to_numpy())[:, None]
    for label, Xm in (("listeners", np.column_stack([lis, coh])), ("+ committed fans", np.column_stack([lis, com, coh])),
                      ("+ good pickers", np.column_stack([lis, com, gd, coh]))):
        r = {"t": t, **evaluate(Xm, y, test, label)}; out["by_month"].append(r)
        print(f"t={t:>2} {label:16s} AUC {r['auc']:.3f} | top 1% flagged: {r['top1_hit_rate']:.1%} breakouts (base {r['base_rate']:.1%}), "
              f"{r['share_caught']:.0%} of all breakouts", flush=True)

# fan-count view: artists reaching k committed fans within 24 months; known = everything up to the month of the k-th fan
pc_ = picks.sort("artist", "d").with_columns(cum=pl.col("c").cum_sum().over("artist"))
for k in (1, 3, 10):
    when = pc_.filter(pl.col("cum") >= k).group_by("artist").agg(dk=pl.col("d").min())
    Dk = D.join(when, on="artist")
    # values at month dk: listeners so far and good fans so far, from the per-month tables
    fk = pl.read_parquet(TMP / "first.parquet").join(when, on="artist").filter(pl.col("d") <= pl.col("dk")).group_by("artist").agg(Lk=pl.len())
    gk = good.join(when, on="artist").filter(pl.col("d") <= pl.col("dk")).group_by("artist").agg(Gk=pl.col("g").sum(), Rk=pl.col("r").sum())
    Dk = Dk.join(fk, on="artist", how="left").join(gk, on="artist", how="left").fill_null(0)
    yk, tk = Dk["hit"].to_numpy(), Dk["test"].to_numpy()
    ck = Dk.select(pl.col("cohort").cast(pl.Utf8)).to_dummies(drop_first=True).to_numpy().astype(float)
    base = np.column_stack([np.log1p(Dk["Lk"].to_numpy()), Dk["dk"].to_numpy(), np.log1p(Dk["Rk"].to_numpy()), Dk["newrel"].to_numpy(), ck])
    full = np.column_stack([base, np.log1p(Dk["Gk"].to_numpy())])
    for label, Xm in (("listeners + speed", base), ("+ good pickers", full)):
        r = {"k": k, "artists": Dk.height, **evaluate(Xm, yk, tk, label)}; out["by_fans"].append(r)
        print(f"k={k:>2} fans ({Dk.height:,} artists) {label:20s} AUC {r['auc']:.3f} | top 1% flagged: {r['top1_hit_rate']:.1%} breakouts "
              f"(base {r['base_rate']:.1%}), {r['share_caught']:.0%} of all breakouts", flush=True)
(ROOT / "analysis" / "out" / f"early_signal_{Q}{'_new' if NEW else ''}.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
