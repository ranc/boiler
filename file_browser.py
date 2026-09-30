import html
import mimetypes
import os
import shutil
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, unquote

'''
    Read-only directory browsing, like Apache's "Options Indexes":
        GET <prefix>/some/dir/   -> html listing (directories first)
        GET <prefix>/some/file   -> the file, streamed
    Every path is resolved (symlinks too) and must stay inside the root directory.
'''

CHUNK = 64 * 1024


def size_str(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def resolve(root: str, rel: str):
    '''the real path of rel under root, or None if it points outside root'''
    root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root, unquote(rel).lstrip("/")))
    if path != root and not path.startswith(root + os.sep):
        return None
    return path


def serve(handler: BaseHTTPRequestHandler, prefix: str, root: str, url_path: str):
    rel = url_path[len(prefix):]
    if rel == "":
        return redirect(handler, prefix + "/")
    path = resolve(root, rel)
    if path is None or not os.path.exists(path):
        return send_text(handler, 404, f"Not found: {url_path}")
    if os.path.isdir(path):
        if not url_path.endswith("/"):
            return redirect(handler, url_path + "/")
        return send_listing(handler, url_path, path, is_root=path == os.path.realpath(root))
    send_file(handler, path)


def redirect(handler: BaseHTTPRequestHandler, location: str):
    handler.send_response(301)
    handler.send_header("Location", quote(location))
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def send_text(handler: BaseHTTPRequestHandler, code: int, text: str):
    payload = text.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def send_listing(handler: BaseHTTPRequestHandler, url_path: str, path: str, is_root: bool):
    try:
        names = os.listdir(path)
    except OSError as e:
        return send_text(handler, 403, f"Cannot list {url_path}: {e.strerror}")
    rows = []
    for name in names:
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue # broken link
        is_dir = os.path.isdir(full)
        rows.append((not is_dir, name.lower(), name, is_dir, st))
    rows.sort()

    title = html.escape(unquote(url_path))
    lines = [f"<tr><td><a href=\"../\">../</a></td><td></td><td></td></tr>"] if not is_root else []
    for _, _, name, is_dir, st in rows:
        href = quote(name) + ("/" if is_dir else "")
        label = html.escape(name) + ("/" if is_dir else "")
        size = "" if is_dir else size_str(st.st_size)
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        lines.append(f"<tr><td><a href=\"{href}\">{label}</a></td><td>{mtime}</td><td class=\"n\">{size}</td></tr>")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Index of {title}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; margin: 16px; }}
h1 {{ font-size: 1.1rem; word-break: break-all; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
td {{ padding: 6px 8px; border-bottom: 1px solid rgba(128,128,128,.25); white-space: nowrap; }}
td:first-child {{ white-space: normal; word-break: break-all; width: 100%; }}
.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
</style></head><body>
<h1>Index of {title}</h1>
<table>{''.join(lines) or '<tr><td>(empty)</td></tr>'}</table>
</body></html>"""
    payload = page.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def send_file(handler: BaseHTTPRequestHandler, path: str):
    try:
        f = open(path, "rb")
    except OSError as e:
        return send_text(handler, 403, f"Cannot read file: {e.strerror}")
    with f:
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
        handler.end_headers()
        try:
            shutil.copyfileobj(f, handler.wfile, CHUNK)
        except (BrokenPipeError, ConnectionResetError):
            pass # the browser stopped the download
