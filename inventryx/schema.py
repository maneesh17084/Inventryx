"""Single source of truth for every exported table.

The data dictionary (docs), SQL DDL, CSV column order and most validation checks
are all generated from these definitions.
"""
from dataclasses import dataclass

# --- Enumerations ---------------------------------------------------------
REGIONS = ("NORTH", "SOUTH", "EAST", "WEST", "CENTRAL")
ZONE_TYPES = ("FORWARD_PICK", "SHELF", "CHILLED", "FROZEN", "HAZMAT", "BULK")
TEMP_CLASSES = ("AMBIENT", "CHILLED", "FROZEN")
STORAGE_CLASSES = ("AMBIENT", "CHILLED", "FROZEN", "HAZMAT", "OVERSIZE")
LOCATION_TYPES = ("FLOW_RACK", "SHELF", "COLD_SHELF", "FREEZER_SHELF", "HAZMAT_CABINET", "PALLET_RACK")
LOCATION_STATUSES = ("ACTIVE", "INACTIVE")
AISLE_STATUSES = ("ACTIVE", "BLOCKED")
HAZARD_CLASSES = ("NONE", "2.1", "3", "5.1", "8", "9")
COMPAT_GROUPS = ("FOOD", "GENERAL", "HAZMAT")
CATEGORIES = ("GROCERY_DRY", "HOUSEHOLD", "ELECTRONICS", "APPAREL", "HEALTH_BEAUTY", "TOYS",
              "FURNITURE", "APPLIANCES", "GARDEN", "DAIRY", "FRESH_PRODUCE", "FROZEN_FOOD",
              "CHEMICALS", "AEROSOLS", "BATTERIES")
COUNTRIES = ("US", "CA", "MX", "DE", "GB", "CN", "IN", "VN")
STOCKING_ROLES = ("PRIMARY", "SECONDARY")
CHANNELS = ("ECOM", "RETAIL", "B2B")
PRIORITIES = ("STANDARD", "EXPRESS")
CARRIER_SERVICES = ("PARCEL_GROUND", "PARCEL_EXPRESS", "STORE_FLEET", "LTL_FREIGHT")
ORDER_STATUSES = ("CREATED", "RELEASED", "ON_HOLD", "PICKED", "SHIPPED", "CANCELLED")
LINE_STATUSES = ("PICKED", "CANCELLED")
VELOCITY_CLASSES = ("A", "B", "C", "D")
DEMAND_TRENDS = ("BASELINE", "STABLE", "PEAK_UP", "DOWN", "NEW", "INACTIVE")
SLOT_STATUSES = ("PROPOSED", "APPROVED", "ACTIVE", "SUPERSEDED", "REJECTED")
PLAN_CODES = ("LEGACY_2026H2", "OPT_PEAK_2026W42", "PLANNER_OVERRIDE")
ASSIGNMENT_SOURCES = ("LEGACY_IMPORT", "OPTIMIZER", "PLANNER_OVERRIDE")
REPLEN_TYPES = ("SCHEDULED", "EMERGENCY")
TRIGGER_REASONS = ("BELOW_REORDER_POINT", "INSUFFICIENT_FOR_PICK")
LABOR_STATUSES = ("WITHIN_CAPACITY", "OVER_CAPACITY")
LABOR_DAY_STATUSES = ("WITHIN_CAPACITY", "EXCEEDED")
BLOCK_TYPES = ("MAINTENANCE", "RACK_INSPECTION", "SPILL", "CLEANING")
CAPACITY_REASONS = ("STANDARD_PLAN", "ABSENTEEISM")
EVENT_ENTITY_TYPES = ("ORDER", "SLOT_ASSIGNMENT", "REPLENISHMENT", "AISLE")
ACTORS = ("WMS", "OPTIMIZER", "PLANNER", "SLOTTING_ENGINE", "MAINTENANCE", "LEGACY_MIGRATION")
EXCEPTION_TYPES = ("LOCATION_CAPACITY_EXCEEDED", "STORAGE_CLASS_MISMATCH", "INCOMPATIBLE_CO_LOCATION",
                   "DUPLICATE_ACTIVE_LOCATION", "PICK_PATH_BLOCKED_AISLE", "REPLEN_LABOR_EXCEEDED",
                   "ORDER_DEFERRED_BLOCKED_AISLE", "NO_FEASIBLE_SLOT")
