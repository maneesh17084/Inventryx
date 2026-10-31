"""SKUProfile derivation: velocity is computed from order lines, never generated independently."""
from collections import defaultdict

from . import config as C
from . import ids


def build_profiles(stock, skus, orders, lines):
    sku_by_id = {s["sku_id"]: s for s in skus}
    order_by_id = {o["order_id"]: o for o in orders}
    profiles = []
    prior = {}
    for version, (ws, we, eff_from, eff_to) in sorted(C.PROFILE_WINDOWS.items()):
        days = (we - ws).days + 1
        agg = defaultdict(lambda: [0, 0, set()])
        for ln in lines:
            o = order_by_id[ln["order_id"]]
            d = o["order_ts"].date()
            if o["status"] == "CANCELLED" or not ws <= d <= we:
                continue
            a = agg[(o["warehouse_id"], ln["sku_id"])]
            a[0] += 1
            a[1] += ln["qty_ordered"]
            a[2].add(d)
        rows_by_wh = defaultdict(list)
        for st in stock:
            key = (st["warehouse_id"], st["sku_id"])
            n_lines, units, active = agg.get(key, (0, 0, set()))
            sku = sku_by_id[st["sku_id"]]
            row = dict(profile_id=ids.profile_id(key[0], key[1], version), warehouse_id=key[0], sku_id=key[1],
                       version=version, window_start=ws, window_end=we, window_days=days, effective_from=eff_from,
                       effective_to=eff_to, order_lines=n_lines, units_total=units, active_days=len(active),
                       lines_per_day=round(n_lines / days, 4), units_per_day=round(units / days, 4),
                       cube_l_per_day=round(units / days * sku["unit_volume_l"], 4),
                       velocity_rank=0, velocity_class="D", prior_profile_id=None, velocity_shift_ratio=None,
                       demand_trend="BASELINE")
            if key in prior:
                p = prior[key]
                row["prior_profile_id"] = p["profile_id"]
                if p["lines_per_day"] > 0:
                    row["velocity_shift_ratio"] = round(row["lines_per_day"] / p["lines_per_day"], 4)
                    ratio = row["velocity_shift_ratio"]
                    row["demand_trend"] = ("PEAK_UP" if ratio >= C.TREND_PEAK_UP_RATIO else
                                           "DOWN" if ratio <= C.TREND_DOWN_RATIO else "STABLE")
                else:
                    row["demand_trend"] = "NEW" if n_lines else "INACTIVE"
            rows_by_wh[key[0]].append(row)
        for wid, wh_rows in rows_by_wh.items():
            # Forecast = observed rate shrunk toward the prior version's rate scaled by the warehouse-wide
            # volume lift (pseudo-count PROFILE_PRIOR_DAYS). Damps 14-day noise but keeps peak shifts.
            prior_rows = [prior[(wid, x["sku_id"])] for x in wh_rows if (wid, x["sku_id"]) in prior]
            prior_lines = sum(p["lines_per_day"] for p in prior_rows)
            lift = (sum(x["lines_per_day"] for x in wh_rows) / prior_lines) if prior_lines else 1.0
            k = C.PROFILE_PRIOR_DAYS
            for x in wh_rows:
                p = prior.get((wid, x["sku_id"]))
                if p is None:
                    x["forecast_lines_per_day"], x["forecast_units_per_day"] = x["lines_per_day"], x["units_per_day"]
                    continue
                x["forecast_lines_per_day"] = round(
                    (x["order_lines"] + k * p["lines_per_day"] * lift) / (x["window_days"] + k), 4)
                x["forecast_units_per_day"] = round(
                    (x["units_total"] + k * p["units_per_day"] * lift) / (x["window_days"] + k), 4)
            wh_rows.sort(key=lambda x: (-x["order_lines"], -x["units_total"], x["sku_id"]))
            total = sum(x["order_lines"] for x in wh_rows) or 1
            cum = 0
            for rank, x in enumerate(wh_rows, 1):
                x["velocity_rank"] = rank
                if x["order_lines"] == 0:
                    x["velocity_class"] = "D"
                    continue
                share_before = cum / total
                cum += x["order_lines"]
                x["velocity_class"] = ("A" if share_before < C.CLASS_A_CUM_SHARE else
                                       "B" if share_before < C.CLASS_B_CUM_SHARE else "C")
            profiles.extend(wh_rows)
        prior = {(x["warehouse_id"], x["sku_id"]): x for x in profiles if x["version"] == version}
    profiles.sort(key=lambda x: (x["version"], x["warehouse_id"], x["sku_id"]))
    return profiles
