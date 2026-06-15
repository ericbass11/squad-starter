# squad-starter

Repositório-base para criar **qualquer squad multi-agente** do padrão Eric.
Clone, copie o squad de exemplo, troque os agentes — o motor, as cercas, a
governança e a auditabilidade vêm prontos.

> Topologia orchestrator-worker · sem LangGraph · Python + Claude Code · auditável desde o início.

## Roda em 30 segundos

```bash
pip install -r requirements.txt
python run.py            # roda o squad de exemplo (Análise de Crédito Agro)
pytest -q                # 6 testes: schema, guardrails, cercas
python scripts/validate_squads.py   # valida todo SQUAD.md contra o schema
```

Saída esperada do `run.py`: o squad roda os agentes, passa pelo checkpoint humano
e emite a recomendação (rating + confiança + razões + precedentes). O estado de
cada execução fica em `output/{run_id}/state.json` — o audit trail.

## O que tem dentro

```
squad_core/            # o MOTOR reutilizável (não precisa mexer)
  types.py             # Handoff (contrato JSON tipado), RunState
  orchestrator.py      # PMO + as 6 cercas + pipeline declarativo + veto + state.json
  guardrails.py        # secret scan · blast radius · citação de fonte
  manifest.py          # carrega o SQUAD.md e valida contra o schema
schemas/
  squad-schema.json    # valida o frontmatter; em context=audax força governança
squads/
  analise_credito_agro/
    SQUAD.md           # manifesto humano (contrato do squad)
    squad.yaml         # sidecar: roster + pipeline que o motor consome
    agents/__init__.py # agentes de exemplo (stubs que respeitam o contrato)
scripts/validate_squads.py   # usado no CI
tests/                 # garantias do motor
docs/adr/              # decisões registradas
```

## Como criar um squad novo

1. Copie `squads/analise_credito_agro/` para `squads/seu_squad/`.
2. Edite o **SQUAD.md** (objetivo, roster, cercas, governança). Em `context: audax`
   o schema obriga `human_in_the_loop`, `audit_trail: immutable`, `source_citation: required`.
3. Ajuste o **squad.yaml** (roster + pipeline: steps `task`/`checkpoint`, `veto_conditions`, `on_reject`).
4. Implemente os **agentes** em `agents/__init__.py` — cada um retorna um `Handoff`
   tipado com `sources` rotuladas (`fato`/`inferencia`/`nao_consta`).
5. `python scripts/validate_squads.py && pytest -q` e rode.

## As seis cercas (no `orchestrator.py`)

1. `max_iterations` — freio de emergência
2. teto de tempo/custo — wall
3. condição de término — antes do happy path
4. detecção de no-progress — aborta loop preso
5. checkpoint humano — pausa em decisão (IA consultiva, humano com accountability)
6. guardrails de transição — handoff tipado + secret scan + blast radius + citação

## Princípios não-negociáveis

- IA é **consultiva**; o humano detém a accountability final.
- Toda asserção carrega **fonte rastreável**; inferência rotulada; sem dado → "não consta".
- Mudança em regra que afeta decisão = **proposta auditável com gate humano** (ver `docs/`).
- Os agentes de exemplo são **stubs**: troque os corpos por SQL/RAG/LLM reais — o
  motor, as cercas e os guardrails permanecem.
```
