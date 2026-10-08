"""Judge scene definitions on criteria unrelated to taste results (explore half).

1. Relatedness lift: for consecutive committed bets by the same user within the same calendar year,
   P(same scene) / P(same scene by chance given scene sizes in that year's bets). Higher = real relatedness.
   Note: the all-years version was fitted on the same listening it is evaluated on (in-sample), so its
   lift is optimistic; the yearly version is out-of-sample by construction.
2. Timing leak: share of variance in artists' peak month (2005-2012) explained by scene, within each year,
   averaged over years. Lower = less leakage of when artists got popular.
3. Genre coherence: normalised mutual information between scene and MusicBrainz top genre (tagged artists).
"""

from pathlib import Path

import duckdb
import polars as pl
from sklearn.metrics import normalized_mutual_info_score

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6")
YEAR = "year(make_timestamp(w4::BIGINT * 604800000000))"

con.execute(f"""CREATE TABLE bets AS
    WITH s AS (SELECT user, min(first_week) AS start FROM read_parquet('{X}/bets/explore/*.parquet') GROUP BY user)
    SELECT b.user, b.artist, b.w4, {YEAR} AS year FROM read_parquet('{X}/bets/explore/*.parquet') b JOIN s USING (user)
    WHERE b.w4 IS NOT NULL AND b.w4 - b.first_week < 26 AND b.first_week >= s.start + 26 AND {YEAR} BETWEEN 2006 AND 2012""")
con.execute("""CREATE TABLE pairs AS SELECT year, artist, nxt FROM (
    SELECT year, artist, lead(artist) OVER (PARTITION BY user ORDER BY w4, artist) AS nxt,
           lead(year) OVER (PARTITION BY user ORDER BY w4, artist) AS nyear FROM bets) WHERE nyear = year""")
con.execute(f"""CREATE TABLE peak AS
    WITH p AS (SELECT l.artist, l.month, l.l0 / p.n_panel AS pen FROM read_parquet('{X}/market/explore/listeners_h12.parquet') l
               JOIN read_parquet('{X}/market/explore/panel.parquet') p ON p.month = l.month AND p.h = 12)
    SELECT artist, arg_max(month, pen) AS peak FROM p GROUP BY artist""")

defs = {
    "yearly co-listening": (f"read_parquet('{X}/scenes_yearly/explore.parquet')", True, [50, 200, 1000]),
    "all-years co-listening": (f"read_parquet('{X}/scenes/explore.parquet')", False, [50, 200, 1000]),
    "genre (tagged only)": (f"read_parquet('{X}/scenes_genre/all.parquet')", False, [50, 200]),
}
mb = pl.read_parquet(X / "mb_artists.parquet").filter(pl.col("genres").list.len() > 0).select(
    "artist", top=pl.col("genres").list.first().struct.field("name"))
con.register("mb", mb.to_arrow())
rows = []
for name, (src, yearly, ks) in defs.items():
    for k in ks:
        col = f"scene_{k}"
        sc = (f"(SELECT artist, year, {col} AS s FROM {src})" if yearly else
              f"(SELECT a.artist, y.year, a.{col} AS s FROM {src} a CROSS JOIN range(2006, 2013) y(year))")
        lift, cover = con.execute(f"""
            WITH p AS (SELECT p.year, a.s AS s1, b.s AS s2 FROM pairs p JOIN {sc} a ON a.artist = p.artist AND a.year = p.year
                       JOIN {sc} b ON b.artist = p.nxt AND b.year = p.year),
                 cnt AS (SELECT b.year, x.s, count(*) AS n FROM bets b JOIN {sc} x ON x.artist = b.artist AND x.year = b.year
                         GROUP BY b.year, x.s),
                 share AS (SELECT year, s, n / sum(n) OVER (PARTITION BY year) AS q FROM cnt),
                 chance AS (SELECT year, sum(q * q) AS c FROM share GROUP BY year),
                 obs AS (SELECT year, avg((s1 = s2)::INT) AS o, count(*) AS n FROM p GROUP BY year)
            SELECT sum(o.o / c.c * o.n) / sum(o.n), sum(o.n) / (SELECT count(*) FROM pairs) FROM obs o JOIN chance c USING (year)
        """).fetchone()
        eta = con.execute(f"""
            WITH d AS (SELECT x.year, x.s, pk.peak FROM {sc} x JOIN peak pk USING (artist)
                       WHERE x.artist IN (SELECT artist FROM read_parquet('{X}/scenes/explore.parquet') WHERE core)),
                 tot AS (SELECT year, var_pop(peak) * count(*) AS t FROM d GROUP BY year),
                 wit AS (SELECT year, sum(v) AS w FROM (SELECT year, s, var_pop(peak) * count(*) AS v FROM d GROUP BY year, s) GROUP BY year)
            SELECT avg(1 - w / t) FROM tot JOIN wit USING (year)""").fetchone()[0]
        g = con.sql(f"SELECT x.s, mb.top FROM {sc} x JOIN mb USING (artist) WHERE x.year = 2010").pl()
        nmi = normalized_mutual_info_score(g["top"].to_numpy(), g["s"].to_numpy())
        rows.append((name, k, round(lift, 2), round(cover, 3), round(eta, 3), round(nmi, 3)))
        print(rows[-1], flush=True)
print(pl.DataFrame(rows, schema=["definition", "k", "relatedness_lift", "pairs_covered", "timing_leak_eta2",
                                 "genre_nmi"], orient="row").to_pandas().to_string(index=False))
