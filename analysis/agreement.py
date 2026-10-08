"""Test 4: do the taste models agree? Correlates users' scores across model variants (explore half).

Usage: agreement.py model_A/<variant> model_D/<variant> ...   (paths under analysis/out/)
Prints Pearson and Spearman correlations of raw and shrunk scores, and the share of variance captured by
the first principal component of the standardized scores (one general factor?).
"""

import sys
from pathlib import Path

import numpy as np
import polars as pl

OUT = Path(__file__).resolve().parent / "out"


def main(paths):
    df = None
    for p in paths:
        u = pl.read_parquet(OUT / p / "users.parquet").select("user", pl.col("shrunk").alias(p))
        df = u if df is None else df.join(u, on="user", how="inner")
    names = paths
    print(f"users scored by all: {df.height:,}\n")
    M = df.select(names).to_numpy()
    pear = np.corrcoef(M.T)
    spear = df.select(names).to_pandas().corr(method="spearman").to_numpy()
    w = max(len(n) for n in names)
    print("Pearson (upper) / Spearman (lower) correlations of shrunk scores")
    for i, n in enumerate(names):
        cells = [f"{(pear[i, j] if j > i else spear[i, j] if j < i else 1):6.3f}" for j in range(len(names))]
        print(f"  {n:{w}s} " + " ".join(cells))
    Z = (M - M.mean(0)) / M.std(0)
    ev = np.linalg.eigvalsh(np.cov(Z.T))[::-1]
    print(f"\nfirst principal component explains {ev[0] / ev.sum():.3f} of standardized variance "
          f"(chance level with {len(names)} unrelated scores: {1 / len(names):.3f})")


if __name__ == "__main__":
    main(sys.argv[1:])
