"""Fetch current (2026) ListenBrainz popularity for every MLHD+ artist.

    data/derived/lb_artist_popularity.parquet
        artist (int64 id), mbid, lb_listens, lb_users, fetched_at
Missing counts (artist unknown to ListenBrainz, e.g. merged MBIDs) are kept as null.
"""

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived" / "lb_artist_popularity.parquet"
URL = "https://api.listenbrainz.org/1/popularity/artist"
BATCH = 1000


def fetch(mbids):
    delay = 5
    while True:
        req = urllib.request.Request(URL, data=json.dumps({"artist_mbids": mbids}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "taste-research/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
                reset_in = float(resp.headers.get("X-RateLimit-Reset-In", 1))
                body = json.load(resp)
            if remaining <= 1:
                time.sleep(reset_in + 1)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("X-RateLimit-Reset-In", delay)) + 1)
                continue
            print(f"HTTP {e.code}; retry in {delay}s", flush=True)
        except OSError as e:
            print(f"{e}; retry in {delay}s", flush=True)
        time.sleep(delay)
        delay = min(delay * 2, 300)


def main():
    amap = pl.read_parquet(ROOT / "data" / "mlhd" / "artist_map" / "all" / "artist_map.parquet")
    mbids = amap["mbid"].to_list()
    rows = []
    for i in range(0, len(mbids), BATCH):
        for r in fetch(mbids[i:i + BATCH]):
            rows.append((r["artist_mbid"], r.get("total_listen_count"), r.get("total_user_count")))
        if i // BATCH % 50 == 0:
            print(f"{i + BATCH:,}/{len(mbids):,}", flush=True)
    got = pl.DataFrame(rows, schema={"mbid": pl.String, "lb_listens": pl.Int64, "lb_users": pl.Int64}, orient="row")
    out = amap.join(got.unique("mbid"), on="mbid", how="left").rename({"id": "artist"}).with_columns(
        fetched_at=pl.lit(datetime.now(timezone.utc).isoformat()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    print(out.select(pl.len(), pl.col("lb_users").is_null().sum().alias("null"),
                     (pl.col("lb_users") == 0).sum().alias("zero"), pl.col("lb_users").median().alias("median")))


if __name__ == "__main__":
    main()
