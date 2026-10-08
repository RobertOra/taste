"""Print MLHD+ ingest progress: per-archive position, overall %, throughput, ETA, disk use."""

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ARCHIVES = [f"mlhdplus-{kind}-{c}.tar" for kind in ("partial", "complete") for c in "0123456789abcdef"]


def approx_size(name):  # until an archive's first checkpoint records its true size
    return (2 if "-partial-" in name else 15.2) * 2**30


def main(out):
    states = {p.name.removesuffix(".json"): json.loads(p.read_text()) for p in sorted((out / "_state").glob("*.json"))}
    total = done_bytes = 0
    for name in ARCHIVES:
        s = states.get(name)
        size = (s or {}).get("size") or approx_size(name)
        total += size
        if s is None:
            continue
        done_bytes += size if s["done"] else s["pos"]
        flag = "done" if s["done"] else f"{100 * s['pos'] / size:5.1f}%"
        print(f"  {name:28s} {flag:>6s}  users={s['users']:>7,d}  listens={s['listens']:>13,d}")
    print(f"overall: {done_bytes / 2**30:.1f} / {total / 2**30:.0f} GiB ({100 * done_bytes / total:.1f}%)")

    # Throughput from checkpoints logged in the last 30 minutes.
    log = out / "_logs" / "ingest.log"
    if log.exists():
        lines = log.read_text().splitlines()[-2000:]
        cutoff = time.time() - 1800
        pts = {}
        for line in lines:
            m = re.match(r"(\S+ \S+),\d+ \d+ INFO (\S+): checkpoint @(\d+)/", line)
            if m:
                t = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").timestamp()
                if t >= cutoff:
                    pts.setdefault(m[2], []).append((t, int(m[3])))
        rate = sum((p[-1][1] - p[0][1]) / max(p[-1][0] - p[0][0], 1) for p in pts.values() if len(p) > 1)
        if rate > 0:
            eta_h = (total - done_bytes) / rate / 3600
            print(f"throughput (last 30 min): {rate / 2**20:.1f} MB/s, ETA ~{eta_h:.1f} h")
        warnings = [l for l in lines if " WARNING " in l or " ERROR " in l]
        if warnings:
            print(f"recent warnings/errors ({len(warnings)}), last: {warnings[-1][:200]}")
    du = subprocess.run(["du", "-sh", str(out)], capture_output=True, text=True).stdout.split("\t")[0]
    print(f"disk used by output: {du}")
    if (out / "_state" / "ALL_DONE").exists():
        print("ALL DONE")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
