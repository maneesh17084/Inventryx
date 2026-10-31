"""Dataset validation, run against the exported CSVs (not in-memory state).

Categories: schema, primary_key, foreign_key, enum, join, date_order, reconciliation, lifecycle,
duplicates, physical_constraints, reproducibility, leakage, sql, ground_truth, distribution.
"""
import csv
import math
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from . import config as C
from . import engine
from .export import load_ground_truth, load_tables
from .rules import (capacity_issue, compat_key, fit_units, handling_seconds, incompatible_pairs, is_oversized,
                    reorder_point, replen_minutes, required_storage_class, route)
from .schema import LIFECYCLES, TABLES
from .simulation import simulate_replenishment

GT_TYPES = ("LOCATION_CAPACITY_EXCEEDED", "STORAGE_CLASS_MISMATCH", "INCOMPATIBLE_CO_LOCATION",
            "DUPLICATE_ACTIVE_LOCATION", "PICK_PATH_BLOCKED_AISLE", "REPLEN_LABOR_EXCEEDED")
LEAK_COLUMNS = {"issue_type", "ground_truth", "is_anomaly", "label", "expected_decision", "origin", "anomaly"}


class Results:
    def __init__(self):
        self.checks = []

    def check(self, category, name, violations, detail="", info=None):
        violations = list(violations)
        self.checks.append(dict(category=category, check=name, status="PASS" if not violations else "FAIL",
                                violations=len(violations), sample=[str(v) for v in violations[:5]],
                                detail=detail, info=info))

    def summary(self):
        by_cat = defaultdict(lambda: Counter())
        for c in self.checks:
            by_cat[c["category"]][c["status"]] += 1
        return dict(total=len(self.checks), passed=sum(c["status"] == "PASS" for c in self.checks),
                    failed=sum(c["status"] == "FAIL" for c in self.checks),
                    by_category={k: dict(v) for k, v in sorted(by_cat.items())}, checks=self.checks)


def _idx(rows, key):
    return {r[key]: r for r in rows}


def _close(a, b, tol=0.011):
    return a is not None and b is not None and abs(a - b) <= tol


def structural(t, R):
    for tb in TABLES:
        rows = t[tb.name]
        R.check("schema", f"{tb.name}: required fields populated",
                (f"{r[tb.pk[0]]}.{f.name}" for f in tb.fields if f.required for r in rows if r[f.name] is None))
        R.check("enum", f"{tb.name}: allowed values",
                (f"{r[tb.pk[0]]}.{f.name}={r[f.name]}" for f in tb.fields if f.enum for r in rows
                 if r[f.name] is not None and r[f.name] not in f.enum))
        pats = [(f, re.compile(f.pattern)) for f in tb.fields if f.pattern]
        R.check("schema", f"{tb.name}: ID / code formats",
                (f"{f.name}={r[f.name]}" for f, rx in pats for r in rows
                 if r[f.name] is not None and not rx.match(r[f.name])))
        pk = Counter(tuple(r[c] for c in tb.pk) for r in rows)
        R.check("primary_key", f"{tb.name}: primary key unique", (k for k, n in pk.items() if n > 1))
        for f in tb.fields:
            if f.unique and f.name not in tb.pk:
                cnt = Counter(r[f.name] for r in rows if r[f.name] is not None)
                R.check("duplicates", f"{tb.name}.{f.name}: unique", (k for k, n in cnt.items() if n > 1))
        for nk in tb.natural_keys:
            cnt = Counter(tuple(r[c] for c in nk) for r in rows)
            R.check("duplicates", f"{tb.name}: natural key {'+'.join(nk)} unique",
                    (k for k, n in cnt.items() if n > 1))


def foreign_keys(t, R):
    for tb in TABLES:
        for f in tb.fields:
            if not f.fk:
                continue
            ref_t, ref_c = f.fk.split(".")
            keys = {r[ref_c] for r in t[ref_t]}
            R.check("foreign_key", f"{tb.name}.{f.name} -> {f.fk}",
                    (f"{r[tb.pk[0]]}:{r[f.name]}" for r in t[tb.name]
                     if r[f.name] is not None and r[f.name] not in keys))


