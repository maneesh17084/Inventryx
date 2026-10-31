"""Labelled edge-case injection.

Baseline records are generated valid first; this module then adds *new* records (planner override
proposals, late-reported aisle blocks, reduced labor capacity) that trigger exactly one documented
rule each, plus negative/boundary controls. Labels go to ground_truth only - never into input tables.
"""
import bisect
import math
from collections import defaultdict
from datetime import datetime, timedelta

from . import config as C
from . import ids
from .rules import compat_key, fit_units, location_conflicts


def _gt(issue, entity_type, entity_id, wh, decision, origin="INJECTED", note=""):
    return dict(issue_type=issue, entity_type=entity_type, entity_id=entity_id, warehouse_id=wh,
                expected_decision=decision, label="POSITIVE" if issue != "NONE" else "NEGATIVE_CONTROL",
                origin=origin, note=note)


class ProposalState:
    """Occupancy/bay view at OVERRIDE_EFFECTIVE, updated as proposals are approved."""

    def __init__(self, tables, active_slots, pairs):
        self.pairs = pairs
        self.loc = {loc["location_id"]: loc for loc in tables["location"]}
        self.sku = {s["sku_id"]: s for s in tables["sku"]}
        self.zone_classes = defaultdict(set)
        for z in tables["zone_storage_class"]:
            self.zone_classes[z["zone_id"]].add(z["storage_class_code"])
        self.occupants = defaultdict(list)
        self.bay = defaultdict(list)
        self.current = {}
        for s in active_slots:
            self._occupy(s)
            self.current[(s["warehouse_id"], s["sku_id"])] = s["slot_id"]
        self.locs_by_wh = defaultdict(list)
        for loc in tables["location"]:
            if loc["status"] == "ACTIVE":
                self.locs_by_wh[loc["warehouse_id"]].append(loc)
        self.stock = defaultdict(list)
        for ws in tables["warehouse_sku"]:
            self.stock[ws["warehouse_id"]].append(ws["sku_id"])

    def _occupy(self, s):
        loc = self.loc[s["location_id"]]
        self.occupants[loc["location_id"]].append(s)
        self.bay[loc["bay_key"]].append(dict(sku_id=s["sku_id"], compat_key=compat_key(self.sku[s["sku_id"]])))

    def issues(self, sku_id, location_id):
        sku, loc = self.sku[sku_id], self.loc[location_id]
        neighbours = [n for n in self.bay[loc["bay_key"]] if n["sku_id"] != sku_id]
        return location_conflicts(sku, loc, self.occupants[location_id], neighbours, self.pairs,
                                  self.zone_classes[loc["zone_id"]])

    def approve(self, proposal):
        self._occupy(proposal)


