"""The Vercel entry point (api/index.py) must serve the app through the rewrite used in vercel.json."""
import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def base_url():
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def fetch(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


@pytest.mark.parametrize("path,ctype,marker", [
    ("/api/index?__path=/", "text/html", b"<title>Inventryx</title>"),                    # rewritten "/"
    ("/api/index?__path=/static/app.js", "javascript", b"Inventryx"),
    ("/api/index?__path=/api/summary", "json", b'"profile": "starter"'),
    ("/api/index?__path=/api/skus&q=dairy", "json", b'"rows"'),                        # original query kept
    ("/api/index?__path=/files/csv/zone.csv", "text/csv", b"zone_id"),
    ("/api/summary", "json", b'"profile": "starter"'),                                 # un-rewritten path
])
def test_rewritten_paths_are_served(base_url, path, ctype, marker):
    status, content_type, body = fetch(base_url + path)
    assert status == 200 and ctype in content_type and marker in body


def test_proposals_work_and_report_non_durable_storage(base_url):
    exc = json.loads(fetch(base_url + "/api/index?__path=/api/exceptions&exception_type=LOCATION_CAPACITY_EXCEEDED")[2])
    sku, rest = exc["rows"][0]["details"].split(" -> ")
    body = dict(warehouse_id=exc["rows"][0]["warehouse_id"], sku_id=sku, location_id=rest.split(":")[0])
    check = json.loads(fetch(base_url + "/api/index?__path=/api/proposals/check", body)[2])
    assert check["decision"] == "REJECTED"
    listing = json.loads(fetch(base_url + "/api/index?__path=/api/proposals")[2])
    assert listing["durable"] is False


def test_vercel_config_routes_everything_to_the_function():
    cfg = json.loads((ROOT / "vercel.json").read_text())
    assert cfg["rewrites"] == [{"source": "/(.*)", "destination": "/api/index?__path=/$1"}]
    inc = cfg["functions"]["api/index.py"]["includeFiles"]
    assert all(p in inc for p in ("inventryx/**", "data/starter/**"))