def joins(t, R):
    zone, aisle, loc = _idx(t["zone"], "zone_id"), _idx(t["aisle"], "aisle_id"), _idx(t["location"], "location_id")
    orders, lines, slots = _idx(t["orders"], "order_id"), _idx(t["order_line"], "order_line_id"), _idx(
        t["slot_assignment"], "slot_id")
    stock = {(w["warehouse_id"], w["sku_id"]) for w in t["warehouse_sku"]}
    R.check("join", "zone/aisle IDs embed their warehouse",
            [z["zone_id"] for z in t["zone"] if not z["zone_id"].startswith(z["warehouse_id"])] +
            [a["aisle_id"] for a in t["aisle"] if not a["aisle_id"].startswith(a["warehouse_id"]) or
             zone[a["zone_id"]]["warehouse_id"] != a["warehouse_id"]])
    R.check("join", "location: ID embeds zone, zone/aisle/warehouse consistent, bay_key and x derived",
            (l_["location_id"] for l_ in t["location"]
             if not l_["location_id"].startswith(f"LOC-{l_['zone_id']}-")
             or zone[l_["zone_id"]]["warehouse_id"] != l_["warehouse_id"]
             or aisle[l_["aisle_id"]]["zone_id"] != l_["zone_id"]
             or l_["bay_key"] != f"{l_['aisle_id']}-{l_['side']}-B{l_['bay']:02d}"
             or l_["x_m"] != aisle[l_["aisle_id"]]["x_m"]))
    R.check("join", "order_line: ID embeds order; SKU stocked at order's warehouse",
            (ln["order_line_id"] for ln in t["order_line"]
             if not ln["order_line_id"].startswith(ln["order_id"] + "-")
             or (orders[ln["order_id"]]["warehouse_id"], ln["sku_id"]) not in stock))
    bad = []
    for p in t["pick_event"]:
        ln, s, o = lines[p["order_line_id"]], slots[p["slot_id"]], orders[p["order_id"]]
        if (not p["pick_id"].startswith(f"PICK-{p['order_id']}-") or ln["order_id"] != p["order_id"]
                or ln["sku_id"] != p["sku_id"] or o["warehouse_id"] != p["warehouse_id"]
                or s["sku_id"] != p["sku_id"] or s["location_id"] != p["location_id"]
                or s["warehouse_id"] != p["warehouse_id"] or loc[p["location_id"]]["aisle_id"] != p["aisle_id"]):
            bad.append(p["pick_id"])
    R.check("join", "pick_event: order/line/SKU/slot/location/aisle all agree", bad)
    R.check("join", "replenishment: slot/SKU/location/warehouse agree",
            (r["replen_id"] for r in t["replenishment"]
             if slots[r["slot_id"]]["sku_id"] != r["sku_id"] or slots[r["slot_id"]]["location_id"] != r["location_id"]
             or slots[r["slot_id"]]["warehouse_id"] != r["warehouse_id"]))
    prof = _idx(t["sku_profile"], "profile_id")
    R.check("join", "slot_assignment: location in same warehouse; SKU stocked; profile matches",
            (s["slot_id"] for s in t["slot_assignment"]
             if loc[s["location_id"]]["warehouse_id"] != s["warehouse_id"]
             or (s["warehouse_id"], s["sku_id"]) not in stock
             or (s["profile_id"] and (prof[s["profile_id"]]["sku_id"], prof[s["profile_id"]]["warehouse_id"])
                 != (s["sku_id"], s["warehouse_id"]))))
    versions = sorted({p["version"] for p in t["sku_profile"]})
    have = {(p["warehouse_id"], p["sku_id"], p["version"]) for p in t["sku_profile"]}
    R.check("join", "sku_profile: exactly one profile per stocked warehouse-SKU per version",
            [k for k in ((w, s, v) for (w, s) in sorted(stock) for v in versions) if k not in have] +
            [p["profile_id"] for p in t["sku_profile"] if (p["warehouse_id"], p["sku_id"]) not in stock])
    R.check("join", "slot_candidate: selected candidate is the slot's location",
            (c["candidate_id"] for c in t["slot_candidate"]
             if c["selected"] != (c["slot_id"] is not None)
             or (c["slot_id"] and slots[c["slot_id"]]["location_id"] != c["location_id"])))
    caps = _idx(t["labor_capacity"], "labor_capacity_id")
    R.check("join", "replen_labor_daily: capacity record matches warehouse/date",
            (r["labor_day_id"] for r in t["replen_labor_daily"]
             if (caps[r["labor_capacity_id"]]["warehouse_id"], caps[r["labor_capacity_id"]]["work_date"])
             != (r["warehouse_id"], r["work_date"])))
    targets = {"ORDER": set(orders), "SLOT_ASSIGNMENT": set(slots), "REPLENISHMENT": {
        r["replen_id"] for r in t["replenishment"]}, "AISLE": set(aisle)}
    R.check("join", "state_event: polymorphic entity_id resolves",
            (e["event_id"] for e in t["state_event"] if e["entity_id"] not in targets[e["entity_type"]]))
    targets.update(PICK_EVENT={p["pick_id"] for p in t["pick_event"]}, SKU={s["sku_id"] for s in t["sku"]},
                   REPLEN_LABOR_DAY={r["labor_day_id"] for r in t["replen_labor_daily"]})
    R.check("join", "slotting_exception: entity_id resolves",
            (e["exception_id"] for e in t["slotting_exception"] if e["entity_id"] not in targets[e["entity_type"]]))
    return targets


