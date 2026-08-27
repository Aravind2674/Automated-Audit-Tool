"""
Abstract collector interface. Every collector implements this and nothing more.

The hard boundary this file exists to enforce: a collector gathers raw
provider-specific state and returns it verbatim. It does not decide whether that
state is compliant, does not compare against a control's expectations, and does not
know that controls exist. Interpretation belongs to the normalizer and evaluator.

Keeping that line clean is what makes a second collector type (AWS, Phase 5) a matter
of writing one new class rather than threading provider branches through the engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CollectorError(Exception):
    """Raised when a collector cannot reach or authenticate to its target at all.

    This is distinct from an individual command failing on a reachable target: a
    command that returns a non-zero exit code is legitimate collected evidence and is
    returned in the raw doc, not raised. Only a failure that prevents collection
    entirely -- unreachable host, rejected credentials, transport error -- raises.
    """


class Collector(ABC):
    """Base class for all collectors."""

    #: Short identifier for the collector type, e.g. "ssh" or "aws". Used for
    #: provenance in the raw doc and by the normalizer to select a mapping. The
    #: evaluator never sees it (Section 5).
    collector_type: str = "abstract"

    @abstractmethod
    def collect(self, target: dict) -> list[dict]:
        """Returns raw provider-specific state docs. Never touches evaluation logic."""
        ...
