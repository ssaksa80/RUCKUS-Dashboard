"""Registers cross-cutting module shells with stub fetchers.

Wireless modules (overview, zones, aps, wlans, clients, alarms, rogues,
controller) and switching modules (switches, switch-groups, ports, traffic,
poe, stack, vlans) are real implementations registered by their own module
files in ``__init__.py`` — they are no longer stubbed here.

Plan 2d will promote the remaining 3 stubs to real implementations.
"""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

_DEFS = [
    # (slug, title, group, icon, poll, caps, warmup)
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