def inject_proposals(scale, seed, tables, active_slots, pairs, next_slot_no):
    r = ids.stream(seed, "anomaly.proposals")
    st = ProposalState(tables, active_slots, pairs)
    wh_ids = sorted(st.stock)
    n_boundary = max(1, scale.valid_controls // 5)
    n_double = scale.duplicate_cases // 3
    plan = (["CAPACITY"] * scale.capacity_cases + ["INCOMPATIBLE"] * scale.incompatible_cases +
            ["STORAGE"] * scale.storage_cases + ["DUP_OCCUPIED"] * (scale.duplicate_cases - n_double) +
            ["DUP_DOUBLE"] * n_double + ["VALID"] * (scale.valid_controls - n_boundary) +
            ["VALID_BOUNDARY"] * n_boundary)
    r.shuffle(plan)
    used = set()
    approved = []
    proposals, gt = [], []
    clock = datetime(C.PROPOSAL_DATE.year, C.PROPOSAL_DATE.month, C.PROPOSAL_DATE.day, 8, 0)
    expected_issue = {"CAPACITY": "LOCATION_CAPACITY_EXCEEDED", "INCOMPATIBLE": "INCOMPATIBLE_CO_LOCATION",
                      "STORAGE": "STORAGE_CLASS_MISMATCH", "DUP_OCCUPIED": "DUPLICATE_ACTIVE_LOCATION",
                      "DUP_DOUBLE": "DUPLICATE_ACTIVE_LOCATION"}

    def free(loc):
        return not st.occupants[loc["location_id"]]

    def attempt(kind):
        wh = r.choice(wh_ids)
        skus = [s for s in st.stock[wh] if (wh, s) not in used]
        locs = st.locs_by_wh[wh]
        if kind == "CAPACITY":
            sku = r.choice([s for s in skus if st.sku[s]["required_storage_class"] == "AMBIENT"])
            loc = r.choice([lc for lc in locs if "AMBIENT" in st.zone_classes[lc["zone_id"]] and free(lc)])
        elif kind == "STORAGE":
            sku = r.choice([s for s in skus if st.sku[s]["required_storage_class"] in ("AMBIENT", "CHILLED",
                                                                                         "FROZEN")])
            need = st.sku[sku]["required_storage_class"]
            loc = r.choice([lc for lc in locs if need not in st.zone_classes[lc["zone_id"]] and free(lc)
                            and "HAZMAT" not in st.zone_classes[lc["zone_id"]]])
        elif kind == "INCOMPATIBLE":
            sku = r.choice([s for s in skus if st.sku[s]["required_storage_class"] == "HAZMAT"] or [None])
            if sku is None:
                return None
            key = compat_key(st.sku[sku])
            options = [lc for lc in locs if "HAZMAT" in st.zone_classes[lc["zone_id"]] and free(lc) and any(
                frozenset((key, n["compat_key"])) in pairs for n in st.bay[lc["bay_key"]] if n["sku_id"] != sku)]
            if not options:
                return None
            loc = r.choice(options)
        elif kind == "DUP_OCCUPIED":
            sku = r.choice(skus)
            need = st.sku[sku]["required_storage_class"]
            loc = r.choice([lc for lc in locs if need in st.zone_classes[lc["zone_id"]] and not free(lc)])
        elif kind == "DUP_DOUBLE":
            pool = [p for p in approved if p["warehouse_id"] == wh]
            if not pool:
                return None
            loc = st.loc[r.choice(pool)["location_id"]]
            sku = r.choice(skus)
        else:
            sku = r.choice(skus)
            need = st.sku[sku]["required_storage_class"]
            loc = r.choice([lc for lc in locs if need in st.zone_classes[lc["zone_id"]] and free(lc)])
        return wh, sku, loc

    queue = list(plan)
    deferred_rounds = 0
    while queue:
        kind = queue.pop(0)
        found = None
        for _ in range(400):
            try:
                got = attempt(kind)
            except IndexError:          # empty candidate pool in the drawn warehouse
                got = None
            if got is None:
                continue
            wh, sku, loc = got
            issues = st.issues(sku, loc["location_id"])
            want = expected_issue.get(kind)
            if want and set(issues) != {want}:
                continue
            if not want and issues:
                continue
            if kind == "VALID_BOUNDARY" and fit_units(st.sku[sku], loc)[0] != st.sku[sku]["max_order_qty"]:
                continue
            found = (wh, sku, loc, issues)
            break
        if found is None:
            if kind == "DUP_DOUBLE" and deferred_rounds < 3:
                queue.append(kind)
                deferred_rounds += 1
            elif kind == "VALID_BOUNDARY":
                queue.append("VALID")
            continue
        wh, sku, loc, issues = found
        used.add((wh, sku))
        clock += timedelta(seconds=r.randint(60, 900))
        p = dict(slot_id=ids.slot_id(next_slot_no), warehouse_id=wh, sku_id=sku, location_id=loc["location_id"],
                 plan_code="PLANNER_OVERRIDE", assignment_source="PLANNER_OVERRIDE", profile_id=None,
                 previous_slot_id=st.current.get((wh, sku)), requested_by=f"PLN-{r.randint(1, 8):02d}",
                 created_ts=clock, effective_from=C.OVERRIDE_EFFECTIVE, effective_to=None, status="PROPOSED",
                 units_capacity=None, reorder_point_units=None, candidate_rank=None, pick_cost_s_per_day=None,
                 replen_cost_s_per_day=None, decision_ts=None, decision_reason=None)
        next_slot_no += 1
        proposals.append(p)
        if issues:
            detail = next(iter(issues.values()))
            gt.append(_gt(next(iter(issues)), "SLOT_ASSIGNMENT", p["slot_id"], wh, "REJECT_PROPOSAL",
                          note=f"case={kind}; {detail}"))
        else:
            note = "boundary: units_fit == max_order_qty" if kind == "VALID_BOUNDARY" else "valid override"
            gt.append(_gt("NONE", "SLOT_ASSIGNMENT", p["slot_id"], wh, "APPROVE_PROPOSAL", note=note))
            st.approve(p)
            approved.append(p)
    return proposals, gt


def inject_blocked_aisles(scale, seed, picks, blocks):
    """Late-reported aisle blocks that overlap picks already executed (rule R-05), plus boundary controls."""
    r = ids.stream(seed, "anomaly.blocks")
    by_aisle = defaultdict(list)
    for p in picks:
        by_aisle[p["aisle_id"]].append((p["pick_ts"], p["pick_id"], p["warehouse_id"]))
    for v in by_aisle.values():
        v.sort()
    eligible = sorted(by_aisle)
    new_blocks, gt = [], []

    def overlaps(aisle, start, end):
        return any(b["aisle_id"] == aisle and b["start_ts"] < end and start < b["end_ts"]
                   for b in blocks + new_blocks)

    def in_window(aisle, start, end):
        arr = by_aisle[aisle]
        lo = bisect.bisect_left(arr, (start, "", ""))
        hi = bisect.bisect_left(arr, (end, "", ""))
        return arr[lo:hi]

    for boundary in [False] * scale.blocked_aisle_cases + [True] * scale.blocked_aisle_controls:
        for _ in range(500):
            aisle = r.choice(eligible)
            ts, pid, wh = r.choice(by_aisle[aisle])
            if boundary:
                end = ts
                start = end - timedelta(minutes=r.randint(30, 120))
            else:
                start = ts - timedelta(minutes=r.randint(10, 90))
                end = ts + timedelta(minutes=r.randint(5, 60))
            if overlaps(aisle, start, end):
                continue
            hits = in_window(aisle, start, end)
            if boundary and hits:
                continue          # keep the control clean: nothing inside the window
            b = dict(block_id=None, warehouse_id=wh, aisle_id=aisle, block_type=r.choice(("SPILL", "MAINTENANCE")),
                     start_ts=start, end_ts=end, reported_ts=end + timedelta(minutes=r.randint(10, 120)))
            new_blocks.append(b)
            if boundary:
                gt.append(_gt("NONE", "PICK_EVENT", pid, wh, "NO_ACTION",
                              note="boundary: pick_ts == block end_ts (end exclusive)"))
            for _, hit, hwh in hits:
                gt.append(_gt("PICK_PATH_BLOCKED_AISLE", "PICK_EVENT", hit, hwh, "ESCALATE_SAFETY_AUDIT",
                              note="block reported after it ended; WMS could not reroute"))
            break
    return new_blocks, gt


def build_labor_capacity(scale, seed, workload, base_caps, warehouses):
    """Capacity rows for every warehouse-day; injected absenteeism days and exact-boundary controls."""
    r = ids.stream(seed, "anomaly.labor")
    rows = {}
    d = C.HISTORY_START
    while d <= C.HISTORY_END:
        for w in warehouses:
            wid = w["warehouse_id"]
            rows[(wid, d)] = dict(labor_capacity_id=ids.labor_id(wid, d), warehouse_id=wid, work_date=d,
                                  replen_capacity_min=base_caps[wid], capacity_reason="STANDARD_PLAN")
        d += timedelta(days=1)
    loads = {k: round(v[2], 2) for k, v in workload.items()}
    # Only days with meaningful workload that were within plan; absenteeism leaves 50-85% of the need.
    calm = sorted(k for k, v in loads.items() if 30 <= v <= base_caps[k[0]] and k in rows)
    chosen = r.sample(calm, min(len(calm), scale.labor_cases + scale.labor_controls))
    injected, controls = chosen[:scale.labor_cases], chosen[scale.labor_cases:]
    for k in injected:
        cap = max(5, math.floor(loads[k] * r.uniform(0.5, 0.85) / 5) * 5)
        rows[k].update(replen_capacity_min=float(cap), capacity_reason="ABSENTEEISM")
    for k in controls:
        rows[k].update(replen_capacity_min=loads[k], capacity_reason="ABSENTEEISM")
    gt = []
    for k in sorted(rows):
        load = loads.get(k, 0.0)
        rid = ids.labor_day_id(*k)
        if load > rows[k]["replen_capacity_min"]:
            origin = "INJECTED" if k in injected else "RULE_DERIVED"
            note = "absenteeism reduced capacity" if k in injected else "peak workload above staffing plan"
            gt.append(_gt("REPLEN_LABOR_EXCEEDED", "REPLEN_LABOR_DAY", rid, k[0], "SCHEDULE_OVERTIME_OR_DEFER",
                          origin=origin, note=note))
        elif k in controls:
            gt.append(_gt("NONE", "REPLEN_LABOR_DAY", rid, k[0], "NO_ACTION",
                          note="boundary: workload == capacity (rule is strictly greater)"))
    return [rows[k] for k in sorted(rows)], gt
