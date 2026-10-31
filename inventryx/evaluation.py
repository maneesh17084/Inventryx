"""Out-of-sample comparison of slotting plans on identical holdout orders.

Every scenario replays the same orders, quantities and pick timestamps through the same routing
policy and replenishment model; only the SKU->location map differs, so results are comparable.
"""
from collections import defaultdict

from . import config as C
from .simulation import daily_workload, simulate_replenishment, tour_metrics

SCENARIOS = ("BASELINE_LEGACY", "OPT_STATIC_V1", "OPT_PEAK_V2")


def holdout_orders(tables):
    lo, hi = C.HOLDOUT
    return [o for o in tables["orders"] if o["status"] != "CANCELLED" and lo <= o["order_ts"].date() <= hi]


def evaluate_scenarios(tables, plans):
    aisle_no = {a["aisle_id"]: a["aisle_no"] for a in tables["aisle"]}
    lines_by_order = defaultdict(list)
    for ln in tables["order_line"]:
        lines_by_order[ln["order_id"]].append(ln)
    orders = holdout_orders(tables)
    order_ids = {o["order_id"] for o in orders}
    caps = {(c["warehouse_id"], c["work_date"]): c["replen_capacity_min"] for c in tables["labor_capacity"]}
    picks = [p for p in tables["pick_event"] if p["order_id"] in order_ids]

    rows = []
    summary, per_wh = {}, []
    for name in SCENARIOS:
        plan = plans[name]
        agg = defaultdict(lambda: defaultdict(float))
        for o in orders:
            olines = lines_by_order[o["order_id"]]
            dist, secs, golden = tour_metrics(olines, plan, o["warehouse_id"], aisle_no)
            rows.append(dict(scenario=name, order_id=o["order_id"], warehouse_id=o["warehouse_id"],
                             lines=len(olines), units=sum(x["qty_ordered"] for x in olines), distance_m=dist,
                             est_seconds=secs, golden_zone_picks=golden))
            for key in (o["warehouse_id"], "ALL"):
                a = agg[key]
                a["orders"] += 1
                a["lines"] += len(olines)
                a["distance_m"] += dist
                a["seconds"] += secs
                a["golden"] += golden
        info = {k: dict(v, warehouse_id=k[0], sku_id=k[1]) for k, v in plan.items()}
        tasks = simulate_replenishment(((( p["warehouse_id"], p["sku_id"]), p["pick_ts"], p["qty"]) for p in picks),
                                       info)
        load = daily_workload(tasks)
        for (wh, d), (n, emerg, minutes) in load.items():
            for key in (wh, "ALL"):
                a = agg[key]
                a["replen_tasks"] += n
                a["emergency_replen"] += emerg
                a["replen_minutes"] += minutes
                over = round(minutes, 2) - caps[(wh, d)]
                if over > 0:
                    a["labor_days_exceeded"] += 1
                    a["over_capacity_min"] += over
        for key, a in sorted(agg.items()):
            hours = a["seconds"] / 3600.0
            rec = dict(scenario=name, warehouse_id=key, orders=int(a["orders"]), lines=int(a["lines"]),
                       distance_m=round(a["distance_m"], 2),
                       distance_per_order_m=round(a["distance_m"] / a["orders"], 2),
                       distance_per_line_m=round(a["distance_m"] / a["lines"], 3),
                       picker_hours=round(hours, 2), lines_per_picker_hour=round(a["lines"] / hours, 2),
                       golden_zone_pick_share=round(a["golden"] / a["lines"], 4),
                       replen_tasks=int(a["replen_tasks"]), emergency_replen=int(a["emergency_replen"]),
                       replen_minutes=round(a["replen_minutes"], 2),
                       labor_days_exceeded=int(a["labor_days_exceeded"]),
                       over_capacity_min=round(a["over_capacity_min"], 2))
            if key == "ALL":
                summary[name] = rec
            else:
                per_wh.append(rec)
    base = summary["BASELINE_LEGACY"]
    for name in SCENARIOS:
        s = summary[name]
        s["distance_reduction_pct"] = round((1 - s["distance_m"] / base["distance_m"]) * 100, 2)
        s["throughput_gain_pct"] = round((s["lines_per_picker_hour"] / base["lines_per_picker_hour"] - 1) * 100, 2)
        s["replen_minutes_change_pct"] = round((s["replen_minutes"] / base["replen_minutes"] - 1) * 100, 2)
    return rows, summary, per_wh
