"""Experiment: does adding momentum and scene corrections bring the site's artist score closer to the frozen prescience score?
Artist picks (ListenBrainz), last five judged years per person, people with >= 110 picks. Prints split-half reliability and
Spearman agreement with the frozen score for: size only (current), + momentum, + momentum + scene. Also the frozen score's own
split-half on the same picks."""
import math
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
X, REF = ROOT / "data" / "derived", ROOT / "data" / "site"
LAST = 2026 * 12 + 8
MONTH = "(year(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) * 12 + month(make_timestamp({w}::BIGINT * 604800000000 + 302400000000)) - 1)"
con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6")
con.execute(f"""CREATE TABLE pk AS SELECT o.user, o.artist, o.m::INT AS m, o.e, ({MONTH.format(w='b.first_week')})::INT AS fm
    FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') o JOIN read_parquet('{X}/bets/lb/*.parquet') b ON b.user = o.user AND b.artist = o.artist
    WHERE o.m <= {LAST - 12}""")
con.execute("CREATE TABLE km AS SELECT DISTINCT artist, m FROM pk")
con.execute(f"""CREATE TABLE ka AS SELECT k.artist, k.m,
      coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m - 5 AND k.m), 0)::BIGINT AS a0,
      coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m + 7 AND k.m + 12), 0)::BIGINT AS a1,
      coalesce(sum(a.adopters) FILTER (WHERE a.month BETWEEN k.m - 11 AND k.m - 6), 0)::BIGINT AS ap
    FROM km k LEFT JOIN read_parquet('{REF}/artist_adopt.parquet') a ON a.artist = k.artist AND a.month BETWEEN k.m - 11 AND k.m + 12 GROUP BY k.artist, k.m""")
con.execute(f"""CREATE TABLE relm AS SELECT DISTINCT artist, (substr(first_release_date, 1, 4)::INT * 12 + substr(first_release_date, 6, 2)::INT - 1)::INT AS rm
    FROM read_parquet('{X}/mb_release_groups_lb.parquet') WHERE regexp_matches(first_release_date, '^[0-9]{{4}}-[0-9]{{2}}') AND first_release_date < '2700'
      AND primary_type IN ('Album', 'EP', 'Single') AND secondary_types NOT LIKE '%Compilation%'""")
con.execute("""CREATE TABLE rel AS SELECT k.artist, k.m, CASE WHEN count(x.rm) = 0 THEN 4 ELSE 2 * (count(*) FILTER (WHERE x.rm > k.m AND x.rm <= k.m + 3) > 0)::INT
      + (count(*) FILTER (WHERE x.rm >= k.m - 3 AND x.rm <= k.m) > 0)::INT END AS relc FROM km k LEFT JOIN relm x ON x.artist = k.artist GROUP BY k.artist, k.m""")
con.execute(f"CREATE TABLE fa AS SELECT artist, min(month) AS fam FROM read_parquet('{REF}/artist_adopt.parquet') GROUP BY artist")
df = con.execute(f"""SELECT p.user, p.artist, p.m, p.e, greatest(ka.a0 - (p.fm BETWEEN p.m - 5 AND p.m)::INT, 0) AS a0, ka.a1, ka.ap, s.scene_200 AS scene,
      rel.relc, CASE WHEN fa.fam <= 2005 * 12 THEN 9 WHEN p.m - fa.fam < 3 THEN 0 WHEN p.m - fa.fam < 6 THEN 1 WHEN p.m - fa.fam < 12 THEN 2
                     WHEN p.m - fa.fam < 24 THEN 3 ELSE 4 END AS age, coalesce(c.country, '?') AS country
    FROM pk p JOIN ka USING (artist, m) LEFT JOIN read_parquet('{X}/scenes_yearly/lb.parquet') s ON s.artist = p.artist AND s.year = p.m // 12
    LEFT JOIN rel ON rel.artist = p.artist AND rel.m = p.m LEFT JOIN fa ON fa.artist = p.artist
    LEFT JOIN read_parquet('{X}/mb_artists_lb.parquet') c ON c.artist = p.artist""").pl()
df = df.with_columns(g=((pl.col("a1") + 1) / (pl.col("a0") + 1)).log(), bin=(pl.col("a0") + 1).log(2).floor().clip(0, 14),
                     mo=(((pl.col("a0") + 1) / (pl.col("ap") + 1)).log(2) / 0.5).floor().clip(-3, 3), scene=pl.col("scene").fill_null(-1), year=pl.col("m") // 12)
df = df.with_columns(r_size=pl.col("g") - pl.col("g").mean().over("m", "bin"), r_mo=pl.col("g") - pl.col("g").mean().over("m", "bin", "mo"))
df = df.with_columns(r_sc=pl.col("r_mo") - pl.col("r_mo").mean().over("year", "scene"))
r = df["r_size"].to_numpy().copy()
facs = ["mo", ["year", "scene"], "age", "relc", "country"]
eff = {i: np.zeros(df.height) for i in range(len(facs))}
for it in range(4):
    for i, f in enumerate(facs):
        part = r + eff[i]
        g = df.select((f if isinstance(f, list) else [f])).with_columns(v=pl.Series(part)).with_columns(mu=pl.col("v").mean().over(f if isinstance(f, list) else [f]))["mu"].to_numpy()
        r = part - g; eff[i] = g
df = df.with_columns(r_all=pl.Series(r))
df = df.with_columns(last=pl.col("m").max().over("user")).filter(pl.col("m") > pl.col("last") - 60)
keep = df.group_by("user").agg(n=pl.len()).filter(pl.col("n") >= 110).select("user")
df = df.join(keep, on="user").sort("user", "m").with_columns(half=pl.int_range(pl.len()).over("user") % 2)
print(f"{keep.height:,} people, {df.height:,} picks; scene known for {(df['scene'] >= 0).mean():.0%}")
sc = {}
for c in ("e", "r_size", "r_mo", "r_sc", "r_all"):
    per = df.group_by("user").agg(s=pl.col(c).sum() / (pl.len() + 20)).sort("user")
    h = df.group_by("user", "half").agg(s=pl.col(c).sum() / (pl.len() + 10)).pivot(on="half", index="user", values="s").drop_nulls()
    r = spearmanr(h["0"], h["1"]).statistic
    sc[c] = per
    agree = spearmanr(per["s"], sc["e"]["s"]).statistic if c != "e" else 1.0
    print(f"{c:7}: split-half {r:.3f} -> full {2 * r / (1 + r):.2f}; agreement with frozen {agree:.3f}")
