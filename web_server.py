import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional
from urllib.parse import urlsplit

import file_browser

'''
    Minimal HTTP server for the boiler UI:
        GET  /           -> website/index.html (whitelisted static files only)
        GET  /api/<name> -> json of get_routes[name]()
        POST /api/<name> -> json body is passed to post_routes[name](body), returns {"message": ...}
        GET  <prefix>/…  -> read-only file browsing of browse_dirs[prefix] (see file_browser.py)
    handlers raise ValueError for bad input, which is returned as 400 {"error": ...}
'''

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
}


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, static_dir: str,
                 get_routes: Dict[str, Callable[[], object]],
                 post_routes: Dict[str, Callable[[dict], str]],
                 browse_dirs: Optional[Dict[str, str]] = None) -> None:
        super().__init__(("0.0.0.0", port), RequestHandler)
        self.static_dir = static_dir
        self.get_routes = get_routes
        self.post_routes = post_routes
        self.browse_dirs = browse_dirs or {} # url prefix (like "/usb") -> directory
        self.logger = logging.getLogger('web')


class RequestHandler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "Boiler/2.0"

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            route = self.server.get_routes.get(path[5:])
            if route is None:
                return self.send_json(404, {"error": f"unknown api {path}"})
            return self.call(lambda: route())
        if path in STATIC_FILES:
            return self.send_static(*STATIC_FILES[path])
        for prefix, root in self.server.browse_dirs.items():
            if path == prefix or path.startswith(prefix + "/"):
                return file_browser.serve(self, prefix, root, path)
        self.send_json(404, {"error": f"not found: {path}"})

    def do_POST(self):
        path = urlsplit(self.path).path
        route = self.server.post_routes.get(path[5:]) if path.startswith("/api/") else None
        if route is None:
            return self.send_json(404, {"error": f"unknown api {path}"})
        # requiring json blocks plain cross-site form posts (they can't set this content type)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.send_json(415, {"error": "expecting application/json"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a json object")
        except ValueError as e:
            return self.send_json(400, {"error": f"bad request: {e}"})
        self.server.logger.info(f"POST {path} {body}")
        self.call(lambda: {"message": route(body)})

    def call(self, func):
        try:
            self.send_json(200, func())
        except ValueError as e:
            self.send_json(400, {"error": str(e)})
        except Exception as e:
            self.server.logger.exception(f"error handling {self.path}")
            self.send_json(500, {"error": str(e)})

    def send_json(self, code: int, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, filename: str, content_type: str):
        try:
            with open(os.path.join(self.server.static_dir, filename), "rb") as f:
                payload = f.read()
        except OSError:
            return self.send_json(404, {"error": f"missing {filename}"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        self.server.logger.debug(f"{self.address_string()} {format % args}")
