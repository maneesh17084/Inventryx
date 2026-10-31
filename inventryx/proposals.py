"""Durable, append-only event log for interactive slot proposals.

Every state change is a new JSON line - nothing is ever rewritten:

  PROPOSAL_SUBMITTED  planner asked for SKU -> location from a date
  PROPOSAL_DECIDED    slotting engine APPROVED / REJECTED it, with reason codes
  PROPOSAL_WITHDRAWN  planner withdrew an approved proposal (it stops occupying the location)

Current state is derived by replaying the log on start-up, so approved proposals keep taking part in
conflict checks after a restart. One log per dataset fingerprint (profile, seed, slot_assignment.csv
checksum) keeps proposals from being replayed against a different dataset.
"""
import json
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path

SLOT_RE = re.compile(r"^SLOT-2026-(\d{6})$")
PLANNER_RE = re.compile(r"^PLN-\d{2}$")
TRANSITIONS = {(None, "PROPOSAL_SUBMITTED"), ("PROPOSAL_SUBMITTED", "PROPOSAL_DECIDED"),
               ("PROPOSAL_DECIDED", "PROPOSAL_WITHDRAWN")}


def fingerprint(manifest: dict) -> str:
    slot_sum = next((f["sha256"] for f in manifest["files"] if f["path"] == "csv/slot_assignment.csv"), "none")
    return f"{manifest['profile']}-{manifest['seed']}-{slot_sum[:12]}"


def _now():
    return datetime.now().replace(microsecond=0)


class ProposalLog:
    def __init__(self, path: Path, dataset_fp: str, first_slot_no: int, log=print):
        self.path = Path(path)
        self.fp = dataset_fp
        self.lock = threading.Lock()
        self.proposals = {}           # slot_id -> current state
        self.events = []
        self.skipped = []             # unreadable / invalid lines, reported not fatal
        self.next_no = first_slot_no
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._replay(log)

    # ------------------------------------------------------------ replay
    def _replay(self, log):
        with open(self.path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    self._apply(ev)
                except (ValueError, KeyError) as e:
                    self.skipped.append(f"line {n}: {e}")
        log(f"[serve] replayed {len(self.events)} proposal events from {self.path}"
            + (f" ({len(self.skipped)} unreadable lines skipped)" if self.skipped else ""))

    def _apply(self, ev):
        if ev.get("dataset") != self.fp:
            raise ValueError("event belongs to a different dataset")
        sid, kind = ev["slot_id"], ev["event"]
        cur = self.proposals.get(sid)
        if (cur["last_event"] if cur else None, kind) not in TRANSITIONS:
            raise ValueError(f"illegal transition {cur and cur['last_event']} -> {kind} for {sid}")
        if kind == "PROPOSAL_SUBMITTED":
            self.proposals[sid] = dict(
                slot_id=sid, warehouse_id=ev["warehouse_id"], sku_id=ev["sku_id"], location_id=ev["location_id"],
                effective_from=date.fromisoformat(ev["effective_from"]),
                effective_to=date.fromisoformat(ev["effective_to"]) if ev.get("effective_to") else None,
                requested_by=ev["requested_by"], created_ts=datetime.fromisoformat(ev["ts"]),
                assignment_source="PLANNER_OVERRIDE", plan_code="PLANNER_OVERRIDE", status="PROPOSED",
                decision_ts=None, reasons=[], units_capacity=None, withdrawn_ts=None, note=ev.get("note"),
                last_event=kind)
            self.next_no = max(self.next_no, int(SLOT_RE.match(sid).group(1)) + 1)
        elif kind == "PROPOSAL_DECIDED":
            cur.update(status=ev["decision"], decision_ts=datetime.fromisoformat(ev["ts"]), reasons=ev["reasons"],
                       units_capacity=ev.get("units_capacity"), last_event=kind)
        else:
            if cur["status"] != "APPROVED":
                raise ValueError(f"only APPROVED proposals can be withdrawn ({sid} is {cur['status']})")
            cur.update(status="WITHDRAWN", withdrawn_ts=datetime.fromisoformat(ev["ts"]), last_event=kind,
                       withdraw_reason=ev.get("reason"))
        self.events.append(ev)

    # ------------------------------------------------------------ writes
    def _append(self, ev):
        """Validate, write durably (flush + fsync), then apply to in-memory state."""
        ev = dict(ev, dataset=self.fp)
        line = json.dumps(ev, separators=(",", ":"), default=str)
        probe = dict(self.proposals.get(ev["slot_id"]) or {})
        if (probe.get("last_event"), ev["event"]) not in TRANSITIONS:
            raise ValueError(f"illegal transition {probe.get('last_event')} -> {ev['event']}")
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._apply(json.loads(line))

    def submit(self, warehouse_id, sku_id, location_id, effective_from, effective_to, requested_by, decision,
               reasons, units_capacity, note=None):
        if not PLANNER_RE.match(requested_by or ""):
            raise ValueError("requested_by must be a planner ID like PLN-01")
        with self.lock:
            sid = f"SLOT-2026-{self.next_no:06d}"
            submitted = _now()
            self._append(dict(event="PROPOSAL_SUBMITTED", slot_id=sid, ts=submitted.isoformat(),
                              warehouse_id=warehouse_id, sku_id=sku_id, location_id=location_id,
                              effective_from=effective_from.isoformat(),
                              effective_to=effective_to.isoformat() if effective_to else None,
                              requested_by=requested_by, note=note))
            self._append(dict(event="PROPOSAL_DECIDED", slot_id=sid, ts=_now().isoformat(), actor="SLOTTING_ENGINE",
                              decision=decision, reasons=reasons, units_capacity=units_capacity))
            return self.proposals[sid]

    def withdraw(self, slot_id, requested_by, reason=None):
        if not PLANNER_RE.match(requested_by or ""):
            raise ValueError("requested_by must be a planner ID like PLN-01")
        with self.lock:
            if slot_id not in self.proposals:
                raise KeyError(slot_id)
            if self.proposals[slot_id]["status"] != "APPROVED":
                raise ValueError(f"{slot_id} is {self.proposals[slot_id]['status']}; only APPROVED can be withdrawn")
            self._append(dict(event="PROPOSAL_WITHDRAWN", slot_id=slot_id, ts=_now().isoformat(),
                              requested_by=requested_by, reason=reason))
            return self.proposals[slot_id]

    # ------------------------------------------------------------ reads
    def approved(self):
        return [p for p in self.proposals.values() if p["status"] == "APPROVED"]

    def listing(self):
        return dict(log_path=str(self.path), dataset=self.fp, events=len(self.events), skipped=self.skipped,
                    proposals=sorted(self.proposals.values(), key=lambda p: p["slot_id"], reverse=True))

    def history(self, slot_id):
        return [e for e in self.events if e["slot_id"] == slot_id]
