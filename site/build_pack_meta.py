"""Final step: site/static/data/meta.json = data/site/pack_meta.json + typical genre mix of reference finds (by unit)."""
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
REF, OUT = ROOT / "data" / "site", ROOT / "site" / "static" / "data"
meta = json.loads((REF / "pack_meta.json").read_text())
meta["family_share"] = {}
for unit in ("artist", "song"):
    f = pl.read_parquet(REF / f"_pack_picks_{unit}.parquet", columns=["fam"])
    c = f.group_by("fam").agg(n=pl.len())
    tot = c["n"].sum()
    meta["family_share"][unit] = [float(c.filter(pl.col("fam") == i)["n"].sum() / tot) for i in range(len(meta["families"]))]
(OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
print("meta.json", (OUT / "meta.json").stat().st_size // 1000, "kB;", {u: [round(x, 3) for x in v] for u, v in meta["family_share"].items()})
