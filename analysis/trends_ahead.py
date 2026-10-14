"""How far ahead are the best pickers? (2026-10-14, exploratory; ListenBrainz, artists)

Breakout artists: first LB listener 2012-2021 (F); monthly distinct listeners L; peak = the highest month within F..F+60, at least
50 listeners and at least 10x their average over F..F+5. Breakout month B = the first month with at least half the peak.
Everyone who got into such an artist (the study's rule; bet table, month m), grouped by how good a picker they were then (rated on
artist picks up to two years before, as the study): top 1%, rest of the top fifth, middle, bottom fifth; plus everyone (incl. unrated).
Lead = B - m months. Per group: median lead, share who got in before the breakout, share at least a year before.
Examples: well-known breakouts (peak >= 300 listeners) with a top-1% picker at least a year early. Writes analysis/out/trends_ahead.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "ahead"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
con.execute(f"CREATE TABLE birth AS SELECT artist, min(month) AS F FROM {uam} GROUP BY artist HAVING min(month) BETWEEN {2012 * 12} AND {2021 * 12 + 11}")
for c in range(8):
    con.execute(f"""COPY (SELECT u.artist, u.month, count(DISTINCT u.user)::INT AS L FROM {uam} u JOIN birth b USING (artist)
                          WHERE ((u.artist % 8) + 8) % 8 = {c} AND u.month BETWEEN b.F AND b.F + 60 GROUP BY ALL) TO '{TMP}/al_{c}.parquet' (FORMAT parquet)""")
al = pl.read_parquet(TMP / "al_*.parquet").join(pl.from_arrow(con.execute("SELECT * FROM birth").arrow()), on="artist")
pk = al.group_by("artist").agg(Lp=pl.col("L").max(), F=pl.col("F").first(), early=pl.col("L").filter(pl.col("month") <= pl.col("F") + 5).sum() / 6)
pk = pk.filter((pl.col("Lp") >= 50) & (pl.col("Lp") >= 10 * pl.col("early")))
B = al.join(pk.select("artist", "Lp"), on="artist").filter(pl.col("L") * 2 >= pl.col("Lp")).group_by("artist").agg(B=pl.col("month").min())
pk = pk.join(B, on="artist")
print(f"breakout artists: {pk.height:,}", flush=True)
con.register("pk", pk.select("artist", "B", "Lp").to_arrow())
fans = con.execute(f"""SELECT p.user, p.artist, min(p.m) AS m, any_value(k.B) AS B FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') p
                       JOIN pk k USING (artist) GROUP BY p.user, p.artist""").pl().with_columns(lead=pl.col("B") - pl.col("m"), year=pl.col("m") // 12)
b = con.execute(f"SELECT user, m // 12 AS year, e FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet')").pl()
R = []
for y in range(2012, 2027):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    R.append(past.select("user", "q").with_columns(year=pl.lit(y)))
fans = fans.join(pl.concat(R), on=["user", "year"], how="left").with_columns(
    grp=pl.when(pl.col("q") > 0.99).then(pl.lit("top 1%")).when(pl.col("q") > 0.8).then(pl.lit("rest of the top fifth"))
    .when(pl.col("q") > 0.2).then(pl.lit("middle")).when(pl.col("q").is_not_null()).then(pl.lit("bottom fifth")).otherwise(pl.lit("unrated")))
out = []
print("group | fans | median months before the breakout | got in before it | a year or more before")
for g in ("top 1%", "rest of the top fifth", "middle", "bottom fifth", "everyone"):
    d = fans if g == "everyone" else fans.filter(pl.col("grp") == g)
    r = {"group": g, "fans": d.height, "median_lead": float(d["lead"].median()), "before": float((d["lead"] > 0).mean()), "year_before": float((d["lead"] >= 12).mean())}
    out.append(r)
    print(f"{g:22s} | {r['fans']:>8,} | {r['median_lead']:+5.0f} | {r['before']:.0%} | {r['year_before']:.0%}", flush=True)
names = pl.read_parquet(X / "mb_artists_lb.parquet", columns=["artist", "name"])
ex = (fans.filter(pl.col("grp") == "top 1%").group_by("artist").agg(first=pl.col("m").min(), n_top=pl.len())
      .join(pk, on="artist").filter((pl.col("Lp") >= 300) & (pl.col("B") - pl.col("first") >= 12)).join(names, on="artist")
      .with_columns(ahead=pl.col("B") - pl.col("first")).sort("Lp", descending=True).head(25))
mon = lambda m: f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m % 12]} {m // 12}"
print("\nexamples (top-1% picker at least a year early; biggest first): artist | top-1% picker got in | broke out | months ahead | top-1% fans")
for r in ex.iter_rows(named=True):
    print(f"  {r['name'][:30]:30s} | {mon(r['first'])} | {mon(r['B'])} | {r['ahead']} | {r['n_top']}")
(ROOT / "analysis" / "out" / "trends_ahead.json").write_text(json.dumps({"groups": out, "examples": [{**r, "first_label": mon(r["first"]), "B_label": mon(r["B"])}
                                                                         for r in ex.select("name", "first", "B", "ahead", "n_top", "Lp").to_dicts()]}, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
