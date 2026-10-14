"""Packed engine (Python mirror) vs the reference scores build_pack_ref.py computed for the same ListenBrainz users (exclude_self)."""
import sys
from pathlib import Path

import duckdb
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score_pack as SP  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
import os
REF = Path(os.environ.get("SITE_REF", ROOT / "data" / "site"))   # with SITE_OUT for the matching pack (score_pack.py)
NORM, SINGLE = SP.META.get("song_keys") == "norm", SP.META.get("warmup") == "single"
SETTLED = os.environ.get("SETTLED") == "1"   # the shipped song_A/artist_A is the settled variant: compare with the As reference
refs = {k: pl.read_parquet(REF / f"_pack_ref_{k.replace('_A', '_As') if SETTLED and k.endswith('_A') else k}.parquet") for k in ("song_A", "song_D", "artist_A", "artist_D")}
users = refs["song_A"].filter(pl.col("n") >= 110).sample(N, seed=13)["user"].to_list()
con = duckdb.connect(); con.execute("SET memory_limit='4GB'; SET threads=6")
con.register("u", pl.DataFrame({"user": users}).to_arrow())
W0, W1 = 1104537600 // 604800, 1790812800 // 604800
if NORM:   # songs keyed by normalized name: all spellings of a song are one song, as in the reference
    w = con.execute(f"""SELECT w.user, w.week, m.rec AS rec_name_h, any_value(w.artist_name_h) AS artist_name_h, sum(w.plays)::BIGINT AS n
                        FROM read_parquet('{ROOT}/data/lb/user_rec_week/*.parquet') w JOIN read_parquet('{REF}/rec_map.parquet') m USING (rec_name_h)
                        SEMI JOIN u USING (user) WHERE w.week BETWEEN {W0} AND {W1} GROUP BY w.user, w.week, m.rec""").pl()
else:
    w = con.execute(f"""SELECT user, week, rec_name_h, artist_name_h, sum(plays)::BIGINT AS n FROM read_parquet('{ROOT}/data/lb/user_rec_week/*.parquet')
                        SEMI JOIN u USING (user) WHERE week BETWEEN {W0} AND {W1} GROUP BY ALL""").pl()
wa = con.execute(f"""SELECT user, week, artist_name_h, sum(plays)::BIGINT AS n FROM read_parquet('{ROOT}/data/lb/user_artist_week/*.parquet')
                     SEMI JOIN u USING (user) WHERE week BETWEEN {W0} AND {W1} GROUP BY ALL""").pl()
pack = SP.Pack(); rows = []
for uid in users:
    g, ga = w.filter(pl.col("user") == uid), wa.filter(pl.col("user") == uid)
    # artist plays from the artist table, song plays from the song table (as the reference build does)
    aplays = [{"week": wk, "ts": wk * 604800.0, "an": str(h), "name": str(h), "tn": "", "ah": h, "n": n} for wk, h, n in ga.select("week", "artist_name_h", "n").iter_rows()]
    splays = [{"week": wk, "ts": wk * 604800.0, "an": str(ah), "name": str(ah), "tn": str(sh), "ah": ah, "sh": sh, "n": n} for wk, sh, ah, n in g.select("week", "rec_name_h", "artist_name_h", "n").iter_rows()]
    start = min(p["week"] for p in aplays)
    for p in splays:
        p["key_override"] = True
    lj = SP.META["last_month"] - 12
    r = {}
    starts = SP.segment_starts((p["week"] for p in aplays), SINGLE)   # warm-up from the person's whole listening (artist table)
    ap = [p for p in SP.find_picks(aplays, lambda p: p["an"], starts) if SP.META["y0"] <= p["m"] <= lj]
    # songs: same start as the person's whole listening (artist table), keyed by the song name hash
    sp_all = SP.find_picks(splays, lambda p: str(p["sh"]), starts)
    sp = [p for p in sp_all if p["key"] != "0" and SP.META["y0"] <= p["m"] <= lj]
    for p in ap:
        p["art"] = pack.artist(p["ah"]); p["item"] = p["art"]
    for p in sp:
        p["art"] = pack.artist(p["ah"]); p["item"] = pack.song(p["sh"]) if p["art"] else None
    def eligible(p, need):   # the reference's rule for ListenBrainz users: enough *other* people played it since 2015
        tot = sum(r[1] for r in p["item"]["rows"]); own = int(SP.month_of_week(p["first_week"]) >= SP.META["m0"])
        return tot - own >= need
    def dedup(ps):
        seen = {}
        need = 3 if ps is sp else 2
        for p in sorted([p for p in ps if p["item"] and eligible(p, need)], key=lambda p: (p["m"], p["key"])):
            seen.setdefault(p["item"]["id"], p)
        return list(seen.values())
    mA, mS = dedup(ap), dedup(sp)
    for k, ps in (("song_A", mS), ("song_D", mS), ("artist_A", mA), ("artist_D", mA)):
        x = SP.score_measure(k, ps, exclude_self=True)
        rows.append({"user": uid, "key": k, "n": x["picks"], "s": x.get("score")})
t = pl.DataFrame(rows)
for k, ref in refs.items():
    j = t.filter(pl.col("key") == k).join(ref.rename({"s": "ref", "n": "ref_n"}), on="user").drop_nulls(["s", "ref"])
    print(f"{k:9} {j.height} users | Spearman {spearmanr(j['s'], j['ref']).statistic:.4f} | exact picks {(j['n'] == j['ref_n']).mean():.0%} | "
          f"mean abs diff {(j['s'] - j['ref']).abs().mean():.6f} (sd {j['ref'].std():.4f})")
