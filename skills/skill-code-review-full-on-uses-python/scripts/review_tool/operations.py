"""Initialization, mutation, imports, reports, and audit operations."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import REVIEW_SPEC_VERSION
from .evidence import (
    EvidenceCache,
    assigned_scope_intersects,
    load_sealed_attempt_manifest,
    load_sealed_unit_manifest,
    missing_primary_scope,
    seal_second_review_history,
    scope_is_valid,
    validate_attempt_manifest_data,
    validate_reviewer_independence,
    validate_review_spec_version,
    validate_second_review_assignment,
    validate_second_review_completion_provenance,
    validate_second_review_payload,
)
from .errors import ReviewToolError
from .identifiers import attempt_token
from .io import (
    atomic_write, canonical_bytes, canonical_identity, digest_bytes, ensure_review_root,
    jsonl_bytes, load_json, load_jsonl, parse_json_bytes, parse_jsonl_bytes,
    safe_child, state_digest,
)
from .references import extract_reference
from .reporting import (
    _format_location,
    _observation_view,
    audit,
    generate,
)
from .security import (
    SECURITY_LEVELS,
    has_declared_security_profile,
    permitted_validation_classes,
    security_level as run_security_level,
    validation_class_allowed,
)
from .transactions import recover, transact

__all__ = [
    "_format_location",
    "_observation_view",
    "audit",
    "generate",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _document_version(data: bytes, label: str) -> int:
    match = re.search(
        rb"(?im)^" + re.escape(label.encode()) + rb" version:\s*(\d+)\b",
        data,
    )
    if not match:
        raise ReviewToolError(f"{label} does not declare its version")
    return int(match.group(1))


def _validate_specification_pair(contract: bytes, pack: bytes) -> int:
    contract_version = _document_version(contract, "Contract")
    pack_version = _document_version(pack, "Reference Pack")
    if contract_version != pack_version:
        raise ReviewToolError(
            f"contract/reference-pack version mismatch: {contract_version} != {pack_version}"
        )
    return contract_version


def _load_v2_run(root: Path) -> dict[str, Any]:
    run = load_json(root / "run.json")
    if not isinstance(run, dict):
        raise ReviewToolError("run.json must contain an object; re-initialize the review")
    validate_review_spec_version(run.get("reviewSpecVersion"))
    if not has_declared_security_profile(run):
        raise ReviewToolError(
            "run.json securityProfile is required; re-initialize the review"
        )
    return run


def initialize(
    review_dir: Path,
    contract: Path,
    reference_pack: Path,
    runtime: str,
    *,
    security_level: str = "off",
    security_source: str = "default",
    stable_reviewer_lineage: bool | None = None,
) -> dict:
    if security_level not in SECURITY_LEVELS:
        raise ReviewToolError(f"invalid security level: {security_level}")
    if security_source not in {"default", "user"}:
        raise ReviewToolError(f"invalid security-level source: {security_source}")
    for label, path in (("contract", contract), ("reference pack", reference_pack)):
        if not path.is_file():
            raise ReviewToolError(f"{label} is not a readable file: {path}")
    root = review_dir.expanduser()
    if root.exists() and (root / "run.json").exists():
        recover(root.resolve())
        existing = _load_v2_run(root.resolve())
        specification = existing.get("specification", {})
        if not isinstance(specification, dict):
            specification = {}
        for label, preserved_key, supplied in (
            ("contract", "contractPreserved", contract),
            ("reference pack", "referencePackPreserved", reference_pack),
        ):
            try:
                preserved_bytes = safe_child(
                    root.resolve(), str(specification.get(preserved_key) or "")
                ).read_bytes()
            except (ReviewToolError, OSError) as exc:
                raise ReviewToolError(
                    f"existing review is missing its preserved {label}: {exc}"
                ) from exc
            if preserved_bytes != supplied.read_bytes():
                raise ReviewToolError(
                    f"existing review preserves a different {label} than the one "
                    "supplied; resume with the preserved specification or start "
                    "a new review"
                )
        if security_source == "user" and security_level != run_security_level(existing):
            raise ReviewToolError(
                "existing review has security level "
                f"{run_security_level(existing)!r}; start a new review to change it"
            )
        if stable_reviewer_lineage is not None and (
            stable_reviewer_lineage
            != existing.get("specialistCapabilities", {}).get(
                "stableReviewerLineage", False
            )
        ):
            raise ReviewToolError(
                "existing review has a different immutable stable-reviewer-lineage capability"
            )
        return {"reviewDirectory": str(root.resolve()), "idempotent": True, "stateDigest": state_digest(root.resolve())}
    if root.exists() and any(root.iterdir()):
        raise ReviewToolError(f"refusing to initialize non-empty unrelated directory: {root}")
    contract_bytes = contract.read_bytes()
    pack_bytes = reference_pack.read_bytes()
    source_version = _validate_specification_pair(contract_bytes, pack_bytes)
    if source_version != REVIEW_SPEC_VERSION:
        raise ReviewToolError(
            f"specification documents declare version {source_version}; "
            f"this tool initializes version {REVIEW_SPEC_VERSION}"
        )
    root = ensure_review_root(root, create=True)
    for directory in ("assignments", "agents", "baseline", "tooling/reference/source", "tooling/transactions"):
        safe_child(root, directory).mkdir(parents=True, exist_ok=True)
    lineage_enabled = stable_reviewer_lineage is True
    atomic_write(root / "tooling/reference/source/contract.md", contract_bytes)
    atomic_write(root / "tooling/reference/source/reference-pack.md", pack_bytes)
    derived = []
    for extract in extract_reference(pack_bytes):
        atomic_write(root / "tooling/reference" / extract.filename, extract.data)
        derived.append({
            "path": extract.filename,
            "sourceSection": extract.section,
            "sourceByteStart": extract.start,
            "sourceByteEnd": extract.end,
            "byteSize": len(extract.data),
            "sha256": digest_bytes(extract.data),
        })
    reference_manifest = {
        "reviewSpecVersion": REVIEW_SPEC_VERSION,
        "specEpoch": "SPEC-0001",
        "sources": [
            {"path": "source/contract.md", "sourcePath": str(contract), "byteSize": len(contract_bytes), "sha256": digest_bytes(contract_bytes)},
            {"path": "source/reference-pack.md", "sourcePath": str(reference_pack), "byteSize": len(pack_bytes), "sha256": digest_bytes(pack_bytes)},
        ],
        "derived": derived,
    }
    reference_manifest_bytes = canonical_bytes(reference_manifest)
    atomic_write(root / "tooling/reference/manifest.json", reference_manifest_bytes)
    atomic_write(
        root / "tooling/reference/source/manifest.json",
        reference_manifest_bytes,
    )
    now = utc_now()
    run = {
        "schemaVersion": 1,
        "reviewSpecVersion": REVIEW_SPEC_VERSION,
        "specEpoch": "SPEC-0001",
        "specification": {
            "initializedAt": now,
            "contractSource": str(contract),
            "contractPreserved": "tooling/reference/source/contract.md",
            "referencePackSource": str(reference_pack),
            "referencePackPreserved": "tooling/reference/source/reference-pack.md",
            "referenceManifestPreserved": "tooling/reference/source/manifest.json",
            "referenceManifestHash": digest_bytes(reference_manifest_bytes),
        },
        "specMigrations": [],
        "repositoryIdentity": "unrecorded",
        "reviewDirectory": str(root),
        "status": "active" if runtime != "none" else "paused",
        "verdict": None,
        "runtimeCapability": runtime,
        "capabilitySource": "harness_declared" if runtime != "none" else "absent_default_none",
        "specialistCapabilities": {
            "stableReviewerLineage": lineage_enabled,
            "source": (
                "harness_declared"
                if lineage_enabled
                else "absent_default_false"
            ),
        },
        "diagnosticAcknowledgements": [],
        "securityProfile": {
            "level": security_level,
            "source": security_source,
            "externalTargets": False,
        },
        "targetPolicy": "frozen_baseline",
        "currentEpoch": "EPOCH-0001",
        "baselineCommit": None,
        "baselineContentSetHash": None,
        "startedAt": now,
        "updatedAt": now,
        "concludedAt": None,
        "budget": None,
        "currentPhase": "baseline",
        "completedPhases": [],
        "checkpointReason": "runtime has no automatic continuation" if runtime == "none" else None,
        "nextActions": ["capture and materialize the frozen baseline", "construct semantic work units", "run the representative pilot"],
        "schemaMigrations": [],
        "stateEventHead": None,
        "supersededBy": None,
        "generatedStateDigest": None,
        "finalAudit": None,
    }
    replacements = {
        "run.json": canonical_bytes(run),
        "paths.jsonl": b"",
        "work-units.jsonl": b"",
        "observations.jsonl": b"",
        "validations.jsonl": b"",
        "audit-objections.jsonl": b"",
        "architecture.md": b"# Review architecture\n\nArchitecture discovery has not yet been completed.\n",
    }
    result = transact(root, replacements, operation="init", actor="orchestrator", timestamp=now, expected_digest=None)
    return {"reviewDirectory": str(root), "idempotent": False, **result}


def _encode_mutation_changes(changes_path: Path | None) -> dict[str, bytes]:
    if changes_path is None:
        return {}
    changes = load_json(changes_path)
    if not isinstance(changes, dict) or not changes:
        raise ReviewToolError(
            "changes file must contain a non-empty object of canonical replacements"
        )
    replacements: dict[str, bytes] = {}
    for relative, value in changes.items():
        if relative.startswith("assignments/"):
            replacements[relative] = (
                canonical_bytes(value)
                if not isinstance(value, str)
                else value.encode()
            )
        elif relative.endswith(".jsonl"):
            if not isinstance(value, list):
                raise ReviewToolError(
                    f"{relative} replacement must be a JSON array"
                )
            replacements[relative] = jsonl_bytes(value)
        elif relative.endswith(".json"):
            replacements[relative] = canonical_bytes(value)
        elif relative == "architecture.md" and isinstance(value, str):
            replacements[relative] = value.encode()
        else:
            raise ReviewToolError(f"unauthorized mutation target: {relative}")
    return replacements


def _proposed_jsonl(data: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(data.splitlines(), 1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewToolError(f"invalid proposed {label}:{number}") from exc
        if not isinstance(row, dict):
            raise ReviewToolError(
                f"invalid proposed {label}:{number}: row must be an object"
            )
        rows.append(row)
    return rows


def _rows_by_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ReviewToolError(f"{label} row requires a non-empty id")
        if identifier in indexed:
            raise ReviewToolError(f"duplicate {label} identifier: {identifier}")
        indexed[identifier] = row
    return indexed


def _validate_immutable_prefix(
    old: Any,
    new: Any,
    label: str,
    *,
    allowed_appends: int | None,
) -> None:
    if not isinstance(old, list) or not isinstance(new, list):
        raise ReviewToolError(f"{label} must be an array")
    if new[: len(old)] != old:
        raise ReviewToolError(f"{label} is append-only")
    if (
        allowed_appends is not None
        and len(new) - len(old) > allowed_appends
    ):
        raise ReviewToolError(
            f"{label} may append at most {allowed_appends} entries"
        )


def _validate_run_mutation(
    root: Path,
    proposed: dict[str, bytes],
) -> dict[str, Any]:
    old = _load_v2_run(root)
    if "run.json" not in proposed:
        return old
    try:
        new = json.loads(proposed["run.json"])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewToolError("proposed run.json is invalid") from exc
    if not isinstance(new, dict):
        raise ReviewToolError("proposed run.json must be an object")
    legal = {
        "active": {"active", "paused", "concluded", "superseded"},
        "paused": {"paused", "active", "concluded", "superseded"},
        "concluded": {"concluded"},
        "superseded": {"superseded"},
    }
    new_status = new.get("status")
    old_status = old.get("status")
    if (
        not isinstance(new_status, str)
        or not isinstance(old_status, str)
        or new_status not in legal.get(old_status, set())
    ):
        raise ReviewToolError(
            f"invalid status transition: {old_status} -> {new_status}"
        )
    if new.get("securityProfile") != old.get("securityProfile"):
        raise ReviewToolError(
            "securityProfile is immutable; start a new review to change it"
        )
    if new.get("reviewSpecVersion") != old.get("reviewSpecVersion"):
        raise ReviewToolError("reviewSpecVersion is immutable; start a new review")
    if new.get("specialistCapabilities") != old.get("specialistCapabilities"):
        raise ReviewToolError("specialistCapabilities are immutable")
    if new.get("specification") != old.get("specification"):
        raise ReviewToolError("run.json specification provenance is immutable")
    if new.get("specMigrations") != old.get("specMigrations"):
        raise ReviewToolError("run.json specMigrations are immutable")
    if new.get("specEpoch") != old.get("specEpoch"):
        raise ReviewToolError("run.json specEpoch is immutable")
    validate_review_spec_version(new.get("reviewSpecVersion"))
    return new


def _is_lifecycle_supersession(
    old_attempt: dict[str, Any], new_attempt: Any
) -> bool:
    if not isinstance(new_attempt, dict):
        return False
    mutable_fields = {"status", "importDisposition", "supersededReason"}
    old_sealed = {
        key: value for key, value in old_attempt.items() if key not in mutable_fields
    }
    new_sealed = {
        key: value for key, value in new_attempt.items() if key not in mutable_fields
    }
    return (
        old_attempt.get("importDisposition") == "pending"
        and new_attempt.get("importDisposition") == "superseded"
        and new_attempt.get("status") == "interrupted"
        and isinstance(new_attempt.get("supersededReason"), str)
        and bool(new_attempt["supersededReason"].strip())
        and old_sealed == new_sealed
    )


def _validate_new_attempt(
    identifier: str, attempt_id: Any, attempt: Any
) -> dict[str, Any]:
    if not isinstance(attempt, dict):
        raise ReviewToolError(
            f"new review attempt must be an object: {identifier}/{attempt_id}"
        )
    if (
        attempt.get("status") != "assigned"
        or attempt.get("importDisposition") != "pending"
        or attempt.get("resultHash") is not None
        or attempt.get("attemptEvidenceHash") is not None
    ):
        raise ReviewToolError(
            "new review attempt must start assigned and pending without imported "
            f"evidence: {identifier}/{attempt_id}"
        )
    return attempt


def _validate_work_unit_transitions(
    old_units: dict[str, dict[str, Any]],
    new_units: dict[str, dict[str, Any]],
) -> None:
    work_legal = {
        "pending": {"pending", "assigned", "blocked"},
        "assigned": {"assigned", "partial", "complete", "blocked", "needs_revalidation"},
        "partial": {"partial", "assigned", "blocked", "needs_revalidation"},
        "complete": {"complete", "needs_revalidation"},
        "blocked": {"blocked", "pending", "assigned", "needs_revalidation"},
        "needs_revalidation": {"needs_revalidation", "assigned", "blocked"},
    }
    angle_legal = {
        "pending": {
            "pending",
            "reviewed",
            "not_applicable",
            "excluded_by_profile",
            "blocked",
        },
        "reviewed": {"reviewed", "needs_revalidation"},
        "not_applicable": {"not_applicable", "needs_revalidation"},
        "excluded_by_profile": {"excluded_by_profile", "needs_revalidation"},
        "blocked": {"blocked", "pending"},
        "needs_revalidation": {
            "needs_revalidation",
            "reviewed",
            "not_applicable",
            "excluded_by_profile",
            "blocked",
        },
    }
    for identifier, old in old_units.items():
        if identifier not in new_units:
            raise ReviewToolError(
                f"work unit deletion is not a legal transition: {identifier}"
            )
        new = new_units[identifier]
        new_status = new.get("status")
        old_status = old.get("status")
        if (
            not isinstance(new_status, str)
            or not isinstance(old_status, str)
            or new_status not in work_legal.get(old_status, set())
        ):
            raise ReviewToolError(
                f"invalid work-unit status transition for {identifier}: "
                f"{old_status} -> {new_status}"
            )
        if new.get("securityLevel") != old.get("securityLevel"):
            raise ReviewToolError(
                f"work-unit securityLevel is immutable: {identifier}"
            )
        _validate_immutable_prefix(
            old.get("manifestHistory", []),
            new.get("manifestHistory", []),
            f"{identifier}: manifestHistory",
            allowed_appends=0,
        )
        _validate_immutable_prefix(
            old.get("secondReviewHistory", []),
            new.get("secondReviewHistory", []),
            f"{identifier}: secondReviewHistory",
            allowed_appends=0,
        )
        old_attempts = {
            item.get("attemptId"): item
            for item in old.get("reviewAttempts", [])
            if isinstance(item, dict)
        }
        new_attempt_rows = new.get("reviewAttempts")
        if not isinstance(new_attempt_rows, list):
            raise ReviewToolError(f"{identifier}: reviewAttempts must be an array")
        new_attempts = {
            item.get("attemptId"): item
            for item in new_attempt_rows
            if isinstance(item, dict)
        }
        if len(new_attempts) != len(new_attempt_rows):
            raise ReviewToolError(
                f"{identifier}: reviewAttempts must contain unique objects"
            )
        for attempt_id, old_attempt in old_attempts.items():
            new_attempt = new_attempts.get(attempt_id)
            if new_attempt != old_attempt and not _is_lifecycle_supersession(
                old_attempt, new_attempt
            ):
                raise ReviewToolError(
                    f"sealed review attempt is immutable: {identifier}/{attempt_id}"
                )
        for attempt_id, new_attempt in new_attempts.items():
            if attempt_id not in old_attempts:
                _validate_new_attempt(identifier, attempt_id, new_attempt)
        old_angles = old.get("angles")
        new_angles = new.get("angles")
        if not isinstance(old_angles, dict) or not isinstance(new_angles, dict):
            raise ReviewToolError(f"{identifier}: angles must be an object")
        for number, old_angle in old_angles.items():
            if number not in new_angles:
                raise ReviewToolError(
                    f"angle disposition removed from {identifier}: {number}"
                )
            if not isinstance(old_angle, dict) or not isinstance(
                new_angles[number], dict
            ):
                raise ReviewToolError(
                    f"angle disposition must be an object: {identifier}/{number}"
                )
            new_status = new_angles[number].get("status")
            old_status = old_angle.get("status")
            if (
                not isinstance(new_status, str)
                or not isinstance(old_status, str)
                or new_status not in angle_legal.get(old_status, set())
            ):
                raise ReviewToolError(
                    f"invalid angle transition for {identifier}/{number}: "
                    f"{old_status} -> {new_status}"
                )


def _load_proposed_attempt_manifest(
    root: Path,
    proposed: dict[str, bytes],
    reference: str,
) -> dict[str, Any]:
    data = proposed.get(reference)
    if data is None:
        path = safe_child(root, reference)
        if not path.is_file():
            raise ReviewToolError(f"attempt manifest is missing: {reference}")
        data = path.read_bytes()
    try:
        manifest = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewToolError(f"invalid attempt manifest: {reference}") from exc
    if not isinstance(manifest, dict):
        raise ReviewToolError(f"attempt manifest must be an object: {reference}")
    return manifest


def _load_proposed_unit_manifest(
    root: Path,
    proposed: dict[str, bytes],
    unit: dict[str, Any],
    attempt_manifest: dict[str, Any],
) -> dict[str, Any]:
    reference = attempt_manifest.get("unitManifest")
    if not isinstance(reference, str):
        raise ReviewToolError(f"{unit.get('id')}: attempt unitManifest is required")
    data = proposed.get(reference)
    if data is None:
        path = safe_child(root, reference)
        if not path.is_file():
            raise ReviewToolError(f"unit manifest is missing: {reference}")
        data = path.read_bytes()
    if digest_bytes(data) != attempt_manifest.get("unitManifestHash"):
        raise ReviewToolError(f"{unit.get('id')}: unit manifest identity mismatch")
    manifest = parse_json_bytes(data, reference)
    if not isinstance(manifest, dict):
        raise ReviewToolError(f"unit manifest must be an object: {reference}")
    return manifest


def _validate_attempt_ownership(
    root: Path,
    proposed: dict[str, bytes],
    run: dict[str, Any],
    units: dict[str, dict[str, Any]],
) -> None:
    output_owners: dict[str, str] = {}
    execution_owners: dict[str, str] = {}
    for identifier, unit in units.items():
        attempts = unit.get("reviewAttempts")
        if not isinstance(attempts, list) or not all(
            isinstance(item, dict) for item in attempts
        ):
            raise ReviewToolError(f"{identifier}: reviewAttempts is malformed")
        seen_ids: set[str] = set()
        for attempt in attempts:
            attempt_id = attempt.get("attemptId")
            label = f"{identifier}/{attempt_id}"
            if not isinstance(attempt_id, str) or not attempt_id.strip():
                raise ReviewToolError(f"{identifier}: attemptId is required")
            if attempt_id in seen_ids:
                raise ReviewToolError(f"duplicate review attempt: {label}")
            seen_ids.add(attempt_id)
            reference = attempt.get("manifest")
            if not isinstance(reference, str):
                raise ReviewToolError(f"attempt manifest path is required: {label}")
            data = proposed.get(reference)
            if data is None:
                path = safe_child(root, reference)
                if not path.is_file():
                    raise ReviewToolError(f"attempt manifest is missing: {reference}")
                data = path.read_bytes()
            if digest_bytes(data) != attempt.get("manifestHash"):
                raise ReviewToolError(f"attempt manifest identity mismatch: {label}")
            manifest = _load_proposed_attempt_manifest(root, proposed, reference)
            validate_attempt_manifest_data(root, unit, attempt, manifest, run)
            unit_manifest = _load_proposed_unit_manifest(
                root, proposed, unit, manifest
            )
            validate_second_review_assignment(unit, unit_manifest, manifest)
            execution = str(manifest["reviewerExecutionId"])
            prior_execution = execution_owners.setdefault(execution, label)
            if prior_execution != label:
                raise ReviewToolError(
                    "reviewerExecutionId must identify exactly one attempt: "
                    f"{label} and {prior_execution}"
                )
            output = str(manifest["outputDirectory"])
            prior = output_owners.setdefault(output, label)
            if prior != label:
                raise ReviewToolError(
                    f"attempt outputDirectory collision: {label} and {prior}"
                )


def _validate_observation_transitions(
    root: Path, proposed: dict[str, bytes]
) -> None:
    if "observations.jsonl" not in proposed:
        return
    old_rows = _rows_by_id(
        load_jsonl(root / "observations.jsonl"), "observation"
    )
    new_rows = _rows_by_id(
        _proposed_jsonl(proposed["observations.jsonl"], "observations.jsonl"),
        "observation",
    )
    added = set(new_rows) - set(old_rows)
    if added:
        raise ReviewToolError(
            "canonical observations can be created only by evidence import: "
            f"{sorted(added)}"
        )
    legal = {
        "open": {
            "open",
            "validated",
            "rejected",
            "duplicate",
            "unresolved",
            "deferred_by_profile",
        },
        "unresolved": {
            "unresolved",
            "open",
            "validated",
            "rejected",
            "duplicate",
            "deferred_by_profile",
        },
        "validated": {"validated", "withdrawn"},
        "rejected": {"rejected"},
        "duplicate": {"duplicate"},
        "withdrawn": {"withdrawn"},
        "deferred_by_profile": {"deferred_by_profile"},
    }
    mutable_fields = {
        "disposition",
        "reportClass",
        "findingId",
        "severity",
        "materiality",
        "materialityRationale",
        "duplicateOf",
        "withdrawal",
        "profileDeferral",
        "updatedAt",
    }
    for identifier, old in old_rows.items():
        if identifier not in new_rows:
            raise ReviewToolError(
                f"observation deletion is not a legal transition: {identifier}"
            )
        new_status = new_rows[identifier].get("disposition")
        old_status = old.get("disposition")
        if (
            not isinstance(new_status, str)
            or not isinstance(old_status, str)
            or new_status not in legal.get(old_status, set())
        ):
            raise ReviewToolError(
                f"invalid observation transition for {identifier}: "
                f"{old_status} -> {new_status}"
            )
        new = new_rows[identifier]
        for field in set(old) | set(new):
            if field not in mutable_fields and old.get(field) != new.get(field):
                raise ReviewToolError(
                    f"immutable observation evidence changed: "
                    f"{identifier}/{field}"
                )


def _validate_validation_transitions(
    root: Path, proposed: dict[str, bytes]
) -> None:
    if "validations.jsonl" not in proposed:
        return
    old_rows = _rows_by_id(
        load_jsonl(root / "validations.jsonl"), "validation"
    )
    new_rows = _rows_by_id(
        _proposed_jsonl(proposed["validations.jsonl"], "validations.jsonl"),
        "validation",
    )
    added = set(new_rows) - set(old_rows)
    if added:
        raise ReviewToolError(
            "canonical validations can be created only by evidence import: "
            f"{sorted(added)}"
        )
    for identifier, old in old_rows.items():
        if identifier not in new_rows:
            raise ReviewToolError(
                f"validation deletion is not a legal transition: {identifier}"
            )
        if new_rows[identifier] != old:
            raise ReviewToolError(
                f"imported validation evidence is immutable: {identifier}"
            )


def _validate_mutation(
    root: Path,
    proposed: dict[str, bytes],
) -> None:
    run = _validate_run_mutation(root, proposed)
    for relative, data in proposed.items():
        if relative.startswith("assignments/"):
            existing = safe_child(root, relative)
            if existing.exists() and existing.read_bytes() != data:
                raise ReviewToolError(
                    f"immutable assignment cannot be replaced: {relative}"
                )
        if relative.startswith("tooling/reference/"):
            existing = safe_child(root, relative)
            if not existing.exists() or existing.read_bytes() != data:
                raise ReviewToolError(
                    f"reference installation is immutable: {relative}"
                )
    if "work-units.jsonl" in proposed:
        old_units = _rows_by_id(
            load_jsonl(root / "work-units.jsonl"), "work-unit"
        )
        new_units = _rows_by_id(
            _proposed_jsonl(proposed["work-units.jsonl"], "work-units.jsonl"),
            "work-unit",
        )
        _validate_work_unit_transitions(old_units, new_units)
        _validate_attempt_ownership(root, proposed, run, new_units)
    _validate_observation_transitions(root, proposed)
    _validate_validation_transitions(root, proposed)


def apply_mutation(root: Path, expected: str, changes_path: Path | None) -> dict:
    root = ensure_review_root(root)
    recover(root)
    _load_v2_run(root)
    replacements = _encode_mutation_changes(changes_path)
    if not replacements:
        raise ReviewToolError("mutate requires --changes")
    return transact(
        root,
        replacements,
        operation="mutate",
        actor="orchestrator",
        timestamp=utc_now(),
        expected_digest=expected,
        validator=lambda _root, proposed: _validate_mutation(root, proposed),
    )


def _allocate(rows: list[dict], field: str, prefix: str, width: int) -> str:
    numbers = []
    pattern = re.compile(rf"{prefix}-(\d{{{width}}})$")
    for row in rows:
        match = pattern.fullmatch(str(row.get(field, "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}-{(max(numbers, default=0) + 1):0{width}d}"


def _candidate_observation(
    candidate: dict,
    *,
    identifier: str,
    source_work_units: list[str],
    source_attempt: str,
    default_title: str,
    default_category: str,
) -> dict:
    return {
        "id": identifier,
        "sourceWorkUnits": source_work_units,
        "sourceAttempt": source_attempt,
        "sourceLocalId": candidate.get("localId"),
        "title": candidate.get("title", default_title),
        "category": candidate.get("category", default_category),
        "primaryLocation": candidate.get("primaryLocation"),
        "additionalLocations": candidate.get("additionalLocations", []),
        "disposition": "open",
        "proposedDisposition": candidate.get("proposedDisposition", candidate.get("disposition")),
        "reportClass": None,
        "findingId": None,
        "severity": None,
        "materiality": None,
        "proposedMateriality": candidate.get("proposedMateriality", candidate.get("materiality")),
        "materialityRationale": None,
        "proposedMaterialityRationale": candidate.get(
            "proposedMaterialityRationale",
            candidate.get("materialityRationale"),
        ),
        "confidence": candidate.get("confidence", "Low"),
        "affectedComponents": candidate.get("affectedComponents", []),
        "affectedConfigurations": candidate.get("affectedConfigurations", []),
        "affectedDeployments": candidate.get("affectedDeployments", []),
        "evidence": candidate.get("evidence", []),
        "counterargument": candidate.get("counterargument", ""),
        "trigger": candidate.get("trigger", ""),
        "expected": candidate.get("expected", ""),
        "actual": candidate.get("actual", ""),
        "impact": candidate.get("impact", ""),
        "likelihood": candidate.get("likelihood", ""),
        "blastRadius": candidate.get("blastRadius", ""),
        "reachability": candidate.get("reachability", ""),
        "existingChecks": candidate.get("existingChecks", ""),
        "reproduction": candidate.get("reproduction", ""),
        "recommendation": candidate.get("recommendation", candidate.get("remediation", "")),
        "regressionTest": candidate.get("regressionTest", ""),
        "residualUncertainty": candidate.get("residualUncertainty", ""),
        "validationRefs": [],
        "duplicateOf": None,
        "withdrawal": None,
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
    }


def _validate_import_unit(unit: dict[str, Any], work_id: str) -> None:
    for field in ("reviewAttempts", "requiredSecondReviews", "completedSecondReviews"):
        value = unit.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise ReviewToolError(f"{work_id}: {field} is malformed")
    history = unit.get("secondReviewHistory", [])
    if not isinstance(history, list) or not all(
        isinstance(item, dict) for item in history
    ):
        raise ReviewToolError(f"{work_id}: secondReviewHistory is malformed")
    angles = unit.get("angles")
    if not isinstance(angles, dict) or not all(
        isinstance(item, dict) for item in angles.values()
    ):
        raise ReviewToolError(f"{work_id}: angles is malformed")
    for requirement in unit["requiredSecondReviews"]:
        angle = requirement.get("angle")
        if (
            not isinstance(requirement.get("id"), str)
            or not requirement["id"].strip()
            or not isinstance(angle, int)
            or isinstance(angle, bool)
            or not 1 <= angle <= 10
            or not scope_is_valid(requirement.get("scope"))
        ):
            raise ReviewToolError(
                f"{work_id}: requiredSecondReviews contains a malformed requirement"
            )
    requirement_ids = [
        requirement["id"] for requirement in unit["requiredSecondReviews"]
    ]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ReviewToolError(
            f"{work_id}: requiredSecondReviews contains duplicate identifiers"
        )
    for completion in unit["completedSecondReviews"]:
        if not isinstance(completion.get("requirementId"), str):
            raise ReviewToolError(
                f"{work_id}: completedSecondReviews contains a malformed requirementId"
            )


def _import_local_evidence(
    work_id: str,
    attempt_id: str,
    result: dict[str, Any],
    local_validations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    security_level: str,
) -> dict[str, str]:
    token = attempt_token(attempt_id)
    source_attempt = f"{work_id}/{attempt_id}"
    local_candidates = result["candidates"]
    candidate_map: dict[str, str] = {}
    imported_candidates: dict[str, dict[str, Any]] = {}
    for candidate in local_candidates:
        local_id = str(candidate["localId"])
        if not re.fullmatch(rf"CAND-{token}-\d{{3}}", local_id):
            raise ReviewToolError(
                f"invalid local candidate identifier after preflight: {local_id}"
            )
        canonical_id = _allocate(observations, "id", "OBS", 6)
        candidate_map[local_id] = canonical_id
        imported = _candidate_observation(
            candidate,
            identifier=canonical_id,
            source_work_units=[work_id],
            source_attempt=source_attempt,
            default_title="Untitled observation",
            default_category="unspecified",
        )
        observations.append(imported)
        imported_candidates[local_id] = imported
    validation_map: dict[str, str] = {}
    for row in local_validations:
        local_id = str(row["localId"])
        if not re.fullmatch(rf"AVAL-{token}-\d{{3}}", local_id):
            raise ReviewToolError(
                f"invalid local validation identifier after preflight: {local_id}"
            )
        validation_class = str(row["validationClass"])
        if not validation_class_allowed(security_level, validation_class):
            raise ReviewToolError(
                f"validation class {validation_class!r} is not permitted at "
                f"security level {security_level!r}"
            )
        canonical_id = _allocate(validations, "id", "VAL", 6)
        validation_map[local_id] = canonical_id
        validations.append(
            {
                "id": canonical_id,
                "sourceAttempt": source_attempt,
                "sourceLocalId": local_id,
                "workUnits": [work_id],
                "observationIds": [
                    candidate_map[item] for item in row["supportsCandidates"]
                ],
                **{
                    key: row.get(key)
                    for key in (
                        "command",
                        "cwd",
                        "environmentSummary",
                        "startedAt",
                        "endedAt",
                        "exitStatus",
                        "result",
                        "limitations",
                        "createdArtifacts",
                    )
                },
                "trackedTreeMutation": row.get("trackedTreeMutation"),
                "validationClass": validation_class,
                "securityLevel": security_level,
            }
        )
    for candidate in local_candidates:
        local_id = str(candidate["localId"])
        imported_candidates[local_id]["validationRefs"] = [
            validation_map[reference]
            for reference in candidate.get("validationRefs", [])
        ]
    return candidate_map


def _record_attempt_import(
    unit: dict[str, Any],
    attempt: dict[str, Any],
    result: dict[str, Any],
    local_validations: list[dict[str, Any]],
    result_bytes: bytes,
    work_id: str,
    attempt_id: str,
) -> None:
    attempt["status"] = result["status"]
    attempt["resultHash"] = digest_bytes(result_bytes)
    attempt["attemptEvidenceHash"] = canonical_identity(
        {"result": result, "validations": local_validations}
    )
    attempt["importDisposition"] = "imported"
    if result["packetType"] != "primary_semantic":
        return
    source_attempt = f"{work_id}/{attempt_id}"
    for number, disposition in result["angleDispositions"].items():
        if number not in unit["angles"]:
            raise ReviewToolError(f"result includes unassigned angle: {number}")
        unit["angles"][number] = {
            "status": disposition["status"],
            "evidence": [
                {"sourceAttempt": source_attempt, **item}
                for item in disposition["evidence"]
            ],
            "specEpoch": result["specEpoch"],
        }


def _history(unit: dict[str, Any]) -> list[dict[str, Any]]:
    history = unit.setdefault("secondReviewHistory", [])
    if not isinstance(history, list):
        raise ReviewToolError(f"{unit.get('id')}: secondReviewHistory is malformed")
    return history


def _archive_second_review_completion(
    unit: dict[str, Any],
    completion: dict[str, Any],
    reason: str,
) -> None:
    history = _history(unit)
    previous_hash = (
        history[-1].get("historyHash")
        if history and isinstance(history[-1], dict)
        else None
    )
    if previous_hash is not None and not isinstance(previous_hash, str):
        raise ReviewToolError(
            f"{unit.get('id')}: secondReviewHistory chain is malformed"
        )
    history.append(
        seal_second_review_history(
            completion,
            reason,
            previous_history_hash=previous_hash,
        )
    )


def _invalidate_primary_dependent_reviews(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any],
    work_id: str,
    attempt_id: str,
) -> bool:
    requirements = {
        item.get("id"): item for item in unit["requiredSecondReviews"]
    }
    assigned_scope = manifest["assignedScope"]
    for pending in unit["reviewAttempts"]:
        if (
            pending is attempt
            or pending.get("packetType") != "independent_second_review"
            or pending.get("importDisposition") != "pending"
        ):
            continue
        pending_manifest = load_sealed_attempt_manifest(root, unit, pending, run)
        requirement = requirements.get(
            pending_manifest.get("secondReviewRequirementId")
        )
        if requirement and assigned_scope_intersects(assigned_scope, requirement):
            pending["status"] = "interrupted"
            pending["importDisposition"] = "superseded"
            pending["supersededReason"] = (
                f"primary evidence changed by {work_id}/{attempt_id}"
            )
    invalidated = False
    retained: list[dict[str, Any]] = []
    for completion in unit["completedSecondReviews"]:
        requirement = requirements.get(completion.get("requirementId"))
        if requirement and assigned_scope_intersects(assigned_scope, requirement):
            _archive_second_review_completion(
                unit,
                completion,
                "later intersecting primary evidence imported from "
                f"{work_id}/{attempt_id}",
            )
            invalidated = True
        else:
            retained.append(completion)
    unit["completedSecondReviews"] = retained
    return invalidated


def _record_second_review(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any],
    result: dict[str, Any],
    candidate_map: dict[str, str],
    work_id: str,
    attempt_id: str,
) -> None:
    requirement_id = manifest["secondReviewRequirementId"]
    requirement = next(
        (
            item
            for item in unit["requiredSecondReviews"]
            if item.get("id") == requirement_id
        ),
        None,
    )
    if requirement is None:
        raise ReviewToolError("second-review attempt names no current requirement")
    if result["status"] != "complete":
        return
    second = result["secondReviewResults"][0]
    validate_second_review_payload(
        second, requirement, candidate_ids=set(candidate_map)
    )
    independent_ids, evidence_hash = validate_reviewer_independence(
        root,
        run,
        unit,
        requirement,
        independent_ids=manifest["independentFromAttemptIds"],
        evidence_set_hash=manifest["primaryEvidenceSetHash"],
        reviewer_principal_id=result["reviewerPrincipalId"],
        reviewer_execution_id=result["reviewerExecutionId"],
    )
    retained: list[dict[str, Any]] = []
    for completion in unit["completedSecondReviews"]:
        if completion.get("requirementId") == requirement_id:
            _archive_second_review_completion(
                unit,
                completion,
                f"replaced by {work_id}/{attempt_id}",
            )
        else:
            retained.append(completion)
    candidate_refs = second["candidateRefs"]
    retained.append(
        {
            "requirementId": requirement_id,
            "required": requirement,
            "attempt": f"{work_id}/{attempt_id}",
            "attemptManifestHash": attempt["manifestHash"],
            "reviewerExecutionId": result["reviewerExecutionId"],
            "reviewerPrincipalId": result["reviewerPrincipalId"],
            "independentFromAttemptIds": independent_ids,
            "primaryEvidenceSetHash": evidence_hash,
            "scopeCovered": second["scopeCovered"],
            "evidence": second.get("evidence", []),
            "conclusion": second.get("conclusion"),
            "candidateRefs": candidate_refs,
            "observations": [candidate_map[reference] for reference in candidate_refs],
            "specEpoch": result["specEpoch"],
            "stale": False,
        }
    )
    unit["completedSecondReviews"] = retained


def _merge_residual_uncertainty(
    unit: dict[str, Any],
    result: dict[str, Any],
    work_id: str,
    attempt_id: str,
) -> None:
    source_attempt = f"{work_id}/{attempt_id}"
    existing = unit.get("residualUncertainty")
    if not isinstance(existing, list):
        existing = []
    retained = [
        item
        for item in existing
        if not isinstance(item, dict)
        or item.get("sourceAttempt") != source_attempt
    ]
    for uncertainty in result["residualUncertainty"]:
        record = {"sourceAttempt": source_attempt, "value": uncertainty}
        if record not in retained:
            retained.append(record)
    unit["residualUncertainty"] = retained


def _read_specialist_evidence(
    result_path: Path,
    validations_path: Path,
) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    try:
        result_bytes = result_path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSON file: {result_path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"cannot read {result_path}: {exc}") from exc
    try:
        validations_bytes = validations_path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSONL file: {validations_path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"cannot read {validations_path}: {exc}") from exc
    result = parse_json_bytes(result_bytes, str(result_path))
    if not isinstance(result, dict):
        raise ReviewToolError("specialist result must be an object")
    validations = parse_jsonl_bytes(
        validations_bytes,
        str(validations_path),
    )
    return result_bytes, result, validations


def _satisfied_second_reviews(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    observations: list[dict[str, Any]],
) -> set[str]:
    requirements = {
        item.get("id"): item for item in unit["requiredSecondReviews"]
    }
    completed: set[str] = set()
    for completion in unit["completedSecondReviews"]:
        requirement = requirements.get(completion.get("requirementId"))
        if requirement is None:
            raise ReviewToolError("active second-review completion is orphaned")
        validate_second_review_completion_provenance(
            root,
            run,
            unit,
            requirement,
            completion,
            observations=observations,
        )
        validate_reviewer_independence(
            root,
            run,
            unit,
            requirement,
            independent_ids=completion.get("independentFromAttemptIds"),
            evidence_set_hash=completion.get("primaryEvidenceSetHash"),
            reviewer_principal_id=completion.get("reviewerPrincipalId"),
            reviewer_execution_id=completion.get("reviewerExecutionId"),
        )
        completed.add(str(completion["requirementId"]))
    return completed


def _update_unit_after_import(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    result: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    was_needs_revalidation: bool,
    invalidated_second_review: bool,
    cache: EvidenceCache,
) -> None:
    completed = _satisfied_second_reviews(root, run, unit, observations)
    requirements_satisfied = all(
        isinstance(item.get("id"), str) and item["id"] in completed
        for item in unit["requiredSecondReviews"]
    )
    all_angles_complete = all(
        isinstance(item.get("status"), str)
        and item["status"] in {"reviewed", "not_applicable", "excluded_by_profile"}
        for item in unit["angles"].values()
    )
    if invalidated_second_review or (
        was_needs_revalidation and not requirements_satisfied
    ):
        unit["status"] = "needs_revalidation"
    elif (
        result["status"] == "complete"
        and all_angles_complete
        and requirements_satisfied
        and not missing_primary_scope(root, run, unit, cache=cache)
    ):
        unit["status"] = "complete"
    elif result["status"] in {"partial", "blocked"}:
        unit["status"] = result["status"]
    else:
        unit["status"] = "partial"
    unit["updatedAt"] = utc_now()


def import_specialist(root: Path, work_id: str, attempt_id: str, expected: str) -> dict:
    root = ensure_review_root(root)
    recover(root)
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    unit = next((item for item in units if item.get("id") == work_id), None)
    if not unit:
        raise ReviewToolError(f"unknown work unit: {work_id}")
    _validate_import_unit(unit, work_id)
    was_needs_revalidation = unit.get("status") == "needs_revalidation"
    attempt = next(
        (
            item
            for item in unit["reviewAttempts"]
            if item.get("attemptId") == attempt_id
        ),
        None,
    )
    if not attempt:
        raise ReviewToolError(f"unknown attempt: {work_id}/{attempt_id}")
    if attempt.get("importDisposition") != "pending":
        raise ReviewToolError(
            f"attempt has already been reconciled: {work_id}/{attempt_id}"
        )
    run = _load_v2_run(root)
    cache = EvidenceCache()
    manifest = load_sealed_attempt_manifest(
        root, unit, attempt, run, cache=cache
    )
    unit_manifest = load_sealed_unit_manifest(
        root, unit, manifest, cache=cache
    )
    validate_second_review_assignment(unit, unit_manifest, manifest)
    output_directory = str(manifest["outputDirectory"])
    result_path = safe_child(root, f"{output_directory}/result.json")
    validations_path = safe_child(root, f"{output_directory}/validations.jsonl")
    result_bytes, result, local_validations = _read_specialist_evidence(
        result_path,
        validations_path,
    )
    from .packets import validate_attempt_result_data

    preflight = validate_attempt_result_data(
        root,
        run,
        unit,
        attempt,
        manifest,
        result,
        local_validations,
    )
    if not preflight["ok"]:
        raise ReviewToolError(
            "specialist result failed attempt checks:\n- "
            + "\n- ".join(preflight["issues"])
        )
    level = run_security_level(run)
    candidate_map = _import_local_evidence(
        work_id,
        attempt_id,
        result,
        local_validations,
        observations,
        validations,
        level,
    )
    _record_attempt_import(
        unit,
        attempt,
        result,
        local_validations,
        result_bytes,
        work_id,
        attempt_id,
    )
    cache.artifacts[
        (
            str(attempt.get("manifestHash")),
            str(attempt.get("resultHash")),
            str(attempt.get("attemptEvidenceHash")),
        )
    ] = (result, local_validations)
    invalidated_second_review = False
    if result["packetType"] == "primary_semantic":
        invalidated_second_review = _invalidate_primary_dependent_reviews(
            root,
            run,
            unit,
            attempt,
            manifest,
            work_id,
            attempt_id,
        )
    else:
        _record_second_review(
            root,
            run,
            unit,
            attempt,
            manifest,
            result,
            candidate_map,
            work_id,
            attempt_id,
        )
    _merge_residual_uncertainty(unit, result, work_id, attempt_id)
    _update_unit_after_import(
        root,
        run,
        unit,
        result,
        observations,
        was_needs_revalidation=was_needs_revalidation,
        invalidated_second_review=invalidated_second_review,
        cache=cache,
    )
    replacements = {
        "work-units.jsonl": jsonl_bytes(units),
        "observations.jsonl": jsonl_bytes(observations),
        "validations.jsonl": jsonl_bytes(validations),
    }
    return transact(
        root,
        replacements,
        operation="import",
        actor=f"{work_id}/{attempt_id}",
        timestamp=utc_now(),
        expected_digest=expected,
    )


def import_audit(root: Path, attempt_id: str, expected: str) -> dict:
    root = ensure_review_root(root)
    recover(root)
    run = _load_v2_run(root)
    manifest_path = root / "assignments/FINAL-AUDIT" / f"{attempt_id}.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = parse_json_bytes(manifest_bytes, str(manifest_path))
    result_path = root / "agents/FINAL-AUDIT" / attempt_id / "result.json"
    result_bytes = result_path.read_bytes()
    result = parse_json_bytes(result_bytes, str(result_path))
    validations_path = result_path.with_name("validations.jsonl")
    local_validations = parse_jsonl_bytes(
        validations_path.read_bytes(), str(validations_path)
    )
    if not isinstance(manifest, dict) or not isinstance(result, dict):
        raise ReviewToolError("final-auditor manifest and result must be objects")
    level = run_security_level(run)
    if result.get("attemptManifestHash") != digest_bytes(manifest_bytes):
        raise ReviewToolError("final-auditor attempt manifest identity mismatch")
    if result.get("reviewerExecutionId") != manifest.get("reviewerExecutionId"):
        raise ReviewToolError("final-auditor reviewer execution identity mismatch")
    if result.get("reviewerExecutionId") in manifest.get("independentFromReviewerExecutionIds", []):
        raise ReviewToolError("final auditor is not independent")
    specialist_executions = {
        attempt.get("reviewerExecutionId")
        for unit in load_jsonl(root / "work-units.jsonl")
        for attempt in unit.get("reviewAttempts", [])
        if isinstance(attempt, dict)
    }
    if result.get("reviewerExecutionId") in specialist_executions:
        raise ReviewToolError(
            "final-auditor reviewerExecutionId is already owned by a specialist attempt"
        )
    for field in ("baselineContentSetHash", "finalWorkUnitSetHash", "mechanicalAuditHash", "reportManifestHash"):
        if field in manifest and result.get(field) != manifest.get(field):
            raise ReviewToolError(f"final-auditor {field} mismatch")
    if "deterministicSample" in manifest and result.get("sampledUnits") != manifest.get("deterministicSample"):
        raise ReviewToolError("final-auditor sampled scope does not match its immutable assignment")
    if result.get("status") != "complete":
        raise ReviewToolError("only a complete final-auditor result can be imported")
    if result.get("specEpoch") != run.get("specEpoch"):
        raise ReviewToolError("final-auditor result uses the wrong specEpoch")
    if manifest.get("securityLevel") != level or result.get("securityLevel") != level:
        raise ReviewToolError("final-auditor securityLevel mismatch")
    if manifest.get("permittedValidationClasses") != permitted_validation_classes(level):
        raise ReviewToolError("final-auditor validation classes do not match security level")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")
    token = attempt_token(attempt_id)
    candidate_map = {}
    audit_candidates = result.get("candidates", [])
    imported_candidates = []
    for candidate in audit_candidates:
        local = candidate.get("localId")
        if not re.fullmatch(rf"CAND-{token}-\d{{3}}", str(local)):
            raise ReviewToolError(f"invalid final-auditor candidate identifier: {local}")
        canonical = _allocate(observations, "id", "OBS", 6)
        candidate_map[local] = canonical
        imported = _candidate_observation(
            candidate,
            identifier=canonical,
            source_work_units=candidate.get("sourceWorkUnits", []),
            source_attempt=f"FINAL-AUDIT/{attempt_id}",
            default_title="Audit observation",
            default_category="audit",
        )
        observations.append(imported)
        imported_candidates.append(imported)
    for objection in result.get("objections", []):
        local = objection.get("localId")
        if not re.fullmatch(rf"AAOB-{token}-\d{{3}}", str(local)):
            raise ReviewToolError(f"invalid local audit objection identifier: {local}")
        refs = objection.get("candidateRefs", [])
        if any(ref not in candidate_map for ref in refs):
            raise ReviewToolError(f"audit objection references unknown candidate: {local}")
        objections.append({"id": _allocate(objections, "id", "AOB", 6), "sourceAttempt": f"FINAL-AUDIT/{attempt_id}", "sourceLocalId": local, "affectedPaths": objection.get("affectedPaths", []), "workUnits": objection.get("workUnits", []), "materiality": objection.get("materiality"), "evidence": objection.get("evidence", []), "requiredResolution": objection.get("requiredResolution", ""), "disposition": "open", "resolutionEvidence": [], "candidateRefs": [candidate_map[ref] for ref in refs], "createdAt": utc_now(), "updatedAt": utc_now()})
    validation_map = {}
    for row in local_validations:
        local = row.get("localId")
        if not re.fullmatch(rf"AVAL-{token}-\d{{3}}", str(local)) or local in validation_map:
            raise ReviewToolError(f"invalid or duplicate final-auditor validation identifier: {local}")
        unknown = set(row.get("supportsCandidates", [])) - set(candidate_map)
        if unknown:
            raise ReviewToolError(f"final-auditor validation references unknown candidates: {sorted(unknown)}")
        validation_class = row.get("validationClass")
        if not validation_class_allowed(level, str(validation_class)):
            raise ReviewToolError(
                f"validation class {validation_class!r} is not permitted at security level {level!r}"
            )
        canonical = _allocate(validations, "id", "VAL", 6)
        validation_map[local] = canonical
        validations.append({
            "id": canonical, "sourceAttempt": f"FINAL-AUDIT/{attempt_id}", "sourceLocalId": local,
            "workUnits": row.get("workUnits", []),
            "observationIds": [candidate_map[item] for item in row.get("supportsCandidates", [])],
            **{key: row.get(key) for key in ("command", "cwd", "environmentSummary", "startedAt", "endedAt", "exitStatus", "result", "limitations", "createdArtifacts")},
            "trackedTreeMutation": row.get("trackedTreeMutation"),
            "validationClass": validation_class,
            "securityLevel": level,
        })
    for candidate, imported in zip(audit_candidates, imported_candidates):
        refs = candidate.get("validationRefs", [])
        if any(ref not in validation_map for ref in refs):
            raise ReviewToolError(f"final-auditor candidate references unknown validation: {candidate.get('localId')}")
        imported["validationRefs"] = [validation_map[ref] for ref in refs]
    run["finalAudit"] = {"attemptId": attempt_id, "reviewerExecutionId": result["reviewerExecutionId"], "resultHash": digest_bytes(result_bytes), "status": "imported", "sampledUnits": result.get("sampledUnits", [])}
    replacements = {"run.json": canonical_bytes(run), "observations.jsonl": jsonl_bytes(observations), "validations.jsonl": jsonl_bytes(validations), "audit-objections.jsonl": jsonl_bytes(objections)}
    return transact(root, replacements, operation="import_audit", actor=f"FINAL-AUDIT/{attempt_id}", timestamp=utc_now(), expected_digest=expected)
