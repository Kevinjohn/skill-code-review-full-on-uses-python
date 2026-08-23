from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import CONTRACT, PACK, clean_unit, new_review
from review_tool.checks import check_review
from review_tool.errors import ReviewToolError
from review_tool.cli import build_parser
from review_tool.io import canonical_bytes, digest_bytes, jsonl_bytes, load_json, load_jsonl, normalize_relative, safe_child, state_digest
from review_tool.operations import (
    _format_location,
    _observation_view,
    apply_mutation,
    generate,
    import_specialist,
    initialize,
)
from review_tool.references import extract_reference, mandatory_block
from review_tool.security import permitted_validation_classes, security_level, validation_class_allowed
from review_tool.identifiers import attempt_token
from review_tool.transactions import recover, simulate_transaction, state_lock


class CoreTests(unittest.TestCase):
    def test_json_and_jsonl_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.json").write_text('{"a":1}')
            (root / "many.jsonl").write_text('{"a":1}\n{"b":2}\n')
            self.assertEqual(load_json(root / "one.json"), {"a": 1})
            self.assertEqual(load_jsonl(root / "many.jsonl"), [{"a": 1}, {"b": 2}])
            (root / "many.jsonl").write_text('{bad}\n')
            with self.assertRaisesRegex(ReviewToolError, "invalid JSONL"):
                load_jsonl(root / "many.jsonl")

    def test_exact_extraction_and_mandatory_block(self):
        source = PACK.read_bytes()
        extracts = {item.filename: item for item in extract_reference(source)}
        self.assertEqual(len([name for name in extracts if name.startswith("angle-") and name != "angle-index.md"]), 10)
        self.assertTrue(extracts["angle-01.md"].data.startswith(b"### Angle 1"))
        self.assertTrue(extracts["security-levels.md"].data.startswith(b"## R3A. Security levels"))
        self.assertTrue(
            extracts["defensive-assurance.md"].data.startswith(
                b"## R3B. Defensive assurance taxonomy"
            )
        )
        self.assertIn(b"Statement and data separation", extracts["defensive-assurance.md"].data)
        start, end = mandatory_block(source)
        self.assertTrue(source[start:end].startswith(b"> For a primary packet, review the entire assigned manifest."))
        self.assertNotIn(b"BEGIN MANDATORY", source[start:end])
        security_start = source.index(b"## R3A. Security levels")
        security_end = source.index(b"## R4. Mandatory specialist block")
        legacy_source = source[:security_start] + source[security_end:]
        with self.assertRaisesRegex(
            ReviewToolError, "required reference heading not found"
        ):
            extract_reference(legacy_source)

    def test_path_normalization_and_containment(self):
        self.assertEqual(normalize_relative("a/b.json"), "a/b.json")
        for unsafe in ("../a", "/tmp/a", "a/../b", "a\\b"):
            with self.assertRaises(ReviewToolError):
                normalize_relative(unsafe)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to(Path(temporary).parent)
            with self.assertRaisesRegex(ReviewToolError, "symlink traversal|escapes review directory"):
                safe_child(root, "link/escape")

    def test_state_digest_ignores_agent_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            before = state_digest(review)
            agent = review / "agents/WORK-0001/ATTEMPT-0001"
            agent.mkdir(parents=True)
            (agent / "result.json").write_text("{}")
            self.assertEqual(before, state_digest(review))

    def test_transaction_staging_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run = load_json(review / "run.json")
            run["checkpointReason"] = "recovered"
            staged = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=False)
            result = recover(review)
            self.assertEqual(result["quarantined"], 1)
            self.assertFalse(staged.exists())
            committed = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=True)
            result = recover(review)
            self.assertEqual(result["rolledForward"], 1)
            self.assertTrue((committed / "COMPLETE").exists())
            self.assertEqual(load_json(review / "run.json")["checkpointReason"], "recovered")

    def test_attempt_token_requires_exactly_four_digits(self):
        self.assertEqual(attempt_token("ATTEMPT-0001"), "A1")
        self.assertEqual(attempt_token("ATTEMPT-0012"), "A12")
        for malformed in ("ATTEMPT-001", "ATTEMPT-1", "ATTEMPT-00001"):
            with self.assertRaisesRegex(ReviewToolError, "exactly four digits"):
                attempt_token(malformed)

    def test_state_lock_serializes_writers(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            with state_lock(review):
                with self.assertRaisesRegex(ReviewToolError, "holds"):
                    recover(review)
            self.assertEqual(recover(review), {"rolledForward": 0, "quarantined": 0})

    def test_recovery_replays_committed_transactions_in_sequence_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run = load_json(review / "run.json")
            run["checkpointReason"] = "first"
            first = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=True)
            run["checkpointReason"] = "second"
            second = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=True)
            base = review / "tooling" / "transactions"
            event = load_json(second / "event.json")
            event["sequence"] = event["sequence"] + 1
            (second / "event.json").write_bytes(canonical_bytes(event))
            # Name the later-sequence transaction so it sorts FIRST by
            # directory name; ordered replay must still apply it last.
            os.replace(second, base / "TXN-AAA")
            os.replace(first, base / "TXN-ZZZ")
            result = recover(review)
            self.assertEqual(result["rolledForward"], 2)
            self.assertEqual(load_json(review / "run.json")["checkpointReason"], "second")

    def test_reinitialize_with_different_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = base / "review"
            initialize(review, CONTRACT, PACK)
            edited = base / "contract.md"
            edited.write_text(CONTRACT.read_text() + "\nEdited.\n")
            with self.assertRaisesRegex(ReviewToolError, "preserves a different contract"):
                initialize(review, edited, PACK)
            result = initialize(review, CONTRACT, PACK)
            self.assertTrue(result["idempotent"])

    def test_failed_initialization_leaves_no_partial_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            contract = base / "contract.md"
            pack = base / "pack.md"
            contract.write_text(
                CONTRACT.read_text().replace(
                    "Contract version: 2", "Contract version: 1"
                )
            )
            pack.write_bytes(PACK.read_bytes())
            review = base / "review"
            with self.assertRaisesRegex(ReviewToolError, "version mismatch"):
                initialize(review, contract, pack)
            self.assertFalse(review.exists())

    def test_manifest_history_is_append_only_and_chain_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = new_review(base)
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["manifestHistory"] = []
            changes = base / "delete-history.json"
            changes.write_bytes(
                canonical_bytes({"work-units.jsonl": units})
            )
            with self.assertRaisesRegex(
                ReviewToolError,
                "manifestHistory is append-only",
            ):
                apply_mutation(
                    review,
                    state_digest(review),
                    changes)
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            issues = check_review(review, check_generated=False)["issues"]
            self.assertTrue(
                any("manifestHistory must be a non-empty array" in issue for issue in issues),
                issues,
            )

    def test_reinit_without_flags_is_idempotent_for_existing_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = base / "review"
            initialize(
                review,
                CONTRACT,
                PACK,
            )
            args = build_parser().parse_args(
                [
                    "init",
                    "--review-dir",
                    str(review),
                    "--contract",
                    str(CONTRACT),
                    "--reference-pack",
                    str(PACK),
                ]
            )
            self.assertFalse(hasattr(args, "runtime_capability"))
            self.assertFalse(hasattr(args, "stable_reviewer_lineage"))
            result = initialize(
                review,
                CONTRACT,
                PACK,
            )
            self.assertTrue(result["idempotent"])

    def test_runtime_capability_is_always_none(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run = load_json(review / "run.json")
            self.assertEqual(run["runtimeCapability"], "none")
            self.assertEqual(run["capabilitySource"], "absent_default_none")
            self.assertEqual(run["status"], "paused")

    def test_generated_view_freshness(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            generate(review)
            self.assertTrue(check_review(review)["ok"])
            (review / "README.md").write_text("stale")
            self.assertTrue(any("generated output changed" in issue for issue in check_review(review)["issues"]))

    def test_location_rendering_handles_supported_shapes(self):
        self.assertEqual(
            _format_location({"path": "src/auth/token-store.ts", "startLine": 84, "endLine": 113}),
            "`src/auth/token-store.ts:84-113`",
        )
        self.assertEqual(
            _format_location({"path": "src/auth/token-store.ts", "startLine": 84, "endLine": 84}),
            "`src/auth/token-store.ts:84`",
        )
        self.assertEqual(_format_location({"path": "src/auth/token-store.ts"}), "`src/auth/token-store.ts`")
        self.assertEqual(_format_location(None), "not recorded")
        self.assertEqual(_format_location({"startLine": 84}), "not recorded")

    def test_observation_view_renders_complete_finding_details(self):
        row = {
            "id": "OBS-000001",
            "findingId": "DBR-0001",
            "title": "Token writes are not atomic",
            "disposition": "validated",
            "category": "correctness",
            "severity": "P1",
            "materiality": "material",
            "materialityRationale": "Authentication can fail.",
            "confidence": "High",
            "primaryLocation": {"path": "src/auth/token-store.ts", "startLine": 84, "endLine": 113},
            "additionalLocations": [{"path": "src/auth/session.ts", "startLine": 22, "endLine": 22}],
            "affectedComponents": ["token store"],
            "affectedConfigurations": ["file-backed sessions"],
            "affectedDeployments": ["desktop"],
            "trigger": "The process exits between writes.",
            "expected": "The prior token remains readable.",
            "actual": "The token file is truncated.",
            "impact": "Users are signed out.",
            "likelihood": "Plausible during shutdown.",
            "blastRadius": "One local account.",
            "evidence": ["A direct reproduction failed."],
            "reachability": "Called by the normal login path.",
            "existingChecks": "The unit test uses an in-memory store.",
            "reproduction": "Interrupt the second write.",
            "recommendation": "Write and rename a temporary file.",
            "regressionTest": "Interrupt each persistence boundary.",
            "counterargument": "The operating system usually buffers the write.",
            "residualUncertainty": "Filesystem-specific rename behavior.",
        }
        report = _observation_view("P1 findings", [row]).decode()
        for heading in (
            "Category",
            "Materiality and rationale",
            "Affected components and configurations",
            "Trigger or failure sequence",
            "Expected / actual",
            "Impact, likelihood, and blast radius",
            "Evidence and reachability",
            "Existing checks and tests",
            "Smallest reproduction",
            "Remediation and regression test",
            "Counterargument",
            "Residual uncertainty",
        ):
            self.assertIn(f"**{heading}:**", report)
        self.assertIn("`src/auth/token-store.ts:84-113`", report)
        self.assertIn("`src/auth/session.ts:22`", report)
        self.assertIn("Components: token store; Configurations: file-backed sessions; Deployments: desktop", report)
        self.assertNotIn("{'path':", report)

    def test_observation_view_marks_missing_details_honestly(self):
        report = _observation_view(
            "Questions",
            [{"id": "OBS-000001", "title": "Legacy observation", "disposition": "unresolved"}],
        ).decode()
        self.assertIn("**Locations:** not recorded", report)
        self.assertIn("**Residual uncertainty:** not recorded", report)

    def test_generated_summary_links_to_complete_finding(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            observation = {
                "id": "OBS-000001",
                "findingId": "DBR-0001",
                "title": "Fixture finding",
                "disposition": "validated",
                "reportClass": "finding",
                "severity": "P1",
                "primaryLocation": {"path": "src/example.py", "startLine": 1, "endLine": 1},
            }
            (review / "observations.jsonl").write_text(json.dumps(observation) + "\n")
            generate(review)
            summary = (review / "README.md").read_text()
            index = (review / "findings-index.md").read_text()
            detail = (review / "findings/P1.md").read_text()
            self.assertIn("[P1](findings/P1.md): 1", summary)
            self.assertIn("[findings index](findings-index.md)", summary)
            self.assertIn("[DBR-0001 — [P1] Fixture finding](findings/P1.md#dbr-0001)", index)
            self.assertIn('<a id="dbr-0001"></a>', detail)

    def test_findings_index_links_withdrawn_finding_to_withdrawn_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            observation = {
                "id": "OBS-000001",
                "findingId": "DBR-0001",
                "title": "Withdrawn fixture",
                "disposition": "withdrawn",
                "reportClass": "finding",
                "severity": "P2",
                "withdrawal": {"reason": "Defeated by validation."},
            }
            (review / "observations.jsonl").write_text(json.dumps(observation) + "\n")
            generate(review)
            index = (review / "findings-index.md").read_text()
            withdrawn = (review / "findings/withdrawn.md").read_text()
            self.assertIn("(findings/withdrawn.md#dbr-0001)", index)
            self.assertIn('<a id="dbr-0001"></a>', withdrawn)

    def test_security_profile_defaults_and_report_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary) / "review"
            initialize(review, CONTRACT, PACK)
            run = load_json(review / "run.json")
            self.assertEqual(
                run["securityProfile"],
                {"level": "off", "source": "default", "externalTargets": False},
            )
            generate(review)
            report = (review / "README.md").read_text()
            self.assertIn("Security level: off", report)
            self.assertIn("Security assessment: NOT PERFORMED", report)
            self.assertIn("declared non-security scope", report)

    def test_security_validation_class_matrix(self):
        self.assertTrue(validation_class_allowed("off", "ordinary"))
        self.assertFalse(validation_class_allowed("off", "security_static"))
        self.assertFalse(validation_class_allowed("low", "security_static"))
        self.assertTrue(validation_class_allowed("medium", "security_static"))
        self.assertFalse(validation_class_allowed("medium", "security_dynamic_isolated"))
        self.assertTrue(validation_class_allowed("high", "security_dynamic_isolated"))
        self.assertEqual(permitted_validation_classes("off"), ["ordinary"])
        self.assertEqual(
            permitted_validation_classes("high"),
            ["ordinary", "security_static", "security_dynamic_isolated"],
        )
        self.assertEqual(security_level({}), "")

    def test_validation_import_enforces_security_level_end_to_end(self):
        cases = [
            ("off", "ordinary", True),
            ("off", "security_static", False),
            ("low", "ordinary", True),
            ("low", "security_static", False),
            ("medium", "security_static", True),
            ("medium", "security_dynamic_isolated", False),
            ("high", "security_dynamic_isolated", True),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for index, (level, validation_class, allowed) in enumerate(cases):
                with self.subTest(level=level, validation_class=validation_class):
                    review = new_review(base / str(index), level=level)
                    identities = clean_unit(review)
                    assigned = [
                        number
                        for number in range(1, 11)
                        if not (level == "off" and number == 5)
                    ]
                    evidence = [{
                        "scopeCovered": {"kind": "whole_unit"},
                        "locations": ["src/example.py:1"],
                        "claim": "Fixture evidence.",
                    }]
                    result = {
                        "workId": "WORK-0001",
                        "attemptId": "ATTEMPT-0001",
                        "reviewerExecutionId": "EXEC-PRIMARY",
                        "reviewerPrincipalId": "EXEC-PRIMARY",
                        "packetType": "primary_semantic",
                        "unitManifestHash": identities["unitHash"],
                        "attemptManifestHash": identities["attemptHash"],
                        "specEpoch": "SPEC-0001",
                        "securityLevel": level,
                        "status": "complete",
                        "inspected": {"paths": ["src/example.py"], "symbols": []},
                        "notInspected": {"paths": [], "symbols": []},
                        "angleDispositions": {
                            str(number): {"status": "reviewed", "evidence": evidence}
                            for number in assigned
                        },
                        "secondReviewResults": [],
                        "candidates": [],
                        "residualUncertainty": [],
                        "remainingScope": {"paths": [], "symbols": [], "angles": []},
                    }
                    attempt_dir = review / "agents/WORK-0001/ATTEMPT-0001"
                    attempt_dir.mkdir(parents=True)
                    (attempt_dir / "result.json").write_text(json.dumps(result))
                    validation = {
                        "localId": "AVAL-A1-001",
                        "validationClass": validation_class,
                        "command": "fixture validation",
                        "cwd": str(base),
                        "environmentSummary": "temporary fixture",
                        "startedAt": "2026-01-01T00:00:00Z",
                        "endedAt": "2026-01-01T00:00:00Z",
                        "exitStatus": 0,
                        "result": "passed",
                        "limitations": [],
                        "createdArtifacts": [],
                        "supportsCandidates": [],
                    }
                    (attempt_dir / "validations.jsonl").write_text(json.dumps(validation) + "\n")
                    if allowed:
                        import_specialist(
                            review,
                            "WORK-0001",
                            "ATTEMPT-0001",
                            state_digest(review),
                        )
                        imported = load_jsonl(review / "validations.jsonl")
                        self.assertEqual(imported[0]["validationClass"], validation_class)
                    else:
                        with self.assertRaisesRegex(ReviewToolError, "not permitted"):
                            import_specialist(
                                review,
                                "WORK-0001",
                                "ATTEMPT-0001",
                                state_digest(review),
                            )

    def test_each_security_level_accepts_a_matching_unit_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for level in ("off", "low", "medium", "high"):
                review = new_review(base / level, level=level)
                clean_unit(review)
                self.assertEqual(check_review(review, check_generated=False)["issues"], [])

    def test_final_audit_manifest_inherits_validation_classes(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            manifest_path = review / "assignments/FINAL-AUDIT/ATTEMPT-0001.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_bytes(canonical_bytes({
                "attemptId": "ATTEMPT-0001",
                "securityLevel": "off",
                "permittedValidationClasses": ["ordinary", "security_static"],
            }))
            issues = check_review(review, check_generated=False)["issues"]
            self.assertTrue(any("validation classes do not match" in issue for issue in issues))

    def test_off_profile_import_omits_security_angle(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            identities = clean_unit(review)
            attempt_dir = review / "agents/WORK-0001/ATTEMPT-0001"
            attempt_dir.mkdir(parents=True)
            evidence = [{
                "scopeCovered": {"kind": "whole_unit"},
                "locations": ["src/example.py:1"],
                "claim": "Fixture evidence.",
            }]
            assigned = [number for number in range(1, 11) if number != 5]
            result = {
                "workId": "WORK-0001",
                "attemptId": "ATTEMPT-0001",
                "reviewerExecutionId": "EXEC-PRIMARY",
                "reviewerPrincipalId": "EXEC-PRIMARY",
                "packetType": "primary_semantic",
                "unitManifestHash": identities["unitHash"],
                "attemptManifestHash": identities["attemptHash"],
                "specEpoch": "SPEC-0001",
                "securityLevel": "off",
                "status": "complete",
                "inspected": {"paths": ["src/example.py"], "symbols": []},
                "notInspected": {"paths": [], "symbols": []},
                "angleDispositions": {
                    str(number): {"status": "reviewed", "evidence": evidence}
                    for number in assigned + [5]
                },
                "secondReviewResults": [],
                "candidates": [],
                "residualUncertainty": [],
                "remainingScope": {"paths": [], "symbols": [], "angles": []},
            }
            (attempt_dir / "result.json").write_text(json.dumps(result))
            (attempt_dir / "validations.jsonl").write_text("")
            with self.assertRaisesRegex(ReviewToolError, "unassigned angles"):
                import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            result["angleDispositions"].pop("5")
            (attempt_dir / "result.json").write_text(json.dumps(result))
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "complete")
            self.assertEqual(unit["angles"]["5"]["status"], "excluded_by_profile")

if __name__ == "__main__":
    unittest.main()
