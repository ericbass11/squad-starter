"""
Tests for the squad engine. Run: pytest -q

Covers the things that MUST hold for a regulated squad:
  - schema rejects an under-governed audax squad
  - secret scanning blocks a leaked key
  - blast radius blocks an out-of-scope source
  - output guardrail blocks an assertion without source
  - the orchestrator terminates and archives state
  - on_reject reflection respects its cap
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from squad_core import Handoff, Orchestrator, RunState, Source, Status
from squad_core.guardrails import GuardrailError, blast_radius, output_guardrail, secret_scan

HERE = Path(__file__).parent.parent


def test_schema_blocks_ungoverned_audax():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((HERE / "schemas" / "squad-schema.json").read_text())
    bad = {"name": "x", "version": "0.1.0", "profile": "agente-ia",
           "context": "audax", "topology": "orchestrator-worker",
           "human_in_the_loop": False, "audit_trail": True, "source_citation": "optional"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_secret_scan_blocks_key():
    with pytest.raises(GuardrailError):
        secret_scan("token = sk-abcdefghijklmnopqrstuvwxyz12345")


def test_blast_radius_blocks_out_of_scope():
    with pytest.raises(GuardrailError):
        blast_radius("AG1", {"Neo4j"}, {"AG1": {"SQL"}})


def test_output_guardrail_requires_source():
    h = Handoff(agent="AG1", status=Status.OK, findings=[{"x": 1}], sources=[])
    with pytest.raises(GuardrailError):
        output_guardrail(h, ["assercao_sem_fonte"])


def _manifest():
    return {
        "name": "test-squad", "version": "0.1.0",
        "max_iterations": 10, "max_execution_seconds": 30,
        "qa_reflection_rounds_max": 1, "stop_on_no_progress": True,
        "output_blocked_if": ["assercao_sem_fonte"],
        "roster": [{"agent": "A", "sources": ["SQL"]}],
        "pipeline": [
            {"id": "s1", "type": "task", "agent": "A"},
            {"id": "ck", "type": "checkpoint", "agent": "user"},
        ],
    }


def test_orchestrator_terminates_and_archives(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        return Handoff(agent="A", status=Status.OK, findings=[{"ok": True}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9)

    orch = Orchestrator(_manifest(), {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-1", {"task": "t"})
    assert state.status == "completed"
    archived = json.loads((tmp_path / "run-1" / "state.json").read_text())
    assert archived["status"] == "completed"
    assert archived["reason"] == "ok"


def test_on_reject_respects_cap(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        # always asks for rework → should hit the reflection cap and escalate
        return Handoff(agent="A", status=Status.NEEDS_HUMAN,
                       findings=[{"v": "REJECT"}],
                       sources=[Source("c", "SQL", "inferencia")], confidence=0.3)

    m = _manifest()
    m["pipeline"] = [{"id": "s1", "type": "task", "agent": "A", "on_reject": "s1"}]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-2", {"task": "t"})
    assert state.status == "escalated"
