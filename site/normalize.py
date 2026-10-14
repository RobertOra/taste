"""Normalized names for the site's song identity (NOTES.md, planned rebuild item 1). Mirrored exactly by normName/songKey in
site/static/engine.js; site/test_normalize.py checks they agree.

norm_name(s): NFKC, lowercase; drop bracketed or dash-separated labels that don't make a different recording (feat./ft./with,
remaster(ed), version, edit, explicit, clean, radio, mono, stereo, deluxe, bonus, single, album, official, lyric(s), audio,
video, visualizer, hd, 4k, mv); keep remix, live, acoustic, slowed, sped up, instrumental, demo, cover and the like; drop
"feat./ft." tails; then keep only letters and digits (Unicode categories L and N). If nothing is left, the lowercased,
trimmed original is used.
song_key(artist, track) = norm_name(artist) + "\\t" + norm_name(track), hashed with blake2b-8 like every other name key.
"""
import re
import unicodedata

DROP = r"feat|ft|featuring|with|remaster|remastered|remasterd|version|edit|explicit|clean|radio|mono|stereo|deluxe|bonus|single|album|official|lyric|lyrics|audio|video|visualizer|visualiser|hd|4k|mv|m/v"
KEEP = r"remix|mix|live|acoustic|slowed|sped|reverb|instrumental|demo|cover|karaoke|orchestral|piano|unplugged|session"
BRACKET = re.compile(r"\s*[(\[]([^)\]]*)[)\]]")
DASH = re.compile(r"\s+-\s+([^-]*)$")
FEAT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$")
WORD_DROP = re.compile(r"(?<![a-z0-9])(?:" + DROP + r")(?![a-z0-9])")
WORD_KEEP = re.compile(r"(?<![a-z0-9])(?:" + KEEP + r")")


def _label_drop(text):
    return bool(WORD_DROP.search(text)) and not WORD_KEEP.search(text)


def norm_name(s):
    t = unicodedata.normalize("NFKC", s or "").lower().strip()
    base = t
    t = BRACKET.sub(lambda m: "" if _label_drop(m.group(1)) else m.group(0), t)
    m = DASH.search(t)
    if m and _label_drop(m.group(1)):
        t = t[:m.start()]
    t = FEAT.sub("", t)
    out = "".join(c for c in t if unicodedata.category(c)[0] in "LN")
    return out if out else base


def song_key(artist, track):
    return norm_name(artist) + "\t" + norm_name(track)
