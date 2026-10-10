"""Time-respecting scenes: for each year Y, relatedness uses only listening before Y (explore half).

For year Y:
  1. Embedding: users x core artists (>= MIN_LISTENERS listeners before Y), log1p(plays) * idf, truncated SVD,
     fitted on listening in months < Y (user sample capped at FIT_USERS).
  2. Every user with listening before Y gets a vector (fold-in of their pre-Y listening).
  3. Artists with >= MIN_LISTENERS listeners before Y keep their fitted (pre-Y) co-listening vector. Other
     artists (new or small) get the mean of their year-Y listeners' pre-Y vectors, after subtracting the
     average user vector (otherwise diverse audiences all average to the same generic point).
     No listening from Y onward shapes the embedding or a listener's vector.

    data/derived/scenes_yearly/explore.parquet   artist, year, n_listeners (year-Y listeners with history),
                                                 scene_50, scene_200, scene_1000
Scene ids are per year (not aligned across years); benchmarks compare within a month, so that's fine.
"""

import os
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import scipy.sparse as sp
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD

ROOT = Path(__file__).resolve().parent.parent
import sys
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from periods import scene_years  # noqa: E402
HALF = sys.argv[1] if len(sys.argv) > 1 else "explore"  # explore (default) or lb
UAM = ROOT / "data" / "derived" / "user_artist_month" / HALF
OUT = ROOT / "data" / "derived" / "scenes_yearly" / f"{HALF}.parquet"
YEARS = range(2006, 2013) if HALF == "explore" else scene_years(HALF)
MIN_LISTENERS = 50
FIT_USERS = 75_000
DIM = 64
KS = [50, 200, 1000]
SEED = 7


def year_scenes(con, y):
    m0 = y * 12
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pre AS
        SELECT user, artist, sum(plays) AS plays FROM read_parquet('{UAM}/*.parquet') WHERE month < {m0} GROUP BY ALL""")
    n_users = con.execute("SELECT count(DISTINCT user) FROM pre").fetchone()[0]
    core = con.sql(f"""SELECT artist, count(*)::INT AS n FROM pre GROUP BY artist HAVING count(*) >= {MIN_LISTENERS}
                       ORDER BY artist""").pl().with_row_index("col")
    users = con.sql("SELECT DISTINCT user FROM pre ORDER BY user").pl().with_row_index("row")
    con.register("core", core.to_arrow())
    con.register("users", users.to_arrow())
    rows = con.sql("""SELECT u.row, c.col, ln(1 + p.plays) AS w FROM pre p
                      JOIN core c USING (artist) JOIN users u USING (user)""").pl()
    idf = np.log(n_users / core["n"].to_numpy()).astype(np.float32)
    X = sp.csr_matrix((rows["w"].to_numpy().astype(np.float32), (rows["row"].to_numpy(), rows["col"].to_numpy())),
                      shape=(users.height, core.height)) @ sp.diags(idf)
    del rows
    rng = np.random.default_rng(SEED)
    fit_rows = rng.choice(users.height, size=min(FIT_USERS, users.height), replace=False)
    svd = TruncatedSVD(n_components=DIM, algorithm="randomized", n_iter=7, random_state=SEED).fit(X[fit_rows])
    V = svd.components_.T
    U = X @ V
    U /= np.maximum(np.linalg.norm(U, axis=1, keepdims=True), 1e-9)
    U -= U.mean(axis=0, keepdims=True)
    core_vec = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
    del X

    # Audiences in year Y, described by their pre-Y vectors.
    cur = con.sql(f"""SELECT DISTINCT l.artist, u.row FROM read_parquet('{UAM}/*.parquet') l JOIN users u USING (user)
                      WHERE l.month BETWEEN {m0} AND {m0 + 11}""").pl()
    arts = cur.select("artist").unique().sort("artist").with_row_index("acol")
    cur = cur.join(arts, on="artist")
    M = sp.csr_matrix((np.ones(cur.height, dtype=np.float32), (cur["acol"].to_numpy(), cur["row"].to_numpy())),
                      shape=(arts.height, users.height))
    n_list = np.asarray(M.sum(axis=1)).ravel().astype(np.int32)
    A = M @ U
    A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-9)
    del M, cur, U
    ci = arts.join(core.select("artist", "col"), on="artist", how="inner")
    A[ci["acol"].to_numpy()] = core_vec[ci["col"].to_numpy()]
    out = arts.select("artist").with_columns(year=pl.lit(y, pl.Int16), n_listeners=pl.Series(n_list))
    for k in KS:
        k_eff = min(k, core.height // 20)
        km = MiniBatchKMeans(n_clusters=k_eff, random_state=SEED, batch_size=8192, n_init=3, max_iter=200).fit(core_vec)
        C = km.cluster_centers_ / np.linalg.norm(km.cluster_centers_, axis=1, keepdims=True)
        lab = np.concatenate([np.argmax(A[i:i + 200_000] @ C.T, axis=1) for i in range(0, A.shape[0], 200_000)])
        out = out.with_columns(pl.Series(f"scene_{k}", lab.astype(np.int16)))
    print(f"{y}: pre-period users {n_users:,}, core artists {core.height:,}, artists placed {out.height:,}, "
          f"explained var {svd.explained_variance_ratio_.sum():.3f}", flush=True)
    return out


def main():
    tmp = ROOT / "data" / "_tmp" / f"scenes-y-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'")
    parts = [year_scenes(con, y) for y in YEARS]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pl.concat(parts).write_parquet(OUT)


if __name__ == "__main__":
    main()
