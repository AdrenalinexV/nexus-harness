"""Frozen entry point: what `NexusHarness.exe`(engine) runs.

PyInstaller needs a script, not a package. This file exists only for that, and it keeps the CLI
behaviour identical to `python -m nexus_harness`.
"""
import multiprocessing
import sys

from nexus_harness.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
