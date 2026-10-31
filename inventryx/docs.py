"""Generate docs/data_dictionary.md and docs/erd.md from inventryx/schema.py."""
from pathlib import Path

from .schema import RELATIONSHIPS, TABLES


def data_dictionary() -> str:
    out = ["# Data dictionary", "",
           "Generated from `inventryx/schema.py` (`python -m inventryx docs`). Types: str, int, float, bool, "
           "date (YYYY-MM-DD), datetime (YYYY-MM-DDTHH:MM:SS, warehouse local time). Empty CSV cell = NULL. "
           "`derived` columns are calculated from source records, never generated independently.", "",
           "| Table | Kind | Rows describe | Primary key |", "|---|---|---|---|"]
    out += [f"| [{t.name}](#{t.name}) | {t.kind} | {t.desc} | {', '.join(t.pk)} |" for t in TABLES]
    for t in TABLES:
        out += ["", f"## {t.name}", "", f"*{t.kind}* - {t.desc}", "", f"Primary key: `{', '.join(t.pk)}`"
                + (f" · Natural keys: {', '.join('`' + '+'.join(k) + '`' for k in t.natural_keys)}"
                   if t.natural_keys else ""), "",
                "| Field | Type | Req | Unit | Allowed values / format | Unique | FK | Validation rule | Description |",
                "|---|---|---|---|---|---|---|---|---|"]
        for f in t.fields:
            allowed = ", ".join(f.enum) if f.enum else (f"`{f.pattern}`" if f.pattern else "")
            out.append(f"| `{f.name}` | {f.type} | {'Y' if f.required else 'N'} | {f.unit} | {allowed} "
                       f"| {'Y' if f.unique or (len(t.pk) == 1 and f.name == t.pk[0]) else ''} | {f.fk or ''} "
                       f"| {f.rule}{' (derived)' if f.derived else ''} | {f.desc} |")
    return "\n".join(out) + "\n"


def erd() -> str:
    out = ["# Entity relationships", "",
           "Cardinality, optionality and lifecycle. Many-to-many relationships use bridge tables "
           "(`zone_storage_class`, `warehouse_sku`, and the time-bounded `slot_assignment` between SKU and "
           "Location).", "", "```mermaid", "erDiagram"]
    sym = {"1:N": "||--o{", "1:1": "||--||"}
    for parent, child, col, card, optional in RELATIONSHIPS:
        base = card.split(" ")[0]
        arrow = "||--o|" if base.startswith("1:0..1") else ("||--||" if base == "1:1" else sym.get(base, "||--o{"))
        out.append(f"    {parent} {arrow} {child} : \"{col}\"")
    out += ["```", "", "| Parent | Child | FK | Cardinality | Optional |", "|---|---|---|---|---|"]
    out += [f"| {p} | {c} | `{col}` | {card} | {'yes' if o else 'no'} |" for p, c, col, card, o in RELATIONSHIPS]
    out += ["", "## Lifecycle states and effective dating", "",
            "| Entity | States | Transitions (logged in `state_event`) | Effective dating |", "|---|---|---|---|",
            "| orders | CREATED, RELEASED, ON_HOLD, PICKED, SHIPPED, CANCELLED | CREATED->RELEASED->(ON_HOLD->RELEASED)"
            "->PICKED->SHIPPED; CREATED->CANCELLED | order_ts .. shipped_ts |",
            "| slot_assignment | PROPOSED, APPROVED, ACTIVE, SUPERSEDED, REJECTED | legacy: ->ACTIVE->SUPERSEDED; "
            "optimizer: ->PROPOSED->ACTIVE; override: ->PROPOSED->APPROVED/REJECTED | effective_from (incl.) .. "
            "effective_to (excl., NULL = open) |",
            "| replenishment | CREATED, COMPLETED | CREATED->COMPLETED | created_ts .. completed_ts |",
            "| aisle | ACTIVE, BLOCKED | ACTIVE->BLOCKED->ACTIVE per aisle_block | aisle_block start_ts .. end_ts "
            "(excl.) |",
            "| sku_profile | versioned | new version supersedes prior (prior_profile_id) | effective_from .. "
            "effective_to |",
            "| warehouse_sku / location | ACTIVE (INACTIVE locations are never slotted) | - | effective_from |"]
    return "\n".join(out) + "\n"


def write_docs(root: Path):
    d = Path(root) / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "data_dictionary.md").write_text(data_dictionary(), encoding="utf-8", newline="\n")
    (d / "erd.md").write_text(erd(), encoding="utf-8", newline="\n")
