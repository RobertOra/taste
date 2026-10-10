"""Before touching ListenBrainz: do the adapted scripts reproduce the MLHD+ (explore half) results they produced before?
Backs up the saved explore outputs, reruns each adapted script on explore, compares point estimates (bootstraps may
differ by row order), and restores the original files. Also rebuilds A_artist_main on explore and compares its headline."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "out"
BK = OUT / "_repro_backup"
BK.mkdir(exist_ok=True)
RUNS = [
    ("ladder_explore.json", ["analysis/ladder.py", "--half", "explore"], [["summary", "top1_odds_10x"], ["crowd_summary", "niche_2_vs_0"]]),
    ("headlines_explore.json", ["analysis/headlines.py", "--half", "explore"], [["H3", "ratio_10x"], ["H2", "best_vs_similar_4x"]]),
    ("recency_explore.json", ["analysis/recency.py", "--half", "explore"], [["tests", "P10a", "est"], ["tests", "P10b", "est"], ["tests", "P10c", "est"]]),
    ("bad_taste_explore.json", ["analysis/bad_taste.py", "--half", "explore"], [["tests", "P11a_bottom_flop_vs_middle", "est"], ["tests", "P11b_asymmetry", "est"]]),
    ("genre4_explore.json", ["analysis/genre4.py", "--half", "explore"], [["summary", "avg_this_minus_other"]]),
    ("top_pickers_explore.json", ["analysis/top_pickers.py", "--half", "explore"], [["top1_within_scene", "est"], ["top1_scene_quality", "est"]]),
]


def get(d, p):
    for k in p:
        d = d[k]
    return d


ok = True
for fname, cmd, keys in RUNS:
    src = OUT / fname
    shutil.copy2(src, BK / fname)
    before = json.loads(src.read_text())
    r = subprocess.run([sys.executable, "-I", *cmd], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAILED to run {cmd[0]}: {r.stderr[-400:]}"); ok = False
        shutil.copy2(BK / fname, src); continue
    after = json.loads(src.read_text())
    for k in keys:
        a, b = get(before, k), get(after, k)
        same = abs(a - b) <= 1e-9 * max(1, abs(a))
        ok &= same
        print(f"{'same' if same else 'DIFFERENT':9} {fname} {'/'.join(map(str, k))}: before {a:.6g}, after {b:.6g}")
    shutil.copy2(BK / fname, src)  # keep the original file
# the measure script itself
r = subprocess.run([sys.executable, "-I", "analysis/taste_models.py", "--model", "A", "--unit", "artist", "--cand", "check_A_artist_main", "--perms", "2",
                    "--scene", "yearly200", "--age", "--momentum", "5", "--country", "--release", "--adjust", "additive"], cwd=ROOT, capture_output=True, text=True)
r2 = subprocess.run([sys.executable, "-I", "analysis/evaluate.py", "check_A_artist_main"], cwd=ROOT, capture_output=True, text=True)
a = json.loads((OUT / "cand" / "A_artist_main" / "scorecard.json").read_text())["headline_adjusted_forward"]
b = json.loads((OUT / "cand" / "check_A_artist_main" / "scorecard.json").read_text())["headline_adjusted_forward"]
same = abs(a - b) < 1e-3
ok &= same
print(f"{'same' if same else 'DIFFERENT':9} taste_models A_artist_main headline: before {a:.6g}, after {b:.6g} (tolerance 1e-3, as for the sealed run)")
shutil.rmtree(OUT / "cand" / "check_A_artist_main", ignore_errors=True)
print("REPRODUCES" if ok else "DOES NOT REPRODUCE")
