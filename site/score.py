"""Score someone's music taste from a Spotify listening history, against ListenBrainz (reference data in data/site).

Taste here = prescience (do the artists and songs you get into go on to grow, compared with similar picks the same month),
the most lasting of the project's measures. Corrections as in the project (site/features.py). Same pick rule as the project: a pick is an artist (or song) you played in at
least 4 separate weeks, the 4th within 26 weeks of your first play, after your first 26 weeks of history; dated at the 4th
week's month. A pick's growth: g = ln((A1 + 1) / (A0 + 1)), A0 = ListenBrainz listeners who first played it in the 6
months up to the pick, A1 = in months 7-12 after; minus the average g of ListenBrainz picks made the same month at the same
size (log2 bins of A0). Your score: sum of those excesses / (picks + 20), over your last five judged years; compared with
ListenBrainz listeners scored the same way. Ranges use the measured reliability (build_baselines.py).

    from score import score_files; result = score_files(["Streaming_History_Audio_2019.json", ...])
"""
import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import duckdb
import polars as pl

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "site"
MIN_PLAY_MS = 30_000          # a play counts like a scrobble: at least 30 seconds
ONBOARD_WEEKS, WINDOW_WEEKS, MIN_WEEKS = 26, 26, 4
SHRINK = 20
WINDOW_YEARS = 5
MIN_PICKS, SOLID_PICKS = 110, 250   # roughly half signal, and a solid score (project reliability)
MIN_MATCH, WARN_MATCH = 0.40, 0.60  # share of plays whose artist ListenBrainz knows
MIN_HISTORY_WEEKS = 104
EXCLUDE_ARTISTS = {"various artists", "unknown artist", ""}
nd = NormalDist()


def name_hash(s):
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big", signed=True)


