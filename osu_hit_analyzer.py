#!/usr/bin/env python3
"""Command-line version of osu! Hit Analyzer (see osu_analyzer/cli.py)."""

import sys

from osu_analyzer import __version__  # noqa: F401  (read by the release workflow)
from osu_analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
