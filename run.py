"""
Roda qualquer squad do repo, por nome.

    python run.py                          # squad de exemplo, checkpoint interativo
    python run.py osint_investigador       # outro squad pelo nome da pasta
    python run.py --approve                # aprova checkpoints sem perguntar (demo/CI)
    python run.py --task '{"operacao": "OP-123"}'   # task customizada (JSON)

Carrega o SQUAD.md + squad.yaml (validados), importa REGISTRY e VETOS de
agents/, resolve as dependências (depends_on) e executa o orquestrador com as
seis cercas. O audit trail de cada run fica em output/{squad}/{run_id}/.

Checkpoint humano: por padrão pergunta no terminal (IA consultiva, humano com
accountability). Sem terminal interativo e sem --approve/--reject, o run escala
— um checkpoint sem humano disponível NÃO é aprovação.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

from squad_core import Orchestrator, load_manifest

HERE = Path(__file__).parent
DEFAULT_SQUAD = "analise_credito_agro"


def make_checkpoint(decision: str | None):
    """decision: 'approve' | 'reject' | None (pergunta no terminal)."""
    def checkpoint(state, step) -> bool:
        last = next((h for h in reversed(state.history) if h.get("handoff")), None)
        if last:
            print(f"  [checkpoint {step['id']}] última saída: "
                  f"{json.dumps(last['handoff']['findings'], ensure_ascii=False)[:300]}")
        if decision == "approve":
            print(f"  [checkpoint {step['id']}] aprovado via --approve")
            return True
        if decision == "reject":
            print(f"  [checkpoint {step['id']}] rejeitado via --reject")
            return False
        if not sys.stdin.isatty():
            print(f"  [checkpoint {step['id']}] sem humano disponível (não-interativo) "
                  "-> escalando; use --approve para aprovar em demo/CI")
            return False
        resp = input(f"  [checkpoint {step['id']}] aprovar? [s/N] ").strip().lower()
        return resp in ("s", "sim", "y", "yes")
    return checkpoint


def load_registry(squad_dir: Path) -> tuple[dict, dict]:
    spec = importlib.util.spec_from_file_location(
        f"{squad_dir.name}_agents", squad_dir / "agents" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.REGISTRY, getattr(mod, "VETOS", {})


def load_upstream(deps: list[str], out_root: Path) -> dict:
    """Para cada squad em depends_on, injeta o result.json do run completado
    mais recente. Dependência sem resultado vira aviso — o agente registra
    'nao_consta' para o que não se verificou."""
    upstream = {}
    for dep in deps:
        results = sorted((out_root / dep).glob("*/result.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if results:
            upstream[dep] = json.loads(results[0].read_text(encoding="utf-8"))
            print(f"  [depends_on] {dep}: consumindo {results[0].parent.name}")
        else:
            print(f"  [depends_on] {dep}: sem run completado em output/{dep}/ "
                  "(seguindo sem — registre 'nao_consta')")
    return upstream


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("squad", nargs="?", default=DEFAULT_SQUAD,
                    help="nome da pasta do squad em squads/")
    ap.add_argument("--task", help="task em JSON (default: task de exemplo)")
    gate = ap.add_mutually_exclusive_group()
    gate.add_argument("--approve", action="store_true",
                      help="aprova checkpoints sem perguntar (demo/CI)")
    gate.add_argument("--reject", action="store_true",
                      help="rejeita checkpoints (testa o caminho de escalada)")
    args = ap.parse_args()

    squad_dir = HERE / "squads" / args.squad
    if not squad_dir.exists():
        raise SystemExit(f"squad nao encontrado: squads/{args.squad}")

    manifest = load_manifest(squad_dir / "SQUAD.md", HERE / "schemas" / "squad-schema.json")
    registry, vetos = load_registry(squad_dir)

    task = json.loads(args.task) if args.task else {"operacao": "OP-001", "alvo": "exemplo"}
    out_root = HERE / "output"
    deps = manifest.get("depends_on") or []
    if deps:
        task["upstream"] = load_upstream(deps, out_root)

    decision = "approve" if args.approve else ("reject" if args.reject else None)
    orch = Orchestrator(manifest, registry, checkpoint=make_checkpoint(decision),
                        vetos=vetos, out_dir=str(out_root / manifest["name"]))
    run_id = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")

    print(f"Rodando squad '{manifest['name']}' v{manifest['version']} - run {run_id}")
    state = orch.run(run_id, task)
    print(f"status: {state.status} | steps: {state.step} | custo: US$ {state.cost_usd:.2f}")
    last = next((h for h in reversed(state.history) if h.get("handoff")), None)
    if last:
        print("  saida:", json.dumps(last["handoff"]["findings"], ensure_ascii=False))
    print(f"  audit trail: output/{manifest['name']}/{run_id}/ "
          "(state.json + events.jsonl" + (" + result.json" if state.status == "completed" else "") + ")")


if __name__ == "__main__":
    main()
