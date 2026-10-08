"""Stream MLHD+ archives from MetaBrainz and reduce them to compact tables.

The raw archives (~240 GB) never touch disk. Each archive is read over HTTP
as a byte stream, parsed as a tar on the fly, and every user's listening
history is reduced in memory to the tables below. Work is checkpointed every
CHUNK_BYTES of input, so an interrupted run resumes from the last checkpoint
with an HTTP Range request instead of starting the archive over. Dropped
connections mid-chunk are retried transparently from the exact byte offset.

Source format: one zstd TSV per user, lines of
    unix_ts <TAB> artist_mbid[,artist_mbid...] <TAB> release_mbid <TAB> recording_mbid

MBIDs are mapped to int64 ids: the last 15 hex digits of the UUID (60 random
bits for v4 UUIDs). id -> mbid maps are saved so collisions can be checked.

Users are split by a salted hash of their id into two halves, "explore" and
"sealed" (the holdout we don't analyse until methods are frozen), and a 1/8
hash bucket of users additionally keeps their full raw history.

Tables written per chunk under <out>/<table>/<half>/<archive>-<offset>.parquet:
    user_artist_week  user, artist, week, plays      (week = unix_ts // 604800)
    user_recording  user, recording, first_week, span_weeks, plays   (span = last - first listen week)
    users         user, mbid, raw_sample, n_listens, n_bad, first_ts, last_ts, n_recordings, n_artists
    raw           (raw_sample users only) user, ts, artists, release, recording
    artist_map, release_map, recording_map   id, mbid (release: raw_sample users only)
When an archive finishes, its chunk files are merged into one file per table
(user_recording sorted by recording, which compresses ~2x better).
"partial" archives hold the same users' listens that MLHD+ could not match to a
recording (mostly artist-only rows, some with no ids at all). Dropping them would
bias against obscure artists, so their artist-level listens are kept in the
*_partial tables:
    user_artist_week_partial  user, artist, week, plays
    users_partial  user, n_rows, n_artist, n_release_only, n_nothing, n_bad, first_ts, last_ts
    raw_partial    (raw_sample users only) user, ts, artists, release
Everything else (the per-artist "market", first listens, commitment) is derived
from user_artist_week afterwards, so no model is baked into what we store.
Multi-artist listens credit every listed artist in the artist-level tables.
"""

import argparse
import hashlib
import http.client
import io
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/listenbrainz/mlhd/"
ARCHIVES = [f"mlhdplus-{kind}-{c}.tar" for kind in ("partial", "complete") for c in "0123456789abcdef"]
CHUNK_BYTES = 64 * 2**20
# Pause (without marking done) once output reaches this size; the user's short-term cap is 100 GB.
SIZE_LIMIT = 75 * 10**9
SPLIT_SALT = "taste-mlhd-split-v1"
WEEK = 7 * 24 * 3600
# Last.fm launched scrobbling in 2002; MLHD+ was published March 2023.
MIN_TS, MAX_TS = 1009843200, 1679000000  # 2002-01-01 .. 2023-03-16

log = logging.getLogger("mlhd")


class RangeReader:
    """Sequential reader over an HTTP resource that survives dropped connections."""

    def __init__(self, url, pos=0):
        self.url, self.pos, self.size, self.resp = url, pos, None, None

    def _open(self):
        delay = 5
        while True:
            try:
                req = urllib.request.Request(
                    self.url, headers={"Range": f"bytes={self.pos}-", "User-Agent": "taste-research/0.1"}
                )
                resp = urllib.request.urlopen(req, timeout=120)
                if resp.status == 206:
                    self.size = int(resp.headers["Content-Range"].rsplit("/", 1)[1])
                elif resp.status == 200 and self.pos == 0:
                    self.size = int(resp.headers["Content-Length"])
                else:
                    raise OSError(f"unexpected HTTP status {resp.status}")
                self.resp = resp
                return
            except urllib.error.HTTPError as e:
                if e.code == 416:  # range starts at/after end of file
                    self.size = self.pos
                    self.resp = None
                    return
                log.warning("open %s @%d failed: %s; retry in %ds", self.url, self.pos, e, delay)
            except (OSError, http.client.HTTPException) as e:
                log.warning("open %s @%d failed: %s; retry in %ds", self.url, self.pos, e, delay)
            time.sleep(delay)
            delay = min(delay * 2, 300)

    def _close(self):
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:
                pass
        self.resp = None

    def read(self, n):
        """Read exactly n bytes, or fewer only at true end of file."""
        buf = bytearray()
        while len(buf) < n:
            if self.size is not None and self.pos >= self.size:
                break
            if self.resp is None:
                self._open()
                if self.resp is None:
                    break
            try:
                chunk = self.resp.read(min(n - len(buf), 4 * 2**20))
            except (OSError, http.client.HTTPException, socket.timeout) as e:
                log.warning("read %s @%d failed: %s; reconnecting", self.url, self.pos, e)
                self._close()
                time.sleep(5)
                continue
            if not chunk:
                self._close()  # server closed early; reconnect unless at EOF
                continue
            buf += chunk
            self.pos += len(chunk)
        return bytes(buf)


