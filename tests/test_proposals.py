"""Durable proposal log: persistence across restarts, append-only history, withdrawal, robustness."""
import json
import threading

import pytest

from inventryx import config as C
from inventryx.cli import generate
from inventryx.server import Store

QUIET = dict(log=lambda *a: None)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("prop") / "small"
    generate(C.resolve_scale("starter", warehouses=2, locations=600, skus=300, order_lines=4000), C.DEFAULT_SEED,
             out, [], log=lambda *a: None)
    return out


def _free_valid_target(store):
    """A SKU and a location the engine approves, taken from its own alternatives list."""
    exc = next(e for e in store.t["slotting_exception"] if e["exception_type"] == "LOCATION_CAPACITY_EXCEEDED")
    sku, rest = exc["details"].split(" -> ")
    body = dict(warehouse_id=exc["warehouse_id"], sku_id=sku, location_id=rest.split(":")[0])
    assert store.check_proposal(dict(body, location_id="LOC-NOPE")).get("error")   # refused, not crashed
    return dict(body, location_id=store.check_proposal(body)["alternatives"][0]["location_id"])


def test_approved_proposal_survives_restart_and_blocks_location(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = dict(_free_valid_target(store), requested_by="PLN-02", note="closer to dock")
    first = store.check_proposal(body, submit=True)
    assert first["decision"] == "APPROVED"
    rec = first["recorded"]
    max_dataset_slot = max(int(s["slot_id"][-6:]) for s in store.t["slot_assignment"])
    assert int(rec["slot_id"][-6:]) == max_dataset_slot + 1 and rec["requested_by"] == "PLN-02"

    restarted = Store(dataset, state_dir=tmp_path, **QUIET)
    p = restarted.proposals.proposals[rec["slot_id"]]
    assert p["status"] == "APPROVED" and p["decision_ts"] and p["units_capacity"]
    again = restarted.check_proposal(dict(body, sku_id=body["sku_id"]))
    assert "DUPLICATE_ACTIVE_LOCATION" in [x["code"] for x in again["reasons"]]
    nxt = restarted.check_proposal(dict(body, requested_by="PLN-04"), submit=True)
    assert nxt["decision"] == "REJECTED" and int(nxt["recorded"]["slot_id"][-6:]) == max_dataset_slot + 2


def test_withdrawal_is_a_new_event_and_frees_the_location(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = dict(_free_valid_target(store), requested_by="PLN-05")
    sid = store.check_proposal(body, submit=True)["recorded"]["slot_id"]
    log_path = store.proposals.path
    before = log_path.read_text(encoding="utf-8").splitlines()

    assert store.withdraw_proposal(sid, dict(requested_by="PLN-05", reason="plan changed"))["recorded"]["status"] \
        == "WITHDRAWN"
    after = log_path.read_text(encoding="utf-8").splitlines()
    assert after[:len(before)] == before and len(after) == len(before) + 1          # append-only
    assert [json.loads(x)["event"] for x in after] == ["PROPOSAL_SUBMITTED", "PROPOSAL_DECIDED", "PROPOSAL_WITHDRAWN"]

    restarted = Store(dataset, state_dir=tmp_path, **QUIET)
    assert restarted.proposals.proposals[sid]["status"] == "WITHDRAWN"
    assert restarted.check_proposal(body)["decision"] == "APPROVED"                  # location free again
    assert restarted.withdraw_proposal(sid, dict(requested_by="PLN-05")).get("error")  # cannot withdraw twice
    assert restarted.withdraw_proposal("SLOT-2026-999999", dict(requested_by="PLN-05")) is None


def test_invalid_submission_writes_nothing(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = _free_valid_target(store)
    assert store.check_proposal(dict(body, requested_by="bob"), submit=True).get("error")
    assert store.check_proposal(dict(body, sku_id="SKU-999999", requested_by="PLN-01"), submit=True).get("error")
    assert not store.proposals.path.exists() or store.proposals.path.read_text() == ""


def test_corrupt_line_is_skipped_not_fatal(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    sid = store.check_proposal(dict(_free_valid_target(store), requested_by="PLN-01"), submit=True)["recorded"]["slot_id"]
    with open(store.proposals.path, "a", encoding="utf-8") as fh:
        fh.write('{"event": "PROPOSAL_SUBM')          # torn write from a crash
    restarted = Store(dataset, state_dir=tmp_path, **QUIET)
    assert restarted.proposals.proposals[sid]["status"] == "APPROVED"
    assert len(restarted.proposals.skipped) == 1


def test_concurrent_submissions_cannot_double_book(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = _free_valid_target(store)
    results = []
    threads = [threading.Thread(target=lambda n=n: results.append(
        store.check_proposal(dict(body, requested_by=f"PLN-0{n}"), submit=True)["decision"])) for n in range(1, 7)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count("APPROVED") == 1 and results.count("REJECTED") == 5
