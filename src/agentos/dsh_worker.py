"""DshAgentWorker — real WorkerAdapter driving the local DeepSeek Harness CLI.

Same INTENTS-only contract as HermesAgentWorker (see docs/EFFECTS_CHANNEL_V2.md):
the child process is contractually restricted to declaring file effects via the
length-safe block channel plus one final AGENTOS_RESULT line. The ENGINE replays
declared effects through the ToolGateway inside the live run; declared effects
are data, never authority (path confinement enforced at parse time AND by the
gateway handler). Output is untrusted data.

The adapter is optional: tests never require it. The OS-level Job Object limits
lifetime/memory but does NOT confine filesystem/network access — the same
residual risk recorded in docs/GAP_REGISTER.md (R2-3) applies.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .hermes_worker import (HermesAgentWorker, PROMPT_TEMPLATE, _JobObject,
                            _sandbox_kwargs)
from .workers import StepRequest, StepResult


class WorkerUnavailable(RuntimeError):
    pass


def resolve_dsh_bin() -> str | None:
    """Locate a launchable ``dsh`` CLI entry point.

    npm installs a .cmd/.ps1 pair; CreateProcess cannot run .ps1 directly, so
    prefer the .cmd wrapper, fall back to pwsh -File for a .ps1-only install.
    """
    if sys.platform == "win32":
        cmd = shutil.which("dsh.cmd")
        if cmd:
            return cmd
    raw = shutil.which("dsh")
    return raw


class DshAgentWorker:
    """Drive ``dsh --profile <profile> <prompt>`` as a run-to-completion step.

    Works like HermesAgentWorker but for the local DeepSeek Harness CLI whose
    headless profile answers exactly one task, prints the result, and exits.
    """

    name = "dsh"

    def __init__(self, dsh_bin: str | None = None,
                 profile: str = "headless", timeout_s: int = 900):
        self.bin = dsh_bin or resolve_dsh_bin()
        self.profile = profile
        self.timeout_s = timeout_s
        if not self.bin:
            raise WorkerUnavailable("dsh CLI not found on PATH")

    # parse_effects is the shared, workspace-confined block-channel parser.
    parse_effects = staticmethod(HermesAgentWorker.parse_effects)

    def _command(self, prompt: str) -> list[str]:
        base = [self.bin, "--profile", self.profile, prompt]
        if self.bin.lower().endswith(".ps1"):
            return ["pwsh", "-NoProfile", "-File", *base]
        return base

    def step(self, req: StepRequest) -> StepResult:
        prompt = PROMPT_TEMPLATE.format(title=req.title, dod=req.definition_of_done,
                                        ws=req.workspace_path,
                                        packet=req.context_packet_text[:4000])
        cmd = self._command(prompt)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=req.workspace_path, **_sandbox_kwargs())
        except OSError as e:
            return StepResult(ok=False, note=f"dsh failed to launch: {e}",
                              fail_class="worker_unavailable")
        job = _JobObject()
        try:
            job.assign(proc)
            try:
                out, err = proc.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                return StepResult(ok=False, note="dsh timeout",
                                  fail_class="deadline")
        finally:
            job.close()

        raw_path = Path(req.workspace_path) / "dsh-output.txt"
        raw_path.write_text((out or "") + ((("\n[stderr]\n" + err)
                                            if err else "")), encoding="utf-8")

        declared_files = self.parse_effects(out or "", req.workspace_path)
        result_line = next((l.strip() for l in (out or "").splitlines()
                            if l.strip().startswith("AGENTOS_RESULT")), None)
        if not result_line:
            return StepResult(ok=False, note="no AGENTOS_RESULT line",
                              fail_class="worker", raw_output_ref=str(raw_path))
        try:
            payload = json.loads(result_line[len("AGENTOS_RESULT"):].strip())
        except json.JSONDecodeError:
            return StepResult(ok=False, note="unparsable AGENTOS_RESULT",
                              fail_class="worker", raw_output_ref=str(raw_path))
        ok = bool(payload.get("ok"))
        outputs = {"files": declared_files} if ok and declared_files else {}
        return StepResult(ok=ok,
                          note=str(payload.get("note", ""))[:300],
                          outputs=outputs,
                          fail_class=None if ok else "worker",
                          raw_output_ref=str(raw_path))
