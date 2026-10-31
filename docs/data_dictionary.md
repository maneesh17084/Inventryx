# Data dictionary

Generated from `inventryx/schema.py` (`python -m inventryx docs`). Types: str, int, float, bool, date (YYYY-MM-DD), datetime (YYYY-MM-DDTHH:MM:SS, warehouse local time). Empty CSV cell = NULL. `derived` columns are calculated from source records, never generated independently.

| Table | Kind | Rows describe | Primary key |
|---|---|---|---|
| [storage_class](#storage_class) | reference | Storage/handling classes a SKU can require and a zone can provide. | storage_class_code |
| [warehouse](#warehouse) | master | Distribution centre. Root of the physical hierarchy. | warehouse_id |
| [zone](#zone) | master | Temperature/handling zone inside a warehouse. 1 warehouse : N zones. | zone_id |
| [zone_storage_class](#zone_storage_class) | bridge | N:M bridge - which storage classes each zone may hold. | zone_id, storage_class_code |
| [aisle](#aisle) | master | Pick aisle. Picker enters/exits from the front cross-aisle (y = 0). | aisle_id |
| [location](#location) | master | Storage/pick location (one slot face). | location_id |
| [supplier](#supplier) | master | Supplier of SKUs (actor: supplier). | supplier_id |
| [sku](#sku) | master | Item master with physical and compatibility attributes. | sku_id |
| [warehouse_sku](#warehouse_sku) | bridge | N:M bridge - which warehouses stock which SKUs. | warehouse_id, sku_id |
| [compatibility_rule](#compatibility_rule) | reference | Pairs of compatibility keys that must not share a bay. | rule_id |
| [sku_profile](#sku_profile) | derived | Versioned velocity profile per warehouse-SKU, derived from order lines. | profile_id |
| [slot_assignment](#slot_assignment) | transaction | Time-bounded SKU->location assignment (N:M SKU-Location bridge with history). | slot_id |
| [slot_candidate](#slot_candidate) | derived | Top-3 candidate slots evaluated per SKU for the optimized plan. | candidate_id |
| [aisle_block](#aisle_block) | event | Aisle closure window (maintenance, spill...). | block_id |
| [orders](#orders) | transaction | Customer/store order (table named orders; ORDER is reserved in SQL). | order_id |
| [order_line](#order_line) | transaction | Order line. 1 order : N lines. | order_line_id |
| [pick_event](#pick_event) | event | One pick confirmation inside an order tour. | pick_id |
| [replenishment](#replenishment) | event | Reserve-to-pick-face replenishment task. | replen_id |
| [labor_capacity](#labor_capacity) | master | Planned replenishment labor per warehouse-day. | labor_capacity_id |
| [replen_labor_daily](#replen_labor_daily) | derived | Replenishment workload vs capacity per warehouse-day. | labor_day_id |
| [state_event](#state_event) | event | Append-only status history for orders, slots, replenishments and aisles. | event_id |
| [slotting_exception](#slotting_exception) | derived | Exceptions raised by the slotting engine (decision log). | exception_id |

## storage_class

*reference* - Storage/handling classes a SKU can require and a zone can provide.

Primary key: `storage_class_code`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `storage_class_code` | str | Y |  | AMBIENT, CHILLED, FROZEN, HAZMAT, OVERSIZE | Y |  |  | Storage class code |
| `description` | str | Y |  |  |  |  |  | Human-readable description |
| `temp_min_c` | float | Y | degC |  |  |  |  | Minimum storage temperature |
| `temp_max_c` | float | Y | degC |  |  |  | temp_min_c < temp_max_c | Maximum storage temperature |

## warehouse

*master* - Distribution centre. Root of the physical hierarchy.

Primary key: `warehouse_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `warehouse_id` | str | Y |  | `^WH-\d{3}$` | Y |  |  | Warehouse ID |
| `warehouse_name` | str | Y |  |  | Y |  |  | Synthetic site name |
| `region` | str | Y |  | NORTH, SOUTH, EAST, WEST, CENTRAL |  |  |  | Operating region |
| `operator_code` | str | Y |  | `^OPR-\d{2}$` |  |  |  | Warehouse operator (3PL/own) code |
| `opened_date` | date | Y |  |  |  |  | < 2026-07-01 | Site opening date |
| `status` | str | Y |  | ACTIVE |  |  |  | Lifecycle state |
| `aisle_pitch_m` | float | Y | m |  |  |  |  | Centre-to-centre aisle spacing |
| `location_count` | int | Y |  |  |  |  |  (derived) | Number of locations (derived = COUNT(location)) |
| `zone_count` | int | Y |  |  |  |  |  (derived) | Number of zones (derived = COUNT(zone)) |
| `aisle_count` | int | Y |  |  |  |  |  (derived) | Number of aisles (derived = COUNT(aisle)) |

## zone

*master* - Temperature/handling zone inside a warehouse. 1 warehouse : N zones.

Primary key: `zone_id` · Natural keys: `warehouse_id+zone_code`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `zone_id` | str | Y |  | `^WH-\d{3}-Z\d{2}$` | Y |  |  | Zone ID = <warehouse_id>-Znn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Parent warehouse |
| `zone_code` | str | Y |  | `^Z\d{2}$` |  |  |  | Zone code within warehouse |
| `zone_type` | str | Y |  | FORWARD_PICK, SHELF, CHILLED, FROZEN, HAZMAT, BULK |  |  |  | Functional zone type |
| `temp_class` | str | Y |  | AMBIENT, CHILLED, FROZEN |  |  |  | Zone temperature regime |
| `travel_rank` | int | Y |  |  |  |  | >= 1 | 1 = closest to the dock/depot |
| `aisle_count` | int | Y |  |  |  |  |  (derived) | Derived = COUNT(aisle) |
| `location_count` | int | Y |  |  |  |  |  (derived) | Derived = COUNT(location) |
| `status` | str | Y |  | ACTIVE |  |  |  | Lifecycle state |

## zone_storage_class

*bridge* - N:M bridge - which storage classes each zone may hold.

Primary key: `zone_id, storage_class_code`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `zone_id` | str | Y |  | `^WH-\d{3}-Z\d{2}$` |  | zone.zone_id |  | Zone |
| `storage_class_code` | str | Y |  | AMBIENT, CHILLED, FROZEN, HAZMAT, OVERSIZE |  | storage_class.storage_class_code |  | Allowed storage class |

## aisle

*master* - Pick aisle. Picker enters/exits from the front cross-aisle (y = 0).

Primary key: `aisle_id` · Natural keys: `warehouse_id+aisle_no`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `aisle_id` | str | Y |  | `^WH-\d{3}-A\d{3}$` | Y |  |  | Aisle ID = <warehouse_id>-Annn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Parent warehouse |
| `zone_id` | str | Y |  |  |  | zone.zone_id |  | Zone the aisle belongs to |
| `aisle_no` | int | Y |  |  |  |  | >= 1 | Sequential aisle number from the dock |
| `x_m` | float | Y | m |  |  |  |  | Aisle centre-line distance from depot |
| `length_m` | float | Y | m |  |  |  |  | Aisle length |
| `bay_count` | int | Y |  |  |  |  | >= 1 | Bays per side |
| `status` | str | Y |  | ACTIVE, BLOCKED |  |  |  | Current state (history in state_event / aisle_block) |

## location

*master* - Storage/pick location (one slot face).

Primary key: `location_id` · Natural keys: `aisle_id+side+bay+level`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `location_id` | str | Y |  | `^LOC-WH-\d{3}-Z\d{2}-\d{6}$` | Y |  |  | LOC-<zone-id>-nnnnnn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `zone_id` | str | Y |  |  |  | zone.zone_id | location_id embeds zone_id | Zone |
| `aisle_id` | str | Y |  |  |  | aisle.aisle_id |  | Aisle |
| `side` | str | Y |  | L, R |  |  |  | Aisle side |
| `bay` | int | Y |  |  |  |  | >= 1 | Bay number from front of aisle |
| `level` | int | Y |  |  |  |  | >= 1 | Rack level (1 = floor) |
| `bay_key` | str | Y |  |  |  |  |  (derived) | <aisle_id>-<side>-Bnn; co-location unit for compatibility |
| `x_m` | float | Y | m |  |  |  |  (derived) | X coordinate (= aisle.x_m) |
| `y_m` | float | Y | m |  |  |  |  | Depth into aisle from front cross-aisle |
| `width_cm` | float | Y | cm |  |  |  | > 0 | Usable width |
| `depth_cm` | float | Y | cm |  |  |  | > 0 | Usable depth |
| `height_cm` | float | Y | cm |  |  |  | > 0 | Usable height |
| `volume_l` | float | Y | L |  |  |  |  (derived) | Derived = width*depth*height/1000 |
| `max_weight_kg` | float | Y | kg |  |  |  | > 0 | Rated load |
| `location_type` | str | Y |  | FLOW_RACK, SHELF, COLD_SHELF, FREEZER_SHELF, HAZMAT_CABINET, PALLET_RACK |  |  |  | Rack/equipment type |
| `is_golden_zone` | bool | Y |  |  |  |  |  (derived) | Derived: ergonomic level for its location_type |
| `status` | str | Y |  | ACTIVE, INACTIVE |  |  |  | ACTIVE locations are slottable |
| `effective_from` | date | Y |  |  |  |  |  | Date location became available |

## supplier

*master* - Supplier of SKUs (actor: supplier).

Primary key: `supplier_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `supplier_id` | str | Y |  | `^SUP-\d{4}$` | Y |  |  | SUP-nnnn |
| `supplier_name` | str | Y |  |  |  |  |  | Synthetic supplier name |
| `country_code` | str | Y |  | US, CA, MX, DE, GB, CN, IN, VN |  |  |  | ISO-3166 alpha-2 |
| `lead_time_days` | int | Y | days |  |  |  | 1..60 | Replenishment lead time |
| `status` | str | Y |  | ACTIVE |  |  |  | Lifecycle state |

## sku

*master* - Item master with physical and compatibility attributes.

Primary key: `sku_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `sku_id` | str | Y |  | `^SKU-\d{6}$` | Y |  |  | SKU-nnnnnn |
| `sku_name` | str | Y |  |  |  |  |  | Synthetic description |
| `supplier_id` | str | Y |  |  |  | supplier.supplier_id |  | Supplier |
| `category` | str | Y |  | GROCERY_DRY, HOUSEHOLD, ELECTRONICS, APPAREL, HEALTH_BEAUTY, TOYS, FURNITURE, APPLIANCES, GARDEN, DAIRY, FRESH_PRODUCE, FROZEN_FOOD, CHEMICALS, AEROSOLS, BATTERIES |  |  |  | Merchandise category |
| `length_cm` | float | Y | cm |  |  |  | length >= width > 0 | Longest unit dimension |
| `width_cm` | float | Y | cm |  |  |  | > 0 | Unit width |
| `height_cm` | float | Y | cm |  |  |  | > 0 | Unit height |
| `unit_volume_l` | float | Y | L |  |  |  |  (derived) | Derived = L*W*H/1000 |
| `unit_weight_kg` | float | Y | kg |  |  |  | > 0 | Unit gross weight |
| `temp_class` | str | Y |  | AMBIENT, CHILLED, FROZEN |  |  |  | Required temperature regime |
| `hazard_class` | str | Y |  | NONE, 2.1, 3, 5.1, 8, 9 |  |  |  | UN hazard class or NONE |
| `compat_group` | str | Y |  | FOOD, GENERAL, HAZMAT |  |  |  | Compatibility group (HAZMAT iff hazard_class != NONE) |
| `is_oversized` | bool | Y |  |  |  |  |  (derived) | Derived: max dim > 60 cm or volume > 60 L |
| `required_storage_class` | str | Y |  |  |  | storage_class.storage_class_code |  (derived) | Derived: HAZMAT > FROZEN > CHILLED > OVERSIZE > AMBIENT |
| `max_order_qty` | int | Y | units |  |  |  | >= 1 | Largest quantity allowed on one order line; a slot must hold at least this |
| `created_date` | date | Y |  |  |  |  |  | Item creation date |
| `status` | str | Y |  | ACTIVE |  |  |  | Lifecycle state |

## warehouse_sku

*bridge* - N:M bridge - which warehouses stock which SKUs.

Primary key: `warehouse_id, sku_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `stocking_role` | str | Y |  | PRIMARY, SECONDARY |  |  |  | PRIMARY = main stocking point |
| `effective_from` | date | Y |  |  |  |  |  | Stocking start date |

## compatibility_rule

*reference* - Pairs of compatibility keys that must not share a bay.

Primary key: `rule_id` · Natural keys: `key_a+key_b`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `rule_id` | str | Y |  | `^CMP-\d{3}$` | Y |  |  | CMP-nnn |
| `key_a` | str | Y |  |  |  |  |  | Compatibility key (hazard class or compat group) |
| `key_b` | str | Y |  |  |  |  | key_a < key_b (stored once) | Compatibility key |
| `relation` | str | Y |  | INCOMPATIBLE |  |  |  | Relation |
| `scope` | str | Y |  | SAME_BAY |  |  |  | Physical scope of the restriction |
| `description` | str | Y |  |  |  |  |  | Reason |

## sku_profile

*derived* - Versioned velocity profile per warehouse-SKU, derived from order lines.

Primary key: `profile_id` · Natural keys: `warehouse_id+sku_id+version`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `profile_id` | str | Y |  | `^SKP-WH-\d{3}-SKU-\d{6}-V\d+$` | Y |  |  | SKP-<warehouse_id>-<sku_id>-Vn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `version` | int | Y |  |  |  |  | >= 1 | Profile version |
| `window_start` | date | Y |  |  |  |  |  | Observation window start |
| `window_end` | date | Y |  |  |  |  | >= window_start | Observation window end (inclusive) |
| `window_days` | int | Y | days |  |  |  |  (derived) | Derived = window_end - window_start + 1 |
| `effective_from` | date | Y |  |  |  |  | > window_end | Profile in force from |
| `effective_to` | date | N |  |  |  |  | > effective_from | Exclusive end; null = open |
| `order_lines` | int | Y |  |  |  |  |  (derived) | Derived: picked order lines in window |
| `units_total` | int | Y | units |  |  |  |  (derived) | Derived: units picked in window |
| `active_days` | int | Y | days |  |  |  |  (derived) | Derived: days with >= 1 line |
| `lines_per_day` | float | Y | lines/day |  |  |  |  (derived) | Derived pick frequency |
| `units_per_day` | float | Y | units/day |  |  |  |  (derived) | Derived |
| `cube_l_per_day` | float | Y | L/day |  |  |  |  (derived) | Derived = units_per_day * unit_volume_l |
| `forecast_lines_per_day` | float | Y | lines/day |  |  |  |  (derived) | Derived: (lines + 14*prior_rate*lift)/(days + 14); = lines_per_day when no prior |
| `forecast_units_per_day` | float | Y | units/day |  |  |  |  (derived) | Derived, same blend on units |
| `velocity_rank` | int | Y |  |  |  |  |  (derived) | Derived rank within warehouse+version (1 = fastest) |
| `velocity_class` | str | Y |  | A, B, C, D |  |  |  (derived) | Derived ABC(D) by cumulative share of lines |
| `prior_profile_id` | str | N |  |  |  | sku_profile.profile_id |  | Previous version |
| `velocity_shift_ratio` | float | N |  |  |  |  |  (derived) | Derived = lines_per_day / prior lines_per_day |
| `demand_trend` | str | Y |  | BASELINE, STABLE, PEAK_UP, DOWN, NEW, INACTIVE |  |  |  (derived) | Derived from velocity_shift_ratio |

## slot_assignment

*transaction* - Time-bounded SKU->location assignment (N:M SKU-Location bridge with history).

Primary key: `slot_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `slot_id` | str | Y |  | `^SLOT-2026-\d{6}$` | Y |  |  | SLOT-2026-nnnnnn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `location_id` | str | Y |  |  |  | location.location_id |  | Location |
| `plan_code` | str | Y |  | LEGACY_2026H2, OPT_PEAK_2026W42, PLANNER_OVERRIDE |  |  |  | Slotting plan that produced the row |
| `assignment_source` | str | Y |  | LEGACY_IMPORT, OPTIMIZER, PLANNER_OVERRIDE |  |  |  | Origin of the row |
| `profile_id` | str | N |  |  |  | sku_profile.profile_id |  | Velocity profile used (optimizer only) |
| `previous_slot_id` | str | N |  |  |  | slot_assignment.slot_id |  | Slot this row replaces |
| `requested_by` | str | N |  | `^PLN-\d{2}$` |  |  |  | Planner ID for overrides |
| `created_ts` | datetime | Y |  |  |  |  |  | Record creation time |
| `effective_from` | date | Y |  |  |  |  |  | Assignment start |
| `effective_to` | date | N |  |  |  |  | > effective_from | Exclusive end; null = open |
| `status` | str | Y |  | PROPOSED, APPROVED, ACTIVE, SUPERSEDED, REJECTED |  |  |  | Current lifecycle state (history in state_event) |
| `units_capacity` | int | N | units |  |  |  |  (derived) | Derived units the slot holds (min of cube, weight fit) |
| `reorder_point_units` | int | N | units |  |  |  |  (derived) | Derived = floor(capacity * 0.30) |
| `candidate_rank` | int | N |  |  |  |  |  (derived) | Rank of chosen candidate (optimizer) |
| `pick_cost_s_per_day` | float | N | s/day |  |  |  |  (derived) | Optimizer pick-travel cost |
| `replen_cost_s_per_day` | float | N | s/day |  |  |  |  (derived) | Optimizer replenishment cost |
| `decision_ts` | datetime | N |  |  |  |  |  | When the engine decided a proposal |
| `decision_reason` | str | N |  |  |  |  |  | Engine decision / reason codes |

## slot_candidate

*derived* - Top-3 candidate slots evaluated per SKU for the optimized plan.

Primary key: `candidate_id` · Natural keys: `plan_code+warehouse_id+sku_id+candidate_rank`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `candidate_id` | str | Y |  | `^CAND-2026-\d{7}$` | Y |  |  | CAND-2026-nnnnnnn |
| `plan_code` | str | Y |  | LEGACY_2026H2, OPT_PEAK_2026W42, PLANNER_OVERRIDE |  |  |  | Plan |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `profile_id` | str | Y |  |  |  | sku_profile.profile_id |  | Profile used |
| `location_id` | str | Y |  |  |  | location.location_id |  | Candidate location |
| `candidate_rank` | int | Y |  |  |  |  | 1..3 | 1 = lowest total cost |
| `units_capacity` | int | Y | units |  |  |  |  | Units the location would hold |
| `pick_cost_s_per_day` | float | Y | s/day |  |  |  |  | Pick travel cost |
| `replen_cost_s_per_day` | float | Y | s/day |  |  |  |  | Replenishment cost |
| `total_cost_s_per_day` | float | Y | s/day |  |  |  |  (derived) | Derived = pick + replen |
| `selected` | bool | Y |  |  |  |  |  | True for the chosen candidate |
| `slot_id` | str | N |  |  |  | slot_assignment.slot_id |  | Resulting slot when selected |

## aisle_block

*event* - Aisle closure window (maintenance, spill...).

Primary key: `block_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `block_id` | str | Y |  | `^ABLK-2026-\d{4}$` | Y |  |  | ABLK-2026-nnnn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `aisle_id` | str | Y |  |  |  | aisle.aisle_id |  | Blocked aisle |
| `block_type` | str | Y |  | MAINTENANCE, RACK_INSPECTION, SPILL, CLEANING |  |  |  | Cause |
| `start_ts` | datetime | Y |  |  |  |  |  | Block start (inclusive) |
| `end_ts` | datetime | Y |  |  |  |  | > start_ts | Block end (exclusive) |
| `reported_ts` | datetime | Y |  |  |  |  |  | When the block was entered in the WMS |

## orders

*transaction* - Customer/store order (table named orders; ORDER is reserved in SQL).

Primary key: `order_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `order_id` | str | Y |  | `^ORD-2026-\d{6}$` | Y |  |  | ORD-2026-nnnnnn (chronological) |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Fulfilling warehouse |
| `channel` | str | Y |  | ECOM, RETAIL, B2B |  |  |  | Sales channel |
| `priority` | str | Y |  | STANDARD, EXPRESS |  |  |  | Service level |
| `carrier_service` | str | Y |  | PARCEL_GROUND, PARCEL_EXPRESS, STORE_FLEET, LTL_FREIGHT |  |  |  | Outbound carrier service (actor: carrier) |
| `order_ts` | datetime | Y |  |  |  |  |  | Order received |
| `required_ship_ts` | datetime | Y |  |  |  |  | > order_ts | Promised ship time |
| `release_ts` | datetime | N |  |  |  |  | >= order_ts | Released to picking |
| `hold_block_id` | str | N |  |  |  | aisle_block.block_id |  | Aisle block that forced a hold |
| `hold_release_ts` | datetime | N |  |  |  |  | = block end_ts | Re-release after hold |
| `picked_ts` | datetime | N |  |  |  |  | >= last pick_ts | Picker back at depot |
| `shipped_ts` | datetime | N |  |  |  |  | >= picked_ts | Handed to carrier |
| `cancelled_ts` | datetime | N |  |  |  |  |  | Cancellation time |
| `status` | str | Y |  | CREATED, RELEASED, ON_HOLD, PICKED, SHIPPED, CANCELLED |  |  |  | Current lifecycle state |
| `line_count` | int | Y |  |  |  |  |  (derived) | Derived = COUNT(order_line) |
| `total_units` | int | Y | units |  |  |  |  (derived) | Derived = SUM(order_line.qty_ordered) |
| `pick_distance_m` | float | N | m |  |  |  |  (derived) | Derived = SUM(pick travel) + return_to_depot_m |
| `return_to_depot_m` | float | N | m |  |  |  |  (derived) | Derived last leg back to depot |

## order_line

*transaction* - Order line. 1 order : N lines.

Primary key: `order_line_id` · Natural keys: `order_id+line_no`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `order_line_id` | str | Y |  | `^ORD-2026-\d{6}-L\d{3}$` | Y |  |  | <order_id>-Lnnn |
| `order_id` | str | Y |  |  |  | orders.order_id |  | Parent order |
| `line_no` | int | Y |  |  |  |  | >= 1 | Line number within order |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU (must be stocked at the order's warehouse) |
| `qty_ordered` | int | Y | units |  |  |  | 1..sku.max_order_qty | Ordered units |
| `qty_picked` | int | Y | units |  |  |  |  (derived) | Derived = SUM(pick_event.qty) |
| `status` | str | Y |  | PICKED, CANCELLED |  |  |  | Current state |

## pick_event

*event* - One pick confirmation inside an order tour.

Primary key: `pick_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `pick_id` | str | Y |  | `^PICK-ORD-2026-\d{6}-\d{3}$` | Y |  |  | PICK-<order-id>-nnn (tour sequence) |
| `order_id` | str | Y |  |  |  | orders.order_id |  | Order |
| `order_line_id` | str | Y |  |  | Y | order_line.order_line_id |  | Order line |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `slot_id` | str | Y |  |  |  | slot_assignment.slot_id |  | Slot assignment in force at pick time |
| `location_id` | str | Y |  |  |  | location.location_id |  | Pick location |
| `aisle_id` | str | Y |  |  |  | aisle.aisle_id |  | Aisle walked |
| `pick_seq` | int | Y |  |  |  |  | >= 1 | Sequence in tour (return routing policy) |
| `pick_ts` | datetime | Y |  |  |  |  |  | Pick confirmation time |
| `qty` | int | Y | units |  |  |  | >= 1 | Units picked |
| `travel_from_prev_m` | float | Y | m |  |  |  |  | Walk from previous stop (depot for seq 1) |
| `handling_s` | float | Y | s |  |  |  |  | Pick handling time |
| `status` | str | Y |  | COMPLETED |  |  |  | State |

## replenishment

*event* - Reserve-to-pick-face replenishment task.

Primary key: `replen_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `replen_id` | str | Y |  | `^REPL-2026-\d{6}$` | Y |  |  | REPL-2026-nnnnnn |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `sku_id` | str | Y |  |  |  | sku.sku_id |  | SKU |
| `slot_id` | str | Y |  |  |  | slot_assignment.slot_id |  | Slot replenished |
| `location_id` | str | Y |  |  |  | location.location_id |  | Pick face |
| `replen_type` | str | Y |  | SCHEDULED, EMERGENCY |  |  |  | SCHEDULED end-of-day or EMERGENCY before a pick |
| `trigger_reason` | str | Y |  | BELOW_REORDER_POINT, INSUFFICIENT_FOR_PICK |  |  |  | Rule that fired |
| `created_ts` | datetime | Y |  |  |  |  |  | Task created |
| `completed_ts` | datetime | Y |  |  |  |  | >= created_ts | Task completed |
| `units` | int | Y | units |  |  |  | >= 1 | Units moved = onhand_after - onhand_before |
| `onhand_before` | int | Y | units |  |  |  | >= 0 | Pick-face units before |
| `onhand_after` | int | Y | units |  |  |  |  | Pick-face units after (= slot capacity) |
| `task_minutes` | float | Y | min |  |  |  |  | Labor minutes (travel + handling) |
| `labor_status` | str | Y |  | WITHIN_CAPACITY, OVER_CAPACITY |  |  |  (derived) | Derived: within or beyond daily labor capacity |
| `status` | str | Y |  | COMPLETED |  |  |  | State |

## labor_capacity

*master* - Planned replenishment labor per warehouse-day.

Primary key: `labor_capacity_id` · Natural keys: `warehouse_id+work_date`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `labor_capacity_id` | str | Y |  | `^LAB-WH-\d{3}-\d{8}$` | Y |  |  | LAB-<warehouse_id>-YYYYMMDD |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `work_date` | date | Y |  |  |  |  |  | Work date |
| `replen_capacity_min` | float | Y | min |  |  |  | >= 0 | Available replenishment labor |
| `capacity_reason` | str | Y |  | STANDARD_PLAN, ABSENTEEISM |  |  |  | Basis of the figure |

## replen_labor_daily

*derived* - Replenishment workload vs capacity per warehouse-day.

Primary key: `labor_day_id` · Natural keys: `warehouse_id+work_date`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `labor_day_id` | str | Y |  | `^RLD-WH-\d{3}-\d{8}$` | Y |  |  | RLD-<warehouse_id>-YYYYMMDD |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `work_date` | date | Y |  |  |  |  |  | Work date |
| `labor_capacity_id` | str | Y |  |  |  | labor_capacity.labor_capacity_id |  | Capacity record |
| `task_count` | int | Y |  |  |  |  |  (derived) | Derived = COUNT(replenishment) |
| `emergency_count` | int | Y |  |  |  |  |  (derived) | Derived = COUNT(EMERGENCY) |
| `workload_min` | float | Y | min |  |  |  |  (derived) | Derived = SUM(task_minutes) |
| `capacity_min` | float | Y | min |  |  |  |  | = labor_capacity.replen_capacity_min |
| `utilization_pct` | float | Y | % |  |  |  |  (derived) | Derived = workload / capacity * 100 |
| `over_capacity_min` | float | Y | min |  |  |  |  (derived) | Derived = max(0, workload - capacity) |
| `status` | str | Y |  | WITHIN_CAPACITY, EXCEEDED |  |  |  (derived) | EXCEEDED iff workload > capacity |

## state_event

*event* - Append-only status history for orders, slots, replenishments and aisles.

Primary key: `event_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `event_id` | str | Y |  | `^EVT-2026-\d{7}$` | Y |  |  | EVT-2026-nnnnnnn (chronological) |
| `entity_type` | str | Y |  | ORDER, SLOT_ASSIGNMENT, REPLENISHMENT, AISLE |  |  |  | Entity whose state changed |
| `entity_id` | str | Y |  |  |  |  |  | Polymorphic FK into the entity table |
| `from_status` | str | N |  |  |  |  |  | Previous state; null on creation |
| `to_status` | str | Y |  |  |  |  | (from,to) in lifecycle | New state |
| `event_ts` | datetime | Y |  |  |  |  |  | When the transition happened |
| `actor` | str | Y |  | WMS, OPTIMIZER, PLANNER, SLOTTING_ENGINE, MAINTENANCE, LEGACY_MIGRATION |  |  |  | Who/what caused it |
| `reason` | str | N |  |  |  |  |  | Reference (block, decision code...) |

## slotting_exception

*derived* - Exceptions raised by the slotting engine (decision log).

Primary key: `exception_id`

| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `exception_id` | str | Y |  | `^EXC-2026-\d{6}$` | Y |  |  | EXC-2026-nnnnnn |
| `exception_type` | str | Y |  | LOCATION_CAPACITY_EXCEEDED, STORAGE_CLASS_MISMATCH, INCOMPATIBLE_CO_LOCATION, DUPLICATE_ACTIVE_LOCATION, PICK_PATH_BLOCKED_AISLE, REPLEN_LABOR_EXCEEDED, ORDER_DEFERRED_BLOCKED_AISLE, NO_FEASIBLE_SLOT |  |  |  | Rule category |
| `severity` | str | Y |  | INFO, WARNING, CRITICAL |  |  |  | Severity |
| `entity_type` | str | Y |  | SLOT_ASSIGNMENT, PICK_EVENT, REPLEN_LABOR_DAY, ORDER, SKU |  |  |  | Kind of flagged entity |
| `entity_id` | str | Y |  |  |  |  |  | Flagged record ID |
| `warehouse_id` | str | Y |  |  |  | warehouse.warehouse_id |  | Warehouse |
| `rule_id` | str | Y |  | `^R-\d{2}$` |  |  |  | Rule reference (see docs/business_rules.md) |
| `detected_ts` | datetime | Y |  |  |  |  |  | Detection time |
| `action` | str | Y |  | REJECT_PROPOSAL, ESCALATE_SAFETY_AUDIT, SCHEDULE_OVERTIME_OR_DEFER, DEFER_ORDER, MANUAL_REVIEW |  |  |  | Recommended / taken action |
| `details` | str | Y |  |  |  |  |  | Evidence (measured vs limit) |
