"""Pick-path and replenishment simulation.

Pick tours: one picker per order, return routing (rules.route). If a tour would enter an aisle
that is blocked at that moment, the order is put ON_HOLD and re-released when the block ends
(rule R-07) - so baseline history never walks a known blocked aisle.

Replenishment: each slot starts full; a SCHEDULED task refills to capacity at end of day when
on-hand <= reorder point; an EMERGENCY task refills before a pick that on-hand cannot cover.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta

from . import config as C
from . import ids
from .rules import handling_seconds, replen_minutes, route


def _ts(base, seconds):
    return base + timedelta(seconds=int(round(seconds)))


def generate_baseline_blocks(scale, seed, aisles):
    r = ids.stream(seed, "sim.blocks")
    by_wh = defaultdict(list)
    for a in aisles:
        by_wh[a["warehouse_id"]].append(a)
    span = (C.HISTORY_END - C.HISTORY_START).days
    blocks = []
    for wh in sorted(by_wh):
        placed = 0
        while placed < scale.baseline_blocks_per_wh:
            a = r.choice(by_wh[wh])
            day = C.HISTORY_START + timedelta(days=r.randint(0, span))
            start = datetime(day.year, day.month, day.day) + timedelta(minutes=r.randint(6 * 60, 17 * 60))
            end = start + timedelta(minutes=r.randint(60, 240))
            if any(b["aisle_id"] == a["aisle_id"] and b["start_ts"] < end and start < b["end_ts"] for b in blocks):
                continue
            blocks.append(dict(block_id=None, warehouse_id=wh, aisle_id=a["aisle_id"],
                               block_type=r.choice(("MAINTENANCE", "RACK_INSPECTION", "CLEANING")),
                               start_ts=start, end_ts=end,
                               reported_ts=start - timedelta(minutes=r.randint(60, 48 * 60))))
            placed += 1
    return blocks


def _tour_times(start, legs, back):
    cum = C.ORDER_SETUP_S
    out = []
    for stop, leg in legs:
        cum += leg / C.PICKER_SPEED_MPS
        handling = handling_seconds(stop["loc"], stop["line"]["qty_ordered"])
        out.append((stop, leg, _ts(start, cum), handling))
        cum += handling
    return out, _ts(start, cum + back / C.PICKER_SPEED_MPS)


def build_stops(order_lines, plan_map, warehouse_id, aisle_no):
    stops = []
    for ln in order_lines:
        slot = plan_map[(warehouse_id, ln["sku_id"])]
        loc = slot["location"]
        stops.append(dict(key=ln["order_line_id"], aisle_no=aisle_no[loc["aisle_id"]], x_m=loc["x_m"],
                          y_m=loc["y_m"], line=ln, slot=slot, loc=loc))
    return stops


def simulate_picks(seed, orders, lines, plans_by_period, blocks, aisles):
    """plans_by_period: callable(date) -> {(wh, sku): slot dict with slot_id/location}."""
    r = ids.stream(seed, "sim.picks")
    aisle_no = {a["aisle_id"]: a["aisle_no"] for a in aisles}
    lines_by_order = defaultdict(list)
    for ln in lines:
        lines_by_order[ln["order_id"]].append(ln)
    blocks_by_aisle = defaultdict(list)
    for b in blocks:
        blocks_by_aisle[b["aisle_id"]].append(b)
    picks = []
    for o in orders:
        if o["status"] == "CANCELLED":
            continue
        olines = lines_by_order[o["order_id"]]
        plan = plans_by_period(o["order_ts"].date())
        legs, back = route(build_stops(olines, plan, o["warehouse_id"], aisle_no))
        delay_min = r.uniform(5, 20) if o["priority"] == "EXPRESS" else r.uniform(10, 75)
        release = _ts(o["order_ts"], delay_min * 60)
        start, hold = release, None
        for _ in range(10):
            timed, picked_ts = _tour_times(start, legs, back)
            conflict = None
            for stop, _, ts, _ in timed:
                for b in blocks_by_aisle.get(stop["loc"]["aisle_id"], ()):
                    if b["start_ts"] <= ts < b["end_ts"]:
                        conflict = b
                        break
                if conflict:
                    break
            if conflict is None:
                break
            hold = hold or conflict
            start = conflict["end_ts"]
        # hold_block_id temporarily holds the block dict; IDs are finalised once all blocks exist.
        o.update(release_ts=release, hold_block_id=hold,
                 hold_release_ts=start if hold else None, picked_ts=picked_ts,
                 shipped_ts=picked_ts + timedelta(minutes=r.randint(20, 180)),
                 pick_distance_m=round(sum(leg for _, leg in legs) + back, 2), return_to_depot_m=back)
        o["status"] = "SHIPPED" if o["shipped_ts"] <= C.AS_OF else "PICKED"
        if o["status"] == "PICKED":
            o["shipped_ts"] = None
        for seq, (stop, leg, ts, handling) in enumerate(timed, 1):
            ln = stop["line"]
            ln["qty_picked"] = ln["qty_ordered"]
            picks.append(dict(pick_id=ids.pick_id(o["order_id"], seq), order_id=o["order_id"],
                              order_line_id=ln["order_line_id"], warehouse_id=o["warehouse_id"], sku_id=ln["sku_id"],
                              slot_id=stop["slot"]["slot_id"], location_id=stop["loc"]["location_id"],
                              aisle_id=stop["loc"]["aisle_id"], pick_seq=seq, pick_ts=ts, qty=ln["qty_ordered"],
                              travel_from_prev_m=leg, handling_s=handling, status="COMPLETED"))
    return picks


def simulate_replenishment(pick_stream, slot_info):
    """pick_stream: iterable of (slot_key, ts, qty). slot_info[slot_key] -> dict(location, units_capacity,
    reorder_point_units, warehouse_id, sku_id, slot_id). Returns unsorted task dicts."""
    by_slot = defaultdict(list)
    for key, ts, qty in pick_stream:
        by_slot[key].append((ts, qty))
    tasks = []

    def task(info, kind, reason, created, onhand):
        units = info["units_capacity"] - onhand
        minutes = replen_minutes(info["location"], units)
        if kind == "EMERGENCY":
            created, completed = created - timedelta(seconds=int(round(minutes * 60))), created
        else:
            completed = _ts(created, minutes * 60)
        tasks.append(dict(slot_key=info["key"], warehouse_id=info["warehouse_id"], sku_id=info["sku_id"],
                          slot_id=info.get("slot_id"), location_id=info["location"]["location_id"], replen_type=kind,
                          trigger_reason=reason, created_ts=created, completed_ts=completed, units=units,
                          onhand_before=onhand, onhand_after=info["units_capacity"], task_minutes=minutes))

    for key in sorted(by_slot, key=str):
        info = dict(slot_info[key], key=key)
        cap, rop = info["units_capacity"], info["reorder_point_units"]
        onhand, day, last_ts = cap, None, None
        for ts, qty in sorted(by_slot[key]):
            if day is not None and ts.date() != day:
                if onhand <= rop:
                    eod = max(datetime(day.year, day.month, day.day, C.SCHEDULED_REPLEN_HOUR),
                              last_ts + timedelta(minutes=1))
                    task(info, "SCHEDULED", "BELOW_REORDER_POINT", eod, onhand)
                    onhand = cap
            if onhand < qty:
                task(info, "EMERGENCY", "INSUFFICIENT_FOR_PICK", ts, onhand)
                onhand = cap
            onhand -= qty
            day, last_ts = ts.date(), ts
        if day is not None and onhand <= rop:
            eod = max(datetime(day.year, day.month, day.day, C.SCHEDULED_REPLEN_HOUR), last_ts + timedelta(minutes=1))
            task(info, "SCHEDULED", "BELOW_REORDER_POINT", eod, onhand)
    tasks.sort(key=lambda t: (t["created_ts"], str(t["slot_key"])))
    return tasks


def daily_workload(tasks):
    out = defaultdict(lambda: [0, 0, 0.0])
    for t in tasks:
        a = out[(t["warehouse_id"], t["created_ts"].date())]
        a[0] += 1
        a[1] += t["replen_type"] == "EMERGENCY"
        a[2] += t["task_minutes"]
    return out


def base_labor_capacity(workload, warehouses):
    """Staffing plan: p95 of Jul-Sep daily workload x headroom, rounded up to 15-minute blocks."""
    caps = {}
    for w in warehouses:
        wid = w["warehouse_id"]
        vals = []
        d = C.HISTORY_START
        while d < C.PEAK_START:
            vals.append(workload.get((wid, d), (0, 0, 0.0))[2])
            d += timedelta(days=1)
        vals.sort()
        p = vals[min(len(vals) - 1, int(math.ceil(C.LABOR_CAPACITY_PERCENTILE * len(vals))) - 1)]
        step = C.LABOR_ROUNDING_MIN
        caps[wid] = float(max(step, math.ceil(p * C.LABOR_CAPACITY_HEADROOM / step) * step))
    return caps


def tour_metrics(order_lines, plan_map, warehouse_id, aisle_no):
    stops = build_stops(order_lines, plan_map, warehouse_id, aisle_no)
    legs, back = route(stops)
    distance = round(sum(leg for _, leg in legs) + back, 2)
    handling = sum(handling_seconds(s["loc"], s["line"]["qty_ordered"]) for s in stops)
    seconds = C.ORDER_SETUP_S + distance / C.PICKER_SPEED_MPS + handling
    golden = sum(1 for s in stops if s["loc"]["is_golden_zone"])
    return distance, round(seconds, 1), golden
