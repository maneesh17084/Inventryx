-- Generated from inventryx/schema.py. Compatible with SQLite 3.23+ and PostgreSQL 12+.

-- Storage/handling classes a SKU can require and a zone can provide.
CREATE TABLE storage_class (
    storage_class_code TEXT NOT NULL CHECK (storage_class_code IN ('AMBIENT', 'CHILLED', 'FROZEN', 'HAZMAT', 'OVERSIZE')),
    description TEXT NOT NULL,
    temp_min_c NUMERIC NOT NULL,
    temp_max_c NUMERIC NOT NULL,
    PRIMARY KEY (storage_class_code)
);

-- Distribution centre. Root of the physical hierarchy.
CREATE TABLE warehouse (
    warehouse_id TEXT NOT NULL,
    warehouse_name TEXT NOT NULL,
    region TEXT NOT NULL CHECK (region IN ('NORTH', 'SOUTH', 'EAST', 'WEST', 'CENTRAL')),
    operator_code TEXT NOT NULL,
    opened_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE')),
    aisle_pitch_m NUMERIC NOT NULL,
    location_count INTEGER NOT NULL,
    zone_count INTEGER NOT NULL,
    aisle_count INTEGER NOT NULL,
    PRIMARY KEY (warehouse_id)
);

-- Temperature/handling zone inside a warehouse. 1 warehouse : N zones.
CREATE TABLE zone (
    zone_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    zone_code TEXT NOT NULL,
    zone_type TEXT NOT NULL CHECK (zone_type IN ('FORWARD_PICK', 'SHELF', 'CHILLED', 'FROZEN', 'HAZMAT', 'BULK')),
    temp_class TEXT NOT NULL CHECK (temp_class IN ('AMBIENT', 'CHILLED', 'FROZEN')),
    travel_rank INTEGER NOT NULL,
    aisle_count INTEGER NOT NULL,
    location_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE')),
    PRIMARY KEY (zone_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    UNIQUE (warehouse_id, zone_code)
);

-- N:M bridge - which storage classes each zone may hold.
CREATE TABLE zone_storage_class (
    zone_id TEXT NOT NULL,
    storage_class_code TEXT NOT NULL CHECK (storage_class_code IN ('AMBIENT', 'CHILLED', 'FROZEN', 'HAZMAT', 'OVERSIZE')),
    PRIMARY KEY (zone_id, storage_class_code),
    FOREIGN KEY (zone_id) REFERENCES zone (zone_id),
    FOREIGN KEY (storage_class_code) REFERENCES storage_class (storage_class_code)
);

-- Pick aisle. Picker enters/exits from the front cross-aisle (y = 0).
CREATE TABLE aisle (
    aisle_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    aisle_no INTEGER NOT NULL,
    x_m NUMERIC NOT NULL,
    length_m NUMERIC NOT NULL,
    bay_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'BLOCKED')),
    PRIMARY KEY (aisle_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (zone_id) REFERENCES zone (zone_id),
    UNIQUE (warehouse_id, aisle_no)
);

-- Storage/pick location (one slot face).
CREATE TABLE location (
    location_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    aisle_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('L', 'R')),
    bay INTEGER NOT NULL,
    level INTEGER NOT NULL,
    bay_key TEXT NOT NULL,
    x_m NUMERIC NOT NULL,
    y_m NUMERIC NOT NULL,
    width_cm NUMERIC NOT NULL,
    depth_cm NUMERIC NOT NULL,
    height_cm NUMERIC NOT NULL,
    volume_l NUMERIC NOT NULL,
    max_weight_kg NUMERIC NOT NULL,
    location_type TEXT NOT NULL CHECK (location_type IN ('FLOW_RACK', 'SHELF', 'COLD_SHELF', 'FREEZER_SHELF', 'HAZMAT_CABINET', 'PALLET_RACK')),
    is_golden_zone BOOLEAN NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    effective_from DATE NOT NULL,
    PRIMARY KEY (location_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (zone_id) REFERENCES zone (zone_id),
    FOREIGN KEY (aisle_id) REFERENCES aisle (aisle_id),
    UNIQUE (aisle_id, side, bay, level)
);

-- Supplier of SKUs (actor: supplier).
CREATE TABLE supplier (
    supplier_id TEXT NOT NULL,
    supplier_name TEXT NOT NULL,
    country_code TEXT NOT NULL CHECK (country_code IN ('US', 'CA', 'MX', 'DE', 'GB', 'CN', 'IN', 'VN')),
    lead_time_days INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE')),
    PRIMARY KEY (supplier_id)
);

