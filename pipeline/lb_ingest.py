"""Stream the ListenBrainz full listens dump into compact weekly tables (the raw dump is never stored).

Source: https://ftp.musicbrainz.org/pub/musicbrainz/listenbrainz/fullexport/<dump>/listenbrainz-listens-dump-*.tar.zst
(236 GB compressed for dump 2692). The bytes are read over HTTP (reconnecting with a Range request from the current
offset if the connection drops), MD5-checked against the published .md5 as they stream, zstd-decompressed, and read as a
tar stream of monthly JSON-lines files (listens/YYYY/M.listens).

Per listen we keep: user_id, week (unix_ts // 604800), artist key, recording key. Keys:
    artist_mbid_id  last 15 hex digits of the first submitted artist MBID as int64 (same scheme as MLHD+), or null
    artist_name_h   64-bit hash of the lowercased, trimmed artist name (always present)
    rec_mbid_id     same scheme for the recording MBID, or null
    rec_name_h      64-bit hash of "artist name\\ttrack name" (lowercased), always present
Weekly tables use the name keys only (consistent whether or not a listen carried MBIDs); MBIDs go to small lookup tables.
Outputs (data/lb/):
    user_artist_week/YYYY-MM.parquet   user, week, artist_name_h, plays
    user_rec_week/YYYY-MM.parquet      user, week, rec_name_h, artist_name_h, plays
    artist_names.parquet               artist_name_h, name (one example spelling)
    name_mbid/YYYY-MM.parquet          artist_name_h, artist_mbid_id, listens (to resolve names to MBIDs later)
    rec_mbid/YYYY-MM.parquet           rec_name_h, rec_mbid_id, listens
Disk guard: before each month, stops cleanly (progress kept, exit code 3) if free space < 25 GB or the project
(baseline measured at start + data/lb) would exceed 148 GB.
    progress.json                      months done, listens per month, bytes read, MD5 status
Months already present in progress.json are skipped (their bytes are still read: a tar stream can't seek).

Usage: lb_ingest.py [--url URL] [--file PATH] [--limit-months N]
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import duckdb
import orjson
import polars as pl
import zstandard

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("LB_OUT", ROOT / "data" / "lb"))
DUMP = "listenbrainz-dump-2692-20261001-000003-full"
BASE = f"https://ftp.musicbrainz.org/pub/musicbrainz/listenbrainz/fullexport/{DUMP}/"
FILE = "listenbrainz-listens-dump-2692-20261001-000003-full.tar.zst"
CHUNK = 4_000_000  # listens per in-memory chunk before spilling a partial aggregate


class ResumingHTTP(io.RawIOBase):
    """Read-only file object over HTTP that reconnects with a Range request after errors and hashes what it reads."""

    def __init__(self, url, retries=200):
        self.url, self.offset, self.retries, self.md5, self.resp = url, 0, retries, hashlib.md5(), None
        self._open()

    def _open(self):
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.offset}-"} if self.offset else {})
        self.resp = urllib.request.urlopen(req, timeout=120)

    def readable(self):
        return True

    def readinto(self, b):
        for attempt in range(self.retries):
            try:
                n = self.resp.readinto(b)
                if n:
                    self.md5.update(memoryview(b)[:n])
                    self.offset += n
                return n
            except Exception as ex:  # network hiccup: reconnect from the current offset
                print(f"[{time.strftime('%H:%M:%S')}] read error at {self.offset:,}: {ex!r}; reconnecting ({attempt + 1})", flush=True)
                time.sleep(min(60, 2 ** min(attempt, 6)))
                try:
                    self._open()
                except Exception as ex2:
                    print(f"    reconnect failed: {ex2!r}", flush=True)
        raise IOError("too many read errors")


def name_hash(s, cache={}):
    h = cache.get(s)
    if h is None:
        h = int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big", signed=True)
        if len(cache) < 5_000_000:
            cache[s] = h
    return h


def mbid_id(m):
    if not m or not isinstance(m, str):
        return None
    try:
        return int(m.replace("-", "")[-15:], 16)
    except ValueError:
        return None


def flush(rows, tmp, k):
    df = pl.DataFrame(rows, schema={"user": pl.Int32, "week": pl.Int32, "a_m": pl.Int64, "a_n": pl.Int64, "r_m": pl.Int64, "r_n": pl.Int64},
                      orient="row")
    df.group_by("user", "week", "a_m", "a_n", "r_m", "r_n").agg(plays=pl.len().cast(pl.Int32)).write_parquet(tmp / f"part-{k:05d}.parquet")


def finish_month(tmp, ym, con):
    parts = f"{tmp}/part-*.parquet"
    (OUT / "user_artist_week").mkdir(parents=True, exist_ok=True)
    (OUT / "user_rec_week").mkdir(parents=True, exist_ok=True)
    (OUT / "name_mbid").mkdir(parents=True, exist_ok=True)
    (OUT / "rec_mbid").mkdir(parents=True, exist_ok=True)
    con.execute(f"""COPY (SELECT user, week, a_n AS artist_name_h, sum(plays)::INT AS plays
                         FROM read_parquet('{parts}') GROUP BY ALL ORDER BY user, week, artist_name_h)
                   TO '{OUT}/user_artist_week/{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT user, week, r_n AS rec_name_h, a_n AS artist_name_h, sum(plays)::INT AS plays
                         FROM read_parquet('{parts}') GROUP BY ALL ORDER BY user, artist_name_h, rec_name_h, week)
                   TO '{OUT}/user_rec_week/{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT r_n AS rec_name_h, r_m AS rec_mbid_id, sum(plays)::BIGINT AS listens
                         FROM read_parquet('{parts}') WHERE r_m IS NOT NULL GROUP BY ALL)
                   TO '{OUT}/rec_mbid/{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT a_n AS artist_name_h, a_m AS artist_mbid_id, sum(plays)::BIGINT AS listens
                         FROM read_parquet('{parts}') WHERE a_m IS NOT NULL GROUP BY ALL)
                   TO '{OUT}/name_mbid/{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    shutil.rmtree(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=BASE + FILE)
    ap.add_argument("--file", default=None, help="read a local .tar.zst (for testing) instead of HTTP")
    ap.add_argument("--limit-months", type=int, default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    prog_path = OUT / "progress.json"
    prog = json.loads(prog_path.read_text()) if prog_path.exists() else {"months": {}}
    raw = open(a.file, "rb") if a.file else ResumingHTTP(a.url)
    stream = zstandard.ZstdDecompressor(max_window_size=2 ** 31).stream_reader(io.BufferedReader(raw, 8 << 20) if a.file is None else raw)
    con = duckdb.connect()
    tmp_root = ROOT / "data" / "_tmp" / "lb"
    con.execute(f"SET memory_limit='4GB'; SET threads=4; SET temp_directory='{tmp_root}/duck'; SET preserve_insertion_order=false")
    names = {}
    names_path = OUT / "artist_names.parquet"
    if names_path.exists():
        names = dict(zip(*pl.read_parquet(names_path).select("artist_name_h", "name").to_dict(as_series=False).values()))
    t0, done_months = time.time(), 0
    def dir_bytes(p):
        return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) if Path(p).exists() else 0
    baseline = dir_bytes(ROOT / "data") - dir_bytes(OUT) + dir_bytes(ROOT / "analysis" / "out")
    print(f"project baseline (excluding data/lb): {baseline / 1e9:.1f} GB", flush=True)
    tf = tarfile.open(fileobj=stream, mode="r|")
    for member in tf:
        if not member.isfile() or "/listens/" not in member.name or not member.name.endswith(".listens"):
            continue
        y, mth = member.name.rsplit("/", 2)[-2], member.name.rsplit("/", 1)[-1].split(".")[0]
        ym = f"{int(y):04d}-{int(mth):02d}"
        if ym in prog["months"]:
            continue  # tar stream: the member's bytes are skipped by reading past them
        free = shutil.disk_usage(ROOT).free
        lb_now = dir_bytes(OUT)
        if free < 25e9 or baseline + lb_now > 148e9:
            prog["paused"] = {"at": ym, "free_gb": round(free / 1e9, 1), "project_gb": round((baseline + lb_now) / 1e9, 1)}
            prog_path.write_text(json.dumps(prog, indent=1))
            print(f"DISK GUARD: stopping before {ym} (free {free / 1e9:.1f} GB, project {(baseline + lb_now) / 1e9:.1f} GB)", flush=True)
            sys.exit(3)
        f = tf.extractfile(member)
        tmp = tmp_root / ym
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        rows, k, n, bad = [], 0, 0, 0
        for line in f:
            try:
                d = orjson.loads(line)
                tm = d["track_metadata"]
                info = tm.get("additional_info") or {}
                mm = tm.get("mbid_mapping") or {}
                an = (tm.get("artist_name") or "").strip().lower()
                tn = (tm.get("track_name") or "").strip().lower()
                am = mm.get("artist_mbids") or info.get("artist_mbids") or []
                a_m = mbid_id(am[0]) if am else None
                r_m = mbid_id(mm.get("recording_mbid") or info.get("recording_mbid"))
                a_n = name_hash(an)
                if a_n not in names and len(names) < 20_000_000:
                    names[a_n] = tm.get("artist_name") or ""
                rows.append((d["user_id"], int(d.get("listened_at") or d.get("timestamp")) // 604800, a_m, a_n, r_m, name_hash(an + "\t" + tn)))
                n += 1
            except Exception:
                bad += 1
                continue
            if len(rows) >= CHUNK:
                flush(rows, tmp, k); rows, k = [], k + 1
        if rows:
            flush(rows, tmp, k)
        if n:
            finish_month(tmp, ym, con)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
        prog["months"][ym] = {"listens": n, "bad": bad, "member_bytes": member.size}
        prog["bytes_read"] = getattr(raw, "offset", None)
        prog_path.write_text(json.dumps(prog, indent=1))
        if len(names) and (done_months % 6 == 0):
            pl.DataFrame({"artist_name_h": list(names.keys()), "name": list(names.values())}, schema={"artist_name_h": pl.Int64, "name": pl.String}).write_parquet(names_path)
        done_months += 1
        el = time.time() - t0
        off = getattr(raw, "offset", 0) or 0
        print(f"[{time.strftime('%H:%M:%S')}] {ym}: {n:,} listens ({bad} bad); {off / 1e9:.1f} GB read, "
              f"{off / max(el, 1) / 1e6:.1f} MB/s", flush=True)
        if a.limit_months and done_months >= a.limit_months:
            break
    pl.DataFrame({"artist_name_h": list(names.keys()), "name": list(names.values())}, schema={"artist_name_h": pl.Int64, "name": pl.String}).write_parquet(names_path)
    if a.file is None and a.limit_months is None:
        while raw.read(1 << 20):  # drain any trailing bytes so the MD5 covers the whole file
            pass
        expected = urllib.request.urlopen(BASE + FILE + ".md5", timeout=60).read().decode().split()[0]
        prog["md5"] = {"expected": expected, "got": raw.md5.hexdigest(), "ok": expected == raw.md5.hexdigest()}
        prog["bytes_read"] = raw.offset
        prog_path.write_text(json.dumps(prog, indent=1))
        print("MD5", prog["md5"], flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
