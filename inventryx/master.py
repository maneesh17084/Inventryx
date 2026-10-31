"""Master/reference data: warehouses, zones, aisles, locations, suppliers, SKUs, stocking bridge."""
import math
from datetime import date, timedelta

from . import config as C
from . import ids
from .rules import COMPATIBILITY_RULES, fit_units, is_oversized, required_storage_class

# Zones are laid out from the dock outward in this order (travel_rank).
ZONE_TEMPLATES = [
    dict(type="FORWARD_PICK", temp="AMBIENT", classes=("AMBIENT",), loc_type="FLOW_RACK", share=0.24,
         widths=(50, 60, 75, 90), depths=(60, 80), heights=(35, 40, 50), max_wt=(40, 50, 60),
         levels=4, bays=10, bay_m=1.0),
    dict(type="SHELF", temp="AMBIENT", classes=("AMBIENT",), loc_type="SHELF", share=0.30,
         widths=(90, 100, 120), depths=(60, 80), heights=(45, 55, 65), max_wt=(80, 100, 120),
         levels=5, bays=12, bay_m=1.2),
    dict(type="CHILLED", temp="CHILLED", classes=("CHILLED",), loc_type="COLD_SHELF", share=0.12,
         widths=(60, 90, 100), depths=(60,), heights=(40, 50), max_wt=(60, 80),
         levels=4, bays=10, bay_m=1.2),
    dict(type="FROZEN", temp="FROZEN", classes=("FROZEN",), loc_type="FREEZER_SHELF", share=0.09,
         widths=(60, 90), depths=(60,), heights=(40, 50), max_wt=(60, 80),
         levels=4, bays=8, bay_m=1.2),
    dict(type="HAZMAT", temp="AMBIENT", classes=("HAZMAT",), loc_type="HAZMAT_CABINET", share=0.07,
         widths=(60, 90), depths=(50, 60), heights=(40, 50), max_wt=(80, 120),
         levels=3, bays=6, bay_m=1.2),
    dict(type="BULK", temp="AMBIENT", classes=("AMBIENT", "OVERSIZE"), loc_type="PALLET_RACK", share=0.18,
         widths=(120,), depths=(100, 120), heights=(120, 150, 180), max_wt=(600, 1000),
         levels=3, bays=8, bay_m=2.8),
]

GOLDEN_LEVELS = {"FLOW_RACK": {2, 3}, "SHELF": {2, 3}, "COLD_SHELF": {2, 3}, "FREEZER_SHELF": {2, 3},
                 "HAZMAT_CABINET": {2}, "PALLET_RACK": {1}}

# Smallest location of the main zone for each storage class; every SKU must fit it with
# max_order_qty units, which guarantees a feasible slot exists in every stocking warehouse.
REFERENCE_SLOT = {
    "AMBIENT": dict(width_cm=90, depth_cm=60, height_cm=45, max_weight_kg=80),
    "OVERSIZE": dict(width_cm=120, depth_cm=100, height_cm=120, max_weight_kg=600),
    "CHILLED": dict(width_cm=60, depth_cm=60, height_cm=40, max_weight_kg=60),
    "FROZEN": dict(width_cm=60, depth_cm=60, height_cm=40, max_weight_kg=60),
    "HAZMAT": dict(width_cm=60, depth_cm=50, height_cm=40, max_weight_kg=80),
}

STORAGE_CLASS_ROWS = [
    ("AMBIENT", "Ambient, standard handling", 10.0, 30.0),
    ("CHILLED", "Chilled 2-8 C", 2.0, 8.0),
    ("FROZEN", "Frozen -25 to -18 C", -25.0, -18.0),
    ("HAZMAT", "Dangerous goods cabinet, ambient", 10.0, 25.0),
    ("OVERSIZE", "Oversized / pallet-handled ambient", 10.0, 30.0),
]

SITE_NAMES = ["Riverside", "Northgate", "Lakeshore", "Pinecrest", "Harbor Point", "Meadowbrook", "Ironwood",
              "Silver Creek", "Eastfield", "Westbrook", "Cedar Ridge", "Summit", "Oakvale", "Bayview",
              "Granite Falls", "Maple Grove", "Stonebridge", "Fairhaven", "Redwood", "Clearwater"]
