# Business rules and generation logic

Every derived value and every label in the dataset comes from one of the rules below. Rule IDs appear in
`slotting_exception.rule_id`. The code for each rule lives in `inventryx/rules.py` and is used by the optimizer,
the decision engine and the validator alike, so there is exactly one definition of each rule.

## Placement rules (hard constraints)

| ID | Rule | Definition | Engine action |
|---|---|---|---|
| R-01 | Location capacity | A unit must fit the location allowing rotation (sorted SKU dims <= sorted location dims), its weight must not exceed the rated load, and the slot must hold at least `sku.max_order_qty` units. `units_capacity = min(floor(W/w)*floor(D/d)*floor(H/h), floor(max_weight/unit_weight))` on sorted dimensions. Sub-codes: DIMENSION, WEIGHT, UNIT_CAPACITY. | Reject proposal |
| R-02 | Storage class | `sku.required_storage_class` must be in the zone's allowed classes (`zone_storage_class`). Class precedence: hazard_class != NONE -> HAZMAT; FROZEN; CHILLED; oversized (max dim > 60 cm or volume > 60 L) -> OVERSIZE; else AMBIENT. BULK zones allow AMBIENT + OVERSIZE. | Reject proposal (critical) |
| R-03 | Co-location compatibility | Two SKUs whose compatibility keys form a pair in `compatibility_rule` must not share a bay (`location.bay_key` = aisle + side + bay) during overlapping effective periods. Key = hazard class if hazardous, else compat group (FOOD / GENERAL). | Reject proposal (critical) |
| R-04 | One assignment per location | No two committed (ACTIVE / SUPERSEDED / APPROVED) assignments may hold the same location over overlapping `[effective_from, effective_to)` periods. | Reject proposal |

Only ACTIVE locations are slottable (0.5% of locations are INACTIVE, i.e. damaged racking).

## Operational rules

| ID | Rule | Definition | Engine action |
|---|---|---|---|
| R-05 | Blocked aisle | A pick confirmed in an aisle while an `aisle_block` covers it (`start_ts <= pick_ts < end_ts`, end exclusive) is a safety violation. | Escalate safety audit (critical) |
| R-06 | Replenishment labor | Daily replenishment workload (`SUM(task_minutes)` of tasks created that day) strictly greater than `labor_capacity.replen_capacity_min`. Tasks past the cumulative limit are marked `OVER_CAPACITY`. | Schedule overtime or defer |
| R-07 | Blocked-aisle hold (handled path) | When a released tour would enter an aisle that is blocked at that moment, the order goes ON_HOLD and is re-released at the block's `end_ts`. | Defer order (info) |
| R-08 | No feasible slot | The optimizer finds no location satisfying R-01..R-04; the legacy slot is retained. Prevented in practice by class reservations (below). | Manual review |

## Slotting optimizer (`inventryx/optimizer.py`)

* **Legacy (as-is) plan** - SKUs in random receiving order, each placed in a uniformly random feasible location.
  It is velocity-blind but obeys R-01..R-04, so the baseline is valid but not efficient.
* **Optimized plans** - greedy, cost-based. SKUs are processed by descending forecast pick frequency; each takes the
  free feasible location with the lowest daily cost:
  * `pick_cost = forecast_lines_per_day * ((x + 2y) / 1.0 m/s + 4 s if not golden zone)` - return routing shares the
    cross-aisle walk across an order's lines, while depth into the aisle is walked twice.
  * `replen_cost = forecast_units_per_day / (capacity - reorder_point) * task_minutes * 60`.
  * Idle SKUs (zero forecast) take the *farthest* feasible slot, keeping good slots free.
  * **Class reservation:** a SKU may take a location in a multi-class zone only while every other class served by
    that zone keeps at least as many free locations as it has unplaced SKUs. Without it, fast ambient movers would
    take every BULK slot and starve oversized items (the first version of this generator hit exactly that, which
    produced 10 R-08 exceptions on the starter set).
  * The top 3 candidates per SKU are stored in `slot_candidate`, with their cost components, for traceability.
* `OPT_STATIC_V1` uses the July-September profile; `OPT_PEAK_V2` (the deployed plan) uses the peak-aware v2 forecast.

## Velocity profiles (`inventryx/profiling.py`)

* v1: window 2026-07-01..09-30, effective 10-01..10-15. v2: window 10-01..10-14, effective from 10-15.
* `lines_per_day = order_lines / window_days`, counting picked (non-cancelled) lines by order date.
* Velocity class per warehouse and version: rank by lines; **A** while the cumulative share of lines before the
  SKU is < 80%, **B** while < 95%, **C** otherwise, **D** when there are no lines.
* Demand trend (v2): `ratio = lines_per_day / prior lines_per_day`; >= 1.8 PEAK_UP, <= 0.5 DOWN, else STABLE;
  NEW / INACTIVE when the prior had no lines.
