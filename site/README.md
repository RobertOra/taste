# Taste Test (site)

Upload a Spotify Extended streaming history; get a percentile range for how well the artists and songs you got into went on
to grow, against ListenBrainz listeners scored the same way. Method: the project's prescience measure with its corrections
(scene, momentum, artist or song age, release timing, country), simplified so it can be computed for anyone
(`features.py`). On ListenBrainz users it agrees with the project's frozen score at 0.71 (about 0.95 once each score's
noise is allowed for), and the engine reproduces the builder's reference scores exactly (`test_engine.py`, `compare_engine.py`).

Run locally (from the project root):

    uv run --with fastapi --with uvicorn --with python-multipart uvicorn app:app --app-dir site --host 127.0.0.1 --port 8766

Reference data (`data/site`, about 3 GB), rebuilt from the project's ListenBrainz tables:

    uv run python -I site/build_reference.py     # new listeners per artist / song per month, name maps
    uv run python -I site/build_artist_info.py   # scenes, releases, countries, first months
    uv run python -I site/build_baselines.py     # baselines, correction effects, reference scores, reliability

Minimum requirements (in `score.py`): extended history (the one-year export is recognised and explained), at least two
years, at least 40% of plays recognised (warning below 60%), at least 110 judged finds for a score (250 for a solid one).
Finds less than a year before the reference data's last month are listed as too recent to judge. Refresh the reference
from a newer ListenBrainz dump every few months so recent finds can be judged.
