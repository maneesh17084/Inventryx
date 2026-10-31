"""End-to-end build: master -> demand -> profiles -> slotting -> simulation -> anomalies -> decisions."""
from datetime import datetime

from . import anomalies, config as C, demand, engine, ids, master, optimizer, profiling, simulation
from .evaluation import evaluate_scenarios
from .events import build_state_events
from .rules import incompatible_pairs

LEGACY_CREATED_TS = datetime(2026, 6, 30, 20, 0)


def _slot_row(no, wh, sku, entry, plan_code, source, created, eff_from, eff_to, status, previous=None):
    return dict(slot_id=ids.slot_id(no), warehouse_id=wh, sku_id=sku, location_id=entry["location"]["location_id"],
                plan_code=plan_code, assignment_source=source, profile_id=entry["profile_id"],
                previous_slot_id=previous, requested_by=None, created_ts=created, effective_from=eff_from,
                effective_to=eff_to, status=status, units_capacity=entry["units_capacity"],
                reorder_point_units=entry["reorder_point_units"], candidate_rank=entry["candidate_rank"],
                pick_cost_s_per_day=entry["pick_cost"], replen_cost_s_per_day=entry["replen_cost"],
                decision_ts=None, decision_reason=None)


def build(scale, seed, log=print):
    t = {}
    log("  master data")
    t.update(master.generate_layout(scale, seed))
    t.update(master.generate_items(scale, seed, t["warehouse"]))

    log("  orders and order lines")
    truth = demand.latent_demand(seed, t["sku"], t["warehouse_sku"])
    t["orders"], t["order_line"] = demand.generate_orders(scale, seed, t["warehouse"], t["sku"], truth)

    log("  SKU velocity profiles")
    t["sku_profile"] = profiling.build_profiles(t["warehouse_sku"], t["sku"], t["orders"], t["order_line"])
    v1 = [p for p in t["sku_profile"] if p["version"] == 1]
    v2 = [p for p in t["sku_profile"] if p["version"] == 2]

    log("  slotting plans (legacy, static, peak-aware)")
    pairs = incompatible_pairs(t["compatibility_rule"])
    legacy, legacy_infeasible = optimizer.plan_legacy(t, pairs, ids.stream(seed, "plan.legacy"))
    if legacy_infeasible:
        raise RuntimeError(f"generator produced SKUs without any feasible slot: {legacy_infeasible[:5]}")
    static, _, _ = optimizer.plan_optimized(t, pairs, v1)
    peak, candidates, peak_infeasible = optimizer.plan_optimized(t, pairs, v2)
    for key in peak_infeasible:                     # R-08 fallback: keep the legacy slot
        peak[key] = legacy[key]
    for key in set(legacy) - set(static):
        static[key] = legacy[key]

    slots, no = [], 1
    for key in sorted(legacy):
        moved = key not in peak_infeasible
        row = _slot_row(no, *key, legacy[key], "LEGACY_2026H2", "LEGACY_IMPORT", LEGACY_CREATED_TS,
                        C.LEGACY_EFFECTIVE, C.CUTOVER if moved else None, "SUPERSEDED" if moved else "ACTIVE")
        slots.append(row)
        legacy[key] = dict(legacy[key], slot_id=row["slot_id"])
        no += 1
    for key in sorted(peak):
        if key in peak_infeasible:
            continue
        row = _slot_row(no, *key, peak[key], "OPT_PEAK_2026W42", "OPTIMIZER", C.PLAN_CREATED_TS, C.CUTOVER, None,
                        "ACTIVE", previous=legacy[key]["slot_id"])
        slots.append(row)
        peak[key] = dict(peak[key], slot_id=row["slot_id"])
        no += 1
    for key in peak_infeasible:
        peak[key] = legacy[key]
    for n, c in enumerate(sorted(candidates, key=lambda c: (c["warehouse_id"], c["sku_id"], c["candidate_rank"])),
                          1):
        c["candidate_id"] = ids.candidate_id(n)
        c["plan_code"] = "OPT_PEAK_2026W42"
        c["slot_id"] = peak[(c["warehouse_id"], c["sku_id"])]["slot_id"] if c["selected"] else None
    t["slot_candidate"] = sorted(candidates, key=lambda c: c["candidate_id"])

    log("  pick tours (return routing, blocked-aisle holds)")
    blocks = simulation.generate_baseline_blocks(scale, seed, t["aisle"])
    t["pick_event"] = simulation.simulate_picks(
        seed, t["orders"], t["order_line"], lambda d: legacy if d < C.CUTOVER else peak, blocks, t["aisle"])

    log("  replenishment workload")
    slot_info = {}
    for plan in (legacy, peak):
        for (wh, sku), e in plan.items():
            slot_info[e["slot_id"]] = dict(location=e["location"], units_capacity=e["units_capacity"],
                                           reorder_point_units=e["reorder_point_units"], warehouse_id=wh,
                                           sku_id=sku, slot_id=e["slot_id"])
    tasks = simulation.simulate_replenishment(((p["slot_id"], p["pick_ts"], p["qty"]) for p in t["pick_event"]),
                                              slot_info)
    for n, task in enumerate(tasks, 1):
        task["replen_id"] = ids.replen_id(n)
        task["labor_status"] = None
        task["status"] = "COMPLETED"
        del task["slot_key"]
    t["replenishment"] = tasks

    log("  labelled edge cases")
    workload = simulation.daily_workload(tasks)
    base_caps = simulation.base_labor_capacity(workload, t["warehouse"])
    t["labor_capacity"], gt_labor = anomalies.build_labor_capacity(scale, seed, workload, base_caps, t["warehouse"])
    new_blocks, gt_blocks = anomalies.inject_blocked_aisles(scale, seed, t["pick_event"], blocks)
    all_blocks = sorted(blocks + new_blocks, key=lambda b: (b["start_ts"], b["aisle_id"]))
    for n, b in enumerate(all_blocks, 1):
        b["block_id"] = ids.block_id(n)
    t["aisle_block"] = all_blocks
    for o in t["orders"]:
        if o["hold_block_id"]:
            o["hold_block_id"] = o["hold_block_id"]["block_id"]
    active = [s for s in slots if s["status"] == "ACTIVE"]
    proposals, gt_props = anomalies.inject_proposals(scale, seed, t, active, pairs, no)
    t["slot_assignment"] = slots + proposals

    log("  decision engine")
    decisions, exc = engine.decide_proposals(t)
    for s in proposals:
        s.update(decisions[s["slot_id"]])
    t["replen_labor_daily"], statuses, labor_exc = engine.labor_analysis(t)
    for task in t["replenishment"]:
        task["labor_status"] = statuses[task["replen_id"]]
    exc += engine.detect_blocked_aisle_picks(t) + labor_exc + engine.deferral_exceptions(t)
    for wh, sku in sorted(peak_infeasible):
        exc.append(engine._exc("NO_FEASIBLE_SLOT", "SKU", sku, wh, C.PLAN_CREATED_TS,
                               "optimizer found no feasible free slot; legacy slot retained"))
    t["slotting_exception"] = engine.number_exceptions(exc)
    t["state_event"] = build_state_events(t)

    gt = gt_props + gt_blocks + gt_labor
    gt.sort(key=lambda g: (g["entity_type"], g["entity_id"], g["issue_type"]))
    for n, g in enumerate(gt, 1):
        g["gt_id"] = ids.gt_id(n)

    log("  scenario evaluation (holdout)")
    plans = {"BASELINE_LEGACY": legacy, "OPT_STATIC_V1": static, "OPT_PEAK_V2": peak}
    scen_rows, scen_summary, scen_wh = evaluate_scenarios(t, plans)
    extras = dict(demand_truth=truth, scenario_rows=scen_rows, scenario_summary=scen_summary,
                  scenario_per_warehouse=scen_wh, plans=plans, v2_profiles=v2)
    return t, gt, extras
