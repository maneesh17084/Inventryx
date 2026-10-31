# Inventryx: warehouse slotting with synthetic data, an optimizer and evaluation

This project places SKUs into warehouse locations using demand velocity, dimensions, hazard and temperature
compatibility, and pick and replenishment constraints. It is one reproducible pipeline:

> master data → orders → velocity profiles → candidate slots → slot assignments → pick-path and replenishment
> simulation → labelled edge cases → decision engine → validation → CSV / JSON / SQL exports and reports

The runtime is pure Python standard library (3.10+, tested on 3.11, 3.12 and 3.13). The full dataset (20 warehouses, 10,000 locations, 5,000 SKUs,
100,000 order lines) builds, validates and exports in about 80 seconds, and a rebuild with the same seed is
byte-identical.

## Headline results (full dataset, seed 20261022)

All three plans are replayed on the same **5,276 held-out orders** (2026-10-15 → 10-28, never seen by the optimizer),
using the same routing policy, timestamps and replenishment model. Only the SKU→location map differs between them.

| Plan | Distance / order | Lines / picker-hour | Golden-zone picks | Replen labor (min) | Days over labor cap |
|---|---:|---:|---:|---:|---:|
| Baseline: legacy, velocity-blind | 67.19 m | 66.81 | 41.8% | 7,999 | 14 |
| Optimized on Jul–Sep profile (v1) | 55.03 m (−18.1%) | 74.48 (+11.5%) | 69.7% | 3,031 (−62.1%) | 0 |
| **Optimized, peak-aware (v2), deployed** | **54.37 m (−19.1%)** | **74.95 (+12.2%)** | **71.2%** | **2,958 (−63.0%)** | **0** |

* **Edge-case detection:** for all 6 labelled issue types, the decision engine's exceptions match `ground_truth.csv`
  exactly (precision = recall = 1.0 on 223 positives), with 0 false alarms on 70 negative and boundary controls.
* **Validation:** 210 of 210 checks pass, covering primary keys, foreign keys, enums, join consistency, date
  ordering, arithmetic reconciliation, lifecycle, duplicates, physical constraints, engine reproducibility, label
  leakage, SQL load and distribution realism.
* **Reproducibility:** two regenerations with the same seed produce identical SHA-256 checksums for all 58 files
  (`reports/reproducibility_full.json`, `reports/reproducibility_starter.json`).

Details: [data/starter/reports/evaluation.md](data/starter/reports/evaluation.md) (starter) and
`data/full/reports/` after a full build. Each dataset also has a self-contained `reports/report.html`.

## Run it

Requirements: Python 3.10+ (tested on 3.11, 3.12 and 3.13). No packages to install.

| How | Command |
|---|---|
| Windows, double-click | `Inventryx.bat` |
| Any terminal, any folder | `python path/to/Inventryx/run.py` (add `--starter` for the small dataset) |
| VS Code | Run and Debug → "Inventryx: start web app (full data)", or press ▶ on `run.py` |
| Explicit | `python -m inventryx serve --data data/full --port 8000 --open` (from the project folder) |

The app opens in your browser at http://127.0.0.1:8000. On the first run of the full dataset it shows an
"Inventryx is starting" page for about a minute while it generates and validates `data/full`. **Keep the terminal
window open**; closing it stops the app.

* **Busy port:** if port 8000 is used by another program, `run.py` and `Inventryx.bat` pick the next free port.
  If Inventryx is already running, they just open it.
* **Other commands:** `run.py` and `Inventryx.bat` pass any command through, e.g.
  `python run.py generate --profile full --seed 7 --out data/full-seed7`.

| Symptom | Cause and fix |
|---|---|
| Browser: `ERR_CONNECTION_REFUSED` | No server is running. Start it again with one of the commands above and keep the window open |
| `No module named inventryx` | `python -m inventryx` was run outside the project folder; use `run.py`, which works from anywhere |
| `port 8000 is unavailable` | Another program holds the port; use `run.py`, or pass `--port 8001` |
| `needs Python 3.10 or newer` | Install a current Python from python.org |

