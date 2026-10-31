"""Candidate-slot calculation and slot assignment.

* legacy plan  - as-is state: SKUs placed in receiving order into any feasible location (velocity-blind).
* optimized    - greedy cost-based slotting: SKUs in descending pick frequency each take the feasible
                 free location with the lowest (pick-travel + replenishment) seconds/day.

Both plans enforce the same hard constraints (rules R-01..R-04): physical fit incl. max_order_qty,
storage class, bay segregation and one SKU per location.
"""
import heapq
from collections import defaultdict

from .rules import capacity_issue, compat_key, reorder_point, replen_minutes, travel_seconds


class WarehouseState:
    """Free locations, bay contents and class reservations for one warehouse.

    Zones can serve several storage classes (BULK holds AMBIENT and OVERSIZE). A SKU may only take
    a shared location if every other class that location serves keeps at least as many free
    locations as it still has unplaced SKUs - otherwise fast ambient movers starve oversized items.
    """

    def __init__(self, warehouse_id, locations, zone_classes, pairs, skus_to_place):
        self.warehouse_id = warehouse_id
        self.pairs = pairs
        self.zone_classes = zone_classes
        self.by_class = defaultdict(list)
        self.free = defaultdict(int)
        for loc in locations:
            if loc["status"] != "ACTIVE":
                continue
            for c in zone_classes[loc["zone_id"]]:
                self.by_class[c].append(loc)
                self.free[c] += 1
        self.remaining = defaultdict(int)
        for s in skus_to_place:
            self.remaining[s["required_storage_class"]] += 1
        self.used = set()
        self.bay_keys = defaultdict(list)
        self._fit = {}

    def fit(self, sku, loc):
        key = (sku["sku_id"], loc["width_cm"], loc["depth_cm"], loc["height_cm"], loc["max_weight_kg"])
        if key not in self._fit:
            self._fit[key] = capacity_issue(sku, loc)
        return self._fit[key]

    def feasible(self, sku):
        key = compat_key(sku)
        own = sku["required_storage_class"]
        for loc in self.by_class[own]:
            if loc["location_id"] in self.used:
                continue
            if any(self.free[c] - 1 < self.remaining[c] for c in self.zone_classes[loc["zone_id"]] if c != own):
                continue
            issue, units = self.fit(sku, loc)
            if issue:
                continue
            if any(frozenset((key, k)) in self.pairs for k in self.bay_keys[loc["bay_key"]]):
                continue
            yield loc, units

    def take(self, sku, loc):
        self.used.add(loc["location_id"])
        self.bay_keys[loc["bay_key"]].append(compat_key(sku))
        self.remaining[sku["required_storage_class"]] -= 1
        for c in self.zone_classes[loc["zone_id"]]:
            self.free[c] -= 1


def _layout(tables):
    zone_classes = defaultdict(set)
    for z in tables["zone_storage_class"]:
        zone_classes[z["zone_id"]].add(z["storage_class_code"])
    locs_by_wh = defaultdict(list)
    for loc in tables["location"]:
        locs_by_wh[loc["warehouse_id"]].append(loc)
    stock_by_wh = defaultdict(list)
    for ws in tables["warehouse_sku"]:
        stock_by_wh[ws["warehouse_id"]].append(ws["sku_id"])
    return zone_classes, locs_by_wh, stock_by_wh


def plan_legacy(tables, pairs, rng):
    """Velocity-blind as-is placement. Returns {(wh, sku): assignment dict}."""
    zone_classes, locs_by_wh, stock_by_wh = _layout(tables)
    sku_by_id = {s["sku_id"]: s for s in tables["sku"]}
    plan, exceptions = {}, []
    for wh in sorted(stock_by_wh):
        skus = sorted(stock_by_wh[wh])
        state = WarehouseState(wh, locs_by_wh[wh], zone_classes, pairs, [sku_by_id[s] for s in skus])
        rng.shuffle(skus)
        for sid in skus:
            sku = sku_by_id[sid]
            options = list(state.feasible(sku))
            if not options:
                exceptions.append((wh, sid))
                continue
            loc, units = rng.choice(options)
            state.take(sku, loc)
            plan[(wh, sid)] = dict(location=loc, units_capacity=units, reorder_point_units=reorder_point(units),
                                   candidate_rank=None, pick_cost=None, replen_cost=None, profile_id=None)
    return plan, exceptions


def _costs(loc, units, prof):
    rop = reorder_point(units)
    per_replen = max(1, units - rop)
    pick = prof["forecast_lines_per_day"] * travel_seconds(loc)
    replen = prof["forecast_units_per_day"] / per_replen * replen_minutes(loc, per_replen) * 60.0
    return pick, replen


def plan_optimized(tables, pairs, profiles, top_k=3):
    """Greedy cost-based slotting. Returns (plan, candidates, infeasible)."""
    zone_classes, locs_by_wh, stock_by_wh = _layout(tables)
    sku_by_id = {s["sku_id"]: s for s in tables["sku"]}
    prof = {(p["warehouse_id"], p["sku_id"]): p for p in profiles}
    plan, candidates, exceptions = {}, [], []
    for wh in sorted(stock_by_wh):
        state = WarehouseState(wh, locs_by_wh[wh], zone_classes, pairs, [sku_by_id[s] for s in stock_by_wh[wh]])
        order = sorted(stock_by_wh[wh], key=lambda s: (-prof[(wh, s)]["forecast_lines_per_day"],
                                                       -prof[(wh, s)]["forecast_units_per_day"], s))
        for sid in order:
            sku, p = sku_by_id[sid], prof[(wh, sid)]
            idle = p["forecast_lines_per_day"] == 0 and p["forecast_units_per_day"] == 0
            scored = []
            for loc, units in state.feasible(sku):
                pick, replen = _costs(loc, units, p)
                # Idle SKUs keep good locations free by preferring the farthest feasible slot.
                tiebreak = -travel_seconds(loc) if idle else travel_seconds(loc)
                scored.append((round(pick + replen, 6), tiebreak, loc["location_id"], loc, units, pick, replen))
            if not scored:
                exceptions.append((wh, sid))
                continue
            best = heapq.nsmallest(top_k, scored, key=lambda x: x[:3])
            for rank, (total, _, _, loc, units, pick, replen) in enumerate(best, 1):
                candidates.append(dict(warehouse_id=wh, sku_id=sid, profile_id=p["profile_id"],
                                       location_id=loc["location_id"], candidate_rank=rank, units_capacity=units,
                                       pick_cost_s_per_day=round(pick, 3), replen_cost_s_per_day=round(replen, 3),
                                       total_cost_s_per_day=round(pick + replen, 3), selected=rank == 1))
            _, _, _, loc, units, pick, replen = best[0]
            state.take(sku, loc)
            plan[(wh, sid)] = dict(location=loc, units_capacity=units, reorder_point_units=reorder_point(units),
                                   candidate_rank=1, pick_cost=round(pick, 3), replen_cost=round(replen, 3),
                                   profile_id=p["profile_id"])
    return plan, candidates, exceptions
