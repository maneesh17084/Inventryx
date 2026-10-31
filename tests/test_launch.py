"""Every supported way of launching the build must work - not just `python -m inventryx` from the repo root."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run(args, cwd):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("args", [
    ["run.py", "--help"],                       # launcher in the project root
    ["inventryx/cli.py", "--help"],             # VS Code "Run Python File" on the CLI module
    ["inventryx/__main__.py", "--help"],
    ["inventryx/server.py", "--help"],          # Run button on the server module starts `serve`
    ["-m", "inventryx", "--help"],
])
def test_entry_points_from_project_root(args):
    r = run(args, ROOT)
    assert r.returncode == 0, r.stderr
    assert "usage: python -m inventryx" in r.stdout


def test_launcher_works_from_any_folder(tmp_path):
    r = run([str(ROOT / "run.py"), "validate", "--data", str(ROOT / "data" / "starter")], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "checks passed" in r.stdout


def test_server_module_defaults_to_serve():
    r = run(["inventryx/server.py", "--help"], ROOT)
    assert "--open" in r.stdout and "--data" in r.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch launcher")
def test_batch_launcher(tmp_path):
    r = subprocess.run(["cmd", "/c", str(ROOT / "Inventryx.bat"), "--help"], cwd=tmp_path, capture_output=True,
                       text=True, timeout=120)
    assert "usage: python -m inventryx" in r.stdout, r.stdout + r.stderr
