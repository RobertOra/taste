"""Integrity checks for the ingested MLHD+ tables. Prints PASS/FAIL per check.

Exact accounting checks (every user):
  user_recording plays per user        == users.n_listens
  user_artist_week plays per user      >= users.n_listens (multi-artist listens credit each artist)
  raw rows per user (raw-sample users) == users.n_listens, and raw artist credits == uaw plays
  (same for the *_partial tables: n_rows / n_artist)
Plus: no duplicate keys, users unique, explore/sealed and raw-sample shares, id-map collisions,
and totals matching the per-archive ingest state.
"""

import json
import sys
from pathlib import Path

import duckdb

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "mlhd")
only = sys.argv[2] if len(sys.argv) > 2 else None  # "partial" or "complete" to check one kind
con = duckdb.connect()
tmp = out / "_tmp" / "validate"
tmp.mkdir(parents=True, exist_ok=True)
con.execute(f"SET memory_limit='5GB'; SET threads=6; SET temp_directory='{tmp}'; SET preserve_insertion_order=false")
failures = 0


def t(table):
    return f"read_parquet('{out}/{table}/*/*.parquet', filename=true)"


def check(name, ok, detail=""):
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def adjacent_check(table, keys):
    """Each compacted file is sorted by `keys`; count adjacent equal rows (duplicates) and order
    violations, streaming row groups. Users never span archives, so per-file checks are complete."""
    import polars as pl
    import pyarrow.parquet as pq

    dups = unsorted = rows = 0
    for f in sorted((out / table).glob("*/*.parquet")):
        prev = None
        for batch in pq.ParquetFile(f).iter_batches(batch_size=4_000_000, columns=keys):
            df = pl.from_arrow(batch)
            if prev is not None:
                df = pl.concat([prev, df])
            cur = [pl.col(k) for k in keys]
            last = [pl.col(k).shift(1) for k in keys]
            eq = pl.all_horizontal([c == l for c, l in zip(cur, last)])
            gt, tie = pl.lit(False), pl.lit(True)
            for c, l in zip(cur, last):
                gt = gt | (tie & (c > l))
                tie = tie & (c == l)
            r = df.select(d=eq.sum(), u=(~(gt | eq)).sum()).row(0)
            dups += r[0] or 0
            unsorted += r[1] or 0
            rows += df.height - (prev is not None)
            prev = df.tail(1)
    return dups, unsorted, rows


def one(sql):
    return con.execute(sql).fetchone()


states = [json.loads(p.read_text()) | {"name": p.stem} for p in (out / "_state").glob("*.json")]

