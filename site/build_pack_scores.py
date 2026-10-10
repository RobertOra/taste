"""Step 2b: reference scores from every reference find's result (data/site/_pack_ex_*.parquet, from build_pack_ref.py).
Score = sum of excess / (finds + 20) over all of a person's judged finds (2016 to a year before the data ends); people with
>= MIN_PICKS form the reference. Per year: the same over that year's finds, for person-years with >= MIN_YEAR finds
(1,001 quantiles). Reliability: split-half (alternate finds in time order), Spearman-Brown to a single find. Typical: the
median reference person's average excess, overall and per year. Agreement: with the study's frozen scores over the same years.
Updates data/site/pack_meta.json."""
import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "site"
meta = json.loads((REF / "pack_meta.json").read_text())
SHRINK, MIN_PICKS, MIN_YEAR = meta["shrink"], meta["min_picks"], 20
meta["window_years"] = 0          # 0 = all judged finds
meta["min_year"] = MIN_YEAR
frozen = {"artist_A": "lb_A_artist_main", "artist_D": "lb_D_artist_main", "song_A": "lb_A_song_main", "song_D": "lb_D_song_main"}
for key, M in meta["measures"].items():
    dd = pl.read_parquet(REF / f"_pack_ex_{key}.parquet").with_columns(year=pl.col("m") // 12)
    per = dd.group_by("user").agg(s=pl.col("excess").sum() / (pl.len() + SHRINK), n=pl.len(), avg=pl.col("excess").mean())
    refp = per.filter(pl.col("n") >= MIN_PICKS)
    h = (dd.sort("user", "m", "item").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
         .group_by("user", "half").agg(s=pl.col("excess").sum() / (pl.len() + SHRINK / 2), n=pl.len()))
    h = h.pivot(on="half", index="user", values=["s", "n"]).drop_nulls().filter((pl.col("n_0") >= 20) & (pl.col("n_1") >= 20))
    rr = spearmanr(h["s_0"], h["s_1"]).statistic; nh = float(np.median(h["n_0"].to_numpy())); r1 = float(rr / (nh - (nh - 1) * rr))
    py = dd.group_by("user", "year").agg(s=pl.col("excess").sum() / (pl.len() + SHRINK), n=pl.len(), avg=pl.col("excess").mean()).filter(pl.col("n") >= MIN_YEAR)
    ag = pl.read_parquet(ROOT / "analysis" / "out" / "cand" / frozen[key] / "agg.parquet", columns=["user", "year", "sw", "swe"])
    span = dd.group_by("user").agg(y0=pl.col("year").min(), y1=pl.col("year").max())
    fz = ag.join(span, on="user").filter(pl.col("year").is_between(pl.col("y0"), pl.col("y1"))).group_by("user").agg(f=pl.col("swe").sum() / pl.col("sw").sum())
    j = refp.join(fz, on="user"); agree = float(spearmanr(j["s"], j["f"]).statistic)
    M.update(per_pick=r1, people=refp.height, agreement_with_study=agree, scores=sorted(round(float(v), 6) for v in refp["s"].to_list()),
             typical_avg=float(refp["avg"].median()),
             year_q=[round(float(v), 6) for v in np.quantile(py["s"].to_numpy(), np.linspace(0, 1, 1001))], year_people=py.height,
             year_typical={str(y): float(g["avg"].median()) for (y,), g in py.group_by("year")})
    per.write_parquet(REF / f"_pack_ref_{key}.parquet")
    print(f"{key}: reference people {refp.height:,}; person-years {py.height:,}; per-find reliability {r1:.4f} (at 110 / 250 / one year of 40: "
          f"{110 * r1 / (1 + 109 * r1):.2f} / {250 * r1 / (1 + 249 * r1):.2f} / {40 * r1 / (1 + 39 * r1):.2f}); agreement with the study {agree:.3f}", flush=True)
(REF / "pack_meta.json").write_text(json.dumps(meta, separators=(",", ":")))
