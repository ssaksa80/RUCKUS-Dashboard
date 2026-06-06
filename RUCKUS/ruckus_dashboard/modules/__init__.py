"""Module registry. Built modules call register() at import time."""
from ._base import ModuleSpec

MODULES: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> ModuleSpec:
    # Override semantics: a real module file later in import order replaces
    # its earlier stub registration.
    MODULES[spec.slug] = spec
    return spec


def all_modules() -> list[ModuleSpec]:
    return sorted(MODULES.values(), key=lambda m: (m.group, m.title))


# Stubs first (covers all 18 slugs initially)
from . import _registry  # noqa: F401,E402

# Real modules below — each subsequent import overrides its stub.
# (Plan 2b Tasks 2-9 will append entries here)
from . import aps  # noqa: F401,E402
from . import zones  # noqa: F401,E402
