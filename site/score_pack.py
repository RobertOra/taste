"""Python mirror of site/static/engine.js for the packed data (site/static/data/meta.json, index.bin, p/NN.bin), used to check
the browser engine and to score ListenBrainz users for validation.
    plays: list of dicts {week, ts, an, name, tn, track[, ah, sh]} (ah/sh: precomputed artist / song name hashes)"""
import bisect
import calendar
import json
import re
import zipfile
import zlib
import math
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import score as S  # noqa: E402  (name_hash, true_range, read_history, EXCLUDE_ARTISTS)

import os
DATA = Path(os.environ.get("SITE_OUT", ROOT / "site" / "static" / "data"))   # SITE_OUT: test another pack (e.g. site/static/data_v2)
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
    if any(p.get("src") == "yt?" for p in plays):
        plays = resolve_youtube(plays, pack)
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


# ---------- YouTube watch history (Google Takeout), as engine.js
YT_TAGS = re.compile(r"\s*[(\[][^)\]]*(official|lyric|audio|video|visualizer|(?<![A-Za-z0-9_])mv(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])m/v(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])hd(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])4k(?![A-Za-z0-9_]))[^)\]]*[)\]]", re.I)
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
TZ = {"UTC": 0, "GMT": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10, "BST": 1,
      "CET": 1, "CEST": 2, "EET": 2, "EEST": 3, "MSK": 3, "IST": 5.5, "JST": 9, "KST": 9, "AEST": 10, "AEDT": 11, "NZST": 12, "NZDT": 13}
YT_TIME = re.compile(r"^(?:([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})|(\d{1,2}) ([A-Za-z]{3})[A-Za-z]*\.? (\d{4})),? (\d{1,2}):(\d{2}):(\d{2}) ?(AM|PM)? ?(?:GMT([+-])(\d{1,2}):?(\d{2})|([A-Z]{2,5}))?$", re.I)


def yt_time(s):
    m = YT_TIME.match(s)
    if not m or (m[1] or m[5]).lower() not in MON:
        return None
    h = int(m[7])
    if m[10]:
        h = h % 12 + (12 if m[10].upper() == "PM" else 0)
    off = ((-1 if m[11] == "-" else 1) * (int(m[12]) + int(m[13]) / 60)) if m[11] else TZ.get((m[14] or "").upper(), 0)
    return calendar.timegm((int(m[3] or m[6]), MON[(m[1] or m[5]).lower()] + 1, int(m[2] or m[4]), h, int(m[8]), int(m[9]))) - off * 3600


def _unescape(s):
    def one(mt):
        k = mt[1].lower()
        return {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}.get(k) or chr(int(k[2:], 16) if k[1] == "x" else int(k[1:]))
    return re.sub(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);", one, s, flags=re.I)


FEAT = re.compile(r"(?:\s+|\s*[(\[])\s*(feat\.?|ft\.?|featuring|prod\.?(?: by)?)\s[^)\]]*[)\]]?", re.I)
SPLIT = re.compile(r"\s*(?:,|&| x | X |(?<![A-Za-z0-9_])feat\.?|(?<![A-Za-z0-9_])ft\.?)\s*")
QUOTED = re.compile(r"^(.+?)\s+[\"'‘“「『]([^\"'’”」』]+)[\"'’”」』]")
HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]+")


def _trim(s):
    return re.sub(r"^[\s\-|]+|[\s\-|]+$", "", s)


def _clean(s):
    return _trim(FEAT.sub("", YT_TAGS.sub("", s)))


def yt_cands(header, title, channel):
    """Readings of one YouTube watch as (rule, artist, song), most reliable first. Rule 'a': counts if the artist is confirmed;
    'av': same, and the reading also counts toward confirming its artist; 's'/'sv': needs the exact song in ListenBrainz too
    (resolve_youtube). Channel-name and quoted readings never confirm an artist on their own, which keeps out YouTubers."""
    out = []; title = re.sub(r" [–—] ", " - ", title)
    if " - " in title:
        i = title.index(" - "); a, s = title[:i], title[i + 3:]
        out += [("av", a, YT_TAGS.sub("", s)), ("sv", SPLIT.split(a)[0], _clean(s)), ("sv", _clean(s), a)]
    m = QUOTED.match(title)
    if m:
        out.append(("s", HANGUL.sub("", re.sub(r"\s*\([^)]*\)", "", m[1])), m[2]))
    ch = re.sub(r"(VEVO|\s*-?\s*Official(\s+(Channel|YouTube))?)$", "", channel, flags=re.I).strip()
    rest = title[len(ch) + 3:] if ch and title.lower().startswith(ch.lower() + " - ") else title
    out.append(("av" if header == "YouTube Music" else "s", ch, _clean(rest)))
    return [(k, a.strip(), s.strip()) for k, a, s in out if a.strip() and s.strip()]


