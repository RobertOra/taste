"""Write-up data for "Music over time" (2026-10-14): analysis/writeup/trends.json from the exploratory trend outputs
(analysis/out/trends_*.json; scripts analysis/trends_*.py). One row per point, keyed "<chart>:<...>".
  fade:<year>      songs by peak year 2010-2022 (all songs, all sizes): share of the whole audience kept and share of the same
                   people still playing, a year after the peak; idx_* = compared with 2010 (1 = the 2010 level)
  singles:<year>   new artists by first year 2010-2022: songs played per listener-month, months with one song, biggest song's share
  niches:<year>    overlap within / across niches 2010-2025 with the 5 samples' range; idx_* vs 2010; niches:panel:<year> same people
  disc:<t>         same people, year of listening 1-9: new artists got into, discovery share, plays; disc:cohort:<t> early vs late starters
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
ni = L("niches"); nb = ni[0]
for r in ni:
    if "year" in r:
        rows.append({"key": f"niches:{r['year']}", "year": r["year"], **{k: r[k] for k in ("within", "within_lo", "within_hi", "across", "across_lo", "across_hi")},
                     **{f"idx_{k}": r[k] / nb[k.split("_")[0]] for k in ("within", "within_lo", "within_hi", "across", "across_lo", "across_hi")}})
    else:
        rows.append({"key": f"niches:panel:{r['panel_year']}", "year": r["panel_year"], "people": r["people"], "within": r["within"], "across": r["across"]})
d = L("discovery")
for r in d["same_people"]:
    rows.append({"key": f"disc:{r['t']}", "t": r["t"], "people": r["people"], "found": r["found"], "share": r["share"], "plays": r["plays"]})
for r in d["cohorts"]:
    rows.append({"key": f"disc:cohort:{r['t']}", **r})
for r in L("gems"):
    pop = "new" if r["pop"] == "new artists" else "all"
    if r["year"] is None:
        g = "loved_good" if r["group"] == "loved by good pickers" else "loved"
        rows.append({"key": f"gems:{pop}:{g}", "pop": pop, "group": g, "n": r["n"], "never": r["never"], "grew3": r["grew"], "some": 1 - r["never"] - r["grew"]})
        if g == "loved":
            rows.append({"key": f"gems:{pop}:ordinary", "pop": pop, "group": "ordinary", "never": r["never_ord"], "grew3": r["grew_ord"],
                         "some": 1 - r["never_ord"] - r["grew_ord"]})
    else:
        rows.append({"key": f"gems:{pop}:{r['year']}", "pop": pop, "year": r["year"], "never": r["never"], "never_ord": r["never_ord"]})
(ROOT / "analysis" / "writeup" / "trends.json").write_text(json.dumps(rows, indent=1))
print(len(rows), "rows")
