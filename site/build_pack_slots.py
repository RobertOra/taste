"""Step 2b (2026-10-14): where each artist and song lives in the pack, so the site needs far fewer requests.

Before: every name was filed by its own hash, so one person's ~7,500 lookups touched ~5,000 places (one request each), and GitHub
Pages rate-limited the site. Now everything about an artist is filed together: an artist name and every song by that artist go to
the shard of slot = name_hash(norm_name(artist)) (site/normalize.py, the same normalization the site uses for song keys). One
request then answers an artist and all its songs, including song guesses that turn out not to exist.
Also a Bloom filter over every slot that has anything in it, so the site can skip artists the reference doesn't know without a
request (no false negatives; about 1% false positives, which only cost a wasted request; results are exact either way).
Writes (SITE_REF, default data/site): slot_artist.parquet (artist_name_h, slot), slot_song.parquet (rec, slot), slots.bloom + its
parameters in slots_bloom.json. build_pack_files.py uses them when SHARD_BY=artist.
"""
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
from normalize import norm_name  # noqa: E402
import score as S  # noqa: E402  (name_hash)

REF = Path(os.environ.get("SITE_REF", ROOT / "data" / "site"))
LB = ROOT / "data" / "lb"


def slots(names):
    return [S.name_hash(norm_name(n.strip().lower())) for n in names]


def slot_column(texts):
    step = 100_000
    with Pool(6) as pool:
        return [x for part in pool.imap(slots, [texts[i:i + step] for i in range(0, len(texts), step)]) for x in part]


def main():
    con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
    # artists: every name in the pack (artist_map rows of artists with data), its text from data/lb/artist_names
    an = con.execute(f"""SELECT m.artist_name_h, n.name FROM read_parquet('{REF}/artist_map.parquet') m JOIN read_parquet('{LB}/artist_names.parquet') n USING (artist_name_h)
                         WHERE m.artist IN (SELECT DISTINCT artist FROM read_parquet('{REF}/pack_artist_rows.parquet'))""").pl()
    an = an.with_columns(slot=pl.Series(slot_column(an["name"].to_list()), dtype=pl.Int64)).select("artist_name_h", "slot")
    an.write_parquet(REF / "slot_artist.parquet")
    print(f"artist names: {an.height:,}", flush=True)
    # songs: each song id in the pack, the artist text of any of its spellings (all spellings share the normalized artist)
    parts = sorted((LB / "names" / "names").glob("part-*.parquet"))
    con.execute(f"CREATE TABLE need AS SELECT rec FROM read_parquet('{REF}/pack_song_first.parquet')")
    sa = con.execute(f"""SELECT m.rec, any_value(n.artist) AS artist FROM read_parquet('{REF}/rec_map.parquet') m SEMI JOIN need USING (rec)
                         JOIN read_parquet({[str(p) for p in parts]}) n USING (rec_name_h) GROUP BY m.rec""").pl()
    missing = con.execute("SELECT count(*) FROM need").fetchone()[0] - sa.height
    uniq = sa.select("artist").unique()
    uniq = uniq.with_columns(slot=pl.Series(slot_column(uniq["artist"].to_list()), dtype=pl.Int64))
    ss = sa.join(uniq, on="artist").select("rec", "slot")
    ss.write_parquet(REF / "slot_song.parquet")
    print(f"songs: {ss.height:,} ({missing:,} without an artist text)", flush=True)
    # Bloom filter over all slots with anything in them
    keys = np.unique(np.concatenate([an["slot"].to_numpy(), ss["slot"].to_numpy()])).view(np.uint64)
    n, p = len(keys), 0.01
    m = int(np.ceil(-n * np.log(p) / np.log(2) ** 2 / 64) * 64); k = max(1, round(m / n * np.log(2)))
    bits = np.zeros(m // 8, np.uint8)
    h1, h2 = keys & np.uint64(0xFFFFFFFF), (keys >> np.uint64(32)) | np.uint64(1)
    for i in range(k):
        pos = (h1 + np.uint64(i) * h2) % np.uint64(m)
        np.bitwise_or.at(bits, (pos >> np.uint64(3)).astype(np.int64), (np.uint8(1) << (pos & np.uint64(7)).astype(np.uint8)))
    (REF / "slots.bloom").write_bytes(bits.tobytes())
    (REF / "slots_bloom.json").write_text(json.dumps({"m": m, "k": k, "n": int(n)}))
    print(f"bloom: {n:,} slots, {m / 8 / 1e6:.1f} MB, k {k}", flush=True)


if __name__ == "__main__":   # workers (macOS spawns them) must not rerun the queries
    main()
