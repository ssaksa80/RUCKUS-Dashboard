"""Registers all 18 module shells with stub fetchers."""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

_DEFS = [
    # (slug, title, group, icon, poll, caps, warmup)
    ("overview",      "DSO Overview",        "Wireless",      "📡", 15, (), True),
    ("zones",         "Zones",               "Wireless",      "🏢", 60, (("GET", "/rkszones"),), True),
    ("aps",           "Access Points",       "Wireless",      "📶", 30, (("POST", "/query/ap"),), True),
    ("wlans",         "WLANs",               "Wireless",      "🌐", 60, (("POST", "/query/wlan"),), True),
    ("clients",       "Wireless Clients",    "Wireless",      "👥", 20, (("POST", "/query/client"),), True),
    ("alarms",        "Alarms & Events",     "Wireless",      "🚨", 10, (("POST", "/alert/alarmSummary"),), True),
    ("rogues",        "Rogues",              "Wireless",      "👻", 60, (("POST", "/query/roguesInfoList"),), True),
    ("controller",    "Controller",          "Wireless",      "🎛️", 120, (("GET", "/cluster/state"),), True),
    ("switches",      "Switches",            "Switching",     "🔌", 60, (("POST", "/switch/view/details"),), True),
    ("switch-groups", "Switch Groups",       "Switching",     "🗂️", 120, (), True),
    ("ports",         "Ports",               "Switching",     "🔗", 30, (("POST", "/switch/ports/summary"),), True),
    ("traffic",       "Traffic",             "Switching",     "📊", 30, (("POST", "/traffic/top/usage"),), True),
    ("poe",           "PoE",                 "Switching",     "⚡", 60, (("POST", "/traffic/top/poeutilization"),), True),
    ("stack",         "Stack",               "Switching",     "🏗️", 60, (), True),
    ("vlans",         "VLANs",               "Switching",     "🏷️", 60, (), True),
    ("firmware",      "Firmware",            "Cross-cutting", "💾", 120, (), True),
    ("security",      "Security",            "Cross-cutting", "🔒", 600, (), True),
    ("api-explorer",  "API Explorer",        "Cross-cutting", "🧭", 600, (), False),
]

for slug, title, group, icon, poll, caps, warmup_flag in _DEFS:
    register(ModuleSpec(
        slug=slug, title=title, group=group, icon=icon, poll_seconds=poll,
        fetcher=stub_fetcher, drill_fetcher=None, drill_tabs=(),
        summary_fn=stub_summary,
        requires_platforms=("smartzone",),
        requires_capabilities=caps,
        supports_views=("table",),
        warmup=warmup_flag,
    ))
