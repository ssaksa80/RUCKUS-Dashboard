"""Registers switching + cross-cutting module shells with stub fetchers.

Wireless modules (overview, zones, aps, wlans, clients, alarms, rogues,
controller) are real implementations registered by their own module files
in ``__init__.py`` — they are no longer stubbed here.

Plans 2c/2d will promote the remaining 10 stubs to real implementations.
"""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

_DEFS = [
    # (slug, title, group, icon, poll, caps, warmup)
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
