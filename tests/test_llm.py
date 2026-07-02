"""
Testa o cliente LLM (gateway LiteLLM) sem rede: o transport é injetável.

Garante que:
  - model_tier resolve por env e o manifesto sobrescreve
  - custo vem do header x-litellm-response-cost (a cerca 2 depende disso)
  - 429/5xx re-tenta e depois sucede; esgotado vira TransientAgentError
  - 4xx de config é terminal (LLMConfigError), sem retry
  - sem LITELLM_BASE_URL falha com mensagem clara
"""
from __future__ import annotations

import pytest

from squad_core import LLMClient, LLMConfigError, TransientAgentError

OK_BODY = {"choices": [{"message": {"content": "resposta"}}],
           "model": "m-1", "usage": {"total_tokens": 10}}


def _client(responses: list, **kw):
    """Cliente com transport fake que devolve as respostas na ordem dada."""
    calls = {"n": 0, "bodies": []}

    def transport(url, headers, body):
        calls["bodies"].append(body)
        resp = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(resp, Exception):
            raise resp
        return resp

    c = LLMClient(kw.pop("manifest", None), base_url="http://gw", api_key="vk-x",
                  backoff_base=0, transport=transport, **kw)
    return c, calls


def test_tier_resolve_env_e_manifesto(monkeypatch):
    monkeypatch.setenv("MODEL_TIER_FAST", "modelo-env-fast")
    c = LLMClient({"model_tiers": {"powerful": "modelo-manifesto"}},
                  base_url="http://gw")
    assert c.resolve_model("fast") == "modelo-env-fast"
    assert c.resolve_model("powerful") == "modelo-manifesto"
    with pytest.raises(LLMConfigError):
        c.resolve_model("tier-fantasma")


def test_custo_vem_do_header():
    c, _ = _client([(200, {"X-LiteLLM-Response-Cost": "0.0042"}, OK_BODY)])
    res = c.complete("oi", tier="fast")
    assert res.text == "resposta"
    assert res.cost_usd == pytest.approx(0.0042)


def test_retry_transiente_depois_sucede():
    c, calls = _client([(429, {}, {}), (200, {}, OK_BODY)], max_retries=2)
    res = c.complete("oi")
    assert res.text == "resposta"
    assert calls["n"] == 2  # 1 falha + 1 sucesso


def test_transiente_esgotado_levanta():
    c, calls = _client([(503, {}, {})], max_retries=1)
    with pytest.raises(TransientAgentError):
        c.complete("oi")
    assert calls["n"] == 2  # tentativa original + 1 retry


def test_erro_de_config_e_terminal_sem_retry():
    c, calls = _client([(401, {}, {"error": "key inválida"})], max_retries=3)
    with pytest.raises(LLMConfigError):
        c.complete("oi")
    assert calls["n"] == 1  # não re-tentou


def test_sem_base_url_falha_claro(monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    with pytest.raises(LLMConfigError, match="LITELLM_BASE_URL"):
        LLMClient().complete("oi")
