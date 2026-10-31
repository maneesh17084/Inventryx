"""Metrics, evaluation write-up and HTML report - computed from the exported files."""
import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import config as C

SCENARIO_LABELS = {"BASELINE_LEGACY": "Baseline (legacy, velocity-blind)",
                   "OPT_STATIC_V1": "Optimized on Jul-Sep profile (v1)",
                   "OPT_PEAK_V2": "Optimized, peak-aware (v2) - deployed"}
SCENARIO_COLUMNS = ["scenario", "warehouse_id", "orders", "lines", "distance_m", "distance_per_order_m",
                    "distance_per_line_m", "picker_hours", "lines_per_picker_hour", "golden_zone_pick_share",
                    "replen_tasks", "emergency_replen", "replen_minutes", "labor_days_exceeded", "over_capacity_min",
                    "distance_reduction_pct", "throughput_gain_pct", "replen_minutes_change_pct"]
ORDER_PATH_COLUMNS = ["scenario", "order_id", "warehouse_id", "lines", "units", "distance_m", "est_seconds",
                      "golden_zone_picks"]


def write_scenarios(out: Path, rows, summary, per_wh):
    d = out / "reports"
    d.mkdir(parents=True, exist_ok=True)
    for name, cols, data in (("scenario_order_paths.csv", ORDER_PATH_COLUMNS, rows),
                             ("scenario_summary.csv", SCENARIO_COLUMNS, [summary[k] for k in summary]),
                             ("scenario_by_warehouse.csv", SCENARIO_COLUMNS[:-3], per_wh)):
        with open(d / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(cols)
            w.writerows([r.get(c) for c in cols] for r in data)


def _read_csv(p):
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_metrics(path: Path, t, gt, validation, meta):
    path = Path(path)
    scen = {r["scenario"]: r for r in _read_csv(path / "reports" / "scenario_summary.csv")}
    truth = {(r["warehouse_id"], r["sku_id"]): r for r in _read_csv(path / "ground_truth" / "demand_truth.csv")}
    loc = {x["location_id"]: x for x in t["location"]}
    zone_type = {z["zone_id"]: z["zone_type"] for z in t["zone"]}
    prof = {p["profile_id"]: p for p in t["sku_profile"]}

    # Profiles: class mix and trend detection vs hidden demand pattern.
    classes = {v: dict(Counter(p["velocity_class"] for p in t["sku_profile"] if p["version"] == v))
               for v in sorted({p["version"] for p in t["sku_profile"]})}
    confusion = defaultdict(Counter)
    for p in t["sku_profile"]:
        if p["version"] == 2:
            confusion[truth[(p["warehouse_id"], p["sku_id"])]["demand_pattern"]][p["demand_trend"]] += 1
    seasonal = confusion["SEASONAL_PEAK"]
    flagged_up = sum(confusion[k]["PEAK_UP"] for k in confusion)

    # Slotting plans.
    plans = {}
    for code in ("LEGACY_2026H2", "OPT_PEAK_2026W42"):
        rows = [s for s in t["slot_assignment"] if s["plan_code"] == code]
        a_rows = []
        for s in rows:
            v2 = prof.get(f"SKP-{s['warehouse_id']}-{s['sku_id']}-V2")
            if v2 and v2["velocity_class"] == "A":
                a_rows.append(s)
        plans[code] = dict(
            slots=len(rows),
            a_class_skus=len(a_rows),
            a_class_in_forward_pick_pct=round(100 * sum(zone_type[loc[s["location_id"]]["zone_id"]] == "FORWARD_PICK"
                                                        for s in a_rows) / max(1, len(a_rows)), 2),
            a_class_in_golden_zone_pct=round(100 * sum(loc[s["location_id"]]["is_golden_zone"] for s in a_rows)
                                             / max(1, len(a_rows)), 2),
            mean_units_capacity=round(sum(s["units_capacity"] for s in rows) / max(1, len(rows)), 2))
    legacy = {(s["warehouse_id"], s["sku_id"]): s["location_id"] for s in t["slot_assignment"]
              if s["plan_code"] == "LEGACY_2026H2"}
    opt = [s for s in t["slot_assignment"] if s["plan_code"] == "OPT_PEAK_2026W42"]
    plans["moves_at_cutover"] = sum(1 for s in opt if legacy.get((s["warehouse_id"], s["sku_id"])) != s["location_id"])
    active_locs = sum(1 for x in t["location"] if x["status"] == "ACTIVE")
    plans["location_utilisation_pct"] = round(100 * len(opt) / active_locs, 2)
    overrides = Counter(s["status"] for s in t["slot_assignment"] if s["assignment_source"] == "PLANNER_OVERRIDE")

    # Operations (actual history).
    rld = t["replen_labor_daily"]
    gt_labor = {g["entity_id"]: g["origin"] for g in gt if g["issue_type"] == "REPLEN_LABOR_EXCEEDED"}
    exceeded_by_month = defaultdict(Counter)
    for r in rld:
        if r["status"] == "EXCEEDED":
            exceeded_by_month[r["work_date"].strftime("%Y-%m")][gt_labor.get(r["labor_day_id"], "?")] += 1
    ops = dict(orders=len(t["orders"]), cancelled=sum(o["status"] == "CANCELLED" for o in t["orders"]),
               order_lines=len(t["order_line"]), picks=len(t["pick_event"]),
               orders_held_for_blocked_aisle=sum(1 for o in t["orders"] if o["hold_block_id"]),
               aisle_blocks=len(t["aisle_block"]),
               replen_tasks=dict(Counter(r["replen_type"] for r in t["replenishment"])),
               replen_over_capacity_tasks=sum(r["labor_status"] == "OVER_CAPACITY" for r in t["replenishment"]),
               labor_days=len(rld), labor_days_exceeded=sum(r["status"] == "EXCEEDED" for r in rld),
               labor_days_exceeded_by_month={k: dict(v) for k, v in sorted(exceeded_by_month.items())})
    exceptions = dict(by_type=dict(Counter(e["exception_type"] for e in t["slotting_exception"])),
                      by_severity=dict(Counter(e["severity"] for e in t["slotting_exception"])))
    return dict(dataset=meta, row_counts={k: len(v) for k, v in t.items()},
                distribution=validation["distribution"],
                profiles=dict(velocity_class_by_version=classes,
                              trend_vs_hidden_pattern={k: dict(v) for k, v in sorted(confusion.items())},
                              seasonal_sku_peak_up_recall=round(seasonal["PEAK_UP"] / max(1, sum(seasonal.values())), 4),
                              peak_up_precision=round(seasonal["PEAK_UP"] / max(1, flagged_up), 4)),
                slotting=dict(plans=plans, planner_overrides=dict(overrides)),
                scenarios={k: {c: _num(v[c]) for c in SCENARIO_COLUMNS[2:]} for k, v in scen.items()},
                operations=ops, exceptions=exceptions,
                ground_truth=dict(rows=len(gt), by_issue=dict(Counter(g["issue_type"] for g in gt)),
                                  by_origin=dict(Counter(g["origin"] for g in gt)),
                                  detection=validation["ground_truth_metrics"]),
                validation=dict(total=validation["total"], passed=validation["passed"], failed=validation["failed"],
                                by_category=validation["by_category"]))


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except (TypeError, ValueError):
        return v


def write_validation(path: Path, validation):
    d = Path(path) / "reports"
    body = {k: v for k, v in validation.items()}
    (d / "validation_summary.json").write_text(json.dumps(body, indent=1, default=str) + "\n", encoding="utf-8",
                                               newline="\n")
    lines = ["# Validation summary", "",
             f"**{validation['passed']} / {validation['total']} checks passed, {validation['failed']} failed.**", "",
             "| Category | Passed | Failed |", "|---|---:|---:|"]
    for cat, c in validation["by_category"].items():
        lines.append(f"| {cat} | {c.get('PASS', 0)} | {c.get('FAIL', 0)} |")
    lines += ["", "| Status | Category | Check | Violations | Sample |", "|---|---|---|---:|---|"]
    for c in validation["checks"]:
        sample = "; ".join(c["sample"]).replace("|", "/")
        lines.append(f"| {c['status']} | {c['category']} | {c['check']} | {c['violations']} | {sample} |")
    (d / "validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_evaluation(path: Path, m):
    s = m["scenarios"]
    b, o, st = s["BASELINE_LEGACY"], s["OPT_PEAK_V2"], s["OPT_STATIC_V1"]
    gtm = m["ground_truth"]["detection"]
    lines = [
        "# Slotting evaluation", "",
        f"Dataset `{m['dataset']['profile']}` - seed {m['dataset']['seed']} - holdout "
        f"{C.HOLDOUT[0]} to {C.HOLDOUT[1]} ({b['orders']:,} orders, {b['lines']:,} lines, same orders in every scenario).",
        "", "## Pick path and throughput (out-of-sample)", "",
        "| Scenario | Distance / order (m) | Distance vs baseline | Lines / picker-hour | Throughput vs baseline "
        "| Golden-zone picks |", "|---|---:|---:|---:|---:|---:|"]
    def vs_base(k, value):
        return "baseline" if k == "BASELINE_LEGACY" else f"{value:+.2f}%"

    for k in ("BASELINE_LEGACY", "OPT_STATIC_V1", "OPT_PEAK_V2"):
        x = s[k]
        lines.append(f"| {SCENARIO_LABELS[k]} | {x['distance_per_order_m']:.2f} "
                     f"| {vs_base(k, -x['distance_reduction_pct'])} | {x['lines_per_picker_hour']:.2f} "
                     f"| {vs_base(k, x['throughput_gain_pct'])} | {100 * x['golden_zone_pick_share']:.1f}% |")
    lines += ["", "## Replenishment impact (same holdout picks)", "",
              "| Scenario | Tasks | Emergency | Labor minutes | vs baseline | Days over capacity | Minutes over |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for k in ("BASELINE_LEGACY", "OPT_STATIC_V1", "OPT_PEAK_V2"):
        x = s[k]
        lines.append(f"| {SCENARIO_LABELS[k]} | {x['replen_tasks']:,} | {x['emergency_replen']:,} "
                     f"| {x['replen_minutes']:,.1f} | {vs_base(k, x['replen_minutes_change_pct'])} "
                     f"| {x['labor_days_exceeded']} | {x['over_capacity_min']:,.1f} |")
    pl = m["slotting"]["plans"]
    lines += ["", "## Slotting decisions", "",
              f"- SKUs re-slotted at cutover ({C.CUTOVER}): **{pl['moves_at_cutover']:,}** of "
              f"{pl['OPT_PEAK_2026W42']['slots']:,}; location utilisation {pl['location_utilisation_pct']}%.",
              f"- A-class SKUs in forward-pick zone: legacy {pl['LEGACY_2026H2']['a_class_in_forward_pick_pct']}% -> "
              f"optimized {pl['OPT_PEAK_2026W42']['a_class_in_forward_pick_pct']}%; in golden zone "
              f"{pl['LEGACY_2026H2']['a_class_in_golden_zone_pct']}% -> {pl['OPT_PEAK_2026W42']['a_class_in_golden_zone_pct']}%.",
              f"- Peak-aware v2 vs static v1: distance {o['distance_per_order_m']:.2f} vs {st['distance_per_order_m']:.2f} "
              f"m/order; replenishment {o['replen_minutes']:,.0f} vs {st['replen_minutes']:,.0f} min.",
              f"- Planner overrides: {m['slotting']['planner_overrides']}.",
              f"- Seasonal SKUs detected as PEAK_UP: recall {m['profiles']['seasonal_sku_peak_up_recall']:.1%}, "
              f"precision {m['profiles']['peak_up_precision']:.1%}.",
              "", "## Exception detection vs ground truth", "",
              "| Issue type | Positives | Flagged | TP | FP | FN | Precision | Recall |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in gtm.items():
        if k == "NEGATIVE_CONTROLS":
            continue
        lines.append(f"| {k} | {v['positives']} | {v['flagged']} | {v['tp']} | {v['fp']} | {v['fn']} "
                     f"| {v['precision']} | {v['recall']} |")
    nc = gtm["NEGATIVE_CONTROLS"]
    lines += ["", f"Negative/boundary controls: {nc['controls']}, false alarms {nc['false_alarms']} "
                  f"(specificity {nc['specificity']}).", "",
              "## Validation", "", f"{m['validation']['passed']} / {m['validation']['total']} checks passed "
                                   f"({m['validation']['failed']} failed) - see validation_summary.md.", ""]
    (Path(path) / "reports" / "evaluation.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_metrics(path: Path, m):
    (Path(path) / "reports" / "metrics.json").write_text(json.dumps(m, indent=1, default=str) + "\n",
                                                         encoding="utf-8", newline="\n")


def write_html(path: Path, m, validation):
    e = html.escape
    s = m["scenarios"]
    kpis = [("Pick distance / order", f"{s['OPT_PEAK_V2']['distance_per_order_m']:.1f} m",
             f"{-s['OPT_PEAK_V2']['distance_reduction_pct']:+.1f}% vs baseline {s['BASELINE_LEGACY']['distance_per_order_m']:.1f} m"),
            ("Lines / picker-hour", f"{s['OPT_PEAK_V2']['lines_per_picker_hour']:.1f}",
             f"{s['OPT_PEAK_V2']['throughput_gain_pct']:+.1f}% vs baseline"),
            ("Replenishment labor", f"{s['OPT_PEAK_V2']['replen_minutes']:,.0f} min",
             f"{s['OPT_PEAK_V2']['replen_minutes_change_pct']:+.1f}% vs baseline"),
            ("Validation", f"{validation['passed']}/{validation['total']}", f"{validation['failed']} failed checks")]
    tiles = "".join(f"<div class='tile'><div class='k'>{e(a)}</div><div class='v'>{e(b)}</div>"
                    f"<div class='d'>{e(c)}</div></div>" for a, b, c in kpis)

    def bar_rows(metric, fmt):
        top = max(float(s[k][metric]) for k in s) or 1
        return "".join(
            f"<tr><td>{e(SCENARIO_LABELS[k])}</td><td class='num'>{fmt(float(s[k][metric]))}</td>"
            f"<td class='barcell'><div class='bar {'hi' if k == 'OPT_PEAK_V2' else ''}' "
            f"style='width:{100 * float(s[k][metric]) / top:.1f}%'></div></td></tr>"
            for k in ("BASELINE_LEGACY", "OPT_STATIC_V1", "OPT_PEAK_V2"))

    gt_rows = "".join(
        f"<tr><td>{e(k)}</td><td class='num'>{v['positives']}</td><td class='num'>{v['tp']}</td>"
        f"<td class='num'>{v['fp']}</td><td class='num'>{v['fn']}</td><td class='num'>{v['precision']}</td>"
        f"<td class='num'>{v['recall']}</td></tr>"
        for k, v in m["ground_truth"]["detection"].items() if k != "NEGATIVE_CONTROLS")
    exc_rows = "".join(f"<tr><td>{e(k)}</td><td class='num'>{v:,}</td></tr>"
                       for k, v in sorted(m["exceptions"]["by_type"].items(), key=lambda x: -x[1]))
    val_rows = "".join(f"<tr><td>{e(k)}</td><td class='num'>{v.get('PASS', 0)}</td>"
                       f"<td class='num {'bad' if v.get('FAIL') else ''}'>{v.get('FAIL', 0)}</td></tr>"
                       for k, v in validation["by_category"].items())
    labor = "".join(f"<tr><td>{e(k)}</td><td class='num'>{v.get('RULE_DERIVED', 0)}</td>"
                    f"<td class='num'>{v.get('INJECTED', 0)}</td></tr>"
                    for k, v in m["operations"]["labor_days_exceeded_by_month"].items())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Inventryx Report</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--mute:#6b6b66;--card:#fff;--line:#e3e2dc;--accent:#2f6f5e;--accent2:#9fb8ae;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151614;--fg:#ecebe6;--mute:#a3a29b;--card:#1f201d;--line:#34352f;--accent:#7cc3ab;--accent2:#4a5d55;--bad:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:24px 16px 48px}} h1{{font-size:26px;margin:0 0 4px}}
h2{{font-size:18px;margin:32px 0 10px}} .sub{{color:var(--mute)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:20px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.k{{color:var(--mute);font-size:13px}} .v{{font-size:24px;font-weight:600;margin:4px 0}} .d{{font-size:13px;color:var(--mute)}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
td,th{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}}
th{{color:var(--mute);font-weight:500}} .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.barcell{{width:38%}} .bar{{height:10px;border-radius:5px;background:var(--accent2)}} .bar.hi{{background:var(--accent)}}
.bad{{color:var(--bad);font-weight:600}} .wrap{{overflow-x:auto}}
</style></head><body><main>
<h1>Inventryx - warehouse slotting evaluation report</h1>
<div class="sub">Dataset {e(m['dataset']['profile'])} · seed {m['dataset']['seed']} · holdout {C.HOLDOUT[0]} to {C.HOLDOUT[1]} ·
{s['BASELINE_LEGACY']['orders']:,} orders replayed identically in every scenario</div>
<div class="tiles">{tiles}</div>
<h2>Pick distance per order (m)</h2><div class="wrap"><table>{bar_rows('distance_per_order_m', lambda v: f'{v:.2f}')}</table></div>
<h2>Lines per picker-hour</h2><div class="wrap"><table>{bar_rows('lines_per_picker_hour', lambda v: f'{v:.1f}')}</table></div>
<h2>Replenishment labor minutes (holdout)</h2><div class="wrap"><table>{bar_rows('replen_minutes', lambda v: f'{v:,.0f}')}</table></div>
<h2>Exception detection vs ground truth</h2><div class="wrap"><table><tr><th>Issue</th><th class="num">Positives</th>
<th class="num">TP</th><th class="num">FP</th><th class="num">FN</th><th class="num">Precision</th><th class="num">Recall</th></tr>{gt_rows}</table></div>
<h2>Labor-capacity exceedances by month</h2><div class="wrap"><table><tr><th>Month</th><th class="num">Rule-derived (demand)</th>
<th class="num">Injected (absenteeism)</th></tr>{labor}</table></div>
<h2>Engine exceptions raised</h2><div class="wrap"><table><tr><th>Type</th><th class="num">Count</th></tr>{exc_rows}</table></div>
<h2>Validation</h2><div class="wrap"><table><tr><th>Category</th><th class="num">Passed</th><th class="num">Failed</th></tr>{val_rows}</table></div>
</main></body></html>
"""
    (Path(path) / "reports" / "report.html").write_text(page, encoding="utf-8", newline="\n")