SUPPLIER_WORDS = (["Apex", "Blue", "Crest", "Delta", "Evergreen", "Falcon", "Golden", "Horizon", "Iris", "Juniper",
                   "Keystone", "Lumen", "Meridian", "Nova", "Orchid", "Pioneer"],
                  ["Goods", "Supply", "Trading", "Industries", "Brands", "Manufacturing", "Imports", "Products"])

CLASS_MIX = [("AMBIENT", 0.71), ("OVERSIZE", 0.05), ("CHILLED", 0.10), ("FROZEN", 0.08), ("HAZMAT", 0.06)]
CATEGORY_BY_CLASS = {
    "AMBIENT": [("GROCERY_DRY", "FOOD", 0.25), ("HOUSEHOLD", "GENERAL", 0.20), ("ELECTRONICS", "GENERAL", 0.15),
                ("APPAREL", "GENERAL", 0.15), ("HEALTH_BEAUTY", "GENERAL", 0.15), ("TOYS", "GENERAL", 0.10)],
    "OVERSIZE": [("FURNITURE", "GENERAL", 0.4), ("APPLIANCES", "GENERAL", 0.35), ("GARDEN", "GENERAL", 0.25)],
    "CHILLED": [("DAIRY", "FOOD", 0.6), ("FRESH_PRODUCE", "FOOD", 0.4)],
    "FROZEN": [("FROZEN_FOOD", "FOOD", 1.0)],
    "HAZMAT": [("CHEMICALS", "HAZMAT", 0.55), ("AEROSOLS", "HAZMAT", 0.25), ("BATTERIES", "HAZMAT", 0.20)],
}
HAZARD_BY_CATEGORY = {"CHEMICALS": [("3", 0.45), ("8", 0.30), ("5.1", 0.25)], "AEROSOLS": [("2.1", 1.0)],
                      "BATTERIES": [("9", 1.0)]}


def _pick(r, weighted):
    return r.choices([w[0] for w in weighted], weights=[w[-1] for w in weighted], k=1)[0]


def _half(x):
    return round(round(x * 2) / 2, 1)