-- Item master with physical and compatibility attributes.
CREATE TABLE sku (
    sku_id TEXT NOT NULL,
    sku_name TEXT NOT NULL,
    supplier_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('GROCERY_DRY', 'HOUSEHOLD', 'ELECTRONICS', 'APPAREL', 'HEALTH_BEAUTY', 'TOYS', 'FURNITURE', 'APPLIANCES', 'GARDEN', 'DAIRY', 'FRESH_PRODUCE', 'FROZEN_FOOD', 'CHEMICALS', 'AEROSOLS', 'BATTERIES')),
    length_cm NUMERIC NOT NULL,
    width_cm NUMERIC NOT NULL,
    height_cm NUMERIC NOT NULL,
    unit_volume_l NUMERIC NOT NULL,
    unit_weight_kg NUMERIC NOT NULL,
    temp_class TEXT NOT NULL CHECK (temp_class IN ('AMBIENT', 'CHILLED', 'FROZEN')),
    hazard_class TEXT NOT NULL CHECK (hazard_class IN ('NONE', '2.1', '3', '5.1', '8', '9')),
    compat_group TEXT NOT NULL CHECK (compat_group IN ('FOOD', 'GENERAL', 'HAZMAT')),
    is_oversized BOOLEAN NOT NULL,
    required_storage_class TEXT NOT NULL,
    max_order_qty INTEGER NOT NULL,
    created_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE')),
    PRIMARY KEY (sku_id),
    FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
    FOREIGN KEY (required_storage_class) REFERENCES storage_class (storage_class_code)
);

-- N:M bridge - which warehouses stock which SKUs.
CREATE TABLE warehouse_sku (
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    stocking_role TEXT NOT NULL CHECK (stocking_role IN ('PRIMARY', 'SECONDARY')),
    effective_from DATE NOT NULL,
    PRIMARY KEY (warehouse_id, sku_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id)
);

-- Pairs of compatibility keys that must not share a bay.
CREATE TABLE compatibility_rule (
    rule_id TEXT NOT NULL,
    key_a TEXT NOT NULL,
    key_b TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('INCOMPATIBLE')),
    scope TEXT NOT NULL CHECK (scope IN ('SAME_BAY')),
    description TEXT NOT NULL,
    PRIMARY KEY (rule_id),
    UNIQUE (key_a, key_b)
);

