"""Effective-date handling for interactive proposals: conflicts are period overlaps, not 'anything approved'."""
from datetime import date

import pytest

from inventryx import config as C
from inventryx.cli import generate
from inventryx.server import Store, overlaps

QUIET = dict(log=lambda *a: None)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("dates") / "small"
    generate(C.resolve_scale("starter", warehouses=2, locations=600, skus=300, order_lines=4000), C.DEFAULT_SEED,
             out, [], log=lambda *a: None)
    return out


def _target(store):
    exc = next(e for e in store.t["slotting_exception"] if e["exception_type"] == "LOCATION_CAPACITY_EXCEEDED")
    sku, rest = exc["details"].split(" -> ")
    body = dict(warehouse_id=exc["warehouse_id"], sku_id=sku, location_id=rest.split(":")[0])
    return dict(body, location_id=store.check_proposal(body)["alternatives"][0]["location_id"])


def _codes(r):
    return [x["code"] for x in r["reasons"]]


@pytest.mark.parametrize("a,b,expected", [
    (("2026-12-01", None), ("2026-11-01", "2026-12-01"), False),   # ends exactly when the other starts
    (("2026-12-01", None), ("2026-11-01", "2026-12-02"), True),
    (("2026-12-01", None), ("2026-11-01", None), True),            # open-ended runs into December
    (("2026-11-01", "2026-12-01"), ("2026-12-01", None), False),
    (("2026-11-01", "2026-11-15"), ("2026-11-10", "2026-11-20"), True),
])
def test_overlap_is_half_open(a, b, expected):
    d = lambda s: s and date.fromisoformat(s)  # noqa: E731
    assert overlaps(d(a[0]), d(a[1]), d(b[0]), d(b[1])) is expected
    assert overlaps(d(b[0]), d(b[1]), d(a[0]), d(a[1])) is expected


def test_future_approval_does_not_block_an_earlier_bounded_assignment(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = dict(_target(store), requested_by="PLN-01")
    dec = store.check_proposal(dict(body, effective_from="2026-12-01"), submit=True)
    assert dec["decision"] == "APPROVED"

    # November -> December 1 (exclusive) ends before the December assignment starts: allowed.
    nov = store.check_proposal(dict(body, effective_from="2026-11-01", effective_to="2026-12-01"))
    assert nov["decision"] == "APPROVED", nov["reasons"]
    # One day longer overlaps December 1: rejected, and the reason names the conflicting period.
    longer = store.check_proposal(dict(body, effective_from="2026-11-01", effective_to="2026-12-02"))
    assert "DUPLICATE_ACTIVE_LOCATION" in _codes(longer)
    assert "2026-12-01" in longer["reasons"][0]["detail"]
    # Open-ended November would hold the location in December too: rejected (otherwise double-booked).
    assert "DUPLICATE_ACTIVE_LOCATION" in _codes(store.check_proposal(dict(body, effective_from="2026-11-01")))
    # Starting after a bounded approval ends is fine.
    assert store.check_proposal(dict(body, effective_from="2026-11-01", effective_to="2026-12-01"), submit=True)[
        "decision"] == "APPROVED"


def test_bounded_periods_survive_restart(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = dict(_target(store), requested_by="PLN-02")
    rec = store.check_proposal(dict(body, effective_from="2026-11-01", effective_to="2026-11-15"), submit=True)
    assert rec["decision"] == "APPROVED"

    restarted = Store(dataset, state_dir=tmp_path, **QUIET)
    p = restarted.proposals.proposals[rec["recorded"]["slot_id"]]
    assert str(p["effective_to"]) == "2026-11-15"
    assert restarted.check_proposal(dict(body, effective_from="2026-11-15"))["decision"] == "APPROVED"
    assert "DUPLICATE_ACTIVE_LOCATION" in _codes(restarted.check_proposal(dict(body, effective_from="2026-11-14")))


def test_end_date_must_follow_start(dataset, tmp_path):
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    body = dict(_target(store), requested_by="PLN-03")
    for end in ("2026-11-01", "2026-10-01", "not-a-date"):
        r = store.check_proposal(dict(body, effective_from="2026-11-01", effective_to=end), submit=True)
        assert r.get("error")
    assert not store.proposals.proposals


def test_generated_history_respects_dates(dataset, tmp_path):
    """A proposal that ends before the optimized plan went live cannot collide with that plan's slots."""
    store = Store(dataset, state_dir=tmp_path, **QUIET)
    opt = next(s for s in store.t["slot_assignment"] if s["plan_code"] == "OPT_PEAK_2026W42")
    legacy_here = [s for s in store.t["slot_assignment"]
                   if s["location_id"] == opt["location_id"] and s["plan_code"] == "LEGACY_2026H2"]
    body = dict(warehouse_id=opt["warehouse_id"], sku_id=opt["sku_id"], location_id=opt["location_id"],
                effective_from="2026-10-01", effective_to="2026-10-15")
    held = [s["slot_id"] for s in store.committed_during(date(2026, 10, 1), date(2026, 10, 15))
            if s["location_id"] == opt["location_id"]]
    assert opt["slot_id"] not in held                         # starts 2026-10-15, after the window
    assert held == [s["slot_id"] for s in legacy_here]        # only the legacy occupant, if any
    r = store.check_proposal(body)
    assert ("DUPLICATE_ACTIVE_LOCATION" in _codes(r)) == bool(legacy_here)
