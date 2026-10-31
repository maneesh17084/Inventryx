"""The delivery zip must contain the project and nothing else."""
from pathlib import Path

import pytest

from inventryx.cli import ROOT, excluded, package


@pytest.mark.parametrize("rel", [
    ".venv/Lib/site.py", "venv/x.py", "inventryx/__pycache__/cli.cpython-313.pyc", ".pytest_cache/v/x",
    ".ruff_cache/x", ".mypy_cache/x", "nb/.ipynb_checkpoints/a.ipynb", "inventryx/old.pyc", "inventryx/old.pyo",
    "docs/.DS_Store", "docs/Thumbs.db", "server.log", "notes.tmp", "README.md.bak", "dist/inventryx.zip",
    "Inventryx.zip", "data/runtime/proposals.jsonl", "data/full/csv/sku.csv", "x/run_a/manifest.json",
])
def test_junk_is_excluded(rel):
    assert excluded(Path(rel))


@pytest.mark.parametrize("rel", [
    "README.md", "run.py", "Inventryx.bat", "inventryx/cli.py", "inventryx/web/app.js", "tests/test_rules.py",
    "docs/erd.md", "data/starter/csv/sku.csv", "data/starter/reports/report.html",
    "reports/reproducibility_full.json", ".vscode/launch.json", "data/fullness/x.csv",
])
def test_deliverables_are_kept(rel):
    assert not excluded(Path(rel))


def test_refuses_to_write_the_zip_inside_the_project():
    with pytest.raises(SystemExit):
        package(ROOT / "dist" / "inventryx.zip")
