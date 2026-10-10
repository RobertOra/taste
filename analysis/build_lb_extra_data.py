"""Write-up data for the ListenBrainz exploratory results: decade.json, samepeople.json, today.json (careers.json is
written by analysis/lb_careers.py). Sources: analysis/out/lb_longrun.json, lb_today.json."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
W = Path(__file__).resolve().parent / "writeup"
lr = json.loads((OUT / "lb_longrun.json").read_text())

dec = [{"key": str(r["years_later"]), **{k: r[k] for k in ("year", "years_later", "people", "top_in_top", "top_in_top_lo", "top_in_top_hi",
        "bottom_in_bottom", "bottom_in_bottom_lo", "bottom_in_bottom_hi", "top_n", "bottom_n", "gap", "gap_lo", "gap_hi")}} for r in lr["decade"]["curve"]]
(W / "decade.json").write_text(json.dumps(dec, indent=1))

name = {("everyone", "early"): "Everyone", ("everyone", "recent"): "Everyone", ("panel", "early"): "Same people", ("panel", "recent"): "Same people",
        ("newcomers", "early"): "Seen only before 2021", ("newcomers", "recent"): "Joined after 2014"}
sp = []
for r in lr["same_people"]["rows"]:
    sp.append({"key": f"{r['group']}:{r['period']}", "group": name[(r["group"], r["period"])], "period": r["period"],
               **{k: r[k] for k in ("gap", "gap_lo", "gap_hi", "top10", "top10_lo", "top10_hi", "best_people", "top10_people")}})
(W / "samepeople.json").write_text(json.dumps(sp, indent=1))

td = json.loads((OUT / "lb_today.json").read_text())["D_song"]
rows = []
for plat, k in (("Last.fm (2005–2013)", "mlhd_hidden"), ("ListenBrainz (2019–2025)", "lb_recent")):
    for r in td[k]["rows"]:
        rows.append({"key": f"{k}:{r['picks']}", "platform": plat, "src": k, **r})
(W / "today.json").write_text(json.dumps(rows, indent=1))
print(len(dec), len(sp), len(rows))
