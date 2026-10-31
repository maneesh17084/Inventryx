# Validation summary

**210 / 210 checks passed, 0 failed.**

| Category | Passed | Failed |
|---|---:|---:|
| date_order | 7 | 0 |
| distribution | 9 | 0 |
| duplicates | 14 | 0 |
| enum | 22 | 0 |
| foreign_key | 46 | 0 |
| ground_truth | 9 | 0 |
| join | 11 | 0 |
| leakage | 2 | 0 |
| lifecycle | 4 | 0 |
| physical_constraints | 3 | 0 |
| primary_key | 22 | 0 |
| reconciliation | 13 | 0 |
| reproducibility | 2 | 0 |
| schema | 45 | 0 |
| sql | 1 | 0 |

| Status | Category | Check | Violations | Sample |
|---|---|---|---:|---|
| PASS | schema | CSV headers match schema; every value parses to its declared type | 0 |  |
| PASS | schema | storage_class: required fields populated | 0 |  |
| PASS | enum | storage_class: allowed values | 0 |  |
| PASS | schema | storage_class: ID / code formats | 0 |  |
| PASS | primary_key | storage_class: primary key unique | 0 |  |
| PASS | schema | warehouse: required fields populated | 0 |  |
| PASS | enum | warehouse: allowed values | 0 |  |
| PASS | schema | warehouse: ID / code formats | 0 |  |
| PASS | primary_key | warehouse: primary key unique | 0 |  |
| PASS | duplicates | warehouse.warehouse_name: unique | 0 |  |
| PASS | schema | zone: required fields populated | 0 |  |
| PASS | enum | zone: allowed values | 0 |  |
| PASS | schema | zone: ID / code formats | 0 |  |
| PASS | primary_key | zone: primary key unique | 0 |  |
| PASS | duplicates | zone: natural key warehouse_id+zone_code unique | 0 |  |
| PASS | schema | zone_storage_class: required fields populated | 0 |  |
| PASS | enum | zone_storage_class: allowed values | 0 |  |
| PASS | schema | zone_storage_class: ID / code formats | 0 |  |
| PASS | primary_key | zone_storage_class: primary key unique | 0 |  |
| PASS | schema | aisle: required fields populated | 0 |  |
| PASS | enum | aisle: allowed values | 0 |  |
| PASS | schema | aisle: ID / code formats | 0 |  |
| PASS | primary_key | aisle: primary key unique | 0 |  |
| PASS | duplicates | aisle: natural key warehouse_id+aisle_no unique | 0 |  |
| PASS | schema | location: required fields populated | 0 |  |
| PASS | enum | location: allowed values | 0 |  |
| PASS | schema | location: ID / code formats | 0 |  |
| PASS | primary_key | location: primary key unique | 0 |  |
| PASS | duplicates | location: natural key aisle_id+side+bay+level unique | 0 |  |
| PASS | schema | supplier: required fields populated | 0 |  |
| PASS | enum | supplier: allowed values | 0 |  |
| PASS | schema | supplier: ID / code formats | 0 |  |
| PASS | primary_key | supplier: primary key unique | 0 |  |
| PASS | schema | sku: required fields populated | 0 |  |
| PASS | enum | sku: allowed values | 0 |  |
| PASS | schema | sku: ID / code formats | 0 |  |
| PASS | primary_key | sku: primary key unique | 0 |  |
| PASS | schema | warehouse_sku: required fields populated | 0 |  |
| PASS | enum | warehouse_sku: allowed values | 0 |  |
| PASS | schema | warehouse_sku: ID / code formats | 0 |  |
| PASS | primary_key | warehouse_sku: primary key unique | 0 |  |
| PASS | schema | compatibility_rule: required fields populated | 0 |  |
| PASS | enum | compatibility_rule: allowed values | 0 |  |
| PASS | schema | compatibility_rule: ID / code formats | 0 |  |
| PASS | primary_key | compatibility_rule: primary key unique | 0 |  |
| PASS | duplicates | compatibility_rule: natural key key_a+key_b unique | 0 |  |
| PASS | schema | sku_profile: required fields populated | 0 |  |
| PASS | enum | sku_profile: allowed values | 0 |  |
| PASS | schema | sku_profile: ID / code formats | 0 |  |
| PASS | primary_key | sku_profile: primary key unique | 0 |  |
| PASS | duplicates | sku_profile: natural key warehouse_id+sku_id+version unique | 0 |  |
| PASS | schema | slot_assignment: required fields populated | 0 |  |
| PASS | enum | slot_assignment: allowed values | 0 |  |
| PASS | schema | slot_assignment: ID / code formats | 0 |  |
| PASS | primary_key | slot_assignment: primary key unique | 0 |  |
| PASS | schema | slot_candidate: required fields populated | 0 |  |
| PASS | enum | slot_candidate: allowed values | 0 |  |
| PASS | schema | slot_candidate: ID / code formats | 0 |  |
| PASS | primary_key | slot_candidate: primary key unique | 0 |  |
| PASS | duplicates | slot_candidate: natural key plan_code+warehouse_id+sku_id+candidate_rank unique | 0 |  |
| PASS | schema | aisle_block: required fields populated | 0 |  |
| PASS | enum | aisle_block: allowed values | 0 |  |
| PASS | schema | aisle_block: ID / code formats | 0 |  |
| PASS | primary_key | aisle_block: primary key unique | 0 |  |
| PASS | schema | orders: required fields populated | 0 |  |
| PASS | enum | orders: allowed values | 0 |  |
| PASS | schema | orders: ID / code formats | 0 |  |
| PASS | primary_key | orders: primary key unique | 0 |  |
| PASS | schema | order_line: required fields populated | 0 |  |
| PASS | enum | order_line: allowed values | 0 |  |
| PASS | schema | order_line: ID / code formats | 0 |  |
| PASS | primary_key | order_line: primary key unique | 0 |  |
| PASS | duplicates | order_line: natural key order_id+line_no unique | 0 |  |
| PASS | schema | pick_event: required fields populated | 0 |  |
| PASS | enum | pick_event: allowed values | 0 |  |
| PASS | schema | pick_event: ID / code formats | 0 |  |
| PASS | primary_key | pick_event: primary key unique | 0 |  |
| PASS | duplicates | pick_event.order_line_id: unique | 0 |  |
| PASS | schema | replenishment: required fields populated | 0 |  |
| PASS | enum | replenishment: allowed values | 0 |  |
| PASS | schema | replenishment: ID / code formats | 0 |  |
| PASS | primary_key | replenishment: primary key unique | 0 |  |
| PASS | schema | labor_capacity: required fields populated | 0 |  |
| PASS | enum | labor_capacity: allowed values | 0 |  |
| PASS | schema | labor_capacity: ID / code formats | 0 |  |
| PASS | primary_key | labor_capacity: primary key unique | 0 |  |
| PASS | duplicates | labor_capacity: natural key warehouse_id+work_date unique | 0 |  |
| PASS | schema | replen_labor_daily: required fields populated | 0 |  |
| PASS | enum | replen_labor_daily: allowed values | 0 |  |
| PASS | schema | replen_labor_daily: ID / code formats | 0 |  |
| PASS | primary_key | replen_labor_daily: primary key unique | 0 |  |
| PASS | duplicates | replen_labor_daily: natural key warehouse_id+work_date unique | 0 |  |
| PASS | schema | state_event: required fields populated | 0 |  |
| PASS | enum | state_event: allowed values | 0 |  |
| PASS | schema | state_event: ID / code formats | 0 |  |
| PASS | primary_key | state_event: primary key unique | 0 |  |
| PASS | schema | slotting_exception: required fields populated | 0 |  |
| PASS | enum | slotting_exception: allowed values | 0 |  |
| PASS | schema | slotting_exception: ID / code formats | 0 |  |
| PASS | primary_key | slotting_exception: primary key unique | 0 |  |
| PASS | foreign_key | zone.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | zone_storage_class.zone_id -> zone.zone_id | 0 |  |
| PASS | foreign_key | zone_storage_class.storage_class_code -> storage_class.storage_class_code | 0 |  |
| PASS | foreign_key | aisle.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | aisle.zone_id -> zone.zone_id | 0 |  |
| PASS | foreign_key | location.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | location.zone_id -> zone.zone_id | 0 |  |
| PASS | foreign_key | location.aisle_id -> aisle.aisle_id | 0 |  |
| PASS | foreign_key | sku.supplier_id -> supplier.supplier_id | 0 |  |
| PASS | foreign_key | sku.required_storage_class -> storage_class.storage_class_code | 0 |  |
| PASS | foreign_key | warehouse_sku.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | warehouse_sku.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | sku_profile.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | sku_profile.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | sku_profile.prior_profile_id -> sku_profile.profile_id | 0 |  |
| PASS | foreign_key | slot_assignment.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | slot_assignment.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | slot_assignment.location_id -> location.location_id | 0 |  |
| PASS | foreign_key | slot_assignment.profile_id -> sku_profile.profile_id | 0 |  |
| PASS | foreign_key | slot_assignment.previous_slot_id -> slot_assignment.slot_id | 0 |  |
| PASS | foreign_key | slot_candidate.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | slot_candidate.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | slot_candidate.profile_id -> sku_profile.profile_id | 0 |  |
| PASS | foreign_key | slot_candidate.location_id -> location.location_id | 0 |  |
| PASS | foreign_key | slot_candidate.slot_id -> slot_assignment.slot_id | 0 |  |
| PASS | foreign_key | aisle_block.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | aisle_block.aisle_id -> aisle.aisle_id | 0 |  |
| PASS | foreign_key | orders.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | orders.hold_block_id -> aisle_block.block_id | 0 |  |
| PASS | foreign_key | order_line.order_id -> orders.order_id | 0 |  |
| PASS | foreign_key | order_line.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | pick_event.order_id -> orders.order_id | 0 |  |
| PASS | foreign_key | pick_event.order_line_id -> order_line.order_line_id | 0 |  |
| PASS | foreign_key | pick_event.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | pick_event.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | pick_event.slot_id -> slot_assignment.slot_id | 0 |  |
| PASS | foreign_key | pick_event.location_id -> location.location_id | 0 |  |
| PASS | foreign_key | pick_event.aisle_id -> aisle.aisle_id | 0 |  |
| PASS | foreign_key | replenishment.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | replenishment.sku_id -> sku.sku_id | 0 |  |
| PASS | foreign_key | replenishment.slot_id -> slot_assignment.slot_id | 0 |  |
| PASS | foreign_key | replenishment.location_id -> location.location_id | 0 |  |
| PASS | foreign_key | labor_capacity.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | replen_labor_daily.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | foreign_key | replen_labor_daily.labor_capacity_id -> labor_capacity.labor_capacity_id | 0 |  |
| PASS | foreign_key | slotting_exception.warehouse_id -> warehouse.warehouse_id | 0 |  |
| PASS | join | zone/aisle IDs embed their warehouse | 0 |  |
| PASS | join | location: ID embeds zone, zone/aisle/warehouse consistent, bay_key and x derived | 0 |  |
| PASS | join | order_line: ID embeds order; SKU stocked at order's warehouse | 0 |  |
| PASS | join | pick_event: order/line/SKU/slot/location/aisle all agree | 0 |  |
| PASS | join | replenishment: slot/SKU/location/warehouse agree | 0 |  |
| PASS | join | slot_assignment: location in same warehouse; SKU stocked; profile matches | 0 |  |
| PASS | join | sku_profile: exactly one profile per stocked warehouse-SKU per version | 0 |  |
| PASS | join | slot_candidate: selected candidate is the slot's location | 0 |  |
| PASS | join | replen_labor_daily: capacity record matches warehouse/date | 0 |  |
| PASS | join | state_event: polymorphic entity_id resolves | 0 |  |
| PASS | join | slotting_exception: entity_id resolves | 0 |  |
| PASS | date_order | orders: order <= release <= (hold release) <= picks <= picked <= shipped | 0 |  |
| PASS | date_order | slot_assignment: effective_from < effective_to; created/decision ordering | 0 |  |
| PASS | date_order | sku_profile: window_start <= window_end < effective_from < effective_to | 0 |  |
| PASS | date_order | aisle_block: start < end | 0 |  |
| PASS | date_order | replenishment: created <= completed | 0 |  |
| PASS | date_order | pick_event: slot in force on the pick date | 0 |  |
| PASS | date_order | stocking starts after SKU creation; locations after warehouse opening | 0 |  |
| PASS | reconciliation | warehouse/zone counts = COUNT(children) | 0 |  |
| PASS | reconciliation | location: volume_l and is_golden_zone derived correctly | 0 |  |
| PASS | reconciliation | sku: volume, oversize flag and storage class derived correctly | 0 |  |
| PASS | reconciliation | orders: line_count and total_units = SUM(order_line) | 0 |  |
| PASS | reconciliation | order_line: qty_picked = SUM(pick_event.qty); status consistent | 0 |  |
| PASS | reconciliation | pick tours: sequence, legs, return leg and pick_distance_m re-derived by router | 0 |  |
| PASS | reconciliation | sku_profile: lines, units, active days and rates re-derived from order lines | 0 |  |
| PASS | reconciliation | slot_assignment: units_capacity = fit, reorder point = floor(0.30 x capacity) | 0 |  |
| PASS | reconciliation | slot_candidate: total = pick + replen | 0 |  |
| PASS | reconciliation | replenishment: units = after - before; after = capacity; minutes re-derived | 0 |  |
| PASS | reconciliation | replenishment: pick-face inventory balance replayed from pick events | 0 |  |
| PASS | reconciliation | replen_labor_daily: workload, utilisation, status = SUM(replenishment) vs capacity | 0 |  |
| PASS | reconciliation | holdout: actual history == OPT_PEAK replay (distance, replen tasks) | 0 |  |
| PASS | lifecycle | state_event: every transition is allowed by the entity lifecycle | 0 |  |
| PASS | lifecycle | state_event: each from_status equals the previous to_status (no gaps) | 0 |  |
| PASS | lifecycle | state_event: IDs are chronological (append-only log) | 0 |  |
| PASS | lifecycle | current status column == last state_event (history not overwritten) | 0 |  |
| PASS | duplicates | no two committed assignments hold one location at the same time | 0 |  |
| PASS | duplicates | one live slot per warehouse-SKU at any time (approved moves excluded) | 0 |  |
| PASS | duplicates | state_event: no duplicated transitions | 0 |  |
| PASS | physical_constraints | committed slots: SKU fits (dimensions, weight, max_order_qty) | 0 |  |
| PASS | physical_constraints | committed slots: zone provides the SKU's storage class; location ACTIVE | 0 |  |
| PASS | physical_constraints | committed slots: no incompatible goods share a bay | 0 |  |
| PASS | reproducibility | engine re-run on CSVs reproduces every proposal decision | 0 |  |
| PASS | reproducibility | detectors re-run on CSVs reproduce slotting_exception | 0 |  |
| PASS | leakage | no label/ground-truth columns in any input or derived table | 0 |  |
| PASS | leakage | ground truth stored only under ground_truth/ | 0 |  |
| PASS | sql | schema.sql + seed.sql load into SQLite with FK enforcement; row counts match CSV | 0 |  |
| PASS | ground_truth | every ground-truth entity exists in the dataset | 0 |  |
| PASS | ground_truth | LOCATION_CAPACITY_EXCEEDED: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | STORAGE_CLASS_MISMATCH: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | INCOMPATIBLE_CO_LOCATION: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | DUPLICATE_ACTIVE_LOCATION: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | PICK_PATH_BLOCKED_AISLE: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | REPLEN_LABOR_EXCEEDED: engine flags == ground truth (precision & recall = 1) | 0 |  |
| PASS | ground_truth | negative and boundary controls raise no exception | 0 |  |
| PASS | ground_truth | proposal decisions match expected_decision | 0 |  |
| PASS | distribution | top20_sku_line_share within [0.55, 0.95] | 0 |  |
| PASS | distribution | peak_volume_lift within [1.2, 1.7] | 0 |  |
| PASS | distribution | weekend_weekday_ratio within [0.5, 0.85] | 0 |  |
| PASS | distribution | oversized_share within [0.03, 0.12] | 0 |  |
| PASS | distribution | hazmat_share within [0.03, 0.09] | 0 |  |
| PASS | distribution | cold_chain_share within [0.12, 0.25] | 0 |  |
| PASS | distribution | class_d_profiles within [1, inf] | 0 |  |
| PASS | distribution | peak_up_trends within [1, inf] | 0 |  |
| PASS | distribution | down_trends within [1, inf] | 0 |  |
