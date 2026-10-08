"""Genre-based scenes (comparison version): k-means on MusicBrainz genre vectors of tagged artists.

    data/derived/scenes_genre/all.parquet   artist, scene_50, scene_200, top_genre
Artists without MusicBrainz genres are absent (that variant drops their bets).
"""

from pathlib import Path

import numpy as np
import polars as pl
import scipy.sparse as sp
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived" / "scenes_genre" / "all.parquet"
SEED = 7


def main():
    mb = pl.read_parquet(ROOT / "data" / "derived" / "mb_artists.parquet").filter(pl.col("genres").list.len() > 0)
    g = mb.select("artist", "genres").explode("genres").unnest("genres").rename({"name": "genre"})
    vocab = g.select("genre").unique().sort("genre").with_row_index("gcol")
    arts = mb.select("artist").with_row_index("row")
    g = g.join(vocab, on="genre").join(arts, on="artist")
    df = g.group_by("genre").agg(pl.col("artist").n_unique().alias("df"))
    g = g.join(df, on="genre").with_columns(
        w=(1 + pl.col("count").clip(lower_bound=0)).log() * (arts.height / pl.col("df")).log())
    X = normalize(sp.csr_matrix((g["w"].to_numpy(), (g["row"].to_numpy(), g["gcol"].to_numpy())),
                                shape=(arts.height, vocab.height)))
    out = mb.select("artist", top_genre=pl.col("genres").list.first().struct.field("name"))
    for k in [50, 200]:
        km = MiniBatchKMeans(n_clusters=k, random_state=SEED, batch_size=8192, n_init=3).fit(X)
        out = out.with_columns(pl.Series(f"scene_{k}", km.labels_.astype(np.int16)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    print(f"{out.height:,} tagged artists, {vocab.height:,} genres")


if __name__ == "__main__":
    main()
