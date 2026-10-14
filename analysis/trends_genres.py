"""Which genres rose and fell? (2026-10-14, exploratory; ListenBrainz)

Each year 2010-2025: the share of new finds (artists people got into, the study's rule; bet table) in each genre family, among
artists with a MusicBrainz genre tag (analysis/genre.py families; untagged / Other left out). Also the share of plays, as a check.
Same people: those with >= 20 tagged finds in both 2012-2014 and 2022-2024 (they also aged 10 years).
Writes analysis/out/trends_genres.json.
"""
import json
import sys
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
from genre import FAMILIES, family_expr  # noqa: E402

X = ROOT / "data" / "derived"
FAMS = [n for n, _ in FAMILIES]
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
gen = pl.read_parquet(X / "scenes_genre" / "lb.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr()).filter(pl.col("fam") != "Other").select("artist", "fam")
con.register("gen", gen.to_arrow())
finds = con.execute(f"""SELECT p.user, p.m // 12 AS year, g.fam FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet') p JOIN gen g USING (artist)
                        WHERE p.m // 12 BETWEEN 2010 AND 2025""").pl()
plays = con.execute(f"""SELECT u.month // 12 AS year, g.fam, sum(u.plays)::BIGINT AS plays FROM read_parquet('{X}/user_artist_month/lb/*.parquet') u JOIN gen g USING (artist)
                        WHERE u.month // 12 BETWEEN 2010 AND 2025 GROUP BY ALL""").pl()
F = finds.group_by("year", "fam").len().with_columns(share=pl.col("len") / pl.col("len").sum().over("year"))
P = plays.with_columns(share=pl.col("plays") / pl.col("plays").sum().over("year"))
out = {"finds": F.sort("year", "fam").to_dicts(), "plays": P.sort("year", "fam").to_dicts()}
print("share of new finds by genre (tagged artists)\n" + "fam".ljust(26) + " ".join(str(y)[2:].rjust(5) for y in range(2010, 2026)))
for f in FAMS:
    r = {d["year"]: d["share"] for d in F.filter(pl.col("fam") == f).to_dicts()}
    print(f.ljust(26) + " ".join(f"{r.get(y, 0):5.1%}" for y in range(2010, 2026)))
print("\nshare of plays by genre\n" + "fam".ljust(26) + " ".join(str(y)[2:].rjust(5) for y in range(2010, 2026)))
for f in FAMS:
    r = {d["year"]: d["share"] for d in P.filter(pl.col("fam") == f).to_dicts()}
    print(f.ljust(26) + " ".join(f"{r.get(y, 0):5.1%}" for y in range(2010, 2026)))
early = finds.filter(pl.col("year").is_between(2012, 2014)).group_by("user").len().filter(pl.col("len") >= 20)["user"]
late = finds.filter(pl.col("year").is_between(2022, 2024)).group_by("user").len().filter(pl.col("len") >= 20)["user"]
panel = set(early.to_list()) & set(late.to_list())
print(f"\nsame people ({len(panel):,}): share of their new finds, 2012-2014 -> 2022-2024")
sp = []
for f in FAMS:
    row = {"fam": f}
    for lab, (a, b) in (("early", (2012, 2014)), ("late", (2022, 2024))):
        d = finds.filter(pl.col("year").is_between(a, b) & pl.col("user").is_in(list(panel)))
        row[lab] = float((d["fam"] == f).mean())
    sp.append(row)
    print(f"  {f:26s} {row['early']:5.1%} -> {row['late']:5.1%}")
out["same_people"] = sp
(ROOT / "analysis" / "out" / "trends_genres.json").write_text(json.dumps(out, indent=1))
