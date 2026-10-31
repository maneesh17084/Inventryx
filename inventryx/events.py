"""Append-only state_event history. Current status columns are the last event per entity."""
from datetime import datetime

from . import ids


def _dt(d):
    return datetime(d.year, d.month, d.day)


def build_state_events(tables):
    ev = []

    def add(entity, eid, frm, to, ts, actor, reason=None):
        ev.append([entity, eid, frm, to, ts, actor, reason, len(ev)])

    for o in tables["orders"]:
        oid = o["order_id"]
        add("ORDER", oid, None, "CREATED", o["order_ts"], "WMS")
        if o["status"] == "CANCELLED":
            add("ORDER", oid, "CREATED", "CANCELLED", o["cancelled_ts"], "WMS", "customer cancellation")
            continue
        add("ORDER", oid, "CREATED", "RELEASED", o["release_ts"], "WMS")
        if o["hold_block_id"]:
            add("ORDER", oid, "RELEASED", "ON_HOLD", o["release_ts"], "WMS", o["hold_block_id"])
            add("ORDER", oid, "ON_HOLD", "RELEASED", o["hold_release_ts"], "WMS", o["hold_block_id"])
        add("ORDER", oid, "RELEASED", "PICKED", o["picked_ts"], "WMS")
        if o["shipped_ts"]:
            add("ORDER", oid, "PICKED", "SHIPPED", o["shipped_ts"], "WMS", o["carrier_service"])

    successor = {s["previous_slot_id"]: s["slot_id"] for s in tables["slot_assignment"]
                 if s["previous_slot_id"] and s["assignment_source"] == "OPTIMIZER"}
    for s in tables["slot_assignment"]:
        sid = s["slot_id"]
        if s["assignment_source"] == "LEGACY_IMPORT":
            add("SLOT_ASSIGNMENT", sid, None, "ACTIVE", _dt(s["effective_from"]), "LEGACY_MIGRATION")
        elif s["assignment_source"] == "OPTIMIZER":
            add("SLOT_ASSIGNMENT", sid, None, "PROPOSED", s["created_ts"], "OPTIMIZER",
                f"candidate rank {s['candidate_rank']}")
            add("SLOT_ASSIGNMENT", sid, "PROPOSED", "ACTIVE", _dt(s["effective_from"]), "OPTIMIZER")
        else:
            add("SLOT_ASSIGNMENT", sid, None, "PROPOSED", s["created_ts"], "PLANNER", s["requested_by"])
            add("SLOT_ASSIGNMENT", sid, "PROPOSED", s["status"], s["decision_ts"], "SLOTTING_ENGINE",
                s["decision_reason"])
        if s["status"] == "SUPERSEDED":
            add("SLOT_ASSIGNMENT", sid, "ACTIVE", "SUPERSEDED", _dt(s["effective_to"]), "OPTIMIZER",
                f"replaced by {successor.get(sid)}")

    for t in tables["replenishment"]:
        add("REPLENISHMENT", t["replen_id"], None, "CREATED", t["created_ts"], "WMS", t["replen_type"])
        add("REPLENISHMENT", t["replen_id"], "CREATED", "COMPLETED", t["completed_ts"], "WMS", t["labor_status"])

    for b in tables["aisle_block"]:
        add("AISLE", b["aisle_id"], "ACTIVE", "BLOCKED", b["start_ts"], "MAINTENANCE", b["block_id"])
        add("AISLE", b["aisle_id"], "BLOCKED", "ACTIVE", b["end_ts"], "MAINTENANCE", b["block_id"])

    ev.sort(key=lambda e: (e[4], e[0], e[1], e[7]))
    return [dict(event_id=ids.event_id(n), entity_type=e[0], entity_id=e[1], from_status=e[2], to_status=e[3],
                 event_ts=e[4], actor=e[5], reason=e[6]) for n, e in enumerate(ev, 1)]
