"""Rating cutoffs per half. MLHD+ halves: 2007-2009 (picks judged in C+2..C+3, outcomes by 2012). ListenBrainz (lb):
every year 2007-2023 (outcomes end by Sep 2026)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cuts(half):
    return tuple(range(2007, 2024)) if half == "lb" else (2007, 2008, 2009)


def picker_cuts(half):
    """pickers.py: new picks in year C+2, so one year earlier than cuts()."""
    return tuple(range(2006, 2024)) if half == "lb" else (2006, 2007, 2008, 2009)


def genre_path(half):
    return ROOT / "data" / "derived" / "scenes_genre" / ("lb.parquet" if half == "lb" else "all.parquet")
