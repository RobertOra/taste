"""Step 3 (then run site/compress_pack.py): pack the item data for the static site (GitHub Pages; the browser reads byte ranges).

    site/static/data/index.bin   u32 magic, u32 shard count S, u16 file count F, then F x u32 file sizes, then S x u32 shard
                                 lengths (shards are stored in order, back to back, files split between shards)
    site/static/data/p/NN.bin    concatenated shards (each file <= ~45 MB)
Shard s holds every artist name and song name whose hash's low SHARD_BITS bits equal s:
    u16 nAN, u16 nAR, u16 nSN, u16 nSR
    nAN x (i64 name hash, u16 artist record index)        artist names (lowercased, trimmed)
    nAR x artist record: u32 id, u16 country index, u16 first month + 1000 - 24000, u8 genre family, u8 has-any-release,
                         varint nScene, nScene x (u8 year - 2000, u8 scene or 255),
                         varint nRel, nRel x varint (release month - previous; first from M0 - 12),
                         varint nRows, rows
    nSN x (i64 name hash, u16 song record index)          song names ("artist\\ttrack", lowercased, trimmed)
    nSR x song record:   u32 id, u16 first month + 1000 - 24000, varint nRows, rows
    rows: monthly (a new listeners, t of them past their own first 26 weeks, k of those kept), months from M0 = 2015-01;
          each row varint((month - previous month) << 2 | code), previous starting at M0 - 1; code 0: a=1,t=0,k=0;
          1: a=1,t=1,k=0; 2: a=1,t=1,k=1; 3: general, followed by varint a, varint t, varint k
"""
import shutil
import struct
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from numba import njit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

REF, X, OUT = ROOT / "data" / "site", ROOT / "data" / "derived", ROOT / "site" / "static" / "data"
M0 = 2015 * 12
SHARD_BITS = 18
S = 1 << SHARD_BITS
FILE_MAX = 45_000_000
FAMS = [n for n, _ in FAMILIES] + ["Other"]
con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")


@njit(cache=True)
def put_varint(buf, pos, v):
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            buf[pos] = b | 0x80; pos += 1
        else:
            buf[pos] = b; pos += 1
            return pos


@njit(cache=True)
def encode_rows(starts, ends, month, a, t, k, m0, out, offs):
    """For each record r (rows starts[r]:ends[r]), write varint(n rows) + rows into out at offs[r]; returns lengths."""
    lens = np.zeros(len(starts), np.int64)
    for r in range(len(starts)):
        p = offs[r]; p0 = p
        p = put_varint(out, p, ends[r] - starts[r])
        prev = m0 - 1
        for i in range(starts[r], ends[r]):
            d = month[i] - prev; prev = month[i]
            if a[i] == 1 and t[i] == 0 and k[i] == 0:
                code = 0
            elif a[i] == 1 and t[i] == 1 and k[i] == 0:
                code = 1
            elif a[i] == 1 and t[i] == 1 and k[i] == 1:
                code = 2
            else:
                code = 3
            p = put_varint(out, p, (d << 2) | code)
            if code == 3:
                p = put_varint(out, p, a[i]); p = put_varint(out, p, t[i]); p = put_varint(out, p, k[i])
        lens[r] = p - p0
        if r + 1 < len(offs) and p > offs[r + 1]:
            lens[r] = -1   # overflowed its reserved space
    return lens


def encoded(rows, key, ids):
    """rows: polars (key, month, a, t, k) sorted by key, month; ids: sorted array of keys to encode. -> dict key -> bytes."""
    keys = rows[key].to_numpy()
    uk, starts = np.unique(keys, return_index=True)
    ends = np.append(starts[1:], len(keys))
    per = (ends - starts) * 16 + 10   # a row needs at most 2 + 3 x 4 bytes; varint(row count) at most 5
    cap = int(per.sum() + 16)
    out = np.zeros(cap, np.uint8)
    offs = np.concatenate([[0], np.cumsum(per)[:-1]]).astype(np.int64)
    lens = encode_rows(starts.astype(np.int64), ends.astype(np.int64), rows["month"].to_numpy().astype(np.int64),
                       rows["a"].to_numpy().astype(np.int64), rows["t"].to_numpy().astype(np.int64), rows["k"].to_numpy().astype(np.int64), M0, out, offs)
    assert (lens >= 0).all(), "a record overflowed its reserved space"
    return {int(kk): out[o:o + l].tobytes() for kk, o, l in zip(uk, offs, lens)}


def vb(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b); return bytes(out)


