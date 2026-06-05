"""RUCKUS NOC Assurance Dashboard package."""
from importlib.metadata import PackageNotFoundError, version as _pkg_version

APP_NAME = "RUCKUS NOC Assurance Dashboard"
try:
    APP_VERSION = _pkg_version("ruckus_dashboard")
except PackageNotFoundError:
    # Source-tree fallback when package not installed (dev / CI before pip install -e)
    APP_VERSION = "2.0.0.dev0"

def main(argv=None):
    """Entry point - full implementation lands in cli.py."""
    from .cli import main as _main
    return _main(argv)
