"""
Manifest loader + validator.

Reads a SQUAD.md, parses the YAML frontmatter, and validates it against
schemas/squad-schema.json. In context=audax the schema FORCES governance fields
(human_in_the_loop, audit_trail=immutable, source_citation=required) — a malformed
or under-governed squad cannot run.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:  # validation is best-effort if dep missing
    _HAS_JSONSCHEMA = False


def _frontmatter(md_text: str) -> dict:
    # maxsplit=2: a "---" horizontal rule in the body must not truncate parsing
    parts = md_text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SQUAD.md sem frontmatter YAML delimitado por ---")
    return yaml.safe_load(parts[1]) or {}


def load_manifest(squad_md: str | Path, schema_path: str | Path | None = None) -> dict:
    squad_md = Path(squad_md)
    data = _frontmatter(squad_md.read_text(encoding="utf-8"))

    # The runnable pieces (roster + pipeline) live in a sidecar squad.yaml next to
    # the SQUAD.md, so the manifest stays human-readable while the engine gets data.
    sidecar = squad_md.parent / "squad.yaml"
    if sidecar.exists():
        data.update(yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {})

    # Validate AFTER the merge: the sidecar must not be able to downgrade the
    # governance the schema enforces (human_in_the_loop, audit_trail, citation).
    if schema_path and _HAS_JSONSCHEMA:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)  # raises on invalid / under-governed audax

    return data
