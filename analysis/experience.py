"""Experience, three ways: do people pick better with practice? (post-freeze, descriptive unless pre-registered)

Artist picks scored with the frozen prescience measure (per-bet excess e). For each pick, three measures of practice up to
(not including) the pick's month: years since the first listen, cumulative plays, and cumulative distinct artists tried.
Within-person: each pick's e minus that person's own average e (people with >= 40 picks), averaged in bins of each measure,
so the curve shows how the same people change as practice accumulates, not who practises more. Also one within-person
regression with all three measures together (log2 of plays and artists), to see which one carries the change.
Bootstrap over people (500 draws).

Usage: experience.py --half explore|sealed
"""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
RNG = np.random.default_rng(1616)
B = 500
MONTH = "(year(to_timestamp({w}::BIGINT * 604800)) * 12 + month(to_timestamp({w}::BIGINT * 604800)) - 1)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", choices=["explore", "sealed"], required=True)
    half = ap.parse_args().half
    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
    plays = con.execute(f"""SELECT user, month, sum(plays)::BIGINT AS p FROM read_parquet('{X}/user_artist_month/{half}/*.parquet') GROUP BY ALL""").pl()
    tried = con.execute(f"""SELECT user, {MONTH.format(w='first_week')}::INT AS month, count(*)::BIGINT AS a
                            FROM read_parquet('{X}/user_artist/{half}/*.parquet') GROUP BY ALL""").pl()
    cum = (plays.join(tried, on=["user", "month"], how="full", coalesce=True).fill_null(0).sort("user", "month")
           .with_columns(cp=pl.col("p").cum_sum().over("user") - pl.col("p"), ca=pl.col("a").cum_sum().over("user") - pl.col("a"))
           .select("user", "month", "cp", "ca"))
    uf = pl.read_parquet(X / "user_features" / f"{half}.parquet", columns=["user", "start_week"]).with_columns(
        start_m=(pl.from_epoch(pl.col("start_week").cast(pl.Int64) * 604800, time_unit="s").dt.year() * 12
                 + pl.from_epoch(pl.col("start_week").cast(pl.Int64) * 604800, time_unit="s").dt.month() - 1))
    b = pl.read_parquet(X / "bet_outcomes" / f"A_artist_{half}.parquet", columns=["user", "m", "e"])
    b = (b.join(uf.select("user", "start_m"), on="user").join(cum.rename({"month": "m"}), on=["user", "m"], how="left")
         .with_columns(pl.col("cp").fill_null(0), pl.col("ca").fill_null(0),
                       years=((pl.col("m") - pl.col("start_m")) / 12.0)))
    b = b.filter(pl.len().over("user") >= 40).with_columns(ed=pl.col("e") - pl.col("e").mean().over("user"))
    print(f"{b.height:,} picks by {b['user'].n_unique():,} people")
    measures = {
        "years": ("Years since first listen", [(0.5, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 9)], "years"),
        "plays": ("Plays before the pick", [(0, 5e3), (5e3, 1e4), (1e4, 2e4), (2e4, 4e4), (4e4, 8e4), (8e4, 1.6e5), (1.6e5, 1e9)], "cp"),
        "artists": ("Artists tried before the pick", [(0, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 1e9)], "ca"),
    }
    out = {"bins": []}
    for key, (label, bins, col) in measures.items():
        print(f"\n{label}:")
        for lo, hi in bins:
            x = b.filter((pl.col(col) >= lo) & (pl.col(col) < hi))
            per = x.group_by("user").agg(s=pl.col("ed").sum(), n=pl.len())
            sv, nv = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (B, per.height)).astype(float)
            bs = (w @ sv) / (w @ nv)
            est = float(sv.sum() / nv.sum())
            lab = (f"{lo:g}–{hi:g}" if hi < 1e8 else f"{lo:g}+") if key == "years" else (
                f"{int(lo):,}–{int(hi):,}" if hi < 1e8 else f"{int(lo):,}+")
            out["bins"].append({"key": f"{key}:{lab}", "measure": key, "label": lab, "lo": lo, "picks": x.height, "people": per.height,
                                "vs_own_average": float(np.expm1(est)), "ci_lo": float(np.expm1(np.percentile(bs, 2.5))),
                                "ci_hi": float(np.expm1(np.percentile(bs, 97.5)))})
            print(f"  {lab:>16}: {np.expm1(est):+.2%} [{np.expm1(np.percentile(bs, 2.5)):+.2%}, {np.expm1(np.percentile(bs, 97.5)):+.2%}]  "
                  f"({x.height:,} picks, {per.height:,} people)")
    # within-person regression with all three measures
    d = b.with_columns(l2p=(pl.col("cp") + 1000).log(2), l2a=(pl.col("ca") + 50).log(2))
    cols = ["years", "l2p", "l2a"]
    for c in cols + ["e"]:
        d = d.with_columns((pl.col(c) - pl.col(c).mean().over("user")).alias(c + "_d"))
    Xm = d.select([c + "_d" for c in cols]).to_numpy(); y = d["e_d"].to_numpy()
    est = np.linalg.lstsq(Xm, y, rcond=None)[0]
    ua, inv = np.unique(d["user"].to_numpy(), return_inverse=True)
    bs = []
    for _ in range(200):
        w = np.sqrt(RNG.poisson(1.0, len(ua))[inv].astype(float))
        bs.append(np.linalg.lstsq(Xm * w[:, None], y * w, rcond=None)[0])
    bs = np.array(bs)
    out["together"] = {c: {"per_unit": float(np.expm1(est[i])), "lo": float(np.expm1(np.percentile(bs[:, i], 2.5))),
                           "hi": float(np.expm1(np.percentile(bs[:, i], 97.5)))} for i, c in enumerate(["per_year", "per_doubling_of_plays", "per_doubling_of_artists"])}
    print("\nAll three together (within person):", {k: f"{v['per_unit']:+.2%} [{v['lo']:+.2%}, {v['hi']:+.2%}]" for k, v in out["together"].items()})
    (ROOT / "analysis" / "out" / f"experience_{half}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
