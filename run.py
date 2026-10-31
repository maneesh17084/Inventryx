"""One-click launcher for Inventryx.

    python run.py                 start the web app on data/full and open the browser
    python run.py --starter       same, on the smaller bundled starter dataset
    python run.py <command> ...   any CLI command, e.g.  python run.py generate --profile full

Works from any folder, from VS Code's Run button, and via Inventryx.bat. If port 8000 is busy it reuses an
Inventryx server already running there, otherwise it picks the next free port.
"""
import socket
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 10):
    sys.exit(f"Inventryx needs Python 3.10 or newer; this is {sys.version.split()[0]}.")

from inventryx.cli import main  # noqa: E402


def _inventryx_at(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
            return r.headers.get("Server", "").startswith("Inventryx")
    except urllib.error.HTTPError as e:          # 503 "starting" page still identifies itself
        return e.headers.get("Server", "").startswith("Inventryx")
    except OSError:
        return False


def _port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def launch(dataset):
    for port in range(8000, 8011):
        if _inventryx_at(port):
            print(f"Inventryx is already running at http://127.0.0.1:{port} - opening it.")
            webbrowser.open(f"http://127.0.0.1:{port}")
            return 0
        if _port_free(port):
            if port != 8000:
                print(f"Port 8000 is in use by another program; using {port}.")
            return main(["serve", "--data", str(ROOT / "data" / dataset), "--port", str(port), "--open"])
    sys.exit("No free port between 8000 and 8010; pass one explicitly: python run.py serve --port 9000")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args == ["--full"]:
        sys.exit(launch("full"))
    if args == ["--starter"]:
        sys.exit(launch("starter"))
    sys.exit(main(args))
