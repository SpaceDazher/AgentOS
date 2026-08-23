"""Obsidian Knowledge Vault (Phase 3). See ADR-0007 and SPEC §10.

The wiki/ directory is a DETERMINISTIC PROJECTION of canonical SQLite state.
wiki-build regenerates generated notes; two consecutive builds over unchanged
canonical state produce a byte-identical tree. The wiki is never authoritative.

Human-authored notes live in human-owned folders and are imported explicitly
with provenance; generated notes are overwritten on rebuild.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

VAULT_DIRS = [
    "10-Architecture", "20-Specifications", "30-Evaluations",
    "40-Experiments", "50-Episodes", "60-Decisions", "70-Incidents",
    "80-Lessons", "90-Glossary", "_indexes", "_templates", "_generated",
]
GENERATED_DIR = "_generated"
HUMAN_DIRS = ("10-Architecture", "20-Specifications", "90-Glossary")

FRONTMATTER_KEYS = ["id", "type", "title", "status", "created_at",
                    "updated_at"]


@dataclass
class CheckIssue:
    kind: str        # broken_link | duplicate_id | invalid_frontmatter |
                     # dangling_ref | orphan_note
    note: str
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "note": self.note, "detail": self.detail}


def leak_scan(text: str) -> list[str]:
    """Lines that still look like unredacted secret assignments (module-level:
    used by wiki-check to verify the projection)."""
    hits = []
    for line in text.splitlines():
        m = re.match(
            r"(?i).*\b(api\s*[-_]?\s*key|apikey|secret|token|password)"
            r"\s*[=:]\s*(\S+)", line)
        if m and "REDACTED" not in m.group(2):
            hits.append(line.strip()[:80])
    return hits


def _fm_escape(value: str) -> str:
    return str(value).replace('"', "'")


def _note(rel_path: str, fm: dict, summary: str, body_sections: list[str],
          generated: bool = True, redact=None) -> str:
    """Compose a note; EVERY text (frontmatter values, title, summary, body)
    passes through `redact` so untrusted fields cannot leak into the vault."""
    _red = redact or (lambda t: t)
    lines = ["---"]
    for k, v in fm.items():
        if v is None:
            continue
        lines.append(f"{k}: {_fm_escape(_red(str(v)))}")
    lines.append("---")
    lines.append("")
    if generated:
        lines.append("> [!warning] GENERATED NOTE")
        lines.append("> Deterministic projection of canonical SQLite state.")
        lines.append("> Edits are overwritten by `wiki-build`. Human notes go"
                     " to 10-/20-/90- folders via explicit import.")
        lines.append("")
    lines.append(f"# {_red(str(fm.get('title', rel_path)))}")
    lines.append("")
    lines.append(_red(summary))
    lines.append("")
    lines.extend(_red(s) for s in body_sections)
    return "\n".join(lines) + "\n"


class WikiBuilder:
    def __init__(self, db, repo_root: str | Path,
                 wiki_dir: str | Path | None = None):
        self.db = db
        self.root = Path(repo_root)
        self.wiki = Path(wiki_dir) if wiki_dir else self.root / "wiki"

    # -- build ---------------------------------------------------------------
    def build(self) -> dict:
        for d in VAULT_DIRS:
            (self.wiki / d).mkdir(parents=True, exist_ok=True)
        c = self.db.conn
        counts: dict[str, int] = {}
        # R6: build into a STAGING directory; _generated is atomically
        # swapped at the end so a mid-build failure cannot leave a mixed
        # projection.
        # R7: staging MUST live beside the vault — rename() across volumes
        # (C: temp -> D: vault) fails with OSError EXDEV.
        self._staging = Path(tempfile.mkdtemp(prefix=".wiki-stage-",
                                              dir=str(self.wiki)))

        # Redaction before any content reaches the vault (R5/R7): applied to
        # EVERY untrusted text field via the _note writer itself, so no field
        # can bypass it. Matches spaced forms too ('api key = v').
        def redact(text: str) -> str:
            text = re.sub(r"(?i)(api\s*[-_]?\s*key|apikey|secret|token|password)"
                          r"(\s*[=:]\s*)(\S+)", r"\1\2[REDACTED]", text)
            text = re.sub(r"\b[A-Za-z0-9_\-]{40,}\b", "[REDACTED-TOKEN]", text)
            return text

        def write_generated(rel_name: str, content: str) -> None:
            (self._staging / GENERATED_DIR).mkdir(parents=True, exist_ok=True)
            (self._staging / GENERATED_DIR / rel_name).write_text(
                content, encoding="utf-8")

        goals = c.execute(
            "SELECT id, status, created_at FROM goal ORDER BY created_at"
            " DESC LIMIT 50").fetchall()
        experiments = c.execute(
            "SELECT id, goal_id, hypothesis, status, decision_rationale"
            " FROM experiment ORDER BY created_at DESC LIMIT 50").fetchall()
        eval_defs = c.execute(
            "SELECT id, MAX(version) AS v, stage, metric, required"
            " FROM eval_definition GROUP BY id ORDER BY stage").fetchall()
        home = _note(
            "_generated/Home.md",
            {"id": "home", "type": "index", "title": "AgentOS Vault",
             "status": "current", "created_at": "", "updated_at": ""},
            "Deterministic projection of AgentOS canonical state.",
            [
                "## Goals",
                *([f"- [[goal-{g['id']}|{g['id']}]] — {g['status']}"
                   for g in goals] or ["- (none)"]),
                "",
                "## Experiments",
                *([f"- [[experiment-{e['id']}|{e['id']}]] — {e['status']}"
                   for e in experiments] or ["- (none)"]),
                "",
                "## Eval definitions",
                *([f"- [[eval-{r['id']}|{r['id']}@{r['v']}]] ({r['stage']},"
                   f" {'required' if r['required'] else 'advisory'})"
                   for r in eval_defs] or ["- (none)"]),
            ], redact=redact)
        write_generated("Home.md", home)
        counts["home"] = 1

        # Goals + tasks + runs ----------------------------------------------
        for g in goals:
            gid = g["id"]
            tasks = c.execute(
                "SELECT id, title, status FROM task WHERE goal_id=?",
                (gid,)).fetchall()
            runs = c.execute(
                "SELECT id, status, terminal_reason FROM run WHERE goal_id=?",
                (gid,)).fetchall()
            gate = c.execute(
                "SELECT result, rationale FROM gate WHERE goal_id=?"
                " ORDER BY rowid DESC LIMIT 1", (gid,)).fetchone()
            body = [
                "## Tasks",
                *([f"- [[task-{t['id']}|{t['title']}]] — {t['status']}"
                   for t in tasks] or ["- (none)"]),
                "",
                "## Runs",
                *([f"- [[run-{r['id']}|{r['id']}]] — {r['status']}"
                   f" ({(r['terminal_reason'] or '')[:60]})" for r in runs]
                  or ["- (none)"]),
                "",
                "## Gate",
                f"- {gate['result'] if gate else 'n/a'}: "
                f"{(gate['rationale'] if gate else '')[:200]}",
            ]
            note = _note(f"_generated/goal-{gid}.md",
                         {"id": gid, "type": "goal", "title": gid,
                          "status": g["status"], "goal_id": gid,
                          "created_at": g["created_at"],
                          "updated_at": g["created_at"]},
                         f"Goal {gid} — {g['status']}.", body,
                         redact=redact)
            write_generated(f"goal-{gid}.md", note)
            counts["goals"] = counts.get("goals", 0) + 1

            # task + run notes (targets of the goal's links); task titles and
            # terminal reasons are UNTRUSTED text -> redacted by _note
            for t in tasks:
                tn = _note(f"_generated/task-{t['id']}.md",
                           {"id": t["id"], "type": "task",
                            "title": t["title"], "status": t["status"],
                            "task_id": t["id"], "goal_id": gid,
                            "created_at": "", "updated_at": ""},
                           f"Task {t['id']} — {t['status']}.",
                           [f"Backlinks: [[goal-{gid}]]"], redact=redact)
                write_generated(f"task-{t['id']}.md", tn)
                counts["tasks"] = counts.get("tasks", 0) + 1
            for r in runs:
                rn = _note(f"_generated/run-{r['id']}.md",
                           {"id": r["id"], "type": "run",
                            "title": r["id"], "status": r["status"],
                            "run_id": r["id"], "goal_id": gid,
                            "created_at": "", "updated_at": ""},
                           f"Run {r['id']} — {r['status']}.",
                           [f"Terminal: {(r['terminal_reason'] or '')[:200]}",
                            f"Backlinks: [[goal-{gid}]]"], redact=redact)
                write_generated(f"run-{r['id']}.md", rn)
                counts["runs"] = counts.get("runs", 0) + 1

        # Eval definitions ---------------------------------------------------
        for r in eval_defs:
            note = _note(
                f"_generated/eval-{r['id']}.md",
                {"id": r["id"], "type": "eval_definition",
                 "title": f"{r['id']}@{r['v']}", "stage": r["stage"],
                 "metric": r["metric"], "status": "current",
                 "created_at": "", "updated_at": ""},
                f"{'Required' if r['required'] else 'Advisory'} eval for"
                f" stage **{r['stage']}**, metric `{r['metric']}`.",
                [f"- latest version: {r['v']}",
                 "- authority: deterministic checks block; llm_judge is"
                 " advisory only (ADR-0006)"], redact=redact)
            write_generated(f"eval-{r['id']}.md", note)
            counts["evals"] = counts.get("evals", 0) + 1

        # Experiments ---------------------------------------------------------
        for e in experiments:
            note = _note(
                f"_generated/experiment-{e['id']}.md",
                {"id": e["id"], "type": "experiment", "title": e["id"],
                 "status": e["status"], "experiment_id": e["id"],
                 "goal_id": e["goal_id"],
                 "created_at": "", "updated_at": ""},
                f"Experiment **{e['status']}**.",
                ["## Hypothesis", redact(e["hypothesis"]),
                 "",
                 "## Decision rationale",
                 redact(e["decision_rationale"] or "(pending)"),
                 "", "Decision policy: ADR-0008."], redact=redact)
            write_generated(f"experiment-{e['id']}.md", note)
            counts["experiments"] = counts.get("experiments", 0) + 1

        # Stage-gates -> decisions folder ------------------------------------
        for sg in c.execute(
                "SELECT id, stage, decision, rationale, goal_id FROM stage_gate"
                " ORDER BY created_at DESC LIMIT 100").fetchall():
            note = _note(
                f"_generated/stagegate-{sg['id']}.md",
                {"id": sg["id"], "type": "decision", "title":
                 f"stage gate {sg['stage']}", "decision": sg["decision"],
                 "status": "final", "created_at": "", "updated_at": "",
                 "goal_id": sg["goal_id"] or ""},
                f"Stage gate **{sg['stage']}** → {sg['decision']}.",
                ["## Rationale", redact(sg["rationale"])], redact=redact)
            write_generated(f"stagegate-{sg['id']}.md", note)
            counts["stage_gates"] = counts.get("stage_gates", 0) + 1

        # R5: staging + atomic swap — remove stale generated notes so a note
        # whose canonical record vanished does not survive a rebuild.
        gen = self.wiki / GENERATED_DIR
        canonical_names = set()
        for g in goals:
            gid = g["id"]
            canonical_names.add(f"goal-{gid}.md")
            for t in c.execute("SELECT id FROM task WHERE goal_id=?",
                               (gid,)).fetchall():
                canonical_names.add(f"task-{t['id']}.md")
            for r in c.execute("SELECT id FROM run WHERE goal_id=?",
                               (gid,)).fetchall():
                canonical_names.add(f"run-{r['id']}.md")
        canonical_names.add("Home.md")
        for r in eval_defs:
            canonical_names.add(f"eval-{r['id']}.md")
        for e in experiments:
            canonical_names.add(f"experiment-{e['id']}.md")
        for sg in c.execute("SELECT id FROM stage_gate LIMIT 100").fetchall():
            canonical_names.add(f"stagegate-{sg['id']}.md")

        # R7 TRUE atomic swap: the staging dir IS fully built, so replacing
        # the live _generated is a single rename — no incremental copytree
        # that can leave a partial projection. Old notes (stale records) are
        # dropped by construction: only canonical names exist in staging.
        staged_gen = self._staging / GENERATED_DIR
        for p in sorted(staged_gen.glob("*.md")):
            if p.name not in canonical_names:
                p.unlink()
        removed = 0
        backup = gen.parent / (gen.name + ".old-" + str(int(time.time())))
        if gen.exists():
            gen.rename(backup)          # move OLD away (atomic)
            removed = len(list(backup.glob("*.md")))
        try:
            staged_gen.rename(gen)      # move NEW in (atomic)
        except Exception:
            if backup.exists() and not gen.exists():
                backup.rename(gen)      # roll back: old projection restored
            raise
        finally:
            shutil.rmtree(backup, ignore_errors=True)
            shutil.rmtree(self._staging, ignore_errors=True)
        return {"notes_written": sum(counts.values()), "counts": counts,
                "stale_removed": removed}

    # -- check -----------------------------------------------------------------
    def check(self) -> dict:
        issues: list[CheckIssue] = []
        md_files = sorted(self.wiki.rglob("*.md"))
        ids: dict[str, str] = {}
        links: list[tuple[str, str]] = []   # (source note, target name)

        for p in md_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            rel = str(p.relative_to(self.wiki))
            # frontmatter parse
            m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
            if not m:
                issues.append(CheckIssue(
                    "invalid_frontmatter", rel, "no frontmatter block"))
                continue
            fm_lines = m.group(1).splitlines()
            fm_ids = [ln.split(":", 1)[0] for ln in fm_lines if ":" in ln]
            missing = [k for k in FRONTMATTER_KEYS if k not in fm_ids]
            if missing:
                issues.append(CheckIssue(
                    "invalid_frontmatter", rel,
                    f"missing keys: {missing}"))
            idm = re.search(r"^id:\s*(.+)$", m.group(1), re.MULTILINE)
            nid = idm.group(1).strip() if idm else None
            if nid:
                if nid in ids:
                    issues.append(CheckIssue(
                        "duplicate_id", rel, f"id {nid} also in {ids[nid]}"))
                ids[nid] = rel
            for target in re.findall(r"\[\[([^|\]#]+)", text):
                links.append((rel, target.strip()))

        # broken links: target must be an existing note stem or id
        stems = {p.stem for p in md_files}
        known = set(stems) | set(ids)
        for src, tgt in links:
            if tgt not in known:
                issues.append(CheckIssue(
                    "broken_link", src, f"[[{tgt}]] not found"))

        # unexpected orphans: .md outside the known vault layout
        for p in md_files:
            rel = str(p.relative_to(self.wiki))
            top = rel.replace("\\", "/").split("/")[0]
            if top not in VAULT_DIRS:
                issues.append(CheckIssue(
                    "orphan_note", rel, f"'{top}' is not a vault folder"))

        # R5: dangling canonical references — frontmatter refs (goal_id etc.)
        # must exist in canonical state; secret patterns must never appear.
        c = self.db.conn
        canonical = {
            "goal_id": {r["id"] for r in c.execute("SELECT id FROM goal")},
            "task_id": {r["id"] for r in c.execute("SELECT id FROM task")},
            "run_id": {r["id"] for r in c.execute("SELECT id FROM run")},
            "experiment_id": {r["id"] for r in
                              c.execute("SELECT id FROM experiment")},
        }
        secret_re = re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password)\s*[=:]\s*(?!"
            r"\[REDACTED\])\S+")
        for p in md_files:
            rel = str(p.relative_to(self.wiki))
            text = p.read_text(encoding="utf-8", errors="replace")
            m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
            fm = m.group(1) if m else ""
            for key, valid_ids in canonical.items():
                idm = re.search(rf"^{key}:\s*(\S+)\s*$", fm, re.MULTILINE)
                if idm and idm.group(1) not in valid_ids:
                    issues.append(CheckIssue(
                        "dangling_ref", rel,
                        f"{key}={idm.group(1)} not in canonical DB"))
            # R7: leak detection uses the SAME spaced-name-aware pattern as
            # build-redaction (leak_scan), so a redaction gap cannot pass.
            for hit_line in leak_scan(text):
                issues.append(CheckIssue(
                    "secret_leak", rel,
                    f"unredacted secret: {hit_line}"))

        return {"files": len(md_files), "links_checked": len(links),
                "issues": [i.as_dict() for i in issues],
                "ok": not issues}
