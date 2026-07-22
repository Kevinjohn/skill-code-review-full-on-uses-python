"""Mechanical validation for canonical review state."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .errors import ReviewToolError
from .io import canonical_bytes, canonical_identity, digest_bytes, load_json, load_jsonl, safe_child, state_digest
from .references import extract_reference

ID_PATTERNS = {
    "observations": re.compile(r"OBS-(\d{6})$"),
    "findings": re.compile(r"DBR-(\d{4})$"),
    "validations": re.compile(r"VAL-(\d{6})$"),
    "objections": re.compile(r"AOB-(\d{6})$"),
}
RUN_STATUSES = {"active", "paused", "concluded", "superseded"}
UNIT_STATUSES = {"pending", "assigned", "partial", "complete", "blocked", "needs_revalidation"}
ANGLE_STATUSES = {"pending", "reviewed", "not_applicable", "blocked", "needs_revalidation"}
OBS_DISPOSITIONS = {"open", "validated", "rejected", "duplicate", "unresolved", "withdrawn"}


def _issue(issues: list[str], condition: bool, message: str) -> None:
    if not condition:
        issues.append(message)


def _ids(rows: list[dict], field: str, kind: str, issues: list[str], *, allow_null: bool = False) -> list[str]:
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not allow_null:
        _issue(issues, len(values) == len(rows), f"{kind}: every row requires {field}")
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        issues.append(f"{kind}: duplicate permanent identifiers: {', '.join(map(str, duplicates))}")
    pattern = ID_PATTERNS[kind]
    numbers = []
    for value in values:
        match = pattern.fullmatch(str(value))
        if not match:
            issues.append(f"{kind}: invalid identifier {value!r}")
        else:
            numbers.append(int(match.group(1)))
    if numbers and sorted(numbers) != list(range(1, max(numbers) + 1)):
        issues.append(f"{kind}: identifier sequence has a gap")
    return [str(value) for value in values]


def verify_events(root: Path, issues: list[str]) -> None:
    events = load_jsonl(root / "state-events.jsonl")
    prior_hash = None
    prior_post = None
    for expected, event in enumerate(events, 1):
        _issue(issues, event.get("sequence") == expected, f"state events: sequence gap at {expected}")
        _issue(issues, event.get("previousEventHash") == prior_hash, f"state events: broken previous link at {expected}")
        unsigned = dict(event)
        supplied = unsigned.pop("eventHash", None)
        calculated = digest_bytes(canonical_bytes(unsigned))
        _issue(issues, supplied == calculated, f"state events: invalid event identity at {expected}")
        if expected > 1:
            _issue(issues, event.get("preStateDigest") == prior_post, f"state events: broken state digest chain at {expected}")
        prior_hash = supplied
        prior_post = event.get("postStateDigest")
    run = load_json(root / "run.json")
    _issue(issues, bool(events), "state events: at least one event is required")
    if events:
        _issue(issues, run.get("stateEventHead") == events[-1].get("eventHash"), "run.json stateEventHead is stale")
        _issue(issues, state_digest(root) == events[-1].get("postStateDigest"), "repository-content or canonical-state identity mismatch")


def verify_reference_install(root: Path, issues: list[str]) -> None:
    manifest_path = root / "tooling/reference/manifest.json"
    if not manifest_path.exists():
        issues.append("preserved reference sources or extraction manifest missing")
        return
    manifest = load_json(manifest_path)
    sources = manifest.get("sources", [])
    pack_entry = next((item for item in sources if item.get("path", "").endswith("reference-pack.md")), None)
    if not pack_entry:
        issues.append("preserved reference pack source is not recorded")
        return
    source = root / "tooling/reference" / pack_entry["path"]
    if not source.exists():
        issues.append(f"preserved reference pack source missing: {pack_entry['path']}")
        return
    expected = {extract.filename: extract for extract in extract_reference(source.read_bytes())}
    entries = {item["path"]: item for item in manifest.get("derived", [])}
    for filename, extract in expected.items():
        path = root / "tooling/reference" / filename
        if filename not in entries or not path.exists():
            issues.append(f"reference extraction missing: {filename}")
            continue
        entry = entries[filename]
        _issue(issues, path.read_bytes() == extract.data, f"reference extraction changed: {filename}")
        _issue(issues, entry.get("sourceByteStart") == extract.start and entry.get("sourceByteEnd") == extract.end, f"reference offsets stale: {filename}")


def verify_transactions(root: Path, issues: list[str]) -> None:
    base = root / "tooling/transactions"
    if not base.exists():
        return
    for transaction in base.iterdir():
        if not transaction.is_dir() or transaction.name == "quarantine":
            continue
        if not (transaction / "COMPLETE").exists():
            kind = "committed-but-incomplete" if (transaction / "COMMIT").exists() else "uncommitted staged"
            issues.append(f"unrecovered transaction ({kind}): {transaction.name}")


def check_review(root: Path, *, check_generated: bool = True) -> dict[str, Any]:
    issues: list[str] = []
    run = load_json(root / "run.json")
    paths = load_jsonl(root / "paths.jsonl")
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")

    _issue(issues, run.get("schemaVersion") == 1, "run.json schemaVersion must be 1")
    _issue(issues, run.get("reviewSpecVersion") == 1, "run.json reviewSpecVersion must be 1")
    _issue(issues, bool(re.fullmatch(r"SPEC-\d{4}", str(run.get("specEpoch", "")))), "run.json specEpoch is invalid")
    _issue(issues, run.get("status") in RUN_STATUSES, "run.json status is invalid")
    _issue(issues, run.get("runtimeCapability") in {"continuous", "persistent_task", "external_supervisor", "none"}, "run.json runtimeCapability is invalid")

    path_keys = [(row.get("revisionEpoch"), row.get("path")) for row in paths]
    if len(path_keys) != len(set(path_keys)):
        issues.append("paths: duplicate path in revision epoch")
    current_epoch = run.get("currentEpoch")
    current_paths = {row.get("path"): row for row in paths if row.get("revisionEpoch") == current_epoch}
    if current_paths:
        baseline_rows = sorted(current_paths.values(), key=lambda row: str(row.get("path", "")).encode("utf-8"))
        _issue(issues, run.get("baselineContentSetHash") == canonical_identity(baseline_rows), "baseline repository-content identity mismatch")
    unit_ids = [unit.get("id") for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        issues.append("work units: duplicate identifiers")
    assignments: Counter[str] = Counter()
    reviewers: dict[str, str] = {}
    attempt_status: dict[str, tuple[str, str]] = {}

    for unit in units:
        uid = unit.get("id")
        _issue(issues, bool(re.fullmatch(r"WORK-\d{4}", str(uid or ""))), f"work unit has invalid identifier: {uid}")
        _issue(issues, unit.get("status") in UNIT_STATUSES, f"{uid}: invalid status transition or status {unit.get('status')!r}")
        _issue(issues, unit.get("specEpoch") == run.get("specEpoch"), f"{uid}: unit from wrong specEpoch")
        for path in unit.get("paths", []):
            assignments[path] += 1
        unit_path_rows = [current_paths[path] for path in unit.get("paths", []) if path in current_paths]
        if unit_path_rows:
            expected_unit_identity = canonical_identity(sorted(unit_path_rows, key=lambda row: row["path"].encode("utf-8")))
            _issue(issues, unit.get("contentSetHash") == expected_unit_identity, f"{uid}: work-unit content identity mismatch")
        angles = unit.get("angles", {})
        _issue(issues, set(angles) == {str(i) for i in range(1, 11)}, f"{uid}: exactly ten angle dispositions required")
        for number, angle in angles.items():
            status = angle.get("status")
            _issue(issues, status in ANGLE_STATUSES, f"{uid} angle {number}: invalid status")
            if status in {"reviewed", "not_applicable"}:
                _issue(issues, bool(angle.get("evidence")), f"{uid} angle {number}: semantic/applicability evidence required")
                _issue(issues, angle.get("specEpoch") == run.get("specEpoch"), f"{uid} angle {number}: disposition from wrong specEpoch")
        requirements = unit.get("requiredSecondReviews", [])
        if unit.get("riskTier") == "A":
            _issue(issues, bool(requirements), f"{uid}: Tier A requires independent second reviews")
        completed = {item.get("requirementId"): item for item in unit.get("completedSecondReviews", [])}
        attempts = unit.get("reviewAttempts", [])
        for attempt in attempts:
            key = f"{uid}/{attempt.get('attemptId')}"
            reviewer = attempt.get("reviewerExecutionId")
            reviewers[key] = reviewer
            attempt_status[key] = (attempt.get("status"), attempt.get("importDisposition"))
            if attempt.get("status") in {"complete", "partial", "blocked"} and attempt.get("importDisposition") == "pending":
                issues.append(f"unreconciled specialist attempt: {key}")
        for requirement in requirements:
            completion = completed.get(requirement.get("id"))
            if unit.get("status") == "complete":
                _issue(issues, completion is not None, f"{uid}: missing required second review {requirement.get('id')}")
            if completion:
                required_scope = requirement.get("scope")
                covered = completion.get("scopeCovered")
                scope_ok = covered == required_scope or covered == {"kind": "whole_unit"}
                _issue(issues, scope_ok, f"{uid}: invalid whole-unit or item second-review claim")
                primary_ids = completion.get("independentFromAttemptIds", [])
                primary_reviewers = {attempt.get("reviewerExecutionId") for attempt in attempts if attempt.get("attemptId") in primary_ids}
                _issue(issues, completion.get("reviewerExecutionId") not in primary_reviewers, f"{uid}: second review performed by contributing primary reviewer")
                _issue(issues, completion.get("specEpoch", run.get("specEpoch")) == run.get("specEpoch"), f"{uid}: stale second-review specEpoch")
                if completion.get("stale") is True:
                    issues.append(f"{uid}: completed second review invalidated by later intersecting primary import")
        if unit.get("status") == "complete":
            _issue(issues, all(angle.get("status") in {"reviewed", "not_applicable"} for angle in angles.values()), f"{uid}: complete status contradicts angle lifecycle")
        history = unit.get("manifestHistory", [])
        if history:
            _issue(issues, history[-1].get("path") == unit.get("currentManifest"), f"{uid}: stale superseded manifest is authoritative")
            for entry in history:
                manifest_path = safe_child(root, entry.get("path", "invalid"))
                if not manifest_path.exists():
                    issues.append(f"{uid}: manifest missing: {entry.get('path')}")
                elif entry.get("hash") and digest_bytes(manifest_path.read_bytes()) != entry.get("hash"):
                    issues.append(f"{uid}: manifest identity mismatch: {entry.get('path')}")

    for path, row in current_paths.items():
        count = assignments[path]
        if row.get("exclusion") is None:
            _issue(issues, count == 1, f"path primary assignment count is {count}, expected 1: {path}")
        else:
            _issue(issues, count == 0, f"excluded path assigned to primary unit: {path}")
    for path in assignments:
        _issue(issues, path in current_paths, f"work unit references unknown baseline path: {path}")

    observation_ids = _ids(observations, "id", "observations", issues)
    finding_rows = [row for row in observations if row.get("findingId")]
    finding_ids = _ids(finding_rows, "findingId", "findings", issues, allow_null=True)
    validation_ids = _ids(validations, "id", "validations", issues)
    objection_ids = _ids(objections, "id", "objections", issues)
    observation_set, validation_set = set(observation_ids), set(validation_ids)
    canonical_targets = observation_set | set(finding_ids)
    for observation in observations:
        disposition = observation.get("disposition")
        _issue(issues, disposition in OBS_DISPOSITIONS, f"{observation.get('id')}: invalid observation disposition")
        for ref in observation.get("validationRefs", []):
            _issue(issues, ref in validation_set, f"orphaned validation reference {ref} from {observation.get('id')}")
        if disposition == "duplicate":
            _issue(issues, observation.get("duplicateOf") in canonical_targets, f"{observation.get('id')}: invalid duplicate mapping")
        if disposition == "withdrawn":
            _issue(issues, bool(observation.get("findingId") and observation.get("withdrawal")), f"{observation.get('id')}: invalid withdrawal mapping")
    for validation in validations:
        for ref in validation.get("observationIds", []):
            _issue(issues, ref in observation_set, f"{validation.get('id')}: orphaned observation reference {ref}")
    for objection in objections:
        for ref in objection.get("candidateRefs", []):
            _issue(issues, ref in observation_set, f"{objection.get('id')}: orphaned candidate reference {ref}")

    if run.get("verdict") in {"PASS", "CONDITIONAL PASS"}:
        material = [row for row in observations if row.get("materiality") == "material" and row.get("disposition") in {"validated", "unresolved"}]
        _issue(issues, not material, "terminal pass verdict has an unresolved material concern")

    verify_events(root, issues)
    verify_reference_install(root, issues)
    verify_transactions(root, issues)
    if check_generated:
        manifest_path = root / "report-manifest.json"
        if not manifest_path.exists():
            issues.append("generated views are missing or stale")
        else:
            report = load_json(manifest_path)
            _issue(issues, report.get("canonicalStateDigest") == state_digest(root), "generated views are stale")
            for name, expected in report.get("outputs", {}).items():
                target = safe_child(root, name)
                _issue(issues, target.exists() and digest_bytes(target.read_bytes()) == expected, f"generated output changed: {name}")

    return {
        "ok": not issues,
        "issues": issues,
        "counts": {
            "baselinePaths": len(current_paths),
            "inScopePaths": sum(row.get("exclusion") is None for row in current_paths.values()),
            "excludedPaths": sum(row.get("exclusion") is not None for row in current_paths.values()),
            "workUnits": len(units),
            "observations": len(observations),
            "validations": len(validations),
            "auditObjections": len(objections),
        },
    }


def require_valid(root: Path, *, check_generated: bool = False) -> None:
    result = check_review(root, check_generated=check_generated)
    if not result["ok"]:
        raise ReviewToolError("proposed state is invalid:\n- " + "\n- ".join(result["issues"]))
