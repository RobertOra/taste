"""Data periods per half (months are year*12 + month - 1). MLHD+ halves end with 2012 (data thin out in 2013);
ListenBrainz ("lb") runs to September 2026."""

PERIODS = {"explore": (2005 * 12, 2012 * 12 + 11), "sealed": (2005 * 12, 2012 * 12 + 11), "lb": (2005 * 12, 2026 * 12 + 8)}
HALVES = list(PERIODS)


def first_month(half):
    return PERIODS[half][0]


def last_month(half):
    return PERIODS[half][1]


def scene_years(half):
    """Years with time-respecting scenes: each needs at least a year of earlier listening."""
    return range(PERIODS[half][0] // 12 + 1, PERIODS[half][1] // 12 + 1)
