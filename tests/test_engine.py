"""
Tests for the squad engine. Run: pytest -q

Covers the things that MUST hold for a regulated squad:
  - schema rejects an under-governed audax squad
  - secret scanning blocks a leaked key
  - blast radius blocks an out-of-scope source
  - output guardrail blocks an assertion without source
  - the orchestrator terminates and archives state
  - on_reject reflection respects its cap
  - cost budget (fence 2) escalates when exceeded
  - no_progress (fence 4) fires on a repeated identical handoff
  - an agent crash still archives the audit trail (failed, not lost)
  - a malformed pipeline is refused before any agent runs
  - veto re-dispatches the agent, which self-corrects
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
    calls = {"n": 0}

    def agent_a(state: RunState) -> Handoff:
        # always asks for rework, with changing output → dodges the no_progress
        # fence, so it is the reflection cap that must escalate
        calls["n"] += 1
        return Handoff(agent="A", status=Status.NEEDS_HUMAN,
                       findings=[{"v": "REJECT", "call": calls["n"]}],
                       sources=[Source("c", "SQL", "inferencia")], confidence=0.3)

    m = _manifest()
    m["pipeline"] = [{"id": "s1", "type": "task", "agent": "A", "on_reject": "s1"}]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-2", {"task": "t"})
    assert state.status == "escalated"
    archived = json.loads((tmp_path / "run-2" / "state.json").read_text())
    assert archived["reason"] == "reflection_cap"


def test_cost_budget_escalates(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        return Handoff(agent="A", status=Status.OK, findings=[{"ok": True}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9,
                       cost_usd=0.60)

    m = _manifest()
    m["max_cost_per_run_usd"] = 0.50
    m["pipeline"] = [
        {"id": "s1", "type": "task", "agent": "A"},
        {"id": "s2", "type": "task", "agent": "A"},
    ]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-cost", {"task": "t"})
    assert state.status == "escalated"
    archived = json.loads((tmp_path / "run-cost" / "state.json").read_text())
    assert archived["reason"] == "cost_budget"
    assert archived["cost_usd"] == pytest.approx(0.60)


def test_no_progress_fires_on_identical_handoff(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        # identical output every time → the rework loop is stuck
        return Handoff(agent="A", status=Status.NEEDS_HUMAN,
                       findings=[{"v": "REJECT"}],
                       sources=[Source("c", "SQL", "inferencia")], confidence=0.3)

    m = _manifest()
    m["qa_reflection_rounds_max"] = 5  # cap alto: quem deve pegar é a cerca 4
    m["pipeline"] = [{"id": "s1", "type": "task", "agent": "A", "on_reject": "s1"}]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-noprog", {"task": "t"})
    assert state.status == "escalated"
    archived = json.loads((tmp_path / "run-noprog" / "state.json").read_text())
    assert archived["reason"] == "no_progress"


def test_agent_crash_archives_audit_trail(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        raise RuntimeError("boom")

    orch = Orchestrator(_manifest(), {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-crash", {"task": "t"})
    assert state.status == "failed"
    archived = json.loads((tmp_path / "run-crash" / "state.json").read_text())
    assert archived["reason"] == "agent_exception"
    assert (tmp_path / "run-crash" / "events.jsonl").exists()


def test_malformed_pipeline_refused_before_running(tmp_path):
    m = _manifest()
    m["pipeline"] = [{"id": "s1", "type": "task", "agent": "NAO_EXISTE"}]
    with pytest.raises(ValueError):
        Orchestrator(m, {"A": lambda s: None}, out_dir=str(tmp_path))

    m = _manifest()
    m["pipeline"][0]["on_reject"] = "step-fantasma"
    with pytest.raises(ValueError):
        Orchestrator(m, {"A": lambda s: None}, out_dir=str(tmp_path))


def test_veto_redispatches_and_agent_self_corrects(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        # self-corrects when the PMO surfaces veto feedback in the history
        got_feedback = any(h.get("veto_feedback") for h in state.history)
        if not got_feedback:
            return Handoff(agent="A", status=Status.OK,
                           findings=[{"x": 1}], sources=[], confidence=0.9)
        return Handoff(agent="A", status=Status.OK, findings=[{"x": 1}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9)

    m = _manifest()
    m["pipeline"][0]["veto_conditions"] = ["assercao_sem_fonte"]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-veto", {"task": "t"})
    assert state.status == "completed"
    assert any(h.get("veto_feedback") for h in state.history)
