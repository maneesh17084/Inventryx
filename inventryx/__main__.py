import sys

if __package__ in (None, ""):
    # Run as a file (e.g. VS Code "Run Python File" or `python inventryx/__main__.py`), not via `python -m`.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from inventryx.cli import main
else:
    from .cli import main

sys.exit(main())
