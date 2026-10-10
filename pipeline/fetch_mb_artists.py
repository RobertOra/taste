"""Stream the MusicBrainz artist JSON dump and keep metadata for MLHD+ artists (nothing raw is stored).

    data/derived/mb_artists.parquet
        artist (int64 id), mbid, name, type, country, begin (YYYY[-MM[-DD]]), genres (list of {name, count}, by count),
        tags (list of {name, count}, top 20 by count)
Artists absent from the current dump (e.g. MBIDs merged since 2023) are simply missing.
"""

import json
import sys
import lzma
import tarfile
import urllib.request
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/"
OUT = ROOT / "data" / "derived" / "mb_artists.parquet"
LB = "--lb" in sys.argv  # ListenBrainz artists: match on the numeric id (last 15 hex digits of the MBID)
if LB:
    OUT = ROOT / "data" / "derived" / "mb_artists_lb.parquet"


def main():
    latest = urllib.request.urlopen(BASE + "LATEST").read().decode().strip()
    if LB:
        import duckdb
        ids = duckdb.connect().execute(f"SELECT DISTINCT artist_mbid_id FROM read_parquet('{ROOT}/data/lb/name_mbid/*.parquet')").fetchall()
        wanted_ids = {r[0] for r in ids}
        mid = lambda m: int(m.replace("-", "")[-15:], 16) if m else None
        print(f"ListenBrainz artist ids wanted: {len(wanted_ids):,}", flush=True)
    else:
        wanted = set(pl.read_parquet(ROOT / "data" / "mlhd" / "artist_map" / "all" / "artist_map.parquet")["mbid"].to_list())
    resp = urllib.request.urlopen(urllib.request.Request(BASE + f"{latest}/artist.tar.xz",
                                                         headers={"User-Agent": "taste-research/0.1"}), timeout=300)
    rows, seen = [], 0
    with tarfile.open(fileobj=lzma.LZMAFile(resp), mode="r|") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith("mbdump/artist"):
                continue
            for line in tar.extractfile(member):
                seen += 1
                a = json.loads(line)
                if (mid(a["id"]) not in wanted_ids) if LB else (a["id"] not in wanted):
                    continue
                tags = sorted(a.get("tags") or [], key=lambda t: -t.get("count", 0))[:20]
                rows.append({
                    "mbid": a["id"], "name": a.get("name"), "type": a.get("type"), "country": a.get("country"),
                    "begin": (a.get("life-span") or {}).get("begin"),
                    "genres": sorted(({"name": g["name"], "count": g.get("count", 0)} for g in a.get("genres") or []),
                                     key=lambda g: -g["count"]),
                    "tags": [{"name": t["name"], "count": t.get("count", 0)} for t in tags],
                })
                if seen % 500_000 == 0:
                    print(f"{seen:,} dump artists read, {len(rows):,} kept", flush=True)
    df = pl.DataFrame(rows).with_columns(
        artist=pl.col("mbid").str.replace_all("-", "", literal=True).str.slice(-15).str.to_integer(base=16))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    print(f"dump {latest}: {seen:,} artists read; kept {df.height:,} of {len(wanted_ids) if LB else len(wanted):,} wanted artists; "
          f"with genres {df.filter(pl.col('genres').list.len() > 0).height:,}; "
          f"with tags {df.filter(pl.col('tags').list.len() > 0).height:,}", flush=True)


if __name__ == "__main__":
    main()
