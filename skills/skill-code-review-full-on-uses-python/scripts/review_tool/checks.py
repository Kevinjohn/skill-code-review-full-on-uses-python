"""Mechanical validation for canonical review state."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .canonical_checks import (
    _verify_canonical_graph,
    _verify_path_partition,
)
from .evidence import (
    EvidenceCache,
    load_sealed_attempt_manifest,
    load_sealed_unit_manifest,
    missing_primary_scope,
    scope_covers,
    scope_is_valid,
    validate_reviewer_independence,
    validate_review_spec_version,
    validate_second_review_assignment,
    validate_second_review_completion_provenance,
    validate_second_review_history,
    verify_imported_attempt_artifacts,
)
from .errors import ReviewToolError
from .identifiers import attempt_token
from .io import canonical_bytes, canonical_identity, digest_bytes, load_json, load_jsonl, parse_json_bytes, safe_child, state_digest
from .packets import (
    CapsuleFreshnessError,
    load_orientation_capsule,
    validate_attempt_result_data,
)
from .policy import (
    CAPSULE_BYTE_WARNING,
    CAPSULE_SHARED_FIELDS,
    TIER_A_DENSITY_DIAGNOSTIC,
    TIER_A_DENSITY_MIN_UNITS,
    TIER_A_DENSITY_THRESHOLD,
    TIER_A_REASON_CODES,
    WARM_BATCH_MAX_ASSIGNMENTS,
)
from .references import extract_reference
from .schema import (
    ANGLE_RULES,
    ANGLE_STATUSES,
    ATTEMPT_LIFECYCLE,
    RUN_RULES,
    RUN_STATUSES,
    SECURITY_PROFILE_RULES,
    UNIT_RULES,
    UNIT_STATUSES,
    VERDICTS,
    apply_rules,
)
from .security import (
    has_declared_security_profile,
    permitted_validation_classes,
    security_level,
    security_profile,
)
from .transactions import VALID_OPERATIONS


def _issue(issues: list[str], condition: bool, message: str) -> None:
    if not condition:
        issues.append(message)


def _is_one_of(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def _unit_symbols(
    root: Path, unit: dict[str, Any], cache: EvidenceCache
) -> set[str]:
    try:
        manifest = load_sealed_unit_manifest(root, unit, cache=cache)
    except ReviewToolError:
        return set()
    symbols: set[str] = set()
    for item in manifest.get("symbols", []):
        if isinstance(item, str) and item:
            symbols.add(item)
        elif isinstance(item, dict):
            value = item.get("symbol", item.get("value"))
            if isinstance(value, str) and value:
                symbols.add(value)
    return symbols


def _diagnostic_identity(
    diagnostic_id: str, run: dict[str, Any], units: list[dict[str, Any]]
) -> str:
    projection = [
        {
            "id": unit.get("id"),
            "riskTier": unit.get("riskTier"),
            "criticalReasons": unit.get("criticalReasons", []),
            "currentManifest": unit.get("currentManifest"),
            "currentManifestHash": unit.get("currentManifestHash"),
        }
        for unit in sorted(units, key=lambda item: str(item.get("id")).encode("utf-8"))
    ]
    return canonical_identity(
        {
            "diagnosticId": diagnostic_id,
            "specEpoch": run.get("specEpoch"),
            "workUnits": projection,
        }
    )


def pilot_diagnostics(
    run: dict[str, Any],
    units: list[dict[str, Any]],
    acknowledgements: list[Any],
) -> dict[str, Any]:
    """Return scoped pilot warnings independently of full state validation."""
    if not isinstance(acknowledgements, list):
        acknowledgements = []
    diagnostic_id = TIER_A_DENSITY_DIAGNOSTIC
    identity = _diagnostic_identity(diagnostic_id, run, units)
    acknowledgement_set = {
        (item.get("id"), item.get("diagnosticIdentity"))
        for item in acknowledgements
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("diagnosticIdentity"), str)
    }
    acknowledged = (diagnostic_id, identity) in acknowledgement_set
    tier_a_count = sum(unit.get("riskTier") == "A" for unit in units)
    warning = None
    if (
        len(units) >= TIER_A_DENSITY_MIN_UNITS
        and tier_a_count / len(units) >= TIER_A_DENSITY_THRESHOLD
        and not acknowledged
    ):
        warning = (
            f"{diagnostic_id}: Tier A density is {tier_a_count}/{len(units)}; "
            "review unit fragmentation and critical reasons, then record the "
            "diagnostic ID and identity in run.json diagnosticAcknowledgements"
        )
    return {
        "warning": warning,
        "identity": identity,
        "acknowledged": acknowledged,
        "bulkDispatchAllowed": warning is None,
    }


def verify_events(root: Path, issues: list[str]) -> None:
    events = load_jsonl(root / "state-events.jsonl")
    prior_hash = None
    prior_post = None
    for expected, event in enumerate(events, 1):
        _issue(issues, event.get("sequence") == expected, f"state events: sequence gap at {expected}")
        _issue(issues, event.get("previousEventHash") == prior_hash, f"state events: broken previous link at {expected}")
        _issue(
            issues,
            _is_one_of(event.get("operation"), set(VALID_OPERATIONS)),
            f"state events: invalid operation at {expected}",
        )
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


def _load_pinned_reference_manifest(
    root: Path,
    relative: Any,
    expected_hash: Any,
    label: str,
    issues: list[str],
    *,
    expected_epoch: str,
) -> dict[str, Any] | None:
    if not isinstance(relative, str) or not isinstance(expected_hash, str):
        issues.append(f"{label} reference manifest pin is missing")
        return None
    try:
        path = safe_child(root, relative)
    except ReviewToolError as exc:
        issues.append(str(exc))
        return None
    if not path.is_file():
        issues.append(f"{label} reference manifest is missing: {relative}")
        return None
    data = path.read_bytes()
    if digest_bytes(data) != expected_hash:
        issues.append(f"{label} reference manifest identity mismatch")
        return None
    try:
        manifest = parse_json_bytes(data, str(path))
    except ReviewToolError as exc:
        issues.append(str(exc))
        return None
    if not isinstance(manifest, dict):
        issues.append(f"{label} reference manifest must be an object")
        return None
    _issue(
        issues,
        manifest.get("reviewSpecVersion") == 2
        and manifest.get("specEpoch") == expected_epoch,
        f"{label} reference manifest specification identity mismatch",
    )
    return manifest


def _verify_reference_sources(
    root: Path,
    manifest: dict[str, Any],
    label: str,
    issues: list[str],
) -> bytes | None:
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        issues.append(f"{label} reference installation sources must be an array")
        return None
    pack_bytes = None
    for entry in sources:
        if not isinstance(entry, dict):
            issues.append(f"{label} reference source entry is malformed")
            continue
        try:
            source_path = safe_child(
                root / "tooling/reference",
                str(entry.get("path", "invalid")),
            )
        except ReviewToolError as exc:
            issues.append(str(exc))
            continue
        valid = (
            source_path.is_file()
            and isinstance(entry.get("sha256"), str)
            and digest_bytes(source_path.read_bytes()) == entry.get("sha256")
        )
        _issue(
            issues,
            valid,
            f"{label} preserved reference source identity mismatch: "
            f"{entry.get('path')}",
        )
        if valid and str(entry.get("path", "")).endswith("reference-pack.md"):
            pack_bytes = source_path.read_bytes()
    if pack_bytes is None:
        issues.append(f"{label} preserved reference pack source is not valid")
    return pack_bytes


def _verify_current_reference_extracts(
    root: Path,
    manifest: dict[str, Any],
    pack_bytes: bytes,
    issues: list[str],
) -> None:
    try:
        expected = {
            extract.filename: extract
            for extract in extract_reference(pack_bytes)
        }
    except ReviewToolError as exc:
        issues.append(str(exc))
        return
    derived = manifest.get("derived")
    if not isinstance(derived, list):
        issues.append("reference installation derived entries must be an array")
        return
    entries = {
        item["path"]: item
        for item in derived
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for filename, extract in expected.items():
        path = root / "tooling/reference" / filename
        if filename not in entries or not path.exists():
            issues.append(f"reference extraction missing: {filename}")
            continue
        data = path.read_bytes()
        entry = entries[filename]
        _issue(
            issues,
            data == extract.data,
            f"reference extraction changed: {filename}",
        )
        _issue(
            issues,
            entry.get("sourceByteStart") == extract.start
            and entry.get("sourceByteEnd") == extract.end,
            f"reference offsets stale: {filename}",
        )
        _issue(
            issues,
            entry.get("sha256") == digest_bytes(data),
            f"reference extraction identity mismatch: {filename}",
        )


def verify_reference_install(root: Path, issues: list[str]) -> None:
    try:
        run = load_json(root / "run.json")
    except ReviewToolError as exc:
        issues.append(str(exc))
        return
    if not isinstance(run, dict):
        issues.append("run.json must contain an object")
        return
    specification = run.get("specification")
    if not isinstance(specification, dict):
        issues.append("run.json specification must be an object")
        return
    latest_hash = specification.get("referenceManifestHash")
    current = _load_pinned_reference_manifest(
        root,
        "tooling/reference/manifest.json",
        latest_hash,
        "current",
        issues,
        expected_epoch=str(run.get("specEpoch")),
    )
    if current is not None:
        pack_bytes = _verify_reference_sources(
            root,
            current,
            "current",
            issues,
        )
        if pack_bytes is not None:
            _verify_current_reference_extracts(
                root,
                current,
                pack_bytes,
                issues,
            )
    initial = _load_pinned_reference_manifest(
        root,
        specification.get("referenceManifestPreserved"),
        specification.get("referenceManifestHash"),
        "SPEC-0001",
        issues,
        expected_epoch="SPEC-0001",
    )
    if initial is not None:
        _verify_reference_sources(root, initial, "SPEC-0001", issues)


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


def _verify_attempt_lifecycle(
    attempt: dict[str, Any],
    key: str,
    issues: list[str],
) -> None:
    try:
        attempt_token(attempt.get("attemptId"))
    except (ReviewToolError, TypeError) as exc:
        issues.append(f"{key}: {exc}")
    disposition = attempt.get("importDisposition")
    status = attempt.get("status")
    legal = ATTEMPT_LIFECYCLE
    disposition_valid = _is_one_of(disposition, set(legal))
    _issue(
        issues,
        disposition_valid,
        f"{key}: invalid importDisposition",
    )
    _issue(
        issues,
        isinstance(status, str)
        and disposition_valid
        and status in legal[disposition],
        f"{key}: attempt status and importDisposition are inconsistent",
    )
    if (
        disposition == "pending"
        and _is_one_of(status, {"complete", "partial", "blocked"})
    ):
        issues.append(f"unreconciled specialist attempt: {key}")
    result_hash = attempt.get("resultHash")
    evidence_hash = attempt.get("attemptEvidenceHash")
    if disposition in {"imported", "reconciled_interruption"}:
        _issue(
            issues,
            isinstance(result_hash, str)
            and bool(result_hash)
            and isinstance(evidence_hash, str)
            and bool(evidence_hash),
            f"{key}: reconciled attempt requires result and evidence hashes",
        )
    else:
        _issue(
            issues,
            result_hash is None and evidence_hash is None,
            f"{key}: non-imported attempt cannot retain imported evidence hashes",
        )
    if disposition == "superseded":
        _issue(
            issues,
            isinstance(attempt.get("supersededReason"), str)
            and bool(attempt["supersededReason"].strip()),
            f"{key}: superseded attempt requires a reason",
        )


def _verify_attempt(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    attempt: dict[str, Any],
    requirements: list[dict[str, Any]],
    *,
    level: str,
    issues: list[str],
    warm_batches: dict[str, list[tuple[str, str | None]]],
    output_directories: dict[str, str],
    execution_owners: dict[str, str],
    cache: EvidenceCache,
) -> None:
    key = f"{unit.get('id')}/{attempt.get('attemptId')}"
    disposition = attempt.get("importDisposition")
    _verify_attempt_lifecycle(attempt, key, issues)
    try:
        manifest = load_sealed_attempt_manifest(
            root, unit, attempt, run, cache=cache
        )
        unit_manifest = load_sealed_unit_manifest(
            root, unit, manifest, cache=cache
        )
        validate_second_review_assignment(unit, unit_manifest, manifest)
    except ReviewToolError as exc:
        issues.append(str(exc))
        return
    for field in (
        "packetType",
        "reviewerExecutionId",
        "reviewerPrincipalId",
        "unitManifestHash",
        "independentFromAttemptIds",
    ):
        _issue(
            issues,
            attempt.get(field) == manifest.get(field),
            f"{key}: attempt row {field} does not match its manifest",
        )
    execution = manifest.get("reviewerExecutionId")
    if isinstance(execution, str) and execution:
        prior_execution = execution_owners.setdefault(execution, key)
        _issue(
            issues,
            prior_execution == key,
            f"{key}: reviewerExecutionId is already owned by {prior_execution}",
        )
    output = manifest.get("outputDirectory")
    if not isinstance(output, str) or not output:
        issues.append(f"{key}: attempt manifest requires an outputDirectory")
    else:
        prior = output_directories.setdefault(output, key)
        _issue(
            issues,
            prior == key,
            f"{key}: outputDirectory is already owned by {prior}",
        )
    if disposition in {"imported", "reconciled_interruption"}:
        try:
            result, validations = verify_imported_attempt_artifacts(
                root, unit, attempt, manifest, cache=cache
            )
            preflight = validate_attempt_result_data(
                root,
                run,
                unit,
                attempt,
                manifest,
                result,
                validations,
                validate_current_evidence=False,
            )
            issues.extend(f"{key}: {issue}" for issue in preflight["issues"])
            result_status = (
                result.get("status") if isinstance(result, dict) else None
            )
            if disposition == "imported":
                _issue(
                    issues,
                    result_status == attempt.get("status"),
                    f"{key}: attempt row status does not match imported result",
                )
            else:
                _issue(
                    issues,
                    _is_one_of(result_status, {"partial", "blocked"}),
                    f"{key}: reconciled interruption has invalid result status",
                )
        except ReviewToolError as exc:
            issues.append(str(exc))
    _issue(
        issues,
        manifest.get("securityLevel") == level,
        f"{key}: attempt manifest securityLevel mismatch",
    )
    _issue(
        issues,
        manifest.get("permittedValidationClasses")
        == permitted_validation_classes(level),
        f"{key}: attempt manifest validation classes do not match security level",
    )
    if level == "off":
        assigned_angles = set(manifest.get("assignedScope", {}).get("angles", []))
        _issue(
            issues,
            5 not in assigned_angles,
            f"{key}: angle 5 assigned at security level off",
        )
    principal = attempt.get("reviewerPrincipalId")
    _issue(
        issues,
        isinstance(principal, str) and bool(principal.strip()),
        f"{key}: reviewerPrincipalId is required",
    )
    _issue(
        issues,
        manifest.get("reviewerPrincipalId") == principal,
        f"{key}: reviewer principal mismatch",
    )
    reuse_mode = manifest.get("reviewerReuseMode")
    _issue(
        issues,
        _is_one_of(reuse_mode, {"cold", "warm_batch"}),
        f"{key}: invalid reviewerReuseMode",
    )
    if reuse_mode == "warm_batch":
        _issue(
            issues,
            manifest.get("packetType") == "independent_second_review",
            f"{key}: warm reviewer reuse is limited to independent second reviews",
        )
        stable = run.get("specialistCapabilities", {}).get("stableReviewerLineage")
        _issue(
            issues,
            stable is True,
            f"{key}: warm reviewer reuse requires stable lineage",
        )
        _issue(
            issues,
            bool(manifest.get("reviewerBatchId")),
            f"{key}: warm reviewer reuse requires reviewerBatchId",
        )
        if manifest.get("reviewerBatchId"):
            warm_batches.setdefault(str(manifest["reviewerBatchId"]), []).append(
                (key, principal)
            )
    if (
        manifest.get("packetType") != "independent_second_review"
        or disposition != "pending"
    ):
        return
    requirement_id = manifest.get("secondReviewRequirementId")
    requirement = next(
        (item for item in requirements if item.get("id") == requirement_id),
        None,
    )
    _issue(
        issues,
        requirement is not None,
        f"{key}: second-review manifest names no current requirement",
    )
    if requirement is None:
        return
    try:
        validate_reviewer_independence(
            root,
            run,
            unit,
            requirement,
            independent_ids=manifest.get("independentFromAttemptIds"),
            evidence_set_hash=manifest.get("primaryEvidenceSetHash"),
            reviewer_principal_id=principal,
            reviewer_execution_id=attempt.get("reviewerExecutionId"),
            cache=cache,
        )
    except ReviewToolError as exc:
        issues.append(str(exc))


def _verify_second_reviews(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    requirements: list[dict[str, Any]],
    *,
    issues: list[str],
    cache: EvidenceCache,
) -> None:
    uid = unit.get("id")
    raw_completed = unit.get("completedSecondReviews", [])
    if not isinstance(raw_completed, list):
        issues.append(f"{uid}: completedSecondReviews must be an array")
        raw_completed = []
    completed_rows = [
        item for item in raw_completed if isinstance(item, dict)
    ]
    if len(completed_rows) != len(raw_completed):
        issues.append(f"{uid}: completedSecondReviews contains a malformed entry")
    requirement_ids = {item.get("id") for item in requirements}
    completion_ids = [
        str(item.get("requirementId")) for item in completed_rows
    ]
    for item in completed_rows:
        _issue(
            issues,
            isinstance(item.get("requirementId"), str),
            f"{uid}: active second-review completion requires a string requirementId",
        )
    duplicates = [
        identifier
        for identifier, count in Counter(completion_ids).items()
        if count > 1
    ]
    if duplicates:
        issues.append(
            f"{uid}: duplicate active second-review completions: {duplicates}"
        )
    for identifier in completion_ids:
        _issue(
            issues,
            identifier in requirement_ids,
            f"{uid}: orphaned active second-review completion {identifier}",
        )
    completed = {
        str(item.get("requirementId")): item for item in completed_rows
    }
    for requirement in requirements:
        completion = completed.get(requirement.get("id"))
        if unit.get("status") == "complete":
            _issue(
                issues,
                completion is not None,
                f"{uid}: missing required second review {requirement.get('id')}",
            )
        if not completion:
            continue
        _issue(
            issues,
            scope_covers(completion.get("scopeCovered"), requirement.get("scope")),
            f"{uid}: invalid whole-unit or item second-review claim",
        )
        primary_ids = completion.get("independentFromAttemptIds", [])
        try:
            validate_second_review_completion_provenance(
                root,
                run,
                unit,
                requirement,
                completion,
                cache=cache,
            )
            validate_reviewer_independence(
                root,
                run,
                unit,
                requirement,
                independent_ids=primary_ids,
                evidence_set_hash=completion.get("primaryEvidenceSetHash"),
                reviewer_principal_id=completion.get("reviewerPrincipalId"),
                reviewer_execution_id=completion.get("reviewerExecutionId"),
                cache=cache,
            )
        except ReviewToolError as exc:
            issues.append(str(exc))
        _issue(
            issues,
            completion.get("specEpoch") == run.get("specEpoch"),
            f"{uid}: stale second-review specEpoch",
        )
        if completion.get("stale") is True:
            issues.append(
                f"{uid}: completed second review invalidated by later intersecting primary import"
            )
    history = unit.get("secondReviewHistory", [])
    if not isinstance(history, list):
        issues.append(f"{uid}: secondReviewHistory must be an array")
        return
    previous_hash = None
    for entry in history:
        try:
            validate_second_review_history(
                root,
                unit,
                entry,
                cache=cache,
                expected_previous_hash=previous_hash,
            )
        except ReviewToolError as exc:
            issues.append(str(exc))
        if isinstance(entry, dict) and isinstance(
            entry.get("historyHash"), str
        ):
            previous_hash = entry["historyHash"]
    expected_attempts = {
        f"{uid}/{attempt.get('attemptId')}"
        for attempt in unit.get("reviewAttempts", [])
        if isinstance(attempt, dict)
        and attempt.get("packetType") == "independent_second_review"
        and attempt.get("importDisposition") == "imported"
        and attempt.get("status") == "complete"
    }
    recorded_attempts = [
        item.get("attempt")
        for item in [*completed_rows, *history]
        if isinstance(item, dict) and isinstance(item.get("attempt"), str)
    ]
    if len(recorded_attempts) != len(set(recorded_attempts)):
        issues.append(f"{uid}: duplicate second-review attempt provenance")
    _issue(
        issues,
        set(recorded_attempts) == expected_attempts,
        f"{uid}: second-review attempt provenance is incomplete",
    )


def _verify_manifest_history(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    *,
    level: str,
    issues: list[str],
    warnings: list[str],
    cache: EvidenceCache,
) -> None:
    uid = unit.get("id")
    history = unit.get("manifestHistory", [])
    if not isinstance(history, list) or not history:
        issues.append(f"{uid}: manifestHistory must be a non-empty array")
        return
    if not all(isinstance(entry, dict) for entry in history):
        issues.append(f"{uid}: manifestHistory contains a malformed entry")
        return
    _issue(
        issues,
        history[-1].get("path") == unit.get("currentManifest"),
        f"{uid}: stale superseded manifest is authoritative",
    )
    path_pins = [
        (entry.get("path"), entry.get("hash"))
        for entry in history
        if isinstance(entry.get("path"), str)
        and isinstance(entry.get("hash"), str)
    ]
    _issue(
        issues,
        len(path_pins) == len(history)
        and len(path_pins) == len(set(path_pins)),
        f"{uid}: manifestHistory path/hash identities must be unique",
    )
    attempt_hashes = {
        attempt.get("manifestHash")
        for attempt in unit.get("reviewAttempts", [])
        if isinstance(attempt, dict)
        and isinstance(attempt.get("manifestHash"), str)
    }
    previous_entry = None
    for expected_revision, entry in enumerate(history, 1):
        expected_supersedes = (
            None
            if previous_entry is None
            else {
                "path": previous_entry.get("path"),
                "hash": previous_entry.get("hash"),
            }
        )
        _issue(
            issues,
            entry.get("revision") == expected_revision,
            f"{uid}: manifestHistory revision chain is invalid",
        )
        _issue(
            issues,
            entry.get("supersedes") == expected_supersedes,
            f"{uid}: manifestHistory supersedes chain is invalid",
        )
        preserved = entry.get("preservedAttemptManifestHashes")
        if not isinstance(preserved, list) or not all(
            isinstance(item, str) for item in preserved
        ):
            issues.append(
                f"{uid}: manifestHistory preserved attempt pins are malformed"
            )
            preserved = []
        _issue(
            issues,
            len(preserved) == len(set(preserved))
            and set(preserved) <= attempt_hashes,
            f"{uid}: manifestHistory preserved attempt pins are invalid",
        )
        previous_entry = entry
        try:
            path = safe_child(root, entry.get("path", "invalid"))
        except ReviewToolError as exc:
            issues.append(str(exc))
            continue
        if not path.exists():
            issues.append(f"{uid}: manifest missing: {entry.get('path')}")
            continue
        if not isinstance(entry.get("hash"), str) or not entry["hash"]:
            issues.append(
                f"{uid}: manifest history hash pin is missing: {entry.get('path')}"
            )
            continue
        if digest_bytes(path.read_bytes()) != entry.get("hash"):
            issues.append(f"{uid}: manifest identity mismatch: {entry.get('path')}")
            continue
        try:
            historical_manifest = load_json(path)
        except ReviewToolError as exc:
            issues.append(str(exc))
            continue
        _issue(
            issues,
            isinstance(historical_manifest, dict)
            and historical_manifest.get("reviewSpecVersion") == 2,
            f"{uid}: historical unit manifest reviewSpecVersion mismatch",
        )
        _issue(
            issues,
            isinstance(historical_manifest, dict)
            and historical_manifest.get("workId") == uid
            and historical_manifest.get("revision") == expected_revision
            and historical_manifest.get("supersedes")
            == expected_supersedes,
            f"{uid}: historical unit manifest chain mismatch",
        )
        _issue(
            issues,
            isinstance(historical_manifest, dict)
            and historical_manifest.get("preservedAttemptManifestHashes")
            == preserved,
            f"{uid}: historical preserved attempt pins mismatch",
        )
        _issue(
            issues,
            isinstance(historical_manifest, dict)
            and historical_manifest.get("specEpoch") == run.get("specEpoch"),
            f"{uid}: historical unit manifest uses an unrecorded specEpoch",
        )
        if entry.get("path") != unit.get("currentManifest"):
            continue
        try:
            manifest = load_sealed_unit_manifest(root, unit, cache=cache)
        except ReviewToolError as exc:
            issues.append(str(exc))
            continue
        _issue(
            issues,
            unit.get("currentManifestHash") == entry.get("hash"),
            f"{uid}: currentManifestHash does not match manifest history",
        )
        _issue(
            issues,
            manifest.get("reviewSpecVersion") == 2,
            f"{uid}: unit manifest reviewSpecVersion mismatch",
        )
        _issue(
            issues,
            manifest.get("securityLevel") == level,
            f"{uid}: unit manifest securityLevel mismatch",
        )
        _issue(
            issues,
            manifest.get("permittedValidationClasses")
            == permitted_validation_classes(level),
            f"{uid}: unit manifest validation classes do not match security level",
        )
        required_angle_values = manifest.get(
            "requiredAngleDispositions", []
        )
        if not isinstance(required_angle_values, list) or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in required_angle_values
        ):
            issues.append(
                f"{uid}: unit manifest requiredAngleDispositions is malformed"
            )
            required_angle_values = []
        required_angles = set(required_angle_values)
        expected_angles = set(range(1, 11)) - ({5} if level == "off" else set())
        _issue(
            issues,
            required_angles == expected_angles,
            f"{uid}: unit manifest angles do not match security level",
        )
        for field in (
            "contentSetHash",
            "subsystem",
            "riskTier",
            "requiredSecondReviews",
        ):
            _issue(
                issues,
                manifest.get(field) == unit.get(field),
                f"{uid}: unit row {field} does not match its immutable manifest",
            )
        raw_manifest_paths = manifest.get("paths", [])
        if not isinstance(raw_manifest_paths, list):
            issues.append(f"{uid}: unit manifest paths must be an array")
            raw_manifest_paths = []
        manifest_paths = [
            item.get("path")
            for item in raw_manifest_paths
            if isinstance(item, dict)
        ]
        _issue(
            issues,
            manifest_paths == unit.get("paths"),
            f"{uid}: unit row paths do not match its immutable manifest",
        )
        _issue(
            issues,
            bool(manifest.get("orientationCapsule")),
            f"{uid}: unit manifest requires an orientation capsule",
        )
        try:
            capsule = load_orientation_capsule(root, manifest)
            capsule_size = len(canonical_bytes(capsule))
            if capsule_size > CAPSULE_BYTE_WARNING:
                warnings.append(
                    f"{uid}: orientation capsule is {capsule_size} bytes; "
                    f"target at most {CAPSULE_BYTE_WARNING}"
                )
        except CapsuleFreshnessError as exc:
            if unit.get("status") != "needs_revalidation":
                issues.append(f"{uid}: {exc}")
        except ReviewToolError as exc:
            issues.append(f"{uid}: {exc}")
        _issue(
            issues,
            all(not manifest.get(field) for field in CAPSULE_SHARED_FIELDS),
            f"{uid}: shared orientation facts must not be duplicated in the unit manifest",
        )


def _verify_run_state(
    root: Path,
    run: dict[str, Any],
    issues: list[str],
) -> tuple[list[dict[str, Any]], str]:
    apply_rules(run, RUN_RULES, issues)
    try:
        validate_review_spec_version(run.get("reviewSpecVersion"))
    except ReviewToolError as exc:
        issues.append(str(exc))
    acknowledgements = run.get("diagnosticAcknowledgements", [])
    if not isinstance(acknowledgements, list):
        acknowledgements = []
    level = security_level(run)
    if not has_declared_security_profile(run):
        issues.append("run.json securityProfile is required and must be an object")
    apply_rules(
        security_profile(run),
        SECURITY_PROFILE_RULES,
        issues,
        {"level": level},
    )
    assignments = root / "assignments" / "FINAL-AUDIT"
    if assignments.is_dir():
        for path in sorted(assignments.glob("*.json")):
            manifest = load_json(path)
            label = path.relative_to(root).as_posix()
            if not isinstance(manifest, dict):
                issues.append(f"{label}: manifest must be an object")
                continue
            _issue(
                issues,
                manifest.get("securityLevel") == level,
                f"{label}: securityLevel mismatch",
            )
            _issue(
                issues,
                manifest.get("permittedValidationClasses")
                == permitted_validation_classes(level),
                f"{label}: validation classes do not match security level",
            )
    return acknowledgements, level


def _current_path_index(
    run: dict[str, Any],
    paths: list[dict[str, Any]],
    issues: list[str],
) -> dict[str, dict[str, Any]]:
    path_keys = [
        (str(row.get("revisionEpoch")), str(row.get("path"))) for row in paths
    ]
    if len(path_keys) != len(set(path_keys)):
        issues.append("paths: duplicate path in revision epoch")
    current_epoch = run.get("currentEpoch")
    current: dict[str, dict[str, Any]] = {}
    for row in paths:
        path = row.get("path")
        _issue(
            issues,
            isinstance(path, str) and bool(path),
            f"paths: invalid path identifier {path!r}",
        )
        if row.get("revisionEpoch") == current_epoch and isinstance(path, str):
            current[path] = row
    if current:
        baseline_rows = sorted(
            current.values(),
            key=lambda row: str(row.get("path", "")).encode("utf-8"),
        )
        _issue(
            issues,
            run.get("baselineContentSetHash") == canonical_identity(baseline_rows),
            "baseline repository-content identity mismatch",
        )
    return current


def _verify_unit_angles(
    run: dict[str, Any],
    unit: dict[str, Any],
    uid: Any,
    level: str,
    issues: list[str],
) -> dict[str, dict[str, Any]]:
    angles = unit.get("angles", {})
    if not isinstance(angles, dict):
        issues.append(f"{uid}: angles must be an object")
        angles = {}
    _issue(
        issues,
        set(angles) == {str(i) for i in range(1, 11)},
        f"{uid}: exactly ten angle dispositions required",
    )
    valid_angles: dict[str, dict[str, Any]] = {}
    for number, angle in angles.items():
        if not isinstance(angle, dict):
            issues.append(f"{uid} angle {number}: disposition must be an object")
            continue
        valid_angles[number] = angle
        apply_rules(
            angle,
            ANGLE_RULES,
            issues,
            {
                "uid": uid,
                "number": number,
                "run": run,
                "level": level,
                "status": angle.get("status"),
            },
        )
    if level == "off":
        angle_five = angles.get("5")
        _issue(
            issues,
            isinstance(angle_five, dict)
            and angle_five.get("status") == "excluded_by_profile",
            f"{uid}: angle 5 must be excluded at security level off",
        )
    else:
        _issue(
            issues,
            all(
                not isinstance(angle, dict)
                or angle.get("status") != "excluded_by_profile"
                for angle in angles.values()
            ),
            f"{uid}: profile exclusion is only valid at security level off",
        )
    return valid_angles


def _valid_second_review_requirements(
    unit: dict[str, Any],
    uid: Any,
    level: str,
    issues: list[str],
) -> list[dict[str, Any]]:
    requirements = unit.get("requiredSecondReviews", [])
    if not isinstance(requirements, list):
        issues.append(f"{uid}: requiredSecondReviews must be an array")
        return []
    valid: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            issues.append(f"{uid}: malformed second-review requirement")
            continue
        requirement_valid = (
            isinstance(requirement.get("id"), str)
            and isinstance(requirement.get("angle"), int)
            and not isinstance(requirement.get("angle"), bool)
            and 1 <= requirement["angle"] <= 10
            and scope_is_valid(requirement.get("scope"))
        )
        _issue(
            issues,
            requirement_valid,
            f"{uid}: malformed second-review requirement",
        )
        if requirement_valid:
            valid.append(requirement)
    requirement_ids = [item["id"] for item in valid]
    _issue(
        issues,
        len(requirement_ids) == len(set(requirement_ids)),
        f"{uid}: duplicate second-review requirement identifiers",
    )
    if level == "off":
        _issue(
            issues,
            all(item.get("angle") != 5 for item in valid),
            f"{uid}: security second review is not permitted at security level off",
        )
    return valid


def _verify_tier_a_reasons(
    root: Path,
    unit: dict[str, Any],
    uid: Any,
    unit_paths: list[str],
    requirements: list[dict[str, Any]],
    issues: list[str],
    cache: EvidenceCache,
) -> None:
    if unit.get("riskTier") != "A":
        return
    _issue(
        issues,
        bool(requirements),
        f"{uid}: Tier A requires independent second reviews",
    )
    reasons = unit.get("criticalReasons", [])
    _issue(
        issues,
        isinstance(reasons, list) and bool(reasons),
        f"{uid}: Tier A requires structured criticalReasons",
    )
    if not isinstance(reasons, list):
        return
    declared_symbols = _unit_symbols(root, unit, cache)
    for index, reason in enumerate(reasons):
        locations = reason.get("locations") if isinstance(reason, dict) else None
        valid_locations = (
            isinstance(locations, list)
            and bool(locations)
            and all(
                isinstance(location, dict)
                and (
                    (
                        isinstance(location.get("path"), str)
                        and location.get("path") in unit_paths
                    )
                    or (
                        isinstance(location.get("symbol"), str)
                        and location.get("symbol") in declared_symbols
                    )
                )
                for location in locations
            )
        )
        valid = (
            isinstance(reason, dict)
            and _is_one_of(reason.get("code"), TIER_A_REASON_CODES)
            and valid_locations
            and all(
                isinstance(reason.get(field), str) and bool(reason[field].strip())
                for field in (
                    "invariant",
                    "materialConsequence",
                    "whyTierBInsufficient",
                )
            )
        )
        _issue(
            issues,
            valid,
            f"{uid}: malformed Tier A criticalReasons entry {index + 1}",
        )


def _verify_unit(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    current_paths: dict[Any, dict[str, Any]],
    level: str,
    issues: list[str],
    warnings: list[str],
    assignments: Counter[str],
    warm_batches: dict[str, list[tuple[str, str | None]]],
    output_directories: dict[str, str],
    execution_owners: dict[str, str],
    cache: EvidenceCache,
) -> None:
    uid = unit.get("id")
    apply_rules(
        unit,
        UNIT_RULES,
        issues,
        {
            "uid": uid,
            "run": run,
            "level": level,
        },
    )
    unit_paths = unit.get("paths", [])
    if not isinstance(unit_paths, list) or not all(
        isinstance(path, str) for path in unit_paths
    ):
        issues.append(f"{uid}: paths must be an array of strings")
        unit_paths = []
    for path in unit_paths:
        assignments[path] += 1
    path_rows = [current_paths[path] for path in unit_paths if path in current_paths]
    if path_rows:
        expected_identity = canonical_identity(
            sorted(path_rows, key=lambda row: row["path"].encode("utf-8"))
        )
        _issue(
            issues,
            unit.get("contentSetHash") == expected_identity,
            f"{uid}: work-unit content identity mismatch",
        )
    angles = _verify_unit_angles(run, unit, uid, level, issues)
    requirements = _valid_second_review_requirements(
        unit, uid, level, issues
    )
    _verify_tier_a_reasons(
        root,
        unit,
        uid,
        unit_paths,
        requirements,
        issues,
        cache,
    )
    attempts = unit.get("reviewAttempts", [])
    if not isinstance(attempts, list):
        issues.append(f"{uid}: reviewAttempts must be an array")
        attempts = []
    if not all(isinstance(attempt, dict) for attempt in attempts):
        issues.append(f"{uid}: reviewAttempts contains a malformed entry")
        attempts = [attempt for attempt in attempts if isinstance(attempt, dict)]
    attempt_ids = [str(attempt.get("attemptId")) for attempt in attempts]
    _issue(
        issues,
        len(attempt_ids) == len(set(attempt_ids)),
        f"{uid}: duplicate review attempt identifiers",
    )
    for attempt in attempts:
        _verify_attempt(
            root,
            run,
            unit,
            attempt,
            requirements,
            level=level,
            issues=issues,
            warm_batches=warm_batches,
            output_directories=output_directories,
            execution_owners=execution_owners,
            cache=cache,
        )
    _verify_second_reviews(
        root,
        run,
        unit,
        requirements,
        issues=issues,
        cache=cache,
    )
    if unit.get("status") == "complete":
        _issue(
            issues,
            all(
                _is_one_of(
                    angle.get("status"),
                    {"reviewed", "not_applicable", "excluded_by_profile"},
                )
                for angle in angles.values()
            ),
            f"{uid}: complete status contradicts angle lifecycle",
        )
        try:
            missing_scope = missing_primary_scope(
                root, run, unit, cache=cache
            )
        except ReviewToolError as exc:
            issues.append(str(exc))
        else:
            _issue(
                issues,
                not missing_scope,
                f"{uid}: complete status lacks primary scope coverage: "
                f"{missing_scope}",
            )
    _verify_manifest_history(
        root,
        run,
        unit,
        level=level,
        issues=issues,
        warnings=warnings,
        cache=cache,
    )


def _verify_warm_batches(
    warm_batches: dict[str, list[tuple[str, str | None]]],
    issues: list[str],
) -> None:
    for batch_id, members in warm_batches.items():
        _issue(
            issues,
            len(members) <= WARM_BATCH_MAX_ASSIGNMENTS,
            f"warm reviewer batch {batch_id} exceeds "
            f"{WARM_BATCH_MAX_ASSIGNMENTS} assignments",
        )
        principals = {principal for _, principal in members}
        _issue(
            issues,
            len(principals) == 1,
            f"warm reviewer batch {batch_id} uses multiple reviewer principals",
        )


def _verify_generated_views(root: Path, issues: list[str]) -> None:
    manifest_path = root / "report-manifest.json"
    if not manifest_path.exists():
        issues.append("generated views are missing or stale")
        return
    report = load_json(manifest_path)
    if not isinstance(report, dict):
        issues.append("report-manifest.json must be an object")
        return
    _issue(
        issues,
        report.get("canonicalStateDigest") == state_digest(root),
        "generated views are stale",
    )
    outputs = report.get("outputs", {})
    if not isinstance(outputs, dict):
        issues.append("report-manifest.json outputs must be an object")
        return
    for name, expected in outputs.items():
        if not isinstance(name, str):
            issues.append("generated output path must be a string")
            continue
        target = safe_child(root, name)
        _issue(
            issues,
            target.exists() and digest_bytes(target.read_bytes()) == expected,
            f"generated output changed: {name}",
        )


def _review_metrics(
    root: Path,
    run: dict[str, Any],
    units: list[dict[str, Any]],
    acknowledgements: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[int, list[int], list[int], dict[str, Any]]:
    tier_a_count = sum(unit.get("riskTier") == "A" for unit in units)
    diagnostics = pilot_diagnostics(run, units, acknowledgements)
    if diagnostics["warning"]:
        warnings.append(diagnostics["warning"])
    path_counts = [
        len(unit["paths"]) if isinstance(unit.get("paths"), list) else 0
        for unit in units
    ]
    implementation_lines: list[int] = []
    for unit in units:
        manifest_path = unit.get("currentManifest")
        if not isinstance(manifest_path, str) or not manifest_path:
            continue
        try:
            manifest = load_json(safe_child(root, manifest_path))
        except ReviewToolError:
            continue
        if not isinstance(manifest, dict):
            continue
        size_totals = manifest.get("sizeTotals", {})
        lines = (
            size_totals.get("implementationLines")
            if isinstance(size_totals, dict)
            else None
        )
        if isinstance(lines, int) and not isinstance(lines, bool):
            implementation_lines.append(lines)
    return tier_a_count, path_counts, implementation_lines, diagnostics


def _invalid_review_result(issue: str | list[str]) -> dict[str, Any]:
    issues = [issue] if isinstance(issue, str) else issue
    return {
        "ok": False,
        "issues": issues,
        "warnings": [],
        "counts": {
            "baselinePaths": 0,
            "inScopePaths": 0,
            "excludedPaths": 0,
            "securityProfileExcludedPaths": 0,
            "workUnits": 0,
            "observations": 0,
            "validations": 0,
            "auditObjections": 0,
            "tierAUnits": 0,
        },
        "metrics": {
            "tierAShare": 0,
            "pathsPerUnit": [],
            "implementationLinesPerUnit": [],
            "acknowledgedDiagnostics": [],
            "diagnostics": {},
        },
        "bulkDispatchAllowed": False,
    }


def _load_canonical_jsonl(
    root: Path,
    filename: str,
    issues: list[str],
) -> list[dict[str, Any]]:
    try:
        return load_jsonl(root / filename)
    except ReviewToolError as exc:
        issues.append(str(exc))
        return []


def check_review(root: Path, *, check_generated: bool = True) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    cache = EvidenceCache()
    try:
        run = load_json(root / "run.json")
    except ReviewToolError as exc:
        issues.append(str(exc))
        run = None
    paths = _load_canonical_jsonl(root, "paths.jsonl", issues)
    units = _load_canonical_jsonl(root, "work-units.jsonl", issues)
    observations = _load_canonical_jsonl(root, "observations.jsonl", issues)
    validations = _load_canonical_jsonl(root, "validations.jsonl", issues)
    objections = _load_canonical_jsonl(root, "audit-objections.jsonl", issues)
    if not isinstance(run, dict):
        issues.append("run.json must contain an object")
        return _invalid_review_result(issues)

    acknowledgements, level = _verify_run_state(root, run, issues)
    current_paths = _current_path_index(run, paths, issues)
    unit_ids = [str(unit.get("id")) for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        issues.append("work units: duplicate identifiers")
    assignments: Counter[str] = Counter()
    warm_batches: dict[str, list[tuple[str, str | None]]] = {}
    output_directories: dict[str, str] = {}
    execution_owners: dict[str, str] = {}

    for unit in units:
        try:
            _verify_unit(
                root,
                run,
                unit,
                current_paths,
                level,
                issues,
                warnings,
                assignments,
                warm_batches,
                output_directories,
                execution_owners,
                cache,
            )
        except (ReviewToolError, OSError, ValueError, TypeError) as exc:
            issues.append(
                f"{unit.get('id')}: unit verification failed safely: {exc}"
            )

    final_audit = run.get("finalAudit")
    if isinstance(final_audit, dict) and final_audit.get("status") == "imported":
        execution = final_audit.get("reviewerExecutionId")
        if isinstance(execution, str) and execution in execution_owners:
            issues.append(
                "final audit reviewerExecutionId is already owned by "
                f"{execution_owners[execution]}"
            )

    _verify_warm_batches(warm_batches, issues)

    _verify_path_partition(current_paths, assignments, level, issues)
    allowed_sources = {
        f"{unit.get('id')}/{attempt.get('attemptId')}"
        for unit in units
        for attempt in unit.get("reviewAttempts", [])
        if isinstance(attempt, dict)
        and _is_one_of(
            attempt.get("importDisposition"),
            {"imported", "reconciled_interruption"},
        )
    }
    # Successor final audits replace run.finalAudit, but validation and objection
    # records imported by earlier audits remain immutable canonical evidence.
    # Preserve every event-recorded audit import as an allowed evidence source.
    for event in load_jsonl(root / "state-events.jsonl"):
        actor = event.get("actor")
        if (
            event.get("operation") == "import_audit"
            and isinstance(actor, str)
            and actor.startswith("FINAL-AUDIT/ATTEMPT-")
        ):
            allowed_sources.add(actor)
    final_audit = run.get("finalAudit")
    if (
        isinstance(final_audit, dict)
        and final_audit.get("status") == "imported"
        and isinstance(final_audit.get("attemptId"), str)
    ):
        allowed_sources.add(f"FINAL-AUDIT/{final_audit['attemptId']}")
    _verify_canonical_graph(
        observations,
        validations,
        objections,
        level,
        allowed_sources,
        {str(unit.get("id")) for unit in units},
        issues,
    )

    if _is_one_of(run.get("verdict"), {"PASS", "CONDITIONAL PASS"}):
        material = [
            row
            for row in observations
            if row.get("materiality") == "material"
            and not _is_one_of(
                row.get("disposition"),
                {"rejected", "duplicate", "withdrawn", "deferred_by_profile"},
            )
        ]
        _issue(issues, not material, "terminal pass verdict has an unresolved material concern")

    for verify in (verify_events, verify_reference_install, verify_transactions):
        try:
            verify(root, issues)
        except (ReviewToolError, OSError, ValueError, TypeError) as exc:
            issues.append(f"{verify.__name__} failed safely: {exc}")
    if check_generated:
        try:
            _verify_generated_views(root, issues)
        except (ReviewToolError, OSError, ValueError, TypeError) as exc:
            issues.append(f"generated-view verification failed safely: {exc}")

    tier_a_count, path_counts, implementation_lines, diagnostics = _review_metrics(
        root, run, units, acknowledgements, warnings
    )

    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "counts": {
            "baselinePaths": len(current_paths),
            "inScopePaths": sum(row.get("exclusion") is None for row in current_paths.values()),
            "excludedPaths": sum(row.get("exclusion") is not None for row in current_paths.values()),
            "securityProfileExcludedPaths": sum(
                row.get("exclusion", {}).get("category") == "security_profile"
                for row in current_paths.values()
                if isinstance(row.get("exclusion"), dict)
            ),
            "workUnits": len(units),
            "observations": len(observations),
            "validations": len(validations),
            "auditObjections": len(objections),
            "tierAUnits": tier_a_count,
        },
        "metrics": {
            "tierAShare": tier_a_count / len(units) if units else 0,
            "pathsPerUnit": path_counts,
            "implementationLinesPerUnit": implementation_lines,
            "acknowledgedDiagnostics": acknowledgements,
            "diagnostics": {
                TIER_A_DENSITY_DIAGNOSTIC: {
                    "identity": diagnostics["identity"],
                    "acknowledged": diagnostics["acknowledged"],
                }
            },
        },
        "bulkDispatchAllowed": not issues and diagnostics["bulkDispatchAllowed"],
    }


def require_valid(root: Path, *, check_generated: bool = False) -> None:
    result = check_review(root, check_generated=check_generated)
    if not result["ok"]:
        raise ReviewToolError("proposed state is invalid:\n- " + "\n- ".join(result["issues"]))
