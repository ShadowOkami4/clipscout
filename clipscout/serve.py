"""The review page: a tiny local web server (standard library only) on 127.0.0.1."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import project as proj
from .export import cut

REVIEW_DIR = Path(__file__).parent / "review"
CLIP_ID = re.compile(r"^clip-\d{3,}$")


def make_handler(project_path: Path, threads: int):
    lock = threading.Lock()
    clip_dir = project_path.parent / "clips"

    class Handler(BaseHTTPRequestHandler):
        server_version = "clipscout"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        # Only answer requests addressed to this local server (blocks DNS-rebinding tricks).
        def _local(self) -> bool:
            port = self.server.server_address[1]
            host = self.headers.get("Host", "")
            ok_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if host not in ok_hosts or (origin and origin.split("//", 1)[-1] not in ok_hosts):
                self.send_error(HTTPStatus.FORBIDDEN)
                return False
            return True

        def _json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path):
            if not path.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(size - int(m.group(2)), 0)
                end = min(end, size - 1)
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    return self.end_headers()
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(length, 1 << 20)) or b"{}")

        def do_GET(self):
            if not self._local():
                return
            path = self.path.split("?", 1)[0]
            if path == "/":
                return self._file(REVIEW_DIR / "index.html")
            if path == "/api/project":
                with lock:
                    return self._json(proj.load(project_path))
            m = re.fullmatch(r"/clips/(clip-\d{3,})\.mp4", path)
            if m:
                return self._file(clip_dir / f"{m.group(1)}.mp4")
            m = re.fullmatch(r"/review/([\w.-]+)", path)
            if m:
                return self._file(REVIEW_DIR / m.group(1))
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if not self._local():
                return
            try:
                body = self._body()
            except ValueError:
                return self._json({"error": "bad JSON"}, HTTPStatus.BAD_REQUEST)
            if self.path == "/api/clip":
                return self._update_clip(body)
            if self.path == "/api/export":
                try:
                    with lock:
                        files = proj.export_clips(project_path, everything=bool(body.get("all")),
                                                  accurate=bool(body.get("accurate")), threads=threads, log=lambda *a: None)
                    return self._json({"files": [str(f) for f in files], "folder": str(project_path.parent / "export")})
                except RuntimeError as e:
                    return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            self.send_error(HTTPStatus.NOT_FOUND)

        def _update_clip(self, body: dict):
            cid = body.get("id", "")
            if not CLIP_ID.match(cid):
                return self._json({"error": "bad clip id"}, HTTPStatus.BAD_REQUEST)
            with lock:
                data = proj.load(project_path)
                clip = next((c for c in data["clips"] if c["id"] == cid), None)
                if not clip:
                    return self._json({"error": "unknown clip"}, HTTPStatus.NOT_FOUND)
                if "keep" in body and body["keep"] in (True, False, None):
                    clip["keep"] = body["keep"]
                recut = False
                if "start" in body or "end" in body:
                    start = float(body.get("start", clip["start"]))
                    end = float(body.get("end", clip["end"]))
                    start = max(0.0, min(start, data["duration"]))
                    end = max(start + 0.5, min(end, data["duration"]))
                    recut = (round(start, 2), round(end, 2)) != (round(clip["start"], 2), round(clip["end"], 2))
                    clip["start"], clip["end"] = round(start, 3), round(end, 3)
                proj.save(project_path, data)
                if recut:
                    cut(data["video"], clip["start"], clip["end"], clip_dir / f"{cid}.mp4", threads=threads, preview=True)
            return self._json(clip)

    return Handler


def serve(project_path: Path, port: int = 0, open_browser: bool = True, threads: int = 4) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(project_path, threads))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Review page: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