def tar_members(reader):
    """Yield (header_offset, name, data) for regular files in a ustar stream."""
    while True:
        offset = reader.pos
        hdr = reader.read(512)
        if len(hdr) < 512 or hdr == bytes(512):
            return
        stored = int(hdr[148:156].strip(b"\0 ") or b"0", 8)
        if stored != sum(hdr[:148]) + 256 + sum(hdr[156:]):
            raise ValueError(f"tar header checksum mismatch at offset {offset}")
        name = hdr[0:100].rstrip(b"\0").decode()
        prefix = hdr[345:500].rstrip(b"\0").decode()
        if prefix:
            name = f"{prefix}/{name}"
        size = int(hdr[124:136].strip(b"\0 ") or b"0", 8)
        data = reader.read(size)
        if len(data) < size:
            raise EOFError(f"truncated member {name} at offset {offset}")
        reader.read(-size % 512)
        if hdr[156:157] in (b"0", b"\0"):
            yield offset, name, data


def assign(user_mbid):
    h = hashlib.sha256(f"{SPLIT_SALT}:{user_mbid}".encode()).digest()
    return ("explore" if h[0] < 128 else "sealed"), h[1] < 32


def mbid_id(expr):
    import polars as pl

    return expr.str.replace_all("-", "", literal=True).str.slice(-15).str.to_integer(base=16, strict=False).cast(pl.Int64)


def parse_user(data, user_mbid):
    """Decompress and parse one user's file; returns (DataFrame of raw strings, n_bad_lines)."""
    import polars as pl
    import zstandard

    text = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    cols = ["ts", "artists", "release", "recording"]
    schema = {"ts": pl.Int64, "artists": pl.String, "release": pl.String, "recording": pl.String}
    try:
        df = pl.read_csv(text, separator="\t", has_header=False, new_columns=cols, schema_overrides=schema,
                         quote_char=None)
        n_bad = 0
    except Exception:
        rows, n_bad = [], 0
        for line in text.decode("utf-8", "replace").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0].isdigit():
                rows.append((int(parts[0]), *parts[1:]))
            else:
                n_bad += 1
        df = pl.DataFrame(rows, schema=schema, orient="row")
    return df, n_bad