def date_order(t, R):
    picks = defaultdict(list)
    for p in t["pick_event"]:
        picks[p["order_id"]].append(p["pick_ts"])
    bad = []
    for o in t["orders"]:
        if o["required_ship_ts"] <= o["order_ts"]:
            bad.append(o["order_id"])
        if o["status"] == "CANCELLED":
            if o["cancelled_ts"] is None or o["cancelled_ts"] < o["order_ts"] or o["order_id"] in picks:
                bad.append(o["order_id"])
            continue
        ps = picks[o["order_id"]]
        start = o["hold_release_ts"] or o["release_ts"]
        if not (o["order_ts"] <= o["release_ts"] <= start <= min(ps) <= max(ps) <= o["picked_ts"]):
            bad.append(o["order_id"])
        if o["shipped_ts"] and o["shipped_ts"] < o["picked_ts"]:
            bad.append(o["order_id"])
    R.check("date_order", "orders: order <= release <= (hold release) <= picks <= picked <= shipped", bad)
    R.check("date_order", "slot_assignment: effective_from < effective_to; created/decision ordering",
            (s["slot_id"] for s in t["slot_assignment"]
             if (s["effective_to"] and s["effective_to"] <= s["effective_from"])
             or s["created_ts"].date() > s["effective_from"]
             or (s["decision_ts"] and s["decision_ts"] < s["created_ts"])))
    R.check("date_order", "sku_profile: window_start <= window_end < effective_from < effective_to",
            (p["profile_id"] for p in t["sku_profile"]
             if not p["window_start"] <= p["window_end"] < p["effective_from"]
             or (p["effective_to"] and p["effective_to"] <= p["effective_from"])))
    R.check("date_order", "aisle_block: start < end",
            (b["block_id"] for b in t["aisle_block"] if b["start_ts"] >= b["end_ts"]))
    R.check("date_order", "replenishment: created <= completed",
            (r["replen_id"] for r in t["replenishment"] if r["created_ts"] > r["completed_ts"]))
    slots = _idx(t["slot_assignment"], "slot_id")
    R.check("date_order", "pick_event: slot in force on the pick date",
            (p["pick_id"] for p in t["pick_event"]
             if not (slots[p["slot_id"]]["effective_from"] <= p["pick_ts"].date()
                     and (slots[p["slot_id"]]["effective_to"] is None
                          or p["pick_ts"].date() < slots[p["slot_id"]]["effective_to"]))))
    sku = _idx(t["sku"], "sku_id")
    wh = _idx(t["warehouse"], "warehouse_id")
    R.check("date_order", "stocking starts after SKU creation; locations after warehouse opening",
            [f"{w['warehouse_id']}/{w['sku_id']}" for w in t["warehouse_sku"]
             if w["effective_from"] < sku[w["sku_id"]]["created_date"]] +
            [x["location_id"] for x in t["location"] if x["effective_from"] < wh[x["warehouse_id"]]["opened_date"]])


