"""End-to-end engine test: rebuild ListenBrainz users' listening as plays, score them with site/score.py, and compare with the
reference scores build_baselines.py computed for the same people (should be close; the engine keeps the user's own first
listen in a0, the builder removes it)."""
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score as S  # noqa: E402

LB, X = ROOT / "data" / "lb", ROOT / "data" / "derived"
con = duckdb.connect(); con.execute("SET memory_limit='4GB'; SET threads=6")
# 300 users with enough judged artist picks (from the project's picks)
users = (pl.read_parquet(X / "bet_outcomes" / "A_artist_lb.parquet", columns=["user", "m"]).filter(pl.col("m") <= 2026 * 12 + 8 - 12)
         .group_by("user").agg(n=pl.len()).filter(pl.col("n").is_between(150, 2000)).sample(int(sys.argv[1]) if len(sys.argv) > 1 else 300, seed=7)["user"].to_list())
con.register("u", pl.DataFrame({"user": users}).to_arrow())
w = con.execute(f"""SELECT w.user, w.week, w.rec_name_h, w.artist_name_h, sum(w.plays)::BIGINT AS cnt FROM read_parquet('{LB}/user_rec_week/*.parquet') w
                    SEMI JOIN u USING (user) WHERE w.week BETWEEN {1104537600 // 604800} AND {1790812800 // 604800} GROUP BY ALL""").pl()
names = pl.read_parquet(LB / "artist_names.parquet")
w = w.join(names, on="artist_name_h", how="left").with_columns(ts=(pl.col("week") * 604800 + 302400).cast(pl.Float64),
        artist=pl.col("name").fill_null("?"), track=pl.lit("x"))
rows = []
for i, u in enumerate(users):
    pu = w.filter(pl.col("user") == u).select("ts", "artist", "track", "cnt", "artist_name_h", "rec_name_h")
    r = S.score_plays(pu, "extended", exclude_self=True)
    a, s_ = r.get("units", {}).get("artist", {}), r.get("units", {}).get("song", {})
    rows.append({"user": u, "ok": r["ok"], "matched": r.get("history", {}).get("matched_share"), "a_picks": a.get("picks"), "a_score": a.get("score"),
                 "a_pct": a.get("percentile"), "s_picks": s_.get("picks"), "s_score": s_.get("score"), "checks": "; ".join(c["id"] for c in r["checks"])})
    if i % 10 == 0:
        print(i, rows[-1], flush=True)
res = pl.DataFrame(rows)
res.write_parquet(ROOT / "data" / "site" / "_engine_test.parquet")  # with exclude_self=True
print(res.select(pl.col("ok").mean(), pl.col("matched").mean(), pl.col("a_picks").median(), pl.col("s_picks").median()))
