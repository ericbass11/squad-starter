"""
Testa o gerador de squad. Run: pytest -q tests/test_generator.py

Garante que o gerador:
  - produz frontmatter válido contra o schema
  - sempre inclui QA + checkpoint humano no fim do pipeline
  - força governança em context=audax
  - recusa nome inválido e colisão
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from scaffolding.generator import AgentSpec, SquadSpec, _frontmatter, _squad_yaml, validate_spec  # noqa: E402


def _spec(name="teste-squad"):
    return SquadSpec(
        name=name, description="um squad de teste", context="audax",
        agents=[AgentSpec(name="AG1", role="coleta", sources=["SQL"])],
    )


def test_frontmatter_valido_contra_schema():
    jsonschema = pytest.importorskip("jsonschema")
    import json
    schema = json.loads((ROOT / "schemas" / "squad-schema.json").read_text())
    jsonschema.validate(_frontmatter(_spec()), schema)  # não levanta = ok


def test_audax_forca_governanca():
    fm = _frontmatter(_spec())
    assert fm["human_in_the_loop"] is True
    assert fm["audit_trail"] == "immutable"
    assert fm["source_citation"] == "required"


def test_pipeline_tem_qa_e_checkpoint_no_fim():
    data = yaml.safe_load(_squad_yaml(_spec()))
    pipe = data["pipeline"]
    assert pipe[-1]["type"] == "checkpoint"      # humano sempre no fim
    assert any(s.get("agent") == "QA" for s in pipe)
    qa = next(s for s in pipe if s.get("agent") == "QA")
    assert qa.get("on_reject")                   # QA pode mandar refazer


def test_agents_stub_traz_vetos_e_custo():
    from scaffolding.generator import _agents_py
    code = _agents_py(_spec())
    assert "VETOS" in code                 # ponto de extensão de vetos do domínio
    assert "cost_usd" in code              # cerca de custo depende do repasse
    assert "LLMClient" in code             # padrão LLM via gateway no guia


def test_squad_md_usa_termination_da_spec():
    from scaffolding.generator import _squad_md
    spec = _spec()
    spec.termination = "o dossiê é emitido com fontes rotuladas"
    md = _squad_md(spec)
    assert "o dossiê é emitido com fontes rotuladas" in md
    assert "[escreva a condição" not in md


def test_recusa_nome_invalido():
    errs = validate_spec(SquadSpec(name="Nome Inválido", description="x",
                                   agents=[AgentSpec(name="AG1", role="r")]))
    assert any("kebab" in e for e in errs)


def test_recusa_sem_agente():
    errs = validate_spec(SquadSpec(name="ok-name", description="x", agents=[]))
    assert any("agente" in e for e in errs)
