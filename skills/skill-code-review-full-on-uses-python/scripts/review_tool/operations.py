"""Initialization, mutation, imports, reports, and audit operations."""

from __future__ import annotations

import json
import math
import random
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checks import check_review, require_valid
from .errors import ReviewToolError
from .io import (
    CANONICAL_FILES, atomic_write, canonical_bytes, digest_bytes, ensure_review_root,
    jsonl_bytes, load_json, load_jsonl, safe_child, state_digest,
)
from .references import extract_reference
from .security import (
    SECURITY_LEVELS,
    has_declared_security_profile,
    permitted_validation_classes,
    security_level as run_security_level,
    validation_class_allowed,
)
from .transactions import recover, transact


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def initialize(
    review_dir: Path,
    contract: Path,
    reference_pack: Path,
    runtime: str,
    *,
    security_level: str = "off",
    security_source: str = "default",
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
        existing = load_json(root.resolve() / "run.json")
        if security_source == "user" and security_level != run_security_level(existing):
            raise ReviewToolError(
                "existing review has security level "
                f"{run_security_level(existing)!r}; start a new review to change it"
            )
        return {"reviewDirectory": str(root.resolve()), "idempotent": True, "stateDigest": state_digest(root.resolve())}
    if root.exists() and any(root.iterdir()):
        raise ReviewToolError(f"refusing to initialize non-empty unrelated directory: {root}")
    root = ensure_review_root(root, create=True)
    for directory in ("assignments", "agents", "baseline", "tooling/reference/source", "tooling/transactions"):
        safe_child(root, directory).mkdir(parents=True, exist_ok=True)
    contract_bytes = contract.read_bytes()
    pack_bytes = reference_pack.read_bytes()
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
        })
    reference_manifest = {
        "reviewSpecVersion": 1,
        "specEpoch": "SPEC-0001",
        "sources": [
            {"path": "source/contract.md", "sourcePath": str(contract), "byteSize": len(contract_bytes)},
            {"path": "source/reference-pack.md", "sourcePath": str(reference_pack), "byteSize": len(pack_bytes)},
        ],
        "derived": derived,
    }
    atomic_write(root / "tooling/reference/manifest.json", canonical_bytes(reference_manifest))
    now = utc_now()
    run = {
        "schemaVersion": 1,
        "reviewSpecVersion": 1,
        "specEpoch": "SPEC-0001",
        "specification": {
            "initializedAt": now,
            "contractSource": str(contract),
            "contractPreserved": "tooling/reference/source/contract.md",
            "referencePackSource": str(reference_pack),
            "referencePackPreserved": "tooling/reference/source/reference-pack.md",
        },
        "specMigrations": [],
        "repositoryIdentity": "unrecorded",
        "reviewDirectory": str(root),
        "status": "active" if runtime != "none" else "paused",
        "verdict": None,
        "runtimeCapability": runtime,
        "capabilitySource": "harness_declared" if runtime != "none" else "absent_default_none",
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


def apply_mutation(root: Path, expected: str, changes_path: Path | None, migrate: tuple[Path, Path, list[str], list[int]] | None) -> dict:
    root = ensure_review_root(root)
    recover(root)
    replacements: dict[str, bytes] = {}
    if changes_path:
        changes = load_json(changes_path)
        if not isinstance(changes, dict) or not changes:
            raise ReviewToolError("changes file must contain a non-empty object of canonical replacements")
        allowed = set(CANONICAL_FILES) | {"assignments"}
        for relative, value in changes.items():
            if relative.startswith("assignments/"):
                replacements[relative] = canonical_bytes(value) if not isinstance(value, str) else value.encode()
            elif relative.endswith(".jsonl"):
                if not isinstance(value, list):
                    raise ReviewToolError(f"{relative} replacement must be a JSON array")
                replacements[relative] = jsonl_bytes(value)
            elif relative.endswith(".json"):
                replacements[relative] = canonical_bytes(value)
            elif relative == "architecture.md" and isinstance(value, str):
                replacements[relative] = value.encode()
            else:
                raise ReviewToolError(f"unauthorized mutation target: {relative}")
    if migrate:
        contract, pack, sections, angles = migrate
        if not contract.is_file() or not pack.is_file():
            raise ReviewToolError("specification migration sources must be readable files")
        run = load_json(root / "run.json")
        next_number = int(run["specEpoch"].split("-")[1]) + 1
        epoch = f"SPEC-{next_number:04d}"
        migration_prefix = f"tooling/reference/migrations/{epoch}"
        contract_bytes = contract.read_bytes()
        pack_bytes = pack.read_bytes()
        if (root / migration_prefix).exists():
            raise ReviewToolError(f"specification migration epoch already exists: {epoch}")
        replacements[f"{migration_prefix}/contract.md"] = contract_bytes
        replacements[f"{migration_prefix}/reference-pack.md"] = pack_bytes
        derived = []
        for extract in extract_reference(pack_bytes):
            replacements[f"tooling/reference/{extract.filename}"] = extract.data
            derived.append({
                "path": extract.filename, "sourceSection": extract.section,
                "sourceByteStart": extract.start, "sourceByteEnd": extract.end,
                "byteSize": len(extract.data),
            })
        install_manifest = {
            "reviewSpecVersion": 1, "specEpoch": epoch,
            "sources": [
                {"path": f"migrations/{epoch}/contract.md", "sourcePath": str(contract), "byteSize": len(contract_bytes)},
                {"path": f"migrations/{epoch}/reference-pack.md", "sourcePath": str(pack), "byteSize": len(pack_bytes)},
            ],
            "derived": derived,
        }
        replacements["tooling/reference/manifest.json"] = canonical_bytes(install_manifest)
        run["specMigrations"].append({
            "id": f"SPEC-MIGRATION-{next_number - 1:04d}", "fromSpecEpoch": run["specEpoch"],
            "toSpecEpoch": epoch, "changedSections": sections, "affectedAngles": angles,
            "wholeUnitRevalidation": not angles, "contractPreserved": f"{migration_prefix}/contract.md",
            "referencePackPreserved": f"{migration_prefix}/reference-pack.md", "recordedAt": utc_now(),
        })
        run["specEpoch"] = epoch
        run["updatedAt"] = utc_now()
        units = load_jsonl(root / "work-units.jsonl")
        for unit in units:
            unit["specEpoch"] = epoch
            for number, disposition in unit.get("angles", {}).items():
                if not angles or int(number) in angles:
                    if disposition.get("status") == "excluded_by_profile":
                        disposition["specEpoch"] = epoch
                        continue
                    if disposition.get("status") in {"reviewed", "not_applicable"}:
                        disposition["status"] = "needs_revalidation"
                    disposition["specEpoch"] = None
                    unit["status"] = "needs_revalidation"
                elif disposition.get("status") in {"reviewed", "not_applicable", "excluded_by_profile"}:
                    disposition["specEpoch"] = epoch
        replacements["run.json"] = canonical_bytes(run)
        replacements["work-units.jsonl"] = jsonl_bytes(units)
    if not replacements:
        raise ReviewToolError("mutate requires --changes or --migrate-spec")

    def validator(_: Path, proposed: dict[str, bytes]) -> None:
        # Validate lifecycle transitions before the commit marker. Full
        # partition checks may intentionally remain incomplete while baseline
        # and work-unit construction are in progress.
        if "run.json" in proposed:
            new = json.loads(proposed["run.json"])
            old = load_json(root / "run.json")
            legal = {
                "active": {"active", "paused", "concluded", "superseded"},
                "paused": {"paused", "active", "concluded", "superseded"},
                "concluded": {"concluded"}, "superseded": {"superseded"},
            }
            if new.get("status") not in legal.get(old.get("status"), set()):
                raise ReviewToolError(f"invalid status transition: {old.get('status')} -> {new.get('status')}")
            if new.get("securityProfile") != old.get("securityProfile"):
                raise ReviewToolError("securityProfile is immutable; start a new review to change it")
        if "work-units.jsonl" in proposed:
            old_units = {item.get("id"): item for item in load_jsonl(root / "work-units.jsonl")}
            new_units = {item.get("id"): item for item in [json.loads(line) for line in proposed["work-units.jsonl"].splitlines() if line]}
            work_legal = {
                "pending": {"pending", "assigned", "blocked"},
                "assigned": {"assigned", "partial", "complete", "blocked", "needs_revalidation"},
                "partial": {"partial", "assigned", "blocked", "needs_revalidation"},
                "complete": {"complete", "needs_revalidation"},
                "blocked": {"blocked", "pending", "assigned"},
                "needs_revalidation": {"needs_revalidation", "assigned", "blocked"},
            }
            angle_legal = {
                "pending": {"pending", "reviewed", "not_applicable", "excluded_by_profile", "blocked"},
                "reviewed": {"reviewed", "needs_revalidation"},
                "not_applicable": {"not_applicable", "needs_revalidation"},
                "excluded_by_profile": {"excluded_by_profile", "needs_revalidation"},
                "blocked": {"blocked", "pending"},
                "needs_revalidation": {"needs_revalidation", "reviewed", "not_applicable", "excluded_by_profile", "blocked"},
            }
            for identifier, old in old_units.items():
                if identifier not in new_units:
                    raise ReviewToolError(f"work unit deletion is not a legal transition: {identifier}")
                new = new_units[identifier]
                if new.get("status") not in work_legal.get(old.get("status"), set()):
                    raise ReviewToolError(f"invalid work-unit status transition for {identifier}: {old.get('status')} -> {new.get('status')}")
                if new.get("securityLevel") != old.get("securityLevel"):
                    raise ReviewToolError(f"work-unit securityLevel is immutable: {identifier}")
                for number, old_angle in old.get("angles", {}).items():
                    if number not in new.get("angles", {}):
                        raise ReviewToolError(f"angle disposition removed from {identifier}: {number}")
                    new_status = new["angles"][number].get("status")
                    if new_status not in angle_legal.get(old_angle.get("status"), set()):
                        raise ReviewToolError(f"invalid angle transition for {identifier}/{number}: {old_angle.get('status')} -> {new_status}")
        if "observations.jsonl" in proposed:
            old_rows = {item.get("id"): item for item in load_jsonl(root / "observations.jsonl")}
            new_rows = {item.get("id"): item for item in [json.loads(line) for line in proposed["observations.jsonl"].splitlines() if line]}
            observation_legal = {
                "open": {"open", "validated", "rejected", "duplicate", "unresolved", "deferred_by_profile"},
                "unresolved": {"unresolved", "open", "validated", "rejected", "duplicate", "deferred_by_profile"},
                "validated": {"validated", "withdrawn"},
                "rejected": {"rejected"}, "duplicate": {"duplicate"}, "withdrawn": {"withdrawn"},
                "deferred_by_profile": {"deferred_by_profile"},
            }
            for identifier, old in old_rows.items():
                if identifier not in new_rows:
                    raise ReviewToolError(f"observation deletion is not a legal transition: {identifier}")
                new_status = new_rows[identifier].get("disposition")
                if new_status not in observation_legal.get(old.get("disposition"), set()):
                    raise ReviewToolError(f"invalid observation transition for {identifier}: {old.get('disposition')} -> {new_status}")
    return transact(root, replacements, operation="mutate", actor="orchestrator", timestamp=utc_now(), expected_digest=expected, validator=validator)


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


def import_specialist(root: Path, work_id: str, attempt_id: str, expected: str) -> dict:
    root = ensure_review_root(root)
    attempt_dir = root / "agents" / work_id / attempt_id
    result_path = attempt_dir / "result.json"
    validations_path = attempt_dir / "validations.jsonl"
    result = load_json(result_path)
    local_validations = load_jsonl(validations_path)
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    unit = next((item for item in units if item.get("id") == work_id), None)
    if not unit:
        raise ReviewToolError(f"unknown work unit: {work_id}")
    attempt = next((item for item in unit.get("reviewAttempts", []) if item.get("attemptId") == attempt_id), None)
    if not attempt:
        raise ReviewToolError(f"unknown attempt: {work_id}/{attempt_id}")
    manifest_path = safe_child(root, attempt["manifest"])
    manifest = load_json(manifest_path)
    run = load_json(root / "run.json")
    level = run_security_level(run)
    checks = {
        "workId": work_id, "attemptId": attempt_id,
        "reviewerExecutionId": attempt.get("reviewerExecutionId"),
        "packetType": attempt.get("packetType"),
        "attemptManifestHash": attempt.get("manifestHash"),
        "unitManifestHash": attempt.get("unitManifestHash"),
        "specEpoch": run["specEpoch"],
    }
    if has_declared_security_profile(run):
        checks["securityLevel"] = level
        if manifest.get("securityLevel") != level:
            raise ReviewToolError("attempt manifest securityLevel mismatch")
        if manifest.get("permittedValidationClasses") != permitted_validation_classes(level):
            raise ReviewToolError("attempt manifest validation classes do not match security level")
    for field, expected_value in checks.items():
        if result.get(field) != expected_value:
            raise ReviewToolError(f"specialist result {field} mismatch")
    if attempt.get("manifestHash") != digest_bytes(manifest_path.read_bytes()):
        raise ReviewToolError("attempt manifest identity mismatch")
    assigned_angles = {str(number) for number in manifest.get("assignedScope", {}).get("angles", [])}
    result_angles = set(result.get("angleDispositions", {}))
    if not result_angles <= assigned_angles:
        raise ReviewToolError(
            f"specialist result includes unassigned angles: {sorted(result_angles - assigned_angles)}"
        )
    if result.get("status") == "complete" and result.get("packetType") == "primary_semantic":
        if result_angles != assigned_angles:
            raise ReviewToolError("complete primary result does not disposition every assigned angle")
    token = f"A{int(attempt_id.split('-')[1])}"
    local_candidates = result.get("candidates", [])
    candidate_map: dict[str, str] = {}
    for candidate in local_candidates:
        local = candidate.get("localId")
        if not re.fullmatch(rf"CAND-{token}-\d{{3}}", str(local)) or local in candidate_map:
            raise ReviewToolError(f"invalid or duplicate local candidate identifier: {local}")
        candidate_map[local] = _allocate(observations, "id", "OBS", 6)
        observations.append(_candidate_observation(
            candidate,
            identifier=candidate_map[local],
            source_work_units=[work_id],
            source_attempt=f"{work_id}/{attempt_id}",
            default_title="Untitled observation",
            default_category="unspecified",
        ))
    validation_map: dict[str, str] = {}
    for row in local_validations:
        local = row.get("localId")
        if not re.fullmatch(rf"AVAL-{token}-\d{{3}}", str(local)) or local in validation_map:
            raise ReviewToolError(f"invalid or duplicate local validation identifier: {local}")
        unknown = set(row.get("supportsCandidates", [])) - set(candidate_map)
        if unknown:
            raise ReviewToolError(f"validation references unknown candidates: {sorted(unknown)}")
        validation_class = row.get("validationClass")
        if has_declared_security_profile(run):
            if not validation_class_allowed(level, str(validation_class)):
                raise ReviewToolError(
                    f"validation class {validation_class!r} is not permitted at security level {level!r}"
                )
        elif validation_class is None:
            validation_class = "ordinary"
        canonical = _allocate(validations, "id", "VAL", 6)
        validation_map[local] = canonical
        validations.append({
            "id": canonical, "sourceAttempt": f"{work_id}/{attempt_id}", "sourceLocalId": local,
            "workUnits": [work_id], "observationIds": [candidate_map[item] for item in row.get("supportsCandidates", [])],
            **{key: row.get(key) for key in ("command", "cwd", "environmentSummary", "startedAt", "endedAt", "exitStatus", "result", "limitations", "createdArtifacts")},
            "trackedTreeMutation": row.get("trackedTreeMutation"),
            "validationClass": validation_class,
            "securityLevel": level,
        })
    for candidate, imported in zip(local_candidates, observations[-len(local_candidates):] if local_candidates else []):
        refs = candidate.get("validationRefs", [])
        if any(ref not in validation_map for ref in refs):
            raise ReviewToolError(f"candidate references unknown local validation: {candidate.get('localId')}")
        imported["validationRefs"] = [validation_map[ref] for ref in refs]
    attempt["status"] = result.get("status")
    attempt["resultHash"] = digest_bytes(result_path.read_bytes())
    attempt["importDisposition"] = "imported"
    for number, disposition in result.get("angleDispositions", {}).items():
        if number not in unit.get("angles", {}):
            raise ReviewToolError(f"result includes unassigned angle: {number}")
        evidence = []
        for item in disposition.get("evidence", []):
            evidence.append({"sourceAttempt": f"{work_id}/{attempt_id}", **item})
        if result.get("packetType") == "primary_semantic":
            unit["angles"][number] = {"status": disposition.get("status"), "evidence": evidence, "specEpoch": result["specEpoch"]}
    if result.get("packetType") == "independent_second_review":
        requirement_id = manifest.get("secondReviewRequirementId")
        requirement = next((item for item in unit.get("requiredSecondReviews", []) if item.get("id") == requirement_id), None)
        if requirement is None:
            raise ReviewToolError("second-review attempt names no current requirement")
        second_results = result.get("secondReviewResults", [])
        if len(second_results) != 1:
            raise ReviewToolError("second-review result must contain exactly one structured completion")
        second = second_results[0]
        if second.get("requirementId") != requirement_id or second.get("required") != requirement:
            raise ReviewToolError("second-review result does not match the assigned requirement")
        covered = second.get("scopeCovered")
        if covered != {"kind": "whole_unit"} and covered != requirement.get("scope"):
            raise ReviewToolError("second-review scope does not cover the requirement")
        independent_ids = manifest.get("independentFromAttemptIds", [])
        contributing_reviewers = {
            item.get("reviewerExecutionId") for item in unit.get("reviewAttempts", [])
            if item.get("attemptId") in independent_ids
        }
        if result.get("reviewerExecutionId") in contributing_reviewers:
            raise ReviewToolError("second reviewer is not independent of primary evidence contributors")
        candidate_refs = second.get("candidateRefs", [])
        if any(ref not in candidate_map for ref in candidate_refs):
            raise ReviewToolError("second-review completion references an unknown candidate")
        unit.setdefault("completedSecondReviews", []).append({
            "requirementId": requirement_id, "required": requirement,
            "attempt": f"{work_id}/{attempt_id}", "attemptManifestHash": attempt["manifestHash"],
            "reviewerExecutionId": result["reviewerExecutionId"],
            "independentFromAttemptIds": independent_ids,
            "primaryEvidenceSetHash": manifest.get("primaryEvidenceSetHash"),
            "scopeCovered": covered, "evidence": second.get("evidence", []),
            "conclusion": second.get("conclusion"),
            "observations": [candidate_map[ref] for ref in candidate_refs],
            "specEpoch": result["specEpoch"],
        })
    unit["residualUncertainty"] = result.get("residualUncertainty", [])
    completed_requirements = {item.get("requirementId") for item in unit.get("completedSecondReviews", [])}
    requirements_satisfied = all(item.get("id") in completed_requirements for item in unit.get("requiredSecondReviews", []))
    all_angles_complete = all(item.get("status") in {"reviewed", "not_applicable", "excluded_by_profile"} for item in unit["angles"].values())
    unit["status"] = "complete" if result.get("status") == "complete" and all_angles_complete and requirements_satisfied else ("partial" if result.get("packetType") == "independent_second_review" else result.get("status"))
    unit["updatedAt"] = utc_now()
    replacements = {"work-units.jsonl": jsonl_bytes(units), "observations.jsonl": jsonl_bytes(observations), "validations.jsonl": jsonl_bytes(validations)}
    return transact(root, replacements, operation="import", actor=f"{work_id}/{attempt_id}", timestamp=utc_now(), expected_digest=expected)


def import_audit(root: Path, attempt_id: str, expected: str) -> dict:
    root = ensure_review_root(root)
    manifest_path = root / "assignments/FINAL-AUDIT" / f"{attempt_id}.json"
    manifest = load_json(manifest_path)
    result_path = root / "agents/FINAL-AUDIT" / attempt_id / "result.json"
    result = load_json(result_path)
    local_validations = load_jsonl(result_path.with_name("validations.jsonl"))
    run = load_json(root / "run.json")
    level = run_security_level(run)
    if result.get("attemptManifestHash") != digest_bytes(manifest_path.read_bytes()):
        raise ReviewToolError("final-auditor attempt manifest identity mismatch")
    if result.get("reviewerExecutionId") != manifest.get("reviewerExecutionId"):
        raise ReviewToolError("final-auditor reviewer execution identity mismatch")
    if result.get("reviewerExecutionId") in manifest.get("independentFromReviewerExecutionIds", []):
        raise ReviewToolError("final auditor is not independent")
    for field in ("baselineContentSetHash", "finalWorkUnitSetHash", "mechanicalAuditHash", "reportManifestHash"):
        if field in manifest and result.get(field) != manifest.get(field):
            raise ReviewToolError(f"final-auditor {field} mismatch")
    if "deterministicSample" in manifest and result.get("sampledUnits") != manifest.get("deterministicSample"):
        raise ReviewToolError("final-auditor sampled scope does not match its immutable assignment")
    if result.get("status") != "complete":
        raise ReviewToolError("only a complete final-auditor result can be imported")
    if result.get("specEpoch") != run.get("specEpoch"):
        raise ReviewToolError("final-auditor result uses the wrong specEpoch")
    if has_declared_security_profile(run):
        if manifest.get("securityLevel") != level or result.get("securityLevel") != level:
            raise ReviewToolError("final-auditor securityLevel mismatch")
        if manifest.get("permittedValidationClasses") != permitted_validation_classes(level):
            raise ReviewToolError("final-auditor validation classes do not match security level")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")
    token = f"A{int(attempt_id.split('-')[1])}"
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
        if has_declared_security_profile(run):
            if not validation_class_allowed(level, str(validation_class)):
                raise ReviewToolError(
                    f"validation class {validation_class!r} is not permitted at security level {level!r}"
                )
        elif validation_class is None:
            validation_class = "ordinary"
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
    run["finalAudit"] = {"attemptId": attempt_id, "reviewerExecutionId": result["reviewerExecutionId"], "resultHash": digest_bytes(result_path.read_bytes()), "status": "imported", "sampledUnits": result.get("sampledUnits", [])}
    replacements = {"run.json": canonical_bytes(run), "observations.jsonl": jsonl_bytes(observations), "validations.jsonl": jsonl_bytes(validations), "audit-objections.jsonl": jsonl_bytes(objections)}
    return transact(root, replacements, operation="import_audit", actor=f"FINAL-AUDIT/{attempt_id}", timestamp=utc_now(), expected_digest=expected)


GENERATED = [
    "README.md", "coverage-ledger.md", "findings-index.md", "findings/P0.md", "findings/P1.md",
    "findings/P2.md", "findings/P3.md", "findings/P4.md", "findings/withdrawn.md",
    "rejected-candidates.md", "nits.md", "suggestions.md", "questions.md", "test-gaps.md",
    "documentation.md", "security-deferrals.md", "validation-log.md", "audit-report.md",
]


def _inline_code(value: str) -> str:
    runs = re.findall(r"`+", value)
    fence = "`" * (max((len(run) for run in runs), default=0) + 1)
    padding = " " if value.startswith(("`", " ")) or value.endswith(("`", " ")) else ""
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


def _observation_view(title: str, rows: list[dict]) -> bytes:
    lines = [f"# {title}", ""]
    if not rows:
        lines.extend(["No records in this category.", ""])
    for row in rows:
        label = row.get("findingId") or row.get("id")
        assigned_severity = row.get("severity")
        severity = assigned_severity or "not assigned"
        anchor = re.sub(r"[^a-z0-9-]", "-", str(label).lower()).strip("-")
        heading = f"## {label} — {row.get('title', 'Untitled')}"
        if assigned_severity:
            heading = f"## {label} — [{assigned_severity}] {row.get('title', 'Untitled')}"
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
        elif severity in {"P0", "P1", "P2", "P3", "P4"}:
            target = f"findings/{severity}.md#{anchor}"
        else:
            target = None
        label = f"{finding} — [{severity}] {row.get('title', 'Untitled')}"
        linked = f"[{label}]({target})" if target else label
        lines.append(f"- {linked} — {_format_locations(row)}")
    lines.append("")
    return ("\n".join(lines)).encode()


def generate(root: Path) -> dict:
    root = ensure_review_root(root)
    recover(root)
    run = load_json(root / "run.json")
    paths = load_jsonl(root / "paths.jsonl")
    units = load_jsonl(root / "work-units.jsonl")
    observations = load_jsonl(root / "observations.jsonl")
    validations = load_jsonl(root / "validations.jsonl")
    objections = load_jsonl(root / "audit-objections.jsonl")
    outputs: dict[str, bytes] = {}
    level = run_security_level(run)
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
    manifest = {"schemaVersion": 1, "generatedAt": utc_now(), "canonicalStateDigest": state_digest(root), "outputs": {name: digest_bytes(data) for name, data in sorted(outputs.items())}}
    atomic_write(root / "report-manifest.json", canonical_bytes(manifest))
    return {"generated": len(outputs), "canonicalStateDigest": manifest["canonicalStateDigest"]}


def deterministic_sample(units: list[dict], baseline_identity: str, work_identity: str, cap: int = 200) -> list[str]:
    eligible = sorted(unit["id"] for unit in units if unit.get("riskTier") != "A" and unit.get("status") == "complete")
    count = min(len(eligible), cap, max(25, math.ceil(0.01 * len(eligible)))) if eligible else 0
    seed = int(digest_bytes(f"{baseline_identity}:{work_identity}".encode()), 16)
    randomizer = random.Random(seed)
    return sorted(randomizer.sample(eligible, count))


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
    level = run_security_level(run)
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
        if unfinished: output["issues"].append(f"unfinished work units: {len(unfinished)}")
        if open_observations: output["issues"].append(f"open observations: {len(open_observations)}")
        if open_material_objections: output["issues"].append(f"open material audit objections: {len(open_material_objections)}")
        if not phase_ok: output["issues"].append("required review phases are incomplete")
        if not final_ok: output["issues"].append("independent final audit is not imported")
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
