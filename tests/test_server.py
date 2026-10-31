"""Web app API tests against a small generated dataset."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from inventryx import config as C
from inventryx.cli import generate
from inventryx.server import Store, _Server, make_handler


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    out = tmp_path_factory.mktemp("web") / "small"
    generate(C.resolve_scale("starter", warehouses=2, locations=600, skus=300, order_lines=4000), C.DEFAULT_SEED,
             out, [], log=lambda *a: None)
    httpd = _Server(("127.0.0.1", 0), make_handler(Store(out, log=lambda *a: None)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def test_pages_and_static_assets(base_url):
    for path in ("/", "/static/app.js", "/static/style.css", "/files/csv/zone.csv"):
        assert get(base_url + path)[0] == 200


def test_core_endpoints(base_url):
    s = json.loads(get(base_url + "/api/summary")[1])
    assert s["validation"]["failed"] == 0 and "OPT_PEAK_V2" in s["scenarios"]
    whs = json.loads(get(base_url + "/api/warehouses")[1])
    layout = json.loads(get(f"{base_url}/api/warehouses/{whs[0]['warehouse_id']}/layout?plan=OPT")[1])
    assert len(layout["locations"]) == whs[0]["location_count"]
    exc = json.loads(get(base_url + "/api/exceptions?exception_type=PICK_PATH_BLOCKED_AISLE")[1])
    assert exc["total"] > 0 and all(r["ground_truth"] for r in exc["rows"])


def test_proposal_check_matches_batch_engine(base_url):
    exc = json.loads(get(base_url + "/api/exceptions?exception_type=LOCATION_CAPACITY_EXCEEDED")[1])["rows"][0]
    sku, rest = exc["details"].split(" -> ")
    loc = rest.split(":")[0]
    r = json.loads(get(base_url + "/api/proposals/check",
                       {"warehouse_id": exc["warehouse_id"], "sku_id": sku, "location_id": loc})[1])
    assert r["decision"] == "REJECTED" and r["reasons"][0]["code"] == "LOCATION_CAPACITY_EXCEEDED"
    alt = r["alternatives"][0]["location_id"]
    ok = json.loads(get(base_url + "/api/proposals/submit",
                        {"warehouse_id": exc["warehouse_id"], "sku_id": sku, "location_id": alt,
                         "requested_by": "PLN-03"})[1])
    assert ok["decision"] == "APPROVED"
    again = json.loads(get(base_url + "/api/proposals/check",
                           {"warehouse_id": exc["warehouse_id"], "sku_id": sku, "location_id": alt})[1])
    assert "DUPLICATE_ACTIVE_LOCATION" in [x["code"] for x in again["reasons"]]   # approval occupies it


def test_actor_endpoints(base_url):
    whs = json.loads(get(base_url + "/api/warehouses")[1])
    wh = whs[0]["warehouse_id"]
    labor = json.loads(get(f"{base_url}/api/labor/{wh}")[1])
    assert labor["days"] and labor["all"]["days"] == len(labor["days"])
    busiest = max(labor["days"], key=lambda d: d["tasks"])
    day = json.loads(get(f"{base_url}/api/labor/{wh}?date={busiest['date']}")[1])
    assert len(day["tasks"]) == busiest["tasks"]
    assert round(sum(t["task_minutes"] for t in day["tasks"]), 2) == busiest["workload"]
    blocks = json.loads(get(base_url + "/api/aisle-blocks")[1])
    assert blocks["violations"] > 0 and blocks["held"] > 0 and blocks["late_reported"] > 0
    ship = json.loads(get(base_url + "/api/shipping")[1])
    assert {c["carrier_service"] for c in ship["carriers"]} >= {"PARCEL_GROUND", "LTL_FREIGHT"}
    sups = json.loads(get(base_url + "/api/suppliers")[1])
    detail = json.loads(get(f"{base_url}/api/suppliers/{sups[0]['supplier_id']}")[1])
    assert len(detail["items"]) >= sups[0]["skus"]


def test_rejects_traversal_and_unknown(base_url):
    for path in ("/files/..%2F..%2Fslotting%2Fconfig.py", "/api/skus/NOPE"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base_url + path)
        assert e.value.code == 404


def test_starting_page_answers_while_loading():
    """The port answers immediately with a self-refreshing page instead of refusing connections."""
    from inventryx.server import make_starting_handler
    state = {"status": "Loading the dataset..."}
    httpd = _Server(("127.0.0.1", 0), make_starting_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for path, marker in (("/", b"Inventryx is starting"), ("/api/summary", b'"starting"')):
            with pytest.raises(urllib.error.HTTPError) as e:
                get(url + path)
            assert e.value.code == 503 and marker in e.value.read()
        state["error"] = "Start-up failed: boom"
        with pytest.raises(urllib.error.HTTPError) as e:
            get(url + "/")
        assert e.value.code == 500 and b"boom" in e.value.read()
    finally:
        httpd.shutdown()
