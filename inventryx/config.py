"""Scale profiles, calendar and operating parameters.

Every tunable used by the generator, optimizer and simulator lives here so the
starter and full datasets come from exactly the same code path.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime

DEFAULT_SEED = 20261022
GENERATOR_VERSION = "1.0.0"

# --- Calendar -------------------------------------------------------------
HISTORY_START = date(2026, 7, 1)
HISTORY_END = date(2026, 10, 28)              # inclusive, last order date
PEAK_START = date(2026, 10, 1)                # peak demand shift begins
PROFILE_WINDOWS = {                           # version -> (window_start, window_end, effective_from, effective_to)
    1: (date(2026, 7, 1), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 15)),
    2: (date(2026, 10, 1), date(2026, 10, 14), date(2026, 10, 15), None),
}
LEGACY_EFFECTIVE = date(2026, 7, 1)
CUTOVER = date(2026, 10, 15)                  # optimized plan goes live
PLAN_CREATED_TS = datetime(2026, 10, 14, 22, 0, 0)
HOLDOUT = (date(2026, 10, 15), HISTORY_END)   # out-of-sample evaluation window
PROPOSAL_DATE = date(2026, 10, 29)
OVERRIDE_EFFECTIVE = date(2026, 11, 2)
AS_OF = datetime(2026, 10, 30, 0, 0, 0)

# --- Layout ---------------------------------------------------------------
AISLE_PITCH_M = 3.0
FIRST_AISLE_X_M = 2.0
FRONT_OFFSET_M = 1.0
INACTIVE_LOCATION_RATE = 0.005

# --- Picking --------------------------------------------------------------
PICKER_SPEED_MPS = 1.0
ORDER_SETUP_S = 45.0
PICK_BASE_S = 8.0
NON_GOLDEN_PENALTY_S = 4.0
PER_EXTRA_UNIT_S = 1.5

# --- Replenishment --------------------------------------------------------
ROP_FRACTION = 0.30                           # reorder point = floor(capacity * fraction)
REPLEN_BASE_MIN = 3.0
REPLEN_SPEED_MPS = 1.2
REPLEN_PER_UNIT_MIN = 0.02
LIFT_PENALTY_MIN = 1.5                        # levels >= LIFT_LEVEL need a lift
LIFT_LEVEL = 4
SCHEDULED_REPLEN_HOUR = 21
LABOR_CAPACITY_PERCENTILE = 0.95
LABOR_CAPACITY_HEADROOM = 1.05
LABOR_ROUNDING_MIN = 15

# --- Velocity classes -----------------------------------------------------
CLASS_A_CUM_SHARE = 0.80
CLASS_B_CUM_SHARE = 0.95
TREND_PEAK_UP_RATIO = 1.8
TREND_DOWN_RATIO = 0.5
PROFILE_PRIOR_DAYS = 14          # pseudo-count (days) of prior evidence in the forecast blend

# --- Demand ---------------------------------------------------------------
WEEKDAY_FACTORS = (1.10, 1.05, 1.00, 1.00, 1.05, 0.75, 0.55)  # Mon..Sun
PEAK_VOLUME_FACTOR = 1.35
CANCEL_RATE = 0.006
MULTI_WAREHOUSE_SECOND = 0.25
MULTI_WAREHOUSE_THIRD = 0.05


@dataclass(frozen=True)
class Scale:
    name: str
    warehouses: int
    locations: int
    skus: int
    order_lines: int
    suppliers: int
    # labelled edge-case volumes
    capacity_cases: int
    incompatible_cases: int
    storage_cases: int
    duplicate_cases: int
    valid_controls: int
    blocked_aisle_cases: int
    blocked_aisle_controls: int
    labor_cases: int
    labor_controls: int
    baseline_blocks_per_wh: int


PROFILES = {
    "starter": Scale("starter", 2, 1_000, 500, 10_000, 20,
                     capacity_cases=8, incompatible_cases=4, storage_cases=4, duplicate_cases=6,
                     valid_controls=10, blocked_aisle_cases=4, blocked_aisle_controls=2,
                     labor_cases=4, labor_controls=2, baseline_blocks_per_wh=8),
    "full": Scale("full", 20, 10_000, 5_000, 100_000, 120,
                  capacity_cases=40, incompatible_cases=20, storage_cases=20, duplicate_cases=30,
                  valid_controls=60, blocked_aisle_cases=16, blocked_aisle_controls=6,
                  labor_cases=20, labor_controls=4, baseline_blocks_per_wh=8),
}


def resolve_scale(profile: str, **overrides) -> Scale:
    scale = PROFILES[profile]
    overrides = {k: v for k, v in overrides.items() if v is not None}
    if overrides:
        scale = replace(scale, name=f"{profile}-custom", **overrides)
    return scale
