# squad-starter

Repositório-base para criar **qualquer squad multi-agente** do padrão Eric.
Clone, gere um squad, troque os agentes — o motor, as cercas, a governança,
a camada LLM e a auditabilidade vêm prontos.

> Topologia orchestrator-worker · sem LangGraph · Python + Claude Code · auditável desde o início.

## Roda em 30 segundos

```bash
pip install -r requirements.txt
python run.py --approve  # roda o squad de exemplo aprovando o checkpoint (demo)
python run.py            # idem, mas o checkpoint humano pergunta no terminal
pytest -q                # testes: motor, guardrails, LLM, runner, gerador
python scripts/validate_squads.py   # valida todo squad (SQUAD.md + squad.yaml) e o pipeline
```

Saída esperada do `run.py`: o squad roda os agentes, passa pelo checkpoint humano
e emite a recomendação (rating + confiança + razões + precedentes). Cada execução
fica em `output/{squad}/{run_id}/` — `state.json` (snapshot por passo, arquivado
no fim), `events.jsonl` (log append-only, o audit trail imutável) e `result.json`
(entregável congelado do run, o que outros squads consomem via `depends_on`).

**Sem humano disponível, não há aprovação:** rodando sem terminal interativo e
sem `--approve`, o checkpoint escala em vez de aprovar sozinho.

## O que tem dentro

```
squad_core/            # o MOTOR reutilizável (não precisa mexer)
  types.py             # Handoff (contrato JSON tipado, com custo), RunState
  orchestrator.py      # PMO + as 6 cercas + veto plugável + retry + audit trail
  llm.py               # cliente do gateway LiteLLM: tier->modelo, custo, retry
  guardrails.py        # secret scan · blast radius · citação · escala de rating
  manifest.py          # carrega SQUAD.md + squad.yaml e valida o resultado mesclado
schemas/
  squad-schema.json    # valida o frontmatter; em context=audax força governança
squads/
  analise_credito_agro/
    SQUAD.md           # manifesto humano (contrato do squad)
    squad.yaml         # sidecar: roster + pipeline que o motor consome
    agents/__init__.py # agentes (REGISTRY) + vetos do domínio (VETOS)
scripts/validate_squads.py   # usado no CI (schema + integridade do pipeline)
tests/                 # garantias do motor
docs/adr/              # decisões registradas
```

## Como criar um squad novo

Use o gerador — ele garante orchestrator-worker + QA + checkpoint humano no fim,
e valida contra o schema antes de gravar. Dois modos:

```bash
python new_squad.py                                   # interativo (pergunta no terminal)
python new_squad.py --from scaffolding/spec.example.yaml   # por arquivo (preencha um YAML)
```

O gerador cria `squads/<seu-squad>/` com SQUAD.md, squad.yaml e agents/__init__.py
(stubs com comentários guiando). Depois:

1. Edite o **SQUAD.md** (condição de término, vetos do domínio).
2. Troque os **stubs dos agentes** por chamadas reais (SQL/RAG/API/LLM) — cada um
   retorna um `Handoff` tipado com `sources` rotuladas (fato/inferencia/nao_consta)
   e `cost_usd` preenchido (o `LLMClient` devolve o custo pronto).
3. Declare os **vetos do seu domínio** no dict `VETOS` do módulo de agentes e
   referencie-os em `veto_conditions` no squad.yaml.
4. `python scripts/validate_squads.py && pytest -q`
5. `python run.py <seu-squad>` para rodar.

O motor, as seis cercas, os guardrails e o checkpoint humano **não mudam** — só os
corpos dos agentes e os vetos. Exemplos prontos: `squads/analise_credito_agro/` e
`squads/osint_investigador/` (este gerado pelo próprio gerador).

## Chamando LLM de verdade (gateway)

Copie `.env.example` para `.env` e preencha `LITELLM_BASE_URL` +
`LITELLM_VIRTUAL_KEY` (as chaves de LLM vivem no gateway, nunca espalhadas por
agente; a virtual key rastreia custo por squad). No corpo do agente:

```python
from squad_core import LLMClient

llm = LLMClient()  # ou LLMClient(manifest) para respeitar model_tiers do squad
res = llm.complete("Analise o cedente X...", system="Você é analista de crédito...",
                   tier="powerful")   # fast | powerful -> modelo real
return Handoff(agent="AG1", status=Status.OK, findings=[...],
               sources=[...], confidence=0.8,
               cost_usd=res.cost_usd)  # custo capturado do gateway
```

`model_tier` resolve por env (`MODEL_TIER_FAST`/`MODEL_TIER_POWERFUL`) ou pelo
campo `model_tiers` do manifesto. Erro transiente (429/5xx/timeout) re-tenta com
backoff no cliente **e** no orquestrador (`agent_retry_max`); erro de config é
terminal e explica o que falta.

## As seis cercas (no `orchestrator.py`)

1. `max_iterations` — freio de emergência
2. teto de tempo (`max_execution_seconds`) **e** custo (`max_cost_per_run_usd`,
   somado dos `cost_usd` dos handoffs) — wall
3. condição de término — antes do happy path
4. detecção de no-progress — aborta quando um step re-emite o mesmo handoff
5. checkpoint humano — pausa em decisão (IA consultiva, humano com accountability)
6. guardrails de transição — handoff tipado + secret scan + blast radius +
   citação de fonte + escala de rating (`rating_scale`)

Além das cercas: pipeline malformado é **recusado antes de rodar** (agente não
registrado, veto desconhecido, `on_reject` órfão, id duplicado); veto por step
**re-executa o agente** com o feedback no estado (máx. 2 tentativas) antes do QA;
erro transiente re-tenta com backoff auditado; e um agente que quebra vira run
`failed` **com o audit trail arquivado**, nunca um crash sem rastro.

O audit trail é **sempre-ligado** — não existe knob para desligar state.json,
events.jsonl ou o arquivamento. Para plugar observabilidade externa (Langfuse
etc.), passe `Orchestrator(on_event=fn)` — cada evento de auditoria chega no
callback, e um erro seu nunca derruba o run.

## Dependência entre squads (`depends_on`)

Declare `depends_on: [outro-squad]` no frontmatter. O `run.py` injeta o
`result.json` do run completado mais recente de cada dependência em
`task["upstream"]`. Dependência sem run vira aviso — o agente registra
`nao_consta` para o que não pôde verificar.

## Princípios não-negociáveis

- IA é **consultiva**; o humano detém a accountability final. Sem humano
  disponível, o checkpoint **escala** — nunca auto-aprova.
- Toda asserção carrega **fonte rastreável**; inferência rotulada; sem dado → "não consta".
- Auditabilidade não é configurável: todo run deixa state.json + events.jsonl.
- Mudança em regra que afeta decisão = **proposta auditável com gate humano** (ver `docs/adr/`).