-- Versioned velocity profile per warehouse-SKU, derived from order lines.
CREATE TABLE sku_profile (
    profile_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    window_days INTEGER NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    order_lines INTEGER NOT NULL,
    units_total INTEGER NOT NULL,
    active_days INTEGER NOT NULL,
    lines_per_day NUMERIC NOT NULL,
    units_per_day NUMERIC NOT NULL,
    cube_l_per_day NUMERIC NOT NULL,
    forecast_lines_per_day NUMERIC NOT NULL,
    forecast_units_per_day NUMERIC NOT NULL,
    velocity_rank INTEGER NOT NULL,
    velocity_class TEXT NOT NULL CHECK (velocity_class IN ('A', 'B', 'C', 'D')),
    prior_profile_id TEXT,
    velocity_shift_ratio NUMERIC,
    demand_trend TEXT NOT NULL CHECK (demand_trend IN ('BASELINE', 'STABLE', 'PEAK_UP', 'DOWN', 'NEW', 'INACTIVE')),
    PRIMARY KEY (profile_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    FOREIGN KEY (prior_profile_id) REFERENCES sku_profile (profile_id),
    UNIQUE (warehouse_id, sku_id, version)
);

-- Time-bounded SKU->location assignment (N:M SKU-Location bridge with history).
CREATE TABLE slot_assignment (
    slot_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    plan_code TEXT NOT NULL CHECK (plan_code IN ('LEGACY_2026H2', 'OPT_PEAK_2026W42', 'PLANNER_OVERRIDE')),
    assignment_source TEXT NOT NULL CHECK (assignment_source IN ('LEGACY_IMPORT', 'OPTIMIZER', 'PLANNER_OVERRIDE')),
    profile_id TEXT,
    previous_slot_id TEXT,
    requested_by TEXT,
    created_ts TIMESTAMP NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    status TEXT NOT NULL CHECK (status IN ('PROPOSED', 'APPROVED', 'ACTIVE', 'SUPERSEDED', 'REJECTED')),
    units_capacity INTEGER,
    reorder_point_units INTEGER,
    candidate_rank INTEGER,
    pick_cost_s_per_day NUMERIC,
    replen_cost_s_per_day NUMERIC,
    decision_ts TIMESTAMP,
    decision_reason TEXT,
    PRIMARY KEY (slot_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    FOREIGN KEY (location_id) REFERENCES location (location_id),
    FOREIGN KEY (profile_id) REFERENCES sku_profile (profile_id),
    FOREIGN KEY (previous_slot_id) REFERENCES slot_assignment (slot_id)
);

-- Top-3 candidate slots evaluated per SKU for the optimized plan.
CREATE TABLE slot_candidate (
    candidate_id TEXT NOT NULL,
    plan_code TEXT NOT NULL CHECK (plan_code IN ('LEGACY_2026H2', 'OPT_PEAK_2026W42', 'PLANNER_OVERRIDE')),
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    candidate_rank INTEGER NOT NULL,
    units_capacity INTEGER NOT NULL,
    pick_cost_s_per_day NUMERIC NOT NULL,
    replen_cost_s_per_day NUMERIC NOT NULL,
    total_cost_s_per_day NUMERIC NOT NULL,
    selected BOOLEAN NOT NULL,
    slot_id TEXT,
    PRIMARY KEY (candidate_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    FOREIGN KEY (profile_id) REFERENCES sku_profile (profile_id),
    FOREIGN KEY (location_id) REFERENCES location (location_id),
    FOREIGN KEY (slot_id) REFERENCES slot_assignment (slot_id),
    UNIQUE (plan_code, warehouse_id, sku_id, candidate_rank)
);

-- Aisle closure window (maintenance, spill...).
CREATE TABLE aisle_block (
    block_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    aisle_id TEXT NOT NULL,
    block_type TEXT NOT NULL CHECK (block_type IN ('MAINTENANCE', 'RACK_INSPECTION', 'SPILL', 'CLEANING')),
    start_ts TIMESTAMP NOT NULL,
    end_ts TIMESTAMP NOT NULL,
    reported_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (block_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (aisle_id) REFERENCES aisle (aisle_id)
);

-- Customer/store order (table named orders; ORDER is reserved in SQL).
CREATE TABLE orders (
    order_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('ECOM', 'RETAIL', 'B2B')),
    priority TEXT NOT NULL CHECK (priority IN ('STANDARD', 'EXPRESS')),
    carrier_service TEXT NOT NULL CHECK (carrier_service IN ('PARCEL_GROUND', 'PARCEL_EXPRESS', 'STORE_FLEET', 'LTL_FREIGHT')),
    order_ts TIMESTAMP NOT NULL,
    required_ship_ts TIMESTAMP NOT NULL,
    release_ts TIMESTAMP,
    hold_block_id TEXT,
    hold_release_ts TIMESTAMP,
    picked_ts TIMESTAMP,
    shipped_ts TIMESTAMP,
    cancelled_ts TIMESTAMP,
    status TEXT NOT NULL CHECK (status IN ('CREATED', 'RELEASED', 'ON_HOLD', 'PICKED', 'SHIPPED', 'CANCELLED')),
    line_count INTEGER NOT NULL,
    total_units INTEGER NOT NULL,
    pick_distance_m NUMERIC,
    return_to_depot_m NUMERIC,
    PRIMARY KEY (order_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (hold_block_id) REFERENCES aisle_block (block_id)
);

-- Order line. 1 order : N lines.
CREATE TABLE order_line (
    order_line_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    sku_id TEXT NOT NULL,
    qty_ordered INTEGER NOT NULL,
    qty_picked INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PICKED', 'CANCELLED')),
    PRIMARY KEY (order_line_id),
    FOREIGN KEY (order_id) REFERENCES orders (order_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    UNIQUE (order_id, line_no)
);

-- One pick confirmation inside an order tour.
CREATE TABLE pick_event (
    pick_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    order_line_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    aisle_id TEXT NOT NULL,
    pick_seq INTEGER NOT NULL,
    pick_ts TIMESTAMP NOT NULL,
    qty INTEGER NOT NULL,
    travel_from_prev_m NUMERIC NOT NULL,
    handling_s NUMERIC NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED')),
    PRIMARY KEY (pick_id),
    FOREIGN KEY (order_id) REFERENCES orders (order_id),
    FOREIGN KEY (order_line_id) REFERENCES order_line (order_line_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    FOREIGN KEY (slot_id) REFERENCES slot_assignment (slot_id),
    FOREIGN KEY (location_id) REFERENCES location (location_id),
    FOREIGN KEY (aisle_id) REFERENCES aisle (aisle_id)
);

-- Reserve-to-pick-face replenishment task.
CREATE TABLE replenishment (
    replen_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    replen_type TEXT NOT NULL CHECK (replen_type IN ('SCHEDULED', 'EMERGENCY')),
    trigger_reason TEXT NOT NULL CHECK (trigger_reason IN ('BELOW_REORDER_POINT', 'INSUFFICIENT_FOR_PICK')),
    created_ts TIMESTAMP NOT NULL,
    completed_ts TIMESTAMP NOT NULL,
    units INTEGER NOT NULL,
    onhand_before INTEGER NOT NULL,
    onhand_after INTEGER NOT NULL,
    task_minutes NUMERIC NOT NULL,
    labor_status TEXT NOT NULL CHECK (labor_status IN ('WITHIN_CAPACITY', 'OVER_CAPACITY')),
    status TEXT NOT NULL CHECK (status IN ('COMPLETED')),
    PRIMARY KEY (replen_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
    FOREIGN KEY (slot_id) REFERENCES slot_assignment (slot_id),
    FOREIGN KEY (location_id) REFERENCES location (location_id)
);

-- Planned replenishment labor per warehouse-day.
CREATE TABLE labor_capacity (
    labor_capacity_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    work_date DATE NOT NULL,
    replen_capacity_min NUMERIC NOT NULL,
    capacity_reason TEXT NOT NULL CHECK (capacity_reason IN ('STANDARD_PLAN', 'ABSENTEEISM')),
    PRIMARY KEY (labor_capacity_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    UNIQUE (warehouse_id, work_date)
);

-- Replenishment workload vs capacity per warehouse-day.
CREATE TABLE replen_labor_daily (
    labor_day_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    work_date DATE NOT NULL,
    labor_capacity_id TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    emergency_count INTEGER NOT NULL,
    workload_min NUMERIC NOT NULL,
    capacity_min NUMERIC NOT NULL,
    utilization_pct NUMERIC NOT NULL,
    over_capacity_min NUMERIC NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('WITHIN_CAPACITY', 'EXCEEDED')),
    PRIMARY KEY (labor_day_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
    FOREIGN KEY (labor_capacity_id) REFERENCES labor_capacity (labor_capacity_id),
    UNIQUE (warehouse_id, work_date)
);

-- Append-only status history for orders, slots, replenishments and aisles.
CREATE TABLE state_event (
    event_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('ORDER', 'SLOT_ASSIGNMENT', 'REPLENISHMENT', 'AISLE')),
    entity_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    event_ts TIMESTAMP NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('WMS', 'OPTIMIZER', 'PLANNER', 'SLOTTING_ENGINE', 'MAINTENANCE', 'LEGACY_MIGRATION')),
    reason TEXT,
    PRIMARY KEY (event_id)
);

-- Exceptions raised by the slotting engine (decision log).
CREATE TABLE slotting_exception (
    exception_id TEXT NOT NULL,
    exception_type TEXT NOT NULL CHECK (exception_type IN ('LOCATION_CAPACITY_EXCEEDED', 'STORAGE_CLASS_MISMATCH', 'INCOMPATIBLE_CO_LOCATION', 'DUPLICATE_ACTIVE_LOCATION', 'PICK_PATH_BLOCKED_AISLE', 'REPLEN_LABOR_EXCEEDED', 'ORDER_DEFERRED_BLOCKED_AISLE', 'NO_FEASIBLE_SLOT')),
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('SLOT_ASSIGNMENT', 'PICK_EVENT', 'REPLEN_LABOR_DAY', 'ORDER', 'SKU')),
    entity_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    detected_ts TIMESTAMP NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('REJECT_PROPOSAL', 'ESCALATE_SAFETY_AUDIT', 'SCHEDULE_OVERTIME_OR_DEFER', 'DEFER_ORDER', 'MANUAL_REVIEW')),
    details TEXT NOT NULL,
    PRIMARY KEY (exception_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id)
);
