"""Python mirror of site/static/engine.js (same rules, same data files: site/static/data/meta.json and s/*.bin). Used to
check the browser engine (node site/static/test_node.mjs) and to score ListenBrainz users for validation.
    score(plays, kind) with plays: list of (week, an, display name[, name_hash]) after the same exclusions as the engine."""
import json
import math
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score as S  # noqa: E402  (name_hash, true_range, read_history)

DATA = ROOT / "site" / "static" / "data"
META = json.loads((DATA / "meta.json").read_text())
BASE = {(m, b): (g, ten, up3) for m, b, g, ten, up3 in META["baseline"]}
EFF = {name: {"|".join(str(v) for v in r[:-1]): r[-1] for r in rows} for name, rows in META["effects"].items()}
_shards = {}


def month_of_week(w):
    d = datetime.fromtimestamp(w * 604800 + 302400, tz=timezone.utc)
    return d.year * 12 + d.month - 1


def varint(b, o):
    x = s = 0
    while True:
        c = b[o[0]]; o[0] += 1
        x |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            return x


def shard(i):
    if i in _shards:
        return _shards[i]
    p = DATA / "s" / f"{i:04x}.bin"
    if not p.exists():
        _shards[i] = ({}, []); return _shards[i]
    b = p.read_bytes()
    nn, na = struct.unpack_from("<HH", b, 0)
    names = {}; pos = 4
    for _ in range(nn):
        h, ai = struct.unpack_from("<qH", b, pos); names[h] = ai; pos += 10
    arts = []; o = [pos]
    for _ in range(na):
        gid, ci, fe = struct.unpack_from("<IHH", b, o[0]); o[0] += 8
        adopt = {}; prev = META["y0"] - 12
        for _ in range(varint(b, o)):
            prev += varint(b, o); adopt[prev] = varint(b, o)
        scene = {}
        for _ in range(varint(b, o)):
            y, s_ = b[o[0]] + 2000, b[o[0] + 1]; o[0] += 2; scene[y] = -1 if s_ == 255 else s_
        anyrel = b[o[0]] == 1; o[0] += 1
        rel = []; prev = META["y0"] - 12
        for _ in range(varint(b, o)):
            prev += varint(b, o); rel.append(prev)
        arts.append({"id": gid, "country": META["countries"][ci], "fm": fe - 1000 + 2000 * 12, "adopt": adopt, "scene": scene, "anyrel": anyrel, "rel": rel})
    _shards[i] = (names, arts)
    return _shards[i]


def find_picks(plays):
    start = min(p[0] for p in plays)
    by = {}
    for p in plays:
        a = by.setdefault(p[1], {"name": p[2], "h": p[3] if len(p) > 3 else None, "weeks": {}})
        a["weeks"][p[0]] = a["weeks"].get(p[0], 0) + (p[4] if len(p) > 4 else 1)
    out = []
    for an, a in by.items():
        ws = sorted(a["weeks"])
        if len(ws) < 4:
            continue
        fw, w4 = ws[0], ws[3]
        if w4 - fw >= 26 or fw < start + 26:
            continue
        out.append({"an": an, "name": a["name"], "h": a["h"], "first_week": fw, "m": month_of_week(w4), "plays26": sum(n for w, n in a["weeks"].items() if w < fw + 26)})
    return out


