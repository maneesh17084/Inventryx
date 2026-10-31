"""Vercel entry point: serves the whole Inventryx app (pages, static files, JSON API) as one Python function.

vercel.json rewrites every URL to /api/index?__path=/<original path>; the handler restores the original path
and delegates to the same request handler the local server uses. Vercel's filesystem is read-only, so the
bundled starter dataset is served and interactive proposals are kept in the temp folder (/tmp on
Vercel) - per instance, NOT durable; the UI says so.
"""
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventryx.server import Store, make_handler  # noqa: E402

_store = Store(ROOT / "data" / "starter", state_dir=Path(tempfile.gettempdir()) / "inventryx-state", ephemeral_state=True)
_Base = make_handler(_store)


class handler(_Base):  # noqa: N801 - Vercel's Python runtime looks for a class named `handler`
    def _restore_path(self):
        parts = urlsplit(self.path)
        if parts.path.rstrip("/") != "/api/index":
            return
        query = parse_qsl(parts.query, keep_blank_values=True)
        original = next((v for k, v in query if k == "__path"), "/") or "/"
        rest = urlencode([(k, v) for k, v in query if k != "__path"])
        self.path = ("/" + original.lstrip("/")) + (f"?{rest}" if rest else "")

    def do_GET(self):
        self._restore_path()
        super().do_GET()

    def do_POST(self):
        self._restore_path()
        super().do_POST()
