"""Module-level capability gating using discovered controller op set."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CapabilityGate:
    available: set[tuple[str, str]] = field(default_factory=set)

    def satisfied(self, required: tuple[tuple[str, str], ...]) -> bool:
        return all(req in self.available for req in required)

    def missing(self, required: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        return [req for req in required if req not in self.available]
