"""Write-up data for "Music over time" (2026-10-14): analysis/writeup/trends.json from the exploratory trend outputs
(analysis/out/trends_*.json; scripts analysis/trends_*.py). One row per point, keyed "<chart>:<...>".
  fade:<year>      songs by peak year 2010-2022 (all songs, all sizes): share of the whole audience kept and share of the same
                   people still playing, a year after the peak; idx_* = compared with 2010 (1 = the 2010 level)
  singles:<year>   new artists by first year 2010-2022: songs played per listener-month, months with one song, biggest song's share
  niches:<year>    overlap within / across niches 2010-2025 with the 5 samples' range; idx_* vs 2010; fans = two fans of the same
                   artist (trends_fans.py, of their 30 incl. the shared favorite); niches:panel:<year> same people
  sim:<year>       weighted similarity (trends_similarity.py) of random / same-niche / same-favorite pairs at artist, scene, genre level
  change:<year>    similarity with oneself the year before (weighted, artists); change:panel:<year> same people
  disc:<t>         same people, year of listening 1-9: new artists got into, discovery share, plays; disc:cohort:<t> early vs late starters
  gemsq:<group>    fans, good pickers' uptake, lasting love, new-artist share for hidden gems etc.; gemsq:tripled overhyped share
  gems:<pop>:<group>  outcomes for loved / loved by good pickers / ordinary (same start), all and new artists; gems:<pop>:<year> over time
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
O = ROOT / "analysis" / "out"
L = lambda f: json.loads((O / f"trends_{f}.json").read_text())
rows = []
fade = [r for r in L("fade") if r["pop"] == "all songs" and r["band"] == "all sizes" and r["year"] <= 2022]
b = fade[0]
for r in fade:
    rows.append({"key": f"fade:{r['year']}", "year": r["year"], "songs": r["songs"], "whole": r["kept12"], "same": r["still12"],
                 "idx_whole": r["kept12"] / b["kept12"], "idx_same": r["still12"] / b["still12"]})
top = {r["year"]: r["top_median"] for r in L("onehit") if r["pop"] == "new artists" and r["band"] == "all sizes"}
for r in L("onehit_check"):
    rows.append({"key": f"singles:{r['year']}", "year": r["year"], "songs_per": r["songs_per"], "single_share": r["single_share"], "top_share": top.get(r["year"])})
fans = {r["year"]: r for r in L("fans")}
top30 = lambda v: (29 * v + 1) / 30   # fans' overlap of their other 29 artists -> of all 30 (the shared favorite counted), as the niche lines
ni = L("niches"); nb = ni[0]
for r in ni:
    if "year" in r:
        rows.append({"key": f"niches:{r['year']}", "year": r["year"], **{k: r[k] for k in ("within", "within_lo", "within_hi", "across", "across_lo", "across_hi", "all", "all_lo", "all_hi")},
                     **{f"idx_{k}": r[k] / nb[k.split("_")[0]] for k in ("within", "within_lo", "within_hi", "across", "across_lo", "across_hi", "all", "all_lo", "all_hi")},
                     **({k: top30(fans[r["year"]][k]) for k in ("fans", "fans_lo", "fans_hi")} if r["year"] in fans else {}),
                     **({f"idx_{k}": top30(fans[r["year"]][k]) / top30(fans[2010]["fans"]) for k in ("fans", "fans_lo", "fans_hi")} if r["year"] in fans else {})})
    else:
        rows.append({"key": f"niches:panel:{r['panel_year']}", "year": r["panel_year"], "people": r["people"], "within": r["within"], "across": r["across"]})
sim = L("similarity")
base = sim["pairs"][0]
for r in sim["pairs"]:   # weighted similarity, 2010 = 1 per pair type and level
    row = {"key": f"sim:{r['year']}", "year": r["year"]}
    for pt in ("random", "niche", "fans"):
        for lv in ("artists", "scenes", "genres"):
            k = f"{pt}_{lv}"
            row.update({k: r[k], f"idx_{k}": r[k] / base[k], f"idx_{k}_lo": r[f"{k}_lo"] / base[k], f"idx_{k}_hi": r[f"{k}_hi"] / base[k]})
    rows.append(row)
for r in sim["change"]:
    if "year" in r:
        rows.append({"key": f"change:{r['year']}", "year": r["year"], "artists": r["artists"], "artists_t2_4": r["artists_t2_4"]})
    else:
        rows.append({"key": f"change:panel:{r['panel_year']}", "year": r["panel_year"], "people": r["people"], "artists": r["artists"]})
d = L("discovery")
for r in d["same_people"]:
    rows.append({"key": f"disc:{r['t']}", "t": r["t"], "people": r["people"], "found": r["found"], "share": r["share"], "plays": r["plays"]})
for r in d["cohorts"]:
    rows.append({"key": f"disc:cohort:{r['t']}", **r})
GROUPS = {"loved": "loved", "loved by good pickers": "loved_good", "loved by 2+ good pickers": "loved_good2", "top 1% loved": "top1"}
seg = lambda never, grew, ten: {"never": never, "some": 1 - never - grew, "grew3": grew - ten, "grew10": ten, "tripled": grew}
for r in L("gems"):
    pop = "new" if r["pop"] == "new artists" else "all"
    if r["year"] is None and r["group"] in GROUPS:
        g = GROUPS[r["group"]]
        rows.append({"key": f"gems:{pop}:{g}", "pop": pop, "group": g, "n": r["n"], **seg(r["never"], r["grew"], r["ten"])})
        if g == "loved":   # ordinary artists matched to the loved ones' first year and starting size
            rows.append({"key": f"gems:{pop}:ordinary", "pop": pop, "group": "ordinary", **seg(r["never_ord"], r["grew_ord"], r["ten_ord"])})
    elif r["year"] is not None:
        rows.append({"key": f"gems:{pop}:{r['year']}", "pop": pop, "year": r["year"], "never": r["never"], "never_ord": r["never_ord"]})
gq = L("gems_quality")
for r in gq["groups"]:   # are hidden gems good (trends_gems_quality.py)
    rows.append({"key": f"gemsq:{r['group']}", **{k: v for k, v in r.items() if k != "group"}})
rows.append({"key": "gemsq:tripled", **gq["tripled"]})
(ROOT / "analysis" / "writeup" / "trends.json").write_text(json.dumps(rows, indent=1))
print(len(rows), "rows")
