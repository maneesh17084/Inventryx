"""Slotting decision engine and exception detectors.

Pure functions over the exported tables (no generator state, no ground truth), so the same code
runs inside the pipeline and later against the CSVs to prove decisions are reproducible.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from . import ids
from .rules import RULE_IDS, compat_key, incompatible_pairs, location_conflicts, reorder_point, fit_units

SEVERITY = {"LOCATION_CAPACITY_EXCEEDED": "WARNING", "STORAGE_CLASS_MISMATCH": "CRITICAL",
            "INCOMPATIBLE_CO_LOCATION": "CRITICAL", "DUPLICATE_ACTIVE_LOCATION": "WARNING",
            "PICK_PATH_BLOCKED_AISLE": "CRITICAL", "REPLEN_LABOR_EXCEEDED": "WARNING",
            "ORDER_DEFERRED_BLOCKED_AISLE": "INFO", "NO_FEASIBLE_SLOT": "WARNING"}
ACTION = {"LOCATION_CAPACITY_EXCEEDED": "REJECT_PROPOSAL", "STORAGE_CLASS_MISMATCH": "REJECT_PROPOSAL",
          "INCOMPATIBLE_CO_LOCATION": "REJECT_PROPOSAL", "DUPLICATE_ACTIVE_LOCATION": "REJECT_PROPOSAL",
          "PICK_PATH_BLOCKED_AISLE": "ESCALATE_SAFETY_AUDIT", "REPLEN_LABOR_EXCEEDED": "SCHEDULE_OVERTIME_OR_DEFER",
          "ORDER_DEFERRED_BLOCKED_AISLE": "DEFER_ORDER", "NO_FEASIBLE_SLOT": "MANUAL_REVIEW"}
COMMITTED = ("ACTIVE", "SUPERSEDED", "APPROVED")


def _exc(kind, entity_type, entity_id, wh, ts, details):
    return dict(exception_id=None, exception_type=kind, severity=SEVERITY[kind], entity_type=entity_type,
                entity_id=entity_id, warehouse_id=wh, rule_id=RULE_IDS[kind], detected_ts=ts, action=ACTION[kind],
                details=details)


def _live(slot, on):
    """True when the slot overlaps an open-ended period starting on `on`."""
    return slot["effective_to"] is None or slot["effective_to"] > on


def decide_proposals(tables):
    """Evaluate planner overrides in arrival order. Returns ({slot_id: decision}, exceptions)."""
    pairs = incompatible_pairs(tables["compatibility_rule"])
    loc = {x["location_id"]: x for x in tables["location"]}
    sku = {x["sku_id"]: x for x in tables["sku"]}
    zone_classes = defaultdict(set)
    for z in tables["zone_storage_class"]:
        zone_classes[z["zone_id"]].add(z["storage_class_code"])
    by_loc, by_bay = defaultdict(list), defaultdict(list)

    def commit(s):
        by_loc[s["location_id"]].append(s)
        by_bay[loc[s["location_id"]]["bay_key"]].append(s)

    for s in tables["slot_assignment"]:
        if s["assignment_source"] != "PLANNER_OVERRIDE" and s["status"] in COMMITTED:
            commit(s)
    proposals = sorted((s for s in tables["slot_assignment"] if s["assignment_source"] == "PLANNER_OVERRIDE"),
                       key=lambda s: (s["created_ts"], s["slot_id"]))
    decisions, exceptions = {}, []
    for p in proposals:
        eff, L, S = p["effective_from"], loc[p["location_id"]], sku[p["sku_id"]]
        occupants = [s for s in by_loc[L["location_id"]] if _live(s, eff)]
        neighbours = [dict(sku_id=s["sku_id"], compat_key=compat_key(sku[s["sku_id"]]))
                      for s in by_bay[L["bay_key"]] if _live(s, eff) and s["sku_id"] != p["sku_id"]]
        issues = location_conflicts(S, L, occupants, neighbours, pairs, zone_classes[L["zone_id"]])
        decided = p["created_ts"] + timedelta(minutes=5)
        if issues:
            decisions[p["slot_id"]] = dict(status="REJECTED", decision_ts=decided,
                                           decision_reason="REJECTED: " + ";".join(sorted(issues)),
                                           units_capacity=None, reorder_point_units=None)
            for kind in sorted(issues):
                exceptions.append(_exc(kind, "SLOT_ASSIGNMENT", p["slot_id"], p["warehouse_id"], decided,
                                       f"{p['sku_id']} -> {p['location_id']}: {issues[kind]}"))
        else:
            units = fit_units(S, L)[0]
            decisions[p["slot_id"]] = dict(status="APPROVED", decision_ts=decided,
                                           decision_reason="APPROVED: all placement rules passed",
                                           units_capacity=units, reorder_point_units=reorder_point(units))
            commit(dict(p, status="APPROVED"))
    return decisions, exceptions


def detect_blocked_aisle_picks(tables):
    """R-05: a pick confirmed inside an aisle while that aisle was blocked [start, end)."""
    by_aisle = defaultdict(list)
    for b in tables["aisle_block"]:
        by_aisle[b["aisle_id"]].append(b)
    out = []
    for p in tables["pick_event"]:
        for b in by_aisle.get(p["aisle_id"], ()):
            if b["start_ts"] <= p["pick_ts"] < b["end_ts"]:
                out.append(_exc("PICK_PATH_BLOCKED_AISLE", "PICK_EVENT", p["pick_id"], p["warehouse_id"],
                                max(b["reported_ts"], p["pick_ts"]),
                                f"{p['aisle_id']} blocked by {b['block_id']} {b['start_ts']:%H:%M}-{b['end_ts']:%H:%M}"
                                f"; pick at {p['pick_ts']:%H:%M:%S}"))
    return out


def labor_analysis(tables):
    """R-06: per warehouse-day replenishment workload vs capacity.

    Returns (replen_labor_daily rows, {replen_id: labor_status}, exceptions)."""
    tasks = defaultdict(list)
    for t in tables["replenishment"]:
        tasks[(t["warehouse_id"], t["created_ts"].date())].append(t)
    rows, statuses, exceptions = [], {}, []
    for cap in sorted(tables["labor_capacity"], key=lambda c: (c["warehouse_id"], c["work_date"])):
        key = (cap["warehouse_id"], cap["work_date"])
        day = sorted(tasks.get(key, ()), key=lambda t: (t["created_ts"], t["replen_id"]))
        limit = cap["replen_capacity_min"]
        cum = 0.0
        for t in day:
            cum = round(cum + t["task_minutes"], 2)
            statuses[t["replen_id"]] = "OVER_CAPACITY" if cum > limit else "WITHIN_CAPACITY"
        load = round(sum(t["task_minutes"] for t in day), 2)
        rid = ids.labor_day_id(*key)
        exceeded = load > limit
        rows.append(dict(labor_day_id=rid, warehouse_id=key[0], work_date=key[1],
                         labor_capacity_id=cap["labor_capacity_id"], task_count=len(day),
                         emergency_count=sum(t["replen_type"] == "EMERGENCY" for t in day), workload_min=load,
                         capacity_min=limit, utilization_pct=round(load / limit * 100, 2) if limit else 0.0,
                         over_capacity_min=round(max(0.0, load - limit), 2),
                         status="EXCEEDED" if exceeded else "WITHIN_CAPACITY"))
        if exceeded:
            d = key[1]
            exceptions.append(_exc("REPLEN_LABOR_EXCEEDED", "REPLEN_LABOR_DAY", rid, key[0],
                                   datetime(d.year, d.month, d.day, 23, 59),
                                   f"workload {load:.2f} min > capacity {limit:.2f} min ({cap['capacity_reason']}); "
                                   f"{len(day)} tasks"))
    return rows, statuses, exceptions


def deferral_exceptions(tables):
    """R-07 (handled exception path): orders held because their tour crossed a known blocked aisle."""
    return [_exc("ORDER_DEFERRED_BLOCKED_AISLE", "ORDER", o["order_id"], o["warehouse_id"], o["release_ts"],
                 f"held for {o['hold_block_id']} until {o['hold_release_ts']:%Y-%m-%d %H:%M}")
            for o in tables["orders"] if o["hold_block_id"]]


def number_exceptions(exceptions):
    exceptions.sort(key=lambda e: (e["detected_ts"], e["exception_type"], e["entity_id"]))
    for n, e in enumerate(exceptions, 1):
        e["exception_id"] = ids.exception_id(n)
    return exceptions
