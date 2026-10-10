"""Decode every shard of the packed site data with the Python mirror's decoder and check record ids are in range."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_pack as SP  # noqa: E402

pk = SP.Pack(); bad = 0; na = ns = 0
for s in range(pk.S):
    try:
        an, ar, sn, sr = pk.shard(s)
        assert all(0 <= a["id"] < 5_000_000 for a in ar) and all(0 <= x["id"] < 17_000_000 for x in sr)
        assert all(i < len(ar) for i in an.values()) and all(i < len(sr) for i in sn.values())
        na += len(ar); ns += len(sr)
    except Exception as e:
        bad += 1
        if bad <= 3:
            print("bad shard", s, type(e).__name__)
    if s % 65536 == 65535:
        pk.cache.clear()
print(f"checked {pk.S:,} shards: {bad} bad; {na:,} artist records, {ns:,} song records")
