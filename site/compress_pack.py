"""Compress each shard of the packed site data (raw deflate), rewriting data/p/*.bin and data/index.bin (magic 'TST2' = compressed
shards). The browser inflates each shard with DecompressionStream('deflate-raw'); site/score_pack.py with zlib."""
import shutil
import struct
import zlib
from pathlib import Path

import os
D = Path(os.environ.get("SITE_OUT", Path(__file__).resolve().parent / "static" / "data"))   # SITE_REF / SITE_OUT / LB_SONGS override the folders (the 2026-10-14 rebuild writes data/site_v2 and site/static/data_v2)
FILE_MAX = 45_000_000
b = (D / "index.bin").read_bytes()
magic, S, F = struct.unpack_from("<IIH", b, 0); p = 10
assert magic == 0x54535431, "already compressed?"
sizes = struct.unpack_from(f"<{F}I", b, p); p += 4 * F
lens = struct.unpack_from(f"<{S}I", b, p)
out = D / "p_new"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
f, off, data = 0, 0, (D / "p" / "00.bin").read_bytes()
new_lens, files, cur, fileno = [], [], bytearray(), 0
for s, ln in enumerate(lens):
    if ln and off + ln > sizes[f]:
        f += 1; off = 0; data = (D / "p" / f"{f:02d}.bin").read_bytes()
    if not ln:
        new_lens.append(0); continue
    c = zlib.compressobj(9, zlib.DEFLATED, -15); z = c.compress(data[off:off + ln]) + c.flush(); off += ln
    if len(cur) + len(z) > FILE_MAX and cur:
        (out / f"{fileno:02d}.bin").write_bytes(bytes(cur)); files.append(len(cur)); fileno += 1; cur = bytearray()
    cur += z; new_lens.append(len(z))
if cur:
    (out / f"{fileno:02d}.bin").write_bytes(bytes(cur)); files.append(len(cur))
idx = bytearray(struct.pack("<IIH", 0x54535432, S, len(files))) + b"".join(struct.pack("<I", x) for x in files) + b"".join(struct.pack("<I", x) for x in new_lens)
shutil.rmtree(D / "p"); out.rename(D / "p"); (D / "index.bin").write_bytes(bytes(idx))
print(f"{len(files)} files, {sum(files) / 1e6:.0f} MB (was {sum(sizes) / 1e6:.0f} MB)")
