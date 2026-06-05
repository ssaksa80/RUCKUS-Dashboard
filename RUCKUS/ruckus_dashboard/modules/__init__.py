"""Module registry. Built modules call register() at import time."""
from ._base import ModuleSpec

MODULES: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> ModuleSpec:
    if spec.slug in MODULES:
        raise ValueError(f"duplicate module slug: {spec.slug}")
    MODULES[spec.slug] = spec
    return spec


def all_modules() -> list[ModuleSpec]:
    return sorted(MODULES.values(), key=lambda m: (m.group, m.title))
