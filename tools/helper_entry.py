"""Entry point for the PyInstaller build of wt-helper.exe (see .github/workflows/helper.yml)."""

import sys

from wt_analytics.helper.cli import main

if __name__ == "__main__":
    sys.exit(main())
