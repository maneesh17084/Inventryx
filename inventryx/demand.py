"""Orders and order lines with heavy-tailed SKU velocity, weekday seasonality and an October peak shift."""
import bisect
import itertools
import math
from datetime import datetime, timedelta

from . import config as C
from . import ids

PATTERNS = [("STEADY", 0.80), ("SEASONAL_PEAK", 0.12), ("DECLINING", 0.08)]
CHANNEL_MIX = [("ECOM", 0.62), ("RETAIL", 0.28), ("B2B", 0.10)]


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _geometric(r, p):
    return int(math.log(1.0 - r.random()) / math.log(1.0 - p))


def latent_demand(seed, skus, stock):
    """Hidden demand parameters. Exported only to ground_truth/, never as input features."""
    r = ids.stream(seed, "demand.latent")
    pattern = {}
    for s in skus:
        p = r.choices([x[0] for x in PATTERNS], weights=[x[1] for x in PATTERNS])[0]
        mult = 1.0 if p == "STEADY" else (r.uniform(2.5, 5.0) if p == "SEASONAL_PEAK" else r.uniform(0.15, 0.4))
        pattern[s["sku_id"]] = (p, round(mult, 4))
    truth = []
    for ws in stock:
        base = r.lognormvariate(0.0, 1.25) * (1.0 if ws["stocking_role"] == "PRIMARY" else 0.6)
        p, mult = pattern[ws["sku_id"]]
        truth.append(dict(warehouse_id=ws["warehouse_id"], sku_id=ws["sku_id"], base_weight=round(base, 6),
                          demand_pattern=p, peak_multiplier=mult))
    return truth


def generate_orders(scale, seed, warehouses, skus, truth):
    r = ids.stream(seed, "demand.orders")
    sku_by_id = {s["sku_id"]: s for s in skus}
    by_wh = {}
    for t in truth:
        by_wh.setdefault(t["warehouse_id"], []).append(t)
    samplers = {}
    for wid, rows in by_wh.items():
        pre = list(itertools.accumulate(t["base_weight"] for t in rows))
        peak = list(itertools.accumulate(t["base_weight"] * t["peak_multiplier"] for t in rows))
        samplers[wid] = ([t["sku_id"] for t in rows], pre, peak)

    days = list(_days(C.HISTORY_START, C.HISTORY_END))
    wh_ids = [w["warehouse_id"] for w in warehouses]
    wh_lines = ids.allocate(scale.order_lines, [w["location_count"] for w in warehouses])
    day_w = [C.WEEKDAY_FACTORS[d.weekday()] * (C.PEAK_VOLUME_FACTOR if d >= C.PEAK_START else 1.0) for d in days]

    raw_orders = []
    for wid, total in zip(wh_ids, wh_lines):
        population, pre, peak = samplers[wid]
        for d, n_lines in zip(days, ids.allocate(total, day_w)):
            cum = peak if d >= C.PEAK_START else pre
            left = n_lines
            while left > 0:
                channel = r.choices([c[0] for c in CHANNEL_MIX], weights=[c[1] for c in CHANNEL_MIX])[0]
                if channel == "ECOM":
                    size = min(6, 1 + _geometric(r, 0.55))
                elif channel == "RETAIL":
                    size = min(12, 1 + _geometric(r, 0.25))
                else:
                    size = min(20, 2 + _geometric(r, 0.18))
                size = min(size, left, len(population))
                left -= size
                chosen = []
                while len(chosen) < size:
                    idx = bisect.bisect_left(cum, r.random() * cum[-1])
                    sku = population[min(idx, len(population) - 1)]
                    if sku not in chosen:
                        chosen.append(sku)
                hour = r.triangular(6.0, 21.0, 12.0)
                order_ts = datetime(d.year, d.month, d.day) + timedelta(seconds=int(hour * 3600))
                express = r.random() < {"ECOM": 0.20, "RETAIL": 0.05, "B2B": 0.0}[channel]
                lines = []
                for sku in chosen:
                    moq = sku_by_id[sku]["max_order_qty"]
                    if channel == "ECOM":
                        qty = r.choices((1, 2, 3), weights=(0.7, 0.2, 0.1))[0]
                    elif channel == "RETAIL":
                        qty = r.randint(1, min(moq, 6))
                    else:
                        qty = r.randint(max(1, moq // 2), moq)
                    lines.append((sku, min(qty, moq)))
                raw_orders.append(dict(order_ts=order_ts, warehouse_id=wid, channel=channel, express=express,
                                       cancelled=r.random() < C.CANCEL_RATE, cancel_delay=r.randint(2, 30),
                                       lines=lines))

    raw_orders.sort(key=lambda o: (o["order_ts"], o["warehouse_id"]))
    orders, lines = [], []
    for n, o in enumerate(raw_orders, 1):
        oid = ids.order_id(n)
        ts = o["order_ts"]
        priority = "EXPRESS" if o["express"] else "STANDARD"
        carrier = {"ECOM": "PARCEL_EXPRESS" if o["express"] else "PARCEL_GROUND", "RETAIL": "STORE_FLEET",
                   "B2B": "LTL_FREIGHT"}[o["channel"]]
        required = ts + timedelta(hours=4) if o["express"] else datetime(ts.year, ts.month, ts.day, 18) + timedelta(
            days=1)
        status = "CANCELLED" if o["cancelled"] else "CREATED"
        orders.append(dict(order_id=oid, warehouse_id=o["warehouse_id"], channel=o["channel"], priority=priority,
                           carrier_service=carrier, order_ts=ts, required_ship_ts=required, release_ts=None,
                           hold_block_id=None, hold_release_ts=None, picked_ts=None, shipped_ts=None,
                           cancelled_ts=ts + timedelta(minutes=o["cancel_delay"]) if o["cancelled"] else None,
                           status=status, line_count=len(o["lines"]), total_units=sum(q for _, q in o["lines"]),
                           pick_distance_m=None, return_to_depot_m=None))
        for k, (sku, qty) in enumerate(o["lines"], 1):
            lines.append(dict(order_line_id=ids.order_line_id(oid, k), order_id=oid, line_no=k, sku_id=sku,
                              qty_ordered=qty, qty_picked=0,
                              status="CANCELLED" if o["cancelled"] else "PICKED"))
    return orders, lines
