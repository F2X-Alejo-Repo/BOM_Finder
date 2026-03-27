"""Console entry point for bom_workbench."""

from __future__ import annotations

import sys
from typing import Sequence

from .app import bootstrap


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application bootstrap and return a process exit code."""
    return bootstrap(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
