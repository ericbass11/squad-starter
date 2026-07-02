"""
Core types and handoff contract for the squad engine.

The Handoff is the validated payload that every worker returns to the PMO.
Nothing flows between agents as free text — it is always a typed Handoff.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Literal


class Status(str, Enum):
    OK = "ok"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


class TransientAgentError(Exception):
    """A recoverable failure (rate limit, timeout, 5xx). The orchestrator
    retries the dispatch with backoff instead of failing the run."""


# Source citation discipline: every assertion is one of these.
SourceType = Literal["fato", "inferencia", "nao_consta"]


@dataclass
class Source:
    claim: str
    source: str
    type: SourceType  # fato | inferencia | nao_consta


@dataclass
class Handoff:
    """Typed payload returned by a worker to the PMO. Never free text."""
    agent: str
    status: Status
    findings: list[dict[str, Any]] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    confidence: float = 0.0
    cost_usd: float = 0.0  # spend of this dispatch; the orchestrator sums per run

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class RunState:
    """Single source of truth for one execution. Persisted at every step."""
    squad: str
    run_id: str
    task: dict[str, Any]
    step: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    status: str = "idle"  # idle | running | completed | escalated | failed
    cost_usd: float = 0.0  # accumulated across dispatches; fence 2 enforces the cap
