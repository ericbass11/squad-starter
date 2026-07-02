# ADR 0002 — Endurecimento do motor (cercas reais, audit trail imutável)

- **Status:** aceito
- **Contexto:** auditoria do motor revelou que duas das seis cercas anunciadas
  não operavam (custo nunca era somado nem aplicado; no-progress nunca disparava,
  pois o fingerprint incluía `history_len`, que cresce a cada passo), o veto não
  re-executava o agente, uma exceção de agente derrubava o run sem arquivar o
  estado, e o sidecar `squad.yaml` podia rebaixar governança após a validação do
  schema (era mesclado depois do `jsonschema.validate`).
- **Decisão:**
  - **Cerca 2 completa:** `Handoff.cost_usd` somado em `RunState.cost_usd`;
    ultrapassar `max_cost_per_run_usd` escala com razão `cost_budget`.
  - **Cerca 4 real:** no-progress = o mesmo step re-emitir um handoff idêntico
    (hash do conteúdo), detectado via conjunto `(step_id, hash)`.
  - **Veto com correção real:** o PMO registra `veto_feedback` no histórico e
    re-executa o agente (máx. 2 tentativas) antes do QA.
  - **Crash nunca perde rastro:** exceção de agente ou handoff fora do contrato
    tipado vira `AgentError` → run arquivado como `failed`.
  - **Fail-fast:** pipeline validado no construtor do `Orchestrator` (agente
    registrado, `on_reject` existente, ids únicos, tipos válidos) — e o mesmo
    check roda no CI via `scripts/validate_squads.py`.
  - **Audit trail imutável de fato:** além do `state.json` (sobrescrito por
    passo), cada run ganha `events.jsonl` append-only com run_start, handoffs,
    checkpoints, bloqueios de guardrail e run_finish.
  - **Governança inviolável:** o manifesto é validado **após** a mesclagem com o
    sidecar — `squad.yaml` não consegue desligar `human_in_the_loop` & cia.
  - **Guardrails ampliados:** padrões de segredo para GitHub/Slack/chaves
    privadas; `rating_sem_razoes` e `rating_sem_precedentes` agora aplicados.
- **Consequências:** manifests existentes continuam válidos; agentes ganham o
  campo opcional `cost_usd` no `Handoff`. Squads presos em loop de rework
  idêntico agora escalam por `no_progress` antes do teto de reflexão.