def generate_layout(scale, seed):
    r = ids.stream(seed, "master.layout")
    warehouses, zones, zone_classes, aisles, locations = [], [], [], [], []
    loc_counts = ids.allocate(scale.locations, [r.uniform(0.8, 1.2) for _ in range(scale.warehouses)])
    for i in range(scale.warehouses):
        wid = ids.wh_id(i + 1)
        name = SITE_NAMES[i % len(SITE_NAMES)] + ("" if i < len(SITE_NAMES) else f" {i // len(SITE_NAMES) + 1}")
        wh = dict(warehouse_id=wid, warehouse_name=f"{name} DC", region=r.choice(("NORTH", "SOUTH", "EAST", "WEST",
                                                                                   "CENTRAL")),
                  operator_code=f"OPR-{r.randint(1, 6):02d}",
                  opened_date=date(2008, 1, 1) + timedelta(days=r.randint(0, 5300)),
                  status="ACTIVE", aisle_pitch_m=C.AISLE_PITCH_M)
        zone_counts = ids.allocate(loc_counts[i], [t["share"] for t in ZONE_TEMPLATES])
        aisle_no = 0
        wh_locs = wh_aisles = 0
        for zi, (t, cnt) in enumerate(zip(ZONE_TEMPLATES, zone_counts)):
            zid = ids.zone_id(wid, zi + 1)
            per_aisle = 2 * t["bays"] * t["levels"]
            n_aisles = max(1, math.ceil(cnt / per_aisle))
            n = 0
            for _ in range(n_aisles):
                aisle_no += 1
                aid = ids.aisle_id(wid, aisle_no)
                x = round(C.FIRST_AISLE_X_M + (aisle_no - 1) * C.AISLE_PITCH_M, 2)
                depth = r.choice(t["depths"])
                aisles.append(dict(aisle_id=aid, warehouse_id=wid, zone_id=zid, aisle_no=aisle_no, x_m=x,
                                   length_m=round(C.FRONT_OFFSET_M + t["bays"] * t["bay_m"], 2),
                                   bay_count=t["bays"], status="ACTIVE"))
                for bay in range(1, t["bays"] + 1):
                    width = r.choice(t["widths"])
                    max_wt = r.choice(t["max_wt"])
                    y = round(C.FRONT_OFFSET_M + (bay - 0.5) * t["bay_m"], 2)
                    for side in ("L", "R"):
                        for level in range(1, t["levels"] + 1):
                            if n >= cnt:
                                break
                            n += 1
                            height = r.choice(t["heights"])
                            inactive = r.random() < C.INACTIVE_LOCATION_RATE
                            locations.append(dict(
                                location_id=ids.location_id(zid, n), warehouse_id=wid, zone_id=zid, aisle_id=aid,
                                side=side, bay=bay, level=level, bay_key=f"{aid}-{side}-B{bay:02d}", x_m=x, y_m=y,
                                width_cm=float(width), depth_cm=float(depth), height_cm=float(height),
                                volume_l=round(width * depth * height / 1000.0, 3), max_weight_kg=float(max_wt),
                                location_type=t["loc_type"], is_golden_zone=level in GOLDEN_LEVELS[t["loc_type"]],
                                status="INACTIVE" if inactive else "ACTIVE", effective_from=wh["opened_date"]))
            zones.append(dict(zone_id=zid, warehouse_id=wid, zone_code=f"Z{zi + 1:02d}", zone_type=t["type"],
                              temp_class=t["temp"], travel_rank=zi + 1, aisle_count=n_aisles, location_count=cnt,
                              status="ACTIVE"))
            zone_classes.extend(dict(zone_id=zid, storage_class_code=c) for c in t["classes"])
            wh_locs += cnt
            wh_aisles += n_aisles
        wh.update(location_count=wh_locs, zone_count=len(ZONE_TEMPLATES), aisle_count=wh_aisles)
        warehouses.append(wh)
    storage = [dict(storage_class_code=c, description=d, temp_min_c=lo, temp_max_c=hi)
               for c, d, lo, hi in STORAGE_CLASS_ROWS]
    return dict(storage_class=storage, warehouse=warehouses, zone=zones, zone_storage_class=zone_classes,
                aisle=aisles, location=locations)


def _dims(cls, r):
    ln = r.lognormvariate
    if cls == "OVERSIZE":
        a = r.uniform(65, 115)
        b = r.uniform(40, min(a, 95))
        c = r.uniform(30, 110)
        density = r.uniform(0.06, 0.25)
    elif cls == "HAZMAT":
        a = min(max(ln(math.log(18), 0.35), 5), 32)
        b = a * r.uniform(0.4, 1.0)
        c = min(max(ln(math.log(20), 0.35), 5), 35)
        density = r.uniform(0.7, 1.3)
    elif cls in ("CHILLED", "FROZEN"):
        a = min(max(ln(math.log(20), 0.4), 4), 38)
        b = a * r.uniform(0.4, 1.0)
        c = min(max(ln(math.log(12), 0.45), 2), 35)
        density = r.uniform(0.5, 1.0)
    else:
        a = min(max(ln(math.log(24), 0.5), 4), 55)
        b = a * r.uniform(0.35, 1.0)
        c = min(max(ln(math.log(15), 0.55), 2), 45)
        density = r.uniform(0.1, 0.8)
    dims = sorted((_half(a), _half(b), _half(c)), reverse=True)
    return dims[0], dims[1], dims[2], density


def _max_order_qty(volume_l, oversized, r):
    if oversized:
        return r.choice((1, 2))
    for limit, qty in ((0.5, 24), (2.0, 12), (8.0, 6), (30.0, 4)):
        if volume_l < limit:
            return qty
    return 2


def _derive_sku(s):
    vol = s["length_cm"] * s["width_cm"] * s["height_cm"] / 1000.0
    s["unit_volume_l"] = round(vol, 3)
    s["is_oversized"] = is_oversized(s["length_cm"], s["width_cm"], s["height_cm"])
    s["required_storage_class"] = required_storage_class(s["hazard_class"], s["temp_class"], s["is_oversized"])


