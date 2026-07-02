# ADR 0003 — De esqueleto a pronto-para-uso

- **Status:** aceito
- **Contexto:** o motor estava endurecido (ADR 0002), mas os manifestos
  declaravam capacidades que o código não tinha: nenhuma camada LLM (agentes
  eram stubs sem caminho para produção), checkpoint humano auto-aprovado por
  `print`, vetos de domínio hardcoded no motor, `depends_on`/`model_tier`/
  `rating_scale`/`output_versioning` sem efeito, e nenhuma política para erro
  transiente de gateway.
- **Decisão:**
  - **Camada LLM no motor** (`squad_core/llm.py`): cliente do gateway LiteLLM
    (API OpenAI-compatível) em stdlib puro, coerente com o princípio
    "sem framework". Resolve `model_tier` → modelo (env `MODEL_TIER_*`,
    sobrescrito pelo campo `model_tiers` do manifesto), captura o custo do
    header `x-litellm-response-cost` para o agente repassar em
    `Handoff.cost_usd` — fechando o circuito da cerca 2 — e re-tenta
    transientes com backoff.
  - **Checkpoint humano real** no `run.py`: interativo por padrão;
    `--approve`/`--reject` para demo/CI; **sem TTY e sem flag, escala** —
    checkpoint sem humano disponível não é aprovação.
  - **Vetos de domínio plugáveis**: o motor só traz `assercao_sem_fonte`;
    cada squad exporta `VETOS = {nome: fn(handoff) -> bool}` no módulo de
    agentes (ex.: `payment_signal_indefinido` movido para o squad de crédito).
    Veto referenciado e não registrado é recusado antes do run.
  - **Erro transiente ≠ erro terminal**: `TransientAgentError` re-tentado com
    backoff auditado no histórico (`agent_retry_max`, default 2); esgotado,
    vira `failed` arquivado.
  - **`depends_on` funcional**: output reorganizado para
    `output/{squad}/{run_id}/`; run completado congela `result.json`
    (também corrigido: o result é o último *handoff*, não o checkpoint final);
    o `run.py` injeta o `result.json` mais recente de cada dependência em
    `task["upstream"]`.
  - **`rating_scale` enforced**: rating fora da escala declarada é bloqueado
    pelo `output_guardrail`.
  - **Knobs de auditabilidade removidos** (`state_per_step`,
    `archive_run_state`, `output_versioning`): o motor sempre grava tudo —
    auditabilidade não é configurável.
  - **Observabilidade plugável**: `Orchestrator(on_event=fn)` recebe cada
    evento de auditoria (ponte para Langfuse); falha do callback nunca
    derruba o run.
- **Consequências:** um squad novo sai do gerador com caminho direto para
  produção (LLM + custo + vetos + checkpoint). Agentes existentes continuam
  válidos; `payment_signal_indefinido` agora exige o `VETOS` do squad de
  crédito. `analise-credito-agro` → 0.4.0, `osint-investigador` → 0.2.0.
