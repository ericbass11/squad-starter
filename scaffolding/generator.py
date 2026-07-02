"""
Squad generator core — materializa um squad novo a partir de uma spec.

Compartilhado pelos dois modos: interativo (new_squad.py) e por arquivo
(new_squad.py --from spec.yaml). O esqueleto é SEMPRE o mesmo:
orchestrator-worker + checkpoint humano no fim. O que muda é o miolo.

Garantias do gerador:
  - nome em kebab/snake correto, sem colisão com squad existente
  - SQUAD.md + squad.yaml + agents/__init__.py coerentes entre si
  - em context=audax, governança forçada (human_in_the_loop, audit_trail, source_citation)
  - SEMPRE inclui um checkpoint humano no fim do pipeline e um QA reviewer
  - valida o resultado contra o schema antes de gravar
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

ROOT = Path(__file__).parent.parent
SCHEMA_PATH = ROOT / "schemas" / "squad-schema.json"


@dataclass
class AgentSpec:
    name: str                       # ex.: AG1
    role: str                       # descrição curta
    sources: list[str] = field(default_factory=list)
    model_tier: str = "powerful"    # fast | powerful
    is_reviewer: bool = False


@dataclass
class SquadSpec:
    name: str                       # kebab-case
    description: str
    context: str = "audax"          # audax | externo | pessoal
    profile: str = "agente-ia"
    owner: str = "Eric"
    regulatory: list[str] = field(default_factory=lambda: ["BACEN", "CMN", "LGPD"])
    max_iterations: int = 12
    max_execution_seconds: int = 90
    max_cost_per_run_usd: float | None = 0.80
    qa_reflection_rounds_max: int = 2
    output_blocked_if: list[str] = field(default_factory=lambda: ["assercao_sem_fonte"])
    agents: list[AgentSpec] = field(default_factory=list)
    # nomes em snake para a pasta/módulo
    @property
    def module(self) -> str:
        return self.name.replace("-", "_")


# ---------- validação de entrada ----------

def _slug_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]{2,50}", name))


def validate_spec(spec: SquadSpec) -> list[str]:
    errs = []
    if not _slug_ok(spec.name):
        errs.append("name deve ser kebab-case (a-z, 0-9, hífen), 2–50 chars")
    if spec.profile not in ("app-web", "agente-ia", "hibrido"):
        errs.append("profile inválido")
    if spec.context not in ("audax", "externo", "pessoal"):
        errs.append("context inválido")
    if not spec.agents:
        errs.append("defina ao menos 1 agente de trabalho")
    if (ROOT / "squads" / spec.module).exists():
        errs.append(f"já existe um squad '{spec.name}' em squads/{spec.module}")
    return errs


# ---------- geração dos artefatos ----------

def _frontmatter(spec: SquadSpec) -> dict:
    fm = {
        "name": spec.name,
        "version": "0.1.0",
        "description": spec.description,
        "owner": spec.owner,
        "profile": spec.profile,
        "context": spec.context,
        "topology": "orchestrator-worker",
        "orchestrator": "PMO",
        "depends_on": [],
        "max_iterations": spec.max_iterations,
        "max_execution_seconds": spec.max_execution_seconds,
        "max_cost_per_run_usd": spec.max_cost_per_run_usd,
        "stop_on_no_progress": True,
        "qa_reflection_rounds_max": spec.qa_reflection_rounds_max,
        "human_in_the_loop": True,
        "source_citation": "required",
        "output_blocked_if": spec.output_blocked_if,
        "state_per_step": True,
        "archive_run_state": True,
        "output_versioning": True,
    }
    if spec.context == "audax":
        fm["regulatory"] = spec.regulatory
        fm["audit_trail"] = "immutable"
    else:
        fm["audit_trail"] = True
    return fm


def _squad_md(spec: SquadSpec) -> str:
    fm = yaml.safe_dump(_frontmatter(spec), sort_keys=False, allow_unicode=True)
    roster_rows = "\n".join(
        f"| {a.name} | {a.role} | {', '.join(a.sources) or '—'} | {a.model_tier} |"
        for a in spec.agents
    )
    return f"""---
{fm}---

# Squad: {spec.name} — Manifesto

> Contrato declarativo de como os agentes se coordenam. Orchestrator-worker:
> o PMO decide; workers não conversam entre si. Checkpoint humano obrigatório.

## 1. Objetivo e término

**Entrega:** {spec.description}

