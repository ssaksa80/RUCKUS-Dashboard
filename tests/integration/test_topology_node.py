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


def test_render_node_markup_carries_glow_style():
    # nodeGlowStyle(n) returns the inline style string applied to each node <g>.
    got = _run(
        "const off={id:'z1',status:'offline',type:'zone',meta:{ap_total:4,ap_down:4}};"
        "const on={id:'z2',status:'online',type:'zone',meta:{ap_total:4,ap_down:0}};"
        "const so=T.nodeGlowStyle(off), sn=T.nodeGlowStyle(on);"
        "console.log(JSON.stringify({so, sn, hasVar: so.indexOf('--glow')>=0}));"
    )
    assert got["hasVar"] is True
    # offline node must request a stronger glow than the online one
    import re
    fo = float(re.search(r"--glow:\s*([0-9.]+)", got["so"]).group(1))
    fn = float(re.search(r"--glow:\s*([0-9.]+)", got["sn"]).group(1))
    assert fo > fn


def test_ribbon_counts_tallies_status_and_alarms():
    got = _run(
        "const nodes=["
        "{id:'a',status:'online',meta:{}},"
        "{id:'b',status:'offline',meta:{}},"
        "{id:'c',status:'flagged',meta:{alarm_count:2}},"
        "{id:'d',status:'online',meta:{alarm_count:1}}];"
        "console.log(JSON.stringify(T.ribbonCounts(nodes)));"
    )
    assert got == {"online": 2, "flagged": 1, "offline": 1, "alarms": 3, "total": 4}


def test_filter_problems_only_keeps_problem_paths_drops_green():
    got = _run(
        "const nodes=["
        "{id:'controller',type:'controller',status:'online',meta:{}},"
        "{id:'zBad',type:'zone',status:'flagged',meta:{}},"
        "{id:'apBad',type:'ap',status:'offline',meta:{}},"
        "{id:'zGood',type:'zone',status:'online',meta:{}},"
        "{id:'apGood',type:'ap',status:'online',meta:{}}];"
        "const edges=["
        "{source:'controller',target:'zBad',status:'flagged'},"
        "{source:'zBad',target:'apBad',status:'offline'},"
        "{source:'controller',target:'zGood',status:'online'},"
        "{source:'zGood',target:'apGood',status:'online'}];"
        "const r=T.filterProblemsOnly(nodes,edges);"
        "console.log(JSON.stringify({"
        "ids:r.nodes.map(n=>n.id).sort(),"
        "edges:r.edges.map(e=>e.source+'>'+e.target).sort()}));"
    )
    assert got["ids"] == ["apBad", "controller", "zBad"]
    assert got["edges"] == ["controller>zBad", "zBad>apBad"]


def test_filter_problems_only_empty_when_all_green():
    got = _run(
        "const nodes=[{id:'controller',type:'controller',status:'online',meta:{}},"
        "{id:'z',type:'zone',status:'online',meta:{}}];"
        "const edges=[{source:'controller',target:'z',status:'online'}];"
        "const r=T.filterProblemsOnly(nodes,edges);"
        "console.log(JSON.stringify(r.nodes.map(n=>n.id)));"
    )
    assert got == []


def test_layout_layered_columns_finite_and_deterministic():
    snippet = (
        "const nodes=["
        "{id:'controller',type:'controller'},"
        "{id:'z1',type:'zone'},{id:'g1',type:'group'},"
        "{id:'s1',type:'switch'},{id:'a1',type:'ap'},{id:'a2',type:'ap'}];"
        "const edges=["
        "{source:'controller',target:'z1'},{source:'controller',target:'g1'},"
        "{source:'g1',target:'s1'},{source:'z1',target:'a1'},{source:'z1',target:'a2'}];"
        "const p1=T.layoutLayered(nodes,edges);"
        "const p2=T.layoutLayered(nodes,edges);"
        "const xs=Object.values(p1).map(p=>p.x);"
        "const allFinite=Object.values(p1).every(p=>isFinite(p.x)&&isFinite(p.y));"
        "console.log(JSON.stringify({"
        "deterministic:JSON.stringify(p1)===JSON.stringify(p2),"
        "allFinite,"
        "ctrlX:p1.controller.x, z1X:p1.z1.x, s1X:p1.s1.x,"
        "colsAscend:(p1.controller.x<p1.z1.x)&&(p1.z1.x<p1.s1.x)}));"
    )
    got = _run(snippet)
    assert got["deterministic"] is True
    assert got["allFinite"] is True
    assert got["colsAscend"] is True


def test_layout_layered_separates_siblings_vertically():
    got = _run(
        "const nodes=[{id:'controller',type:'controller'},"
        "{id:'z1',type:'zone'},{id:'a1',type:'ap'},{id:'a2',type:'ap'}];"
        "const edges=[{source:'controller',target:'z1'},"
        "{source:'z1',target:'a1'},{source:'z1',target:'a2'}];"
        "const p=T.layoutLayered(nodes,edges);"
        "console.log(JSON.stringify(p.a1.y!==p.a2.y));"
    )
    assert got is True


def test_flow_width_monotonic_and_finite():
    got = _run(
        "const e={source:'g1',target:'s1',status:'online'};"
        "const lo=T.flowWidth(e,{s1:1e6});"      # 1 Mbps
        "const hi=T.flowWidth(e,{s1:1e9});"      # 1 Gbps
        "const none=T.flowWidth(e,{});"          # no rate
        "console.log(JSON.stringify({lo,hi,none,"
        "finite:[lo,hi,none].every(isFinite),mono:hi>lo,floor:none>0}));"
    )
    assert got["finite"] is True
    assert got["mono"] is True
    assert got["floor"] is True


def test_flow_width_never_nan_on_garbage_rate():
    got = _run(
        "const e={source:'g1',target:'s1'};"
        "console.log(JSON.stringify(isFinite(T.flowWidth(e,{s1:NaN}))));"
    )
    assert got is True


def test_render_flow_emits_svg_with_finite_ribbon_widths():
    snippet = (
        "const data={nodes:["
        "{id:'controller',type:'controller',status:'online',label:'Ctrl',meta:{}},"
        "{id:'g1',type:'group',status:'online',label:'Core',meta:{}},"
        "{id:'s1',type:'switch',status:'online',label:'SW-1',meta:{}}],"
        "edges:["
        "{source:'controller',target:'g1',status:'online',label:''},"
        "{source:'g1',target:'s1',status:'online',label:'2 MB'}]};"
        "const svg=T.renderFlow(data,{s1:5e6});"
        "const widths=[...svg.matchAll(/stroke-width=\"([0-9.]+)\"/g)].map(m=>parseFloat(m[1]));"
        "console.log(JSON.stringify({"
        "isSvg:svg.indexOf('<svg')===0,"
        "hasRibbon:svg.indexOf('topo-flow-ribbon')>=0,"
        "allFinite:widths.every(isFinite)&&widths.length>0,"
        "escaped:svg.indexOf('Ctrl')>=0}));"
    )
    got = _run(snippet)
    assert got["isSvg"] is True
    assert got["hasRibbon"] is True
    assert got["allFinite"] is True
    assert got["escaped"] is True


def test_render_flow_escapes_node_labels():
    got = _run(
        "const data={nodes:[{id:'x',type:'switch',status:'online',"
        "label:'<script>',meta:{}}],edges:[]};"
        "const svg=T.renderFlow(data,{});"
        "console.log(JSON.stringify({"
        "noRaw:svg.indexOf('<script>')<0, hasEsc:svg.indexOf('&lt;script&gt;')>=0}));"
    )
    assert got["noRaw"] is True
    assert got["hasEsc"] is True
