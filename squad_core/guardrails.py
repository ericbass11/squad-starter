"""
Guardrails (hooks) applied at every transition. Padrão Megazord.

These are the deterministic constraints — the tool IS the constraint, so the
SQUAD.md does not restate them in prose. Three guards:
  1. secret_scan      — no secret escapes into a handoff/log
  2. blast_radius     — an agent only touches sources it declares
  3. output_guardrail — block assertions without source; force the citation
                        discipline (fato | inferencia | nao_consta)
"""
from __future__ import annotations

import re

from .types import Handoff, Status

# Minimal secret patterns — extend per environment. Never log the match itself.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),          # generic API key
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),             # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),   # GitHub tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


class GuardrailError(Exception):
    """Raised when a guardrail blocks a transition. Never silent."""


def secret_scan(text: str) -> None:
    for pat in _SECRET_PATTERNS:
        if pat.search(text or ""):
            # Do not include the matched value in the message.
            raise GuardrailError("secret_scan: possível segredo detectado na saída")


def blast_radius(agent_name: str, requested_sources: set[str],
                 allowed: dict[str, set[str]]) -> None:
    permitted = allowed.get(agent_name, set())
    over = requested_sources - permitted
    if over:
        raise GuardrailError(
            f"blast_radius: {agent_name} tentou acessar fontes não permitidas: {sorted(over)}"
        )


def output_guardrail(handoff: Handoff, blocked_if: list[str],
                     is_reviewer: bool = False,
                     rating_scale: list[str] | None = None) -> None:
    """Enforce source-citation discipline and domain veto flags.

    Reviewer agents (QA) consolidate upstream findings and do not cite data
    sources themselves — they are exempt from the 'needs a source' rule, but
    still subject to the domain veto flags below.
    """
    # Every finding-bearing assertion needs a source — unless it's a reviewer.
    if not is_reviewer and handoff.findings and not handoff.sources:
        raise GuardrailError("output_guardrail: assercao_sem_fonte")

    for s in handoff.sources:
        if s.type not in ("fato", "inferencia", "nao_consta"):
            raise GuardrailError(f"output_guardrail: tipo de fonte inválido: {s.type}")

    # A rating outside the declared scale never leaves the squad.
    if rating_scale:
        for f in handoff.findings:
            rating = f.get("rating") if isinstance(f, dict) else None
            if rating is not None and rating not in rating_scale:
                raise GuardrailError(
                    f"output_guardrail: rating '{rating}' fora da escala {rating_scale}")

    # Credit example: a rating must carry confidence + reasons + precedents.
    needs_rating_pack = any(
        b in blocked_if for b in
        ("rating_sem_confianca", "rating_sem_razoes", "rating_sem_precedentes")
    )
    if needs_rating_pack and handoff.status == Status.OK:
        flat = " ".join(str(f) for f in handoff.findings).lower()
        if "rating" in flat:
            if "rating_sem_confianca" in blocked_if and handoff.confidence <= 0:
                raise GuardrailError("output_guardrail: rating_sem_confianca")
            if "rating_sem_razoes" in blocked_if and "razoes" not in flat:
                raise GuardrailError("output_guardrail: rating_sem_razoes")
            if "rating_sem_precedentes" in blocked_if and "precedentes" not in flat:
                raise GuardrailError("output_guardrail: rating_sem_precedentes")