* Forecast (v2): `(lines + 14 * prior_rate * lift) / (window_days + 14)`, where `lift` is the warehouse's total
  line-rate ratio. This shrinks noisy 14-day estimates toward the longer history while keeping the peak shift.

## Pick path simulation (`inventryx/simulation.py`)

* One picker per order (discrete order picking), depot at (0, 0) on the front cross-aisle.
* **Return routing:** aisles are visited in ascending order; inside an aisle the picker walks to increasing depth and
  exits the way they came in. `travel_from_prev_m` stores each leg and `orders.return_to_depot_m` the final leg.
* Time model: 45 s order setup, 1.0 m/s walking, 8 s per pick + 4 s outside the golden zone + 1.5 s per extra unit.
* Release delay after order: 5-20 min for EXPRESS orders, 10-75 min for STANDARD orders. Ship 20-180 min after picking.

## Replenishment model

* Every slot starts full. Reorder point = `floor(0.30 * capacity)`.
* **EMERGENCY**: before a pick whose quantity exceeds on-hand, the slot is refilled to capacity (the task completes at
  the pick time).
* **SCHEDULED**: at the end of a day with picks, if on-hand <= reorder point, the slot is refilled at 21:00 (or 1 minute
  after the last pick).
* `task_minutes = 3.0 + 2*(x + y)/1.2 m/s/60 + 0.02 * units + 1.5 if level >= 4`.
* Labor plan: per warehouse, the 95th percentile of July-September daily workload x 1.05, rounded up to 15 minutes.

## Synthetic data distributions

| Aspect | Generation rule |
|---|---|
| Warehouses | 20 sites, sizes U(0.8, 1.2) relative weight; locations split exactly with largest-remainder allocation |
| Zones (share of locations) | FORWARD_PICK 24%, SHELF 30%, CHILLED 12%, FROZEN 9%, HAZMAT 7%, BULK 18%; laid out from the dock outward |
| Location sizes | Standard rack sizes per zone type (e.g. flow rack 50-90 x 60-80 x 35-50 cm, 40-60 kg; pallet 120 x 100-120 x 120-180 cm, 600-1000 kg) |
| SKU class mix | ambient 71%, oversize 5%, chilled 10%, frozen 8%, hazmat 6% (classes 3, 8, 5.1, 2.1, 9) |
| SKU dimensions | lognormal per class, clipped; weight = volume x class-specific density (0.06-1.3 kg/L); every SKU is guaranteed to fit its class's smallest main-zone slot with `max_order_qty` units |
| Stocking | primary warehouse weighted by size; 25% of SKUs in a second warehouse, 5% in a third |
| Demand per warehouse-SKU | lognormal(0, 1.25) base weight (heavy tail: top 20% of SKUs ~ 64% of lines); 0.6x for secondary sites |
| Demand pattern (hidden) | STEADY 80%, SEASONAL_PEAK 12% (x2.5-5 from Oct 1), DECLINING 8% (x0.15-0.4 from Oct 1) |
| Daily volume | weekday factors Mon-Sun 1.10/1.05/1.00/1.00/1.05/0.75/0.55; x1.35 from 2026-10-01 |
| Orders | ECOM 62% (1 + geometric lines, max 6), RETAIL 28% (max 12), B2B 10% (2-20 lines); 0.6% cancelled |
| Order time | triangular(06:00, 21:00, mode 12:00) |

## Edge-case injection (`inventryx/anomalies.py`)

Baseline records are generated valid first. Injection then **adds** records (it never edits baseline rows). Each
candidate is checked against the rules and kept only if it violates exactly its intended rule:

| Case | How it is injected | Label |
|---|---|---|
| SKU exceeds location capacity | Planner override moving an ambient SKU into a free ambient location it does not fit | `LOCATION_CAPACITY_EXCEEDED` |
| Incompatible products co-located | Override placing a hazmat SKU into a free hazmat-zone slot whose bay holds an incompatible class | `INCOMPATIBLE_CO_LOCATION` |
| Storage/temperature mismatch | Override placing a frozen/chilled/ambient SKU into a zone that does not provide its class | `STORAGE_CLASS_MISMATCH` |
| Slot duplicates active location | Override targeting an occupied location, or a second override targeting a location approved minutes earlier | `DUPLICATE_ACTIVE_LOCATION` |
| Pick path uses blocked aisle | A late-reported aisle block (reported after it ended) covering picks that already happened | `PICK_PATH_BLOCKED_AISLE` (every pick inside the window) |
| Replenishment exceeds labor | Absenteeism cuts a calm day's capacity to 50-85% of its workload; peak days also exceed the plan naturally | `REPLEN_LABOR_EXCEEDED`, origin INJECTED or RULE_DERIVED |
| Controls | Valid overrides; boundary overrides where capacity == max_order_qty exactly; blocks ending exactly at a pick (end exclusive); capacity == workload exactly | `NONE` (negative control) |
