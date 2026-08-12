"""Servidor do playground de busca visual."""

import argparse
import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.app import render_document
from src.search_service import visual_search

PUBLIC = Path(__file__).resolve().parents[1] / "public"
MAX_UPLOAD = 15 * 1024 * 1024


class AppHandler(BaseHTTPRequestHandler):
    server_version = "Research/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(render_document(live_reload=True).encode(), "text/html; charset=utf-8")
        if path.startswith("/api/frames/"):
            try:
                frame_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self._json({"error": "Frame inválido"}, 400)
            frame = visual_search.frame_path(frame_id)
            if frame is None:
                return self._json({"error": "Frame não encontrado"}, 404)
            return self._send(frame.read_bytes(), mimetypes.guess_type(frame.name)[0] or "image/png", cache="private, max-age=3600")
        if path == "/__prpm_reload.js":
            return self._send(RELOAD_SCRIPT.encode(), "text/javascript; charset=utf-8")
        if path == "/__prpm_stamp":
            watched = [*PUBLIC.rglob("*"), *PUBLIC.parent.joinpath("src").rglob("*.py")]
            stamp = max((item.stat().st_mtime_ns for item in watched if item.is_file()), default=0)
            return self._send(str(stamp).encode(), "text/plain")
        if path in {"/app.js", "/styles.css", "/favicon.svg"}:
            asset = PUBLIC / path[1:]
            return self._send(asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        return self._json({"error": "Rota não encontrada"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/search":
            return self._json({"error": "Rota não encontrada"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"error": "Content-Length inválido"}, 400)
        if length < 1 or length > MAX_UPLOAD:
            return self._json({"error": "A imagem deve ter no máximo 15 MB"}, 413)
        content_type = self.headers.get("Content-Type", "")
        if content_type not in {"image/png", "image/jpeg", "image/webp"}:
            return self._json({"error": "Formato não suportado. Use PNG, JPG ou WebP"}, 415)
        try:
            limit = min(24, max(1, int(parse_qs(parsed.query).get("limit", ["12"])[0])))
        except ValueError:
            return self._json({"error": "Limite inválido"}, 400)
        started = time.perf_counter()
        try:
            results = visual_search.search(self.rfile.read(length), limit)
        except Exception as error:
            print(f"[search:error] {error}")
            return self._json({"error": str(error)}, 500)
        for item in results:
            item["image_url"] = f"/api/frames/{item['id']}"
            item["timestamp"] = item["frame"] / item["fps"] if item.get("fps") else None
            item.pop("path", None)
        return self._json({"results": results, "elapsed_ms": round((time.perf_counter() - started) * 1000)})

    def _json(self, value, status=200):
        self._send(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def _send(self, data, content_type, status=200, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, pattern, *args):
        print(f"[research] {self.address_string()} - {pattern % args}")


RELOAD_SCRIPT = """
let stamp = null;
setInterval(async () => {
  try { const r = await fetch('/__prpm_stamp'); const n = await r.text(); if (stamp && n !== stamp) location.reload(); stamp = n; } catch (_) {}
}, 1200);
"""


def run(port=3000, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"[OK] Research em {url}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    run(args.port, not args.no_open)
