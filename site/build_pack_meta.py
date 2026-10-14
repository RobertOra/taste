"""Final step: site/static/data/meta.json = data/site/pack_meta.json + typical genre mix of reference finds (by unit)."""
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
# SITE_REF / SITE_OUT / LB_SONGS override the folders (the 2026-10-14 rebuild writes data/site_v2 and site/static/data_v2)
import os
REF, OUT = Path(os.environ.get("SITE_REF", ROOT / "data" / "site")), Path(os.environ.get("SITE_OUT", ROOT / "site" / "static" / "data"))
meta = json.loads((REF / "pack_meta.json").read_text())
# prescience among settled listeners (rebuild item 2): SETTLED=1 ships it as the site's prescience (song_A / artist_A);
# otherwise the all-listener version stays. Either way the other variant isn't shipped.
for unit in ("song", "artist"):
    if f"{unit}_As" in meta["measures"]:
        alt = meta["measures"].pop(f"{unit}_As")
        if os.environ.get("SETTLED") == "1":
            meta["measures"][f"{unit}_A"] = alt
meta["family_share"] = {}
for unit in ("artist", "song"):
    f = pl.read_parquet(REF / f"_pack_picks_{unit}.parquet", columns=["fam"])
    c = f.group_by("fam").agg(n=pl.len())
    tot = c["n"].sum()
    meta["family_share"][unit] = [float(c.filter(pl.col("fam") == i)["n"].sum() / tot) for i in range(len(meta["families"]))]
(OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
print("meta.json", (OUT / "meta.json").stat().st_size // 1000, "kB;", {u: [round(x, 3) for x in v] for u, v in meta["family_share"].items()})
