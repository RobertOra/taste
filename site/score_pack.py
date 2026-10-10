"""Python mirror of site/static/engine.js for the packed data (site/static/data/meta.json, index.bin, p/NN.bin), used to check
the browser engine and to score ListenBrainz users for validation.
    plays: list of dicts {week, ts, an, name, tn, track[, ah, sh]} (ah/sh: precomputed artist / song name hashes)"""
import bisect
import json
import zlib
import math
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score as S  # noqa: E402  (name_hash, true_range, read_history, EXCLUDE_ARTISTS)

DATA = ROOT / "site" / "static" / "data"
META = json.loads((DATA / "meta.json").read_text())


def month_of_week(w):
    d = datetime.fromtimestamp(w * 604800 + 302400, tz=timezone.utc)
    return d.year * 12 + d.month - 1


class Pack:
    def __init__(self):
        b = (DATA / "index.bin").read_bytes()
        magic, n, nf = struct.unpack_from("<IIH", b, 0); p = 10
        self.compressed = magic == 0x54535432
        sizes = struct.unpack_from(f"<{nf}I", b, p); p += 4 * nf
        lens = struct.unpack_from(f"<{n}I", b, p)
        self.S, self.loc, f, off = n, [], 0, 0
        for ln in lens:
            if ln and off + ln > sizes[f]:
                f += 1; off = 0
            self.loc.append((f, off, ln)); off += ln
        self.files, self.cache = {}, {}

    def shard_of(self, h):
        return h & (self.S - 1)

    def shard(self, s):
        if s in self.cache:
            return self.cache[s]
        f, off, ln = self.loc[s]
        if not ln:
            self.cache[s] = ({}, [], {}, []); return self.cache[s]
        if f not in self.files:
            self.files[f] = (DATA / "p" / f"{f:02d}.bin").read_bytes()
        raw = self.files[f][off:off + ln]
        self.cache[s] = decode(zlib.decompress(raw, -15) if self.compressed else raw)
        return self.cache[s]

    def artist(self, h):
        an, ar, _, _ = self.shard(self.shard_of(h)); i = an.get(h)
        return None if i is None else ar[i]

    def song(self, h):
        _, _, sn, sr = self.shard(self.shard_of(h)); i = sn.get(h)
        return None if i is None else sr[i]


def varint(b, o):
    x = s = 0
    while True:
        c = b[o[0]]; o[0] += 1; x |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            return x


def rows(b, o):
    n = varint(b, o); prev = META["m0"] - 1; out = []
    for _ in range(n):
        v = varint(b, o); code = v & 3; prev += v >> 2
        if code == 0:
            out.append((prev, 1, 0, 0))
        elif code == 1:
            out.append((prev, 1, 1, 0))
        elif code == 2:
            out.append((prev, 1, 1, 1))
        else:
            a = varint(b, o); t = varint(b, o); k = varint(b, o); out.append((prev, a, t, k))
    return out


def decode(b):
    nan, nar, nsn, nsr = struct.unpack_from("<HHHH", b, 0); p = 8
    an = {}
    for _ in range(nan):
        h, i = struct.unpack_from("<qH", b, p); an[h] = i; p += 10
    o = [p]; ar = []
    for _ in range(nar):
        gid, ci, fe, fam, anyrel = struct.unpack_from("<IHHBB", b, o[0]); o[0] += 10
        scene = {}
        for _ in range(varint(b, o)):
            scene[b[o[0]] + 2000] = -1 if b[o[0] + 1] == 255 else b[o[0] + 1]; o[0] += 2
        rel = []; prev = META["m0"] - 12
        for _ in range(varint(b, o)):
            prev += varint(b, o); rel.append(prev)
        ar.append({"id": gid, "country": META["countries"][ci], "fm": fe - 1000 + 24000, "fam": fam, "anyrel": anyrel == 1, "scene": scene, "rel": rel, "rows": rows(b, o)})
    p = o[0]; sn = {}
    for _ in range(nsn):
        h, i = struct.unpack_from("<qH", b, p); sn[h] = i; p += 10
    o = [p]; sr = []
    for _ in range(nsr):
        gid, fe = struct.unpack_from("<IH", b, o[0]); o[0] += 6
        sr.append({"id": gid, "fm": fe - 1000 + 24000, "rows": rows(b, o)})
    return an, ar, sn, sr


