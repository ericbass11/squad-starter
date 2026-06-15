"""
Roda qualquer squad do repo, por nome.

    python run.py                          # roda o squad de exemplo (crédito)
    python run.py osint_investigador       # roda outro squad pelo nome da pasta

Carrega o SQUAD.md (validado), importa o REGISTRY de agents/, e executa o
orquestrador com as seis cercas. O estado de cada run fica em output/{run_id}/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path

from squad_core import Orchestrator, load_manifest

HERE = Path(__file__).parent
DEFAULT_SQUAD = "analise_credito_agro"


def human_checkpoint(state, step) -> bool:
    print(f"  [checkpoint] {step['id']} -> auto-aprovado (em producao, decisao humana)")
    return True


def load_registry(squad_dir: Path) -> dict:
    spec = importlib.util.spec_from_file_location(
        f"{squad_dir.name}_agents", squad_dir / "agents" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.REGISTRY


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("squad", nargs="?", default=DEFAULT_SQUAD,
                    help="nome da pasta do squad em squads/")
    args = ap.parse_args()

    squad_dir = HERE / "squads" / args.squad
    if not squad_dir.exists():
        raise SystemExit(f"squad nao encontrado: squads/{args.squad}")

    manifest = load_manifest(squad_dir / "SQUAD.md", HERE / "schemas" / "squad-schema.json")
    registry = load_registry(squad_dir)

    orch = Orchestrator(manifest, registry, checkpoint=human_checkpoint,
                        out_dir=str(HERE / "output"))
    run_id = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    task = {"operacao": "OP-001", "alvo": "exemplo"}

    print(f"Rodando squad '{manifest['name']}' v{manifest['version']} - run {run_id}")
    state = orch.run(run_id, task)
    print(f"status: {state.status} | steps: {state.step}")
    last = next((h for h in reversed(state.history) if h.get("handoff")), None)
    if last:
        print("  saida:", json.dumps(last["handoff"]["findings"], ensure_ascii=False))
    print(f"  audit trail: output/{run_id}/state.json")


if __name__ == "__main__":
    main()
