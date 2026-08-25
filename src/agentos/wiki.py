"""Obsidian Knowledge Vault (Phase 3). See ADR-0007 and SPEC §10.

The wiki/ directory is a DETERMINISTIC PROJECTION of canonical SQLite state.
wiki-build regenerates generated notes; two consecutive builds over unchanged
canonical state produce a byte-identical tree. The wiki is never authoritative.

Human-authored notes live in human-owned folders and are imported explicitly
with provenance; generated notes are overwritten on rebuild.
"""
from __future__ import annotations

import gc
import json
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .ids import canonical_json

VAULT_DIRS = [
    "10-Architecture", "20-Specifications", "30-Evaluations",
    "40-Experiments", "50-Episodes", "60-Decisions", "70-Incidents",
    "80-Lessons", "90-Glossary", "_indexes", "_templates", "_generated",
]
GENERATED_DIR = "_generated"
HUMAN_DIRS = ("10-Architecture", "20-Specifications", "90-Glossary")

FRONTMATTER_KEYS = ["id", "type", "title", "status", "created_at",
                    "updated_at"]


def _rename_with_retry(source: Path, target: Path) -> None:
    """Rename a projection tree, tolerating short Windows handle races.

    Windows can briefly keep a directory handle alive after a completed
    ``glob``/file read.  Collect Python-owned iterators before the first
    attempt, then retry only the permission error used for that race.  The
    caller still owns the swap transaction and can restore its backup if the
    lock does not clear.
    """
    gc.collect()
    attempts = 8
    for attempt in range(attempts):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(min(0.05 * (2 ** attempt), 0.25))


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
    # JSON string quoting is a YAML-compatible scalar and, importantly,
    # escapes newlines so untrusted text cannot inject a second frontmatter
    # key or terminate the document header.
    return json.dumps(str(value), ensure_ascii=False)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the small scalar frontmatter dialect emitted by ``_note``.

    This intentionally reads only the header block; regexes over the whole
    Markdown body can mistake arbitrary prose for canonical references.
    """
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        if key in out:
            # Ambiguous canonical bindings are inadmissible.  Returning an
            # empty mapping makes evidence-pack inclusion fail closed; the
            # checker independently reports the duplicate key.
            return {}
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            try:
                out[key] = str(json.loads(raw))
                continue
            except json.JSONDecodeError:
                pass
        out[key] = raw.strip("'")
    return out


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
            # Generated wikilinks are canonical bindings, not retrieved
            # content.  Protect their targets while redacting surrounding
            # untrusted prose; otherwise a long but valid research id would be
            # mistaken for a token and turn a link into a dangling reference.
            links: list[str] = []

            def hold(match: re.Match[str]) -> str:
                target = match.group(1)
                label = match.group(2)
                links.append(target)
                placeholder = f"__AGENTOS_LINK_{len(links) - 1}__"
                # Keep a human/untrusted display label in the redaction pass;
                # protect only the canonical target binding.
                return f"[[{placeholder}|{label}]]" if label is not None \
                    else f"[[{placeholder}]]"

            text = re.sub(r"\[\[([^|\]]+)(?:\|([^\]]*))?\]\]", hold, str(text))
            text = re.sub(r"(?i)(api\s*[-_]?\s*key|apikey|secret|token|password)"
                          r"(\s*[=:]\s*)(\S+)", r"\1\2[REDACTED]", text)
            text = re.sub(r"\b[A-Za-z0-9_\-]{40,}\b", "[REDACTED-TOKEN]", text)
            for index, link in enumerate(links):
                text = text.replace(f"__AGENTOS_LINK_{index}__", link)
            return text

        def write_generated(rel_name: str, content: str) -> None:
            (self._staging / GENERATED_DIR).mkdir(parents=True, exist_ok=True)
            (self._staging / GENERATED_DIR / rel_name).write_text(
                content, encoding="utf-8")

        goals = c.execute(
            "SELECT id, status, created_at FROM goal ORDER BY created_at"
            " DESC").fetchall()
        experiments = c.execute(
            "SELECT e.id, COALESCE(e.goal_id, c.goal_id) AS goal_id,"
            " e.hypothesis, e.status, e.decision_rationale"
            " FROM experiment e JOIN campaign c ON c.id=e.campaign_id"
            " ORDER BY e.created_at DESC").fetchall()
        eval_defs = c.execute(
            "SELECT id, MAX(version) AS v, stage, metric, required"
            " FROM eval_definition GROUP BY id ORDER BY stage").fetchall()
        has_research_schema = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_campaign'"
        ).fetchone()
        research_campaigns = c.execute(
            "SELECT id, goal_id, topic, thresholds_json, manifest_sha256,"
            " created_at FROM research_campaign ORDER BY created_at, id"
        ).fetchall() if has_research_schema else []
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
                "",
                "## Research campaigns",
                *([f"- [[research-campaign-{r['id']}|{r['id']}]] —"
                   f" {r['topic']} (goal {r['goal_id']})"
                   for r in research_campaigns] or ["- (none)"]),
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
            goal_research = [r for r in research_campaigns
                             if r["goal_id"] == gid]
            body.extend([
                "",
                "## Research",
                *([f"- [[research-campaign-{r['id']}|{r['id']}]] — {r['topic']}"
                   for r in goal_research] or ["- (none)"]),
            ])
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

        # Research projection ------------------------------------------------
        # Only metadata, hashes, and canonical links are projected.  The
        # source table intentionally has no raw body column, and artifact
        # content is never read here.  Every generated research note carries
        # the exact owning goal in frontmatter.
        for campaign in research_campaigns:
            cid = campaign["id"]
            gid = campaign["goal_id"]
            sources = c.execute(
                "SELECT id, canonical_uri, title, source_type, content_sha256,"
                " verification_status, verifier, verification_method"
                " FROM research_source WHERE campaign_id=? AND goal_id=?"
                " ORDER BY id", (cid, gid)).fetchall()
            claims = c.execute(
                "SELECT id, text, claim_class FROM research_claim"
                " WHERE campaign_id=? AND goal_id=? ORDER BY id", (cid, gid)).fetchall()
            artifacts = c.execute(
                "SELECT id, kind, version, content_sha256, producer"
                " FROM research_artifact WHERE campaign_id=? AND goal_id=?"
                " ORDER BY kind, version, id", (cid, gid)).fetchall()
            evaluations = c.execute(
                "SELECT id, evaluation_version, result, artifact_chain_hash,"
                " reasons_json, limitations_json FROM research_evaluation"
                " WHERE campaign_id=? AND goal_id=? ORDER BY evaluation_version, id",
                (cid, gid)).fetchall()
            try:
                thresholds = json.loads(campaign["thresholds_json"] or "{}")
            except json.JSONDecodeError:
                thresholds = {}
            campaign_note = _note(
                f"_generated/research-campaign-{cid}.md",
                {"id": cid, "type": "research_campaign", "title": cid,
                 "status": "current", "goal_id": gid,
                 "created_at": campaign["created_at"], "updated_at": campaign["created_at"]},
                "Research campaign metadata; no retrieved source body is projected.",
                [f"Backlink: [[goal-{gid}]]",
                 f"Topic: {campaign['topic']}",
                 f"Manifest SHA-256: {campaign['manifest_sha256']}",
                 f"Thresholds: {canonical_json(thresholds)}",
                 "",
                 "## Sources",
                 *([f"- [[research-source-{s['id']}|{s['id']}]]"
                    for s in sources] or ["- (none)"]),
                 "",
                 "## Claims",
                 *([f"- [[research-claim-{cl['id']}|{cl['id']}]] — {cl['claim_class']}"
                    for cl in claims] or ["- (none)"]),
                 "",
                 "## Artifacts",
                 *([f"- [[research-artifact-{a['id']}|{a['kind']} v{a['version']}]]"
                    for a in artifacts] or ["- (none)"]),
                 "",
                 "## Evaluations",
                 *([f"- [[research-evaluation-{e['id']}|{e['result']} v{e['evaluation_version']}]]"
                    for e in evaluations] or ["- (none)"])],
                redact=redact)
            write_generated(f"research-campaign-{cid}.md", campaign_note)
            counts["research_campaigns"] = counts.get("research_campaigns", 0) + 1

            for source in sources:
                source_note = _note(
                    f"_generated/research-source-{source['id']}.md",
                    {"id": source["id"], "type": "research_source",
                     "title": source["title"], "status": source["verification_status"],
                     "source_id": source["id"], "goal_id": gid,
                     "created_at": "", "updated_at": ""},
                    "Source metadata only; raw retrieved content is excluded.",
                    [f"Backlink: [[research-campaign-{cid}]]",
                     f"Canonical URI: {source['canonical_uri']}",
                     f"Source type: {source['source_type']}",
                     f"Content SHA-256: {source['content_sha256']}",
                     f"Verification: {source['verification_status']}",
                     f"Verifier: {source['verifier'] or '(none)'}",
                     f"Method: {source['verification_method'] or '(none)'}"],
                    redact=redact)
                write_generated(f"research-source-{source['id']}.md", source_note)
                counts["research_sources"] = counts.get("research_sources", 0) + 1

            for claim in claims:
                links = c.execute(
                    "SELECT source_id FROM research_claim_source"
                    " WHERE claim_id=? AND goal_id=? ORDER BY source_id",
                    (claim["id"], gid)).fetchall()
                claim_note = _note(
                    f"_generated/research-claim-{claim['id']}.md",
                    {"id": claim["id"], "type": "research_claim",
                     "title": claim["id"], "status": "asserted",
                     "claim_id": claim["id"], "goal_id": gid,
                     "created_at": "", "updated_at": ""},
                    "Claim text is untrusted bundle data and is redacted before projection.",
                    [f"Backlink: [[research-campaign-{cid}]]",
                     f"Class: {claim['claim_class']}",
                     "",
                     "## Claim",
                     claim["text"],
                     "",
                     "## Sources",
                     *([f"- [[research-source-{s['source_id']}|{s['source_id']}]]"
                        for s in links] or ["- (none)"])],
                    redact=redact)
                write_generated(f"research-claim-{claim['id']}.md", claim_note)
                counts["research_claims"] = counts.get("research_claims", 0) + 1

            for artifact in artifacts:
                artifact_note = _note(
                    f"_generated/research-artifact-{artifact['id']}.md",
                    {"id": artifact["id"], "type": "research_artifact",
                     "title": f"{artifact['kind']} v{artifact['version']}",
                     "status": "current", "artifact_id": artifact["id"],
                     "goal_id": gid, "created_at": "", "updated_at": ""},
                    "Versioned artifact metadata only; artifact body is excluded.",
                    [f"Backlink: [[research-campaign-{cid}]]",
                     f"Kind: {artifact['kind']}",
                     f"Version: {artifact['version']}",
                     f"Content SHA-256: {artifact['content_sha256']}",
                     f"Producer: {artifact['producer']}"],
                    redact=redact)
                write_generated(f"research-artifact-{artifact['id']}.md", artifact_note)
                counts["research_artifacts"] = counts.get("research_artifacts", 0) + 1

            for evaluation in evaluations:
                try:
                    reasons = json.loads(evaluation["reasons_json"] or "[]")
                except json.JSONDecodeError:
                    reasons = []
                try:
                    limitations = json.loads(evaluation["limitations_json"] or "[]")
                except json.JSONDecodeError:
                    limitations = []
                evaluation_note = _note(
                    f"_generated/research-evaluation-{evaluation['id']}.md",
                    {"id": evaluation["id"], "type": "research_evaluation",
                     "title": f"{evaluation['result']} v{evaluation['evaluation_version']}",
                     "status": evaluation["result"], "evaluation_id": evaluation["id"],
                     "goal_id": gid, "created_at": "", "updated_at": ""},
                    "Append-only deterministic research evaluation.",
                    [f"Backlink: [[research-campaign-{cid}]]",
                     f"Result: {evaluation['result']}",
                     f"Artifact chain hash: {evaluation['artifact_chain_hash']}",
                     "",
                     "## Reasons",
                     *([f"- {reason}" for reason in reasons] or ["- none"]),
                     "",
                     "## Limitations",
                     *([f"- {limit}" for limit in limitations] or ["- none"])],
                    redact=redact)
                write_generated(f"research-evaluation-{evaluation['id']}.md", evaluation_note)
                counts["research_evaluations"] = counts.get("research_evaluations", 0) + 1

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
                " ORDER BY created_at DESC").fetchall():
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
        for sg in c.execute("SELECT id FROM stage_gate").fetchall():
            canonical_names.add(f"stagegate-{sg['id']}.md")
        for rc in research_campaigns:
            canonical_names.add(f"research-campaign-{rc['id']}.md")
            gid = rc["goal_id"]
            for rs in c.execute(
                    "SELECT id FROM research_source WHERE campaign_id=? AND goal_id=?",
                    (rc["id"], gid)).fetchall():
                canonical_names.add(f"research-source-{rs['id']}.md")
            for cl in c.execute(
                    "SELECT id FROM research_claim WHERE campaign_id=? AND goal_id=?",
                    (rc["id"], gid)).fetchall():
                canonical_names.add(f"research-claim-{cl['id']}.md")
            for ra in c.execute(
                    "SELECT id FROM research_artifact WHERE campaign_id=? AND goal_id=?",
                    (rc["id"], gid)).fetchall():
                canonical_names.add(f"research-artifact-{ra['id']}.md")
            for reval in c.execute(
                    "SELECT id FROM research_evaluation WHERE campaign_id=? AND goal_id=?",
                    (rc["id"], gid)).fetchall():
                canonical_names.add(f"research-evaluation-{reval['id']}.md")

        # R7 TRUE atomic swap: the staging dir IS fully built, so replacing
        # the live _generated is a single rename — no incremental copytree
        # that can leave a partial projection. Old notes (stale records) are
        # dropped by construction: only canonical names exist in staging.
        staged_gen = self._staging / GENERATED_DIR
        for p in sorted(staged_gen.glob("*.md")):
            if p.name not in canonical_names:
                p.unlink()
        removed = 0
        backup = gen.parent / (gen.name + ".old-" + uuid.uuid4().hex)
        swap_ok = False
        old_moved = False
        try:
            if gen.exists():
                _rename_with_retry(gen, backup)  # move OLD away (atomic)
                old_moved = True
                removed = len(list(backup.glob("*.md")))
            _rename_with_retry(staged_gen, gen)  # move NEW in (atomic)
            swap_ok = True
        except Exception:
            if old_moved and backup.exists() and not gen.exists():
                _rename_with_retry(backup, gen)  # roll back old projection
            raise
        finally:
            # Keep the old tree available if swapping failed before rollback;
            # successful swaps can safely retire it.  The random suffix avoids
            # collisions between concurrent/restarted builders.
            if swap_ok:
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
            fm = parse_frontmatter(text)
            fm_lines = m.group(1).splitlines()
            fm_ids = [ln.split(":", 1)[0].strip()
                      for ln in fm_lines if ":" in ln]
            missing = [k for k in FRONTMATTER_KEYS if k not in fm_ids]
            if missing:
                issues.append(CheckIssue(
                    "invalid_frontmatter", rel,
                    f"missing keys: {missing}"))
            duplicates = sorted({key for key in fm_ids
                                 if fm_ids.count(key) > 1})
            if duplicates:
                issues.append(CheckIssue(
                    "invalid_frontmatter", rel,
                    f"duplicate keys: {duplicates}"))
            nid = fm.get("id")
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
        if c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_campaign'"
        ).fetchone():
            # IDs are globally unique, but that is not sufficient for a
            # projection check: a note can still claim another goal in its
            # frontmatter.  Keep explicit ownership maps for every research
            # object type and validate them below.
            research_object_owners = {
                "research_campaign": {r["id"]: r["goal_id"] for r in
                                       c.execute("SELECT id, goal_id FROM research_campaign")},
                "research_source": {r["id"]: r["goal_id"] for r in
                                    c.execute("SELECT id, goal_id FROM research_source")},
                "research_claim": {r["id"]: r["goal_id"] for r in
                                   c.execute("SELECT id, goal_id FROM research_claim")},
                "research_artifact": {r["id"]: r["goal_id"] for r in
                                      c.execute("SELECT id, goal_id FROM research_artifact")},
                "research_evaluation": {r["id"]: r["goal_id"] for r in
                                         c.execute("SELECT id, goal_id FROM research_evaluation")},
            }
            canonical.update({
                "research_campaign_id": {r["id"] for r in
                                          c.execute("SELECT id FROM research_campaign")},
                "source_id": {r["id"] for r in
                               c.execute("SELECT id FROM research_source")},
                "claim_id": {r["id"] for r in
                              c.execute("SELECT id FROM research_claim")},
                "artifact_id": {r["id"] for r in
                                 c.execute("SELECT id FROM research_artifact")},
                "evaluation_id": {r["id"] for r in
                                   c.execute("SELECT id FROM research_evaluation")},
            })
        else:
            research_object_owners = {}
        for p in md_files:
            rel = str(p.relative_to(self.wiki))
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(text)
            object_type = fm.get("type", "")
            object_id = fm.get("id", "")
            object_owner = research_object_owners.get(object_type, {}).get(object_id)
            note_goal = fm.get("goal_id", "")
            if object_owner is not None and note_goal != object_owner:
                issues.append(CheckIssue(
                    "ownership_mismatch", rel,
                    f"{object_type} {object_id} belongs to goal {object_owner}, "
                    f"not frontmatter goal {note_goal or '(none)'}"))
            for key, valid_ids in canonical.items():
                ref = fm.get(key)
                if ref and ref not in valid_ids:
                    issues.append(CheckIssue(
                        "dangling_ref", rel,
                        f"{key}={ref} not in canonical DB"))
                if ref and key.endswith("_id"):
                    type_for_ref = {
                        "research_campaign_id": "research_campaign",
                        "source_id": "research_source",
                        "claim_id": "research_claim",
                        "artifact_id": "research_artifact",
                        "evaluation_id": "research_evaluation",
                    }.get(key)
                    owner = (research_object_owners.get(type_for_ref, {}).get(ref)
                             if type_for_ref else None)
                    if owner is not None and note_goal != owner:
                        issues.append(CheckIssue(
                            "ownership_mismatch", rel,
                            f"{key}={ref} belongs to goal {owner}, "
                            f"not frontmatter goal {note_goal or '(none)'}"))
            # Use the same spaced-name-aware scanner as build redaction.
            for hit_line in leak_scan(text):
                issues.append(CheckIssue(
                    "secret_leak", rel,
                    f"unredacted secret: {hit_line}"))

        return {"files": len(md_files), "links_checked": len(links),
                "issues": [i.as_dict() for i in issues],
                "ok": not issues}
