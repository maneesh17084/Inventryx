"""End-to-end tests on a small dataset, plus mutation tests proving the validator catches corruption."""
import csv
import json
import shutil

import pytest

from inventryx import config as C
from inventryx.cli import generate
from inventryx.validate import validate

SMALL = dict(warehouses=2, locations=600, skus=300, order_lines=4000)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("data") / "small"
    validation, manifest = generate(C.resolve_scale("starter", **SMALL), C.DEFAULT_SEED, out, [], log=lambda *a: None)
    return out, validation, manifest


def test_generated_dataset_passes_all_checks(dataset):
    _, validation, _ = dataset
    failed = [c for c in validation["checks"] if c["status"] == "FAIL"]
    assert not failed, failed


def test_volumes_match_scale(dataset):
    _, _, manifest = dataset
    t = manifest["tables"]
    assert t["warehouse"]["rows"] == 2 and t["location"]["rows"] == 600 and t["sku"]["rows"] == 300
    assert t["order_line"]["rows"] == 4000


def test_every_edge_case_is_labelled(dataset):
    out, _, _ = dataset
    with open(out / "ground_truth" / "ground_truth.csv", newline="") as fh:
        issues = {r["issue_type"] for r in csv.DictReader(fh)}
    assert {"LOCATION_CAPACITY_EXCEEDED", "INCOMPATIBLE_CO_LOCATION", "STORAGE_CLASS_MISMATCH",
            "DUPLICATE_ACTIVE_LOCATION", "PICK_PATH_BLOCKED_AISLE", "REPLEN_LABOR_EXCEEDED", "NONE"} <= issues


def test_optimized_plan_beats_baseline(dataset):
    out, _, _ = dataset
    with open(out / "reports" / "scenario_summary.csv", newline="") as fh:
        s = {r["scenario"]: r for r in csv.DictReader(fh)}
    assert float(s["OPT_PEAK_V2"]["distance_m"]) < float(s["BASELINE_LEGACY"]["distance_m"])
    assert s["OPT_PEAK_V2"]["orders"] == s["BASELINE_LEGACY"]["orders"]       # same orders => comparable


def test_same_seed_is_byte_identical_and_other_seed_differs(dataset, tmp_path):
    out, _, manifest = dataset
    scale = C.resolve_scale("starter", **SMALL)
    _, again = generate(scale, C.DEFAULT_SEED, tmp_path / "again", [], log=lambda *a: None)
    assert {f["path"]: f["sha256"] for f in again["files"]} == {f["path"]: f["sha256"] for f in manifest["files"]}
    _, other = generate(scale, C.DEFAULT_SEED + 1, tmp_path / "other", [], log=lambda *a: None)
    sums = {f["path"]: f["sha256"] for f in manifest["files"]}
    assert any(sums[f["path"]] != f["sha256"] for f in other["files"] if f["path"] in sums)


def _mutate(src, dst, table, fn, folder="csv"):
    shutil.copytree(src, dst)
    path = dst / folder / f"{table}.csv"
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    rows = fn(rows)
    with open(path, "w", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    result, _, _ = validate(dst)
    return {c["category"] for c in result["checks"] if c["status"] == "FAIL"}


def _col(rows, name):
    return rows[0].index(name)


def test_detects_broken_foreign_key(dataset, tmp_path):
    def fn(rows):
        rows[1][_col(rows, "slot_id")] = "SLOT-2026-999999"
        return rows
    assert "foreign_key" in _mutate(dataset[0], tmp_path / "m", "pick_event", fn)


def test_detects_duplicate_primary_key(dataset, tmp_path):
    assert "primary_key" in _mutate(dataset[0], tmp_path / "m", "orders", lambda rows: rows + [rows[1]])


def test_detects_reconciliation_break(dataset, tmp_path):
    def fn(rows):
        i = _col(rows, "total_units")
        rows[1][i] = str(int(rows[1][i]) + 1)
        return rows
    assert "reconciliation" in _mutate(dataset[0], tmp_path / "m", "orders", fn)


def test_detects_overwritten_history(dataset, tmp_path):
    def fn(rows):
        i = _col(rows, "to_status")
        drop = next(k for k, r in enumerate(rows) if k and r[i] == "PICKED")
        return rows[:drop] + rows[drop + 1:]
    assert "lifecycle" in _mutate(dataset[0], tmp_path / "m", "state_event", fn)


def test_detects_double_booked_location(dataset, tmp_path):
    def fn(rows):
        st, loc, wh = _col(rows, "status"), _col(rows, "location_id"), _col(rows, "warehouse_id")
        active = [r for r in rows[1:] if r[st] == "ACTIVE"]
        a, b = next((x, y) for x in active for y in active if x is not y and x[wh] == y[wh])
        b[loc] = a[loc]
        return rows
    assert "duplicates" in _mutate(dataset[0], tmp_path / "m", "slot_assignment", fn)


def test_detects_label_drift(dataset, tmp_path):
    def fn(rows):
        i = _col(rows, "issue_type")
        drop = next(k for k, r in enumerate(rows) if k and r[i] == "LOCATION_CAPACITY_EXCEEDED")
        return rows[:drop] + rows[drop + 1:]
    assert "ground_truth" in _mutate(dataset[0], tmp_path / "m", "ground_truth", fn, folder="ground_truth")


def test_manifest_records_seed_and_command(dataset):
    out, _, _ = dataset
    m = json.loads((out / "manifest.json").read_text())
    assert m["seed"] == C.DEFAULT_SEED and "--seed" in m["command"] and m["files"]
