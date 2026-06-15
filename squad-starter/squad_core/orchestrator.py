"""
PMO Orchestrator — orchestrator-worker topology.

The PMO decides "what comes next". Workers never talk to each other; they return
a typed Handoff to the PMO. The loop carries the six fences:

  1. max_iterations        — emergency brake
  2. time/cost budget      — wall
  3. termination_condition — defined before the happy path
  4. no_progress           — abort if state stops changing
  5. human checkpoint      — pause at decision points (consultive, human accountable)
  6. transition guardrails — typed handoff + hooks + output discipline

Plus the field-validated mechanisms: declarative pipeline (task/checkpoint,
on_reject with cap), per-step veto with internal correction BEFORE QA, and
state.json written every step + archived per run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from .guardrails import GuardrailError, blast_radius, output_guardrail, secret_scan
from .types import Handoff, RunState, Status

# An agent is any callable: (state) -> Handoff. Register them by name.
AgentFn = Callable[[RunState], Handoff]
# A human checkpoint callable: (state, step) -> bool (approved?).
CheckpointFn = Callable[[RunState, dict], bool]


class Orchestrator:
    def __init__(self, manifest: dict, agents: dict[str, AgentFn],
                 checkpoint: CheckpointFn | None = None,
                 out_dir: str = "output"):
        self.m = manifest
        self.agents = agents
        self.checkpoint = checkpoint or (lambda s, step: True)
        self.out_dir = out_dir
        self.allowed = self._allowed_sources()

    # ---- fences as config, read from the manifest frontmatter ----
    @property
    def max_iterations(self) -> int:
        return int(self.m.get("max_iterations", 12))

    @property
    def max_seconds(self) -> int:
        return int(self.m.get("max_execution_seconds", 90))

    @property
    def reflection_max(self) -> int:
        return int(self.m.get("qa_reflection_rounds_max", 2))

    @property
    def blocked_if(self) -> list[str]:
        return list(self.m.get("output_blocked_if", []))

    def _allowed_sources(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for a in self.m.get("roster", []):
            out[a["agent"]] = set(a.get("sources", []))
        return out

    # ---- the loop ----
    def run(self, run_id: str, task: dict) -> RunState:
        state = RunState(squad=self.m["name"], run_id=run_id, task=task, status="running")
        run_path = Path(self.out_dir) / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.max_seconds
        pipeline = self.m["pipeline"]
        reject_counts: dict[str, int] = {}

        i = 0
        idx = 0
        last_fp = None
        while idx < len(pipeline):
            step = pipeline[idx]
            i += 1
            self._write_state(run_path, state, step)

            # fence 1 — max_iterations
            if i > self.max_iterations:
                return self._finish(run_path, state, "escalated", "max_iterations")
            # fence 2 — time wall
            if time.monotonic() > deadline:
                return self._finish(run_path, state, "escalated", "timeout")
            # fence 4 — no_progress
            fp = state.fingerprint()
            if self.m.get("stop_on_no_progress", True) and fp == last_fp:
                return self._finish(run_path, state, "escalated", "no_progress")
            last_fp = fp

            stype = step.get("type", "task")

            # fence 5 — human checkpoint is a pipeline step
            if stype == "checkpoint":
                approved = self.checkpoint(state, step)
                state.history.append({"step": step["id"], "type": "checkpoint",
                                      "approved": approved})
                if not approved:
                    return self._finish(run_path, state, "escalated", "checkpoint_rejected")
                idx += 1
                continue

            # task step — dispatch to the named agent
            agent_name = step["agent"]
            agent = self.agents[agent_name]
            handoff = agent(state)

            # fence 6 — transition guardrails
            try:
                secret_scan(json.dumps(handoff.to_dict(), default=str))
                requested = {s.source for s in handoff.sources}
                blast_radius(agent_name, requested, self.allowed)
                # per-step veto + internal correction BEFORE QA (max 2 tries)
                self._apply_veto(step, handoff)
                output_guardrail(handoff, self.blocked_if,
                                 is_reviewer=(step.get("role") == "reviewer"))
            except GuardrailError as e:
                state.history.append({"step": step["id"], "agent": agent_name,
                                      "guardrail": str(e)})
                return self._finish(run_path, state, "escalated", str(e))

            state.history.append({"step": step["id"], "agent": agent_name,
                                  "handoff": handoff.to_dict()})
            state.step = i

            # on_reject — declarative reflection loop with a cap
            if handoff.status == Status.NEEDS_HUMAN and step.get("on_reject"):
                reject_counts[step["id"]] = reject_counts.get(step["id"], 0) + 1
                if reject_counts[step["id"]] > self.reflection_max:
                    return self._finish(run_path, state, "escalated", "reflection_cap")
                idx = self._index_of(pipeline, step["on_reject"])
                continue
            if handoff.status == Status.FAILED:
                return self._finish(run_path, state, "failed", "agent_failed")

            idx += 1

        # fence 3 — termination: pipeline consumed cleanly
        state.result = state.history[-1] if state.history else None
        return self._finish(run_path, state, "completed", "ok")

    # ---- veto with internal correction (max 2) ----
    def _apply_veto(self, step: dict, handoff: Handoff) -> None:
        vetos = step.get("veto_conditions", [])
        if not vetos:
            return
        for attempt in range(2):
            failed = self._check_vetos(vetos, handoff)
            if not failed:
                return
            # In a real squad you'd re-dispatch the agent with the veto feedback.
            # Here we surface it; the agent fn is responsible for self-correction.
            handoff.findings.append({"veto_feedback": failed, "attempt": attempt + 1})
        still = self._check_vetos(vetos, handoff)
        if still:
            raise GuardrailError(f"veto não resolvido após 2 tentativas: {still}")

    @staticmethod
    def _check_vetos(vetos: list[str], handoff: Handoff) -> list[str]:
        failed = []
        flat = json.dumps(handoff.to_dict(), default=str).lower()
        for v in vetos:
            if v == "assercao_sem_fonte" and handoff.findings and not handoff.sources:
                failed.append(v)
            if v == "payment_signal_indefinido" and "payment_signal" in flat \
               and '"n/a"' not in flat and "indefinido" in flat:
                failed.append(v)
        return failed

    @staticmethod
    def _index_of(pipeline: list[dict], step_id: str) -> int:
        for k, s in enumerate(pipeline):
            if s["id"] == step_id:
                return k
        raise ValueError(f"on_reject aponta para step inexistente: {step_id}")

    # ---- state.json: write every step, archive per run ----
    def _write_state(self, run_path: Path, state: RunState, step: dict) -> None:
        snapshot = {
            "squad": state.squad, "run_id": state.run_id, "status": state.status,
            "step": {"current": state.step, "label": step.get("id")},
            "history_len": len(state.history),
            "updatedAt": time.time(),
        }
        (run_path / "state.json").write_text(json.dumps(snapshot, indent=2,
                                                        ensure_ascii=False))

    def _finish(self, run_path: Path, state: RunState, status: str, reason: str) -> RunState:
        state.status = status
        archive = {
            "squad": state.squad, "run_id": state.run_id, "status": status,
            "reason": reason, "steps": state.step, "history": state.history,
            "result": state.result, "completedAt": time.time(),
        }
        # archive the run state permanently (audit trail)
        (run_path / "state.json").write_text(json.dumps(archive, indent=2,
                                                        ensure_ascii=False))
        return state
