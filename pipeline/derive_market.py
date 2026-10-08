"""Fixed-panel artist popularity ("market") for horizons H (months), one half at a time.

For bet month m and horizon H, the panel is the users active (any listen) in both m and m+H.
    data/derived/market/<half>/listeners_h<H>.parquet   artist, month, l0, l1
        l0 = panel users who played the artist in month m, l1 = panel users who played it in m+H
    data/derived/market/<half>/panel.parquet            month, h, n_panel
Penetration = l / n_panel; with a fixed panel, growth = log((l1 + s) / (l0 + s)) needs no denominator.
Leave-one-out is applied when scoring bets (the bettor's own presence is subtracted there).
Months are year*12 + month-1; only m+H <= 2012-12 (data thin out during 2013).

Usage: derive_market.py <half> [--horizons 6 12 24]
"""

import argparse
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
UAM = ROOT / "data" / "derived" / "user_artist_month"
DST = ROOT / "data" / "derived" / "market"
FIRST, LAST = 2005 * 12, 2012 * 12 + 11


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("half", choices=["explore", "sealed"])
    ap.add_argument("--horizons", type=int, nargs="+", default=[6, 12, 24])
    args = ap.parse_args()
    out = DST / args.half
    out.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "data" / "_tmp" / f"market-{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='7GB'; SET threads=8; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
    panel_parts = []
    for h in args.horizons:
        dest = out / f"listeners_h{h}.parquet"
        parts = []
        for c in "0123456789abcdef":
            uam = f"read_parquet('{UAM / args.half / f'mlhdplus-{c}.parquet'}')"
            con.execute(f"CREATE OR REPLACE TEMP TABLE act AS SELECT DISTINCT user, month FROM {uam}")
            con.execute(f"""CREATE OR REPLACE TEMP TABLE p{c} AS
                WITH a0 AS (SELECT l.artist, l.month, count(*) AS l0 FROM {uam} l
                            JOIN act a ON a.user = l.user AND a.month = l.month + {h}
                            WHERE l.month BETWEEN {FIRST} AND {LAST - h} GROUP BY ALL),
                     a1 AS (SELECT l.artist, l.month - {h} AS month, count(*) AS l1 FROM {uam} l
                            JOIN act a ON a.user = l.user AND a.month = l.month - {h}
                            WHERE l.month BETWEEN {FIRST + h} AND {LAST} GROUP BY ALL)
                SELECT artist, month, coalesce(l0, 0) AS l0, coalesce(l1, 0) AS l1
                FROM a0 FULL JOIN a1 USING (artist, month)""")
            parts.append(f"SELECT * FROM p{c}")
            panel_parts.append(f"""SELECT a.month, {h} AS h, count(*) AS n FROM act a JOIN act b
                ON a.user = b.user AND b.month = a.month + {h} WHERE a.month BETWEEN {FIRST} AND {LAST - h} GROUP BY ALL""")
            con.execute(f"CREATE OR REPLACE TEMP TABLE panel_{h}_{c} AS {panel_parts[-1]}")
            panel_parts[-1] = f"SELECT * FROM panel_{h}_{c}"
        con.execute(f"""COPY (SELECT artist, month::SMALLINT AS month, sum(l0)::INT AS l0, sum(l1)::INT AS l1
                         FROM ({' UNION ALL '.join(parts)}) GROUP BY ALL ORDER BY artist, month)
                     TO '{dest}' (FORMAT parquet, COMPRESSION zstd)""")
        for c in "0123456789abcdef":
            con.execute(f"DROP TABLE p{c}")
        print(f"h={h}: {con.execute(f'SELECT count(*) FROM read_parquet(\'{dest}\')').fetchone()[0]:,} artist-months",
              flush=True)
    con.execute(f"""COPY (SELECT month::SMALLINT AS month, h::SMALLINT AS h, sum(n)::INT AS n_panel
                     FROM ({' UNION ALL '.join(panel_parts)}) GROUP BY ALL ORDER BY h, month)
                 TO '{out / 'panel.parquet'}' (FORMAT parquet)""")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
