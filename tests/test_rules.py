from inventryx.rules import (capacity_issue, compat_key, fit_units, incompatible_pairs, location_conflicts,
                            reorder_point, required_storage_class, route)

LOC = dict(location_id="L1", width_cm=60.0, depth_cm=40.0, height_cm=30.0, max_weight_kg=20.0, bay_key="B1",
           x_m=5.0, y_m=2.0, level=2, is_golden_zone=True, zone_id="Z")


def sku(**kw):
    base = dict(sku_id="S1", length_cm=20.0, width_cm=20.0, height_cm=10.0, unit_weight_kg=1.0, max_order_qty=6,
                hazard_class="NONE", compat_group="GENERAL", required_storage_class="AMBIENT")
    return {**base, **kw}


def test_fit_allows_rotation_and_takes_weight_limit():
    # sorted dims (20,20,10) into (60,40,30): 3*2*3 = 18 by cube, 20 by weight
    assert fit_units(sku(), LOC) == (18, 18, 20)
    assert fit_units(sku(unit_weight_kg=2.5), LOC)[0] == 8


def test_capacity_issue_codes_and_boundary():
    assert capacity_issue(sku(length_cm=61.0), LOC)[0] == "DIMENSION"
    assert capacity_issue(sku(unit_weight_kg=25.0), LOC)[0] == "WEIGHT"
    assert capacity_issue(sku(max_order_qty=19), LOC)[0] == "UNIT_CAPACITY"
    assert capacity_issue(sku(max_order_qty=18), LOC)[0] is None          # exactly at capacity is valid
    assert capacity_issue(sku(length_cm=60.0, width_cm=40.0, height_cm=30.0, max_order_qty=1), LOC)[0] is None


def test_storage_class_precedence():
    assert required_storage_class("3", "AMBIENT", True) == "HAZMAT"
    assert required_storage_class("NONE", "FROZEN", True) == "FROZEN"
    assert required_storage_class("NONE", "AMBIENT", True) == "OVERSIZE"
    assert required_storage_class("NONE", "AMBIENT", False) == "AMBIENT"


def test_location_conflicts_reports_each_rule():
    pairs = incompatible_pairs()
    oxidizer = sku(hazard_class="5.1", compat_group="HAZMAT", required_storage_class="HAZMAT")
    neighbour = [dict(sku_id="S9", compat_key="3")]
    issues = location_conflicts(oxidizer, LOC, [dict(slot_id="X")], neighbour, pairs, {"AMBIENT"})
    assert set(issues) == {"STORAGE_CLASS_MISMATCH", "INCOMPATIBLE_CO_LOCATION", "DUPLICATE_ACTIVE_LOCATION"}
    assert compat_key(oxidizer) == "5.1"
    assert location_conflicts(sku(), LOC, [], [dict(sku_id="S9", compat_key="FOOD")], pairs, {"AMBIENT"}) == {}


def test_return_routing_distance():
    stops = [dict(key="a", aisle_no=2, x_m=5.0, y_m=4.0), dict(key="b", aisle_no=1, x_m=2.0, y_m=3.0),
             dict(key="c", aisle_no=2, x_m=5.0, y_m=1.0)]
    legs, back = route(stops)
    assert [s["key"] for s, _ in legs] == ["b", "c", "a"]
    # depot->b: 0+2+3=5; b->c: 3+3+1=7; c->a: 3; back: 4+5=9
    assert [leg for _, leg in legs] == [5.0, 7.0, 3.0] and back == 9.0


def test_reorder_point():
    assert reorder_point(1) == 0 and reorder_point(10) == 3
