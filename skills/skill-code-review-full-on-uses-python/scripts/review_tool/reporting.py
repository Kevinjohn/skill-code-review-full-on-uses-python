"""Generated review views and terminal audit gates."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checks import check_review
from .evidence import validate_review_spec_version
from .errors import ReviewToolError
from .io import (
    atomic_write,
    canonical_bytes,
    digest_bytes,
    ensure_review_root,
    load_json,
    load_jsonl,
    safe_child,
    state_digest,
)
from .security import has_declared_security_profile, security_level
from .transactions import recover


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_run(root: Path) -> dict[str, Any]:
    run = load_json(root / "run.json")
    if not isinstance(run, dict):
        raise ReviewToolError("run.json must contain an object; re-initialize the review")
    validate_review_spec_version(run.get("reviewSpecVersion"))
    if not has_declared_security_profile(run):
        raise ReviewToolError(
            "run.json securityProfile is required; re-initialize the review"
        )
    return run


GENERATED = [
    "README.md",
    "coverage-ledger.md",
    "findings-index.md",
    "findings/P0.md",
    "findings/P1.md",
    "findings/P2.md",
    "findings/P3.md",
    "findings/P4.md",
    "findings/withdrawn.md",
    "rejected-candidates.md",
    "nits.md",
    "suggestions.md",
    "questions.md",
    "test-gaps.md",
    "documentation.md",
    "security-deferrals.md",
    "validation-log.md",
    "audit-report.md",
]


def _inline_code(value: str) -> str:
    runs = re.findall(r"`+", value)
    fence = "`" * (max((len(run) for run in runs), default=0) + 1)
    padding = (
        " "
        if value.startswith(("`", " ")) or value.endswith(("`", " "))
        else ""
    )
    return f"{fence}{padding}{value}{padding}{fence}"


def _format_location(location: Any) -> str:
    if not isinstance(location, dict) or not isinstance(location.get("path"), str):
        return "not recorded"
    path = location["path"].strip()
    if not path:
        return "not recorded"
    start = location.get("startLine")
    end = location.get("endLine")
    if not isinstance(start, int) or isinstance(start, bool) or start < 1:
        return _inline_code(path)
    suffix = f":{start}"
    if isinstance(end, int) and not isinstance(end, bool) and end > start:
        suffix += f"-{end}"
    return _inline_code(f"{path}{suffix}")


def _format_locations(row: dict) -> str:
    additional = row.get("additionalLocations")
    if not isinstance(additional, list):
        additional = []
    locations = [row.get("primaryLocation"), *additional]
    rendered = []
    for location in locations:
        value = _format_location(location)
        if value != "not recorded" and value not in rendered:
            rendered.append(value)
    return ", ".join(rendered) or "not recorded"


def _format_value(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "not recorded"
    if isinstance(value, list):
        values = [_format_value(item) for item in value]
        return "; ".join(item for item in values if item != "not recorded") or "not recorded"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _combine(*values: Any, labels: tuple[str, ...] | None = None) -> str:
    rendered = [_format_value(value) for value in values]
    present = [(index, value) for index, value in enumerate(rendered) if value != "not recorded"]
    if not present:
        return "not recorded"
    if labels:
        return "; ".join(f"{labels[index]}: {value}" for index, value in present)
    return "; ".join(value for _, value in present)


def _display_title(row: dict) -> str:
    title = str(row.get("title") or "Untitled")
    severity = row.get("severity")
    if isinstance(severity, str):
        title = re.sub(rf"^\[{re.escape(severity)}\]\s+", "", title)
    return title


def _observation_view(title: str, rows: list[dict]) -> bytes:
    lines = [f"# {title}", ""]
    if not rows:
        lines.extend(["No records in this category.", ""])
    for row in rows:
        label = row.get("findingId") or row.get("id")
        assigned_severity = row.get("severity")
        severity = assigned_severity or "not assigned"
        anchor = re.sub(r"[^a-z0-9-]", "-", str(label).lower()).strip("-")
        display_title = _display_title(row)
        heading = f"## {label} — {display_title}"
        if assigned_severity:
            heading = f"## {label} — [{assigned_severity}] {display_title}"
        lines.extend([
            f'<a id="{anchor}"></a>',
            heading,
            "",
            f"- **Observation:** {_format_value(row.get('id'))}",
            f"- **Disposition:** {_format_value(row.get('disposition'))}",
            f"- **Category:** {_format_value(row.get('category'))}",
            f"- **Severity:** {severity}",
            f"- **Materiality and rationale:** {_combine(row.get('materiality'), row.get('materialityRationale'))}",
            f"- **Confidence:** {_format_value(row.get('confidence'))}",
            f"- **Locations:** {_format_locations(row)}",
            f"- **Affected components and configurations:** {_combine(row.get('affectedComponents'), row.get('affectedConfigurations'), row.get('affectedDeployments'), labels=('Components', 'Configurations', 'Deployments'))}",
            f"- **Trigger or failure sequence:** {_format_value(row.get('trigger'))}",
            f"- **Expected / actual:** {_combine(row.get('expected'), row.get('actual'), labels=('Expected', 'Actual'))}",
            f"- **Impact, likelihood, and blast radius:** {_combine(row.get('impact'), row.get('likelihood'), row.get('blastRadius'), labels=('Impact', 'Likelihood', 'Blast radius'))}",
            f"- **Evidence and reachability:** {_combine(row.get('evidence'), row.get('reachability'), labels=('Evidence', 'Reachability'))}",
            f"- **Existing checks and tests:** {_format_value(row.get('existingChecks'))}",
            f"- **Smallest reproduction:** {_format_value(row.get('reproduction'))}",
            f"- **Remediation and regression test:** {_combine(row.get('recommendation'), row.get('regressionTest'), labels=('Remediation', 'Regression test'))}",
            f"- **Counterargument:** {_format_value(row.get('counterargument'))}",
            f"- **Residual uncertainty:** {_format_value(row.get('residualUncertainty'))}",
            "",
        ])
    return ("\n".join(lines)).encode()


def _observation_index(rows: list[dict]) -> bytes:
    lines = ["# Findings index", ""]
    if not rows:
        lines.extend(["No records in this category.", ""])
    for row in rows:
        finding = row.get("findingId")
        severity = row.get("severity") or "unassigned"
        anchor = re.sub(r"[^a-z0-9-]", "-", str(finding).lower()).strip("-")
        if row.get("disposition") == "withdrawn":
            target = f"findings/withdrawn.md#{anchor}"
        elif isinstance(severity, str) and severity in {
            "P0",
            "P1",
            "P2",
            "P3",
            "P4",
        }:
            target = f"findings/{severity}.md#{anchor}"
        else:
            target = None
        label = f"{finding} — [{severity}] {_display_title(row)}"
        linked = f"[{label}]({target})" if target else label
        lines.append(f"- {linked} — {_format_locations(row)}")
    lines.append("")
    return ("\n".join(lines)).encode()


def generate(root: Path) -> dict:
    root = ensure_review_root(root)
    recover(root)
    run = _load_run(root)
    paths = load_jsonl(root / "paths.jsonl")
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")
    outputs: dict[str, bytes] = {}
    level = security_level(run)
    security_exclusions = [
        row for row in paths
        if isinstance(row.get("exclusion"), dict)
        and row["exclusion"].get("category") == "security_profile"
    ]
    security_assessment = {
        "off": "NOT PERFORMED",
        "low": "PASSIVE",
        "medium": "STATIC",
        "high": "ACTIVE ISOLATED",
    }.get(level, "INVALID")
    scope_note = "declared non-security scope" if level == "off" else f"declared {level} security scope"
    severity_counts = {
        severity: sum(
            row.get("severity") == severity and row.get("disposition") == "validated"
            for row in observations
        )
        for severity in ("P0", "P1", "P2", "P3", "P4")
    }
    severity_summary = " · ".join(
        f"[{severity}](findings/{severity}.md): {count}"
        for severity, count in severity_counts.items()
    )
    outputs["README.md"] = (f"# Exhaustive repository review\n\n- Repository: {run.get('repositoryIdentity')}\n- Revision: {run.get('baselineCommit')} / {run.get('currentEpoch')}\n- Specification epoch: {run.get('specEpoch')}\n- Lifecycle: {run.get('status')}\n- Runtime capability: {run.get('runtimeCapability')}\n- Security level: {level}\n- Security assessment: {security_assessment}\n- Security-profile excluded paths: {len(security_exclusions)}\n- Verdict: {run.get('verdict') or 'nonterminal checkpoint'} ({scope_note})\n- Baseline paths: {len(paths)}\n- Work units: {len(units)}\n- Observations: {len(observations)}\n- Validations: {len(validations)}\n- Audit objections: {len(objections)}\n\n## Findings\n\n{severity_summary}\n\nSee the [findings index](findings-index.md) for a concise list linking to complete finding details.\n\nThis report is a generated view of canonical state and is not proof that no undiscovered defects exist.\n").encode()
    coverage = ["# Coverage ledger", ""] + [f"- {unit.get('id')}: {unit.get('status')} — {', '.join(unit.get('paths', []))}" for unit in units]
    if security_exclusions:
        coverage.extend(["", "## Security-profile exclusions", ""])
        coverage.extend(
            f"- {row.get('path')}: {row['exclusion'].get('rationale')}"
            for row in security_exclusions
        )
    outputs["coverage-ledger.md"] = ("\n".join(coverage) + "\n").encode()
    outputs["findings-index.md"] = _observation_index([row for row in observations if row.get("findingId")])
    for severity in ("P0", "P1", "P2", "P3", "P4"):
        outputs[f"findings/{severity}.md"] = _observation_view(f"{severity} findings", [row for row in observations if row.get("severity") == severity and row.get("disposition") == "validated"])
    mappings = {
        "findings/withdrawn.md": ("Withdrawn findings", lambda row: row.get("disposition") == "withdrawn"),
        "rejected-candidates.md": ("Rejected candidates", lambda row: row.get("disposition") == "rejected"),
        "nits.md": ("Nits", lambda row: row.get("reportClass") == "nit"),
        "suggestions.md": ("Suggestions", lambda row: row.get("reportClass") == "suggestion"),
        "questions.md": ("Questions", lambda row: row.get("reportClass") == "question"),
        "test-gaps.md": ("Test gaps", lambda row: row.get("reportClass") == "test_gap"),
        "documentation.md": ("Documentation observations", lambda row: row.get("reportClass") == "documentation"),
        "security-deferrals.md": ("Security profile deferrals", lambda row: row.get("disposition") == "deferred_by_profile"),
    }
    for name, (title, predicate) in mappings.items():
        outputs[name] = _observation_view(title, [row for row in observations if predicate(row)])
    outputs["validation-log.md"] = ("# Validation log\n\n" + ("\n".join(f"- {row.get('id')}: {row.get('result')} — {row.get('command')}" for row in validations) or "No validation records.") + "\n").encode()
    outputs["audit-report.md"] = ("# Audit report\n\n" + ("\n".join(f"- {row.get('id')}: {row.get('disposition')} ({row.get('materiality')})" for row in objections) or "No audit objections recorded.") + "\n").encode()
    for relative, data in outputs.items():
        atomic_write(safe_child(root, relative), data)
    manifest = {"schemaVersion": 1, "generatedAt": _utc_now(), "canonicalStateDigest": state_digest(root), "outputs": {name: digest_bytes(data) for name, data in sorted(outputs.items())}}
    atomic_write(root / "report-manifest.json", canonical_bytes(manifest))
    return {"generated": len(outputs), "canonicalStateDigest": manifest["canonicalStateDigest"]}


def audit(root: Path, mode: str) -> dict:
    root = ensure_review_root(root)
    result = check_review(root, check_generated=True)
    run = load_json(root / "run.json")
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")
    unfinished = [unit for unit in units if unit.get("status") != "complete"]
    open_observations = [row for row in observations if row.get("disposition") == "open"]
    open_material_objections = [row for row in objections if row.get("disposition") == "open" and row.get("materiality") == "material"]
    level = security_level(run)
    output: dict[str, Any] = {
        "mode": mode,
        "canonicalStateValid": result["ok"],
        "issues": list(result["issues"]),
        "counts": result["counts"],
        "securityLevel": level,
        "coverageScope": "non_security" if level == "off" else f"security_{level}",
    }
    if mode == "checkpoint":
        output.update({"completionGate": "FAIL", "checkpointState": run.get("status", "paused").upper(), "unfinishedUnits": len(unfinished), "openObservations": len(open_observations), "nextActionsRecorded": bool(run.get("nextActions")), "passed": result["ok"] and bool(run.get("nextActions") or not unfinished)})
    elif mode == "completion":
        phase_ok = set(run.get("completedPhases", [])) >= {"baseline", "semantic", "validation", "cross_component", "tail", "candidate_validation", "final_reconciliation", "independent_audit"}
        final_ok = run.get("finalAudit", {}).get("status") == "imported" if isinstance(run.get("finalAudit"), dict) else False
        if unfinished:
            output["issues"].append(f"unfinished work units: {len(unfinished)}")
        if open_observations:
            output["issues"].append(f"open observations: {len(open_observations)}")
        if open_material_objections:
            output["issues"].append(
                f"open material audit objections: {len(open_material_objections)}"
            )
        if not phase_ok:
            output["issues"].append("required review phases are incomplete")
        if not final_ok:
            output["issues"].append("independent final audit is not imported")
        output["passed"] = not output["issues"]
        output["completionGate"] = "PASS" if output["passed"] else "FAIL"
        output["coverageOutcome"] = (
            "COMPLETE_WITH_DECLARED_SECURITY_EXCLUSION"
            if output["passed"] and level == "off"
            else ("COMPLETE" if output["passed"] else "INCOMPLETE")
        )
    else:
        blockers = run.get("externalBlockers", [])
        valid = [item for item in blockers if all(item.get(key) for key in ("affectedItem", "requiredAction", "evidence", "whyIndependentWorkCannotResolve", "resumeAction"))]
        output.update({"completionGate": "FAIL", "unfinishedMaterialItems": len(blockers), "itemsWithValidExternalBlockers": len(valid), "itemsWithoutValidExternalBlockers": len(blockers) - len(valid), "independentActionableItems": len(run.get("independentActionableItems", [])), "passed": bool(blockers) and len(valid) == len(blockers) and not run.get("independentActionableItems")})
        output["incompleteHandoffGate"] = "PASS" if output["passed"] else "FAIL"
    return output