def generate_items(scale, seed, warehouses):
    r = ids.stream(seed, "master.items")
    suppliers = []
    for n in range(1, scale.suppliers + 1):
        suppliers.append(dict(supplier_id=ids.supplier_id(n),
                              supplier_name=f"{r.choice(SUPPLIER_WORDS[0])} {r.choice(SUPPLIER_WORDS[1])} {n:04d}",
                              country_code=r.choice(("US", "CA", "MX", "DE", "GB", "CN", "IN", "VN")),
                              lead_time_days=r.randint(2, 45), status="ACTIVE"))
    skus = []
    for n in range(1, scale.skus + 1):
        cls = _pick(r, CLASS_MIX)
        category, group, _ = r.choices(CATEGORY_BY_CLASS[cls], weights=[c[2] for c in CATEGORY_BY_CLASS[cls]])[0]
        hazard = _pick(r, HAZARD_BY_CATEGORY[category]) if group == "HAZMAT" else "NONE"
        temp = cls if cls in ("CHILLED", "FROZEN") else "AMBIENT"
        length, width, height, density = _dims(cls, r)
        s = dict(sku_id=ids.sku_id(n), sku_name=f"{category.replace('_', ' ').title()} item {n:06d}",
                 supplier_id=r.choice(suppliers)["supplier_id"], category=category, length_cm=length,
                 width_cm=width, height_cm=height, unit_weight_kg=0.0, temp_class=temp, hazard_class=hazard,
                 compat_group=group, max_order_qty=1,
                 created_date=date(2019, 1, 1) + timedelta(days=r.randint(0, 2700)), status="ACTIVE")
        s["unit_weight_kg"] = round(max(0.05, length * width * height / 1000.0 * density), 3)
        _derive_sku(s)
        s["max_order_qty"] = _max_order_qty(s["unit_volume_l"], s["is_oversized"], r)
        # Guarantee a feasible slot: shrink until the SKU fits its class's reference slot.
        while True:
            units = fit_units(s, REFERENCE_SLOT[s["required_storage_class"]])[0]
            if units >= s["max_order_qty"]:
                break
            if units >= 1:
                s["max_order_qty"] = units
                break
            for k in ("length_cm", "width_cm", "height_cm"):
                s[k] = _half(s[k] * 0.9)
            s["unit_weight_kg"] = round(max(0.05, s["unit_weight_kg"] * 0.8), 3)
            _derive_sku(s)
        skus.append(s)

    # Stocking bridge (N:M): primary warehouse weighted by size, some SKUs in 2-3 warehouses.
    weights = [w["location_count"] for w in warehouses]
    wh_ids = [w["warehouse_id"] for w in warehouses]
    stock = []
    for s in skus:
        chosen = [r.choices(wh_ids, weights=weights)[0]]
        extra = 0
        if len(wh_ids) > 1 and r.random() < C.MULTI_WAREHOUSE_SECOND:
            extra = 2 if (len(wh_ids) > 2 and r.random() < C.MULTI_WAREHOUSE_THIRD / C.MULTI_WAREHOUSE_SECOND) else 1
        while len(chosen) < 1 + extra:
            w = r.choices(wh_ids, weights=weights)[0]
            if w not in chosen:
                chosen.append(w)
        for k, w in enumerate(chosen):
            eff = max(s["created_date"], date(2026, 1, 1)) if k == 0 else date(2026, 6, 1)
            stock.append(dict(warehouse_id=w, sku_id=s["sku_id"], stocking_role="PRIMARY" if k == 0 else "SECONDARY",
                              effective_from=min(eff, C.LEGACY_EFFECTIVE)))
    stock.sort(key=lambda x: (x["warehouse_id"], x["sku_id"]))
    rules = [dict(rule_id=f"CMP-{i:03d}", key_a=min(a, b), key_b=max(a, b), relation="INCOMPATIBLE",
                  scope="SAME_BAY", description=d) for i, (a, b, d) in enumerate(COMPATIBILITY_RULES, 1)]
    return dict(supplier=suppliers, sku=skus, warehouse_sku=stock, compatibility_rule=rules)
