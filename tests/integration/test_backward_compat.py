import subprocess
import sys


def test_legacy_script_still_runnable():
    """`python RUCKUS/ruckus_dashboard.py --help` must still work."""
    r = subprocess.run(
        [sys.executable, "RUCKUS/ruckus_dashboard.py", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "--bind" in r.stdout


def test_legacy_main_importable():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "ruckus_dashboard_shim",
        pathlib.Path("RUCKUS/ruckus_dashboard.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert mod.APP_NAME == "RUCKUS NOC Assurance Dashboard"
