import html
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, unquote

'''
    Read-only directory browsing, like Apache's "Options Indexes":
        GET <prefix>/some/dir/   -> html listing (directories first)
        GET <prefix>/some/file   -> the file, streamed
    Files support single byte ranges (Range: bytes=a-b -> 206 Partial Content), which video players
    need to seek, to read an mp4 index stored at the end, and which iOS Safari requires to play at all.
    HEAD gets the same headers without a body.
    Every path is resolved (symlinks too) and must stay inside the root directory.
'''

CHUNK = 64 * 1024
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


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


def write_body(handler: BaseHTTPRequestHandler, payload: bytes):
    if handler.command != "HEAD":
        handler.wfile.write(payload)


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
    write_body(handler, payload)


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
    write_body(handler, payload)


def parse_range(header: str, size: int):
    '''(start, end) inclusive for a single "bytes=" range, None to send the whole file, ValueError if unsatisfiable'''
    m = RANGE_RE.match(header.strip()) if header else None
    if m is None:
        return None # no range, or a form we don't handle (multiple ranges): the whole file is a valid answer
    first, last = m.groups()
    if first == "" and last == "":
        return None
    if first == "": # bytes=-N: the last N bytes
        if int(last) == 0:
            raise ValueError("empty suffix range")
        return max(0, size - int(last)), size - 1
    start = int(first)
    end = size - 1 if last == "" else min(int(last), size - 1)
    if start >= size or end < start:
        raise ValueError("range outside the file")
    return start, end


def send_file(handler: BaseHTTPRequestHandler, path: str):
    try:
        f = open(path, "rb")
    except OSError as e:
        return send_text(handler, 403, f"Cannot read file: {e.strerror}")
    with f:
        st = os.fstat(f.fileno())
        size = st.st_size
        try:
            byte_range = parse_range(handler.headers.get("Range", ""), size)
        except ValueError:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        start, end = byte_range if byte_range else (0, size - 1)
        length = end - start + 1 if size else 0

        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        handler.send_response(206 if byte_range else 200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(length))
        if byte_range:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.send_header("Last-Modified", handler.date_time_string(st.st_mtime))
        handler.end_headers()
        if handler.command == "HEAD":
            return
        f.seek(start)
        left = length
        try:
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break # the file shrank while we were sending it
                handler.wfile.write(chunk)
                left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass # the player stopped this request, normal when seeking