def yt_play(header, title, channel, ts):
    if ts is None:
        return None
    base = {"week": int(ts // 604800), "ts": ts, "key": f"{int(ts)}\t{title}\t{channel}"}
    if channel.endswith(" - Topic"):
        artist, track = channel[:-8].strip(), title.strip(); an = artist.lower()
        if an in S.EXCLUDE_ARTISTS or not track:
            return None
        return {**base, "an": an, "name": artist, "tn": track.lower(), "track": track, "src": "yt"}
    c = yt_cands(header, title, channel)
    return {**base, "src": "yt?", "cands": c} if c else None


def _yt_html(text, watch_file):
    text = text.replace("\u202f", " ").replace("\xa0", " "); out = []
    for cell in text.split("outer-cell")[1:]:
        if "From Google Ads" in cell:
            continue
        h = re.search(r'mdl-typography--title">([^<]*)<', cell)
        c = re.search(r'mdl-typography--body-1">([^<]*)<a href="([^"]*)">([^<]*)</a><br><a href="[^"]*">([^<]*)</a><br>([^<]*)<br>', cell)
        if not c or "watch?v=" not in c[2] or not (watch_file or c[1].strip() == "Watched"):
            continue
        p = yt_play(h[1].strip() if h else "", _unescape(c[3]).strip(), _unescape(c[4]).strip(), yt_time(c[5].strip()))
        if p:
            out.append(p)
    return out


def _yt_json(data, watch_file):
    out = []
    for d in data if isinstance(data, list) else []:
        if not (isinstance(d, dict) and "time" in d and "header" in d and isinstance(d.get("title"), str) and isinstance(d.get("titleUrl"), str)):
            continue
        if "watch?v=" not in d["titleUrl"] or not isinstance(d.get("subtitles"), list) or not d["subtitles"]:
            continue
        if isinstance(d.get("details"), list) and any(isinstance(x, dict) and x.get("name") == "From Google Ads" for x in d["details"]):
            continue
        if not watch_file and not d["title"].startswith("Watched "):
            continue
        t = d["title"][8:] if d["title"].startswith("Watched ") else d["title"]
        ts = datetime.fromisoformat(d["time"].replace("Z", "+00:00")).timestamp()
        p = yt_play(str(d["header"]).strip(), t.strip(), str(d["subtitles"][0].get("name") or "").strip(), ts)
        if p:
            out.append(p)
    return out


def read_youtube(paths):
    out = []
    def one(name, raw):
        wf = bool(re.search("watch-history", name, re.I))
        if name.lower().endswith(".html"):
            out.extend(_yt_html(raw.decode("utf-8", "replace"), wf))
        elif name.lower().endswith(".json"):
            try:
                out.extend(_yt_json(json.loads(raw), wf))
            except ValueError:
                pass
    for path in map(Path, paths):
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    want = (n.lower().endswith(".json") and re.search("history|youtube", n, re.I)) or (n.lower().endswith(".html") and re.search("youtube|watch-history", n, re.I))
                    one(n, z.read(n)) if want else None
        else:
            one(path.name, path.read_bytes())
    seen = set(); uniq = []
    for p in out:   # the same watch in two exports counts once
        k = p["key"]
        if k not in seen:
            seen.add(k); uniq.append(p)
    return uniq


def resolve_youtube(plays, pack):
    """Settle each guessed YouTube watch on its first reading that passes (yt_cands), preferring one whose artist you play elsewhere. An artist is confirmed if it's in the
    history some surer way (Spotify, a Topic channel), or (from 'av'/'sv' readings in 4+ separate weeks) ListenBrainz knows it
    and one of its three most-played songs. Watches with no passing reading are taken as not music (as engine.js resolveYouTube)."""
    sure = {p["an"] for p in plays if p.get("src", "spotify") != "yt?"}; by = {}
    guessed = [p for p in plays if p.get("src") == "yt?"]
    for p in guessed:
        for rule, a, s in p["cands"]:
            an = a.lower()
            if rule.endswith("v") and an not in sure:
                g = by.setdefault(an, {"weeks": set(), "songs": {}}); g["weeks"].add(p["week"]); g["songs"].setdefault(s.lower(), set()).add(p["week"])
    known = set(sure)
    for an, g in by.items():
        if len(g["weeks"]) < 4 or not pack.artist(S.name_hash(an)):
            continue
        top = sorted(g["songs"].items(), key=lambda kv: (-len(kv[1]), kv[0]))[:3]
        if any(pack.song(S.name_hash(an + "\t" + tn)) for tn, _ in top):
            known.add(an)
    span = {}   # weeks an artist could have at most; below 4 it can't be a find, so its song readings aren't checked
    for p in plays:
        for an in ([a.lower() for _, a, _ in p["cands"]] if p.get("src") == "yt?" else [p["an"]]):
            span.setdefault(an, set()).add(p["week"])
    def passes(rule, an, tn):
        return an in known and an not in S.EXCLUDE_ARTISTS and (rule[0] == "a" or (len(span[an]) >= 4 and pack.artist(S.name_hash(an)) is not None and pack.song(S.name_hash(an + "\t" + tn)) is not None))
    out = []
    for p in plays:
        if p.get("src") != "yt?":
            out.append(p); continue
        ok = [(a, s) for rule, a, s in p["cands"] if passes(rule, a.lower(), s.lower())]
        pick = next(((a, s) for a, s in ok if a.lower() in sure), ok[0] if ok else None)   # an artist you play elsewhere wins
        if pick:
            a, s = pick; out.append({"week": p["week"], "ts": p["ts"], "an": a.lower(), "name": a, "tn": s.lower(), "track": s, "src": "yt?"})
    return out


def plays_from_files(paths):
    df, kind = S.read_history(paths)
    out = []
    for ts, artist, track in df.iter_rows():
        an = artist.strip().lower()
        if an in S.EXCLUDE_ARTISTS:
            continue
        out.append({"week": int(ts // 604800), "ts": ts, "an": an, "name": artist, "tn": (track or "").strip().lower(), "track": track, "src": "spotify"})
    return out + read_youtube(paths)


if __name__ == "__main__":
    print(json.dumps(score(plays_from_files(sys.argv[1:])), indent=1))
