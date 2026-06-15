# ADR 0001 — Fundação do squad-starter

- **Status:** aceito
- **Contexto:** precisávamos de um repositório-base reutilizável para criar
  qualquer squad multi-agente do Eric, com as decisões do padrão já materializadas.
- **Decisão:**
  - Topologia **orchestrator-worker** (PMO decide; workers não conversam entre si).
  - **Sem LangGraph** — Python puro + padrão Megazord; o motor é `squad_core/`.
  - Manifesto em **SQUAD.md** (humano) + sidecar **squad.yaml** (dados do motor),
    validado contra **JSON Schema** no CI.
  - As **seis cercas** de loop no orquestrador; **veto-por-step** antes do QA;
    **state.json** escrito a cada passo e arquivado por run.
  - Guardrails (`hooks/` lógica em `squad_core/guardrails.py`): secret scan,
    blast radius, citação de fonte (fato/inferencia/nao_consta).
- **Consequências:** squads novos herdam cercas, governança e auditabilidade sem
  reescrever o motor. Desvio de qualquer decisão acima exige novo ADR.