def features(art, m):
    s = lambda lo, hi: sum(art["adopt"].get(t, 0) for t in range(lo, hi + 1))
    a0, a1, ap = s(m - 5, m), s(m + 7, m + 12), s(m - 11, m - 6)
    d = m - art["fm"]
    age = 9 if art["fm"] <= 2005 * 12 else 0 if d < 3 else 1 if d < 6 else 2 if d < 12 else 3 if d < 24 else 4
    relc = 4 if not art["anyrel"] else 2 * int(any(m < r <= m + 3 for r in art["rel"])) + int(any(m - 3 <= r <= m for r in art["rel"]))
    return {"a0": a0, "a1": a1, "ap": ap, "age": age, "relc": relc, "scene": art["scene"].get(m // 12, -1), "country": art["country"]}


def excess(f, m):
    g = math.log((f["a1"] + 1) / (f["a0"] + 1))
    b = min(14, max(0, math.floor(math.log(f["a0"] + 1) / math.log(2))))
    mo = min(3, max(-3, math.floor((math.log((f["a0"] + 1) / (f["ap"] + 1)) / math.log(2)) / 0.5)))
    if (m, b) not in BASE:
        return None
    gm, ten, up3 = BASE[(m, b)]
    e = EFF["mo"].get(str(mo), 0) + EFF["year_scene"].get(f"{m // 12}|{f['scene']}", 0) + EFF["age"].get(str(f["age"]), 0) + \
        EFF["relc"].get(str(f["relc"]), 0) + EFF["country"].get(f["country"], 0)
    return {"g": g, "g_mean": gm, "up3_rate": up3, "excess": g - gm - e, "up3": g >= math.log(3)}


def score(plays, exclude_self=False):
    """plays: (week, an, name[, hash[, count]]). exclude_self: tests on ListenBrainz users (remove their own first listen from a0)."""
    out = {}
    last_j = META["last_month"] - 12
    picks = find_picks(plays)
    judged = [p for p in picks if META["y0"] <= p["m"] <= last_j]
    for p in judged:
        if p["h"] is None:
            p["h"] = S.name_hash(p["an"])
        sh = p["h"] & ((1 << META["shard_bits"]) - 1)
        names, arts = shard(sh)
        ai = names.get(p["h"])
        p["art"] = arts[ai] if ai is not None else None
        p["key"] = p["art"]["id"] if p["art"] else None
    seen = {}
    for p in sorted([p for p in judged if p["art"]], key=lambda p: (p["m"], p["an"])):
        seen.setdefault(p["key"], p)
    matched = list(seen.values())
    out["matched_share"] = sum(1 for p in judged if p["art"]) / len(judged) if judged else 0
    for p in matched:
        f = features(p["art"], p["m"])
        if exclude_self and p["m"] - 5 <= month_of_week(p["first_week"]) <= p["m"]:
            f["a0"] = max(f["a0"] - 1, 0)
        p.update(f); p.update(excess(f, p["m"]) or {"excess": None})
    sc = [p for p in matched if p.get("excess") is not None]
    if not sc:
        out["picks"] = 0; return out
    last = max(p["m"] for p in sc)
    win = [p for p in sc if p["m"] > last - 12 * META["window_years"]]
    n = len(win)
    out.update(picks=n, too_recent=sum(1 for p in picks if p["m"] > last_j))
    if n >= META["min_picks"]:
        import bisect
        s = sum(p["excess"] for p in win) / (n + META["shrink"])
        pct = bisect.bisect_left(META["scores"], s) / len(META["scores"])
        rel = n * META["per_pick"] / (1 + (n - 1) * META["per_pick"])
        lo, hi = S.true_range(rel, pct)
        out.update(score=s, percentile=round(100 * pct), range=[round(lo), round(hi)])
        out["took_off"] = {"yours": sum(p["up3"] for p in win), "expected": round(sum(p["up3_rate"] for p in win))}
        out["best"] = [p["name"] for p in sorted(win, key=lambda p: -p["excess"])[:8]]
    return out


def plays_from_files(paths):
    df, kind = S.read_history(paths)
    rows = []
    for ts, artist, track in df.iter_rows():
        an = artist.strip().lower()
        if an in S.EXCLUDE_ARTISTS:
            continue
        rows.append((int(ts // 604800), an, artist))
    return rows, kind


if __name__ == "__main__":
    rows, kind = plays_from_files(sys.argv[1:])
    print(json.dumps(score(rows), default=str, indent=1))
