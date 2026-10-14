"""Are hidden gems actually good? And what about overhyped music? (2026-10-14, exploratory; ListenBrainz, artists)

Same artists as trends_gems.py (first on LB 2015-2022, >= 10 people who tried them in year 1; kept rate = share of those who kept
listening; year-1 and year-3 listeners). Groups:
  hidden gems: loved (top 10% of their year by kept rate) and never spread (year-3 listeners <= year-1)
  loved and spread: loved and tripled (year-3 >= 3 x year-1)
  overhyped: among the least loved (bottom 30% by kept rate) yet tripled
  ordinary: everyone else
People's taste: rated each year Y on their artist picks up to Y-2 (frozen prescience score e, shrunk sum / (n + 20), >= 20 picks;
good = top fifth, poor = bottom fifth), as the study and pickers.py.
Checks, per group (pooled over artists):
  1. who got into them: of the rated people who got into the artist in its first two years (bet table), the share good / poor pickers;
  2. do good pickers love them: of rated people who tried the artist in year 1 (first play), the share who got into it
     (the study's rule), for good and for poor pickers;
  3. does the love last: of people who got into the artist in year 1 and were still listening to music 24-35 months later, the share
     still playing this artist then.
Writes analysis/out/trends_gems_quality.json; intermediates in data/_tmp/gq (deleted at the end).
"""
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
TMP = ROOT / "data" / "_tmp" / "gq"; TMP.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{TMP}'; SET preserve_insertion_order=false; SET max_temp_directory_size='15GB'")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
bets = f"read_parquet('{X}/bet_outcomes/A_artist_lb.parquet')"
# artists and groups (as trends_gems.py)
con.execute(f"CREATE TABLE birth AS SELECT artist, min(month) AS F FROM {uam} GROUP BY artist HAVING min(month) BETWEEN {2015 * 12} AND {2022 * 12 + 11}")
tk = con.execute(f"""SELECT r.artist, sum(r.t)::BIGINT AS T, sum(r.k)::BIGINT AS K FROM read_parquet('{ROOT}/data/site/pack_artist_rows.parquet') r JOIN birth b USING (artist)
                     WHERE r.month BETWEEN b.F AND b.F + 11 GROUP BY r.artist HAVING sum(r.t) >= 10""").pl()
con.register("tk", tk.select("artist").to_arrow())
con.execute(f"""CREATE TABLE fu AS SELECT u.user, u.artist, min(u.month) AS fm FROM {uam} u SEMI JOIN tk USING (artist) GROUP BY u.user, u.artist""")
L = con.execute(f"""SELECT u.artist, count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F AND b.F + 11) AS L1,
                           count(DISTINCT u.user) FILTER (WHERE u.month BETWEEN b.F + 24 AND b.F + 35) AS L3
                    FROM {uam} u JOIN birth b USING (artist) SEMI JOIN tk USING (artist) GROUP BY u.artist""").pl()
A = (tk.join(L, on="artist").join(con.execute("SELECT artist, F, F // 12 AS year FROM birth").pl(), on="artist")
     .with_columns(rate=pl.col("K") / pl.col("T")).with_columns(q=pl.col("rate").rank("average").over("year") / pl.len().over("year")))
A = A.with_columns(group=pl.when((pl.col("q") > 0.9) & (pl.col("L3") <= pl.col("L1"))).then(pl.lit("hidden gems"))
                   .when((pl.col("q") > 0.9) & (pl.col("L3") >= 3 * pl.col("L1"))).then(pl.lit("loved and spread"))
                   .when((pl.col("q") <= 0.3) & (pl.col("L3") >= 3 * pl.col("L1"))).then(pl.lit("overhyped"))
                   .otherwise(pl.lit("ordinary")))
G = con.execute(f"""SELECT r.artist, sum(r.n_good)::BIGINT AS G FROM read_parquet('{X}/pickers/rate_A_lb.parquet') r JOIN birth b USING (artist)
                    WHERE r.m BETWEEN b.F AND b.F + 23 GROUP BY r.artist""").pl()
A = A.join(G, on="artist", how="left").with_columns(pl.col("G").fill_null(0))
# finer groups for fair comparisons (each artist is in one "group" and at most one "sub")
A = A.with_columns(sub=pl.when((pl.col("group") == "hidden gems") & (pl.col("G") >= 1)).then(pl.lit("gems, a good picker got into them"))
                   .when(pl.col("group") == "hidden gems").then(pl.lit("gems, no good picker"))
                   .when((pl.col("group") == "ordinary") & (pl.col("L3") <= pl.col("L1"))).then(pl.lit("ordinary, never spread"))
                   .otherwise(pl.lit(None)))
con.register("A", A.select("artist", "F", "group", "sub").to_arrow())
print(A.group_by("group").len().sort("group"), flush=True)
new = con.execute(f"""SELECT DISTINCT b.artist FROM read_parquet('{ROOT}/data/site/artist_release.parquet') a JOIN birth b USING (artist)
                      WHERE a.rm BETWEEN b.F - 12 AND b.F""").pl().with_columns(new=pl.lit(1))
