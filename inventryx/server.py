"""Web app: JSON API over a generated dataset plus the static single-page frontend in inventryx/web/.

Standard library only. Start with:  python -m inventryx serve --data data/full
"""
import sys

if __package__ in (None, ""):
    # Executed as a file (VS Code "Run Python File"): start the web app through the package CLI.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from inventryx.cli import main
    sys.exit(main(["serve", *sys.argv[1:]]))

import json
import mimetypes
from html import escape as html_escape
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config as C
from .export import load_ground_truth, load_tables
from .proposals import ProposalLog, fingerprint
from .rules import (capacity_issue, compat_key, fit_units, incompatible_pairs, location_conflicts, reorder_point,
                    replen_minutes, travel_seconds)

WEB = Path(__file__).resolve().parent / "web"
COMMITTED = ("ACTIVE", "SUPERSEDED", "APPROVED")
# Fixed types for everything the app serves; mimetypes alone depends on the OS registry
# (e.g. Windows maps .csv to Excel), which would make responses differ between hosts.
CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json",
                 ".csv": "text/csv", ".md": "text/markdown", ".sql": "application/sql", ".txt": "text/plain",
                 ".svg": "image/svg+xml", ".png": "image/png"}


def _json_default(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    raise TypeError(type(v))


class Store:
    """In-memory indexes over one dataset directory."""

    def __init__(self, path: Path, log=print, state_dir: Path | None = None, ephemeral_state=False):
        self.path = Path(path)
        log(f"[serve] loading {self.path} ...")
        t, errors = load_tables(self.path)
        if errors:
            raise SystemExit(f"dataset failed to load: {errors[:3]}")
        self.t = t
        self.gt = load_ground_truth(self.path)
        self.reports = self.path / "reports"
        self.metrics = json.loads((self.reports / "metrics.json").read_text(encoding="utf-8"))
        self.validation = json.loads((self.reports / "validation_summary.json").read_text(encoding="utf-8"))
        self.manifest = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        self.lock = threading.Lock()
        self._index()
        # Interactive proposals live in an append-only log outside the dataset folder, so the dataset's
        # checksums stay reproducible while submissions survive restarts.
        fp = fingerprint(self.manifest)
        state = Path(state_dir) if state_dir else self.path.parent / "runtime"
        last_slot = max(int(s["slot_id"][-6:]) for s in t["slot_assignment"])
        self.proposals = ProposalLog(state / f"proposals-{fp}.jsonl", fp, last_slot + 1, log=log)
        self.proposals.durable = not ephemeral_state   # False on serverless hosts (/tmp is per instance)
        log(f"[serve] {len(t['order_line']):,} order lines, {len(t['location']):,} locations ready")

    def _index(self):
        t = self.t
        by = lambda rows, k: {r[k]: r for r in rows}  # noqa: E731
        self.wh = by(t["warehouse"], "warehouse_id")
        self.zone = by(t["zone"], "zone_id")
        self.aisle = by(t["aisle"], "aisle_id")
        self.loc = by(t["location"], "location_id")
        self.sku = by(t["sku"], "sku_id")
        self.order = by(t["orders"], "order_id")
        self.slot = by(t["slot_assignment"], "slot_id")
        self.zone_classes = defaultdict(set)
        for z in t["zone_storage_class"]:
            self.zone_classes[z["zone_id"]].add(z["storage_class_code"])
        self.pairs = incompatible_pairs(t["compatibility_rule"])
        self.stock = defaultdict(list)
        for ws in t["warehouse_sku"]:
            self.stock[ws["sku_id"]].append(ws)
        self.profiles = defaultdict(list)
        for p in t["sku_profile"]:
            self.profiles[(p["warehouse_id"], p["sku_id"])].append(p)
        self.slots_by_loc, self.slots_by_sku = defaultdict(list), defaultdict(list)
        for s in t["slot_assignment"]:
            self.slots_by_loc[s["location_id"]].append(s)
            self.slots_by_sku[(s["warehouse_id"], s["sku_id"])].append(s)
        self.candidates = defaultdict(list)
        for c in t["slot_candidate"]:
            self.candidates[(c["warehouse_id"], c["sku_id"])].append(c)
        self.lines = defaultdict(list)
        for ln in t["order_line"]:
            self.lines[ln["order_id"]].append(ln)
        self.picks = defaultdict(list)
        self.picks_by_loc = Counter()
        self.picks_by_sku = Counter()
        for p in t["pick_event"]:
            self.picks[p["order_id"]].append(p)
            self.picks_by_loc[p["location_id"]] += 1
            self.picks_by_sku[(p["warehouse_id"], p["sku_id"])] += 1
        self.events = defaultdict(list)
        for e in t["state_event"]:
            self.events[e["entity_id"]].append(e)
        self.replen_by_slot = Counter(r["slot_id"] for r in t["replenishment"])
        self.exc_by_entity = defaultdict(list)
        for e in t["slotting_exception"]:
            self.exc_by_entity[e["entity_id"]].append(e)
        self.gt_by_entity = defaultdict(list)
        for g in self.gt:
            self.gt_by_entity[g["entity_id"]].append(g)
        self.orders_by_day = defaultdict(list)
        for o in t["orders"]:
            self.orders_by_day[(o["warehouse_id"], o["order_ts"].date())].append(o)
        self.blocks_by_wh = defaultdict(list)
        for b in t["aisle_block"]:
            self.blocks_by_wh[b["warehouse_id"]].append(b)
        self.held_by_block = defaultdict(list)
        for o in t["orders"]:
            if o["hold_block_id"]:
                self.held_by_block[o["hold_block_id"]].append(o["order_id"])
        self.violations_by_block = defaultdict(list)
        for e in t["slotting_exception"]:
            if e["exception_type"] == "PICK_PATH_BLOCKED_AISLE":
                m = re.search(r"ABLK-2026-\d{4}", e["details"])
                if m:
                    self.violations_by_block[m.group(0)].append(e["entity_id"])
        self.capacity = {(c["warehouse_id"], c["work_date"]): c for c in t["labor_capacity"]}
        self.replen_by_day = defaultdict(list)
        for r in t["replenishment"]:
            self.replen_by_day[(r["warehouse_id"], r["created_ts"].date())].append(r)
        self.skus_by_supplier = defaultdict(list)
        for s in t["sku"]:
            self.skus_by_supplier[s["supplier_id"]].append(s)

    # ---------------------------------------------------------------- helpers
    def profile(self, wh, sku, version=2):
        return next((p for p in self.profiles[(wh, sku)] if p["version"] == version), None)

    def plan_slots(self, wh, plan):
        """Slot per location for the LEGACY or OPT view of a warehouse."""
        out = {}
        for s in self.t["slot_assignment"]:
            if s["warehouse_id"] != wh:
                continue
            if plan == "LEGACY" and s["plan_code"] == "LEGACY_2026H2":
                out[s["location_id"]] = s
            elif plan == "OPT" and (s["plan_code"] == "OPT_PEAK_2026W42" or
                                    (s["plan_code"] == "LEGACY_2026H2" and s["status"] == "ACTIVE")):
                out[s["location_id"]] = s
        return out

    def committed_during(self, start: date, end: date | None = None):
        """Committed assignments whose [effective_from, effective_to) overlaps [start, end).

        None means open-ended on either side. An open-ended request overlaps everything that has not
        ended by `start` - including assignments that only begin later - because both would hold the
        location from the later start date onwards (rule R-04)."""
        return [s for s in self.t["slot_assignment"] + self.proposals.approved()
                if s["status"] in COMMITTED and overlaps(s["effective_from"], s["effective_to"], start, end)]

    # ------------------------------------------------------------------- views
    def summary(self):
        m = self.metrics
        return dict(dataset=m["dataset"], row_counts=m["row_counts"], scenarios=m["scenarios"],
                    slotting=m["slotting"], operations=m["operations"], exceptions=m["exceptions"],
                    ground_truth=m["ground_truth"], validation=m["validation"], profiles=m["profiles"],
                    distribution=m["distribution"],
                    calendar=dict(history=[C.HISTORY_START, C.HISTORY_END], cutover=C.CUTOVER, holdout=C.HOLDOUT,
                                  as_of=C.AS_OF))

    def warehouses(self):
        per_wh = defaultdict(dict)
        for r in _read_csv(self.reports / "scenario_by_warehouse.csv"):
            per_wh[r["warehouse_id"]][r["scenario"]] = r
        exc = Counter(e["warehouse_id"] for e in self.t["slotting_exception"])
        skus = Counter(ws["warehouse_id"] for ws in self.t["warehouse_sku"])
        out = []
        for w in self.t["warehouse"]:
            s = per_wh.get(w["warehouse_id"], {})
            base, opt = s.get("BASELINE_LEGACY"), s.get("OPT_PEAK_V2")
            gain = None
            if base and opt:
                gain = round((1 - float(opt["distance_m"]) / float(base["distance_m"])) * 100, 2)
            out.append(dict(w, skus=skus[w["warehouse_id"]], exceptions=exc[w["warehouse_id"]],
                            distance_reduction_pct=gain,
                            baseline_m_per_order=base and float(base["distance_per_order_m"]),
                            optimized_m_per_order=opt and float(opt["distance_per_order_m"])))
        return out

    def layout(self, wh, plan):
        if wh not in self.wh:
            return None
        slots = self.plan_slots(wh, plan)
        aisles = sorted((a for a in self.t["aisle"] if a["warehouse_id"] == wh), key=lambda a: a["aisle_no"])
        zones = [z for z in self.t["zone"] if z["warehouse_id"] == wh]
        locs = []
        for x in self.t["location"]:
            if x["warehouse_id"] != wh:
                continue
            s = slots.get(x["location_id"])
            prof = self.profile(wh, s["sku_id"]) if s else None
            locs.append(dict(id=x["location_id"], aisle=x["aisle_id"], side=x["side"], bay=x["bay"],
                             level=x["level"], y=x["y_m"], zone=self.zone[x["zone_id"]]["zone_type"],
                             status=x["status"], golden=x["is_golden_zone"], sku=s["sku_id"] if s else None,
                             vclass=prof["velocity_class"] if prof else None,
                             picks=self.picks_by_loc.get(x["location_id"], 0)))
        return dict(warehouse=self.wh[wh], plan=plan, zones=zones,
                    aisles=[dict(a, bay_m=round((a["length_m"] - C.FRONT_OFFSET_M) / a["bay_count"], 3),
                                 zone_type=self.zone[a["zone_id"]]["zone_type"]) for a in aisles],
                    locations=locs, blocks=len(self.blocks_by_wh[wh]))

    def location(self, lid):
        x = self.loc.get(lid)
        if not x:
            return None
        hist = sorted(self.slots_by_loc[lid], key=lambda s: s["slot_id"])
        return dict(location=x, zone=self.zone[x["zone_id"]], storage_classes=sorted(self.zone_classes[x["zone_id"]]),
                    slots=[dict(s, sku_name=self.sku[s["sku_id"]]["sku_name"], replenishments=self.replen_by_slot[
                        s["slot_id"]]) for s in hist], picks=self.picks_by_loc.get(lid, 0))

    def sku_search(self, q, wh=None, vclass=None, limit=60):
        q = (q or "").strip().lower()
        out = []
        for s in self.t["sku"]:
            if q and q not in s["sku_id"].lower() and q not in s["sku_name"].lower() and q not in s["category"].lower():
                continue
            for ws in self.stock[s["sku_id"]]:
                if wh and ws["warehouse_id"] != wh:
                    continue
                p = self.profile(ws["warehouse_id"], s["sku_id"])
                if vclass and (not p or p["velocity_class"] != vclass):
                    continue
                out.append(dict(sku_id=s["sku_id"], sku_name=s["sku_name"], category=s["category"],
                                warehouse_id=ws["warehouse_id"], storage=s["required_storage_class"],
                                hazard=s["hazard_class"], vclass=p["velocity_class"] if p else None,
                                lines_per_day=p["lines_per_day"] if p else 0, trend=p["demand_trend"] if p else None))
        out.sort(key=lambda r: (-r["lines_per_day"], r["sku_id"], r["warehouse_id"]))
        return dict(total=len(out), rows=out[:limit])

    def sku_detail(self, sid):
        s = self.sku.get(sid)
        if not s:
            return None
        sites = []
        for ws in self.stock[sid]:
            key = (ws["warehouse_id"], sid)
            sites.append(dict(stocking=ws, profiles=sorted(self.profiles[key], key=lambda p: p["version"]),
                              slots=[dict(sl, location=self.loc[sl["location_id"]], replenishments=self.replen_by_slot[
                                  sl["slot_id"]]) for sl in sorted(self.slots_by_sku[key], key=lambda x: x["slot_id"])],
                              candidates=sorted(self.candidates[key], key=lambda c: c["candidate_rank"]),
                              picks=self.picks_by_sku[key]))
        return dict(sku=s, compat_key=compat_key(s), sites=sites)

    def orders_list(self, wh, day, limit=200):
        rows = self.orders_by_day.get((wh, day), [])
        return [dict(order_id=o["order_id"], order_ts=o["order_ts"], channel=o["channel"], priority=o["priority"],
                     status=o["status"], lines=o["line_count"], units=o["total_units"],
                     distance=o["pick_distance_m"], held=bool(o["hold_block_id"])) for o in rows[:limit]]

    def order_detail(self, oid):
        o = self.order.get(oid)
        if not o:
            return None
        picks = sorted(self.picks[oid], key=lambda p: p["pick_seq"])
        return dict(order=o, lines=self.lines[oid],
                    picks=[dict(p, x=self.loc[p["location_id"]]["x_m"], y=self.loc[p["location_id"]]["y_m"],
                                aisle_no=self.aisle[p["aisle_id"]]["aisle_no"],
                                golden=self.loc[p["location_id"]]["is_golden_zone"]) for p in picks],
                    events=self.events.get(oid, []), plan="LEGACY" if o["order_ts"].date() < C.CUTOVER else "OPT",
                    exceptions=self.exc_by_entity.get(oid, []))

    def exceptions(self, q):
        rows = self.t["slotting_exception"]
        for k in ("exception_type", "severity", "warehouse_id"):
            if q.get(k):
                rows = [r for r in rows if r[k] == q[k]]
        text = (q.get("q") or "").lower()
        if text:
            rows = [r for r in rows if text in r["entity_id"].lower() or text in r["details"].lower()]
        total = len(rows)
        off = int(q.get("offset") or 0)
        page = rows[off:off + 50]
        out = []
        for r in page:
            gt = self.gt_by_entity.get(r["entity_id"], [])
            out.append(dict(r, ground_truth=[g["issue_type"] for g in gt]))
        return dict(total=total, offset=off, rows=out,
                    types=sorted({r["exception_type"] for r in self.t["slotting_exception"]}))

    def check_proposal(self, body, submit=False):
        if not submit:
            return self._evaluate(body)
        # Decide and record atomically so two concurrent submissions cannot both claim one location.
        with self.lock:
            result = self._evaluate(body)
            if result.get("error"):
                return result
            try:
                rec = self.proposals.submit(
                    result["location"]["warehouse_id"], result["sku"]["sku_id"], result["location"]["location_id"],
                    result["effective_from"], result["effective_to"],
                    body.get("requested_by"), result["decision"], result["reasons"], result["units_capacity"],
                    note=(body.get("note") or None))
            except ValueError as e:
                return dict(error=str(e))
            result["recorded"] = rec
            result["durable"] = self.proposals.durable
            return result

    def withdraw_proposal(self, slot_id, body):
        with self.lock:
            try:
                return dict(recorded=self.proposals.withdraw(slot_id, body.get("requested_by"), body.get("reason")))
            except KeyError:
                return None
            except ValueError as e:
                return dict(error=str(e))

    def proposal_history(self, slot_id):
        p = self.proposals.proposals.get(slot_id)
        return p and dict(proposal=p, events=self.proposals.history(slot_id))

    def _evaluate(self, body):
        wh, sid, lid = body.get("warehouse_id"), body.get("sku_id"), body.get("location_id")
        try:
            eff = date.fromisoformat(body.get("effective_from") or C.OVERRIDE_EFFECTIVE.isoformat())
            end = date.fromisoformat(body["effective_to"]) if body.get("effective_to") else None
        except ValueError:
            return dict(error="effective_from / effective_to must be YYYY-MM-DD")
        if end is not None and end <= eff:
            return dict(error="effective_to must be after effective_from (the end date is exclusive)")
        if wh not in self.wh:
            return dict(error=f"unknown warehouse {wh}")
        if sid not in self.sku:
            return dict(error=f"unknown SKU {sid}")
        if not any(ws["warehouse_id"] == wh for ws in self.stock[sid]):
            return dict(error=f"{sid} is not stocked at {wh} (warehouse_sku)")
        x = self.loc.get(lid)
        if not x or x["warehouse_id"] != wh:
            return dict(error=f"location {lid} does not exist in {wh}")
        sku = self.sku[sid]
        committed = self.committed_during(eff, end)
        issues = self._issues(sku, x, committed)
        if x["status"] != "ACTIVE":
            issues["LOCATION_INACTIVE"] = "location is INACTIVE (not slottable)"
        units = fit_units(sku, x)[0]
        current = next((s for s in committed if s["warehouse_id"] == wh and s["sku_id"] == sid
                        and s["assignment_source"] != "PLANNER_OVERRIDE"), None)
        result = dict(decision="REJECTED" if issues else "APPROVED",
                      reasons=[dict(code=k, detail=v) for k, v in sorted(issues.items())],
                      units_capacity=units, reorder_point=reorder_point(units) if units else None,
                      travel_seconds=round(travel_seconds(x), 1), current_slot=current and dict(
                          current, location=self.loc[current["location_id"]]),
                      location=x, sku=sku, effective_from=eff, effective_to=end,
                      alternatives=self._alternatives(sku, wh, committed))
        return result

    def _issues(self, sku, x, committed):
        occupants = [s for s in committed if s["location_id"] == x["location_id"]]
        neighbours = [dict(sku_id=s["sku_id"], compat_key=compat_key(self.sku[s["sku_id"]])) for s in committed
                      if self.loc[s["location_id"]]["bay_key"] == x["bay_key"] and s["sku_id"] != sku["sku_id"]]
        issues = location_conflicts(sku, x, occupants, neighbours, self.pairs, self.zone_classes[x["zone_id"]])
        if "DUPLICATE_ACTIVE_LOCATION" in issues:      # say *when* the location is taken, not just by whom
            issues["DUPLICATE_ACTIVE_LOCATION"] = "location already held by " + ", ".join(
                f"{s['slot_id']} ({s['effective_from']} to {s['effective_to'] or 'open'})"
                for s in sorted(occupants, key=lambda s: (s["effective_from"], s["slot_id"])))
        return issues

    def _alternatives(self, sku, wh, committed, k=5):
        used = {s["location_id"] for s in committed}
        bays = defaultdict(list)
        for s in committed:
            bays[self.loc[s["location_id"]]["bay_key"]].append(compat_key(self.sku[s["sku_id"]]))
        prof = self.profile(wh, sku["sku_id"]) or {}
        f, u = prof.get("forecast_lines_per_day", 0), prof.get("forecast_units_per_day", 0)
        key = compat_key(sku)
        out = []
        for x in self.t["location"]:
            if (x["warehouse_id"] != wh or x["status"] != "ACTIVE" or x["location_id"] in used
                    or sku["required_storage_class"] not in self.zone_classes[x["zone_id"]]):
                continue
            issue, units = capacity_issue(sku, x)
            if issue or any(frozenset((key, b)) in self.pairs for b in bays[x["bay_key"]]):
                continue
            per = max(1, units - reorder_point(units))
            pick = f * travel_seconds(x)
            rep = u / per * replen_minutes(x, per) * 60
            out.append(dict(location_id=x["location_id"], zone=self.zone[x["zone_id"]]["zone_type"],
                            golden=x["is_golden_zone"], units_capacity=units, pick_cost=round(pick, 1),
                            replen_cost=round(rep, 1), total_cost=round(pick + rep, 1)))
        out.sort(key=lambda r: (r["total_cost"], r["location_id"]))
        return out[:k]

    # ---------------------------------------------------------- actor views
    def labor(self, wh):
        """Operations manager: daily replenishment workload vs planned labor."""
        if wh not in self.wh:
            return None
        days = [dict(date=r["work_date"], workload=r["workload_min"], capacity=r["capacity_min"],
                     tasks=r["task_count"], emergency=r["emergency_count"], status=r["status"],
                     over=r["over_capacity_min"], reason=self.capacity[(wh, r["work_date"])]["capacity_reason"],
                     plan=("LEGACY" if r["work_date"] < C.CUTOVER else "OPT"))
                for r in self.t["replen_labor_daily"] if r["warehouse_id"] == wh]
        days.sort(key=lambda d: d["date"])

        def period(rows):
            n = max(1, len(rows))
            return dict(days=len(rows), avg_workload=round(sum(d["workload"] for d in rows) / n, 1),
                        avg_tasks=round(sum(d["tasks"] for d in rows) / n, 1),
                        emergency_share=round(sum(d["emergency"] for d in rows) / max(1, sum(d["tasks"] for d in rows)), 4),
                        exceeded=sum(d["status"] == "EXCEEDED" for d in rows))
        pre = [d for d in days if C.PEAK_START <= d["date"] < C.CUTOVER]
        post = [d for d in days if d["date"] >= C.CUTOVER]
        return dict(warehouse=self.wh[wh], days=days, cutover=C.CUTOVER, peak_start=C.PEAK_START,
                    peak_before_cutover=period(pre), after_cutover=period(post), all=period(days))

    def labor_day(self, wh, day):
        tasks = sorted(self.replen_by_day.get((wh, day), []), key=lambda r: r["created_ts"])
        cap = self.capacity.get((wh, day))
        return dict(warehouse_id=wh, date=day, capacity=cap,
                    tasks=[dict(r, sku_name=self.sku[r["sku_id"]]["sku_name"],
                                zone=self.zone[self.loc[r["location_id"]]["zone_id"]]["zone_type"]) for r in tasks])

    def aisle_blocks(self, wh=None):
        """Warehouse operator: aisle closures, orders held, and late-reported violations."""
        rows = []
        for b in self.t["aisle_block"]:
            if wh and b["warehouse_id"] != wh:
                continue
            late = b["reported_ts"] > b["start_ts"]
            rows.append(dict(b, zone=self.zone[self.aisle[b["aisle_id"]]["zone_id"]]["zone_type"],
                             duration_min=int((b["end_ts"] - b["start_ts"]).total_seconds() // 60),
                             late_reported=late, orders_held=self.held_by_block.get(b["block_id"], []),
                             violations=self.violations_by_block.get(b["block_id"], [])))
        rows.sort(key=lambda r: r["start_ts"], reverse=True)
        return dict(rows=rows, total=len(rows), held=sum(len(r["orders_held"]) for r in rows),
                    violations=sum(len(r["violations"]) for r in rows),
                    late_reported=sum(r["late_reported"] for r in rows))

    def shipping(self, wh=None):
        """Carrier / logistics analyst: service-level and lead-time performance per carrier service."""
        agg = defaultdict(lambda: dict(orders=0, shipped=0, on_time=0, units=0, slack=[], lead=[], cancelled=0))
        daily = defaultdict(Counter)
        for o in self.t["orders"]:
            if wh and o["warehouse_id"] != wh:
                continue
            a = agg[o["carrier_service"]]
            a["orders"] += 1
            if o["status"] == "CANCELLED":
                a["cancelled"] += 1
                continue
            if o["shipped_ts"]:
                a["shipped"] += 1
                a["units"] += o["total_units"]
                slack = (o["required_ship_ts"] - o["shipped_ts"]).total_seconds() / 3600
                a["on_time"] += slack >= 0
                a["slack"].append(slack)
                a["lead"].append((o["shipped_ts"] - o["order_ts"]).total_seconds() / 3600)
                daily[o["shipped_ts"].date()][o["carrier_service"]] += 1
        out = []
        for k, a in sorted(agg.items()):
            s, ld = sorted(a["slack"]), sorted(a["lead"])
            pick = lambda v, q: round(v[min(len(v) - 1, int(q * len(v)))], 2) if v else None  # noqa: E731
            out.append(dict(carrier_service=k, orders=a["orders"], shipped=a["shipped"], cancelled=a["cancelled"],
                            late=a["shipped"] - a["on_time"],
                            units=a["units"], on_time_rate=round(a["on_time"] / a["shipped"], 4) if a["shipped"] else None,
                            min_slack_h=pick(s, 0), p10_slack_h=pick(s, 0.10), median_slack_h=pick(s, 0.5),
                            median_lead_h=pick(ld, 0.5), p90_lead_h=pick(ld, 0.9)))
        last = sorted(daily)[-28:]
        return dict(carriers=out, daily=[dict(date=d, **daily[d]) for d in last])

    def suppliers(self):
        rows = []
        for sup in self.t["supplier"]:
            skus = self.skus_by_supplier[sup["supplier_id"]]
            picks = sum(self.picks_by_sku[(ws["warehouse_id"], s["sku_id"])] for s in skus
                        for ws in self.stock[s["sku_id"]])
            rows.append(dict(sup, skus=len(skus), picks=picks,
                             hazmat=sum(s["hazard_class"] != "NONE" for s in skus),
                             cold=sum(s["temp_class"] != "AMBIENT" for s in skus),
                             oversized=sum(s["is_oversized"] for s in skus)))
        rows.sort(key=lambda r: -r["picks"])
        return rows

    def supplier(self, sid):
        sup = next((s for s in self.t["supplier"] if s["supplier_id"] == sid), None)
        if not sup:
            return None
        items = []
        for s in self.skus_by_supplier[sid]:
            for ws in self.stock[s["sku_id"]]:
                key = (ws["warehouse_id"], s["sku_id"])
                p = self.profile(*key)
                live = next((x for x in self.slots_by_sku[key] if x["status"] == "ACTIVE"), None)
                items.append(dict(sku_id=s["sku_id"], sku_name=s["sku_name"], category=s["category"],
                                  warehouse_id=key[0], storage=s["required_storage_class"], vclass=p and p["velocity_class"],
                                  trend=p and p["demand_trend"], lines_per_day=p["lines_per_day"] if p else 0,
                                  picks=self.picks_by_sku[key], location_id=live and live["location_id"]))
        items.sort(key=lambda r: (-r["picks"], r["sku_id"]))
        return dict(supplier=sup, items=items)

    def quality(self):
        files = [f for f in self.manifest["files"]]
        return dict(validation=self.validation, manifest=dict((k, v) for k, v in self.manifest.items() if k != "files"),
                    files=files, reproducibility=self._repro())

    def _repro(self):
        # <project>/reports/reproducibility_<profile>.json, written by `python run.py reproduce`
        p = self.path.resolve().parent.parent / "reports" / f"reproducibility_{self.manifest['profile']}.json"
        if not p.exists():
            return None
        r = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in r.items() if k != "checksums"}


def overlaps(a_from, a_to, b_from, b_to):
    """Half-open date intervals [from, to); None = open-ended."""
    return (a_to is None or a_to > b_from) and (b_to is None or b_to > a_from)


def _read_csv(p):
    import csv
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Inventryx/1.0"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, default=_json_default).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, base: Path, rel: str):
            target = (base / rel).resolve()
            if base.resolve() not in target.parents or not target.is_file():
                return self._send(404, {"error": "not found"})
            ctype = (CONTENT_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
                     or "application/octet-stream")
            if ctype.startswith("text/") or ctype in ("application/json", "application/javascript", "application/sql"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            parts = [unquote(p) for p in u.path.strip("/").split("/") if p]
            try:
                if not parts:
                    return self._file(WEB, "index.html")
                if parts[0] == "static":
                    return self._file(WEB, "/".join(parts[1:]))
                if parts[0] == "files":
                    return self._file(store.path, "/".join(parts[1:]))
                if parts[0] != "api":
                    return self._file(WEB, "index.html")
                return self._api(parts[1:], q)
            except Exception as e:  # surface API errors as JSON
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _api(self, p, q):
            found = lambda v: self._send(200, v) if v is not None else self._send(404, {"error": "not found"})  # noqa
            if p == ["summary"]:
                return self._send(200, store.summary())
            if p == ["warehouses"]:
                return self._send(200, store.warehouses())
            if len(p) == 3 and p[0] == "warehouses" and p[2] == "layout":
                return found(store.layout(p[1], q.get("plan", "OPT")))
            if len(p) == 2 and p[0] == "locations":
                return found(store.location(p[1]))
            if p == ["skus"]:
                return self._send(200, store.sku_search(q.get("q"), q.get("warehouse"), q.get("vclass")))
            if len(p) == 2 and p[0] == "skus":
                return found(store.sku_detail(p[1]))
            if p == ["orders"]:
                day = date.fromisoformat(q.get("date") or C.HOLDOUT[0].isoformat())
                return self._send(200, store.orders_list(q.get("warehouse", "WH-001"), day))
            if len(p) == 2 and p[0] == "orders":
                return found(store.order_detail(p[1]))
            if p == ["exceptions"]:
                return self._send(200, store.exceptions(q))
            if p == ["proposals"]:
                return self._send(200, store.proposals.listing())
            if len(p) == 2 and p[0] == "proposals":
                return found(store.proposal_history(p[1]))
            if p == ["quality"]:
                return self._send(200, store.quality())
            if len(p) == 2 and p[0] == "labor":
                if q.get("date"):
                    return self._send(200, store.labor_day(p[1], date.fromisoformat(q["date"])))
                return found(store.labor(p[1]))
            if p == ["aisle-blocks"]:
                return self._send(200, store.aisle_blocks(q.get("warehouse")))
            if p == ["shipping"]:
                return self._send(200, store.shipping(q.get("warehouse")))
            if p == ["suppliers"]:
                return self._send(200, store.suppliers())
            if len(p) == 2 and p[0] == "suppliers":
                return found(store.supplier(p[1]))
            if p == ["scenarios"]:
                return self._send(200, _read_csv(store.reports / "scenario_by_warehouse.csv"))
            self._send(404, {"error": "unknown endpoint"})

        def do_POST(self):
            parts = [p for p in urlparse(self.path).path.strip("/").split("/") if p]
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON"})
            if parts == ["api", "proposals", "check"]:
                return self._send(200, store.check_proposal(body))
            if parts == ["api", "proposals", "submit"]:
                r = store.check_proposal(body, submit=True)
                return self._send(400 if r.get("error") else 201, r)
            if len(parts) == 4 and parts[:2] == ["api", "proposals"] and parts[3] == "withdraw":
                r = store.withdraw_proposal(parts[2], body)
                if r is None:
                    return self._send(404, {"error": f"unknown proposal {parts[2]}"})
                return self._send(400 if r.get("error") else 200, r)
            self._send(404, {"error": "unknown endpoint"})

    return Handler


class _Server(ThreadingHTTPServer):
    # SO_REUSEADDR on Windows lets two processes share a port silently; fail loudly instead.
    allow_reuse_address = False
    daemon_threads = True


STARTING_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="3">
<title>Inventryx - starting</title><style>
:root{{--bg:#f6f6f3;--fg:#1c1d1a;--mute:#6c6d66;--accent:#2f6f5e;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131412;--fg:#ebeae4;--mute:#a2a29a;--accent:#7cc3ab;--bad:#ff8a80}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}} main{{max-width:520px;padding:24px 16px;text-align:center}}
h1{{font-size:22px;margin:0 0 8px}} p{{color:var(--mute);margin:0}} .err{{color:var(--bad)}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--accent);margin-right:8px;
animation:p 1s infinite alternate}} @keyframes p{{to{{opacity:.25}}}}</style></head>
<body><main><h1><span class="dot"></span>Inventryx is starting</h1><p class="{cls}">{status}</p>
<p style="margin-top:10px">This page refreshes itself and opens the app when it is ready.</p></main></body></html>"""


def make_starting_handler(state):
    """Answers while the dataset is generated/loaded, so the browser never sees 'connection refused'."""
    class Starting(BaseHTTPRequestHandler):
        server_version = "Inventryx/1.0"

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            failed = state.get("error")
            if self.path.startswith("/api/"):
                body = json.dumps({"error": failed or "starting", "status": state["status"]}).encode()
                ctype = "application/json; charset=utf-8"
            else:
                body = STARTING_PAGE.format(status=html_escape(failed or state["status"]),
                                            cls="err" if failed else "").encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(500 if failed else 503)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", "3")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET
    return Starting


def serve(data: Path, host="127.0.0.1", port=8000, state_dir=None, prepare=None, open_browser=False):
    """Open the port first, then prepare (generate if needed) and load the dataset in the background.

    Until the data is ready every request gets a self-refreshing 'starting' page instead of a refused
    connection; the real app handler is swapped in as soon as loading finishes."""
    try:
        httpd = _Server((host, port), None)
    except OSError as e:
        raise SystemExit(f"[serve] port {port} is unavailable ({e.strerror}); try --port {port + 1}")
    state = {"status": "Loading the dataset..."}
    httpd.RequestHandlerClass = make_starting_handler(state)
    url = f"http://{host}:{port}"

    def load():
        try:
            if prepare:
                prepare(state)
            state["status"] = "Loading the dataset into memory..."
            store = Store(data, state_dir=state_dir)
            print(f"[serve] proposal log: {store.proposals.path} ({len(store.proposals.proposals)} proposals)",
                  flush=True)
            httpd.RequestHandlerClass = make_handler(store)
            print(f"[serve] Inventryx ready at {url}", flush=True)
        except BaseException as e:      # surface the reason on the page and in the console
            state["error"] = f"Start-up failed: {e}"
            print(f"[serve] {state['error']}", flush=True)

    print(f"[serve] Inventryx listening at {url} (starting up; Ctrl+C to stop)", flush=True)
    threading.Thread(target=load, daemon=True).start()
    if open_browser:              # the starting page refreshes itself until the app is ready
        import webbrowser
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
