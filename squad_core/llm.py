"""
LLM client — chamadas via gateway LiteLLM (API OpenAI-compatível), stdlib puro.

Fecha o circuito que o manifesto declara:
  - model_tier (fast/powerful) resolvido para modelo real, por env ou manifesto
  - custo capturado automaticamente do gateway (header x-litellm-response-cost)
    e devolvido para o agente preencher Handoff.cost_usd — a cerca 2 depende disso
  - erro transiente (429/5xx/timeout) vira TransientAgentError, que o
    orquestrador re-tenta com backoff; erro de config/contrato é terminal

Uso num agente:

    from squad_core.llm import LLMClient
    llm = LLMClient(manifest)          # ou LLMClient() para defaults por env
    res = llm.complete("prompt...", system="persona...", tier="powerful")
    return Handoff(..., cost_usd=res.cost_usd)

Config (.env / ambiente):
    LITELLM_BASE_URL      ex.: https://litellm.suaempresa.com
    LITELLM_VIRTUAL_KEY   virtual key do squad (rastreia custo por squad)
    MODEL_TIER_FAST       default: claude-haiku-4-5
    MODEL_TIER_POWERFUL   default: claude-sonnet-5
O manifesto pode sobrescrever os tiers via campo `model_tiers: {fast: ..., powerful: ...}`.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import TransientAgentError

DEFAULT_TIERS = {"fast": "claude-haiku-4-5", "powerful": "claude-sonnet-5"}

# transport: (url, headers, body) -> (status, resp_headers, resp_body_dict)
Transport = Callable[[str, dict, dict], tuple[int, dict, dict]]


class LLMConfigError(Exception):
    """Configuração ausente/inválida (URL, key, tier). Terminal — não re-tenta."""


@dataclass
class LLMResult:
    text: str
    model: str
    cost_usd: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


def _http_transport(url: str, headers: dict, body: dict) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        payload = {}
        try:
            payload = json.loads(e.read())
        except Exception:  # noqa: BLE001 — corpo de erro pode não ser JSON
            pass
        return e.code, dict(e.headers or {}), payload
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TransientAgentError(f"gateway inacessível: {e}") from e


class LLMClient:
    def __init__(self, manifest: dict | None = None, *,
                 base_url: str | None = None, api_key: str | None = None,
                 max_retries: int = 3, backoff_base: float = 1.0,
                 transport: Transport | None = None):
        self.base_url = (base_url or os.environ.get("LITELLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("LITELLM_VIRTUAL_KEY", "")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.transport = transport or _http_transport

        tiers = dict(DEFAULT_TIERS)
        for t in tiers:
            tiers[t] = os.environ.get(f"MODEL_TIER_{t.upper()}", tiers[t])
        if manifest:
            tiers.update(manifest.get("model_tiers") or {})
        self.tiers = tiers

    def resolve_model(self, tier: str) -> str:
        model = self.tiers.get(tier)
        if not model:
            raise LLMConfigError(f"model_tier desconhecido: '{tier}' "
                                 f"(conhecidos: {sorted(self.tiers)})")
        return model

    def complete(self, prompt: str, *, system: str | None = None,
                 tier: str = "powerful", model: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 1024) -> LLMResult:
        if not self.base_url:
            raise LLMConfigError(
                "LITELLM_BASE_URL não configurado — copie .env.example para .env "
                "e preencha o gateway (as chaves de LLM vão pelo gateway, "
                "nunca espalhadas por agente)")
        model = model or self.resolve_model(tier)
        body = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/v1/chat/completions"

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                status, resp_headers, data = self.transport(url, headers, body)
            except TransientAgentError as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** attempt))
                continue
            if status == 200:
                return self._parse(model, resp_headers, data)
            if status == 429 or status >= 500:
                last_err = TransientAgentError(f"gateway respondeu {status}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** attempt))
                continue
            # 4xx que não é rate limit: config/contrato errado — não adianta re-tentar
            raise LLMConfigError(f"gateway respondeu {status}: "
                                 f"{json.dumps(data, ensure_ascii=False)[:300]}")
        raise TransientAgentError(
            f"LLM indisponível após {self.max_retries + 1} tentativas: {last_err}")

    @staticmethod
    def _parse(model: str, headers: dict, data: dict) -> LLMResult:
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMConfigError(f"resposta do gateway fora do contrato: {e}") from e
        # LiteLLM devolve o custo calculado no header; sem ele, custo fica 0.0
        # (e o teto de custo do run deixa de proteger — prefira um gateway que informe)
        headers_lower = {k.lower(): v for k, v in headers.items()}
        try:
            cost = float(headers_lower.get("x-litellm-response-cost", 0.0))
        except (TypeError, ValueError):
            cost = 0.0
        return LLMResult(text=text, model=data.get("model", model),
                         cost_usd=cost, usage=data.get("usage") or {})
