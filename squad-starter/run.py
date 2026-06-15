"""
Entrypoint — run the credit squad end to end.

    python run.py

Loads the SQUAD.md (validated against the schema), wires the agents, runs the
orchestrator with all six fences, and prints the archived run state.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from squad_core import Orchestrator, load_manifest

HERE = Path(__file__).parent
SQUAD = HERE / "squads" / "analise_credito_agro"


def human_checkpoint(state, step) -> bool:
    # In production this pauses for a real human. Here we auto-approve to run
    # headless, but the hook point is explicit and audited in the run state.
    print(f"  [checkpoint] {step['id']} → auto-aprovado (em produção, decisão humana)")
    return True


def main() -> None:
    manifest = load_manifest(SQUAD / "SQUAD.md", HERE / "schemas" / "squad-schema.json")
    from squads.analise_credito_agro.agents import REGISTRY

    orch = Orchestrator(manifest, REGISTRY, checkpoint=human_checkpoint,
                        out_dir=str(HERE / "output"))
    run_id = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    task = {"operacao": "OP-001", "sacado": "Fazenda Boa Vista", "cedente": "AgroX"}

    print(f"🚀 Rodando squad '{manifest['name']}' v{manifest['version']} — run {run_id}")
    state = orch.run(run_id, task)
    print(f"✓ status: {state.status} | steps: {state.step}")
    last_handoff = next((h for h in reversed(state.history) if h.get("handoff")), None)
    if last_handoff:
        print("  recomendação:", json.dumps(last_handoff["handoff"]["findings"],
                                            ensure_ascii=False))
    print(f"  audit trail: output/{run_id}/state.json")


if __name__ == "__main__":
    main()
