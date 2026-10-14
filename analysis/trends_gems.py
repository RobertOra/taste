"""Hidden gems: music people loved that never spread (2026-10-14, exploratory; ListenBrainz, artists)

Artists whose first LB listener came 2015-2022 (F; the tried/kept table starts in 2015). Year 1 = F..F+11, year 3 = F+24..F+35.
  tried / kept (data/site/pack_artist_rows.parquet): t = new listeners past their own first 26 weeks, k = those who kept listening
  (4 separate weeks within 26); kept rate = sum k / sum t over year 1, for artists with >= 10 people who tried them;
  good pickers: committed fans with a good track record in the first 24 months (pickers/rate_A_lb);
  listeners in year 1 and year 3 (distinct; user_artist_month).
Loved = top 10% of kept rate within the birth year. Loved by good pickers = loved and >= 1 good-picker fan.
Outcomes: never spread = year-3 listeners <= year-1 listeners; grew 3x = year-3 >= 3 x year-1.
Ordinary artists are reweighted to the loved artists' mix of birth year and year-1 size (log2 bins), so they started out alike.
Also new artists only (a MusicBrainz release in the 12 months before F). Writes analysis/out/trends_gems.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "gems"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
con.execute(f"CREATE TABLE birth AS SELECT artist, min(month) AS F FROM {uam} GROUP BY artist HAVING min(month) BETWEEN {2015 * 12} AND {2022 * 12 + 11}")
tk = con.execute(f"""SELECT r.artist, sum(r.t)::BIGINT AS T, sum(r.k)::BIGINT AS K FROM read_parquet('{ROOT}/data/site/pack_artist_rows.parquet') r JOIN birth b USING (artist)
                     WHERE r.month BETWEEN b.F AND b.F + 11 GROUP BY r.artist HAVING sum(r.t) >= 10""").pl()
con.register("tk", tk.select("artist").to_arrow())
L = con.execute(f"""SELECT u.artist, count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F AND b.F + 11) AS L1,
                           count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F + 24 AND b.F + 35) AS L3
                    FROM {uam} u JOIN birth b USING (artist) SEMI JOIN tk USING (artist) GROUP BY u.artist""").pl()
G = con.execute(f"""SELECT r.artist, sum(r.n_good)::BIGINT AS G FROM read_parquet('{X}/pickers/rate_A_lb.parquet') r JOIN birth b USING (artist)
                    WHERE r.m BETWEEN b.F AND b.F + 23 GROUP BY r.artist""").pl()
new = con.execute(f"""SELECT DISTINCT b.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a JOIN birth b USING (artist)
                      WHERE a.rm BETWEEN b.F - 12 AND b.F""").pl().with_columns(new=pl.lit(1))
D = (tk.join(L, on="artist").join(G, on="artist", how="left").join(new, on="artist", how="left").join(con.execute("SELECT artist, F // 12 AS year FROM birth").pl(), on="artist")
     .fill_null(0).with_columns(rate=pl.col("K") / pl.col("T"), size=(pl.col("L1") + 1).log(2).floor().cast(pl.Int16),
                                never=(pl.col("L3") <= pl.col("L1")), grew=(pl.col("L3") >= 3 * pl.col("L1"))))
D = D.with_columns(loved=pl.col("rate") >= pl.col("rate").quantile(0.9).over("year"),
                   loved1=pl.col("rate") >= pl.col("rate").quantile(0.99).over("year"),
                   dec=(pl.col("rate").rank("average").over("year") / pl.len().over("year") * 10).ceil().clip(1, 10).cast(pl.Int8))
out = []


def compare(d, flag):
    """loved-type rates vs ordinary artists reweighted to the same year x size mix."""
    lv, od = d.filter(flag), d.filter(~pl.col("loved"))
    w = lv.group_by("year", "size").len().rename({"len": "w"})
    o = od.group_by("year", "size").agg(never=pl.col("never").mean(), grew=pl.col("grew").mean()).join(w, on=["year", "size"])
    return {"n": lv.height, "never": float(lv["never"].mean()), "grew": float(lv["grew"].mean()),
            "never_ord": float((o["never"] * o["w"]).sum() / o["w"].sum()), "grew_ord": float((o["grew"] * o["w"]).sum() / o["w"].sum()),
            "kept_rate": float(lv["rate"].mean()), "kept_rate_ord": float(od["rate"].mean())}


for pop, pf in (("all artists", pl.lit(True)), ("new artists", pl.col("new") == 1)):
    d = D.filter(pf)
    print(f"\n== {pop}: {d.height:,} artists with >= 10 people who tried them in year 1")
    for lab, flag in (("loved", pl.col("loved")), ("loved by good pickers", pl.col("loved") & (pl.col("G") >= 1)),
                      ("loved by 2+ good pickers", pl.col("loved") & (pl.col("G") >= 2)), ("top 1% loved", pl.col("loved1")),
                      ("top 1% loved, good picker", pl.col("loved1") & (pl.col("G") >= 1))):
        r = compare(d, flag); out.append({"pop": pop, "group": lab, "year": None, **r})
        print(f"{lab:22s} ({r['n']:,}; kept {r['kept_rate']:.0%} vs {r['kept_rate_ord']:.0%}): never spread {r['never']:.0%} (ordinary, same start: {r['never_ord']:.0%}) | "
              f"grew 3x {r['grew']:.0%} ({r['grew_ord']:.0%})")
    print("by how loved (tenth of the year's artists by kept rate; ordinary = the bottom 90% reweighted to the same start):")
    for q in range(1, 11):
        r = compare(d, pl.col("dec") == q); out.append({"pop": pop, "group": f"decile {q}", "year": None, **r})
        print(f"  tenth {q:>2} ({r['n']:,}; kept {r['kept_rate']:.0%}): never spread {r['never']:.0%} | grew 3x {r['grew']:.0%}")
    print("by birth year (loved): year | artists | never spread (ordinary) | grew 3x (ordinary)")
    for y in range(2015, 2023):
        r = compare(d.filter(pl.col("year") == y), pl.col("loved")); out.append({"pop": pop, "group": "loved", "year": y, **r})
        print(f"  {y} | {r['n']:,} | {r['never']:.0%} ({r['never_ord']:.0%}) | {r['grew']:.0%} ({r['grew_ord']:.0%})")
(ROOT / "analysis" / "out" / "trends_gems.json").write_text(json.dumps(out, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
