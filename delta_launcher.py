"""Entry point for PyInstaller (delta.spec)."""
import sys

from delta.cli import main

if __name__ == "__main__":
    sys.exit(main())
