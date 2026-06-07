"""Empty no-op stub registry — all 18 modules are now real.

Every module slug (8 wireless + 7 switching + 3 cross-cutting) now has a
real fetcher file that self-registers via its own import in ``__init__.py``.
No slugs remain stubbed, so ``_DEFS`` is empty.

This module is retained (rather than deleted) so the ``from . import _registry``
line in ``__init__.py`` stays valid and import order is unchanged. The imports
below remain valid and ``_stub`` is still referenced by tests.
"""
from __future__ import annotations
from . import register
from ._base import ModuleSpec
from ._stub import stub_fetcher, stub_summary

# All modules promoted to real implementations — nothing left to stub.
_DEFS: list[tuple] = []

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
