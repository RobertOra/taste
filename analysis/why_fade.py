"""Why does good taste fade? (2026-10-14, exploratory; ListenBrainz, artists)

People in the top fifth of pickers on their 2011-2015 finds (frozen prescience score e, shrunk sum / (n + 20), >= 20 finds), rated
again on their 2020-2024 finds (same score, >= 20 finds, ranked among everyone rated then). Stayed good = top fifth later;
faded = bottom half later; in between = the rest.
Habits in each period (per person):
  finds a year: new artists they got into per year they listened (>= 500 plays that year)
  brand-new share: share of their finds that were artists first heard on LB within the 12 months before (new music)
  mainstream: median share of active listeners the artist had when they got into it (pen0), as a ratio to everyone's median that year
  plays a year: their listening per active year
  ahead share: share of their finds made before the artist's listeners peaked within the next 24 months (finding things on the way up)
Then: how much of the later score do the changes in habits explain, for these people (linear model, later score on early score
+ changes)? Writes analysis/out/why_fade.json.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "data" / "derived"
con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET threads=6; SET preserve_insertion_order=false")
uam = f"read_parquet('{X}/user_artist_month/lb/*.parquet')"
b = con.execute(f"SELECT user, artist, m, m // 12 AS year, pen0, e FROM read_parquet('{X}/bet_outcomes/A_artist_lb.parquet')").pl()
PER = {"early": (2011, 2015), "late": (2020, 2024)}


def rate(y0, y1):
    d = b.filter(pl.col("year").is_between(y0, y1)).group_by("user").agg(s=pl.col("e").sum() / (pl.len() + 20), n=pl.len()).filter(pl.col("n") >= 20)
    return d.with_columns(q=pl.col("s").rank("average") / pl.len())


E, Lt = rate(*PER["early"]), rate(*PER["late"])
good = E.filter(pl.col("q") > 0.8).join(Lt.select("user", ql="q", sl="s"), on="user")
good = good.with_columns(fate=pl.when(pl.col("ql") > 0.8).then(pl.lit("stayed good")).when(pl.col("ql") <= 0.5).then(pl.lit("faded")).otherwise(pl.lit("in between")))
users = good["user"].to_list()
print(f"top fifth in 2011-2015 and rated again in 2020-2024: {len(users):,}", good.group_by("fate").len().sort("fate").to_dicts(), flush=True)
con.register("gu", pl.DataFrame({"user": users}).to_arrow())
plays = con.execute(f"SELECT user, month // 12 AS year, sum(plays)::BIGINT AS plays FROM {uam} SEMI JOIN gu USING (user) WHERE month // 12 BETWEEN 2011 AND 2024 GROUP BY ALL").pl()
first = con.execute(f"SELECT artist, min(month) AS F FROM {uam} GROUP BY artist").pl()
gb = b.filter(pl.col("user").is_in(users)).join(first, on="artist")
# year medians of pen0 (everyone's finds) for the mainstream ratio
med = b.group_by("year").agg(pm=pl.col("pen0").median())
gb = gb.join(med, on="year").with_columns(new=(pl.col("F") >= pl.col("m") - 12).cast(pl.Float64), main=pl.col("pen0") / pl.col("pm"))
# ahead: was the pick before the artist's peak month within the next 24 months? (monthly listeners of the picked artists)
con.register("pa", gb.select("artist").unique().to_arrow())
al = con.execute(f"SELECT artist, month, count(DISTINCT user) AS L FROM {uam} SEMI JOIN pa USING (artist) WHERE month BETWEEN {2011 * 12} AND {2026 * 12} GROUP BY ALL").pl()
gp = gb.select("user", "artist", "m").join(al, on="artist").filter(pl.col("month").is_between(pl.col("m"), pl.col("m") + 24))
peak = gp.sort(["user", "artist", "m", "L", "month"], descending=[False, False, False, True, False]).group_by("user", "artist", "m", maintain_order=True).first()
gb = gb.join(peak.select("user", "artist", "m", pm_month="month"), on=["user", "artist", "m"], how="left").with_columns(ahead=(pl.col("pm_month") > pl.col("m") + 2).cast(pl.Float64))
habits = []
for lab, (y0, y1) in PER.items():
    act = plays.filter(pl.col("year").is_between(y0, y1) & (pl.col("plays") >= 500)).group_by("user").agg(yrs=pl.len(), plays=pl.col("plays").mean())
    f = gb.filter(pl.col("year").is_between(y0, y1)).group_by("user").agg(n=pl.len(), new=pl.col("new").mean(), main=pl.col("main").median(), ahead=pl.col("ahead").mean())
    h = act.join(f, on="user").with_columns(per_year=pl.col("n") / pl.col("yrs")).select("user", *[pl.col(c).alias(f"{c}_{lab}") for c in ("per_year", "new", "main", "plays", "ahead")])
    habits.append(h)
H = good.join(habits[0], on="user").join(habits[1], on="user")
cols = [("per_year", "finds a year", "{:.0f}"), ("new", "brand-new share", "{:.0%}"), ("main", "mainstream (x everyone's median)", "{:.2f}"),
        ("plays", "plays a year", "{:,.0f}"), ("ahead", "found before the peak", "{:.0%}")]
out = {"people": H.height, "groups": []}
print(f"\n{H.height:,} people with both periods' habits | early -> late (medians; shares as means)")
for fate in ("stayed good", "in between", "faded"):
    g = H.filter(pl.col("fate") == fate); row = {"fate": fate, "people": g.height}
    parts = []
    for c, lab, fm in cols:
        agg = (lambda s: float(s.median())) if c in ("per_year", "main", "plays") else (lambda s: float(s.mean()))
        e_, l_ = agg(g[f"{c}_early"]), agg(g[f"{c}_late"]); row[f"{c}_early"], row[f"{c}_late"] = e_, l_
        parts.append(f"{lab} {fm.format(e_)} -> {fm.format(l_)}")
    out["groups"].append(row)
    print(f"{fate:12s} ({g.height:,}): " + " | ".join(parts), flush=True)
# stuck or moved on? similarity of a person's genre mix between the periods, and how their genres did overall
import sys
sys.path.insert(0, str(ROOT / "analysis"))
from genre import family_expr  # noqa: E402
gen = pl.read_parquet(X / "scenes_genre" / "lb.parquet", columns=["artist", "top_genre"]).with_columns(fam=family_expr()).filter(pl.col("fam") != "Other").select("artist", "fam")
gg = gb.join(gen, on="artist").with_columns(per=pl.when(pl.col("year").is_between(*PER["early"])).then(pl.lit("early")).when(pl.col("year").is_between(*PER["late"])).then(pl.lit("late")))
mix = gg.drop_nulls("per").group_by("user", "per", "fam").len().with_columns(w=pl.col("len") / (pl.col("len") ** 2).sum().over("user", "per").sqrt())
sim = mix.filter(pl.col("per") == "early").join(mix.filter(pl.col("per") == "late"), on=["user", "fam"], suffix="_l").group_by("user").agg(genre_same=(pl.col("w") * pl.col("w_l")).sum())
# the crowd's genre shift: everyone's share of finds by family, early vs late
crowd = b.join(gen, on="artist").with_columns(per=pl.when(pl.col("year").is_between(*PER["early"])).then(pl.lit("early")).when(pl.col("year").is_between(*PER["late"])).then(pl.lit("late"))).drop_nulls("per")
cs = crowd.group_by("per", "fam").len().with_columns(sh=pl.col("len") / pl.col("len").sum().over("per")).pivot(on="per", index="fam", values="sh").with_columns(rise=pl.col("late") / pl.col("early"))
ue = gg.filter(pl.col("per") == "early").join(cs.select("fam", "rise"), on="fam").group_by("user").agg(early_genres_rise=pl.col("rise").mean())
H = H.join(sim, on="user", how="left").join(ue, on="user", how="left")
for fate in ("stayed good", "in between", "faded"):
    g = H.filter(pl.col("fate") == fate)
    print(f"{fate:12s}: genre mix similar to their own earlier mix {g['genre_same'].mean():.2f} | their early genres' growth in the crowd {g['early_genres_rise'].mean():.2f}x", flush=True)
    for row in out["groups"]:
        if row["fate"] == fate:
            row.update(genre_same=float(g["genre_same"].mean()), early_genres_rise=float(g["early_genres_rise"].mean()))
# how much do changes in habits explain the later score?
Z = H.with_columns(genre_same=pl.col("genre_same").fill_null(pl.col("genre_same").mean()), early_genres_rise=pl.col("early_genres_rise").fill_null(1.0)).with_columns(d_per=(pl.col("per_year_late") + 1).log() - (pl.col("per_year_early") + 1).log(), d_new=pl.col("new_late") - pl.col("new_early"),
                   d_main=(pl.col("main_late") + 1e-9).log() - (pl.col("main_early") + 1e-9).log(), d_plays=(pl.col("plays_late") + 1).log() - (pl.col("plays_early") + 1).log(),
                   d_ahead=pl.col("ahead_late") - pl.col("ahead_early")).drop_nulls()
y = Z["sl"].to_numpy()
def r2(cols_):
    Xm = np.column_stack([np.ones(len(y))] + [Z[c].to_numpy() for c in cols_]); beta = np.linalg.lstsq(Xm, y, rcond=None)[0]
    return 1 - ((y - Xm @ beta) ** 2).sum() / ((y - y.mean()) ** 2).sum(), beta
base, _ = r2(["s"])
full, beta = r2(["s", "d_per", "d_new", "d_main", "d_plays"])   # "ahead" left out: it is nearly the score itself
print(f"\nlater score explained: early score alone R2 {base:.3f}; plus changes in habits R2 {full:.3f}")
for c in ("d_per", "d_new", "d_main", "d_plays", "d_ahead", "genre_same", "early_genres_rise"):
    corr = float(np.corrcoef(Z[c].to_numpy(), y)[0, 1]); print(f"  {c}: correlation with later score {corr:+.3f}")
    out[f"corr_{c}"] = corr
out.update({"r2_early": base, "r2_with_changes": full})
(ROOT / "analysis" / "out" / "why_fade.json").write_text(json.dumps(out, indent=1))