def reduce_chunk(batch):
    """batch: list of (user_mbid, half, raw_sample, DataFrame, n_bad). Returns {table: {half: DataFrame}}."""
    import polars as pl

    frames, user_rows = [], []
    for user_mbid, half, raw_sample, df, n_bad in batch:
        frames.append(df.with_columns(user_mbid=pl.lit(user_mbid), half=pl.lit(half), raw_sample=pl.lit(raw_sample),
                                      n_bad_parse=pl.lit(n_bad)))
    lf = pl.concat(frames)
    lf = lf.with_columns(user=mbid_id(pl.col("user_mbid")))

    valid = (
        pl.col("ts").is_between(MIN_TS, MAX_TS)
        & pl.col("artists").is_not_null()
        & pl.col("recording").is_not_null()
    )
    L = lf.with_columns(
        artist_ids=pl.col("artists").str.split(",").list.eval(mbid_id(pl.element())),
        release_id=mbid_id(pl.col("release")),
        recording_id=mbid_id(pl.col("recording")),
    )
    valid = valid & pl.col("recording_id").is_not_null() & (pl.col("artist_ids").list.drop_nulls().list.len() == pl.col("artist_ids").list.len())
    L = L.with_columns(valid=valid)
    good = L.filter(pl.col("valid"))

    users = (
        L.group_by("user")
        .agg(
            mbid=pl.col("user_mbid").first(),
            half=pl.col("half").first(),
            raw_sample=pl.col("raw_sample").first(),
            n_listens=pl.col("valid").sum().cast(pl.Int64),
            n_bad=(pl.len() - pl.col("valid").sum() + pl.col("n_bad_parse").first()).cast(pl.Int64),
            first_ts=pl.col("ts").filter(pl.col("valid")).min(),
            last_ts=pl.col("ts").filter(pl.col("valid")).max(),
            n_recordings=pl.col("recording_id").filter(pl.col("valid")).n_unique(),
        )
    )

    E = good.select("user", "half", "ts", artist="artist_ids").explode("artist").with_columns(
        week=(pl.col("ts") // WEEK).cast(pl.Int32)
    )
    uaw = E.group_by("user", "half", "artist", "week").agg(plays=pl.len().cast(pl.Int32))
    users = users.join(uaw.group_by("user").agg(n_artists=pl.col("artist").n_unique().cast(pl.Int32)), on="user",
                       how="left")

    ur = (
        good.select("user", "half", recording="recording_id", week=(pl.col("ts") // WEEK).cast(pl.Int32))
        .group_by("user", "half", "recording")
        .agg(first_week=pl.col("week").min(), span_weeks=(pl.col("week").max() - pl.col("week").min()),
             plays=pl.len().cast(pl.Int32))
    )

    rs = good.filter(pl.col("raw_sample"))
    raw = rs.select("user", "half", ts=pl.col("ts").cast(pl.Int32), artists="artist_ids", release="release_id",
                    recording="recording_id")
    artist_map = good.select(mbid=pl.col("artists").str.split(","), id="artist_ids").explode("mbid", "id").unique()
    release_map = rs.select(id="release_id", mbid="release").drop_nulls().unique()
    recording_map = good.select(id="recording_id", mbid="recording").unique()

    out = {}
    for name, df, keys in [("user_artist_week", uaw, ["user", "artist", "week"]), ("user_recording", ur, ["user", "recording"]),
                           ("users", users, ["user"]),
                           ("raw", raw, ["user", "ts"])]:
        df = df.sort(keys)
        out[name] = {h: df.filter(pl.col("half") == h).drop("half") for h in ("explore", "sealed")}
    for name, df in [("artist_map", artist_map), ("release_map", release_map), ("recording_map", recording_map)]:
        out[name] = {"all": df}
    return out


def reduce_partial_chunk(batch):
    """Like reduce_chunk, for "partial" archives: artist and release ids may be missing."""
    import polars as pl

    L = pl.concat([
        df.with_columns(user_mbid=pl.lit(u), half=pl.lit(h), raw_sample=pl.lit(r), n_bad_parse=pl.lit(nb))
        for u, h, r, df, nb in batch
    ])
    L = L.with_columns(
        user=mbid_id(pl.col("user_mbid")),
        artist_ids=pl.col("artists").str.split(",").list.eval(mbid_id(pl.element())),
        release_id=mbid_id(pl.col("release")),
    )
    has_artist = pl.col("artist_ids").is_not_null() & (
        pl.col("artist_ids").list.drop_nulls().list.len() == pl.col("artist_ids").list.len())
    L = L.with_columns(valid=pl.col("ts").is_between(MIN_TS, MAX_TS), has_artist=has_artist)
    good = L.filter(pl.col("valid"))
    users = L.group_by("user").agg(
        half=pl.col("half").first(),
        n_rows=pl.col("valid").sum().cast(pl.Int64),
        n_artist=(pl.col("valid") & pl.col("has_artist")).sum().cast(pl.Int64),
        n_release_only=(pl.col("valid") & ~pl.col("has_artist") & pl.col("release_id").is_not_null()).sum()
        .cast(pl.Int64),
        n_nothing=(pl.col("valid") & ~pl.col("has_artist") & pl.col("release_id").is_null()).sum().cast(pl.Int64),
        n_bad=(pl.len() - pl.col("valid").sum() + pl.col("n_bad_parse").first()).cast(pl.Int64),
        first_ts=pl.col("ts").filter(pl.col("valid")).min(),
        last_ts=pl.col("ts").filter(pl.col("valid")).max(),
    )
    A = good.filter(pl.col("has_artist"))
    uaw = (
        A.select("user", "half", "ts", artist="artist_ids").explode("artist")
        .with_columns(week=(pl.col("ts") // WEEK).cast(pl.Int32))
        .group_by("user", "half", "artist", "week").agg(plays=pl.len().cast(pl.Int32))
    )
    rs = good.filter(pl.col("raw_sample"))
    raw = rs.select("user", "half", ts=pl.col("ts").cast(pl.Int32), artists="artist_ids", release="release_id")
    artist_map = A.select(mbid=pl.col("artists").str.split(","), id="artist_ids").explode("mbid", "id").unique()
    release_map = rs.select(id="release_id", mbid="release").drop_nulls().unique()

    out = {}
    for name, df, keys in [("user_artist_week_partial", uaw, ["user", "artist", "week"]),
                           ("users_partial", users, ["user"]), ("raw_partial", raw, ["user", "ts"])]:
        df = df.sort(keys)
        out[name] = {h: df.filter(pl.col("half") == h).drop("half") for h in ("explore", "sealed")}
    for name, df in [("artist_map", artist_map), ("release_map", release_map),
                     ("recording_map", pl.DataFrame(schema={"id": pl.Int64, "mbid": pl.String}))]:
        out[name] = {"all": df}
    return out


def write_chunk(out_dir, archive, offset, tables):
    import pyarrow.parquet as pq

    stem = f"{archive.removesuffix('.tar')}-{offset:012d}"
    for name, parts in tables.items():
        for half, df in parts.items():
            if df.height == 0:
                continue
            d = out_dir / name / half
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{stem}.parquet.tmp"
            enc = {"week": "DELTA_BINARY_PACKED"} if name.startswith("user_artist_week") else (
                {"ts": "DELTA_BINARY_PACKED"} if name.startswith("raw") else {})
            pq.write_table(df.to_arrow(), tmp, compression="zstd", compression_level=9, column_encoding=enc or None,
                           use_dictionary=[c for c in df.columns if c not in enc])
            os.replace(tmp, d / f"{stem}.parquet")


def dir_bytes(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except FileNotFoundError:  # another worker renamed/deleted it meanwhile
                pass
    return total


def state_path(out_dir, archive):
    return out_dir / "_state" / f"{archive}.json"


def load_state(out_dir, archive):
    p = state_path(out_dir, archive)
    return json.loads(p.read_text()) if p.exists() else {"pos": 0, "done": False, "users": 0, "listens": 0}


def save_state(out_dir, archive, state):
    p = state_path(out_dir, archive)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, p)


def process_archive(archive, out_dir, max_bytes=None, chunk_bytes=CHUNK_BYTES):
    setup_logging(out_dir)
    state = load_state(out_dir, archive)
    if state["done"]:
        return archive, state
    reader = RangeReader(BASE_URL + archive, state["pos"])
    log.info("%s: starting at byte %d", archive, state["pos"])
    import polars as pl

    batch, chunk_start, t0 = [], state["pos"], time.time()
    seen = {"artist_map": set(), "release_map": set(), "recording_map": set()}

    def flush(next_pos):
        nonlocal batch, chunk_start, t0
        if batch:
            tables = (reduce_partial_chunk if "-partial-" in archive else reduce_chunk)(batch)
            for name, ids in seen.items():  # id maps: only write ids this worker hasn't written yet
                df = tables[name]["all"]
                df = df.filter(~pl.col("id").is_in(list(ids))) if ids else df
                ids.update(df["id"].to_list())
                tables[name]["all"] = df
            write_chunk(out_dir, archive, chunk_start, tables)
            ut, col = ("users_partial", "n_rows") if "-partial-" in archive else ("users", "n_listens")
            n_listens = int(tables[ut]["explore"][col].sum() + tables[ut]["sealed"][col].sum())
            state["users"] += len(batch)
            state["listens"] += n_listens
        state["pos"], state["size"] = next_pos, reader.size
        save_state(out_dir, archive, state)
        dt = time.time() - t0
        log.info("%s: checkpoint @%d/%s (%.1f%%), %d users, %.1f MB/s", archive, next_pos, reader.size,
                 100 * next_pos / (reader.size or 1), state["users"], (next_pos - chunk_start) / 2**20 / max(dt, 1e-9))
        batch, chunk_start, t0 = [], next_pos, time.time()

    for offset, name, data in tar_members(reader):
        if not name.endswith(".txt.zst"):
            continue
        if batch and offset - chunk_start >= chunk_bytes:
            flush(offset)
            if dir_bytes(out_dir) >= SIZE_LIMIT:
                log.error("%s: output reached size limit (%d bytes); pausing", archive, SIZE_LIMIT)
                return archive, state
            if max_bytes is not None and offset >= max_bytes:
                log.info("%s: stopping at max_bytes", archive)
                return archive, state
        user_mbid = name.rsplit("/", 1)[-1].removesuffix(".txt.zst")
        half, raw_sample = assign(user_mbid)
        df, n_bad = parse_user(data, user_mbid)
        batch.append((user_mbid, half, raw_sample, df, n_bad))
    flush(reader.pos)
    state["done"] = True
    save_state(out_dir, archive, state)
    log.info("%s: done, %d users, %d listens", archive, state["users"], state["listens"])
    compact_archive(out_dir, archive)
    return archive, state


COMPACT_ORDER = {
    "user_recording": "recording, user",
    "user_artist_week": "user, artist, week",
    "raw": "user, ts",
    "users": "user",
    "user_artist_week_partial": "user, artist, week",
    "raw_partial": "user, ts",
    "users_partial": "user",
    "artist_map": None,  # None = SELECT DISTINCT
    "release_map": None,
    "recording_map": None,
}


def compact(out_dir, pattern_by_half, stem, keep_sources=False):
    """Merge parquet files into <table>/<half>/<stem>.parquet. Resume-safe: the merged file appears atomically,
    and if it already exists, leftover sources are already included in it and are just deleted."""
    import duckdb

    import shutil

    # Per-process spill dir: DuckDB names its temp files deterministically, so concurrent
    # compactions sharing one directory overwrite each other's spill data.
    tmpdir = out_dir / "_tmp" / str(os.getpid())
    shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmpdir}'; "
                "SET preserve_insertion_order=false")
    for table, order in COMPACT_ORDER.items():
        for half_dir in sorted((out_dir / table).glob("*")):
            sources = [f for f in sorted(half_dir.glob("*.parquet")) if pattern_by_half(f)]
            dest = half_dir / f"{stem}.parquet"
            sources = [f for f in sources if f != dest]
            if not sources:
                continue
            if not dest.exists():
                files = ", ".join(f"'{f}'" for f in sources)
                select = f"SELECT * FROM read_parquet([{files}])"
                query = f"SELECT DISTINCT * FROM ({select})" if order is None else f"{select} ORDER BY {order}"
                tmp = half_dir / f".{stem}.parquet.tmp"
                con.execute(f"COPY ({query}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, "
                            "ROW_GROUP_SIZE 1000000)")
                os.replace(tmp, dest)
            if not keep_sources:
                for f in sources:
                    f.unlink()
    con.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


def compact_archive(out_dir, archive):
    stem = archive.removesuffix(".tar")
    compact(out_dir, lambda f: f.name.startswith(stem + "-"), stem)
    log.info("%s: compacted", archive)


def setup_logging(out_dir):
    if log.handlers:
        return
    (out_dir / "_logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(process)d %(levelname)s %(message)s")
    for h in (logging.FileHandler(out_dir / "_logs" / "ingest.log"), logging.StreamHandler(sys.stderr)):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "mlhd")
    ap.add_argument("--archives", nargs="*", default=ARCHIVES)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-bytes", type=int, help="pilot mode: stop each archive after this many bytes")
    ap.add_argument("--chunk-mb", type=int, default=CHUNK_BYTES // 2**20)
    args = ap.parse_args()
    setup_logging(args.out)
    todo = [a for a in args.archives if not load_state(args.out, a)["done"]]
    log.info("archives to process: %d (workers=%d)", len(todo), args.workers)
    os.environ.setdefault("POLARS_MAX_THREADS", str(max(1, (os.cpu_count() or 4) // args.workers)))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        submit = lambda a: pool.submit(process_archive, a, args.out, args.max_bytes, args.chunk_mb * 2**20)
        futures = {submit(a): a for a in todo}
        while futures:
            f = next(as_completed(futures))
            archive = futures.pop(f)
            try:
                _, state = f.result()
                log.info("finished %s: %s", archive, state)
            except Exception:
                # Resumes from the archive's last checkpoint. Process death (crash, reboot) is handled by launchd.
                log.exception("%s failed; retrying in 60s", archive)
                time.sleep(60)
                futures[submit(archive)] = archive
    if args.max_bytes is None and all(load_state(args.out, a)["done"] for a in args.archives):
        for a in args.archives:  # no-op unless a crash interrupted an archive's compaction
            compact_archive(args.out, a)
        maps = {"artist_map", "release_map", "recording_map"}
        for table in maps:  # dedupe id maps across archives
            for half_dir in (args.out / table).glob("*"):
                compact(args.out, lambda f: f.parent == half_dir and f.stem != table, table)
        (args.out / "_state" / "ALL_DONE").touch()
        log.info("all archives complete")


if __name__ == "__main__":
    main()