def reconciliation(t, R, path):
    cnt = lambda rows, k: Counter(r[k] for r in rows)  # noqa: E731
    lz, la, lw = cnt(t["location"], "zone_id"), cnt(t["aisle"], "zone_id"), cnt(t["location"], "warehouse_id")
    zw, aw = cnt(t["zone"], "warehouse_id"), cnt(t["aisle"], "warehouse_id")
    R.check("reconciliation", "warehouse/zone counts = COUNT(children)",
            [w["warehouse_id"] for w in t["warehouse"] if (w["location_count"], w["zone_count"], w["aisle_count"])
             != (lw[w["warehouse_id"]], zw[w["warehouse_id"]], aw[w["warehouse_id"]])] +
            [z["zone_id"] for z in t["zone"] if (z["location_count"], z["aisle_count"])
             != (lz[z["zone_id"]], la[z["zone_id"]])])
    golden = {"FLOW_RACK": {2, 3}, "SHELF": {2, 3}, "COLD_SHELF": {2, 3}, "FREEZER_SHELF": {2, 3},
              "HAZMAT_CABINET": {2}, "PALLET_RACK": {1}}
    R.check("reconciliation", "location: volume_l and is_golden_zone derived correctly",
            (x["location_id"] for x in t["location"]
             if not _close(x["volume_l"], x["width_cm"] * x["depth_cm"] * x["height_cm"] / 1000, 0.0011)
             or x["is_golden_zone"] != (x["level"] in golden[x["location_type"]])))
    R.check("reconciliation", "sku: volume, oversize flag and storage class derived correctly",
            (s["sku_id"] for s in t["sku"]
             if not _close(s["unit_volume_l"], s["length_cm"] * s["width_cm"] * s["height_cm"] / 1000, 0.0011)
             or s["is_oversized"] != is_oversized(s["length_cm"], s["width_cm"], s["height_cm"])
             or s["required_storage_class"] != required_storage_class(s["hazard_class"], s["temp_class"],
                                                                      s["is_oversized"])
             or (s["hazard_class"] != "NONE") != (s["compat_group"] == "HAZMAT")))
    lines_by_order, picks_by_order, picked = defaultdict(list), defaultdict(list), Counter()
    for ln in t["order_line"]:
        lines_by_order[ln["order_id"]].append(ln)
    for p in t["pick_event"]:
        picks_by_order[p["order_id"]].append(p)
        picked[p["order_line_id"]] += p["qty"]
    R.check("reconciliation", "orders: line_count and total_units = SUM(order_line)",
            (o["order_id"] for o in t["orders"] if o["line_count"] != len(lines_by_order[o["order_id"]])
             or o["total_units"] != sum(x["qty_ordered"] for x in lines_by_order[o["order_id"]])))
    R.check("reconciliation", "order_line: qty_picked = SUM(pick_event.qty); status consistent",
            (ln["order_line_id"] for ln in t["order_line"] if ln["qty_picked"] != picked[ln["order_line_id"]]
             or (ln["status"] == "PICKED") != (ln["qty_picked"] == ln["qty_ordered"] and ln["qty_picked"] > 0)))
    loc = _idx(t["location"], "location_id")
    aisle_no = {a["aisle_id"]: a["aisle_no"] for a in t["aisle"]}
    line_idx = _idx(t["order_line"], "order_line_id")
    bad = []
    for o in t["orders"]:
        ps = sorted(picks_by_order.get(o["order_id"], []), key=lambda p: p["pick_seq"])
        if not ps:
            continue
        stops = [dict(key=p["order_line_id"], aisle_no=aisle_no[p["aisle_id"]], x_m=loc[p["location_id"]]["x_m"],
                      y_m=loc[p["location_id"]]["y_m"], pid=p["pick_id"]) for p in ps]
        legs, back = route(stops)
        total = sum(p["travel_from_prev_m"] for p in ps) + o["return_to_depot_m"]
        if ([s["pid"] for s, _ in legs] != [p["pick_id"] for p in ps]
                or any(not _close(leg, p["travel_from_prev_m"], 0.005) for (_, leg), p in zip(legs, ps))
                or not _close(back, o["return_to_depot_m"], 0.005) or not _close(total, o["pick_distance_m"])
                or any(p["handling_s"] != handling_seconds(loc[p["location_id"]], line_idx[p["order_line_id"]]
                                                            ["qty_ordered"]) for p in ps)):
            bad.append(o["order_id"])
    R.check("reconciliation", "pick tours: sequence, legs, return leg and pick_distance_m re-derived by router", bad)

    sku = _idx(t["sku"], "sku_id")
    orders = _idx(t["orders"], "order_id")
    bad = []
    by_version = defaultdict(list)
    for p in t["sku_profile"]:
        by_version[p["version"]].append(p)
    for v, profs in by_version.items():
        ws, we = profs[0]["window_start"], profs[0]["window_end"]
        agg = defaultdict(lambda: [0, 0, set()])
        for ln in t["order_line"]:
            o = orders[ln["order_id"]]
            if o["status"] != "CANCELLED" and ws <= o["order_ts"].date() <= we:
                a = agg[(o["warehouse_id"], ln["sku_id"])]
                a[0] += 1
                a[1] += ln["qty_ordered"]
                a[2].add(o["order_ts"].date())
        for p in profs:
            n, u, act = agg.get((p["warehouse_id"], p["sku_id"]), (0, 0, set()))
            days = (we - ws).days + 1
            if (p["order_lines"], p["units_total"], p["active_days"], p["window_days"]) != (n, u, len(act), days) \
                    or not _close(p["lines_per_day"], n / days, 0.0001) \
                    or not _close(p["cube_l_per_day"], u / days * sku[p["sku_id"]]["unit_volume_l"], 0.002):
                bad.append(p["profile_id"])
    R.check("reconciliation", "sku_profile: lines, units, active days and rates re-derived from order lines", bad)

    slots = _idx(t["slot_assignment"], "slot_id")
    R.check("reconciliation", "slot_assignment: units_capacity = fit, reorder point = floor(0.30 x capacity)",
            (s["slot_id"] for s in t["slot_assignment"] if s["units_capacity"] is not None and (
                s["units_capacity"] != fit_units(sku[s["sku_id"]], loc[s["location_id"]])[0]
                or s["reorder_point_units"] != reorder_point(s["units_capacity"]))))
    R.check("reconciliation", "slot_candidate: total = pick + replen",
            (c["candidate_id"] for c in t["slot_candidate"]
             if not _close(c["total_cost_s_per_day"], c["pick_cost_s_per_day"] + c["replen_cost_s_per_day"], 0.002)))
    R.check("reconciliation", "replenishment: units = after - before; after = capacity; minutes re-derived",
            (r["replen_id"] for r in t["replenishment"]
             if r["units"] != r["onhand_after"] - r["onhand_before"]
             or r["onhand_after"] != slots[r["slot_id"]]["units_capacity"]
             or not _close(r["task_minutes"], replen_minutes(loc[r["location_id"]], r["units"]), 0.0001)))
    info = {s["slot_id"]: dict(location=loc[s["location_id"]], units_capacity=s["units_capacity"],
                               reorder_point_units=s["reorder_point_units"], warehouse_id=s["warehouse_id"],
                               sku_id=s["sku_id"], slot_id=s["slot_id"]) for s in t["slot_assignment"]}
    replay = simulate_replenishment(((p["slot_id"], p["pick_ts"], p["qty"]) for p in t["pick_event"]), info)
    stored = sorted(t["replenishment"], key=lambda r: r["replen_id"])
    mismatch = [r["replen_id"] for r, x in zip(stored, replay)
                if (r["slot_id"], r["created_ts"], r["units"], r["onhand_before"], r["replen_type"])
                != (x["slot_id"], x["created_ts"], x["units"], x["onhand_before"], x["replen_type"])]
    if len(stored) != len(replay):
        mismatch.append(f"count {len(stored)} != replay {len(replay)}")
    R.check("reconciliation", "replenishment: pick-face inventory balance replayed from pick events", mismatch)
    rows, statuses, _ = engine.labor_analysis(t)
    stored = _idx(t["replen_labor_daily"], "labor_day_id")
    R.check("reconciliation", "replen_labor_daily: workload, utilisation, status = SUM(replenishment) vs capacity",
            [r["labor_day_id"] for r in rows if any(
                not _close(r[k], stored[r["labor_day_id"]][k], 0.0001) if isinstance(r[k], float)
                else r[k] != stored[r["labor_day_id"]][k] for k in r)] +
            [r["replen_id"] for r in t["replenishment"] if r["labor_status"] != statuses[r["replen_id"]]])
    summary_path = path / "reports" / "scenario_summary.csv"
    if summary_path.exists():
        with open(summary_path, newline="", encoding="utf-8") as fh:
            scen = {r["scenario"]: r for r in csv.DictReader(fh)}
        lo, hi = C.HOLDOUT
        actual = round(sum(o["pick_distance_m"] for o in t["orders"]
                           if o["status"] != "CANCELLED" and lo <= o["order_ts"].date() <= hi), 2)
        actual_rep = sum(1 for r in t["replenishment"] if slots[r["slot_id"]]["plan_code"] == "OPT_PEAK_2026W42")
        issues = []
        if not _close(actual, float(scen["OPT_PEAK_V2"]["distance_m"]), 0.05):
            issues.append(f"distance {actual} != {scen['OPT_PEAK_V2']['distance_m']}")
        if actual_rep != int(scen["OPT_PEAK_V2"]["replen_tasks"]):
            issues.append(f"replen tasks {actual_rep} != {scen['OPT_PEAK_V2']['replen_tasks']}")
        R.check("reconciliation", "holdout: actual history == OPT_PEAK replay (distance, replen tasks)", issues)


