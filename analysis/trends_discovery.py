"""Trend 4: do people stop discovering new music? (2026-10-14, exploratory; ListenBrainz, artists)

A person's listening life starts at their first LB listen (S); year t of it = months S + 12t .. S + 12t + 11. Per person and year,
when they listened (>= 500 plays that year):
  new artists they got into: committed adoptions in that year (the study's 4-week rule; bet table, which skips the first 26 weeks);
  discovery share: the share of that year's plays going to artists they first played that same year.
Same people: those who started 2008-2014 and listened (>= 500 plays) in each of years 1-9 of their listening life; curve over t = 1..9
(year 0 is left out: everything is new in someone's first year, and imported histories start there).
Aging or era: people who started 2010-2012 vs 2016-2018, compared at the same years of listening (t = 1..5).
Built in 16 slices of people. Writes analysis/out/trends_discovery.json.
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "disc"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
parts = []
for c in range(16):
    parts.append(con.execute(f"""
        WITH u AS (SELECT * FROM {uam} WHERE user % 16 = {c}),
             s AS (SELECT user, min(month) AS S FROM u GROUP BY user),
             fa AS (SELECT user, artist, min(month) AS fm FROM u GROUP BY user, artist),
             x AS (SELECT u.user, (u.month - s.S) // 12 AS t, u.plays, ((fa.fm - s.S) // 12 = (u.month - s.S) // 12)::INT AS isnew
                   FROM u JOIN s USING (user) JOIN fa USING (user, artist))
        SELECT x.user, s.S, x.t, sum(x.plays)::BIGINT AS plays, sum(x.plays * x.isnew)::BIGINT AS newplays FROM x JOIN s USING (user) GROUP BY ALL""").pl())
    print("slice", c, flush=True)
D = pl.concat(parts)
bets = con.execute(f"SELECT user, m FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet')").pl()
bets = bets.join(D.select("user", "S").unique(), on="user").with_columns(t=(pl.col("m") - pl.col("S")) // 12).group_by("user", "t").agg(found=pl.len())
D = D.join(bets, on=["user", "t"], how="left").with_columns(pl.col("found").fill_null(0), share=pl.col("newplays") / pl.col("plays"), sy=pl.col("S") // 12)
A = D.filter(pl.col("plays") >= 500)
out = {}
# same people
cohort = A.filter(pl.col("sy").is_between(2008, 2014) & pl.col("t").is_between(1, 9)).group_by("user").agg(n=pl.len()).filter(pl.col("n") == 9)["user"]
P = A.filter(pl.col("user").is_in(cohort.to_list()) & pl.col("t").is_between(1, 9))
c = P.group_by("t").agg(people=pl.len(), found=pl.col("found").mean(), found_med=pl.col("found").median(), share=pl.col("share").mean(), plays=pl.col("plays").median()).sort("t")
print(f"\nsame people ({cohort.len():,}, started 2008-2014, listening in each of years 1-9): year of listening | new artists got into (mean, median) | discovery share | plays (median)")
for r in c.iter_rows(named=True):
    print(f"  {r['t']} | {r['found']:5.1f} {r['found_med']:4.0f} | {r['share']:5.1%} | {r['plays']:,.0f}")
out["same_people"] = c.to_dicts()
# aging or era
print("\naging or era: year of listening | started 2010-2012: new artists, discovery share | started 2016-2018: new artists, discovery share")
out["cohorts"] = []
for t in range(1, 6):
    row = {"t": t}
    for lab, (a, b) in (("early", (2010, 2012)), ("late", (2016, 2018))):
        d = A.filter(pl.col("sy").is_between(a, b) & (pl.col("t") == t))
        row.update({f"{lab}_people": d.height, f"{lab}_found": float(d["found"].mean()), f"{lab}_share": float(d["share"].mean())})
    out["cohorts"].append(row)
    print(f"  {t} | {row['early_found']:5.1f}, {row['early_share']:5.1%} ({row['early_people']:,}) | {row['late_found']:5.1f}, {row['late_share']:5.1%} ({row['late_people']:,})")
(ROOT / "analysis" / "out" / "trends_discovery.json").write_text(json.dumps(out, indent=1, default=float))
shutil.rmtree(TMP, ignore_errors=True)
