"""CSV / JSON / SQL export, typed loading and the checksum manifest."""
import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from .schema import TABLES

GT_COLUMNS = ["gt_id", "issue_type", "entity_type", "entity_id", "warehouse_id", "expected_decision", "label",
              "origin", "note"]


# --- value formatting ----------------------------------------------------
def to_text(field, v):
    if v is None:
        return ""
    if field.type == "bool":
        return "true" if v else "false"
    if field.type == "float":
        return f"{v:.{field.dec if field.dec is not None else 4}f}"
    if field.type == "datetime":
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if field.type == "date":
        return v.isoformat()
    return str(v)


def to_json(field, v):
    if v is None:
        return None
    if field.type == "float":
        return round(v, field.dec if field.dec is not None else 4)
    if field.type in ("date", "datetime"):
        return to_text(field, v)
    return v


def parse(field, s):
    if s == "":
        return None
    t = field.type
    if t == "int":
        return int(s)
    if t == "float":
        return float(s)
    if t == "bool":
        if s not in ("true", "false"):
            raise ValueError(f"bad bool {s!r}")
        return s == "true"
    if t == "date":
        return date.fromisoformat(s)
    if t == "datetime":
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
    return s


def sql_literal(field, v):
    if v is None:
        return "NULL"
    if field.type == "bool":
        return "TRUE" if v else "FALSE"
    if field.type in ("int", "float"):
        return to_text(field, v)
    if field.type == "datetime":
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    return "'" + to_text(field, v).replace("'", "''") + "'"


SQL_TYPES = {"str": "TEXT", "int": "INTEGER", "float": "NUMERIC", "bool": "BOOLEAN", "date": "DATE",
             "datetime": "TIMESTAMP"}


# --- writers --------------------------------------------------------------
def _write_rows_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        w.writerows(rows)


def write_tables(out: Path, tables: dict):
    (out / "csv").mkdir(parents=True, exist_ok=True)
    (out / "json").mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        rows = tables[t.name]
        _write_rows_csv(out / "csv" / f"{t.name}.csv", t.columns,
                        ([to_text(f, r[f.name]) for f in t.fields] for r in rows))
        with open(out / "json" / f"{t.name}.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write("[\n")
            for i, r in enumerate(rows):
                obj = {f.name: to_json(f, r[f.name]) for f in t.fields}
                fh.write(json.dumps(obj, separators=(",", ":")) + (",\n" if i < len(rows) - 1 else "\n"))
            fh.write("]\n")


def write_ground_truth(out: Path, gt: list, demand_truth: list):
    d = out / "ground_truth"
    d.mkdir(parents=True, exist_ok=True)
    _write_rows_csv(d / "ground_truth.csv", GT_COLUMNS, ([g[c] for c in GT_COLUMNS] for g in gt))
    with open(d / "ground_truth.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump([{c: g[c] for c in GT_COLUMNS} for g in gt], fh, indent=1)
        fh.write("\n")
    cols = ["warehouse_id", "sku_id", "base_weight", "demand_pattern", "peak_multiplier"]
    _write_rows_csv(d / "demand_truth.csv", cols, ([r[c] for c in cols] for r in demand_truth))


def ddl() -> str:
    out = ["-- Generated from inventryx/schema.py. Compatible with SQLite 3.23+ and PostgreSQL 12+.", ""]
    for t in TABLES:
        cols = []
        for f in t.fields:
            line = f"    {f.name} {SQL_TYPES[f.type]}"
            if f.required:
                line += " NOT NULL"
            if f.enum:
                line += f" CHECK ({f.name} IN (" + ", ".join(f"'{e}'" for e in f.enum) + "))"
            cols.append(line)
        cols.append(f"    PRIMARY KEY ({', '.join(t.pk)})")
        for f in t.fields:
            if f.fk:
                ref_t, ref_c = f.fk.split(".")
                cols.append(f"    FOREIGN KEY ({f.name}) REFERENCES {ref_t} ({ref_c})")
        for nk in t.natural_keys:
            cols.append(f"    UNIQUE ({', '.join(nk)})")
        out.append(f"-- {t.desc}")
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(out)


def write_sql(out: Path, tables: dict, batch=500):
    d = out / "sql"
    d.mkdir(parents=True, exist_ok=True)
    (d / "schema.sql").write_text(ddl(), encoding="utf-8", newline="\n")
    with open(d / "seed.sql", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- Seed data in foreign-key dependency order. Load after schema.sql.\nBEGIN;\n")
        for t in TABLES:
            rows = tables[t.name]
            head = f"INSERT INTO {t.name} ({', '.join(t.columns)}) VALUES\n"
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                fh.write(head + ",\n".join(
                    "(" + ", ".join(sql_literal(f, r[f.name]) for f in t.fields) + ")" for r in chunk) + ";\n")
        fh.write("COMMIT;\n")


def write_schema_json(out: Path):
    d = out / "schema"
    d.mkdir(parents=True, exist_ok=True)
    spec = []
    for t in TABLES:
        spec.append(dict(table=t.name, kind=t.kind, description=t.desc, primary_key=list(t.pk),
                         natural_keys=[list(k) for k in t.natural_keys],
                         fields=[dict(name=f.name, type=f.type, required=f.required, description=f.desc,
                                      unit=f.unit or None, allowed_values=list(f.enum) if f.enum else None,
                                      unique=f.unique, pattern=f.pattern, foreign_key=f.fk, decimals=f.dec,
                                      rule=f.rule or None, derived=f.derived) for f in t.fields]))
    (d / "data_dictionary.json").write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8", newline="\n")


# --- loading --------------------------------------------------------------
def load_tables(path: Path) -> tuple[dict, list]:
    """Load every CSV back with schema typing. Returns (tables, load_errors)."""
    tables, errors = {}, []
    for t in TABLES:
        p = path / "csv" / f"{t.name}.csv"
        rows = []
        with open(p, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            if header != t.columns:
                errors.append(f"{t.name}: header mismatch {header} != {t.columns}")
                tables[t.name] = []
                continue
            for n, rec in enumerate(reader, 2):
                row = {}
                for f, v in zip(t.fields, rec):
                    try:
                        row[f.name] = parse(f, v)
                    except ValueError as e:
                        errors.append(f"{t.name} line {n} {f.name}: {e}")
                        row[f.name] = None
                rows.append(row)
        tables[t.name] = rows
    return tables, errors


def load_ground_truth(path: Path) -> list:
    with open(path / "ground_truth" / "ground_truth.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- manifest ----------------------------------------------------------------
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out: Path, meta: dict, tables: dict):
    files = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files.append(dict(path=p.relative_to(out).as_posix(), bytes=p.stat().st_size, sha256=sha256(p)))
    manifest = dict(meta, tables={t.name: dict(kind=t.kind, rows=len(tables[t.name])) for t in TABLES},
                    files=files)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + "\n", encoding="utf-8",
                                       newline="\n")
    return manifest
