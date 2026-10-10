"""A Spotify-extended-history-shaped sample from one ListenBrainz user's real listening (artist names real, track names
unknown in our data, so songs won't match and the score falls back to artists). For testing the page only."""
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
user = int(sys.argv[1])
w = duckdb.sql(f"""SELECT week, artist_name_h, sum(plays)::INT AS n FROM read_parquet('{ROOT}/data/lb/user_artist_week/*.parquet')
                   WHERE user = {user} GROUP BY ALL""").pl().join(pl.read_parquet(ROOT / "data" / "lb" / "artist_names.parquet"), on="artist_name_h")
rng = random.Random(1)
recs = []
for wk, name, n in w.select("week", "name", "n").iter_rows():
    for i in range(min(n, 30)):
        ts = datetime.fromtimestamp(wk * 604800 + rng.randrange(604800), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        recs.append({"ts": ts, "ms_played": 200000, "master_metadata_track_name": f"Track {rng.randrange(20)}",
                     "master_metadata_album_artist_name": name, "master_metadata_album_album_name": "Album", "spotify_track_uri": None})
out = ROOT / "data" / "site" / "_sample_spotify.json"
out.write_text(json.dumps(recs)); print(out, len(recs), "plays")