for kind, users, n_col, uaw, raw in [
    ("complete", "users", "n_listens", "user_artist_week", "raw"),
    ("partial", "users_partial", "n_rows", "user_artist_week_partial", "raw_partial"),
]:
    if only and kind != only:
        continue
    print(f"== {kind}")
    st = [s for s in states if f"-{kind}-" in s["name"]]
    check(f"{kind}: all archives done", all(s["done"] for s in st), f"{sum(s['done'] for s in st)}/{len(st)}")
    n, nu, total = one(f"SELECT count(*), count(DISTINCT user), sum({n_col}) FROM {t(users)}")
    check(f"{kind}: users unique", n == nu, f"{n:,} rows, {nu:,} distinct")
    check(f"{kind}: listen total matches ingest state", total == sum(s["listens"] for s in st),
          f"{total:,} vs {sum(s['listens'] for s in st):,}")
    files = sum(s["users"] for s in st)  # user files seen; empty files produce no users row
    check(f"{kind}: users == user files minus a few empty files", 0 <= files - n <= files // 1000,
          f"{files:,} files, {files - n:,} without rows")
    share = one(f"SELECT avg((filename LIKE '%/explore/%')::INT) FROM {t(users)}")[0]
    check(f"{kind}: explore share ~50%", abs(share - 0.5) < 0.01, f"{share:.4f}")

    dup, uns, rows = adjacent_check(uaw, ["user", "artist", "week"])
    check(f"{kind}: {uaw} sorted with unique keys", dup == uns == 0, f"{rows:,} rows, {dup:,} dups, {uns:,} unsorted")
    plays = "n_artist" if kind == "partial" else n_col
    bad = one(f"""
        WITH p AS (SELECT user, sum(plays) AS s FROM {t(uaw)} GROUP BY user)
        SELECT count(*) FILTER (WHERE coalesce(p.s, 0) < u.{plays}),
               count(*) FILTER (WHERE u.{plays} = 0 AND p.s > 0)
        FROM {t(users)} u LEFT JOIN p USING (user)""")
    check(f"{kind}: {uaw} plays cover every listen", bad == (0, 0), f"{bad[0]:,} users short, {bad[1]:,} phantom")

    if kind == "complete":
        bad = one(f"""
            WITH p AS (SELECT user, sum(plays) AS s FROM {t('user_recording')} GROUP BY user)
            SELECT count(*) FROM {t(users)} u LEFT JOIN p USING (user) WHERE coalesce(p.s, 0) != u.n_listens""")[0]
        check("complete: user_recording plays == n_listens for every user", bad == 0, f"{bad:,} mismatched")
        dup, uns, rows = adjacent_check("user_recording", ["recording", "user"])
        check("complete: user_recording sorted with unique keys", dup == uns == 0,
              f"{rows:,} rows, {dup:,} dups, {uns:,} unsorted")
        rs = one(f"SELECT avg(raw_sample::INT) FROM {t(users)}")[0]
        check("complete: raw-sample share ~1/8", abs(rs - 0.125) < 0.005, f"{rs:.4f}")

    sample = f"(SELECT user FROM {t('users')} WHERE raw_sample)"
    bad = one(f"""
        WITH r AS (SELECT user, count(*) AS n, sum(len(artists)) FILTER (WHERE artists IS NOT NULL) AS credits
                   FROM {t(raw)} GROUP BY user),
             p AS (SELECT user, sum(plays) AS s FROM {t(uaw)} WHERE user IN {sample} GROUP BY user)
        SELECT count(*) FILTER (WHERE coalesce(r.n, 0) != u.{n_col}),
               count(*) FILTER (WHERE coalesce(r.credits, 0) != coalesce(p.s, 0)),
               count(*)
        FROM {t(users)} u LEFT JOIN r USING (user) LEFT JOIN p USING (user)
        WHERE u.user IN {sample}""")
    check(f"{kind}: raw sample matches summaries exactly", bad[:2] == (0, 0),
          f"{bad[2]:,} sample users; {bad[0]:,} row-count and {bad[1]:,} credit mismatches")
    stray = one(f"SELECT count(DISTINCT user) FROM {t(raw)} WHERE user NOT IN {sample}")[0]
    check(f"{kind}: raw contains only sample users", stray == 0, f"{stray:,} stray users")

if not only:
    print("== complete vs partial")
    a, b, both = one(f"""SELECT count(*) FILTER (WHERE p.user IS NULL), count(*) FILTER (WHERE c.user IS NULL),
        count(*) FILTER (WHERE c.user IS NOT NULL AND p.user IS NOT NULL)
        FROM (SELECT user FROM {t('users')}) c FULL JOIN (SELECT user FROM {t('users_partial')}) p USING (user)""")
    check("partial-only users are rare (their raw-sample membership is unknown)", b <= (a + b + both) // 100,
          f"{both:,} in both, {a:,} complete-only, {b:,} partial-only")

print("== id maps")
for m in ["artist_map", "release_map", "recording_map"]:
    if not list((out / m).glob("*/*.parquet")):
        continue
    n_id, n_mbid, coll = one(f"""SELECT count(DISTINCT id), count(DISTINCT mbid),
        (SELECT count(*) FROM (SELECT id FROM {t(m)} GROUP BY id HAVING count(DISTINCT mbid) > 1))
        FROM {t(m)}""")
    check(f"{m}: no id collisions", coll == 0, f"{n_id:,} ids, {n_mbid:,} mbids, {coll} colliding ids")

print(f"\n{failures} check(s) failed" if failures else "\nall checks passed")
sys.exit(1 if failures else 0)
