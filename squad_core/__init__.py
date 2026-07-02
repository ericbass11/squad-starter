"""squad_core — engine reutilizável de orquestração de squad (padrão Eric)."""
from .types import Handoff, RunState, Source, Status, TransientAgentError
from .orchestrator import AgentError, Orchestrator
from .manifest import load_manifest
from .guardrails import GuardrailError
from .llm import LLMClient, LLMConfigError, LLMResult

__all__ = [
    "Handoff", "RunState", "Source", "Status",
    "Orchestrator", "load_manifest",
    "AgentError", "GuardrailError", "TransientAgentError",
    "LLMClient", "LLMConfigError", "LLMResult",
]