def lifecycle(t, R):
    events = defaultdict(list)
    for e in t["state_event"]:
        events[(e["entity_type"], e["entity_id"])].append(e)
    bad_transition, bad_chain = [], []
    for (etype, eid), evs in events.items():
        evs.sort(key=lambda e: e["event_id"])
        prev = None if etype != "AISLE" else "ACTIVE"
        for e in evs:
            if (e["from_status"], e["to_status"]) not in LIFECYCLES[etype]:
                bad_transition.append(f"{e['event_id']} {e['from_status']}->{e['to_status']}")
            if e["from_status"] != prev:
                bad_chain.append(e["event_id"])
            prev = e["to_status"]
    R.check("lifecycle", "state_event: every transition is allowed by the entity lifecycle", bad_transition)
    R.check("lifecycle", "state_event: each from_status equals the previous to_status (no gaps)", bad_chain)
    ids_ = [e["event_id"] for e in t["state_event"]]
    R.check("lifecycle", "state_event: IDs are chronological (append-only log)",
            (ids_[i] for i in range(1, len(ids_)) if t["state_event"][i]["event_ts"] < t["state_event"][i - 1]
             ["event_ts"]))
    last = {k: v[-1]["to_status"] for k, v in events.items()}
    final = []
    for etype, table, key in (("ORDER", "orders", "order_id"), ("SLOT_ASSIGNMENT", "slot_assignment", "slot_id"),
                              ("REPLENISHMENT", "replenishment", "replen_id")):
        final += [r[key] for r in t[table] if last.get((etype, r[key])) != r["status"]]
    final += [a["aisle_id"] for a in t["aisle"] if last.get(("AISLE", a["aisle_id"]), "ACTIVE") != a["status"]]
    R.check("lifecycle", "current status column == last state_event (history not overwritten)", final)


