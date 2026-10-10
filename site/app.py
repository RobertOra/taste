"""Taste-scoring web app. Run: uv run --with fastapi --with uvicorn --with python-multipart uvicorn site.app:app --port 8000
(from the project root, or with app-dir). Upload Spotify extended streaming history (.zip or .json files) -> JSON result."""
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as S  # noqa: E402

app = FastAPI(title="Taste test")
MAX_BYTES = 300 * 1024 * 1024


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.post("/api/score")
async def api_score(files: list[UploadFile] = File(...)):
    tmp = Path(tempfile.mkdtemp(prefix="taste_"))
    try:
        total = 0
        paths = []
        for f in files:
            name = Path(f.filename or "upload").name
            if not name.lower().endswith((".zip", ".json")):
                continue
            dest = tmp / name
            with dest.open("wb") as out:
                while chunk := await f.read(1 << 20):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return JSONResponse({"ok": False, "checks": [{"id": "size", "ok": False, "text": "Those files are too large (over 300 MB)."}]})
                    out.write(chunk)
            paths.append(dest)
        if not paths:
            return JSONResponse({"ok": False, "checks": [{"id": "format", "ok": False, "text": "Please upload the .zip or .json files from your Spotify export."}]})
        try:
            return JSONResponse(S.score_files(paths))
        except Exception as e:  # keep the page friendly
            return JSONResponse({"ok": False, "checks": [{"id": "error", "ok": False, "text": f"Something went wrong reading those files ({type(e).__name__})."}]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
