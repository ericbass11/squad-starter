"""squad_core — engine reutilizável de orquestração de squad (padrão Eric)."""
from .types import Handoff, RunState, Source, Status
from .orchestrator import Orchestrator
from .manifest import load_manifest
from .guardrails import GuardrailError

__all__ = [
    "Handoff", "RunState", "Source", "Status",
    "Orchestrator", "load_manifest", "GuardrailError",
]
