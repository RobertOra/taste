"""Static engine (Python mirror) vs the builder's static reference scores for the same ListenBrainz users (exclude_self)."""
import sys
from pathlib import Path

import duckdb
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score_static as SS  # noqa: E402

ref = pl.read_parquet(ROOT / "data" / "site" / "_ref_scores_static.parquet").filter(pl.col("n") >= 110)
users = ref.sample(int(sys.argv[1]) if len(sys.argv) > 1 else 300, seed=11)["user"].to_list()
con = duckdb.connect(); con.execute("SET memory_limit='4GB'; SET threads=6")
con.register("u", pl.DataFrame({"user": users}).to_arrow())
w = con.execute(f"""SELECT user, week, artist_name_h, sum(plays)::BIGINT AS n FROM read_parquet('{ROOT}/data/lb/user_artist_week/*.parquet') SEMI JOIN u USING (user)
                    WHERE week BETWEEN {1104537600 // 604800} AND {1790812800 // 604800} GROUP BY ALL""").pl()
rows = []
for uid, g in w.group_by("user"):
    plays = [(wk, str(h), str(h), h, n) for wk, h, n in g.select("week", "artist_name_h", "n").iter_rows()]
    r = SS.score(plays, exclude_self=True)
    rows.append({"user": uid[0], "picks": r.get("picks"), "s": r.get("score")})
t = pl.DataFrame(rows).join(ref.rename({"s": "ref", "n": "ref_n"}), on="user").drop_nulls("s")
print(f"{t.height} users | Spearman {spearmanr(t['s'], t['ref']).statistic:.4f} | picks median {t['picks'].median():.0f} vs {t['ref_n'].median():.0f} | "
      f"mean abs diff {(t['s'] - t['ref']).abs().mean():.5f} (sd {t['ref'].std():.4f}) | exact picks {(t['picks'] == t['ref_n']).mean():.0%}")
