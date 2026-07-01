"""Node-run behavioural tests for the topology renderer's pure functions.

topology.js is a browser script; Task 2 adds a guarded CommonJS export so the
pure layout/encoding helpers can be required and exercised under Node. These
tests skip (not fail) where node is unavailable so the suite stays green on
machines without a JS runtime; CI runners (ubuntu/windows) ship node."""
import json
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path("RUCKUS/ruckus_dashboard/static/topology.js").resolve()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(snippet: str) -> dict:
    """Execute a JS snippet that requires topology.js and prints JSON to stdout."""
    prog = (
        f"const T = require({json.dumps(str(JS))});\n"
        f"{snippet}\n"
    )
    out = subprocess.run([NODE, "-e", prog], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_topology_js_requires_under_node():
    got = _run('console.log(JSON.stringify(Object.keys(T).sort()));')
    assert "fmtRate" in got


def test_health_weight_monotonic_in_severity():
    got = _run(
        "const off={status:'offline',meta:{}};"
        "const fl={status:'flagged',meta:{}};"
        "const on={status:'online',meta:{}};"
        "const un={status:'unknown',meta:{}};"
        "console.log(JSON.stringify("
        "[T.healthWeight(off),T.healthWeight(fl),T.healthWeight(on),T.healthWeight(un)]));"
    )
    off, fl, on, un = got
    assert off >= fl >= on >= un
    assert 0.0 <= un and off <= 1.0


def test_health_weight_scales_with_down_aps_and_alarms():
    got = _run(
        "const few={status:'flagged',meta:{ap_total:10,ap_down:1,alarm_count:0}};"
        "const many={status:'flagged',meta:{ap_total:10,ap_down:9,alarm_count:3}};"
        "console.log(JSON.stringify([T.healthWeight(few),T.healthWeight(many)]));"
    )
    few, many = got
    assert many > few


def test_health_weight_never_nan():
    got = _run(
        "const n={status:'offline',meta:{ap_total:0,ap_down:0}};"
        "console.log(JSON.stringify(isFinite(T.healthWeight(n))));"
    )
    assert got is True
