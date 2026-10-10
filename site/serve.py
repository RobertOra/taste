"""Local static server with HTTP byte-range support (like GitHub Pages), for testing the site.
    uv run python -I site/serve.py [port]    serves site/static on 127.0.0.1"""
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.match(r"bytes=(\d+)-(\d*)$", rng.strip())
        size = os.path.getsize(path)
        if not m:
            self.send_error(416); return None
        start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_error(416); return None
        f = open(path, "rb"); f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = getattr(self, "_remaining", None)
        if n is None:
            return super().copyfile(source, outputfile)
        while n > 0:
            chunk = source.read(min(65536, n))
            if not chunk:
                break
            outputfile.write(chunk); n -= len(chunk)
        self._remaining = None

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    root = Path(__file__).resolve().parent / "static"
    ThreadingHTTPServer(("127.0.0.1", port), partial(RangeHandler, directory=str(root))).serve_forever()
