from __future__ import annotations

import os
import sys


def run_cli() -> None:
    """Entry point for the `app` command (wraps the Litestar CLI).

    Examples: `app run --reload`, `app database upgrade`, `app seed`, `app users create`.
    """
    os.environ.setdefault("LITESTAR_APP", "app.server.asgi:create_app")
    try:
        from litestar.cli.main import litestar_group
    except ImportError as exc:
        print("Could not load required libraries. Is the virtual environment active?", exc)  # noqa: T201
        sys.exit(1)
    litestar_group()


if __name__ == "__main__":
    run_cli()