A = A.join(new, on="artist", how="left").with_columns(pl.col("new").fill_null(0))
NEWSHARE = {g: float(A.filter(pl.col("group") == g)["new"].mean()) for g in ("hidden gems", "loved and spread", "ordinary", "overhyped")}
print("share that are new artists (a MusicBrainz release in the year before they appeared):", {k: f"{v:.0%}" for k, v in NEWSHARE.items()}, flush=True)
tri = A.filter(pl.col("L3") >= 3 * pl.col("L1"))
TRI = {"tripled": tri.height, "overhyped_share": float((tri["q"] <= 0.3).mean()), "loved_share": float((tri["q"] > 0.9).mean())}
print(f"tripled: {tri.height:,} artists; overhyped (bottom 30% by kept rate) {(tri['q'] <= 0.3).mean():.0%} of them; loved (top 10%) {(tri['q'] > 0.9).mean():.0%}", flush=True)
# people's taste by year (rated on picks up to Y-2)
b = con.execute(f"SELECT user, m // 12 AS year, e FROM {bets}").pl()
R = []
for y in range(2015, 2025):
    past = (b.filter(pl.col("year") <= y - 2).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len())
            .filter(pl.col("n") >= 20).with_columns(q=pl.col("s").rank("average") / pl.len()))
    R.append(past.select("user", taste=pl.when(pl.col("q") > 0.8).then(pl.lit("good")).when(pl.col("q") <= 0.2).then(pl.lit("poor")).otherwise(pl.lit("ordinary")))
             .with_columns(year=pl.lit(y)))
con.register("R", pl.concat(R).to_arrow())
# 1. who got into them (first two years)
who = con.execute(f"""SELECT a."group", a.sub, r.taste, count(*) AS n FROM {bets} p JOIN A a USING (artist) JOIN R r ON r.user = p.user AND r.year = p.m // 12
                      WHERE p.m BETWEEN a.F AND a.F + 23 GROUP BY ALL""").pl()
# 2. tried in year 1 -> got into it
tried = con.execute(f"""SELECT a."group", a.sub, r.taste, count(*) AS tried, count(p.user) AS kept FROM fu JOIN A a USING (artist)
                        JOIN R r ON r.user = fu.user AND r.year = fu.fm // 12
                        LEFT JOIN (SELECT DISTINCT user, artist FROM {bets}) p ON p.user = fu.user AND p.artist = fu.artist
                        WHERE fu.fm BETWEEN a.F AND a.F + 11 GROUP BY ALL""").pl()
# 3. does the love last: fans who got into it in year 1, still listening to music 24-35 months later
for c in range(8):
    con.execute(f"COPY (SELECT DISTINCT user, month FROM {uam} WHERE user % 8 = {c}) TO '{TMP}/act_{c}.parquet' (FORMAT parquet)")
act = f"read_parquet('{TMP}/act_*.parquet')"
last = con.execute(f"""WITH fans AS (SELECT DISTINCT p.user, p.artist, a."group", a.sub, p.m FROM {bets} p JOIN A a USING (artist) WHERE p.m BETWEEN a.F AND a.F + 11),
                            alive AS (SELECT DISTINCT f.* FROM fans f JOIN {act} x ON x.user = f.user AND x.month BETWEEN f.m + 24 AND f.m + 35),
                            still AS (SELECT DISTINCT al.user, al.artist FROM alive al JOIN {uam} u ON u.user = al.user AND u.artist = al.artist
                                      AND u.month BETWEEN al.m + 24 AND al.m + 35)
                       SELECT al."group", al.sub, count(*) AS fans, count(s.user) AS still FROM alive al LEFT JOIN still s USING (user, artist) GROUP BY al."group", al.sub""").pl()
out = []
print("\ngroup | artists | kept rate | of rated fans: good / poor | good pickers who tried: got into it | poor pickers who tried | fans still listening 2 years on")
for col, g in [("group", g) for g in ("hidden gems", "loved and spread", "ordinary", "overhyped")] + \
              [("sub", g) for g in ("gems, a good picker got into them", "gems, no good picker", "ordinary, never spread")]:
    w = who.filter(pl.col(col) == g); tot = w["n"].sum()
    t = tried.filter(pl.col(col) == g)
    kr = lambda taste: float(t.filter(pl.col("taste") == taste)["kept"].sum() / max(t.filter(pl.col("taste") == taste)["tried"].sum(), 1))
    l = last.filter(pl.col(col) == g)
    row = {"group": g, "artists": A.filter(pl.col(col) == g).height, "kept_rate": float(A.filter(pl.col(col) == g)["rate"].mean()),
           "good_share": float(w.filter(pl.col("taste") == "good")["n"].sum() / tot), "poor_share": float(w.filter(pl.col("taste") == "poor")["n"].sum() / tot),
           "good_kept": kr("good"), "poor_kept": kr("poor"), "good_tried": int(t.filter(pl.col("taste") == "good")["tried"].sum()),
           "lasting": float(l["still"].sum() / max(l["fans"].sum(), 1)), "lasting_fans": int(l["fans"].sum()), "new_share": NEWSHARE.get(g)}
    out.append(row)
    print(f"{g:35s} | {row['artists']:>7,} | {row['kept_rate']:.0%} | {row['good_share']:.0%} / {row['poor_share']:.0%} | {row['good_kept']:.0%} ({row['good_tried']:,} tried) | "
          f"{row['poor_kept']:.0%} | {row['lasting']:.0%} ({row['lasting_fans']:,} fans)", flush=True)
(ROOT / "analysis" / "out" / "trends_gems_quality.json").write_text(json.dumps({"groups": out, "tripled": TRI}, indent=1))
shutil.rmtree(TMP, ignore_errors=True)
