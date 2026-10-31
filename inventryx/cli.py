"""Command line: serve (default) | generate | validate | reproduce | docs | package."""
import sys

if __package__ in (None, ""):
    # Executed as a file (VS Code "Run Python File", `python inventryx/cli.py`): re-enter as the package.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from inventryx.cli import main
    sys.exit(main())

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import config as C
from . import export, pipeline, report
from .docs import write_docs
from .validate import validate

ROOT = Path(__file__).resolve().parent.parent


def _meta(scale, seed):
    overrides = "".join(f" --{k.replace('_', '-')} {getattr(scale, k)}"
                        for k in ("warehouses", "locations", "skus", "order_lines")
                        if scale.name.endswith("-custom"))
    base = scale.name.removesuffix("-custom")
    return dict(profile=scale.name, seed=seed, generator_version=C.GENERATOR_VERSION,
                command=f"python -m inventryx generate --profile {base} --seed {seed}{overrides}",
                scale=scale.__dict__,
                calendar=dict(history=[str(C.HISTORY_START), str(C.HISTORY_END)], peak_start=str(C.PEAK_START),
                              cutover=str(C.CUTOVER), holdout=[str(C.HOLDOUT[0]), str(C.HOLDOUT[1])],
                              as_of=str(C.AS_OF)),
                provenance="100% synthetic; no external datasets used. See docs/provenance.md.")


def generate(scale, seed, out: Path, argv, log=print, hint=True):
    t0 = time.time()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    log(f"[generate] profile={scale.name} seed={seed} -> {out}")
    tables, gt, extras = pipeline.build(scale, seed, log=log)
    log("  writing CSV / JSON / SQL / ground truth")
    export.write_tables(out, tables)
    export.write_sql(out, tables)
    export.write_schema_json(out)
    export.write_ground_truth(out, gt, extras["demand_truth"])
    report.write_scenarios(out, extras["scenario_rows"], extras["scenario_summary"], extras["scenario_per_warehouse"])
    meta = _meta(scale, seed)
    log("  validating exported files")
    validation, loaded, gt_loaded = validate(out)
    report.write_validation(out, validation)
    metrics = report.build_metrics(out, loaded, gt_loaded, validation, meta)
    report.write_metrics(out, metrics)
    report.write_evaluation(out, metrics)
    report.write_html(out, metrics, validation)
    manifest = export.write_manifest(out, dict(meta, validation=dict(passed=validation["passed"],
                                                                      failed=validation["failed"])), tables)
    log(f"  done in {time.time() - t0:.1f}s - {validation['passed']}/{validation['total']} checks passed, "
        f"{len(manifest['files'])} files")
    if hint:
        log(f"  explore it in the web app: python -m inventryx serve --data {out}")
    for c in validation["checks"]:
        if c["status"] == "FAIL":
            log(f"  FAIL [{c['category']}] {c['check']}: {c['violations']} e.g. {c['sample'][:3]}")
    return validation, manifest