**Termina quando:** [escreva a condição ANTES do happy path — ex.: recomendação
emitida com os campos obrigatórios; "nao_consta" registrado para o que não se verificou].

**Não faz:** decidir sozinho onde há accountability humana.

## 2. Roster

| Agente | Papel | Fontes | model_tier |
|---|---|---|---|
{roster_rows}
| QA | Revisa saída dos agentes; PASS/FAIL com motivo (máx. {spec.qa_reflection_rounds_max} rodadas) | — | powerful |

Workers devolvem ao PMO — não falam entre si. Acesso a dado via gateway, nunca banco direto.

## 3. Checkpoints humanos

- [ ] Aprovação do design antes da 1ª execução
- [ ] Antes de a saída virar decisão/recomendação oficial (sempre)
- [ ] Quando confiança < limiar ou QA = FAIL após as rodadas permitidas

## 4. Observabilidade

Traces no Langfuse; custo via virtual key no LiteLLM; métrica de ganho + baseline manual.
"""


def _squad_yaml(spec: SquadSpec) -> str:
    roster = [{"agent": a.name, "role": a.role, "sources": a.sources,
               "model_tier": a.model_tier} for a in spec.agents]
    roster.append({"agent": "QA", "role": "Revisão de qualidade", "sources": [],
                   "model_tier": "powerful"})

    pipeline = []
    for a in spec.agents:
        step = {"id": f"{a.name.lower()}-step", "type": "task", "agent": a.name,
                "model_tier": a.model_tier}
        if not a.is_reviewer:
            step["veto_conditions"] = ["assercao_sem_fonte"]
        pipeline.append(step)
    # QA reviewer + on_reject para o primeiro agente de trabalho
    first_step = pipeline[0]["id"] if pipeline else None
    pipeline.append({"id": "qa-review", "type": "task", "agent": "QA",
                     "role": "reviewer", "on_reject": first_step})
    # checkpoint humano SEMPRE no fim
    pipeline.append({"id": "aprova-final", "type": "checkpoint", "agent": "user"})

    return yaml.safe_dump({"roster": roster, "pipeline": pipeline},
                          sort_keys=False, allow_unicode=True)


def _agents_py(spec: SquadSpec) -> str:
    fns = []
    names = []
    for a in spec.agents:
        fn = a.name.lower()
        names.append((a.name, fn))
        fns.append(f'''def {fn}(state: RunState) -> Handoff:
    """{a.role}

    GUIA: troque o corpo por chamada real (SQL / RAG / API / LLM).
    - Toda asserção precisa de Source com type fato | inferencia | nao_consta.
    - Só acesse as fontes declaradas no roster ({", ".join(a.sources) or "nenhuma"}),
      senão o blast_radius bloqueia.
    - Defina confidence honestamente (0.0–1.0).
    """
    # exemplo (REMOVA ao implementar):
    return Handoff(
        agent="{a.name}",
        status=Status.OK,
        findings=[{{"dimension": "{fn}", "exemplo": True}}],
        sources=[
            Source(claim="descreva o achado", source="{(a.sources or ["SQL"])[0]}", type="fato"),
        ],
        confidence=0.7,
    )
''')

    # QA reviewer stub
    fns.append('''def qa(state: RunState) -> Handoff:
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
''')

    registry = ",\n    ".join([f'"{n}": {fn}' for n, fn in names] + ['"QA": qa'])
    body = "\n\n".join(fns)
    return f'''"""
Agentes do squad {spec.name}. Stubs com guia — troque os corpos por lógica real.
O motor (cercas, guardrails, checkpoint) NÃO muda; só estes corpos mudam.
"""
from __future__ import annotations

from squad_core import Handoff, RunState, Source, Status


{body}

REGISTRY = {{
    {registry},
}}
'''


def generate(spec: SquadSpec) -> Path:
    errs = validate_spec(spec)
    if errs:
        raise ValueError("spec inválida:\n  - " + "\n  - ".join(errs))

    # valida o frontmatter contra o schema ANTES de gravar
    if _HAS_JSONSCHEMA:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(_frontmatter(spec), schema)

    target = ROOT / "squads" / spec.module
    (target / "agents").mkdir(parents=True, exist_ok=True)
    (target / "SQUAD.md").write_text(_squad_md(spec), encoding="utf-8")
    (target / "squad.yaml").write_text(_squad_yaml(spec), encoding="utf-8")
    (target / "__init__.py").write_text("", encoding="utf-8")
    (target / "agents" / "__init__.py").write_text(_agents_py(spec), encoding="utf-8")
    return target
