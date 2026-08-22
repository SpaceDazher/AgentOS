"""Deterministic workers: WorkerAdapter protocol + FakeWorker (scripted).

The engine never imports an LLM. Real adapters (e.g. HermesAgentWorker) implement
the same protocol; their output is untrusted data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class StepRequest:
    task_id: str
    run_id: str
    goal_id: str
    title: str
    definition_of_done: str
    inputs: dict
    workspace_path: str
    step: int
    checkpoint: dict | None = None   # resume context when step>0
    context_packet_text: str = ""


@dataclass
class StepResult:
    ok: bool
    note: str = ""
    outputs: dict = field(default_factory=dict)      # declared expected outputs
    fail_class: str | None = None                    # worker|budget|deadline|worker_unavailable
    next_action: dict = field(default_factory=dict)
    raw_output_ref: str | None = None                # untrusted output stored as evidence


class WorkerAdapter(Protocol):
    name: str

    def step(self, req: StepRequest) -> StepResult: ...


class FakeWorker:
    """Deterministic scripted worker.

    Script: list of dicts consumed one per step.
      {"ok": True, "outputs": {...}}                      — success
      {"ok": False, "fail_class": "worker"}               — failure (consumes retry)
      {"ok": False, "fail_then_ok": True, ...}            — fails on first attempt,
                                                            succeeds on retry
      {"ok": True, "outputs": {"alternative": True}}      — alternative-but-valid result
    """

    def __init__(self, script: list[dict] | None = None):
        self.script = script or [{"ok": True}]
        self.name = "fake"

    def step(self, req: StepRequest) -> StepResult:
        # resume continues the script where the checkpoint left off, so a
        # fail-then-succeed script succeeds on retry (not on attempt #1 again).
        idx = min(req.step, len(self.script) - 1)
        action = self.script[idx]
        if not action.get("ok", True):
            cls = action.get("fail_class", "worker")
            return StepResult(ok=False, note=f"scripted {cls} failure",
                              fail_class=cls,
                              next_action=action.get("next_action", {}))
        outputs = dict(action.get("outputs", {}))
        if req.checkpoint:
            outputs.setdefault("resumed_from_checkpoint", True)
        if action.get("fail_then_ok"):
            outputs["recovered_after_retry"] = True
        return StepResult(ok=True, note="scripted success",
                          outputs=outputs,
                          next_action={"done": True})