def duplicates_and_physical(t, R):
    loc, sku = _idx(t["location"], "location_id"), _idx(t["sku"], "sku_id")
    zone_classes = defaultdict(set)
    for z in t["zone_storage_class"]:
        zone_classes[z["zone_id"]].add(z["storage_class_code"])
    pairs = incompatible_pairs(t["compatibility_rule"])
    committed = [s for s in t["slot_assignment"] if s["status"] in ("ACTIVE", "SUPERSEDED", "APPROVED")]

    def overlap(a, b):
        return (a["effective_to"] is None or a["effective_to"] > b["effective_from"]) and (
            b["effective_to"] is None or b["effective_to"] > a["effective_from"])

    def pairwise(groups):
        out = []
        for key, rows in groups.items():
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    if overlap(rows[i], rows[j]):
                        out.append(f"{key}: {rows[i]['slot_id']} & {rows[j]['slot_id']}")
        return out

    by_loc, by_sku = defaultdict(list), defaultdict(list)
    for s in committed:
        by_loc[s["location_id"]].append(s)
        if s["status"] != "APPROVED":
            by_sku[(s["warehouse_id"], s["sku_id"])].append(s)
    R.check("duplicates", "no two committed assignments hold one location at the same time", pairwise(by_loc))
    R.check("duplicates", "one live slot per warehouse-SKU at any time (approved moves excluded)", pairwise(by_sku))
    ev = Counter((e["entity_type"], e["entity_id"], e["from_status"], e["to_status"], e["event_ts"])
                 for e in t["state_event"])
    R.check("duplicates", "state_event: no duplicated transitions", (k for k, n in ev.items() if n > 1))
    R.check("physical_constraints", "committed slots: SKU fits (dimensions, weight, max_order_qty)",
            (f"{s['slot_id']}:{capacity_issue(sku[s['sku_id']], loc[s['location_id']])[0]}" for s in committed
             if capacity_issue(sku[s["sku_id"]], loc[s["location_id"]])[0]))
    R.check("physical_constraints", "committed slots: zone provides the SKU's storage class; location ACTIVE",
            (s["slot_id"] for s in committed
             if sku[s["sku_id"]]["required_storage_class"] not in zone_classes[loc[s["location_id"]]["zone_id"]]
             or loc[s["location_id"]]["status"] != "ACTIVE"))
    by_bay = defaultdict(list)
    for s in committed:
        by_bay[loc[s["location_id"]]["bay_key"]].append(s)
    clashes = []
    for bay, rows in by_bay.items():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if overlap(a, b) and frozenset((compat_key(sku[a["sku_id"]]), compat_key(sku[b["sku_id"]]))) in pairs:
                    clashes.append(f"{bay}: {a['slot_id']} & {b['slot_id']}")
    R.check("physical_constraints", "committed slots: no incompatible goods share a bay", clashes)


