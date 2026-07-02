"""
Testa o runner (run.py): checkpoint humano real e dependências (depends_on).

Garante que:
  - --approve / --reject decidem sem perguntar
  - sem terminal interativo e sem flag, o checkpoint NÃO aprova (escala)
  - depends_on injeta o result.json do run completado mais recente
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("run_module", ROOT / "run.py")
run_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_module)


class _FakeState:
    history: list = []


def test_checkpoint_approve_e_reject():
    step = {"id": "ck"}
    assert run_module.make_checkpoint("approve")(_FakeState(), step) is True
    assert run_module.make_checkpoint("reject")(_FakeState(), step) is False


def test_checkpoint_sem_humano_nao_aprova(monkeypatch):
    # sem TTY e sem flag: checkpoint sem humano disponível não é aprovação
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert run_module.make_checkpoint(None)(_FakeState(), {"id": "ck"}) is False


def test_load_upstream_pega_run_mais_recente(tmp_path):
    dep = tmp_path / "squad-a"
    for run_id, valor in (("run-velho", 1), ("run-novo", 2)):
        d = dep / run_id
        d.mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({"result": valor}))
    upstream = run_module.load_upstream(["squad-a", "squad-inexistente"], tmp_path)
    assert upstream["squad-a"]["result"] == 2          # o mais recente
    assert "squad-inexistente" not in upstream          # ausente vira aviso
