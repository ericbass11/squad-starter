---
name: osint-investigador
version: 0.2.0
description: Investigação OSINT auditável de cedente/sacado com citação rastreável
  de fonte.
owner: Eric
profile: agente-ia
context: audax
topology: orchestrator-worker
orchestrator: PMO
depends_on: []
max_iterations: 20
max_execution_seconds: 120
max_cost_per_run_usd: 1.2
stop_on_no_progress: true
qa_reflection_rounds_max: 2
human_in_the_loop: true
source_citation: required
output_blocked_if:
- assercao_sem_fonte
regulatory:
- BACEN
- CMN
- LGPD
audit_trail: immutable
---

# Squad: osint-investigador — Manifesto

> Contrato declarativo de como os agentes se coordenam. Orchestrator-worker:
> o PMO decide; workers não conversam entre si. Checkpoint humano obrigatório.

## 1. Objetivo e término

**Entrega:** Investigação OSINT auditável de cedente/sacado com citação rastreável de fonte.

**Termina quando:** o dossiê OSINT é emitido com as três dimensões cobertas
(fontes públicas, grafo de relacionamentos, red flags), toda asserção com fonte
rotulada, e "nao_consta" registrado para o que não se verificou.

**Não faz:** decidir sozinho onde há accountability humana.

## 2. Roster

| Agente | Papel | Fontes | model_tier |
|---|---|---|---|
| AG1 | Coleta em fontes públicas (Receita, judiciário) | ReceitaFederal, Judiciario | powerful |
| AG2 | Grafo de entidades e relacionamentos (Neo4j) | Neo4j, SQL | powerful |
| AG3 | Sinais de risco e red flags | Serasa, SCR | fast |
| QA | Revisa saída dos agentes; PASS/FAIL com motivo (máx. 2 rodadas) | — | powerful |

Workers devolvem ao PMO — não falam entre si. Acesso a dado via gateway, nunca banco direto.

## 3. Checkpoints humanos

- [ ] Aprovação do design antes da 1ª execução
- [ ] Antes de a saída virar decisão/recomendação oficial (sempre)
- [ ] Quando confiança < limiar ou QA = FAIL após as rodadas permitidas

## 4. Observabilidade

Traces no Langfuse; custo via virtual key no LiteLLM; métrica de ganho + baseline manual.
