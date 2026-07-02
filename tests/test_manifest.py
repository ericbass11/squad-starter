"""
Testa o carregamento do manifesto (SQUAD.md + sidecar squad.yaml).

Garante que:
  - o sidecar NÃO consegue rebaixar a governança validada pelo schema
  - um "---" no corpo do SQUAD.md não quebra o parse do frontmatter
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from squad_core import load_manifest

ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "schemas" / "squad-schema.json"

_VALID_AUDAX_FM = {
    "name": "squad-teste", "version": "0.1.0", "profile": "agente-ia",
    "context": "audax", "topology": "orchestrator-worker",
    "human_in_the_loop": True, "audit_trail": "immutable",
    "source_citation": "required",
}


def _write_squad(tmp_path: Path, fm: dict, body: str = "# corpo\n") -> Path:
    md = tmp_path / "SQUAD.md"
    md.write_text(f"---\n{yaml.safe_dump(fm)}---\n\n{body}", encoding="utf-8")
    return md


def test_sidecar_nao_rebaixa_governanca(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    md = _write_squad(tmp_path, _VALID_AUDAX_FM)
    # sidecar tenta desligar o human_in_the_loop DEPOIS da validação do frontmatter
    (tmp_path / "squad.yaml").write_text(
        yaml.safe_dump({"human_in_the_loop": False, "roster": [], "pipeline": []}),
        encoding="utf-8")
    with pytest.raises(jsonschema.ValidationError):
        load_manifest(md, SCHEMA)


def test_frontmatter_sobrevive_hr_no_corpo(tmp_path):
    md = _write_squad(tmp_path, _VALID_AUDAX_FM,
                      body="# corpo\n\nseção 1\n\n---\n\nseção 2\n")
    data = load_manifest(md, SCHEMA)
    assert data["name"] == "squad-teste"
    assert data["human_in_the_loop"] is True