EXCEPTION_ENTITY_TYPES = ("SLOT_ASSIGNMENT", "PICK_EVENT", "REPLEN_LABOR_DAY", "ORDER", "SKU")
SEVERITIES = ("INFO", "WARNING", "CRITICAL")
ACTIONS = ("REJECT_PROPOSAL", "ESCALATE_SAFETY_AUDIT", "SCHEDULE_OVERTIME_OR_DEFER", "DEFER_ORDER", "MANUAL_REVIEW")

# Lifecycle transitions allowed in state_event (from_status None = creation).
LIFECYCLES = {
    "ORDER": {(None, "CREATED"), ("CREATED", "RELEASED"), ("CREATED", "CANCELLED"), ("RELEASED", "ON_HOLD"),
              ("ON_HOLD", "RELEASED"), ("RELEASED", "PICKED"), ("PICKED", "SHIPPED")},
    "SLOT_ASSIGNMENT": {(None, "ACTIVE"), (None, "PROPOSED"), ("PROPOSED", "ACTIVE"), ("PROPOSED", "APPROVED"),
                        ("PROPOSED", "REJECTED"), ("APPROVED", "ACTIVE"), ("ACTIVE", "SUPERSEDED")},
    "REPLENISHMENT": {(None, "CREATED"), ("CREATED", "COMPLETED")},
    "AISLE": {("ACTIVE", "BLOCKED"), ("BLOCKED", "ACTIVE")},
}


@dataclass(frozen=True)
class Field:
    name: str
    type: str                      # str | int | float | bool | date | datetime
    required: bool = True
    desc: str = ""
    unit: str = ""
    enum: tuple | None = None
    unique: bool = False
    pattern: str | None = None
    fk: str | None = None          # "table.column"
    dec: int | None = None         # decimals for float formatting
    rule: str = ""
    derived: bool = False


@dataclass(frozen=True)
class Table:
    name: str
    kind: str                      # reference | master | bridge | transaction | event | derived
    desc: str
    pk: tuple
    fields: tuple
    natural_keys: tuple = ()

    @property
    def columns(self):
        return [f.name for f in self.fields]

    def field(self, name):
        return next(f for f in self.fields if f.name == name)


def F(name, type_, required=True, desc="", **kw):
    return Field(name, type_, required, desc, **kw)


P_WH = r"^WH-\d{3}$"
P_ZONE = r"^WH-\d{3}-Z\d{2}$"
P_AISLE = r"^WH-\d{3}-A\d{3}$"
P_LOC = r"^LOC-WH-\d{3}-Z\d{2}-\d{6}$"
P_SKU = r"^SKU-\d{6}$"
P_ORD = r"^ORD-2026-\d{6}$"
P_SLOT = r"^SLOT-2026-\d{6}$"
P_PROFILE = r"^SKP-WH-\d{3}-SKU-\d{6}-V\d+$"
P_BLOCK = r"^ABLK-2026-\d{4}$"

