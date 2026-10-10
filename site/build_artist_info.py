"""Small per-artist tables the site needs for its corrections (from the project's ListenBrainz tables).
    data/site/artist_scene.parquet    artist, year, scene      (time-respecting yearly scenes, data/derived/scenes_yearly/lb.parquet)
    data/site/artist_release.parquet  artist, rm               (months of album/EP/single releases, MusicBrainz)
    data/site/artist_info.parquet     artist, country, first_month (first month anyone in ListenBrainz played them)
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
X, REF = ROOT / "data" / "derived", ROOT / "data" / "site"
con = duckdb.connect(); con.execute("SET memory_limit='5GB'; SET threads=6")
con.execute(f"COPY (SELECT artist, year::SMALLINT AS year, scene_200::SMALLINT AS scene FROM read_parquet('{X}/scenes_yearly/lb.parquet')) TO '{REF}/artist_scene.parquet' (FORMAT parquet, COMPRESSION zstd)")
con.execute(f"""COPY (SELECT DISTINCT artist, (substr(first_release_date, 1, 4)::INT * 12 + substr(first_release_date, 6, 2)::INT - 1)::INT AS rm
                      FROM read_parquet('{X}/mb_release_groups_lb.parquet') WHERE regexp_matches(first_release_date, '^[0-9]{{4}}-[0-9]{{2}}')
                        AND first_release_date < '2700' AND primary_type IN ('Album', 'EP', 'Single') AND secondary_types NOT LIKE '%Compilation%')
                TO '{REF}/artist_release.parquet' (FORMAT parquet, COMPRESSION zstd)""")
con.execute(f"""COPY (SELECT a.artist, coalesce(c.country, '?') AS country, a.first_month FROM
                       (SELECT artist, min(month)::SMALLINT AS first_month FROM read_parquet('{REF}/artist_adopt.parquet') GROUP BY artist) a
                       LEFT JOIN (SELECT artist, any_value(country) AS country FROM read_parquet('{X}/mb_artists_lb.parquet') GROUP BY artist) c USING (artist))
                TO '{REF}/artist_info.parquet' (FORMAT parquet, COMPRESSION zstd)""")
for f in ("artist_scene", "artist_release", "artist_info"):
    print(f, con.execute(f"SELECT count(*) FROM read_parquet('{REF}/{f}.parquet')").fetchone()[0], f"{(REF / (f + '.parquet')).stat().st_size / 1e6:.0f} MB")
