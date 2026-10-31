"""Business rules shared by the optimizer, the decision engine and the validator.

Rule IDs (R-xx) are referenced in slotting_exception.rule_id and docs/business_rules.md.
"""
import math

from . import config as C

RULE_IDS = {
    "LOCATION_CAPACITY_EXCEEDED": "R-01",
    "STORAGE_CLASS_MISMATCH": "R-02",
    "INCOMPATIBLE_CO_LOCATION": "R-03",
    "DUPLICATE_ACTIVE_LOCATION": "R-04",
    "PICK_PATH_BLOCKED_AISLE": "R-05",
    "REPLEN_LABOR_EXCEEDED": "R-06",
    "ORDER_DEFERRED_BLOCKED_AISLE": "R-07",
    "NO_FEASIBLE_SLOT": "R-08",
}

# Segregation pairs: (key_a, key_b, reason). Keys are hazard classes or compat groups.
COMPATIBILITY_RULES = [
    ("2.1", "5.1", "Flammable gas must be segregated from oxidizers"),
    ("3", "5.1", "Flammable liquid must be segregated from oxidizers"),
    ("5.1", "8", "Oxidizers must be segregated from corrosives"),
    ("2.1", "8", "Flammable gas must be segregated from corrosives"),
    ("2.1", "FOOD", "Food must not share a bay with flammable gas"),
    ("3", "FOOD", "Food must not share a bay with flammable liquids"),
    ("5.1", "FOOD", "Food must not share a bay with oxidizers"),
    ("8", "FOOD", "Food must not share a bay with corrosives"),
    ("9", "FOOD", "Food must not share a bay with misc. dangerous goods"),
]


def incompatible_pairs(rule_rows=None) -> set:
    rows = rule_rows if rule_rows is not None else [
        {"key_a": a, "key_b": b} for a, b, _ in COMPATIBILITY_RULES]
    return {frozenset((r["key_a"], r["key_b"])) for r in rows}


def compat_key(sku: dict) -> str:
    return sku["hazard_class"] if sku["hazard_class"] != "NONE" else sku["compat_group"]


def is_oversized(length, width, height) -> bool:
    return max(length, width, height) > 60.0 or length * width * height / 1000.0 > 60.0


def required_storage_class(hazard_class, temp_class, oversized) -> str:
    if hazard_class != "NONE":
        return "HAZMAT"
    if temp_class in ("FROZEN", "CHILLED"):
        return temp_class
    return "OVERSIZE" if oversized else "AMBIENT"


def fit_units(sku: dict, loc: dict) -> tuple[int, int, int]:
    """Units a location holds: min(cube fit with rotation, weight fit). Returns (units, dim_units, weight_units)."""
    s = sorted((sku["length_cm"], sku["width_cm"], sku["height_cm"]), reverse=True)
    lo = sorted((loc["width_cm"], loc["depth_cm"], loc["height_cm"]), reverse=True)
    dim = 1
    for a, b in zip(s, lo):
        dim *= math.floor(b / a + 1e-9)
    wt = math.floor(loc["max_weight_kg"] / sku["unit_weight_kg"] + 1e-9)
    return min(dim, wt), dim, wt


def capacity_issue(sku: dict, loc: dict) -> tuple[str | None, int]:
    """R-01: a unit must physically fit, not exceed the rated load, and the slot must hold max_order_qty."""
    units, dim, wt = fit_units(sku, loc)
    if dim == 0:
        return "DIMENSION", units
    if wt == 0:
        return "WEIGHT", units
    if units < sku["max_order_qty"]:
        return "UNIT_CAPACITY", units
    return None, units


def reorder_point(capacity: int) -> int:
    return math.floor(capacity * C.ROP_FRACTION)


def travel_seconds(loc: dict) -> float:
    """Expected per-line travel cost of a location under return routing (x shared across lines, y walked twice)."""
    penalty = 0.0 if loc["is_golden_zone"] else C.NON_GOLDEN_PENALTY_S
    return (loc["x_m"] + 2.0 * loc["y_m"]) / C.PICKER_SPEED_MPS + penalty


def replen_minutes(loc: dict, units: int) -> float:
    lift = C.LIFT_PENALTY_MIN if loc["level"] >= C.LIFT_LEVEL else 0.0
    travel = 2.0 * (loc["x_m"] + loc["y_m"]) / C.REPLEN_SPEED_MPS / 60.0
    return round(C.REPLEN_BASE_MIN + travel + C.REPLEN_PER_UNIT_MIN * units + lift, 2)


def handling_seconds(loc: dict, qty: int) -> float:
    penalty = 0.0 if loc["is_golden_zone"] else C.NON_GOLDEN_PENALTY_S
    return round(C.PICK_BASE_S + penalty + C.PER_EXTRA_UNIT_S * (qty - 1), 1)


def route(stops: list[dict]) -> tuple[list[tuple[dict, float]], float]:
    """Return-policy routing from a depot at (0, 0) on the front cross-aisle.

    Aisles are visited in ascending x; inside an aisle the picker walks to each stop in
    ascending depth and leaves the way they came in. Returns [(stop, leg_m)] and the final leg.
    """
    ordered = sorted(stops, key=lambda s: (s["aisle_no"], s["y_m"], s["key"]))
    legs = []
    cur_aisle, cur_x, cur_y = None, 0.0, 0.0
    for s in ordered:
        if s["aisle_no"] != cur_aisle:
            leg = cur_y + abs(s["x_m"] - cur_x) + s["y_m"]
            cur_aisle, cur_x = s["aisle_no"], s["x_m"]
        else:
            leg = s["y_m"] - cur_y
        cur_y = s["y_m"]
        legs.append((s, round(leg, 2)))
    back = round(cur_y + cur_x, 2) if ordered else 0.0
    return legs, back


def location_conflicts(proposal_sku: dict, loc: dict, occupants: list[dict], bay_neighbours: list[dict],
                       pairs: set, zone_classes: set) -> dict:
    """Evaluate every placement rule for one SKU-location pair. Returns {issue_type: detail}."""
    issues = {}
    cap_issue, units = capacity_issue(proposal_sku, loc)
    if cap_issue:
        issues["LOCATION_CAPACITY_EXCEEDED"] = f"{cap_issue}: units_fit={units} max_order_qty={proposal_sku['max_order_qty']}"
    if proposal_sku["required_storage_class"] not in zone_classes:
        issues["STORAGE_CLASS_MISMATCH"] = (
            f"requires {proposal_sku['required_storage_class']}; zone allows {'/'.join(sorted(zone_classes))}")
    key = compat_key(proposal_sku)
    clashes = sorted({n["sku_id"] for n in bay_neighbours if frozenset((key, n["compat_key"])) in pairs})
    if clashes:
        issues["INCOMPATIBLE_CO_LOCATION"] = f"key {key} clashes in bay {loc['bay_key']} with {','.join(clashes)}"
    if occupants:
        issues["DUPLICATE_ACTIVE_LOCATION"] = "location already held by " + ",".join(
            sorted(o["slot_id"] for o in occupants))
    return issues
