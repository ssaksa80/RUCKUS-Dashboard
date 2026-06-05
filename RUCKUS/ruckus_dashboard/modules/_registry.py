"""Registers all 18 module shells with stub fetchers."""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

_DEFS = [
    # ─── Wireless ───────────────────────────────────────────────
    ("overview",      "DSO Overview",        "Wireless",      "📡", 15, ()),
    ("zones",         "Zones",               "Wireless",      "🏢", 60,
        (("GET", "/rkszones"),)),
    ("aps",           "Access Points",       "Wireless",      "📶", 30,
        (("POST", "/query/ap"),)),
    ("wlans",         "WLANs",               "Wireless",      "🌐", 60,
        (("POST", "/query/wlan"),)),
    ("clients",       "Wireless Clients",    "Wireless",      "👥", 20,
        (("POST", "/query/client"),)),
    ("alarms",        "Alarms & Events",     "Wireless",      "🚨", 10,
        (("POST", "/alert/alarmSummary"),)),
    ("rogues",        "Rogues",              "Wireless",      "👻", 60,
        (("POST", "/query/roguesInfoList"),)),
    ("controller",    "Controller",          "Wireless",      "🎛️", 120,
        (("GET", "/cluster/state"),)),
    # ─── Switching ──────────────────────────────────────────────
    ("switches",      "Switches",            "Switching",     "🔌", 60,
        (("POST", "/switch/view/details"),)),
    ("switch-groups", "Switch Groups",       "Switching",     "🗂️", 120, ()),
    ("ports",         "Ports",               "Switching",     "🔗", 30,
        (("POST", "/switch/ports/summary"),)),
    ("traffic",       "Traffic",             "Switching",     "📊", 30,
        (("POST", "/traffic/top/usage"),)),
    ("poe",           "PoE",                 "Switching",     "⚡", 60,
        (("POST", "/traffic/top/poeutilization"),)),
    ("stack",         "Stack",               "Switching",     "🏗️", 60, ()),
    ("vlans",         "VLANs",               "Switching",     "🏷️", 60, ()),
    # ─── Cross-cutting ──────────────────────────────────────────
    ("firmware",      "Firmware",            "Cross-cutting", "💾", 120, ()),
    ("security",      "Security",            "Cross-cutting", "🔒", 600, ()),
    ("api-explorer",  "API Explorer",        "Cross-cutting", "🧭", 600, ()),
]

for slug, title, group, icon, poll, caps in _DEFS:
    register(ModuleSpec(
        slug=slug, title=title, group=group, icon=icon, poll_seconds=poll,
        fetcher=stub_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=stub_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=caps,
        supports_views=("table",),
    ))
