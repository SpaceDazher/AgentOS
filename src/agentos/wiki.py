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


def _fm_escape(value: str) -> str:
    return str(value).replace('"', "'")


def _note(rel_path: str, fm: dict, summary: str, body_sections: list[str],
          generated: bool = True) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if v is None:
            continue
        lines.append(f"{k}: {_fm_escape(v)}")
    lines.append("---")
    lines.append("")
    if generated:
        lines.append("> [!warning] GENERATED NOTE")
        lines.append("> Deterministic projection of canonical SQLite state.")
        lines.append("> Edits are overwritten by `wiki-build`. Human notes go"
                     " to 10-/20-/90- folders via explicit import.")
        lines.append("")
    lines.append(f"# {fm.get('title', rel_path)}")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.extend(body_sections)
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

        # Home index -------------------------------------------------------
        goals = c.execute(
            "SELECT id, status, created_at FROM goal ORDER BY created_at"
            " DESC LIMIT 50").fetchall()
        experiments = c.execute(
            "SELECT id, hypothesis, status FROM experiment"
            " ORDER BY created_at DESC LIMIT 50").fetchall()
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
            ])
        (self.wiki / GENERATED_DIR / "Home.md").write_text(home,
                                                           encoding="utf-8")
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
                         f"Goal {gid} — {g['status']}.", body)
            (self.wiki / GENERATED_DIR / f"goal-{gid}.md").write_text(
                note, encoding="utf-8")
            counts["goals"] = counts.get("goals", 0) + 1

            # task + run notes (targets of the goal's links)
            for t in tasks:
                tn = _note(f"_generated/task-{t['id']}.md",
                           {"id": t["id"], "type": "task",
                            "title": t["title"], "status": t["status"],
                            "task_id": t["id"], "goal_id": gid,
                            "created_at": "", "updated_at": ""},
                           f"Task {t['id']} — {t['status']}.",
                           [f"Backlinks: [[goal-{gid}]]"])
                (self.wiki / GENERATED_DIR /
                 f"task-{t['id']}.md").write_text(tn, encoding="utf-8")
                counts["tasks"] = counts.get("tasks", 0) + 1
            for r in runs:
                rn = _note(f"_generated/run-{r['id']}.md",
                           {"id": r["id"], "type": "run",
                            "title": r["id"], "status": r["status"],
                            "run_id": r["id"], "goal_id": gid,
                            "created_at": "", "updated_at": ""},
                           f"Run {r['id']} — {r['status']}.",
                           [f"Terminal: {(r['terminal_reason'] or '')[:200]}",
                            f"Backlinks: [[goal-{gid}]]"])
                (self.wiki / GENERATED_DIR /
                 f"run-{r['id']}.md").write_text(rn, encoding="utf-8")
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
                 " advisory only (ADR-0006)"])
            (self.wiki / GENERATED_DIR /
             f"eval-{r['id']}.md").write_text(note, encoding="utf-8")
            counts["evals"] = counts.get("evals", 0) + 1

        # Experiments ---------------------------------------------------------
        for e in experiments:
            note = _note(
                f"_generated/experiment-{e['id']}.md",
                {"id": e["id"], "type": "experiment", "title": e["id"],
                 "status": e["status"], "experiment_id": e["id"],
                 "created_at": "", "updated_at": ""},
                f"Experiment **{e['status']}**.",
                ["## Hypothesis", e["hypothesis"],
                 "", "Decision policy: ADR-0008."])
            (self.wiki / GENERATED_DIR /
             f"experiment-{e['id']}.md").write_text(note, encoding="utf-8")
            counts["experiments"] = counts.get("experiments", 0) + 1

        # Stage-gates -> decisions folder ------------------------------------
        for sg in c.execute(
                "SELECT id, stage, decision, rationale FROM stage_gate"
                " ORDER BY created_at DESC LIMIT 100").fetchall():
            note = _note(
                f"_generated/stagegate-{sg['id']}.md",
                {"id": sg["id"], "type": "decision", "title":
                 f"stage gate {sg['stage']}", "decision": sg["decision"],
                 "status": "final", "created_at": "", "updated_at": ""},
                f"Stage gate **{sg['stage']}** → {sg['decision']}.",
                ["## Rationale", sg["rationale"]])
            (self.wiki / GENERATED_DIR /
             f"stagegate-{sg['id']}.md").write_text(note, encoding="utf-8")
            counts["stage_gates"] = counts.get("stage_gates", 0) + 1

        return {"notes_written": sum(counts.values()), "counts": counts}

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

        return {"files": len(md_files), "links_checked": len(links),
                "issues": [i.as_dict() for i in issues],
                "ok": not issues}
