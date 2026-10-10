"""Stream the MusicBrainz release-group JSON dump; keep release dates for MLHD+ artists (nothing raw stored).

    data/derived/mb_release_groups.parquet
        artist (int64 id), rg_mbid, primary_type (Album/Single/EP/...), secondary_types, first_release_date
One row per (credited artist, release group). Used for the "music news" control: is a bet made shortly
before or after one of the artist's releases?
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
OUT = ROOT / "data" / "derived" / "mb_release_groups.parquet"
LB = "--lb" in sys.argv  # ListenBrainz artists: match on the numeric id (last 15 hex digits of the MBID)
if LB:
    OUT = ROOT / "data" / "derived" / "mb_release_groups_lb.parquet"


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
    resp = urllib.request.urlopen(urllib.request.Request(BASE + f"{latest}/release-group.tar.xz",
                                                         headers={"User-Agent": "taste-research/0.1"}), timeout=300)
    cols = {"mbid": [], "rg_mbid": [], "primary_type": [], "secondary_types": [], "first_release_date": []}
    seen = 0
    with tarfile.open(fileobj=lzma.LZMAFile(resp), mode="r|") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith("mbdump/release-group"):
                continue
            for line in tar.extractfile(member):
                seen += 1
                rg = json.loads(line)
                date = rg.get("first-release-date") or None
                for credit in rg.get("artist-credit") or []:
                    a = (credit.get("artist") or {}).get("id")
                    if a and ((mid(a) in wanted_ids) if LB else (a in wanted)):
                        cols["mbid"].append(a)
                        cols["rg_mbid"].append(rg["id"])
                        cols["primary_type"].append(rg.get("primary-type"))
                        cols["secondary_types"].append(",".join(rg.get("secondary-types") or []))
                        cols["first_release_date"].append(date)
                if seen % 1_000_000 == 0:
                    print(f"{seen:,} release groups read, {len(cols['mbid']):,} kept", flush=True)
    df = pl.DataFrame(cols).with_columns(
        artist=pl.col("mbid").str.replace_all("-", "", literal=True).str.slice(-15).str.to_integer(base=16))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    print(f"dump {latest}: {seen:,} release groups; kept {df.height:,} rows for "
          f"{df['artist'].n_unique():,} artists; with a date {df.filter(pl.col('first_release_date').is_not_null()).height:,}")


if __name__ == "__main__":
    main()