def segment_starts(weeks):
    ws = sorted(set(weeks)); return [w for i, w in enumerate(ws) if i == 0 or w - ws[i - 1] >= 26]


def in_warmup(starts, fw):
    i = bisect.bisect_right(starts, fw) - 1
    return i >= 0 and fw < starts[i] + 26


def find_picks(plays, key_of, starts=None):
    starts = starts if starts is not None else segment_starts(p["week"] for p in plays); by = {}
    for p in plays:
        k = key_of(p)
        a = by.get(k)
        if a is None:
            a = by[k] = {"p": p, "weeks": {}}
        a["weeks"][p["week"]] = a["weeks"].get(p["week"], 0) + p.get("n", 1)
    out = []
    for k, a in by.items():
        ws = sorted(a["weeks"]); fw = ws[0]
        if in_warmup(starts, fw) or len(ws) < 4 or ws[3] - fw >= 26:
            continue
        out.append({"key": k, "an": a["p"]["an"], "name": a["p"]["name"], "ah": a["p"].get("ah"), "sh": a["p"].get("sh") if "sh" in a["p"] else None,
                    "first_week": fw, "m": month_of_week(ws[3]), "w": sum(n for w, n in a["weeks"].items() if w < fw + 26)})
    return out


def feats(unit, item, art, m):
    a0 = a1 = ap = tl = kl = tp = kp = 0
    for mo, a, t, k in item["rows"]:
        if mo > m + 12:
            break
        if mo <= m:
            tp += t; kp += k
            if mo >= m - 5:
                a0 += a
            elif m - 11 <= mo <= m - 6:
                ap += a
        else:
            tl += t; kl += k
            if mo >= m + 7:
                a1 += a
    d = m - item["fm"]
    if unit == "artist":
        age = 9 if item["fm"] <= 2005 * 12 else 0 if d < 3 else 1 if d < 6 else 2 if d < 12 else 3 if d < 24 else 4
    else:
        age = 9 if item["fm"] <= 2005 * 12 else d if d <= 2 else 3 if d < 6 else 4 if d < 12 else 5 if d < 24 else 6
    relc = 2 * int(any(m < r <= m + 3 for r in art["rel"])) + int(any(m - 3 <= r <= m for r in art["rel"])) if art["anyrel"] else 4
    return dict(a0=a0, a1=a1, ap=ap, tl=tl, kl=kl, tp=tp, kp=kp, age=age, scene=art["scene"].get(m // 12, -1), relc=relc, country=art["country"])


_LK = {}


def excess(M, key, f, m):
    if key not in _LK:
        _LK[key] = ({(r[0], r[1]): r for r in M["baseline"]}, {n: {"|".join(str(v) for v in r[:-1]): r[-1] for r in rows_} for n, rows_ in M["effects"].items()},
                    {r[0]: r[1:] for r in M.get("xb_cuts", [])})
    base, eff, cuts = _LK[key]
    b = min(14, max(0, math.floor(math.log(f["a0"] + 1) / math.log(2))))
    mo = min(3, max(-3, math.floor((math.log((f["a0"] + 1) / (f["ap"] + 1)) / math.log(2)) / 0.5)))
    br = base.get((m, b))
    if br is None:
        return None
    g = math.log((f["a1"] + 1) / (f["a0"] + 1))
    keys = {"mo": str(mo), "year_scene": f"{m // 12}|{f['scene']}", "age": str(f["age"]), "relc": str(f["relc"]), "country": f["country"]}
    if M["measure"] == "A":
        y = g
    else:
        y = (f["kl"] + 2 * M["p0"]) / (f["tl"] + 2)
        cp = (f["kp"] + 2 * M["p0"]) / (f["tp"] + 2); q = cuts.get(m)
        if q is None:
            return None
        keys["xb"] = str(sum(cp > x for x in q))
    e = sum(eff[n].get(k, 0) for n, k in keys.items() if n in eff)
    return y - br[2] - e


def score_measure(key, picks, exclude_self=False):
    M = META["measures"][key]; unit = M["unit"]; sc = []
    for p in picks:
        f = feats(unit, p["item"], p["art"], p["m"])
        if exclude_self:
            fmo = month_of_week(p["first_week"])
            if p["m"] - 5 <= fmo <= p["m"]:
                f["a0"] = max(f["a0"] - 1, 0)
            if fmo >= META["m0"]:
                f["tp"] = max(f["tp"] - 1, 0); f["kp"] = max(f["kp"] - 1, 0)
        x = excess(M, key, f, p["m"])
        if x is not None:
            sc.append({**p, "excess": x})
    if unit == "song":
        g = {}
        for p in sc:
            g.setdefault((p["art"]["id"], p["m"]), []).append(p)
        sc = [{"m": ps[0]["m"], "excess": sum(p["excess"] * p["w"] for p in ps) / sum(p["w"] for p in ps)} for ps in g.values()]
    if not sc:
        return {"picks": 0}
    last = max(p["m"] for p in sc)
    win = [p for p in sc if p["m"] > last - 12 * META["window_years"]] if META.get("window_years") else sc
    n = len(win); r = {"picks": n}
    if n >= META["min_picks"]:
        s = sum(p["excess"] for p in win) / (n + META["shrink"])
        pct = bisect.bisect_left(M["scores"], s) / len(M["scores"]); rel = n * M["per_pick"] / (1 + (n - 1) * M["per_pick"])
        lo, hi = S.true_range(rel, pct)
        r.update(score=s, percentile=round(100 * pct), range=[round(lo), round(hi)])
    return r


def score(plays, exclude_self=False, pack=None):
    pack = pack or Pack(); lj = META["last_month"] - 12
    starts = segment_starts(p["week"] for p in plays)
    ap = [p for p in find_picks(plays, lambda p: p["an"], starts) if META["y0"] <= p["m"] <= lj]
    sp = [p for p in find_picks(plays, lambda p: p["an"] + "\t" + p["tn"], starts) if p["key"].split("\t", 1)[1] and META["y0"] <= p["m"] <= lj]
    for p in ap:
        p["ah"] = p["ah"] if p["ah"] is not None else S.name_hash(p["an"]); p["art"] = pack.artist(p["ah"]); p["item"] = p["art"]
    for p in sp:
        p["ah"] = p["ah"] if p["ah"] is not None else S.name_hash(p["an"]); p["sh"] = p["sh"] if p["sh"] is not None else S.name_hash(p["key"])
        p["art"] = pack.artist(p["ah"]); p["item"] = pack.song(p["sh"]) if p["art"] else None
    def dedup(ps):
        seen = {}
        for p in sorted([p for p in ps if p["item"]], key=lambda p: (p["m"], p["key"])):
            seen.setdefault(p["item"]["id"], p)
        return list(seen.values())
    mA, mS = dedup(ap), dedup(sp)
    return {k: score_measure(k, ps, exclude_self) for k, ps in (("song_A", mS), ("song_D", mS), ("artist_A", mA), ("artist_D", mA))}


def plays_from_files(paths):
    df, kind = S.read_history(paths)
    out = []
    for ts, artist, track in df.iter_rows():
        an = artist.strip().lower()
        if an in S.EXCLUDE_ARTISTS:
            continue
        out.append({"week": int(ts // 604800), "ts": ts, "an": an, "name": artist, "tn": (track or "").strip().lower(), "track": track})
    return out


if __name__ == "__main__":
    print(json.dumps(score(plays_from_files(sys.argv[1:])), indent=1))