def reproduce(scale, seed, out: Path, argv):
    """Build twice in a throw-away temp folder (outside the project, removed even on failure) and write one
    JSON report to `out`."""
    import tempfile
    runs = []
    with tempfile.TemporaryDirectory(prefix="inventryx-repro-") as tmp:
        for tag in ("run_a", "run_b"):
            target = Path(tmp) / tag
            generate(scale, seed, target, argv, log=lambda *a: None, hint=False)
            runs.append(json.loads((target / "manifest.json").read_text(encoding="utf-8")))
    a = {f["path"]: f["sha256"] for f in runs[0]["files"]}
    b = {f["path"]: f["sha256"] for f in runs[1]["files"]}
    diff = sorted(p for p in a.keys() | b.keys() if a.get(p) != b.get(p))
    published = ROOT / "data" / scale.name / "manifest.json"
    vs_published = None
    if published.exists():
        pub = {f["path"]: f["sha256"] for f in json.loads(published.read_text(encoding="utf-8"))["files"]}
        vs_published = sorted(p for p in a.keys() | pub.keys() if a.get(p) != pub.get(p))
    result = dict(profile=scale.name, seed=seed, files_compared=len(a), identical=not diff, differing_files=diff,
                  row_counts_a=runs[0]["tables"], row_counts_b=runs[1]["tables"],
                  row_counts_equal=runs[0]["tables"] == runs[1]["tables"],
                  matches_published_dataset=None if vs_published is None else not vs_published,
                  differing_from_published=vs_published, checksums={p: a[p] for p in sorted(a)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"[reproduce] {len(a)} files compared, identical={not diff}, row counts equal="
          f"{result['row_counts_equal']} -> {out}")
    return result


# Never part of a delivery: environments, caches, OS/editor junk, logs, temp files, runtime state, build output.
PACKAGE_EXCLUDE = (".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
                   ".ipynb_checkpoints", ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.bak",
                   "*.zip", "dist", "runtime", "run_a", "run_b", "inventryx-repro-*")
# Generated, regenerable and large: rebuilt byte-identically by `python run.py generate --profile full`.
PACKAGE_EXCLUDE_PATHS = ("data/full",)


def excluded(rel: Path) -> bool:
    from fnmatch import fnmatch
    if any(rel.as_posix() == p or rel.as_posix().startswith(p + "/") for p in PACKAGE_EXCLUDE_PATHS):
        return True
    return any(fnmatch(part, pat) for part in rel.parts for pat in PACKAGE_EXCLUDE)


def package(out: Path, root_name: str = "Inventryx"):
    """Zip the delivery: source, docs, tests, launchers, starter dataset and reports - nothing else."""
    import zipfile
    out = out.resolve()
    if ROOT in out.parents:
        raise SystemExit(f"[package] write the zip outside the project folder (not {out}) so it never ends up "
                         f"inside its own delivery; the default is {ROOT.parent / 'Inventryx.zip'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    count, skipped = 0, 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if not p.is_file():
                continue
            if excluded(rel):
                skipped += 1
                continue
            z.write(p, Path(root_name) / rel)
            count += 1
    print(f"[package] {count} files -> {out} ({out.stat().st_size / 1e6:.1f} MB); {skipped} files excluded "
          f"(environments, caches, logs, temp files, runtime state, data/full)")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]          # bare `python -m inventryx` starts the web app
    p = argparse.ArgumentParser(prog="python -m inventryx", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "reproduce"):
        s = sub.add_parser(name)
        s.add_argument("--profile", choices=sorted(C.PROFILES), default="starter")
        s.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
        s.add_argument("--out", type=Path)
        for k in ("warehouses", "locations", "skus", "order_lines"):
            s.add_argument(f"--{k.replace('_', '-')}", type=int, dest=k)
    v = sub.add_parser("validate")
    v.add_argument("--data", type=Path, required=True)
    sub.add_parser("docs")
    pk = sub.add_parser("package", help="zip the project for submission (no .venv, caches or data/full)")
    pk.add_argument("--out", type=Path, default=ROOT.parent / "Inventryx.zip",
                    help="zip path, outside the project folder (default: next to it)")
    pk.add_argument("--root-name", default="Inventryx", help="top-level folder name inside the zip")
    w = sub.add_parser("serve", help="run the web app over a generated dataset")
    w.add_argument("--data", type=Path, default=ROOT / "data" / "full")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--open", action="store_true", help="open the browser when the app is ready")
    w.add_argument("--state-dir", type=Path, default=None,
                   help="where the append-only proposal log is kept (default: <data>/../runtime)")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve

        def prepare(state):
            if (args.data / "manifest.json").exists():
                return
            profile = args.data.name if args.data.name in C.PROFILES else "starter"
            state["status"] = (f"First run: generating the '{profile}' dataset in {args.data} "
                               f"(about {'a minute' if profile == 'full' else '10 seconds'})...")
            print(f"[serve] no dataset at {args.data}; generating profile '{profile}' first", flush=True)
            validation, _ = generate(C.PROFILES[profile], C.DEFAULT_SEED, args.data, argv,
                                     log=lambda *a: print(*a, flush=True), hint=False)
            if validation["failed"]:
                raise RuntimeError(f"generated dataset failed {validation['failed']} validation checks")

        serve(args.data, args.host, args.port, args.state_dir, prepare=prepare, open_browser=args.open)
        return 0
    if args.cmd == "package":
        package(args.out, args.root_name)
        return 0
    if args.cmd == "docs":
        write_docs(ROOT)
        print("docs/data_dictionary.md and docs/erd.md regenerated")
        return 0
    if args.cmd == "validate":
        result, _, _ = validate(args.data)
        report.write_validation(args.data, result)
        print(f"{result['passed']}/{result['total']} checks passed")
        return 0 if result["failed"] == 0 else 1
    scale = C.resolve_scale(args.profile, warehouses=args.warehouses, locations=args.locations, skus=args.skus,
                            order_lines=args.order_lines)
    if args.cmd == "generate":
        validation, _ = generate(scale, args.seed, args.out or ROOT / "data" / scale.name, argv)
        return 0 if validation["failed"] == 0 else 1
    result = reproduce(scale, args.seed, args.out or ROOT / "reports" / f"reproducibility_{scale.name}.json", argv)
    return 0 if result["identical"] else 1
