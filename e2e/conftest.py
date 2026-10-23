"""The web interface, driven by a real browser against a real server on a throwaway home.

    cd web && npm run build              (the server serves web/dist)
    pip install playwright pytest && python -m playwright install chromium
    python -m pytest e2e

Each test file gets one server (a fresh home); the tests in it run in order, as one person working through the pages."""
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pw = pytest.importorskip("playwright.sync_api")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """the Studio on a free port, its home a new temporary folder"""
    if not os.path.exists(os.path.join(ROOT, "web", "dist", "index.html")):
        pytest.fail("web/dist is missing: npm run build in web/ first")
    home = tempfile.mkdtemp(prefix="inspector-e2e-")
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("INSPECTOR_")}
    env.update(INSPECTOR_HOME=home, INSPECTOR_EDITION="studio", PYTHONIOENCODING="utf-8")
    log = open(os.path.join(home, "server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "server", "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(240):
        try:
            urllib.request.urlopen(base + "/api/project", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the server did not start")
    if proc.poll() is not None:
        log.close()
        pytest.fail("the server stopped:\n" + open(os.path.join(home, "server.log"), encoding="utf-8").read()[-3000:])
    yield base
    proc.kill()
    proc.wait(10)
    log.close()


@pytest.fixture(scope="module")
def camera():
    """a camera's snapshot address: a plain picture, served here"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), (40, 120, 60)).save(buf, "JPEG")
    jpg = buf.getvalue()

    class Snap(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Snap)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/snap.jpg"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# answers that are not failures: a new project has nothing to train on yet (the page shows that answer)
EXPECTED = [(400, "/api/train/preview")]


def _expected(r):
    return any(r.status == st and urllib.parse.urlparse(r.url).path == path for st, path in EXPECTED)


class Tab:
    """one browser tab in one interface language; page errors and failed requests are collected as it goes"""

    def __init__(self, browser, base, lang):
        self.base = base
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        self.ctx.add_init_script(f"try{{localStorage.setItem('inspector.lang', {json.dumps(lang)})}}catch(e){{}}")
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(f"page error: {e}"))
        self.page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
                     and self.errors.append(f"console: {m.text}"))
        self.page.on("response", lambda r: r.status >= 400 and not _expected(r) and self.errors.append(f"{r.status} {r.url}"))

    def go(self, path):
        self.page.goto(self.base + path)
        self.page.wait_for_load_state("networkidle")
        self.page.locator("main h1").first.wait_for()
        return self.page

    def text(self):
        """what the page itself shows (the main area, not the menu)"""
        return self.page.locator("main").inner_text()

    def api(self, method, path, body=None):
        r = urllib.request.Request(self.base + path, method=method, headers={"Content-Type": "application/json"},
                                   data=json.dumps(body).encode() if body is not None else None)
        return json.loads(urllib.request.urlopen(r, timeout=30).read() or b"{}")

    def close(self):
        self.ctx.close()


@pytest.fixture
def zh(browser, server):
    t = Tab(browser, server, "zh-TW")
    yield t
    t.close()
    assert not t.errors, "\n".join(t.errors)


@pytest.fixture
def en(browser, server):
    t = Tab(browser, server, "en")
    yield t
    t.close()
    assert not t.errors, "\n".join(t.errors)


HAN = re.compile(r"[㐀-鿿豈-﫿]")