# ---- artists: everything in memory (37.7M rows)
arows = pl.read_parquet(REF / "pack_artist_rows.parquet").sort("artist", "month")
aids = np.unique(arows["artist"].to_numpy())
agid = {int(a): i for i, a in enumerate(aids)}
info = pl.read_parquet(REF / "artist_info.parquet").filter(pl.col("artist").is_in(aids))
countries = sorted(set(pl.read_parquet(REF / "artist_info.parquet", columns=["country"])["country"].to_list()) | {"?"})
cidx = {c: i for i, c in enumerate(countries)}
fam = (pl.read_parquet(X / "scenes_genre" / "lb.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr())
       .with_columns(fam_i=pl.col("fam").replace_strict({f: i for i, f in enumerate(FAMS)}, return_dtype=pl.Int8)))
FAM = dict(zip(fam["artist"].to_list(), fam["fam_i"].to_list()))
SC = {r[0]: list(zip(r[1], r[2])) for r in pl.read_parquet(REF / "artist_scene.parquet").filter((pl.col("year") >= 2015) & pl.col("artist").is_in(aids))
      .sort("artist", "year").group_by("artist", maintain_order=True).agg("year", "scene").iter_rows()}
relall = pl.read_parquet(REF / "artist_release.parquet")
anyrel = set(relall["artist"].unique().to_list())
RL = {r[0]: r[1] for r in relall.filter((pl.col("rm") >= M0 - 12) & pl.col("artist").is_in(aids)).sort("artist", "rm").group_by("artist", maintain_order=True).agg("rm").iter_rows()}
AROW = encoded(arows.rename({"artist": "key"}), "key", aids)
del arows
arec = {}
for a, c, fm in info.iter_rows():
    b = bytearray(struct.pack("<IHHBB", agid[a], cidx.get(c, cidx["?"]), fm - 24000 + 1000, FAM.get(a, len(FAMS) - 1), 1 if a in anyrel else 0))
    sc = SC.get(a, [])
    b += vb(len(sc))
    for y, s_ in sc:
        b += bytes([y - 2000, s_ if s_ >= 0 else 255])
    rl = RL.get(a, [])
    b += vb(len(rl)); prev = M0 - 12
    for rm in rl:
        b += vb(rm - prev); prev = rm
    b += AROW[a]
    arec[a] = bytes(b)
del AROW, SC, RL
anames = con.execute(f"SELECT artist_name_h AS h, artist FROM read_parquet('{REF}/artist_map.parquet') WHERE artist IN (SELECT DISTINCT artist FROM read_parquet('{REF}/pack_artist_rows.parquet'))").pl()
anames = anames.with_columns(shard=(pl.col("h") & (S - 1)).cast(pl.Int64))
print(f"artists: {len(arec):,} records, {anames.height:,} names; {sum(map(len, arec.values())) / 1e6:.0f} MB", flush=True)

# ---- songs: names first, then rows in chunks of shards
snames = con.execute(f"""SELECT m.rec_name_h AS h, m.rec FROM read_parquet('{REF}/rec_map.parquet') m
                         SEMI JOIN read_parquet('{REF}/pack_song_first.parquet') f ON f.rec = m.rec""").pl()
snames = snames.with_columns(shard=(pl.col("h") & (S - 1)).cast(pl.Int64))
sf = pl.read_parquet(REF / "pack_song_first.parquet").sort("rec")
sids, sfm = sf["rec"].to_numpy(), sf["first_month"].to_numpy().astype(np.int64)   # global song id = position in sids
del sf
print(f"songs: {len(sids):,} records, {snames.height:,} names", flush=True)

sd = OUT / "p"
if sd.exists():
    shutil.rmtree(sd)
sd.mkdir(parents=True)
lengths = np.zeros(S, np.int64); files = []; cur = bytearray(); fileno = 0
CH = 64
A_by = {k[0]: g for k, g in anames.partition_by("shard", as_dict=True).items()}
for c in range(CH):
    lo, hi = c * (S // CH), (c + 1) * (S // CH)
    sn = snames.filter(pl.col("shard").is_between(lo, hi - 1))
    need = np.unique(sn["rec"].to_numpy())
    con.register("need", pl.DataFrame({"rec": need}).to_arrow())
    rows = con.execute(f"SELECT r.rec AS key, r.month, r.a, r.t, r.k FROM read_parquet('{REF}/pack_song_rows.parquet') r SEMI JOIN need ON need.rec = r.rec ORDER BY r.rec, r.month").pl()
    SROW = encoded(rows, "key", need)
    del rows
    S_by = {k[0]: g for k, g in sn.partition_by("shard", as_dict=True).items()}
    for s in range(lo, hi):
        ga, gs = A_by.get(s), S_by.get(s)
        alist = list(dict.fromkeys(ga["artist"].to_list())) if ga is not None else []
        slist = list(dict.fromkeys(gs["rec"].to_list())) if gs is not None else []
        ai = {a: i for i, a in enumerate(alist)}; si = {r: i for i, r in enumerate(slist)}
        b = bytearray(struct.pack("<HHHH", 0 if ga is None else ga.height, len(alist), 0 if gs is None else gs.height, len(slist)))
        if ga is not None:
            for h, a in zip(ga["h"].to_list(), ga["artist"].to_list()):
                b += struct.pack("<qH", h, ai[a])
        for a in alist:
            b += arec[a]
        if gs is not None:
            for h, r in zip(gs["h"].to_list(), gs["rec"].to_list()):
                b += struct.pack("<qH", h, si[r])
        if slist:
            pos = np.searchsorted(sids, np.array(slist))
            for r, g_ in zip(slist, pos):
                b += struct.pack("<IH", int(g_), int(sfm[g_]) - 24000 + 1000) + SROW[r]
        if len(cur) + len(b) > FILE_MAX and cur:
            (sd / f"{fileno:02d}.bin").write_bytes(bytes(cur)); files.append(len(cur)); fileno += 1; cur = bytearray()
        cur += b; lengths[s] = len(b)
    del SROW
    print(f"chunk {c + 1}/{CH} done; files so far {fileno}, current {len(cur) / 1e6:.0f} MB", flush=True)
if cur:
    (sd / f"{fileno:02d}.bin").write_bytes(bytes(cur)); files.append(len(cur))
idx = bytearray(struct.pack("<IIH", 0x54535431, S, len(files))) + b"".join(struct.pack("<I", f) for f in files) + b"".join(struct.pack("<I", int(x)) for x in lengths)
(OUT / "index.bin").write_bytes(bytes(idx))
print(f"done: {len(files)} files, {sum(files) / 1e6:.0f} MB; largest shard {lengths.max() / 1e3:.1f} kB, mean {lengths.mean() / 1e3:.2f} kB; index {len(idx) / 1e3:.0f} kB", flush=True)
