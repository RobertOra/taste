"""Descriptive chart data from already-confirmed sealed measures (no new tests).

thresholds: per band of pickers (ladder.py design, 12 bands), how many of every 1,000 new artists grew 2x..100x within a
  year, vs similar artists (same month and size).
growth: per band, average growth of their new artists vs similar artists, with 95% intervals (bootstrap over people).
scatter: one dot per listener (hidden half, prescience for artists, rated on picks through 2008, >= 20 picks): earlier
  percentile vs how their new artists in 2010-2011 (>= 10 picks) grew compared with similar artists; plus 5% bands.
repeat: the frozen discernment-for-songs candidate's forward test (evaluate.py design): for each band of earlier rank, the
  average later rank, its middle 50%, and the share in the top fifth later.
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
CAND = ROOT / "analysis" / "out" / "cand"
RNG = np.random.default_rng(3)
BANDS = [("0–10", 0, .1), ("10–20", .1, .2), ("20–30", .2, .3), ("30–40", .3, .4), ("40–50", .4, .5), ("50–60", .5, .6),
         ("60–70", .6, .7), ("70–80", .7, .8), ("80–90", .8, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0001)]
THRESH = [2, 3, 5, 10, 20, 50, 100]


def band_expr(col="q"):
    e = pl.lit(None, pl.String)
    for lab, lo, hi in BANDS:
        e = pl.when((pl.col(col) > lo) & (pl.col(col) <= hi)).then(pl.lit(lab)).otherwise(e)
    return e


def mid(lab):
    lo, hi = next((lo, hi) for l, lo, hi in BANDS if l == lab)
    return (lo + min(hi, 1.0)) / 2 * 100


def ladder_data():
    b = pl.read_parquet(X / "bet_outcomes" / "A_artist_sealed.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    parts = []
    for c in (2007, 2008, 2009):
        past = (b.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", band=band_expr()), on="user"))
    f = pl.concat(parts)
    thr = []
    for t in THRESH:
        lt = float(np.log(t))
        exp = b.group_by("m", "bin").agg(sim=(pl.col("v") >= lt).mean())
        g = f.join(exp, on=["m", "bin"]).with_columns(hit=(pl.col("v") >= lt).cast(pl.Float64))
        for lab, _, _ in BANDS:
            x = g.filter(pl.col("band") == lab)
            thr.append({"key": f"{t}x:{lab}", "fold": t, "band": f"{lab}%", "mid": mid(lab), "events": int(x["hit"].sum()),
                        "per_1000": float(x["hit"].mean() * 1000), "similar_per_1000": float(x["sim"].mean() * 1000),
                        "times_similar": float(x["hit"].mean() / x["sim"].mean())})
    ve = b.group_by("m", "bin").agg(ve=pl.col("v").mean())
    g = f.join(ve, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    gro = []
    for lab, _, _ in BANDS:
        per = g.filter(pl.col("band") == lab).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        s_, n_ = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
        w = RNG.poisson(1.0, (500, per.height)).astype(float)
        bs = np.expm1((w @ s_) / (w @ n_))
        gro.append({"key": lab, "band": f"{lab}%", "mid": mid(lab), "growth": float(np.expm1(s_.sum() / n_.sum())),
                    "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "people": per.height})
    return thr, gro


def ladder_data_songs():
    """thresholds and growth for songs (hidden half; exploratory additions 2026-10-13, see SONG_PREREG.md): people ranked on their
    song picks (songs by one artist found the same month count as one pick, as the study's song measure), outcomes per song
    they picked in C+2..C+3, vs similar songs (same month and size). Keys prefixed "songs:"."""
    b = pl.read_parquet(X / "bet_outcomes" / "A_song_sealed.parquet", columns=["user", "artist", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    groups = b.group_by("user", "artist", "m").agg(e=pl.col("e").mean()).with_columns(year=pl.col("m") // 12)
    parts = []
    for c in (2007, 2008, 2009):
        past = (groups.filter(pl.col("year") <= c).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
                .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
        parts.append(b.filter(pl.col("year").is_between(c + 2, c + 3)).join(past.select("user", band=band_expr()), on="user"))
    f = pl.concat(parts)
    thr = []
    for t in THRESH:
        lt = float(np.log(t))
        exp = b.group_by("m", "bin").agg(sim=(pl.col("v") >= lt).mean())
        g = f.join(exp, on=["m", "bin"]).with_columns(hit=(pl.col("v") >= lt).cast(pl.Float64))
        for lab, _, _ in BANDS:
            x = g.filter(pl.col("band") == lab)
            thr.append({"key": f"songs:{t}x:{lab}", "unit": "songs", "fold": t, "band": f"{lab}%", "mid": mid(lab), "events": int(x["hit"].sum()),
                        "per_1000": float(x["hit"].mean() * 1000), "similar_per_1000": float(x["sim"].mean() * 1000),
                        "times_similar": float(x["hit"].mean() / x["sim"].mean())})
    ve = b.group_by("m", "bin").agg(ve=pl.col("v").mean())
    g = f.join(ve, on=["m", "bin"]).with_columns(gx=pl.col("v") - pl.col("ve"))
    gro = []
    rng = np.random.default_rng(31)
    for lab, _, _ in BANDS:
        per = g.filter(pl.col("band") == lab).group_by("user").agg(s=pl.col("gx").sum(), n=pl.len())
        s_, n_ = per["s"].to_numpy(), per["n"].to_numpy().astype(float)
        w = rng.poisson(1.0, (500, per.height)).astype(float)
        bs = np.expm1((w @ s_) / (w @ n_))
        gro.append({"key": f"songs:{lab}", "unit": "songs", "band": f"{lab}%", "mid": mid(lab), "growth": float(np.expm1(s_.sum() / n_.sum())),
                    "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "people": per.height})
    return thr, gro


def repeat_data(name="sealed_D_song_main"):
    agg = pl.read_parquet(CAND / name / "agg.parquet")
    years = sorted(agg["year"].unique().to_list())
    per = lambda d: d.group_by("user").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    rows = []
    for cut in [y for y in years if y + 2 in years and y >= 2006]:
        past = per(agg.filter(pl.col("year") <= cut)).filter(pl.col("n") >= 10)
        fut = per(agg.filter(pl.col("year").is_between(cut + 2, cut + 3))).filter(pl.col("n") >= 10)
        j = past.select("user", p=pl.col("swe") / pl.col("sw")).join(fut.select("user", f=pl.col("swe") / pl.col("sw")), on="user")
        if j.height < 500:
            continue
        rows.append(j.with_columns(q=pl.col("p").rank("average") / pl.len(), rf=pl.col("f").rank("average") / pl.len()))
    d = pl.concat(rows).with_columns(band=band_expr())
    out = []
    for lab, _, _ in BANDS:
        x = d.filter(pl.col("band") == lab)["rf"].to_numpy() * 100
        out.append({"key": lab, "band": f"{lab}%", "mid": mid(lab), "people": int(len(x)), "later_mean": float(x.mean()),
                    "later_p25": float(np.percentile(x, 25)), "later_p75": float(np.percentile(x, 75)),
                    "later_top_fifth": float((x > 80).mean()), "later_bottom_fifth": float((x <= 20).mean())})
    return out


def scatter(cut=2008):
    b = pl.read_parquet(X / "bet_outcomes" / "A_artist_sealed.parquet", columns=["user", "m", "bin", "v", "e"]).with_columns(year=pl.col("m") // 12)
    ve = b.group_by("m", "bin").agg(ve=pl.col("v").mean())
    past = (b.filter(pl.col("year") <= cut).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    fut = (b.filter(pl.col("year").is_between(cut + 2, cut + 3)).join(ve, on=["m", "bin"])
           .group_by("user").agg(g=(pl.col("v") - pl.col("ve")).mean(), nf=pl.len()).filter(pl.col("nf") >= 10))
    d = past.join(fut, on="user").with_columns(x=(pl.col("q") * 100).round(2), y=pl.col("g").exp() - 1).sort("user")
    dots = [{"x": float(x), "y": round(float(y), 4)} for x, y in zip(d["x"], d["y"])]
    lines = []
    for lo in range(0, 100, 5):
        sel = d.filter((pl.col("x") > lo) & (pl.col("x") <= lo + 5))
        lines.append({"key": f"b{lo}", "kind": "band", "lo": lo, "mid": lo + 2.5, "people": sel.height, "mean": float(sel["y"].mean()),
                      "median": float(sel["y"].median()), "above_zero": float((sel["y"] > 0).mean())})
    for key, lo, hi in (("bottom10", 0, 10), ("top10", 90, 100), ("all", 0, 100)):
        sel = d.filter((pl.col("x") > lo) & (pl.col("x") <= hi))
        lines.append({"key": key, "kind": "summary", "lo": lo, "mid": None, "people": sel.height, "mean": float(sel["y"].mean()),
                      "median": float(sel["y"].median()), "above_zero": float((sel["y"] > 0).mean())})
    return dots, lines


def scene_split():
    """Hidden half, descriptive: for each band of pickers, 10x odds vs similar size, split into scene choice x picks within scenes."""
    sys.path.insert(0, str(ROOT / "analysis"))
    from explain import bets_with_bands
    b, f = bets_with_bands("sealed")
    sc = pl.read_parquet(X / "scenes_yearly" / "explore.parquet", columns=["artist", "year", "scene_200"])
    b = b.join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1), x10=(pl.col("v") >= np.log(10)).cast(pl.Float64))
    e1 = b.group_by("m", "bin").agg(s10=pl.col("x10").mean())
    e2 = b.group_by("m", "bin", "scene_200").agg(s10_sc=pl.col("x10").mean())
    f = (f.filter(pl.col("period") == "future").join(sc, on=["artist", "year"], how="left").with_columns(pl.col("scene_200").fill_null(-1))
         .join(e1, on=["m", "bin"]).join(e2, on=["m", "bin", "scene_200"]).with_columns(x10=(pl.col("v") >= np.log(10)).cast(pl.Float64)))
    rows = []
    f = f.with_columns(band2=pl.when(pl.col("q") <= .25).then(pl.lit("0–25")).when(pl.col("q") <= .5).then(pl.lit("25–50")).otherwise(pl.col("band")))
    for lab, lo, hi in (("0–25", 0, .25), ("25–50", .25, .5), ("50–75", .5, .75), ("75–90", .75, .9), ("90–95", .9, .95), ("95–99", .95, .99), ("99–100", .99, 1.0)):
        per = f.filter(pl.col("band2") == lab).group_by("user").agg(h=pl.col("x10").sum(), e=pl.col("s10").sum(), es=pl.col("s10_sc").sum())
        h, e, es = (per[c].to_numpy().astype(float) for c in ("h", "e", "es"))
        w = RNG.poisson(1.0, (500, per.height)).astype(float)
        sq, ws = (w @ es) / (w @ e), (w @ h) / (w @ es)
        rows.append({"key": lab, "band": f"{lab}%", "mid": (lo + hi) / 2 * 100, "people": per.height, "total": float(h.sum() / e.sum()),
                     "scenes": float(es.sum() / e.sum()), "scenes_lo": float(np.percentile(sq, 2.5)), "scenes_hi": float(np.percentile(sq, 97.5)),
                     "artists": float(h.sum() / es.sum()), "artists_lo": float(np.percentile(ws, 2.5)), "artists_hi": float(np.percentile(ws, 97.5))})
    return rows


def crowd_log():
    """Hidden half, descriptive: growth multiplier by number of good pickers among new fans (each count with >= 100
    artist-months), within niche / middle / crowded, plus a constant per-picker boost fitted within cells (all counts)."""
    df = pl.read_parquet(X / "pickers" / "rate_A_sealed.parquet")
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), others=pl.col("n_ord") + pl.col("n_poor"))
    cell = ["m", "sz", "mo", "ub", "n_ord", "n_poor"]
    df = df.with_columns(cs=pl.len().over(cell), cg=pl.col("n_good").n_unique().over(cell)).filter((pl.col("cs") >= 2) & (pl.col("cg") >= 2))
    df = df.with_columns(gx=pl.col("g") - (pl.col("g").sum().over(cell) - pl.col("g")) / (pl.col("cs") - 1),
                         grp=pl.when(pl.col("others") <= 2).then(pl.lit("niche")).when(pl.col("others") <= 5).then(pl.lit("middle")).otherwise(pl.lit("crowded")))
    rows = []
    for grp in ("niche", "middle", "crowded"):
        d = df.filter(pl.col("grp") == grp)
        for k in range(0, 40):
            x = d.filter(pl.col("n_good") == k)
            if x.height < 100:
                break
            a = x.group_by("artist").agg(s=pl.col("gx").sum(), n=pl.len())
            sv, nv = a["s"].to_numpy(), a["n"].to_numpy().astype(float)
            w = RNG.poisson(1.0, (500, a.height)).astype(float)
            bs = (w @ sv) / (w @ nv)
            rows.append({"key": f"{grp}:{k}", "kind": "point", "group": grp, "good": k, "mult": float(np.exp(sv.sum() / nv.sum())),
                         "lo": float(np.exp(np.percentile(bs, 2.5))), "hi": float(np.exp(np.percentile(bs, 97.5))), "artist_months": x.height})
        kmax = rows[-1]["good"]
        sub = d.filter(pl.col("n_good") <= kmax).with_columns(Gd=pl.col("n_good").cast(pl.Float64))
        sub = sub.with_columns(xd=pl.col("Gd") - pl.col("Gd").mean().over(cell), yd=pl.col("g") - pl.col("g").mean().over(cell))
        xg, yg = sub["xd"].to_numpy(), sub["yd"].to_numpy()
        ua, inv = np.unique(sub["artist"].to_numpy(), return_inverse=True)
        boots = []
        for _ in range(500):
            w = RNG.poisson(1.0, len(ua))[inv].astype(float)
            boots.append(((w * xg) @ yg) / ((w * xg) @ xg))
        est = float((xg @ yg) / (xg @ xg))
        base = next(r["mult"] for r in rows if r["group"] == grp and r["good"] == 0)
        rows.append({"key": f"{grp}:fit", "kind": "fit", "group": grp, "good": None, "mult": base, "boost": float(np.exp(est)),
                     "boost_lo": float(np.exp(np.percentile(boots, 2.5))), "boost_hi": float(np.exp(np.percentile(boots, 97.5))), "kmax": kmax})
    return rows


def poor_crowd():
    """Hidden half, descriptive (2026-10-13): the crowd curve with poor pickers. Growth by the number of poor pickers among an
    artist's new fans, against artist-months of the same month, size, momentum and unrated new fans with exactly the same
    numbers of good and ordinary new fans (ladder.py crowd_curve with the roles swapped). Niche / middle / crowded = 0-2 / 3-5 /
    6+ other rated new fans (good + ordinary). Each count shown while it has >= 300 artist-months; the rest pooled. Plus a
    per-poor-picker slope within cells. Bootstrap over artists (1,000 draws)."""
    df = pl.read_parquet(X / "pickers" / "rate_A_sealed.parquet")
    df = df.with_columns(g=((pl.col("l1") + 1) / (pl.col("l0") + 1)).log(), sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), others=pl.col("n_ord") + pl.col("n_good"))
    cell = ["m", "sz", "mo", "ub", "n_ord", "n_good"]
    df = df.with_columns(cs=pl.len().over(cell), cp=pl.col("n_poor").n_unique().over(cell)).filter((pl.col("cs") >= 2) & (pl.col("cp") >= 2))
    df = df.with_columns(gx=pl.col("g") - (pl.col("g").sum().over(cell) - pl.col("g")) / (pl.col("cs") - 1),
                         grp=pl.when(pl.col("others") <= 2).then(pl.lit("niche")).when(pl.col("others") <= 5).then(pl.lit("middle")).otherwise(pl.lit("crowded")),
                         Pc=pl.col("n_poor").clip(0, 6).cast(pl.Float64))
    df = df.with_columns(Pd=pl.col("Pc") - pl.col("Pc").mean().over(cell), yd=pl.col("g") - pl.col("g").mean().over(cell))
    rng = np.random.default_rng(29)
    rows = []
    for grp in ("niche", "middle", "crowded"):
        d = df.filter(pl.col("grp") == grp)
        counts = d.group_by("n_poor").agg(n=pl.len()).sort("n_poor")
        kmax = 0
        for k, n in zip(counts["n_poor"], counts["n"]):
            if k == kmax + 1 and n >= 300:
                kmax = k
            elif k > kmax + 1 or (k == kmax + 1 and n < 300):
                break
        d = d.with_columns(P=pl.col("n_poor").clip(0, kmax + 1))
        a = d.group_by("artist", "P").agg(s=pl.col("gx").sum(), n=pl.len())
        for k in range(0, kmax + 2):
            x = a.filter(pl.col("P") == k)
            if x.height == 0:
                continue
            sv, nv = x["s"].to_numpy().astype(float), x["n"].to_numpy().astype(float)
            w = rng.poisson(1.0, (1000, x.height)).astype(float)
            gb = np.expm1((w @ sv) / (w @ nv))
            rows.append({"key": f"{grp}:{k}", "kind": "point", "crowd": grp, "poor": k, "label": f"{k}+" if k == kmax + 1 else str(k),
                         "artist_months": int(nv.sum()), "growth": float(np.expm1(sv.sum() / nv.sum())),
                         "growth_lo": float(np.percentile(gb, 2.5)), "growth_hi": float(np.percentile(gb, 97.5))})
        ua, inv = np.unique(d["artist"].to_numpy(), return_inverse=True)
        xg, yg = d["Pd"].to_numpy(), d["yd"].to_numpy()
        bb = [((w * xg) @ yg) / ((w * xg) @ xg) for w in (rng.poisson(1.0, len(ua))[inv].astype(float) for _ in range(500))]
        rows.append({"key": f"{grp}:slope", "kind": "slope", "crowd": grp, "per_picker": float(np.expm1((xg @ yg) / (xg @ xg))),
                     "lo": float(np.expm1(np.percentile(bb, 2.5))), "hi": float(np.expm1(np.percentile(bb, 97.5)))})
    return rows

def crowd_means():
    """Hidden half: the average number of good pickers among new fans, for the artist-months behind each crowding line
    (same filters as analysis/ladder.py crowd_curve), i.e. where 'similar artists' sit on that line."""
    df = pl.read_parquet(X / "pickers" / "rate_A_sealed.parquet")
    df = df.with_columns(sz=(pl.col("l0") + 1).log(2).floor().cast(pl.Int16),
                         mo=(((pl.col("l0") + 1) / (pl.col("l_pre") + 1)).log() / 0.5).floor().clip(-3, 3).cast(pl.Int8),
                         ub=pl.col("n_unrated").clip(0, 4), others=pl.col("n_ord") + pl.col("n_poor"))
    cell = ["m", "sz", "mo", "ub", "n_ord", "n_poor"]
    df = df.with_columns(cs=pl.len().over(cell), cg=pl.col("n_good").n_unique().over(cell)).filter((pl.col("cs") >= 2) & (pl.col("cg") >= 2))
    df = df.with_columns(grp=pl.when(pl.col("others") <= 2).then(pl.lit("niche")).when(pl.col("others") <= 5).then(pl.lit("middle")).otherwise(pl.lit("crowded")))
    return [{"key": f"{g}:mean", "crowd": g, "mean_good": float(df.filter(pl.col("grp") == g)["n_good"].mean())} for g in ("niche", "middle", "crowded")]


def crowd_steps(rows):
    """What each additional good picker adds: step k = multiplier at k / multiplier at k-1 (from crowd_log points), with an
    approximate 95% range from the two points' ranges (independent groups of artist-months)."""
    out = []
    for g in ("niche", "middle", "crowded"):
        pts = sorted([r for r in rows if r["group"] == g and r["kind"] == "point"], key=lambda r: r["good"])
        for a, b in zip(pts[:-1], pts[1:]):
            sa = (np.log(a["hi"]) - np.log(a["lo"])) / 3.92
            sb = (np.log(b["hi"]) - np.log(b["lo"])) / 3.92
            se, st = float(np.sqrt(sa ** 2 + sb ** 2)), float(np.log(b["mult"]) - np.log(a["mult"]))
            out.append({"key": f"{g}:{b['good']}", "group": g, "nth": b["good"], "step": float(np.expm1(st)),
                        "lo": float(np.expm1(st - 1.96 * se)), "hi": float(np.expm1(st + 1.96 * se)), "artist_months": b["artist_months"]})
    return out


if __name__ == "__main__":
    W = ROOT / "analysis" / "writeup"
    if "--poor-crowd" in sys.argv:
        rows = poor_crowd()
        (W / "poorcrowd.json").write_text(json.dumps(rows, indent=1))
        for r in rows:
            print(r)
        raise SystemExit
    if "--crowd-means" in sys.argv:
        rows = crowd_means()
        (ROOT / "analysis" / "out" / "crowd_means_sealed.json").write_text(json.dumps(rows, indent=1))
        print(rows)
        raise SystemExit
    if "--crowd-steps" in sys.argv:
        (W / "crowdsteps.json").write_text(json.dumps(crowd_steps(json.loads((W / "crowdlog.json").read_text())), indent=1))
        raise SystemExit
    if "--crowd-log" in sys.argv:
        rows = crowd_log()
        (W / "crowdlog.json").write_text(json.dumps(rows, indent=1))
        for r in rows:
            if r["kind"] == "fit":
                print(f"  {r['group']}: per good picker x{r['boost']:.3f} [{r['boost_lo']:.3f}, {r['boost_hi']:.3f}], counts 0-{r['kmax']}")
        raise SystemExit
    if "--scene-split" in sys.argv:
        rows = scene_split()
        (W / "scenesplit.json").write_text(json.dumps(rows, indent=1))
        for r in rows:
            print(f"  {r['band']:>8}: scenes {r['scenes']:.2f} x artists {r['artists']:.2f} = {r['total']:.2f}")
        raise SystemExit
    if "--songs" in sys.argv:   # add song rows to thresholds.json and growthband.json (artist rows untouched)
        thr, gro = ladder_data_songs()
        for name, rows in (("thresholds", thr), ("growthband", gro)):
            old = [r for r in json.loads((W / f"{name}.json").read_text()) if r.get("unit", "artists") != "songs"]
            (W / f"{name}.json").write_text(json.dumps(old + rows, indent=1))
        for r in gro:
            print(f"  songs {r['band']:>8} growth {r['growth']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}] people {r['people']}")
        for r in thr:
            if r["band"] == "99–100%":
                print(f"  songs top 1% {r['fold']:>3}x: {r['per_1000']:.1f} vs {r['similar_per_1000']:.2f} per 1,000 = {r['times_similar']:.1f}x ({r['events']} events)")
        raise SystemExit
    dots, lines = scatter()
    (W / "scatter.json").write_text(json.dumps(dots, separators=(",", ":")))
    (W / "scatterline.json").write_text(json.dumps(lines, indent=1))
    print("scatter", len(dots), "dots;", [(r["key"], round(r["mean"], 3), round(r["above_zero"], 2)) for r in lines if r["kind"] == "summary"])
    if "--scatter-only" in sys.argv:
        raise SystemExit
    thr, gro = ladder_data()
    rep = repeat_data()
    for name, rows in (("thresholds", thr), ("growthband", gro), ("repeat", rep)):
        (W / f"{name}.json").write_text(json.dumps(rows, indent=1))
    for r in rep:
        print(f"  {r['band']:>8} n {r['people']:>6} later mean {r['later_mean']:.0f} (mid 50% {r['later_p25']:.0f}-{r['later_p75']:.0f}) top fifth later {r['later_top_fifth']:.0%}")
    for r in gro:
        print(f"  {r['band']:>8} growth {r['growth']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}]")