## Deploy on Vercel

The repository deploys to Vercel as-is: import it in Vercel, or push to a connected repo, with no build settings
to change.

* `api/index.py` serves the whole app (pages, static files and the JSON API) as one Python function. It reuses
  the same request handler as the local server.
* `vercel.json` rewrites every URL to that function, bundles `inventryx/`, `data/starter/` and `reports/`, and
  serves nothing else statically.

Differences from running locally:

| | Local (`python run.py`) | Vercel |
|---|---|---|
| Dataset | `data/full` (generated on first run) or `data/starter` | `data/starter` (bundled; the filesystem is read-only, so the full dataset can't be generated there) |
| Proposal log | Durable, append-only, survives restarts | Kept in the instance's temp folder, so lost when the instance is recycled. The register shows a "Demo hosting" notice |
| First request | About a minute on a fresh `data/full` | A cold start of about 1–2 s while the starter data loads |

A `404 NOT_FOUND` page from Vercel means the deployment predates these files. Redeploy the latest commit.

## Web app: Inventryx

`python -m inventryx serve` defaults to `--data data/full --port 8000 --host 127.0.0.1`. If the `--data` folder has
no dataset yet, it is generated and validated first; the profile comes from the folder name, `full` or `starter`.
The port opens immediately, and a self-refreshing "starting" page is shown until the data is loaded.

A **"View as"** selector tailors the navigation to each actor in the problem statement: slotting planner,
warehouse operator, operations manager, logistics analyst, carrier and supplier. The selector only filters the
menu; it is not a login, and every page stays reachable by URL.

A complete operations front end over the dataset and the live rule engine. It needs no build step and no CDN,
so it works offline. It is served by a standard-library HTTP server (`inventryx/server.py`) with a JSON API, and the
single-page app lives in `inventryx/web/`.

| Page | What you can do |
|---|---|
| Overview | KPIs, plan comparison (distance, throughput, replenishment, golden-zone share), slotting decisions, exceptions, labor-capacity breaches by month, per-warehouse results |
| Warehouse map | Top-down rack map of any warehouse: switch legacy vs optimized plan, colour by velocity class / zone / pick heat; click a location for size, status and full slot history |
| SKUs | Search by ID, name or category; filter by warehouse and class; detail page shows v1/v2 profiles, slot history with decision reasons, and the optimizer's top-3 candidates with cost breakdown |
| Orders & pick tours | Browse any day's orders; an order shows its routed tour drawn on the map, line-by-line legs and the full event history (incl. blocked-aisle holds) |
| Aisle blocks | Warehouse operator: every closure with its window and reporting time, the orders held and re-released, and late-reported blocks that led to picks in a closed aisle |
| Replenishment & labor | Operations manager: daily workload vs planned labor per warehouse (chart with capacity line and plan cut-over), peak before vs after re-slotting, days over capacity; click a day for its task list |
| Shipping & carriers | Carrier / analyst: per carrier service orders, on-time handover, late count, slack to the promised ship time, lead-time percentiles, daily shipment mix |
| Suppliers | Supplier: assortment size, demand driven, special-handling counts; supplier page lists each SKU's velocity class and current slot |
| Exceptions | Filterable, paginated decision log with evidence, rule IDs and the ground-truth label for each case |
| Slot proposals | What-if tool: propose SKU → location and the engine applies R-01..R-04 live, explains violations and ranks the cheapest valid alternatives. Submissions (with planner ID and optional note) are written to a durable, append-only proposal log; approved ones occupy the slot in every later check, including after a restart, until withdrawn. Click a register row for its event history |
| Data quality | All validation checks by category, reproducibility status, seed/command, and download links for every CSV / JSON / SQL / report file |

API endpoints: `/api/summary`, `/api/warehouses`, `/api/warehouses/{id}/layout?plan=LEGACY|OPT`,
`/api/locations/{id}`, `/api/skus?q=&warehouse=&vclass=`, `/api/skus/{id}`, `/api/orders?warehouse=&date=`,
`/api/orders/{id}`, `/api/exceptions?exception_type=&severity=&warehouse_id=&q=&offset=`,
`POST /api/proposals/check|submit`, `/api/proposals`, `/api/labor/{wh}[?date=]`, `/api/aisle-blocks`,
`/api/shipping`, `/api/suppliers[/{id}]`, `/api/quality`, `/api/proposals/{id}` (event history),
`POST /api/proposals/{id}/withdraw`, plus `/files/<path>` downloads.

### Interactive proposals are persisted as events, never overwritten

`inventryx/proposals.py` keeps one append-only JSONL log per dataset in `data/runtime/` (override with `--state-dir`),
outside the dataset folder so the dataset's checksums stay reproducible. Each state change is a new line:

| Event | Fields |
|---|---|
| `PROPOSAL_SUBMITTED` | `slot_id` (continues the `SLOT-2026-nnnnnn` sequence after the generated assignments), timestamp, warehouse, SKU, location, `effective_from`, optional `effective_to` (exclusive), planner ID (`PLN-nn`), note |
| `PROPOSAL_DECIDED` | timestamp, actor `SLOTTING_ENGINE`, decision APPROVED/REJECTED, reason codes with evidence, units that fit |
| `PROPOSAL_WITHDRAWN` | timestamp, planner ID, reason; only for APPROVED proposals, and it frees the location |

* **Restart:** the server replays the log on start-up, so approved proposals keep taking part in duplicate-location
  and bay-compatibility checks.
* **Effective dates:** conflicts are decided by **period overlap** on half-open intervals `[effective_from,
  effective_to)`, against both generated assignments and approved proposals. Examples, given an approved
  proposal from 2026-12-01 with no end date:
  * a request for 2026-11-01 → 2026-12-01 is **approved**, because it ends as December starts;
  * an open-ended request from 2026-11-01 is **rejected** with "held by SLOT-… (2026-12-01 to open)". Approving
    it would put two SKUs in the location from December 1, which rule R-04 forbids.
  * An earlier-dated proposal does not ignore later ones; it just has to end before they start.
* **Durability and concurrency:** each line is fsync'd before the state changes, and deciding plus recording runs
  under one lock, so concurrent submissions cannot double-book a location.
* **Validation on replay:** illegal transitions and lines from a different dataset are rejected. A torn final line
  from a crash is skipped and reported, not fatal.
* **Tests:** `tests/test_proposals.py` covers restart persistence, append-only history, withdrawal, bad input,
  a corrupted log and concurrent submissions. `tests/test_effective_dates.py` covers the future-dated scenarios
  above, interval edge cases, bounded periods across a restart, and invalid end dates.

## Quick start

```bash
python -m inventryx generate --profile starter --seed 20261022 --out data/starter    # 2 WH, 1k loc, 500 SKUs, 10k lines (~9 s)
python -m inventryx generate --profile full --seed 20261022 --out data/full          # 20 WH, 10k loc, 5k SKUs, 100k lines (~80 s)
python -m inventryx generate --profile full --seed 7 --out data/full-seed7           # another seed, kept separate
python -m inventryx validate --data data/full                                        # re-run all checks on exported files
python -m inventryx reproduce --profile full --seed 20261022                       # build twice, compare counts + checksums
python -m inventryx docs                                                             # regenerate data dictionary and ERD
python -m inventryx serve --data data/full --port 8000                               # web app at http://127.0.0.1:8000
python -m inventryx package                                                        # clean delivery zip (see below)
python -m pytest -q                                                                 # 86 tests
```

`generate` replaces whatever is in `--out` (default `data/<profile>`), so always pass `--out` when trying another
seed. Otherwise you overwrite the reference dataset that the web app and the reproducibility report use.

**Packaging:** `python -m inventryx package` writes `Inventryx.zip` **next to** the project folder (never inside
it, so the delivery can't contain a copy of itself). Everything sits under a top-level `Inventryx/` folder; change the
name with `--root-name`. The zip holds the source, docs, tests, launchers, the starter dataset and reports. Excluded by
name at any depth:

* **Environments and VCS:** `.venv/`, `venv/`, `env/`, `.git/`
* **Caches:** `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.ipynb_checkpoints/`
* **Compiled files:** `*.pyc`, `*.pyo`
* **OS files:** `.DS_Store`, `Thumbs.db`
* **Logs and temp files:** `*.log`, `*.tmp`, `*.bak`
* **Nested archives:** `*.zip`, `dist/`
* **Runtime state:** proposal logs in `data/runtime/`
* **Leftover reproducibility folders:** `run_a/`, `run_b/`, `inventryx-repro-*`
* **Regenerable datasets:** `data/full/`; rebuild it byte-identically with `python run.py generate --profile full`

Your local folders, including `.venv`, are not touched.

The starter and full datasets come from the **same generator**. Profiles differ only in scale parameters
(`inventryx/config.py`). `data/starter/` is committed; `data/full/` (~270 MB) is git-ignored because one command
regenerates it byte for byte.

## Repository layout

```
inventryx/
  config.py       scale profiles, calendar, operating parameters, fixed seed
  schema.py       single source of truth: tables, fields, types, enums, FKs, rules, cardinality
  ids.py          deterministic IDs, seeded RNG sub-streams, exact integer allocation
  rules.py        business rules R-01..R-08, shared by the optimizer, engine and validator
  master.py       Warehouse, Zone, Aisle, Location, Supplier, SKU, stocking bridge
  demand.py       orders and order lines (fast/slow movers, weekday pattern, peak shift)
  profiling.py    SKUProfile v1/v2 derived from order lines, with the peak-aware forecast
  optimizer.py    candidate slots and assignment: legacy, static and peak-aware plans
  simulation.py   return-routing pick tours, blocked-aisle holds, replenishment, labor plan
  anomalies.py    labelled edge cases and controls -> ground truth
  engine.py       decision engine: proposal approval, detectors, labor analysis
  events.py       append-only state_event history
  evaluation.py   out-of-sample scenario replay
  validate.py     all validation checks, run against the exported CSVs
  export.py       CSV / JSON / SQL / manifest writers and the typed loader
  report.py       metrics.json, evaluation.md, report.html
  server.py       web app: JSON API + static file server (python -m inventryx serve)
  web/            single-page frontend (index.html, app.js, style.css)
run.py            launcher: works from any folder / VS Code Run; picks a free port; opens the browser
Inventryx.bat     Windows double-click launcher (wraps run.py)
.vscode/          launch configurations: start app (full / starter), generate, run tests
api/index.py      Vercel entry point (serverless function serving the whole app)
vercel.json       Vercel routing and function bundle configuration
docs/             data_dictionary.md, erd.md, business_rules.md, provenance.md
tests/            rule unit tests, end-to-end tests, mutation tests
data/<profile>/   csv/ json/ sql/ schema/ ground_truth/ reports/ manifest.json
```

## How the challenge steps map to the build

| Step | Where |
|---|---|
| 1. Data dictionary | [docs/data_dictionary.md](docs/data_dictionary.md), generated from `schema.py` (type, required, allowed values, units, uniqueness, FK, validation rule, derived flag) and also exported as `data/*/schema/data_dictionary.json` |
| 2. Parents before children | `pipeline.py` order; `seed.sql` inserts in FK order. Zone capacities/dimensions, SKU size/weight/hazard/temperature/velocity, order-line pick frequencies, candidate slots, assignments, pick paths and replenishment workload are all derived by the code |
| 3. Deterministic IDs | `ids.py`: `WH-001`, `LOC-WH-001-Z01-000001`, `SKU-000001`, `ORD-2026-000001`, `PICK-ORD-2026-000001-001`, `SLOT-2026-000001`, plus `WH-001-Z01`, `WH-001-A001`, `REPL-2026-000001`, `EVT-2026-0000001`, ... All zero-padded and assigned once |
| 4. Baseline volume | 20 / 10,000 / 5,000 / 100,000 exactly; fast and slow movers (top 20% of SKUs ≈ 64% of lines; 3,390 zero-pick profiles), 5.6% oversized, 6% hazmat, 18.5% cold-chain, +35% October volume with seasonal and declining SKUs. Seed 20261022 |
| 5. Valid first, then edge cases | `anomalies.py` adds new records only; [business rules: injection](docs/business_rules.md#edge-case-injection-slottinganomaliespy) |
| 6. Derived values | counts, totals, distances, capacities, reorder points, velocity classes, workloads and statuses are computed from source rows and re-derived by the validator |
| 7. Separate ground truth | `ground_truth/ground_truth.csv/.json` (293 rows: 223 positives, 70 controls) and `demand_truth.csv` (hidden demand parameters). The leakage check confirms no label columns exist in any table |
| 8. Validation | `validate.py` → `reports/validation_summary.md/json` |
| 9. Exports | `csv/`, `json/`, `sql/schema.sql` + `sql/seed.sql` (SQLite and PostgreSQL), `schema/`, `manifest.json` (seed, command, scale, row counts, SHA-256 per file), README and docs |
| 10. Reproducibility | `python -m inventryx reproduce` builds twice in a temporary folder (removed afterwards) → `reports/reproducibility_<profile>.json` |

## Data model

22 tables (see the [ERD](docs/erd.md) and the [data dictionary](docs/data_dictionary.md)):

* **Master and reference:** `warehouse` 1:N `zone` 1:N `aisle` 1:N `location`; `supplier` 1:N `sku`;
  `storage_class`; `compatibility_rule`; `labor_capacity` (one per warehouse-day).
* **Bridges (N:M):** `zone_storage_class` (zone ↔ storage class), `warehouse_sku` (warehouse ↔ SKU), and
  `slot_assignment`, the time-bounded SKU ↔ location bridge with `effective_from` / `effective_to` (exclusive),
  `previous_slot_id` supersession chains and a lifecycle of PROPOSED → APPROVED/REJECTED, or ACTIVE → SUPERSEDED.
* **Derived:** `sku_profile` (versioned per warehouse-SKU, with `prior_profile_id` chain), `slot_candidate` (top 3
  per SKU with cost breakdown), `replen_labor_daily`, `slotting_exception` (the engine's decision log).
* **Transactions and events:** `orders` 1:N `order_line` 1:0..1 `pick_event`; `replenishment`; `aisle_block`.
* **History:** `state_event` is an append-only log of every status change for orders, slots, replenishments and
  aisles. The current `status` column always equals the last event, and the validator proves it, so history is
  never overwritten.

## Decision logic (summary; full spec in [docs/business_rules.md](docs/business_rules.md))

* **Hard constraints:**
  * **R-01** physical fit with rotation, rated weight, and room for `max_order_qty`.
  * **R-02** storage/temperature class.
  * **R-03** no incompatible goods in the same bay (e.g. oxidizer 5.1 vs flammables 3 / 2.1, food vs hazmat).
  * **R-04** one assignment per location over any overlapping period.
* **Optimizer:** greedy by forecast pick frequency. Each SKU takes the feasible slot that minimises
  `pick-travel seconds/day + replenishment seconds/day`, and the top 3 candidates are stored. A class-reservation
  guard stops ambient SKUs from consuming the bulk slots that oversized SKUs need.
* **Peak awareness:** the v2 profile blends the 14-day October signal with July–September history, scaled by the
  warehouse's volume lift. It flags 72.8% of the hidden seasonal SKUs as `PEAK_UP`.
* **Exception path:**
  * Planner override proposals go through the engine and are APPROVED or REJECTED with reason codes.
  * Tours that would cross a known blocked aisle are put ON_HOLD and re-released at the block's end (108 orders).
  * Late-reported blocks are escalated as safety violations.
  * Labor-capacity breaches are flagged per warehouse-day, and tasks beyond capacity are marked `OVER_CAPACITY`.

### A trade-off the cost model exposes

The optimizer moves A-class SKUs into the golden zone (42% → 69%), but *fewer* of them into the forward-pick flow
racks (23% → 18%). Flow-rack faces are small, so fast movers placed there would need replenishment many times a day.
The combined cost puts them in nearby golden-level shelf slots instead and leaves the flow racks to small items.
That is why replenishment labor falls 63% while pick distance still falls 19%. A pick-distance-only objective would
not show this trade-off.

## Edge cases and ground truth

| Required edge case | Injected as | Count (full) |
|---|---|---:|
| SKU exceeds location capacity | planner override into a slot too small or too weak (DIMENSION / WEIGHT / UNIT_CAPACITY) | 40 |
| Incompatible products co-located | hazmat override into a bay holding an incompatible class | 20 |
| (extra) Storage/temperature mismatch | e.g. frozen SKU proposed for an ambient shelf | 20 |
| Slot duplicates active location | override onto an occupied location, or two overrides racing for one free slot | 30 |
| Pick path uses blocked aisle | late-reported aisle blocks overlapping executed picks | 25 picks |
| Replenishment exceeds labor capacity | 20 absenteeism days (injected) + 68 peak days (rule-derived) | 88 days |
| Negative / boundary controls | valid overrides, capacity == max_order_qty, pick at block end (exclusive), workload == capacity | 70 |

Every injected candidate is kept only if the shared rules say it violates **exactly** its intended rule. Labels
record `origin` (INJECTED vs RULE_DERIVED) and `expected_decision`, and they never appear in the input tables.

## Validation

`reports/validation_summary.md` lists every check with its violation count and samples. Highlights:

* **Re-derivation:** every pick tour is re-routed from location coordinates; every profile is re-aggregated from
  order lines; pick-face inventory is replayed from pick events and must reproduce every replenishment task; daily
  labor workload is re-summed.
* **Engine reproducibility:** the decision engine and detectors are re-run on the CSVs and must reproduce every
  stored decision and exception.
* **Holdout reconciliation:** the actual post-cutover history equals the OPT_PEAK replay (distance and replenishment
  tasks), which proves the scenario comparison uses the same mechanics as the recorded history.
* **SQL:** `schema.sql` + `seed.sql` load into SQLite with `PRAGMA foreign_keys = ON`, and row counts match the CSVs.
* **Mutation tests** (`tests/test_pipeline.py`) corrupt the exported files: a dangling FK, a duplicated PK, a broken
  total, a deleted history event, a double-booked location, and a dropped label. Each test asserts that the
  matching category fails.

## Assumptions and limitations

* Warehouses are compact (about 500 locations and 10 aisles each) because the specified volume is 10,000 locations
  over 20 sites. Absolute distances are small, so the relative changes are what matter.
* Picking is single-order with return routing; batching and S-shape routing are not modelled. Replenishment comes
  from a reserve area at the depot with unlimited reserve stock.
* The greedy optimizer is a strong, transparent heuristic, not a proven optimum.
* Detection precision and recall are 1.0 **by construction**: labels and detectors implement the same documented
  rules. Treat those figures as coverage and consistency evidence, not as a measure of model accuracy. The
  non-trivial evaluation is the out-of-sample slotting comparison and the trend detection (72.8% recall, 35.5%
  precision on hidden seasonal SKUs).
* Approved overrides become effective 2026-11-02, after the data's as-of time (2026-10-30), so their activation (and
  the superseding of the SKU's current slot) is intentionally not yet in the history.

## Provenance

The data is 100% synthetic, contains no personal data, and uses no external datasets. See
[docs/provenance.md](docs/provenance.md).
