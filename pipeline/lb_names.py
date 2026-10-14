"""Re-stream the ListenBrainz full listens dump (the same dump as lb_ingest.py) to keep the text of every song name, so songs
can later be keyed by a normalized name (NOTES.md, planned site reference rebuild, item 1). Nothing else is re-derived.

Per listen: the lowercased, trimmed artist name and track name, exactly as lb_ingest.py hashed them
(rec_name_h = name_hash(artist + "\\t" + track)). Per month: the distinct (rec_name_h, artist, track) seen, with listens.
Outputs (data/lb/names/):
    month/YYYY-MM.parquet    rec_name_h, artist, track, listens        (per month, deduplicated within the month)
    progress.json            months done, bytes read, MD5 when finished
Then, after all months: names.parquet = one row per rec_name_h (the most-listened spelling of the text, which is unique
anyway since the hash is of the text), written by --finish.
Disk guard: stops cleanly (exit 3) if free space < 25 GB or the project would exceed 178 GB (Robert's cap: 180 GB).
Months already in progress.json are skipped (their bytes are still read: a tar stream can't seek).

Usage: lb_names.py [--limit-months N] | lb_names.py --finish
"""
import argparse
import io
import json
import shutil
import sys
import tarfile
import time
from pathlib import Path

import duckdb
import orjson
import polars as pl
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lb_ingest import BASE, FILE, ResumingHTTP, name_hash  # noqa: E402  (same dump, same hashing)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "lb" / "names"


def project_bytes():
    return sum(f.stat().st_size for f in (ROOT / "data").rglob("*") if f.is_file())


def finish():
    con = duckdb.connect(); con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{ROOT}/data/_tmp/lbnames'; SET preserve_insertion_order=false")
    con.execute(f"""COPY (SELECT rec_name_h, arg_max(artist, listens) AS artist, arg_max(track, listens) AS track, sum(listens)::BIGINT AS listens
                         FROM read_parquet('{OUT}/month/*.parquet') GROUP BY rec_name_h)
                   TO '{OUT}/names.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    print(con.execute(f"SELECT count(*), sum(listens) FROM read_parquet('{OUT}/names.parquet')").fetchone())
    shutil.rmtree(ROOT / "data" / "_tmp" / "lbnames", ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-months", type=int, default=None)
    ap.add_argument("--finish", action="store_true")
    a = ap.parse_args()
    if a.finish:
        return finish()
    (OUT / "month").mkdir(parents=True, exist_ok=True)
    prog_path = OUT / "progress.json"
    prog = json.loads(prog_path.read_text()) if prog_path.exists() else {"months": {}}
    raw = ResumingHTTP(BASE + FILE)
    stream = zstandard.ZstdDecompressor(max_window_size=2 ** 31).stream_reader(io.BufferedReader(raw, 8 << 20))
    t0, done = time.time(), 0
    tf = tarfile.open(fileobj=stream, mode="r|")
    for member in tf:
        if not member.isfile() or "/listens/" not in member.name or not member.name.endswith(".listens"):
            continue
        y, mth = member.name.rsplit("/", 2)[-2], member.name.rsplit("/", 1)[-1].split(".")[0]
        ym = f"{int(y):04d}-{int(mth):02d}"
        if ym in prog["months"]:
            continue  # its bytes are read past by the tar stream
        free, proj = shutil.disk_usage(ROOT).free, project_bytes()
        if free < 25e9 or proj > 178e9:
            prog["paused"] = {"at": ym, "free_gb": round(free / 1e9, 1), "project_gb": round(proj / 1e9, 1)}
            prog_path.write_text(json.dumps(prog, indent=1))
            print(f"DISK GUARD: stopping before {ym} (free {free / 1e9:.1f} GB, project {proj / 1e9:.1f} GB)", flush=True)
            sys.exit(3)
        counts, n, bad = {}, 0, 0
        for line in tf.extractfile(member):
            try:
                tm = orjson.loads(line)["track_metadata"]
                an = (tm.get("artist_name") or "").strip().lower()
                tn = (tm.get("track_name") or "").strip().lower()
                key = (an, tn)
                counts[key] = counts.get(key, 0) + 1
                n += 1
            except Exception:
                bad += 1
        if counts:
            keys = list(counts)
            pl.DataFrame({"rec_name_h": [name_hash(a_ + "\t" + t_) for a_, t_ in keys], "artist": [k[0] for k in keys],
                          "track": [k[1] for k in keys], "listens": list(counts.values())},
                         schema={"rec_name_h": pl.Int64, "artist": pl.String, "track": pl.String, "listens": pl.Int64}
                         ).write_parquet(OUT / "month" / f"{ym}.parquet", compression="zstd")
        prog["months"][ym] = {"listens": n, "bad": bad, "names": len(counts)}
        prog["bytes_read"] = raw.offset
        prog_path.write_text(json.dumps(prog, indent=1))
        done += 1
        el = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] {ym}: {n:,} listens, {len(counts):,} names; read {raw.offset / 1e9:.1f} of 253 GB "
              f"({raw.offset / 252956952894:.0%}), {raw.offset / 1e6 / max(el, 1):.1f} MB/s", flush=True)
        if a.limit_months and done >= a.limit_months:
            return
    prog["md5"] = raw.md5.hexdigest(); prog["complete"] = True
    prog_path.write_text(json.dumps(prog, indent=1))
    print("done; md5", prog["md5"], flush=True)


if __name__ == "__main__":
    main()
