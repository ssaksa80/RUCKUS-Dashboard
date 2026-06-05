#!/usr/bin/env python3
"""Backward-compat shim. Real code lives in the ruckus_dashboard package.

Allows `python RUCKUS/ruckus_dashboard.py` to keep working for users
who hand-launch the script. New entrypoint: `python -m ruckus_dashboard`.
"""
from __future__ import annotations
import sys, pathlib

# Ensure the package directory next to this shim is importable
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ruckus_dashboard import APP_NAME, APP_VERSION  # re-export  # noqa: F401
from ruckus_dashboard.cli import main                # re-export  # noqa: F401

if __name__ == "__main__":
    main()
