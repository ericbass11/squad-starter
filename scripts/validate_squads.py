"""
Valida TODOS os squads do repo: SQUAD.md + squad.yaml (mesclados) contra
schemas/squad-schema.json, mais a integridade referencial do pipeline.
Usado no CI: nenhum squad malformado ou sub-governado (audax) entra no main.

    python scripts/validate_squads.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from squad_core.manifest import load_manifest  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "squad-schema.json"


def check_pipeline(m: dict) -> list[str]:
    """O mesmo que o Orchestrator recusa em runtime, pego já no CI."""
    errs: list[str] = []
    roster = {a.get("agent") for a in m.get("roster", [])}
    pipeline = m.get("pipeline", [])
    ids = [s.get("id") for s in pipeline]
    if None in ids or len(ids) != len(set(ids)):
        errs.append("todo step do pipeline precisa de um id único")
    for s in pipeline:
        stype = s.get("type", "task")
        if stype not in ("task", "checkpoint"):
            errs.append(f"step {s.get('id')}: tipo inválido '{stype}'")
        if stype == "task" and s.get("agent") not in roster:
            errs.append(f"step {s.get('id')}: agente '{s.get('agent')}' fora do roster")
        target = s.get("on_reject")
        if target and target not in ids:
            errs.append(f"step {s.get('id')}: on_reject aponta para step inexistente: {target}")
    return errs


def main() -> int:
    squads = list(ROOT.glob("squads/*/SQUAD.md"))
    if not squads:
        print("nenhum SQUAD.md encontrado")
        return 0
    failed = 0
    for sq in squads:
        rel = sq.relative_to(ROOT)
        try:
            manifest = load_manifest(sq, SCHEMA_PATH)
        except (jsonschema.ValidationError, ValueError) as e:
            failed += 1
            print(f"✗ {rel}: {getattr(e, 'message', e)}")
            continue
        errs = check_pipeline(manifest)
        if errs:
            failed += 1
            for err in errs:
                print(f"✗ {rel}: {err}")
        else:
            print(f"✓ {rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
