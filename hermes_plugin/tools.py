"""Thin-client handlers over the local AgentOS Python API.

The AgentOS package lives in ``<repo>/src`` next to this plugin directory;
we prepend that path to ``sys.path`` below so the plugin works without a pip
install. Every handler receives the tool-call JSON arguments as a single
positional dict and returns a JSON string. Exceptions are wrapped into
``{"success": false, "error": ...}``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- AgentOS import bootstrap -------------------------------------------------
# The plugin is a thin client: the AgentOS repo lives at a fixed local path
# (override with AGENTOS_REPO env var). Layout: <repo>/src/agentos/...
_REPO_ROOT = Path(os.environ.get("AGENTOS_REPO", r"D:\Project\AgentOS")).resolve()
_SRC_DIR = _REPO_ROOT / "src"
if not (_SRC_DIR / "agentos").is_dir():
    # fallback: repo next to the plugin dir (dev checkout layout)
    _alt = Path(__file__).resolve().parents[1] / "src"
    if (_alt / "agentos").is_dir():
        _SRC_DIR = _alt
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from agentos.cli import run_demo                                  # noqa: E402
from agentos.db import open_db                                    # noqa: E402
from agentos.engine import Engine                                 # noqa: E402
from agentos.evidence_pack import build as build_evidence_pack    # noqa: E402
from agentos.journal import Journal                               # noqa: E402

MAX_PACK_CHARS = 6000
_VALID_RISK_TIERS = ("normal", "sensitive")


# --- helpers -------------------------------------------------------------------
def _default_root() -> Path:
    """Default AgentOS home: $AGENTOS_HOME or ~/.agentos."""
    return Path(os.environ.get("AGENTOS_HOME", str(Path.home() / ".agentos")))


def _resolve_db_path(db_dir: str | None) -> tuple[Path, Path]:
    """Return (agentos.db path, root dir).

    Explicit db_dir wins. Otherwise prefer an existing database ($AGENTOS_HOME
    first, then a .agentos-demo tree in the current working directory); if
    neither exists, fall back to the AgentOS default home (opened clean).
    """
    if db_dir:
        root = Path(db_dir)
        return root / "agentos.db", root
    home_root = _default_root()
    demo_root = Path.cwd() / ".agentos-demo"
    for db_path, root in ((home_root / "agentos.db", home_root),
                          (demo_root / "agentos.db", demo_root)):
        if db_path.exists():
            return db_path, root
    return home_root / "agentos.db", home_root


def _open(db_dir: str | None):
    db_path, root = _resolve_db_path(db_dir)
    return open_db(db_path), root


def _err(exc: BaseException) -> str:
    return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})


def tool_adapter(handler):
    """Hermes dispatches plugin tools as handler(args_dict, **kwargs); some
    hosts also forward stray schema kwargs (e.g. task_id from a shared tool
    envelope). Accept both shapes and merge them into one args dict."""
    def wrapped(args=None, **kwargs):
        if isinstance(args, dict):
            params = dict(args)
        elif args is None:
            params = {}
        else:
            params = {"__positional__": args}
        params.update(kwargs)
        return handler(params)
    wrapped.__name__ = getattr(handler, "__name__", "wrapped")
    return wrapped


# --- tool handlers ---------------------------------------------------------------
def handle_agentos_status(args: dict) -> str:
    """Goal counts by status + last 5 audit events + audit-chain integrity."""
    args = args or {}
    try:
        db, root = _open(args.get("db_dir"))
        goals_by_status = {
            row["status"]: row["n"]
            for row in db.conn.execute(
                "SELECT status, COUNT(*) AS n FROM goal GROUP BY status ORDER BY status")
        }
        events = [dict(row) for row in db.conn.execute(
            "SELECT seq, ts, actor, event_type FROM audit_event"
            " ORDER BY seq DESC LIMIT 5")]
        chain_ok, first_bad_seq = Journal(db).full_chain_check()
        return json.dumps({
            "success": True,
            "db_path": str(root / "agentos.db"),
            "total_goals": sum(goals_by_status.values()),
            "goals_by_status": goals_by_status,
            "last_audit_events": events,
            "chain_ok": chain_ok,
            "chain_first_bad_seq": first_bad_seq,
        })
    except Exception as e:  # noqa: BLE001 — wrapped per plugin contract
        return _err(e)


def handle_agentos_create_goal(args: dict) -> str:
    """Create a Goal + default spec placeholder; goal remains DRAFT."""
    args = args or {}
    try:
        concept_text = (args.get("concept_text") or "").strip()
        if not concept_text:
            raise ValueError("concept_text is required and must be non-empty")
        risk_tier = args.get("risk_tier") or "normal"
        if risk_tier not in _VALID_RISK_TIERS:
            raise ValueError(
                f"risk_tier must be one of {_VALID_RISK_TIERS}, got {risk_tier!r}")
        db, root = _open(args.get("db_dir"))
        eng = Engine(db, root)
        goal_id = eng.create_goal(concept_text, actor="hermes-plugin",
                                  risk_tier=risk_tier)
        # Default spec placeholder + single machine-checkable criterion.
        eng.refine_spec(
            goal_id,
            "[placeholder] Specification pending refinement for this concept.",
            criteria=[{"criterion_id": "tests_present", "kind": "tests_present"}],
            actor="hermes-plugin",
        )
        return json.dumps({
            "success": True,
            "goal_id": goal_id,
            "risk_tier": risk_tier,
            "state": "DRAFT",
            "criteria": ["tests_present"],
            "note": ("Goal created with a placeholder spec and a "
                     "'tests_present' acceptance criterion. It stays in state "
                     "DRAFT until the spec is refined and the goal is "
                     "(re-)activated."),
        })
    except Exception as e:  # noqa: BLE001
        return _err(e)


def handle_agentos_run_demo(args: dict) -> str:
    """Run the AgentOS vertical demo; return agentos.cli.run_demo's JSON verbatim."""
    args = args or {}
    try:
        flaky = bool(args.get("flaky", False))
        db_dir = args.get("db_dir")
        result = run_demo(worker_kind="fake", flaky=flaky,
                          db_path=str(db_dir) if db_dir else None)
        # Verbatim pass-through: run_demo already reports gate/eval results, and
        # worker-level failures surface inside the dict (e.g. {"error": ...}).
        return json.dumps(result)
    except Exception as e:  # noqa: BLE001
        return _err(e)


def handle_agentos_evidence_pack(args: dict) -> str:
    """Return the evidence-pack JSON for one goal (6000-char cap when huge)."""
    args = args or {}
    try:
        goal_id = (args.get("goal_id") or "").strip()
        if not goal_id:
            raise ValueError("goal_id is required")
        db, root = _open(args.get("db_dir"))
        built = build_evidence_pack(db, root, goal_id)
        pack = built["pack"]
        meta = {"success": True, "goal_id": goal_id,
                "sha256": built["sha256"], "path": built["path"]}
        text = json.dumps(pack, indent=2, sort_keys=True)
        if len(text) > MAX_PACK_CHARS:
            return json.dumps({**meta, "truncated": True,
                               "total_chars": len(text),
                               "pack_json": text[:MAX_PACK_CHARS]})
        return json.dumps({**meta, "truncated": False, "evidence_pack": pack})
    except Exception as e:  # noqa: BLE001
        return _err(e)
