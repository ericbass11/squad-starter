"""
Valida TODOS os SQUAD.md do repo contra schemas/squad-schema.json.
Usado no CI: nenhum squad malformado ou sub-governado (audax) entra no main.

    python scripts/validate_squads.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "squad-schema.json").read_text(encoding="utf-8"))


def frontmatter(md: str) -> dict:
    return yaml.safe_load(md.split("---")[1])


def main() -> int:
    squads = list(ROOT.glob("squads/*/SQUAD.md"))
    if not squads:
        print("nenhum SQUAD.md encontrado")
        return 0
    failed = 0
    for sq in squads:
        try:
            jsonschema.validate(frontmatter(sq.read_text(encoding="utf-8")), SCHEMA)
            print(f"✓ {sq.relative_to(ROOT)}")
        except jsonschema.ValidationError as e:
            failed += 1
            print(f"✗ {sq.relative_to(ROOT)}: {e.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
