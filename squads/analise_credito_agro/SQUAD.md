---
# ═══════════════ IDENTIDADE ═══════════════
name: analise-credito-agro
version: 0.4.0
description: Recomendação consultiva de crédito (rating + confiança + razões + precedentes) para o comitê. Piloto Agro.
owner: Eric
profile: agente-ia
context: audax
regulatory: [BACEN, CMN, LGPD]

# ═══════════════ TOPOLOGIA ═══════════════
topology: orchestrator-worker          # workers não conversam entre si
orchestrator: PMO
accountability: humano-2o-nivel         # IA = 1º nível consultivo; comitê decide

# ═══════════════ DEPENDÊNCIAS ═══════════════
depends_on: [pre-analise-cedente]       # consome o card de pré-análise quando existir

# ═══════════════ CERCAS DO LOOP ═══════════════
max_iterations: 12
max_execution_seconds: 90               # análise multi-fonte; > tarefa simples
max_cost_per_run_usd: 0.80              # teto por análise; ajustar com baseline real
stop_on_no_progress: true
qa_reflection_rounds_max: 2

# ═══════════════ GOVERNANÇA (enforced, não prosa) ═══════════════
human_in_the_loop: true
audit_trail: immutable                  # sempre-ligado no motor: state.json por step + events.jsonl + result.json congelado
source_citation: required               # toda asserção: fato | inferencia | nao_consta
output_blocked_if: [rating_sem_confianca, rating_sem_razoes, rating_sem_precedentes, assercao_sem_fonte]

# ═══════════════ ESCALA DE RATING ═══════════════
rating_scale: [A, B, "D+", "D-", E, F]

# ═══════════════ GATEWAY / OBSERVABILIDADE ═══════════════
llm_gateway: litellm
virtual_key: vk-analise-credito-agro
tracing: langfuse
metrics_lib: audax-metrics
---

# Squad: Análise de Crédito (Agro) — Manifesto

> Contrato declarativo de como os agentes se coordenam. Complementa o PRD (o quê/por quê)
> e o AGENTS.md (como mexer no repo). Mínimo e preciso por desígnio: o que uma ferramenta
> (hook, schema, gate) garante **não** se repete aqui — a ferramenta é a restrição.

## 1. Objetivo e término

**Entrega:** uma recomendação consultiva por operação — `rating` + `confiança` +
`razões` + `precedentes` — para o comitê de crédito. A IA **não aprova**; recomenda.

**Termina quando:** a recomendação é emitida com os quatro campos preenchidos e
todo dado faltante registrado como `nao_consta`. Não há nó sem caminho para este fim.

**Não faz:** decidir aprovação/reprovação; assinar; alterar limites; substituir o parecer humano.

## 2. Fundamentação (o diferencial)

A recomendação ancora em **desempenho realizado**, não em padrão histórico de aprovação:
*"perfis assim, quando aprovados, performaram assim na prática"*. SQL para fatos
estruturados; RAG/vector **apenas** sobre pareceres humanos históricos. Fine-tuning congelado.

## 3. Roster

| Agente | Papel | Fontes | Blast radius | model_tier |
|---|---|---|---|---|
| **PMO** | Orquestra, roteia, consolida, decide próximo/encerra. Não gera artefato de domínio. | estado | roteamento + leitura | powerful |
| **AG1** | Cedente & sinais de queda (faturamento × safra) | SQL, Bitrix24 | leitura | powerful |
| **AG2** | Precificação & garantias (inclui Agrisk: terra/patrimônio rural) | Agrisk, SQL | leitura | powerful |
| **AG3** | Risco-retorno & Selic | SQL, mercado | leitura | fast |
| **AG4** | Endividamento × faturamento & nicho | SQL, SCR | leitura | powerful |
| **AG5** | Serasa (peso reduzido — produtor opera como PF) | Serasa | leitura | fast |
| **AG6** | SCR/BACEN | SCR/BACEN | leitura | powerful |
| **QA** | Revisa saída dos agentes; PASS/FAIL com motivo; pede correção (máx. 2 rodadas) | — | leitura | powerful |
| **MON** | Monitor pós-aprovação, **independente** do fluxo de recomendação | SQL, Serasa, SCR, Agrisk, CreditHub | leitura | fast |

Workers devolvem ao PMO — não falam entre si. Cada agente acessa via **gateway API**, nunca o banco direto.

> **Piloto:** o roster acima é o desenho-alvo. O `squad.yaml` implementa hoje o
> subconjunto AG1 + AG4 + QA; os demais entram conforme as fontes forem plugadas.

## 4. Roteamento (SE/ENTÃO com veto)

- **Route A — cedente conhecido** → fluxo padrão.
- **Route B — cedente novo** → −10 pontos, teto **BB**, ciclo de monitoramento intensificado (90 dias).
- **Overlays Agro:** Serasa com peso menor (PF); descasamento **prazo da dívida × prazo da safra** = sinal de risco; queda de faturamento **fora da safra** = esperado, **não** dispara alerta.
- **Veto (recompra):** sinal de pagamento `recompra` → cedente absorveu a não-quitação → **reclassificar como inadimplência realizada**. `repasse` e `recompra` são idênticos no extrato e dizem o oposto sobre o sacado: distinguir é obrigatório (campo `payment_signal`).
- **Cadeia de pagamento:** `direto` (limpo) → `repasse` (bom pagador, alerta operacional menor) → `recompra` (inadimplência realizada).

## 5. Checkpoints humanos

- [ ] Aprovação do **design** do squad antes da 1ª execução.
- [ ] Antes de a recomendação virar item de pauta do **comitê** (sempre).
- [ ] `confiança < 0.6` **ou** `QA = FAIL` após 2 rodadas → escala para humano com o estado.
- [ ] Sinal `recompra` detectado → destaque obrigatório ao analista.

## 6. Handoff (schema; o validador é a restrição)

```json
{
  "from": "AG4", "to": "PMO",
  "status": "ok | needs_human | failed",
  "dimension": "endividamento_faturamento",
  "findings": [{"label": "...", "value": "...", "payment_signal": "direto|repasse|recompra|n/a"}],
  "sources": [{"claim": "...", "source": "SCR|Serasa|SQL|RAG|...", "type": "fato|inferencia|nao_consta"}],
  "confidence": 0.0
}
```

## 7. Dimensões de avaliação (5 eixos)

Cadastral/Societário · Serasa · SCR/BACEN · Endividamento × Faturamento · Sinais de pagamento.
CPF dos sócios pesquisado para **cedente e sacado**.

## 8. Observabilidade & ROI

- Traces no Langfuse para o loop e cada agente; custo via `vk-analise-credito-agro` no LiteLLM.
- Métrica de ganho via `audax-metrics` contra **baseline manual** do analista (tempo/operação + concordância com revisão humana).

## 9. Decisões

ADRs em `docs/adr/`. Mudança de regra de rating, overlay Agro ou cerca de loop → novo ADR + bump de `version`.
