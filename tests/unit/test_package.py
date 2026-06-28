import importlib

def test_package_imports():
    pkg = importlib.import_module("ruckus_dashboard")
    assert pkg.APP_NAME == "RUCKUS NOC Assurance Dashboard"
    assert pkg.APP_VERSION

def test_main_entrypoint_exists():
    pkg = importlib.import_module("ruckus_dashboard")
    assert callable(pkg.main)

def test_legacy_shim_still_works():
    # Top-level ruckus_dashboard.py module must still expose main()
    import importlib.util
    import pathlib
    import sys
    shim_path = pathlib.Path("RUCKUS/ruckus_dashboard.py")
    spec = importlib.util.spec_from_file_location("ruckus_dashboard_shim", shim_path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass with `from __future__ import annotations`
    # can resolve string-form annotations via sys.modules lookup.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        assert callable(mod.main)
    finally:
        sys.modules.pop(spec.name, None)