TABLES = [
    Table("storage_class", "reference", "Storage/handling classes a SKU can require and a zone can provide.",
          ("storage_class_code",), (
              F("storage_class_code", "str", desc="Storage class code", enum=STORAGE_CLASSES, unique=True),
              F("description", "str", desc="Human-readable description"),
              F("temp_min_c", "float", desc="Minimum storage temperature", unit="degC", dec=1),
              F("temp_max_c", "float", desc="Maximum storage temperature", unit="degC", dec=1,
                rule="temp_min_c < temp_max_c"),
          )),
    Table("warehouse", "master", "Distribution centre. Root of the physical hierarchy.", ("warehouse_id",), (
        F("warehouse_id", "str", desc="Warehouse ID", unique=True, pattern=P_WH),
        F("warehouse_name", "str", desc="Synthetic site name", unique=True),
        F("region", "str", desc="Operating region", enum=REGIONS),
        F("operator_code", "str", desc="Warehouse operator (3PL/own) code", pattern=r"^OPR-\d{2}$"),
        F("opened_date", "date", desc="Site opening date", rule="< 2026-07-01"),
        F("status", "str", desc="Lifecycle state", enum=("ACTIVE",)),
        F("aisle_pitch_m", "float", desc="Centre-to-centre aisle spacing", unit="m", dec=2),
        F("location_count", "int", desc="Number of locations (derived = COUNT(location))", derived=True),
        F("zone_count", "int", desc="Number of zones (derived = COUNT(zone))", derived=True),
        F("aisle_count", "int", desc="Number of aisles (derived = COUNT(aisle))", derived=True),
    )),
    Table("zone", "master", "Temperature/handling zone inside a warehouse. 1 warehouse : N zones.", ("zone_id",), (
        F("zone_id", "str", desc="Zone ID = <warehouse_id>-Znn", unique=True, pattern=P_ZONE),
        F("warehouse_id", "str", desc="Parent warehouse", fk="warehouse.warehouse_id"),
        F("zone_code", "str", desc="Zone code within warehouse", pattern=r"^Z\d{2}$"),
        F("zone_type", "str", desc="Functional zone type", enum=ZONE_TYPES),
        F("temp_class", "str", desc="Zone temperature regime", enum=TEMP_CLASSES),
        F("travel_rank", "int", desc="1 = closest to the dock/depot", rule=">= 1"),
        F("aisle_count", "int", desc="Derived = COUNT(aisle)", derived=True),
        F("location_count", "int", desc="Derived = COUNT(location)", derived=True),
        F("status", "str", desc="Lifecycle state", enum=("ACTIVE",)),
    ), natural_keys=(("warehouse_id", "zone_code"),)),
    Table("zone_storage_class", "bridge", "N:M bridge - which storage classes each zone may hold.",
          ("zone_id", "storage_class_code"), (
              F("zone_id", "str", desc="Zone", fk="zone.zone_id", pattern=P_ZONE),
              F("storage_class_code", "str", desc="Allowed storage class", fk="storage_class.storage_class_code",
                enum=STORAGE_CLASSES),
          )),
    Table("aisle", "master", "Pick aisle. Picker enters/exits from the front cross-aisle (y = 0).", ("aisle_id",), (
        F("aisle_id", "str", desc="Aisle ID = <warehouse_id>-Annn", unique=True, pattern=P_AISLE),
        F("warehouse_id", "str", desc="Parent warehouse", fk="warehouse.warehouse_id"),
        F("zone_id", "str", desc="Zone the aisle belongs to", fk="zone.zone_id"),
        F("aisle_no", "int", desc="Sequential aisle number from the dock", rule=">= 1"),
        F("x_m", "float", desc="Aisle centre-line distance from depot", unit="m", dec=2),
        F("length_m", "float", desc="Aisle length", unit="m", dec=2),
        F("bay_count", "int", desc="Bays per side", rule=">= 1"),
        F("status", "str", desc="Current state (history in state_event / aisle_block)", enum=AISLE_STATUSES),
    ), natural_keys=(("warehouse_id", "aisle_no"),)),
    Table("location", "master", "Storage/pick location (one slot face).", ("location_id",), (
        F("location_id", "str", desc="LOC-<zone-id>-nnnnnn", unique=True, pattern=P_LOC),
        F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
        F("zone_id", "str", desc="Zone", fk="zone.zone_id", rule="location_id embeds zone_id"),
        F("aisle_id", "str", desc="Aisle", fk="aisle.aisle_id"),
        F("side", "str", desc="Aisle side", enum=("L", "R")),
        F("bay", "int", desc="Bay number from front of aisle", rule=">= 1"),
        F("level", "int", desc="Rack level (1 = floor)", rule=">= 1"),
        F("bay_key", "str", desc="<aisle_id>-<side>-Bnn; co-location unit for compatibility", derived=True),
        F("x_m", "float", desc="X coordinate (= aisle.x_m)", unit="m", dec=2, derived=True),
        F("y_m", "float", desc="Depth into aisle from front cross-aisle", unit="m", dec=2),
        F("width_cm", "float", desc="Usable width", unit="cm", dec=1, rule="> 0"),
        F("depth_cm", "float", desc="Usable depth", unit="cm", dec=1, rule="> 0"),
        F("height_cm", "float", desc="Usable height", unit="cm", dec=1, rule="> 0"),
        F("volume_l", "float", desc="Derived = width*depth*height/1000", unit="L", dec=3, derived=True),
        F("max_weight_kg", "float", desc="Rated load", unit="kg", dec=1, rule="> 0"),
        F("location_type", "str", desc="Rack/equipment type", enum=LOCATION_TYPES),
        F("is_golden_zone", "bool", desc="Derived: ergonomic level for its location_type", derived=True),
        F("status", "str", desc="ACTIVE locations are slottable", enum=LOCATION_STATUSES),
        F("effective_from", "date", desc="Date location became available"),
    ), natural_keys=(("aisle_id", "side", "bay", "level"),)),
    Table("supplier", "master", "Supplier of SKUs (actor: supplier).", ("supplier_id",), (
        F("supplier_id", "str", desc="SUP-nnnn", unique=True, pattern=r"^SUP-\d{4}$"),
        F("supplier_name", "str", desc="Synthetic supplier name"),
        F("country_code", "str", desc="ISO-3166 alpha-2", enum=COUNTRIES),
        F("lead_time_days", "int", desc="Replenishment lead time", unit="days", rule="1..60"),
        F("status", "str", desc="Lifecycle state", enum=("ACTIVE",)),
    )),
    Table("sku", "master", "Item master with physical and compatibility attributes.", ("sku_id",), (
        F("sku_id", "str", desc="SKU-nnnnnn", unique=True, pattern=P_SKU),
        F("sku_name", "str", desc="Synthetic description"),
        F("supplier_id", "str", desc="Supplier", fk="supplier.supplier_id"),
        F("category", "str", desc="Merchandise category", enum=CATEGORIES),
        F("length_cm", "float", desc="Longest unit dimension", unit="cm", dec=1, rule="length >= width > 0"),
        F("width_cm", "float", desc="Unit width", unit="cm", dec=1, rule="> 0"),
        F("height_cm", "float", desc="Unit height", unit="cm", dec=1, rule="> 0"),
        F("unit_volume_l", "float", desc="Derived = L*W*H/1000", unit="L", dec=3, derived=True),
        F("unit_weight_kg", "float", desc="Unit gross weight", unit="kg", dec=3, rule="> 0"),
        F("temp_class", "str", desc="Required temperature regime", enum=TEMP_CLASSES),
        F("hazard_class", "str", desc="UN hazard class or NONE", enum=HAZARD_CLASSES),
        F("compat_group", "str", desc="Compatibility group (HAZMAT iff hazard_class != NONE)", enum=COMPAT_GROUPS),
        F("is_oversized", "bool", desc="Derived: max dim > 60 cm or volume > 60 L", derived=True),
        F("required_storage_class", "str", desc="Derived: HAZMAT > FROZEN > CHILLED > OVERSIZE > AMBIENT",
          fk="storage_class.storage_class_code", derived=True),
        F("max_order_qty", "int", desc="Largest quantity allowed on one order line; a slot must hold at least this",
          unit="units", rule=">= 1"),
        F("created_date", "date", desc="Item creation date"),
        F("status", "str", desc="Lifecycle state", enum=("ACTIVE",)),
    )),
    Table("warehouse_sku", "bridge", "N:M bridge - which warehouses stock which SKUs.",
          ("warehouse_id", "sku_id"), (
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
              F("stocking_role", "str", desc="PRIMARY = main stocking point", enum=STOCKING_ROLES),
              F("effective_from", "date", desc="Stocking start date"),
          )),
    Table("compatibility_rule", "reference", "Pairs of compatibility keys that must not share a bay.",
          ("rule_id",), (
              F("rule_id", "str", desc="CMP-nnn", unique=True, pattern=r"^CMP-\d{3}$"),
              F("key_a", "str", desc="Compatibility key (hazard class or compat group)"),
              F("key_b", "str", desc="Compatibility key", rule="key_a < key_b (stored once)"),
              F("relation", "str", desc="Relation", enum=("INCOMPATIBLE",)),
              F("scope", "str", desc="Physical scope of the restriction", enum=("SAME_BAY",)),
              F("description", "str", desc="Reason"),
          ), natural_keys=(("key_a", "key_b"),)),
    Table("sku_profile", "derived", "Versioned velocity profile per warehouse-SKU, derived from order lines.",
          ("profile_id",), (
              F("profile_id", "str", desc="SKP-<warehouse_id>-<sku_id>-Vn", unique=True, pattern=P_PROFILE),
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
              F("version", "int", desc="Profile version", rule=">= 1"),
              F("window_start", "date", desc="Observation window start"),
              F("window_end", "date", desc="Observation window end (inclusive)", rule=">= window_start"),
              F("window_days", "int", desc="Derived = window_end - window_start + 1", unit="days", derived=True),
              F("effective_from", "date", desc="Profile in force from", rule="> window_end"),
              F("effective_to", "date", False, desc="Exclusive end; null = open", rule="> effective_from"),
              F("order_lines", "int", desc="Derived: picked order lines in window", derived=True),
              F("units_total", "int", desc="Derived: units picked in window", unit="units", derived=True),
              F("active_days", "int", desc="Derived: days with >= 1 line", unit="days", derived=True),
              F("lines_per_day", "float", desc="Derived pick frequency", unit="lines/day", dec=4, derived=True),
              F("units_per_day", "float", desc="Derived", unit="units/day", dec=4, derived=True),
              F("cube_l_per_day", "float", desc="Derived = units_per_day * unit_volume_l", unit="L/day", dec=4,
                derived=True),
              F("forecast_lines_per_day", "float",
                desc="Derived: (lines + 14*prior_rate*lift)/(days + 14); = lines_per_day when no prior",
                unit="lines/day", dec=4, derived=True),
              F("forecast_units_per_day", "float", desc="Derived, same blend on units", unit="units/day", dec=4,
                derived=True),
              F("velocity_rank", "int", desc="Derived rank within warehouse+version (1 = fastest)", derived=True),
              F("velocity_class", "str", desc="Derived ABC(D) by cumulative share of lines", enum=VELOCITY_CLASSES,
                derived=True),
              F("prior_profile_id", "str", False, desc="Previous version", fk="sku_profile.profile_id"),
              F("velocity_shift_ratio", "float", False, desc="Derived = lines_per_day / prior lines_per_day",
                dec=4, derived=True),
              F("demand_trend", "str", desc="Derived from velocity_shift_ratio", enum=DEMAND_TRENDS, derived=True),
          ), natural_keys=(("warehouse_id", "sku_id", "version"),)),
    Table("slot_assignment", "transaction",
          "Time-bounded SKU->location assignment (N:M SKU-Location bridge with history).", ("slot_id",), (
              F("slot_id", "str", desc="SLOT-2026-nnnnnn", unique=True, pattern=P_SLOT),
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
              F("location_id", "str", desc="Location", fk="location.location_id"),
              F("plan_code", "str", desc="Slotting plan that produced the row", enum=PLAN_CODES),
              F("assignment_source", "str", desc="Origin of the row", enum=ASSIGNMENT_SOURCES),
              F("profile_id", "str", False, desc="Velocity profile used (optimizer only)", fk="sku_profile.profile_id"),
              F("previous_slot_id", "str", False, desc="Slot this row replaces", fk="slot_assignment.slot_id"),
              F("requested_by", "str", False, desc="Planner ID for overrides", pattern=r"^PLN-\d{2}$"),
              F("created_ts", "datetime", desc="Record creation time"),
              F("effective_from", "date", desc="Assignment start"),
              F("effective_to", "date", False, desc="Exclusive end; null = open", rule="> effective_from"),
              F("status", "str", desc="Current lifecycle state (history in state_event)", enum=SLOT_STATUSES),
              F("units_capacity", "int", False, desc="Derived units the slot holds (min of cube, weight fit)",
                unit="units", derived=True),
              F("reorder_point_units", "int", False, desc="Derived = floor(capacity * 0.30)", unit="units",
                derived=True),
              F("candidate_rank", "int", False, desc="Rank of chosen candidate (optimizer)", derived=True),
              F("pick_cost_s_per_day", "float", False, desc="Optimizer pick-travel cost", unit="s/day", dec=3,
                derived=True),
              F("replen_cost_s_per_day", "float", False, desc="Optimizer replenishment cost", unit="s/day", dec=3,
                derived=True),
              F("decision_ts", "datetime", False, desc="When the engine decided a proposal"),
              F("decision_reason", "str", False, desc="Engine decision / reason codes"),
          )),
    Table("slot_candidate", "derived", "Top-3 candidate slots evaluated per SKU for the optimized plan.",
          ("candidate_id",), (
              F("candidate_id", "str", desc="CAND-2026-nnnnnnn", unique=True, pattern=r"^CAND-2026-\d{7}$"),
              F("plan_code", "str", desc="Plan", enum=PLAN_CODES),
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
              F("profile_id", "str", desc="Profile used", fk="sku_profile.profile_id"),
              F("location_id", "str", desc="Candidate location", fk="location.location_id"),
              F("candidate_rank", "int", desc="1 = lowest total cost", rule="1..3"),
              F("units_capacity", "int", desc="Units the location would hold", unit="units"),
              F("pick_cost_s_per_day", "float", desc="Pick travel cost", unit="s/day", dec=3),
              F("replen_cost_s_per_day", "float", desc="Replenishment cost", unit="s/day", dec=3),
              F("total_cost_s_per_day", "float", desc="Derived = pick + replen", unit="s/day", dec=3, derived=True),
              F("selected", "bool", desc="True for the chosen candidate"),
              F("slot_id", "str", False, desc="Resulting slot when selected", fk="slot_assignment.slot_id"),
          ), natural_keys=(("plan_code", "warehouse_id", "sku_id", "candidate_rank"),)),
    Table("aisle_block", "event", "Aisle closure window (maintenance, spill...).", ("block_id",), (
        F("block_id", "str", desc="ABLK-2026-nnnn", unique=True, pattern=P_BLOCK),
        F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
        F("aisle_id", "str", desc="Blocked aisle", fk="aisle.aisle_id"),
        F("block_type", "str", desc="Cause", enum=BLOCK_TYPES),
        F("start_ts", "datetime", desc="Block start (inclusive)"),
        F("end_ts", "datetime", desc="Block end (exclusive)", rule="> start_ts"),
        F("reported_ts", "datetime", desc="When the block was entered in the WMS"),
    )),
    Table("orders", "transaction", "Customer/store order (table named orders; ORDER is reserved in SQL).",
          ("order_id",), (
              F("order_id", "str", desc="ORD-2026-nnnnnn (chronological)", unique=True, pattern=P_ORD),
              F("warehouse_id", "str", desc="Fulfilling warehouse", fk="warehouse.warehouse_id"),
              F("channel", "str", desc="Sales channel", enum=CHANNELS),
              F("priority", "str", desc="Service level", enum=PRIORITIES),
              F("carrier_service", "str", desc="Outbound carrier service (actor: carrier)", enum=CARRIER_SERVICES),
              F("order_ts", "datetime", desc="Order received"),
              F("required_ship_ts", "datetime", desc="Promised ship time", rule="> order_ts"),
              F("release_ts", "datetime", False, desc="Released to picking", rule=">= order_ts"),
              F("hold_block_id", "str", False, desc="Aisle block that forced a hold", fk="aisle_block.block_id"),
              F("hold_release_ts", "datetime", False, desc="Re-release after hold", rule="= block end_ts"),
              F("picked_ts", "datetime", False, desc="Picker back at depot", rule=">= last pick_ts"),
              F("shipped_ts", "datetime", False, desc="Handed to carrier", rule=">= picked_ts"),
              F("cancelled_ts", "datetime", False, desc="Cancellation time"),
              F("status", "str", desc="Current lifecycle state", enum=ORDER_STATUSES),
              F("line_count", "int", desc="Derived = COUNT(order_line)", derived=True),
              F("total_units", "int", desc="Derived = SUM(order_line.qty_ordered)", unit="units", derived=True),
              F("pick_distance_m", "float", False, desc="Derived = SUM(pick travel) + return_to_depot_m", unit="m",
                dec=2, derived=True),
              F("return_to_depot_m", "float", False, desc="Derived last leg back to depot", unit="m", dec=2,
                derived=True),
          )),
    Table("order_line", "transaction", "Order line. 1 order : N lines.", ("order_line_id",), (
        F("order_line_id", "str", desc="<order_id>-Lnnn", unique=True, pattern=r"^ORD-2026-\d{6}-L\d{3}$"),
        F("order_id", "str", desc="Parent order", fk="orders.order_id"),
        F("line_no", "int", desc="Line number within order", rule=">= 1"),
        F("sku_id", "str", desc="SKU (must be stocked at the order's warehouse)", fk="sku.sku_id"),
        F("qty_ordered", "int", desc="Ordered units", unit="units", rule="1..sku.max_order_qty"),
        F("qty_picked", "int", desc="Derived = SUM(pick_event.qty)", unit="units", derived=True),
        F("status", "str", desc="Current state", enum=LINE_STATUSES),
    ), natural_keys=(("order_id", "line_no"),)),
    Table("pick_event", "event", "One pick confirmation inside an order tour.", ("pick_id",), (
        F("pick_id", "str", desc="PICK-<order-id>-nnn (tour sequence)", unique=True,
          pattern=r"^PICK-ORD-2026-\d{6}-\d{3}$"),
        F("order_id", "str", desc="Order", fk="orders.order_id"),
        F("order_line_id", "str", desc="Order line", fk="order_line.order_line_id", unique=True),
        F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
        F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
        F("slot_id", "str", desc="Slot assignment in force at pick time", fk="slot_assignment.slot_id"),
        F("location_id", "str", desc="Pick location", fk="location.location_id"),
        F("aisle_id", "str", desc="Aisle walked", fk="aisle.aisle_id"),
        F("pick_seq", "int", desc="Sequence in tour (return routing policy)", rule=">= 1"),
        F("pick_ts", "datetime", desc="Pick confirmation time"),
        F("qty", "int", desc="Units picked", unit="units", rule=">= 1"),
        F("travel_from_prev_m", "float", desc="Walk from previous stop (depot for seq 1)", unit="m", dec=2),
        F("handling_s", "float", desc="Pick handling time", unit="s", dec=1),
        F("status", "str", desc="State", enum=("COMPLETED",)),
    )),
    Table("replenishment", "event", "Reserve-to-pick-face replenishment task.", ("replen_id",), (
        F("replen_id", "str", desc="REPL-2026-nnnnnn", unique=True, pattern=r"^REPL-2026-\d{6}$"),
        F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
        F("sku_id", "str", desc="SKU", fk="sku.sku_id"),
        F("slot_id", "str", desc="Slot replenished", fk="slot_assignment.slot_id"),
        F("location_id", "str", desc="Pick face", fk="location.location_id"),
        F("replen_type", "str", desc="SCHEDULED end-of-day or EMERGENCY before a pick", enum=REPLEN_TYPES),
        F("trigger_reason", "str", desc="Rule that fired", enum=TRIGGER_REASONS),
        F("created_ts", "datetime", desc="Task created"),
        F("completed_ts", "datetime", desc="Task completed", rule=">= created_ts"),
        F("units", "int", desc="Units moved = onhand_after - onhand_before", unit="units", rule=">= 1"),
        F("onhand_before", "int", desc="Pick-face units before", unit="units", rule=">= 0"),
        F("onhand_after", "int", desc="Pick-face units after (= slot capacity)", unit="units"),
        F("task_minutes", "float", desc="Labor minutes (travel + handling)", unit="min", dec=2),
        F("labor_status", "str", desc="Derived: within or beyond daily labor capacity", enum=LABOR_STATUSES,
          derived=True),
        F("status", "str", desc="State", enum=("COMPLETED",)),
    )),
    Table("labor_capacity", "master", "Planned replenishment labor per warehouse-day.", ("labor_capacity_id",), (
        F("labor_capacity_id", "str", desc="LAB-<warehouse_id>-YYYYMMDD", unique=True,
          pattern=r"^LAB-WH-\d{3}-\d{8}$"),
        F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
        F("work_date", "date", desc="Work date"),
        F("replen_capacity_min", "float", desc="Available replenishment labor", unit="min", dec=2, rule=">= 0"),
        F("capacity_reason", "str", desc="Basis of the figure", enum=CAPACITY_REASONS),
    ), natural_keys=(("warehouse_id", "work_date"),)),
    Table("replen_labor_daily", "derived", "Replenishment workload vs capacity per warehouse-day.",
          ("labor_day_id",), (
              F("labor_day_id", "str", desc="RLD-<warehouse_id>-YYYYMMDD", unique=True,
                pattern=r"^RLD-WH-\d{3}-\d{8}$"),
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("work_date", "date", desc="Work date"),
              F("labor_capacity_id", "str", desc="Capacity record", fk="labor_capacity.labor_capacity_id"),
              F("task_count", "int", desc="Derived = COUNT(replenishment)", derived=True),
              F("emergency_count", "int", desc="Derived = COUNT(EMERGENCY)", derived=True),
              F("workload_min", "float", desc="Derived = SUM(task_minutes)", unit="min", dec=2, derived=True),
              F("capacity_min", "float", desc="= labor_capacity.replen_capacity_min", unit="min", dec=2),
              F("utilization_pct", "float", desc="Derived = workload / capacity * 100", unit="%", dec=2,
                derived=True),
              F("over_capacity_min", "float", desc="Derived = max(0, workload - capacity)", unit="min", dec=2,
                derived=True),
              F("status", "str", desc="EXCEEDED iff workload > capacity", enum=LABOR_DAY_STATUSES, derived=True),
          ), natural_keys=(("warehouse_id", "work_date"),)),
    Table("state_event", "event", "Append-only status history for orders, slots, replenishments and aisles.",
          ("event_id",), (
              F("event_id", "str", desc="EVT-2026-nnnnnnn (chronological)", unique=True,
                pattern=r"^EVT-2026-\d{7}$"),
              F("entity_type", "str", desc="Entity whose state changed", enum=EVENT_ENTITY_TYPES),
              F("entity_id", "str", desc="Polymorphic FK into the entity table"),
              F("from_status", "str", False, desc="Previous state; null on creation"),
              F("to_status", "str", desc="New state", rule="(from,to) in lifecycle"),
              F("event_ts", "datetime", desc="When the transition happened"),
              F("actor", "str", desc="Who/what caused it", enum=ACTORS),
              F("reason", "str", False, desc="Reference (block, decision code...)"),
          )),
    Table("slotting_exception", "derived", "Exceptions raised by the slotting engine (decision log).",
          ("exception_id",), (
              F("exception_id", "str", desc="EXC-2026-nnnnnn", unique=True, pattern=r"^EXC-2026-\d{6}$"),
              F("exception_type", "str", desc="Rule category", enum=EXCEPTION_TYPES),
              F("severity", "str", desc="Severity", enum=SEVERITIES),
              F("entity_type", "str", desc="Kind of flagged entity", enum=EXCEPTION_ENTITY_TYPES),
              F("entity_id", "str", desc="Flagged record ID"),
              F("warehouse_id", "str", desc="Warehouse", fk="warehouse.warehouse_id"),
              F("rule_id", "str", desc="Rule reference (see docs/business_rules.md)", pattern=r"^R-\d{2}$"),
              F("detected_ts", "datetime", desc="Detection time"),
              F("action", "str", desc="Recommended / taken action", enum=ACTIONS),
              F("details", "str", desc="Evidence (measured vs limit)"),
          )),
]

