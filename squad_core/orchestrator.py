"""
PMO Orchestrator — orchestrator-worker topology.

The PMO decides "what comes next". Workers never talk to each other; they return
a typed Handoff to the PMO. The loop carries the six fences:

  1. max_iterations        — emergency brake
  2. time/cost budget      — wall (max_execution_seconds + max_cost_per_run_usd)
  3. termination_condition — defined before the happy path
  4. no_progress           — abort if a step re-emits the exact same handoff
  5. human checkpoint      — pause at decision points (consultive, human accountable)
  6. transition guardrails — typed handoff + hooks + output discipline

Plus the field-validated mechanisms: declarative pipeline (task/checkpoint,
on_reject with cap), per-step veto with real re-dispatch BEFORE QA, transient
error retry with backoff, and the always-on audit trail: state.json snapshot per
step, append-only events.jsonl, final archive, and result.json frozen per run.
Auditability is not a knob — it cannot be turned off.

Domain vetos are pluggable: pass `vetos={"nome": fn}` where fn(handoff) -> bool
(True = condição violada). The builtin `assercao_sem_fonte` is always available.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from .guardrails import GuardrailError, blast_radius, output_guardrail, secret_scan
from .types import Handoff, RunState, Status, TransientAgentError

# An agent is any callable: (state) -> Handoff. Register them by name.
AgentFn = Callable[[RunState], Handoff]
# A human checkpoint callable: (state, step) -> bool (approved?).
CheckpointFn = Callable[[RunState, dict], bool]
# A domain veto: (handoff) -> bool. True = the veto condition is violated.
VetoFn = Callable[[Handoff], bool]
# An observability hook: receives every audit event (for Langfuse etc.).
EventFn = Callable[[dict], None]

BUILTIN_VETOS: dict[str, VetoFn] = {
    "assercao_sem_fonte": lambda h: bool(h.findings and not h.sources),
}


class AgentError(Exception):
    """An agent crashed or broke the typed-handoff contract. The run is
    archived as 'failed' — the audit trail survives the crash."""


class Orchestrator:
    def __init__(self, manifest: dict, agents: dict[str, AgentFn],
                 checkpoint: CheckpointFn | None = None,
                 vetos: dict[str, VetoFn] | None = None,
                 on_event: EventFn | None = None,
                 out_dir: str = "output"):
        self.m = manifest
        self.agents = agents
        self.checkpoint = checkpoint or (lambda s, step: True)
        self.vetos = {**BUILTIN_VETOS, **(vetos or {})}
        self.on_event = on_event
        self.out_dir = out_dir
        self.allowed = self._allowed_sources()
        self._validate_pipeline()  # fail fast, before any agent runs

    # ---- fences as config, read from the manifest frontmatter ----
    @property
    def max_iterations(self) -> int:
        return int(self.m.get("max_iterations", 12))

    @property
    def max_seconds(self) -> int:
        return int(self.m.get("max_execution_seconds", 90))

    @property
    def max_cost(self) -> float | None:
        v = self.m.get("max_cost_per_run_usd")
        return None if v is None else float(v)

    @property
    def reflection_max(self) -> int:
        return int(self.m.get("qa_reflection_rounds_max", 2))

    @property
    def retry_max(self) -> int:
        return int(self.m.get("agent_retry_max", 2))

    @property
    def retry_backoff(self) -> float:
        return float(self.m.get("agent_retry_backoff_seconds", 1.0))

    @property
    def blocked_if(self) -> list[str]:
        return list(self.m.get("output_blocked_if", []))

    def _allowed_sources(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for a in self.m.get("roster", []):
            out[a["agent"]] = set(a.get("sources", []))
        return out

    def _validate_pipeline(self) -> None:
        """A malformed pipeline must not start — a mid-run KeyError would kill
        the run without an audit trail. Everything referential is checked here."""
        pipeline = self.m.get("pipeline") or []
        if not pipeline:
            raise ValueError("manifest sem pipeline — nada a executar")
        ids = [s.get("id") for s in pipeline]
        if None in ids or len(ids) != len(set(ids)):
            raise ValueError("todo step do pipeline precisa de um id único")
        for s in pipeline:
            stype = s.get("type", "task")
            if stype not in ("task", "checkpoint"):
                raise ValueError(f"step {s['id']}: tipo inválido '{stype}'")
            if stype == "task" and s.get("agent") not in self.agents:
                raise ValueError(
                    f"step {s['id']}: agente '{s.get('agent')}' não registrado "
                    f"(registrados: {sorted(self.agents)})")
            for v in s.get("veto_conditions", []):
                if v not in self.vetos:
                    raise ValueError(
                        f"step {s['id']}: veto '{v}' não registrado — exporte-o "
                        f"no VETOS do módulo de agentes (conhecidos: {sorted(self.vetos)})")
            target = s.get("on_reject")
            if target and target not in ids:
                raise ValueError(f"step {s['id']}: on_reject aponta para step "
                                 f"inexistente: {target}")

    # ---- the loop ----
    def run(self, run_id: str, task: dict) -> RunState:
        state = RunState(squad=self.m["name"], run_id=run_id, task=task, status="running")
        run_path = Path(self.out_dir) / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        self._log_event(run_path, {"event": "run_start", "squad": state.squad,
                                   "run_id": run_id, "task": task})
        deadline = time.monotonic() + self.max_seconds
        pipeline = self.m["pipeline"]
        reject_counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()  # (step_id, handoff hash) — fence 4

        i = 0
        idx = 0
        while idx < len(pipeline):
            step = pipeline[idx]
            i += 1
            self._write_state(run_path, state, step)

            # fence 1 — max_iterations
            if i > self.max_iterations:
                return self._finish(run_path, state, "escalated", "max_iterations")
            # fence 2 — time/cost wall
            if time.monotonic() > deadline:
                return self._finish(run_path, state, "escalated", "timeout")
            if self.max_cost is not None and state.cost_usd > self.max_cost:
                return self._finish(run_path, state, "escalated", "cost_budget")

            stype = step.get("type", "task")

            # fence 5 — human checkpoint is a pipeline step
            if stype == "checkpoint":
                approved = self.checkpoint(state, step)
                state.history.append({"step": step["id"], "type": "checkpoint",
                                      "approved": approved})
                self._log_event(run_path, {"event": "checkpoint", "step": step["id"],
                                           "approved": approved})
                if not approved:
                    return self._finish(run_path, state, "escalated", "checkpoint_rejected")
                idx += 1
                continue

            # task step — dispatch to the named agent
            agent_name = step["agent"]
            agent = self.agents[agent_name]

            try:
                handoff = self._dispatch(agent_name, agent, state)
                # per-step veto with real re-dispatch BEFORE QA (max 2 tries)
                handoff = self._apply_veto(step, handoff, agent_name, agent, state)
                # fence 6 — transition guardrails on the final handoff
                payload = json.dumps(handoff.to_dict(), default=str)
                secret_scan(payload)
                requested = {s.source for s in handoff.sources}
                blast_radius(agent_name, requested, self.allowed)
                output_guardrail(handoff, self.blocked_if,
                                 is_reviewer=(step.get("role") == "reviewer"),
                                 rating_scale=self.m.get("rating_scale"))
            except AgentError as e:
                state.history.append({"step": step["id"], "agent": agent_name,
                                      "error": str(e)})
                self._log_event(run_path, {"event": "agent_error", "step": step["id"],
                                           "error": str(e)})
                return self._finish(run_path, state, "failed", "agent_exception")
            except GuardrailError as e:
                state.history.append({"step": step["id"], "agent": agent_name,
                                      "guardrail": str(e)})
                self._log_event(run_path, {"event": "guardrail_block", "step": step["id"],
                                           "guardrail": str(e)})
                return self._finish(run_path, state, "escalated", str(e))

            # fence 4 — no_progress: the same step re-emitting the same handoff
            fp = (step["id"], hashlib.sha256(payload.encode()).hexdigest())
            if self.m.get("stop_on_no_progress", True) and fp in seen:
                state.history.append({"step": step["id"], "agent": agent_name,
                                      "no_progress": True})
                return self._finish(run_path, state, "escalated", "no_progress")
            seen.add(fp)

            state.history.append({"step": step["id"], "agent": agent_name,
                                  "handoff": handoff.to_dict()})
            state.step = i
            self._log_event(run_path, {"event": "handoff", "step": step["id"],
                                       "agent": agent_name, "status": handoff.status.value,
                                       "confidence": handoff.confidence,
                                       "cost_usd": handoff.cost_usd})

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

        # fence 3 — termination: pipeline consumed cleanly. The result is the
        # last HANDOFF (the deliverable), not the trailing checkpoint entry.
        state.result = next((h for h in reversed(state.history) if h.get("handoff")),
                            state.history[-1] if state.history else None)
        return self._finish(run_path, state, "completed", "ok")

    # ---- dispatch: typed contract + transient retry + audit on crash ----
    def _dispatch(self, agent_name: str, agent: AgentFn, state: RunState) -> Handoff:
        for attempt in range(self.retry_max + 1):
            try:
                handoff = agent(state)
                break
            except TransientAgentError as e:
                if attempt >= self.retry_max:
                    raise AgentError(f"{agent_name}: transiente não resolvido após "
                                     f"{self.retry_max + 1} tentativas: {e}") from e
                state.history.append({"agent": agent_name, "retry": attempt + 1,
                                      "transient_error": str(e)})
                time.sleep(self.retry_backoff * (2 ** attempt))
            except Exception as e:  # noqa: BLE001 — any crash becomes an archived failure
                raise AgentError(f"{agent_name}: {e!r}") from e
        if not isinstance(handoff, Handoff):
            raise AgentError(f"{agent_name} não retornou um Handoff tipado")
        state.cost_usd += float(handoff.cost_usd or 0.0)
        return handoff

    # ---- veto with internal correction: re-dispatch the agent (max 2) ----
    def _apply_veto(self, step: dict, handoff: Handoff, agent_name: str,
                    agent: AgentFn, state: RunState) -> Handoff:
        vetos = step.get("veto_conditions", [])
        if not vetos:
            return handoff
        for attempt in (1, 2):
            failed = self._check_vetos(vetos, handoff)
            if not failed:
                return handoff
            # surface the feedback in state, then re-dispatch: the agent fn reads
            # the veto_feedback from history and self-corrects.
            state.history.append({"step": step["id"], "agent": agent_name,
                                  "veto_feedback": failed, "attempt": attempt})
            handoff = self._dispatch(agent_name, agent, state)
        still = self._check_vetos(vetos, handoff)
        if still:
            raise GuardrailError(f"veto não resolvido após 2 tentativas: {still}")
        return handoff

    def _check_vetos(self, vetos: list[str], handoff: Handoff) -> list[str]:
        return [v for v in vetos if self.vetos[v](handoff)]

    @staticmethod
    def _index_of(pipeline: list[dict], step_id: str) -> int:
        return next(k for k, s in enumerate(pipeline) if s["id"] == step_id)

    # ---- audit trail (always on): state.json per step + append-only events.jsonl ----
    def _write_state(self, run_path: Path, state: RunState, step: dict) -> None:
        snapshot = {
            "squad": state.squad, "run_id": state.run_id, "status": state.status,
            "step": {"current": state.step, "label": step.get("id")},
            "history_len": len(state.history),
            "cost_usd": state.cost_usd,
            "updatedAt": time.time(),
        }
        (run_path / "state.json").write_text(json.dumps(snapshot, indent=2,
                                                        ensure_ascii=False))

    def _log_event(self, run_path: Path, event: dict) -> None:
        event = {"ts": time.time(), **event}
        line = json.dumps(event, ensure_ascii=False, default=str)
        with (run_path / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 — observabilidade nunca derruba o run
                pass

    def _finish(self, run_path: Path, state: RunState, status: str, reason: str) -> RunState:
        state.status = status
        archive = {
            "squad": state.squad, "run_id": state.run_id, "status": status,
            "reason": reason, "steps": state.step, "cost_usd": state.cost_usd,
            "history": state.history, "result": state.result,
            "completedAt": time.time(),
        }
        # archive the run state permanently (audit trail)
        (run_path / "state.json").write_text(json.dumps(archive, indent=2,
                                                        ensure_ascii=False))
        if status == "completed":
            # frozen deliverable of the run — what depends_on consumers read
            (run_path / "result.json").write_text(json.dumps(
                {"squad": state.squad, "run_id": state.run_id,
                 "result": state.result, "cost_usd": state.cost_usd,
                 "completedAt": archive["completedAt"]},
                indent=2, ensure_ascii=False))
        self._log_event(run_path, {"event": "run_finish", "status": status,
                                   "reason": reason, "cost_usd": state.cost_usd})
        return state
