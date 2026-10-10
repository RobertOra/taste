"""Compare the engine's scores (site/test_engine.py) with the builder's reference scores for the same ListenBrainz users."""
from pathlib import Path

import polars as pl
from scipy.stats import spearmanr

REF = Path(__file__).resolve().parent.parent / "data" / "site"
t = pl.read_parquet(REF / "_engine_test.parquet")
for unit, sc, pk in (("artist", "a_score", "a_picks"), ("song", "s_score", "s_picks")):
    r = pl.read_parquet(REF / f"_ref_scores_{unit}.parquet")
    j = t.join(r, on="user").drop_nulls(sc)
    print(f"{unit}: {j.height} people | engine vs builder score Spearman {spearmanr(j[sc], j['s']).statistic:.3f} | "
          f"picks engine median {j[pk].median():.0f} vs builder {j['n'].median():.0f} | mean abs score diff {(j[sc] - j['s']).abs().mean():.4f} "
          f"(score sd {j['s'].std():.4f})")
print("checks raised:", t["checks"].value_counts().sort("count", descending=True).head(5).to_dicts())
