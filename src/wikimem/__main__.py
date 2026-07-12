"""``python -m wikimem`` — same entrypoint as the ``wikimem`` console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
