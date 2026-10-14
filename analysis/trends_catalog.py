"""Is new music losing ground to old music? (2026-10-14, exploratory; ListenBrainz)

Each year 2010-2025: the share of plays going to artists by how long ago they first released music (their earliest MusicBrainz
release; artists with a known date only): under 3 years, 3-9, 10-19, 20+ years before that year. Also the share of new finds
(the study's rule) going to artists whose first release was 10+ years earlier.
Same people: those with >= 2,000 dated plays in each of 2014, 2019, 2024 (they also aged 10 years).
Writes analysis/out/trends_catalog.json.
"""
import json
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
con.execute(f"CREATE TABLE fr AS SELECT artist, min(rm) AS rm FROM read_parquet('{ROOT}/data/site/artist_release.parquet') GROUP BY artist")
AGE = "CASE WHEN y * 12 - fr.rm < 36 THEN 'under 3' WHEN y * 12 - fr.rm < 120 THEN '3-9' WHEN y * 12 - fr.rm < 240 THEN '10-19' ELSE '20+' END"
ua = con.execute(f"""WITH u AS (SELECT user, artist, month // 12 AS y, plays FROM read_parquet('{X}/user_artist_month/lb/*.parquet') WHERE month // 12 BETWEEN 2010 AND 2025)
                     SELECT u.user, u.y AS year, {AGE} AS age, sum(u.plays)::BIGINT AS plays FROM u JOIN fr USING (artist) GROUP BY ALL""").pl()
AGES = ["under 3", "3-9", "10-19", "20+"]
P = ua.group_by("year", "age").agg(pl.col("plays").sum()).with_columns(share=pl.col("plays") / pl.col("plays").sum().over("year"))
finds = con.execute(f"""SELECT p.m // 12 AS year, avg(((p.m // 12) * 12 - fr.rm >= 120)::INT) AS old_share, count(*) AS n
                        FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') p JOIN fr USING (artist) WHERE p.m // 12 BETWEEN 2010 AND 2025 GROUP BY 1 ORDER BY 1""").pl()
print("share of plays by years since the artist's first release\nyear | " + " | ".join(AGES) + " | new finds of 10+ year-old artists")
fo = dict(zip(finds["year"].to_list(), finds["old_share"].to_list()))
for y in range(2010, 2026):
    r = {d["age"]: d["share"] for d in P.filter(pl.col("year") == y).to_dicts()}
    print(f"{y} | " + " | ".join(f"{r.get(a, 0):5.1%}" for a in AGES) + f" | {fo.get(y, 0):5.1%}")
tot = ua.group_by("user", "year").agg(pl.col("plays").sum())
panel = None
for y in (2014, 2019, 2024):
    s = set(tot.filter((pl.col("year") == y) & (pl.col("plays") >= 2000))["user"].to_list()); panel = s if panel is None else panel & s
print(f"\nsame people ({len(panel):,}): share of plays by years since first release")
sp = []
for y in (2014, 2019, 2024):
    d = ua.filter((pl.col("year") == y) & pl.col("user").is_in(list(panel))).group_by("age").agg(pl.col("plays").sum())
    d = d.with_columns(share=pl.col("plays") / pl.col("plays").sum())
    r = {x["age"]: x["share"] for x in d.to_dicts()}; sp.append({"year": y, **r})
    print(f"{y} | " + " | ".join(f"{r.get(a, 0):5.1%}" for a in AGES))
(ROOT / "analysis" / "out" / "trends_catalog.json").write_text(json.dumps({"plays": P.sort("year", "age").to_dicts(), "finds_old": finds.to_dicts(), "same_people": sp}, indent=1))