TABLE_BY_NAME = {t.name: t for t in TABLES}
TABLE_ORDER = [t.name for t in TABLES]

# Cardinality documentation (parent, child, fk column, cardinality, optional?)
RELATIONSHIPS = [
    ("warehouse", "zone", "warehouse_id", "1:N", False),
    ("zone", "aisle", "zone_id", "1:N", False),
    ("aisle", "location", "aisle_id", "1:N", False),
    ("zone", "location", "zone_id", "1:N", False),
    ("zone", "zone_storage_class", "zone_id", "1:N (zone N:M storage_class)", False),
    ("storage_class", "zone_storage_class", "storage_class_code", "1:N (zone N:M storage_class)", False),
    ("supplier", "sku", "supplier_id", "1:N", False),
    ("storage_class", "sku", "required_storage_class", "1:N", False),
    ("warehouse", "warehouse_sku", "warehouse_id", "1:N (warehouse N:M sku)", False),
    ("sku", "warehouse_sku", "sku_id", "1:N (warehouse N:M sku)", False),
    ("warehouse_sku", "sku_profile", "warehouse_id+sku_id", "1:N (one per version)", False),
    ("sku_profile", "sku_profile", "prior_profile_id", "1:0..1 (version chain)", True),
    ("sku", "slot_assignment", "sku_id", "1:N (sku N:M location over time)", False),
    ("location", "slot_assignment", "location_id", "1:N (<=1 ACTIVE at a time)", False),
    ("sku_profile", "slot_assignment", "profile_id", "1:0..N", True),
    ("slot_assignment", "slot_assignment", "previous_slot_id", "1:0..N (supersession chain)", True),
    ("slot_assignment", "slot_candidate", "slot_id", "1:0..1 (selected candidate)", True),
    ("warehouse", "orders", "warehouse_id", "1:N", False),
    ("orders", "order_line", "order_id", "1:N (1..20 lines)", False),
    ("order_line", "pick_event", "order_line_id", "1:0..1 (cancelled lines have none)", True),
    ("slot_assignment", "pick_event", "slot_id", "1:N", False),
    ("aisle", "aisle_block", "aisle_id", "1:0..N", True),
    ("aisle_block", "orders", "hold_block_id", "1:0..N", True),
    ("slot_assignment", "replenishment", "slot_id", "1:0..N", True),
    ("warehouse", "labor_capacity", "warehouse_id", "1:N (one per day)", False),
    ("labor_capacity", "replen_labor_daily", "labor_capacity_id", "1:1", False),
]
