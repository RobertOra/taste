"""Stream the MusicBrainz artist JSON dump and keep metadata for MLHD+ artists (nothing raw is stored).

    data/derived/mb_artists.parquet
        artist (int64 id), mbid, name, type, country, begin (YYYY[-MM[-DD]]), genres (list of {name, count}, by count),
        tags (list of {name, count}, top 20 by count)
Artists absent from the current dump (e.g. MBIDs merged since 2023) are simply missing.
"""

import json
import lzma
import tarfile
import urllib.request
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/"
OUT = ROOT / "data" / "derived" / "mb_artists.parquet"


def main():
    latest = urllib.request.urlopen(BASE + "LATEST").read().decode().strip()
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
                if a["id"] not in wanted:
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
    print(f"dump {latest}: {seen:,} artists read; kept {df.height:,} of {len(wanted):,} MLHD+ artists; "
          f"with genres {df.filter(pl.col('genres').list.len() > 0).height:,}; "
          f"with tags {df.filter(pl.col('tags').list.len() > 0).height:,}", flush=True)


if __name__ == "__main__":
    main()