def reproducibility(t, R):
    decisions, exc = engine.decide_proposals(t)
    slots = _idx(t["slot_assignment"], "slot_id")
    R.check("reproducibility", "engine re-run on CSVs reproduces every proposal decision",
            (sid for sid, d in decisions.items()
             if (slots[sid]["status"], slots[sid]["decision_reason"]) != (d["status"], d["decision_reason"])))
    exc += engine.detect_blocked_aisle_picks(t) + engine.labor_analysis(t)[2] + engine.deferral_exceptions(t)
    recomputed = {(e["exception_type"], e["entity_id"]) for e in exc}
    stored = {(e["exception_type"], e["entity_id"]) for e in t["slotting_exception"]
              if e["exception_type"] != "NO_FEASIBLE_SLOT"}
    R.check("reproducibility", "detectors re-run on CSVs reproduce slotting_exception",
            sorted(recomputed ^ stored))


def leakage(t, R, path):
    R.check("leakage", "no label/ground-truth columns in any input or derived table",
            (f"{tb.name}.{c}" for tb in TABLES for c in tb.columns if c in LEAK_COLUMNS))
    R.check("leakage", "ground truth stored only under ground_truth/",
            (p.as_posix() for p in (path / "csv").glob("*") if "truth" in p.name))


def sql_load(t, R, path):
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    errors = []
    try:
        con.executescript((path / "sql" / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((path / "sql" / "seed.sql").read_text(encoding="utf-8"))
        errors += [f"fk violation {r}" for r in con.execute("PRAGMA foreign_key_check").fetchall()[:20]]
        for tb in TABLES:
            n = con.execute(f"SELECT COUNT(*) FROM {tb.name}").fetchone()[0]
            if n != len(t[tb.name]):
                errors.append(f"{tb.name}: {n} rows in SQL vs {len(t[tb.name])} in CSV")
    except sqlite3.Error as e:
        errors.append(str(e))
    con.close()
    R.check("sql", "schema.sql + seed.sql load into SQLite with FK enforcement; row counts match CSV", errors)


def ground_truth_eval(t, R, gt, targets):
    R.check("ground_truth", "every ground-truth entity exists in the dataset",
            (g["gt_id"] for g in gt if g["entity_id"] not in targets.get(g["entity_type"], set())))
    flagged = defaultdict(set)
    for e in t["slotting_exception"]:
        flagged[e["exception_type"]].add(e["entity_id"])
    all_flagged = {e["entity_id"] for e in t["slotting_exception"] if e["exception_type"] in GT_TYPES}
    metrics = {}
    for kind in GT_TYPES:
        pos = {g["entity_id"] for g in gt if g["issue_type"] == kind}
        f = flagged[kind]
        tp, fp, fn = len(pos & f), len(f - pos), len(pos - f)
        metrics[kind] = dict(positives=len(pos), flagged=len(f), tp=tp, fp=fp, fn=fn,
                             precision=round(tp / (tp + fp), 4) if tp + fp else None,
                             recall=round(tp / (tp + fn), 4) if tp + fn else None)
        R.check("ground_truth", f"{kind}: engine flags == ground truth (precision & recall = 1)",
                [f"FN {x}" for x in sorted(pos - f)] + [f"FP {x}" for x in sorted(f - pos)],
                info=metrics[kind])
    controls = [g for g in gt if g["issue_type"] == "NONE"]
    wrong = [g["entity_id"] for g in controls if g["entity_id"] in all_flagged]
    metrics["NEGATIVE_CONTROLS"] = dict(controls=len(controls), false_alarms=len(wrong),
                                        specificity=round(1 - len(wrong) / len(controls), 4) if controls else None)
    R.check("ground_truth", "negative and boundary controls raise no exception", wrong,
            info=metrics["NEGATIVE_CONTROLS"])
    slots = _idx(t["slot_assignment"], "slot_id")
    dec = {"REJECT_PROPOSAL": "REJECTED", "APPROVE_PROPOSAL": "APPROVED"}
    R.check("ground_truth", "proposal decisions match expected_decision",
            (g["gt_id"] for g in gt if g["entity_type"] == "SLOT_ASSIGNMENT"
             and slots[g["entity_id"]]["status"] != dec[g["expected_decision"]]))
    return metrics


def distribution(t, R):
    """Realism guards - fail if the generator drifts out of plausible ranges."""
    orders = _idx(t["orders"], "order_id")
    per_wh = defaultdict(Counter)
    day_lines = Counter()
    for ln in t["order_line"]:
        o = orders[ln["order_id"]]
        per_wh[o["warehouse_id"]][ln["sku_id"]] += 1
        day_lines[o["order_ts"].date()] += 1
    shares = []
    for c in per_wh.values():
        vals = sorted(c.values(), reverse=True)
        top = vals[: max(1, math.ceil(0.2 * len(vals)))]
        shares.append(sum(top) / sum(vals))
    pareto = round(sum(shares) / len(shares), 3)
    base = [n for d, n in day_lines.items() if d < C.PEAK_START]
    peak = [n for d, n in day_lines.items() if d >= C.PEAK_START]
    lift = round((sum(peak) / len(peak)) / (sum(base) / len(base)), 3)
    wkend = [n for d, n in day_lines.items() if d.weekday() >= 5]
    wkday = [n for d, n in day_lines.items() if d.weekday() < 5]
    weekend_ratio = round((sum(wkend) / len(wkend)) / (sum(wkday) / len(wkday)), 3)
    skus = t["sku"]
    share = lambda f: round(sum(1 for s in skus if f(s)) / len(skus), 4)  # noqa: E731
    stats = dict(top20_sku_line_share=pareto, peak_volume_lift=lift, weekend_weekday_ratio=weekend_ratio,
                 oversized_share=share(lambda s: s["is_oversized"]),
                 hazmat_share=share(lambda s: s["hazard_class"] != "NONE"),
                 cold_chain_share=share(lambda s: s["temp_class"] != "AMBIENT"),
                 class_d_profiles=sum(1 for p in t["sku_profile"] if p["velocity_class"] == "D"),
                 peak_up_trends=sum(1 for p in t["sku_profile"] if p["demand_trend"] == "PEAK_UP"),
                 down_trends=sum(1 for p in t["sku_profile"] if p["demand_trend"] == "DOWN"))
    ranges = dict(top20_sku_line_share=(0.55, 0.95), peak_volume_lift=(1.2, 1.7), weekend_weekday_ratio=(0.5, 0.85),
                  oversized_share=(0.03, 0.12), hazmat_share=(0.03, 0.09), cold_chain_share=(0.12, 0.25),
                  class_d_profiles=(1, 10 ** 9), peak_up_trends=(1, 10 ** 9), down_trends=(1, 10 ** 9))
    for k, (lo, hi) in ranges.items():
        R.check("distribution", f"{k} within [{lo}, {hi if hi < 10 ** 9 else 'inf'}]",
                [] if lo <= stats[k] <= hi else [f"{k}={stats[k]}"], info={k: stats[k]})
    return stats


def validate(path: Path):
    path = Path(path)
    R = Results()
    t, load_errors = load_tables(path)
    R.check("schema", "CSV headers match schema; every value parses to its declared type", load_errors)
    gt = load_ground_truth(path)

    def guarded(category, fn, *args, default=None):
        # Corrupt data (e.g. a dangling FK) must surface as a failed check, not a crash.
        try:
            return fn(*args)
        except (KeyError, TypeError, ValueError, AttributeError, StopIteration, ZeroDivisionError) as e:
            R.check(category, f"{fn.__name__} could not complete on this data", [f"{type(e).__name__}: {e}"])
            return default

    guarded("schema", structural, t, R)
    guarded("foreign_key", foreign_keys, t, R)
    targets = guarded("join", joins, t, R, default={})
    guarded("date_order", date_order, t, R)
    guarded("reconciliation", reconciliation, t, R, path)
    guarded("lifecycle", lifecycle, t, R)
    guarded("duplicates", duplicates_and_physical, t, R)
    guarded("reproducibility", reproducibility, t, R)
    guarded("leakage", leakage, t, R, path)
    guarded("sql", sql_load, t, R, path)
    gt_metrics = guarded("ground_truth", ground_truth_eval, t, R, gt, targets, default={})
    dist = guarded("distribution", distribution, t, R, default={})
    out = R.summary()
    out["ground_truth_metrics"] = gt_metrics
    out["distribution"] = dist
    return out, t, gt
