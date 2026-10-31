"""Deterministic, zero-padded identifiers. IDs are assigned once and never rewritten."""
import hashlib
import random
from datetime import date


def wh_id(n: int) -> str:
    return f"WH-{n:03d}"


def zone_id(warehouse_id: str, n: int) -> str:
    return f"{warehouse_id}-Z{n:02d}"


def aisle_id(warehouse_id: str, n: int) -> str:
    return f"{warehouse_id}-A{n:03d}"


def location_id(zone: str, n: int) -> str:
    return f"LOC-{zone}-{n:06d}"


def supplier_id(n: int) -> str:
    return f"SUP-{n:04d}"


def sku_id(n: int) -> str:
    return f"SKU-{n:06d}"


def profile_id(warehouse_id: str, sku: str, version: int) -> str:
    return f"SKP-{warehouse_id}-{sku}-V{version}"


def order_id(n: int) -> str:
    return f"ORD-2026-{n:06d}"


def order_line_id(order: str, n: int) -> str:
    return f"{order}-L{n:03d}"


def pick_id(order: str, n: int) -> str:
    return f"PICK-{order}-{n:03d}"


def slot_id(n: int) -> str:
    return f"SLOT-2026-{n:06d}"


def candidate_id(n: int) -> str:
    return f"CAND-2026-{n:07d}"


def replen_id(n: int) -> str:
    return f"REPL-2026-{n:06d}"


def block_id(n: int) -> str:
    return f"ABLK-2026-{n:04d}"


def labor_id(warehouse_id: str, d: date) -> str:
    return f"LAB-{warehouse_id}-{d:%Y%m%d}"


def labor_day_id(warehouse_id: str, d: date) -> str:
    return f"RLD-{warehouse_id}-{d:%Y%m%d}"


def event_id(n: int) -> str:
    return f"EVT-2026-{n:07d}"


def exception_id(n: int) -> str:
    return f"EXC-2026-{n:06d}"


def gt_id(n: int) -> str:
    return f"GT-{n:05d}"


def stream(seed: int, name: str) -> random.Random:
    """Independent RNG sub-stream per component so adding one never shifts another."""
    digest = hashlib.sha256(f"{seed}|{name}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def allocate(total: int, weights: list[float]) -> list[int]:
    """Largest-remainder split of an integer total, exact and deterministic."""
    s = sum(weights)
    raw = [total * w / s for w in weights]
    base = [int(r) for r in raw]
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[: total - sum(base)]:
        base[i] += 1
    return base