def week_of(ts):
    return int(ts // 604800)


def month_of_week(w):
    d = datetime.fromtimestamp(w * 604800 + 302400, tz=timezone.utc)
    return d.year * 12 + d.month - 1


def month_label(m):
    return f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m % 12]} {m // 12}"


# ---------- reading histories
def _records(path):
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.lower().endswith(".json") and ("streaming" in n.lower() or "history" in n.lower()):
                    yield n, json.loads(z.read(n))
    elif p.suffix.lower() == ".json":
        yield p.name, json.loads(p.read_text(encoding="utf-8"))


def read_history(paths):
    """-> (plays DataFrame [ts, artist, track], kind) where kind is 'extended', 'standard' or None."""
    rows, kinds = [], set()
    for name, data in (r for p in paths for r in _records(p)):
        if not isinstance(data, list):
            continue
        for d in data:
            if not isinstance(d, dict):
                continue
            if "ts" in d and "master_metadata_album_artist_name" in d:      # extended streaming history
                kinds.add("extended")
                a, t, ms = d.get("master_metadata_album_artist_name"), d.get("master_metadata_track_name"), d.get("ms_played") or 0
                if a and t and ms >= MIN_PLAY_MS:
                    ts = datetime.fromisoformat(d["ts"].replace("Z", "+00:00")).timestamp()
                    rows.append((ts, a, t))
            elif "endTime" in d and "artistName" in d:                          # standard (last year only)
                kinds.add("standard")
                if (d.get("msPlayed") or 0) >= MIN_PLAY_MS:
                    ts = datetime.strptime(d["endTime"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
                    rows.append((ts, d["artistName"], d.get("trackName") or ""))
    kind = "extended" if "extended" in kinds else ("standard" if kinds else None)
    df = pl.DataFrame(rows, schema=["ts", "artist", "track"], orient="row") if rows else pl.DataFrame(schema={"ts": pl.Float64, "artist": pl.String, "track": pl.String})
    return df, kind


# ---------- picks
def find_picks(plays, by):
    """by = ['artist'] or ['artist', 'track']. Returns one row per pick: key columns, first_week, w4, m, plays_26w."""
    start = plays["week"].min()
    w = plays.group_by(by + ["week"]).agg(n=pl.col("cnt").sum()).sort(by + ["week"])
    w = w.with_columns(rn=pl.int_range(pl.len()).over(by) + 1, fw=pl.col("week").min().over(by))
    agg = w.group_by(by).agg(first_week=pl.col("week").min(), w4=pl.col("week").filter(pl.col("rn") == MIN_WEEKS).first(),
                             plays_26w=pl.col("n").filter(pl.col("week") < pl.col("fw") + WINDOW_WEEKS).sum())
    agg = agg.filter(pl.col("w4").is_not_null() & (pl.col("w4") - pl.col("first_week") < WINDOW_WEEKS) & (pl.col("first_week") >= start + ONBOARD_WEEKS))
    return agg.with_columns(m=pl.col("w4").map_elements(month_of_week, return_dtype=pl.Int32))


# ---------- reference
_cache = {}


def ref():
    if not _cache:
        _cache["meta"] = json.loads((REF / "reference.json").read_text())
        _cache["con"] = duckdb.connect()
        _cache["con"].execute("SET threads=4")
    return _cache["meta"], _cache["con"]


def growth(con, picks, unit, exclude_self=False):
    """Add a0, a1, g, bin and excess (vs similar ListenBrainz picks, with the project's corrections; site/features.py)."""
    key = "artist" if unit == "artist" else "rec"
    pk = picks.with_columns(key=pl.col(key))
    con.register("pk_in", pk.select("key", "artist", "m").to_arrow())
    feats = F.raw_features(con, "pk_in", unit)
    if exclude_self:  # tests on ListenBrainz users only: remove the user's own first listen from a0, as build_baselines.py does
        own = pk.select("key", "artist", "m", fmo=pl.col("first_week").map_elements(month_of_week, return_dtype=pl.Int32))
        feats = feats.join(own, on=["key", "artist", "m"], how="left").with_columns(
            a0=(pl.col("a0") - pl.col("fmo").is_between(pl.col("m") - 5, pl.col("m")).fill_null(False).cast(pl.Int64)).clip(0)).drop("fmo")
    feats = F.apply_effects(F.derive(feats), unit)
    return pk.join(feats.select("key", "artist", "m", "a0", "a1", "g", "excess", "ten", "ten_rate", "up3", "up3_rate", "g_mean"), on=["key", "artist", "m"], how="left")


def true_range(rho, observed):
    rho = max(min(rho, 0.999), 0.0)
    z, sd = nd.inv_cdf(min(max(observed, 0.005), 0.995)) * rho ** 0.5, (1 - rho) ** 0.5
    return 100 * nd.cdf(z - 1.2816 * sd), 100 * nd.cdf(z + 1.2816 * sd)


def summarize(p, unit, meta):
    """Score one unit from judged picks with excess; p has columns m, excess, w (weight)."""
    last = p["m"].max()
    win = p.filter(pl.col("m") > last - 12 * WINDOW_YEARS)
    n = win.height
    s = float((win["excess"] * win["w"]).sum() / (win["w"].sum() + SHRINK)) if n else None
    r = meta[unit]
    res = {"picks": n, "window": f"{month_label(win['m'].min())} – {month_label(last)}" if n else None, "enough": n >= MIN_PICKS, "solid": n >= SOLID_PICKS}
    if n >= MIN_PICKS:
        import bisect
        ref_scores = r["scores"]
        pct = bisect.bisect_left(ref_scores, s) / len(ref_scores)
        rel = n * r["per_pick"] / (1 + (n - 1) * r["per_pick"])
        lo, hi = true_range(rel, pct)
        res.update({"score": s, "percentile": round(100 * pct), "range": [round(lo), round(hi)], "reliability": round(rel, 2)})
    return res


def score_files(paths):
    plays, kind = read_history(paths)
    return score_plays(plays, kind)


def score_plays(plays, kind, exclude_self=False):
    """plays: ts, artist, track (names), optionally cnt (plays per row), artist_name_h, rec_name_h (precomputed hashes)."""
    meta, con = ref()
    if "cnt" not in plays.columns:
        plays = plays.with_columns(cnt=pl.lit(1, pl.Int64))
    out = {"kind": kind, "checks": [], "ok": False}
    if kind is None or plays.height == 0:
        out["checks"].append({"id": "format", "ok": False, "text": "We couldn't find Spotify listening history in those files."})
        return out
    plays = plays.with_columns(week=(pl.col("ts") // 604800).cast(pl.Int64), an=pl.col("artist").str.strip_chars().str.to_lowercase(),
                               tn=pl.col("track").str.strip_chars().str.to_lowercase()).filter(~pl.col("an").is_in(list(EXCLUDE_ARTISTS)))
    span = int(plays["week"].max() - plays["week"].min())
    out["history"] = {"plays": int(plays["cnt"].sum()), "from": datetime.fromtimestamp(plays["ts"].min(), tz=timezone.utc).strftime("%b %Y"),
                      "to": datetime.fromtimestamp(plays["ts"].max(), tz=timezone.utc).strftime("%b %Y"), "weeks": span}
    if kind == "standard":
        out["checks"].append({"id": "format", "ok": False, "text": "This is Spotify's one-year export. Each find needs a year of follow-up, so we need your "
                              "Extended streaming history (Spotify → Account → Privacy settings → request Extended streaming history; it can take a few weeks)."})
    if span < MIN_HISTORY_WEEKS:
        out["checks"].append({"id": "history", "ok": False, "text": f"Your history covers {span // 52} year(s); we need at least two."})
    # matching (artist ids as in ListenBrainz; keep the name you see for display)
    plays = plays.rename({"artist": "artist_name"})
    if "artist_name_h" not in plays.columns:
        plays = plays.with_columns(artist_name_h=pl.col("an").map_elements(name_hash, return_dtype=pl.Int64),
                                   rec_name_h=(pl.col("an") + "\t" + pl.col("tn")).map_elements(name_hash, return_dtype=pl.Int64))
    con.register("hs", plays.select("artist_name_h").unique().to_arrow())
    amap = con.execute(f"SELECT m.artist_name_h, m.artist FROM read_parquet('{REF}/artist_map.parquet') m SEMI JOIN hs USING (artist_name_h)").pl()
    plays = plays.join(amap, on="artist_name_h", how="left")
    matched = float((plays["cnt"] * plays["artist"].is_not_null()).sum() / plays["cnt"].sum())
    out["history"]["matched_share"] = round(matched, 3)
    if matched < MIN_MATCH:
        out["checks"].append({"id": "match", "ok": False, "text": f"We recognised only {matched:.0%} of your listening. Your taste may be outside what we can judge."})
    elif matched < WARN_MATCH:
        out["checks"].append({"id": "match", "ok": True, "warn": True, "text": f"We recognised {matched:.0%} of your listening, so your score rests on part of it."})
    if any(not c["ok"] for c in out["checks"]):
        return out
    last_judgeable = meta["last_month"] - 12
    units = {}
    # artists
    known = plays.filter(pl.col("artist").is_not_null())
    pa = find_picks(known, ["artist"]).join(known.group_by("artist").agg(name=pl.col("artist_name").first()), on="artist", how="left")
    recent_a = pa.filter(pl.col("m") > last_judgeable).height
    pa = growth(con, pa.filter(pl.col("m") <= last_judgeable), "artist", exclude_self).drop_nulls("excess").with_columns(w=pl.lit(1.0))
    units["artist"] = summarize(pa, "artist", meta) | {"too_recent": recent_a}
    # songs (by one artist in the same month count as one pick, weighted by plays)
    con.register("rh", known.select("rec_name_h").unique().to_arrow())
    rmap = con.execute(f"SELECT m.rec_name_h, m.rec FROM read_parquet('{REF}/rec_map.parquet') m SEMI JOIN rh USING (rec_name_h)").pl()
    ps = find_picks(known, ["artist", "rec_name_h"]).join(rmap, on="rec_name_h", how="inner")
    recent_s = ps.filter(pl.col("m") > last_judgeable).height
    ps = growth(con, ps.filter(pl.col("m") <= last_judgeable), "song", exclude_self).drop_nulls("excess")
    ps = ps.group_by("artist", "m").agg(excess=(pl.col("excess") * pl.col("plays_26w")).sum() / pl.col("plays_26w").sum(), w=pl.lit(1.0).first())
    units["song"] = summarize(ps, "song", meta) | {"too_recent": recent_s}
    out["units"] = units
    # headline: songs if enough, else artists
    head = "song" if units["song"].get("enough") else ("artist" if units["artist"].get("enough") else None)
    out["headline_unit"] = head
    if head is None:
        need = MIN_PICKS - max(units["artist"]["picks"], units["song"]["picks"])
        out["checks"].append({"id": "picks", "ok": False, "text": f"We found {units['artist']['picks']} artists and {units['song']['picks']} songs you got into that we can judge; "
                              f"we need at least {MIN_PICKS} of one. About {need} more."})
        return out
    if not units[head]["solid"]:
        out["checks"].append({"id": "picks", "ok": True, "warn": True, "text": "You have enough finds for a rough score; more history would narrow the range."})
    # stories: best calls, tenfold, obsessions (artists)
    pa_w = pa.filter(pl.col("m") > pa["m"].max() - 12 * WINDOW_YEARS)
    out["best_calls"] = [{"artist": r["name"], "found": month_label(r["m"]), "grew": round(math.exp(r["g"]), 1), "similar_grew": round(math.exp(r["g_mean"]), 1)}
                         for r in pa_w.sort("excess", descending=True).head(8).iter_rows(named=True)]
    out["tenfold"] = {"yours": int(pa_w["ten"].sum()), "expected": round(float(pa_w["ten_rate"].sum()), 1), "picks": pa_w.height}
    out["took_off"] = {"yours": int(pa_w["up3"].sum()), "expected": round(float(pa_w["up3_rate"].sum())), "picks": pa_w.height}
    q = pa_w.with_columns(hooked=pl.col("plays_26w").rank("average") / pl.len())
    hi, lo = q.filter(pl.col("hooked") > .75), q.filter(pl.col("hooked") <= .25)
    out["obsessions"] = {"most_hooked": float(math.expm1(hi["excess"].mean())) if hi.height else None, "least_hooked": float(math.expm1(lo["excess"].mean())) if lo.height else None}
    out["ok"] = True
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(score_files(sys.argv[1:]), indent=1, default=str))
