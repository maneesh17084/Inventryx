# Slotting evaluation

Dataset `starter` - seed 20261022 - holdout 2026-10-15 to 2026-10-28 (519 orders, 1,449 lines, same orders in every scenario).

## Pick path and throughput (out-of-sample)

| Scenario | Distance / order (m) | Distance vs baseline | Lines / picker-hour | Throughput vs baseline | Golden-zone picks |
|---|---:|---:|---:|---:|---:|
| Baseline (legacy, velocity-blind) | 67.91 | baseline | 67.44 | baseline | 48.0% |
| Optimized on Jul-Sep profile (v1) | 55.97 | -17.57% | 74.55 | +10.54% | 68.5% |
| Optimized, peak-aware (v2) - deployed | 54.26 | -20.10% | 75.82 | +12.43% | 73.4% |

## Replenishment impact (same holdout picks)

| Scenario | Tasks | Emergency | Labor minutes | vs baseline | Days over capacity | Minutes over |
|---|---:|---:|---:|---:|---:|---:|
| Baseline (legacy, velocity-blind) | 185 | 50 | 762.0 | baseline | 1 | 4.9 |
| Optimized on Jul-Sep profile (v1) | 84 | 13 | 329.7 | -56.73% | 0 | 0.0 |
| Optimized, peak-aware (v2) - deployed | 83 | 13 | 325.5 | -57.29% | 0 | 0.0 |

## Slotting decisions

- SKUs re-slotted at cutover (2026-10-15): **630** of 634; location utilisation 63.98%.
- A-class SKUs in forward-pick zone: legacy 19.23% -> optimized 15.38%; in golden zone 44.87% -> 73.72%.
- Peak-aware v2 vs static v1: distance 54.26 vs 55.97 m/order; replenishment 325 vs 330 min.
- Planner overrides: {'APPROVED': 10, 'REJECTED': 22}.
- Seasonal SKUs detected as PEAK_UP: recall 69.7%, precision 37.9%.

## Exception detection vs ground truth

| Issue type | Positives | Flagged | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| LOCATION_CAPACITY_EXCEEDED | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |
| STORAGE_CLASS_MISMATCH | 4 | 4 | 4 | 0 | 0 | 1.0 | 1.0 |
| INCOMPATIBLE_CO_LOCATION | 4 | 4 | 4 | 0 | 0 | 1.0 | 1.0 |
| DUPLICATE_ACTIVE_LOCATION | 6 | 6 | 6 | 0 | 0 | 1.0 | 1.0 |
| PICK_PATH_BLOCKED_AISLE | 4 | 4 | 4 | 0 | 0 | 1.0 | 1.0 |
| REPLEN_LABOR_EXCEEDED | 9 | 9 | 9 | 0 | 0 | 1.0 | 1.0 |

Negative/boundary controls: 14, false alarms 0 (specificity 1.0).

## Validation

210 / 210 checks passed (0 failed) - see validation_summary.md.
