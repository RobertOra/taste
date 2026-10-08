"""Scenes: clusters of artists that the same people listen to (explore half only).

1. Core artists (>= MIN_LISTENERS explore listeners) x a hash sample of users, weights
   log1p(plays) * idf, truncated SVD -> artist embeddings (L2-normalised).
2. k-means on core artists for each k in KS.
3. Other artists are folded in: embed all users (their weighted core-artist rows x V), then an artist's
   vector = mean of its listeners' user vectors, assigned to the nearest centroid.

    data/derived/scenes/explore.parquet   artist, n_listeners, core, scene_<k> for each k
Note: built from the full 2005-2013 listening period (see SPEC revisions).
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
UA = ROOT / "data" / "derived" / "user_artist" / "explore"
OUT = ROOT / "data" / "derived" / "scenes" / "explore.parquet"
MIN_LISTENERS = 100
USER_SAMPLE_MOD = 4  # 1/4 of users for fitting the embedding
DIM = 64
KS = [50, 200, 1000]
SEED = 7


def main():
    con = duckdb.connect()
    tmp = ROOT / "data" / "_tmp" / f"scenes-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'")
    ua = f"read_parquet('{UA}/*.parquet')"
    listeners = con.sql(f"SELECT artist, count(*)::INT AS n_listeners FROM {ua} GROUP BY artist").pl()
    core = listeners.filter(pl.col("n_listeners") >= MIN_LISTENERS).sort("artist").with_row_index("col")
    n_users = con.sql(f"SELECT count(DISTINCT user) FROM {ua}").fetchone()[0]
    con.register("core", core.to_arrow())

    # Fit embedding on a user sample.
    fit = con.sql(f"""SELECT dense_rank() OVER (ORDER BY ua.user) - 1 AS row, c.col, ln(1 + ua.plays) AS w
                      FROM {ua} ua JOIN core c USING (artist) WHERE hash(ua.user) % {USER_SAMPLE_MOD} = 0""").pl()
    X = sp.csr_matrix((fit["w"].to_numpy(), (fit["row"].to_numpy(), fit["col"].to_numpy())),
                      shape=(fit["row"].max() + 1, core.height), dtype=np.float32)
    del fit
    idf = np.log(n_users / core["n_listeners"].to_numpy()).astype(np.float32)
    X = X @ sp.diags(idf)
    print(f"fit matrix {X.shape}, nnz {X.nnz:,}", flush=True)
    svd = TruncatedSVD(n_components=DIM, algorithm="randomized", n_iter=7, random_state=SEED)
    svd.fit(X)
    V = svd.components_.T  # artists x DIM
    del X
    core_vec = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
    print(f"explained variance {svd.explained_variance_ratio_.sum():.3f}", flush=True)

    # Fold in: user vectors for all users, then artist vectors as listener means (all artists).
    users = con.sql(f"SELECT DISTINCT user FROM {ua} ORDER BY user").pl().with_row_index("row")
    con.register("users", users.to_arrow())
    rows = con.sql(f"""SELECT u.row, c.col, ln(1 + ua.plays) AS w FROM {ua} ua
                       JOIN core c USING (artist) JOIN users u USING (user)""").pl()
    XU = sp.csr_matrix((rows["w"].to_numpy(), (rows["row"].to_numpy(), rows["col"].to_numpy())),
                       shape=(users.height, core.height), dtype=np.float32) @ sp.diags(idf)
    del rows
    U = XU @ V
    U /= np.maximum(np.linalg.norm(U, axis=1, keepdims=True), 1e-9)
    del XU
    allart = listeners.sort("artist").with_row_index("acol")
    con.register("allart", allart.to_arrow())
    pairs = con.sql(f"""SELECT u.row, a.acol FROM {ua} ua JOIN allart a USING (artist) JOIN users u USING (user)""").pl()
    M = sp.csr_matrix((np.ones(pairs.height, dtype=np.float32), (pairs["acol"].to_numpy(), pairs["row"].to_numpy())),
                      shape=(allart.height, users.height))
    del pairs
    A = M @ U
    A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-9)
    del M, U
    # Core artists keep their fitted vectors.
    core_idx = allart.join(core.select("artist", "col"), on="artist", how="inner")
    A[core_idx["acol"].to_numpy()] = core_vec[core_idx["col"].to_numpy()]

    out = allart.select("artist", "n_listeners").with_columns(core=pl.col("n_listeners") >= MIN_LISTENERS)
    for k in KS:
        km = MiniBatchKMeans(n_clusters=k, random_state=SEED, batch_size=8192, n_init=5, max_iter=200)
        km.fit(core_vec)
        C = km.cluster_centers_ / np.linalg.norm(km.cluster_centers_, axis=1, keepdims=True)
        labels = np.concatenate([np.argmax(A[i:i + 200_000] @ C.T, axis=1) for i in range(0, A.shape[0], 200_000)])
        out = out.with_columns(pl.Series(f"scene_{k}", labels.astype(np.int16)))
        sizes = np.bincount(labels[out["core"].to_numpy()], minlength=k)
        print(f"k={k}: core artists per scene min/median/max {sizes.min()}/{int(np.median(sizes))}/{sizes.max()}",
              flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    np.save(OUT.with_suffix(".artist_vectors.npy"), A.astype(np.float16))
    print(f"wrote {out.height:,} artists", flush=True)


if __name__ == "__main__":
    main()
