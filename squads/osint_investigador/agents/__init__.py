"""
Agentes do squad osint-investigador. Stubs com guia — troque os corpos por lógica real.
O motor (cercas, guardrails, checkpoint) NÃO muda; só estes corpos mudam.
"""
from __future__ import annotations

from squad_core import Handoff, RunState, Source, Status


def ag1(state: RunState) -> Handoff:
    """Coleta em fontes públicas (Receita, judiciário)

    GUIA: troque o corpo por chamada real (SQL / RAG / API / LLM).
    - Toda asserção precisa de Source com type fato | inferencia | nao_consta.
    - Só acesse as fontes declaradas no roster (ReceitaFederal, Judiciario),
      senão o blast_radius bloqueia.
    - Defina confidence honestamente (0.0–1.0).
    """
    # exemplo (REMOVA ao implementar):
    return Handoff(
        agent="AG1",
        status=Status.OK,
        findings=[{"dimension": "ag1", "exemplo": True}],
        sources=[
            Source(claim="descreva o achado", source="ReceitaFederal", type="fato"),
        ],
        confidence=0.7,
    )


def ag2(state: RunState) -> Handoff:
    """Grafo de entidades e relacionamentos (Neo4j)

    GUIA: troque o corpo por chamada real (SQL / RAG / API / LLM).
    - Toda asserção precisa de Source com type fato | inferencia | nao_consta.
    - Só acesse as fontes declaradas no roster (Neo4j, SQL),
      senão o blast_radius bloqueia.
    - Defina confidence honestamente (0.0–1.0).
    """
    # exemplo (REMOVA ao implementar):
    return Handoff(
        agent="AG2",
        status=Status.OK,
        findings=[{"dimension": "ag2", "exemplo": True}],
        sources=[
            Source(claim="descreva o achado", source="Neo4j", type="fato"),
        ],
        confidence=0.7,
    )


def ag3(state: RunState) -> Handoff:
    """Sinais de risco e red flags

    GUIA: troque o corpo por chamada real (SQL / RAG / API / LLM).
    - Toda asserção precisa de Source com type fato | inferencia | nao_consta.
    - Só acesse as fontes declaradas no roster (Serasa, SCR),
      senão o blast_radius bloqueia.
    - Defina confidence honestamente (0.0–1.0).
    """
    # exemplo (REMOVA ao implementar):
    return Handoff(
        agent="AG3",
        status=Status.OK,
        findings=[{"dimension": "ag3", "exemplo": True}],
        sources=[
            Source(claim="descreva o achado", source="Serasa", type="fato"),
        ],
        confidence=0.7,
    )


def qa(state: RunState) -> Handoff:
    """QA Reviewer — consolida e dá PASS/FAIL. Não cita fonte de dado (é revisor).

    GUIA: defina aqui os critérios de qualidade e o veredito do SEU domínio.
    Se reprovar, retorne status NEEDS_HUMAN para acionar o on_reject (com teto).
    """
    confidences = [h["handoff"]["confidence"] for h in state.history if h.get("handoff")]
    avg = sum(confidences) / len(confidences) if confidences else 0.0
    if avg < 0.6:
        return Handoff(agent="QA", status=Status.NEEDS_HUMAN,
                       findings=[{"verdict": "REJECT", "avg_confidence": round(avg, 2)}],
                       confidence=avg)
    return Handoff(agent="QA", status=Status.OK,
                   findings=[{"verdict": "PASS", "avg_confidence": round(avg, 2),
                              "razoes": ["preencha"], "precedentes": ["preencha"]}],
                   sources=[], confidence=avg)


REGISTRY = {
    "AG1": ag1,
    "AG2": ag2,
    "AG3": ag3,
    "QA": qa,
}
