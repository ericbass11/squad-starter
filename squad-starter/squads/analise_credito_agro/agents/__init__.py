"""
Example agents for the credit squad.

These are STUBS that respect the Handoff contract — they show the shape of a real
agent (typed output, sources with fato/inferencia/nao_consta, confidence) without
calling a real LLM. Replace the bodies with real SQL/RAG/LLM calls; the engine,
fences and guardrails stay the same.
"""
from __future__ import annotations

from squad_core import Handoff, RunState, Source, Status


def ag1_cedente(state: RunState) -> Handoff:
    """Cedente & sinais de queda. Distinguishes the payment signal."""
    sacado = state.task.get("sacado", "desconhecido")
    return Handoff(
        agent="AG1",
        status=Status.OK,
        findings=[
            {"dimension": "cedente", "sacado": sacado, "payment_signal": "repasse"},
        ],
        sources=[
            Source(claim="faturamento estável na safra", source="SQL", type="fato"),
            Source(claim="histórico de bom pagador", source="Bitrix24", type="inferencia"),
        ],
        confidence=0.72,
    )


def ag4_endividamento(state: RunState) -> Handoff:
    """Endividamento x faturamento & nicho."""
    return Handoff(
        agent="AG4",
        status=Status.OK,
        findings=[{"dimension": "endividamento_faturamento", "ratio": 0.38}],
        sources=[
            Source(claim="dívida/faturamento = 0.38", source="SCR", type="fato"),
            Source(claim="prazo da dívida compatível com a safra", source="SQL", type="inferencia"),
        ],
        confidence=0.80,
    )


def qa_review(state: RunState) -> Handoff:
    """QA Reviewer — PASS if upstream confidence holds, else asks for rework."""
    confidences = [
        h["handoff"]["confidence"]
        for h in state.history
        if h.get("handoff")
    ]
    avg = sum(confidences) / len(confidences) if confidences else 0.0
    if avg < 0.6:
        return Handoff(agent="QA", status=Status.NEEDS_HUMAN,
                       findings=[{"verdict": "REJECT", "avg_confidence": round(avg, 2)}],
                       confidence=avg)
    return Handoff(
        agent="QA",
        status=Status.OK,
        findings=[{"verdict": "PASS", "rating": "B", "avg_confidence": round(avg, 2),
                   "razoes": ["endividamento saudável", "pagador repasse"],
                   "precedentes": ["perfis B aprovados performaram adimplentes em 2024-25"]}],
        sources=[],  # QA revisa o trabalho dos agentes; não consulta fontes de dado
        confidence=avg,
    )


REGISTRY = {
    "AG1": ag1_cedente,
    "AG4": ag4_endividamento,
    "QA": qa_review,
}
