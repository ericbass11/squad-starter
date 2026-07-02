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
        "agent_retry_backoff_seconds": 0,
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


def test_transient_error_retried_then_succeeds(tmp_path):
    from squad_core import TransientAgentError
    calls = {"n": 0}

    def agent_a(state: RunState) -> Handoff:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientAgentError("rate limit")
        return Handoff(agent="A", status=Status.OK, findings=[{"ok": True}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9)

    orch = Orchestrator(_manifest(), {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-retry", {"task": "t"})
    assert state.status == "completed"
    assert calls["n"] == 2
    assert any(h.get("transient_error") for h in state.history)  # retry auditado


def test_transient_error_exhausted_fails_archived(tmp_path):
    from squad_core import TransientAgentError

    def agent_a(state: RunState) -> Handoff:
        raise TransientAgentError("gateway fora")

    m = _manifest()
    m["agent_retry_max"] = 1
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-retry2", {"task": "t"})
    assert state.status == "failed"
    archived = json.loads((tmp_path / "run-retry2" / "state.json").read_text())
    assert archived["reason"] == "agent_exception"


def test_custom_domain_veto_pluggable(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        corrected = any(h.get("veto_feedback") for h in state.history)
        return Handoff(agent="A", status=Status.OK,
                       findings=[{"valor": 10 if corrected else -1}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9)

    m = _manifest()
    m["pipeline"][0]["veto_conditions"] = ["valor_negativo"]
    vetos = {"valor_negativo": lambda h: any(
        isinstance(f, dict) and f.get("valor", 0) < 0 for f in h.findings)}
    orch = Orchestrator(m, {"A": agent_a}, vetos=vetos, out_dir=str(tmp_path))
    state = orch.run("run-veto-dom", {"task": "t"})
    assert state.status == "completed"


def test_unknown_veto_name_refused_before_running(tmp_path):
    m = _manifest()
    m["pipeline"][0]["veto_conditions"] = ["veto_que_nao_existe"]
    with pytest.raises(ValueError, match="veto"):
        Orchestrator(m, {"A": lambda s: None}, out_dir=str(tmp_path))


def test_rating_fora_da_escala_bloqueado(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        return Handoff(agent="A", status=Status.OK,
                       findings=[{"rating": "Z"}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9)

    m = _manifest()
    m["rating_scale"] = ["A", "B", "C"]
    orch = Orchestrator(m, {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-scale", {"task": "t"})
    assert state.status == "escalated"
    archived = json.loads((tmp_path / "run-scale" / "state.json").read_text())
    assert "fora da escala" in archived["reason"]


def test_result_json_congelado_ao_completar(tmp_path):
    def agent_a(state: RunState) -> Handoff:
        return Handoff(agent="A", status=Status.OK, findings=[{"ok": True}],
                       sources=[Source("c", "SQL", "fato")], confidence=0.9,
                       cost_usd=0.10)

    orch = Orchestrator(_manifest(), {"A": agent_a}, out_dir=str(tmp_path))
    state = orch.run("run-result", {"task": "t"})
    assert state.status == "completed"
    frozen = json.loads((tmp_path / "run-result" / "result.json").read_text())
    assert frozen["squad"] == "test-squad"
    assert frozen["cost_usd"] == pytest.approx(0.10)
    assert frozen["result"]["handoff"]["findings"] == [{"ok": True}]


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
