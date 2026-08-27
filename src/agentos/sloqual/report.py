"""Final report generator: markdown summary from compare-result.json."""
from __future__ import annotations

import json
from pathlib import Path


def generate_markdown(ticket_dir: Path) -> str:
    ticket_dir = Path(ticket_dir)
    compare_path = ticket_dir / "reports" / "compare-result.json"
    compare = json.loads(compare_path.read_text(encoding="utf-8"))
    contract = json.loads(
        (ticket_dir / "slo-contract.json").read_text(encoding="utf-8"))
    lines: list[str] = []
    lines.append(f"# {contract['slo_id']} — Production-like SLO qualification "
                 f"report\n")
    lines.append(f"Contract version: `{contract['version']}` · "
                 f"frozen at `{contract.get('frozen_at')}` · "
                 f"self-hash `{compare['contract_sha256'][:16]}…`\n")
    lines.append(f"## Verdict: **{compare['verdict']}**\n")
    runs = ", ".join(f"`{r}`" for r in compare["run_ids"])
    lines.append(f"Runs compared: {runs}\n")
    lines.append("## SLO table\n")
    lines.append("| SLI | Scope | Threshold | Observed | 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|")
    for row in compare["slo_table"]:
        ci = row.get("ci") or [None, None]
        ci_text = (f"[{ci[0]}, {ci[1]}]" if ci[0] is not None else "n/a")
        lines.append(
            f"| `{row['slo']}` | {row['scope']} | {row['threshold']} | "
            f"{row.get('observed')} | {ci_text} | {row['verdict']} |")
    lines.append("")
    rev = compare["revocation"]
    lines.append("## S1-008 revocation security gate\n")
    lines.append(
        f"- trials (main run): **{rev['total_trials_main_run']}** "
        f"(minimum {100})\n"
        f"- trials by run: **{rev.get('trials_per_run', {})}**\n"
        f"- max observed enforcement latency: **{rev['max_observed_ms']} ms** "
        f"(limit ≤ {rev['limit_ms']} ms)\n"
        f"- post-revoke forbidden side effects: **{rev['violations']}**\n")
    lines.append("## Fail conditions\n")
    if compare["fail_conditions"]:
        for reason in compare["fail_conditions"]:
            lines.append(f"- FAIL: `{reason}`")
    else:
        lines.append("- none")
    lines.append("\n## Limits (why not full PASS)\n")
    if compare["limits"]:
        for limit in compare["limits"]:
            lines.append(f"- LIMIT: `{limit}`")
    else:
        lines.append("- none")
    rerun = compare["rerun_comparison"]
    lines.append("\n## Independent rerun comparison\n")
    lines.append(f"- status: {rerun.get('status')} · "
                 f"gross divergences (>50% relative diff): "
                 f"**{rerun.get('gross_divergences', 'n/a')}**\n")
    lines.append("Interpretation: PASS requires every proof complete; "
                 "PASS_WITH_LIMITS itemizes exactly which production-grade "
                 "proofs are still missing; any invariant/security failure "
                 "forces FAIL regardless of latency or throughput.\n")
    return "\n".join(lines) + "\n"
