"""
Example agents for the credit squad.

These are STUBS that respect the Handoff contract — they show the shape of a real
agent (typed output, sources with fato/inferencia/nao_consta, confidence, cost)
without calling a real LLM. Replace the bodies with real SQL/RAG/LLM calls; the
engine, fences and guardrails stay the same.

Real LLM pattern (via gateway — configure .env):

    from squad_core import LLMClient
    llm = LLMClient()   # lê LITELLM_BASE_URL / LITELLM_VIRTUAL_KEY do ambiente
    res = llm.complete("Analise o cedente X...", system="Você é analista...",
                       tier="powerful")
    return Handoff(..., findings=[...], cost_usd=res.cost_usd)

Domain vetos live HERE (the engine only ships assercao_sem_fonte): export a
VETOS dict {nome: fn(handoff) -> bool} and reference the names in squad.yaml.
"""
from __future__ import annotations

from squad_core import Handoff, RunState, Source, Status

_PAYMENT_SIGNALS = ("direto", "repasse", "recompra", "n/a")


def _veto_payment_signal(handoff: Handoff) -> bool:
    """repasse e recompra são idênticos no extrato e dizem o oposto sobre o
    sacado — um payment_signal fora do vocabulário fechado bloqueia o handoff."""
    for f in handoff.findings:
        if isinstance(f, dict) and "payment_signal" in f \
           and f["payment_signal"] not in _PAYMENT_SIGNALS:
            return True
    return False


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

VETOS = {
    "payment_signal_indefinido": _veto_payment_signal,
}
