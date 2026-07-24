from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import clean_unit, new_review, rewrite_canonical
from tests.helpers import CONTRACT, PACK
from review_tool.checks import check_review
from review_tool.errors import ReviewToolError
from review_tool.io import canonical_bytes, digest_bytes, load_json, load_jsonl, state_digest
from review_tool.operations import apply_mutation, generate, initialize
from review_tool.transactions import simulate_transaction


class BrokenStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.review = new_review(Path(self.temporary.name))
        clean_unit(self.review)
        generate(self.review)

    def tearDown(self):
        self.temporary.cleanup()

    def assertIssue(self, text: str):
        issues = check_review(self.review)["issues"]
        self.assertTrue(any(text in issue for issue in issues), f"{text!r} not found in {issues}")

    def test_clean_equivalent_passes(self):
        self.assertEqual(check_review(self.review)["issues"], [])

    def test_duplicate_permanent_identifiers(self):
        row = {"id": "OBS-000001", "disposition": "open", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [row, dict(row)])
        self.assertIssue("duplicate permanent identifiers")

    def test_unhashable_permanent_identifier_is_reported(self):
        row = {"id": {"malformed": True}, "disposition": "open", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [row])
        self.assertIssue("invalid identifier")

    def test_unhashable_path_identifier_is_reported(self):
        paths = load_jsonl(self.review / "paths.jsonl")
        paths[0]["path"] = {"malformed": True}
        rewrite_canonical(self.review, "paths.jsonl", paths)
        self.assertIssue("invalid path identifier")

    def test_unhashable_second_review_requirement_id_is_reported(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["completedSecondReviews"] = [
            {"requirementId": {"malformed": True}}
        ]
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("requires a string requirementId")

    def test_invalid_status_transition(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["status"] = "teleported"
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("invalid status transition")

    def test_missing_primary_assignment(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["paths"] = []
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("expected 1")

    def test_multiple_primary_assignments(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        other = dict(units[0])
        other["id"] = "WORK-0002"
        units.append(other)
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("count is 2")

    def test_repository_content_identity_mismatch(self):
        paths = load_jsonl(self.review / "paths.jsonl")
        paths[0]["contentId"] = "changed-content"
        rewrite_canonical(self.review, "paths.jsonl", paths)
        self.assertIssue("repository-content or canonical-state identity mismatch")

    def test_stale_generated_views(self):
        run = load_json(self.review / "run.json")
        run["checkpointReason"] = "new mutation"
        changes = Path(self.temporary.name) / "changes.json"
        changes.write_bytes(canonical_bytes({"run.json": run}))
        apply_mutation(self.review, state_digest(self.review), changes)
        self.assertIssue("generated views are stale")

    def test_unreconciled_specialist_attempt(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["reviewAttempts"][0]["status"] = "complete"
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("unreconciled specialist attempt")

    def test_orphaned_validation_reference(self):
        observation = {"id": "OBS-000001", "disposition": "open", "validationRefs": ["VAL-000001"]}
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("orphaned validation reference")

    def _second_review(self, *, scope=None, reviewer="EXEC-SECOND", stale=False):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        unit["riskTier"] = "A"
        unit["criticalReasons"] = [{
            "code": "durability_recovery",
            "locations": ["src/example.py"],
            "invariant": "Fixture durability.",
            "materialConsequence": "Fixture data loss.",
            "whyTierBInsufficient": "Exercises Tier-A integrity checks.",
        }]
        unit["reviewAttempts"][0].update({
            "status": "complete",
            "importDisposition": "imported",
            "resultHash": "result-hash",
            "attemptEvidenceHash": "evidence-hash",
        })
        requirement = {"id": "SR-001", "angle": 3, "scope": {"kind": "whole_unit"}}
        unit["requiredSecondReviews"] = [requirement]
        unit["completedSecondReviews"] = [{
            "requirementId": "SR-001", "scopeCovered": scope or {"kind": "whole_unit"},
            "reviewerExecutionId": reviewer,
            "reviewerPrincipalId": reviewer,
            "independentFromAttemptIds": ["ATTEMPT-0001"],
            "specEpoch": "SPEC-0001", "stale": stale,
        }]
        rewrite_canonical(self.review, "work-units.jsonl", units)

    def test_invalid_whole_unit_second_review(self):
        self._second_review(scope={"kind": "items", "items": [{"type": "path", "value": "src/example.py"}]})
        self.assertIssue("invalid whole-unit")

    def test_stale_superseded_manifest(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["manifestHistory"].append({"path": "assignments/WORK-0001/MANIFEST-0002.json"})
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("stale superseded manifest")

    def test_late_primary_import_invalidates_second_review(self):
        self._second_review(stale=True)
        self.assertIssue("later intersecting primary import")

    def test_excluded_path_assigned(self):
        paths = load_jsonl(self.review / "paths.jsonl")
        paths[0]["exclusion"] = {"category": "explicit_out_of_scope", "rationale": "fixture", "boundaryEvidence": ["test"], "authorizedBy": "user:test"}
        rewrite_canonical(self.review, "paths.jsonl", paths)
        self.assertIssue("excluded path assigned")

    def test_pass_with_material_concern(self):
        run = load_json(self.review / "run.json")
        run["verdict"] = "PASS"
        rewrite_canonical(self.review, "run.json", run)
        observation = {"id": "OBS-000001", "disposition": "unresolved", "materiality": "material", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("terminal pass verdict")

    def test_pass_with_open_material_concern(self):
        run = load_json(self.review / "run.json")
        run["verdict"] = "PASS"
        rewrite_canonical(self.review, "run.json", run)
        observation = {"id": "OBS-000001", "disposition": "open", "materiality": "material", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("terminal pass verdict")

    def test_invalid_verdict_value_is_reported(self):
        run = load_json(self.review / "run.json")
        run["verdict"] = "Pass"
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("verdict is invalid")

    def test_missing_current_epoch_is_reported(self):
        run = load_json(self.review / "run.json")
        run["currentEpoch"] = None
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("currentEpoch is required")

    def test_free_text_event_operation_is_reported(self):
        events_path = self.review / "state-events.jsonl"
        rows = load_jsonl(events_path)
        tampered = dict(rows[-1])
        tampered["operation"] = "fixture_corruption"
        tampered.pop("eventHash", None)
        tampered["eventHash"] = digest_bytes(canonical_bytes(tampered))
        rows[-1] = tampered
        events_path.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        self.assertIssue("invalid operation")

    def test_recorded_spec_migration_is_rejected(self):
        run = load_json(self.review / "run.json")
        run["specMigrations"] = [{"id": "SPEC-MIGRATION-0001"}]
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("specMigrations must be an empty array")

    def test_wrong_specification_epoch(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["angles"]["1"] = {"status": "reviewed", "evidence": [{"claim": "x"}], "specEpoch": "SPEC-9999"}
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("wrong specEpoch")

    def test_security_angle_assigned_while_profile_is_off(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["angles"]["5"] = {"status": "pending", "evidence": [], "specEpoch": None}
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("angle 5 must be excluded")

    def test_dynamic_security_validation_rejected_while_profile_is_off(self):
        validation = {
            "id": "VAL-000001",
            "sourceAttempt": "WORK-0001/ATTEMPT-0001",
            "sourceLocalId": "AVAL-A1-001",
            "workUnits": ["WORK-0001"],
            "observationIds": [],
            "securityLevel": "off",
            "validationClass": "security_dynamic_isolated",
        }
        rewrite_canonical(self.review, "validations.jsonl", [validation])
        self.assertIssue("validation class is not permitted")

    def test_profile_deferral_requires_security_category(self):
        observation = {
            "id": "OBS-000001",
            "category": "correctness",
            "disposition": "deferred_by_profile",
            "validationRefs": [],
        }
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("invalid profile deferral")

    def test_security_profile_change_is_rejected(self):
        run = load_json(self.review / "run.json")
        run["securityProfile"]["level"] = "high"
        changes = Path(self.temporary.name) / "security-change.json"
        changes.write_bytes(canonical_bytes({"run.json": run}))
        with self.assertRaisesRegex(ReviewToolError, "securityProfile is immutable"):
            apply_mutation(self.review, state_digest(self.review), changes)

    def test_existing_assignment_file_is_immutable(self):
        manifest_path = self.review / "assignments/WORK-0001/ATTEMPT-0001.json"
        manifest = load_json(manifest_path)
        manifest["reviewerExecutionId"] = "REWRITTEN"
        changes = Path(self.temporary.name) / "changes.json"
        changes.write_bytes(canonical_bytes({
            "assignments/WORK-0001/ATTEMPT-0001.json": manifest
        }))
        with self.assertRaisesRegex(ReviewToolError, "immutable assignment"):
            apply_mutation(self.review, state_digest(self.review), changes)

    def test_existing_attempt_record_is_immutable(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["reviewAttempts"][0]["reviewerPrincipalId"] = "REWRITTEN"
        changes = Path(self.temporary.name) / "changes.json"
        changes.write_bytes(canonical_bytes({"work-units.jsonl": units}))
        with self.assertRaisesRegex(ReviewToolError, "sealed review attempt"):
            apply_mutation(self.review, state_digest(self.review), changes)

    def test_specialist_capabilities_are_immutable(self):
        run = load_json(self.review / "run.json")
        run["specialistCapabilities"]["stableReviewerLineage"] = True
        changes = Path(self.temporary.name) / "changes.json"
        changes.write_bytes(canonical_bytes({"run.json": run}))
        with self.assertRaisesRegex(ReviewToolError, "specialistCapabilities"):
            apply_mutation(self.review, state_digest(self.review), changes)

    def test_missing_review_spec_version_is_reported(self):
        run = load_json(self.review / "run.json")
        run.pop("reviewSpecVersion")
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("reviewSpecVersion is required")

    def test_malformed_review_spec_version_is_reported(self):
        run = load_json(self.review / "run.json")
        run["reviewSpecVersion"] = []
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("reviewSpecVersion must be an integer")

    def test_null_diagnostic_acknowledgements_is_reported(self):
        run = load_json(self.review / "run.json")
        run["diagnosticAcknowledgements"] = None
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("diagnosticAcknowledgements")

    def test_malformed_required_second_reviews_are_reported_without_crashing(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["requiredSecondReviews"] = ["not-an-object"]
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("malformed second-review requirement")

    def test_null_critical_reasons_are_reported_without_crashing(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["riskTier"] = "A"
        units[0]["criticalReasons"] = None
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("structured criticalReasons")

    def test_manifest_history_requires_a_hash_pin(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["manifestHistory"][0]["hash"] = None
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("manifest history hash pin is missing")

    def test_attempt_output_must_stay_below_agents(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        attempt = units[0]["reviewAttempts"][0]
        manifest_path = self.review / attempt["manifest"]
        manifest = load_json(manifest_path)
        manifest["outputDirectory"] = "assignments/WORK-0001/output"
        manifest_path.write_bytes(canonical_bytes(manifest))
        attempt["manifestHash"] = digest_bytes(manifest_path.read_bytes())
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("must be below the agents directory")

    def test_attempt_output_directories_must_be_unique(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        original = unit["reviewAttempts"][0]
        manifest = load_json(self.review / original["manifest"])
        manifest["attemptId"] = "ATTEMPT-0002"
        manifest["reviewerExecutionId"] = "EXEC-SECOND-PRIMARY"
        manifest["reviewerPrincipalId"] = "PRINCIPAL-SECOND-PRIMARY"
        manifest_bytes = canonical_bytes(manifest)
        manifest_path = self.review / "assignments/WORK-0001/ATTEMPT-0002.json"
        manifest_path.write_bytes(manifest_bytes)
        unit["reviewAttempts"].append(
            {
                **original,
                "attemptId": "ATTEMPT-0002",
                "manifest": "assignments/WORK-0001/ATTEMPT-0002.json",
                "manifestHash": digest_bytes(manifest_bytes),
                "reviewerExecutionId": "EXEC-SECOND-PRIMARY",
                "reviewerPrincipalId": "PRINCIPAL-SECOND-PRIMARY",
            }
        )
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("outputDirectory is already owned")

    def test_duplicate_and_orphan_active_second_reviews_are_reported(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        unit["requiredSecondReviews"] = [
            {"id": "SR-001", "angle": 3, "scope": {"kind": "whole_unit"}}
        ]
        completion = {"requirementId": "SR-ORPHAN"}
        unit["completedSecondReviews"] = [completion, dict(completion)]
        rewrite_canonical(self.review, "work-units.jsonl", units)
        issues = check_review(self.review, check_generated=False)["issues"]
        self.assertTrue(any("duplicate active" in issue for issue in issues), issues)
        self.assertTrue(any("orphaned active" in issue for issue in issues), issues)

    def test_v2_checks_do_not_depend_on_security_profile(self):
        run = load_json(self.review / "run.json")
        run.pop("securityProfile")
        rewrite_canonical(self.review, "run.json", run)
        units = load_jsonl(self.review / "work-units.jsonl")
        attempt = units[0]["reviewAttempts"][0]
        manifest_path = self.review / attempt["manifest"]
        manifest = load_json(manifest_path)
        manifest["reviewerPrincipalId"] = ""
        manifest_path.write_bytes(canonical_bytes(manifest))
        attempt["reviewerPrincipalId"] = ""
        attempt["manifestHash"] = digest_bytes(manifest_path.read_bytes())
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("reviewerPrincipalId is required")

    def test_unit_row_must_match_immutable_manifest(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["subsystem"] = "rewritten"
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("unit row subsystem")

    def test_capsule_owned_fields_cannot_be_duplicated_in_unit_manifest(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        unit_manifest_path = self.review / unit["currentManifest"]
        unit_manifest = load_json(unit_manifest_path)
        unit_manifest["configuration"] = ["settings.toml"]
        unit_manifest_path.write_bytes(canonical_bytes(unit_manifest))
        unit_hash = digest_bytes(unit_manifest_path.read_bytes())
        unit["currentManifestHash"] = unit_hash
        unit["manifestHistory"][-1]["hash"] = unit_hash
        attempt = unit["reviewAttempts"][0]
        attempt["unitManifestHash"] = unit_hash
        attempt_manifest_path = self.review / attempt["manifest"]
        attempt_manifest = load_json(attempt_manifest_path)
        attempt_manifest["unitManifestHash"] = unit_hash
        attempt_manifest_path.write_bytes(canonical_bytes(attempt_manifest))
        attempt["manifestHash"] = digest_bytes(attempt_manifest_path.read_bytes())
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("shared orientation facts")

    def test_tier_a_reason_accepts_declared_symbol_location(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        unit["riskTier"] = "A"
        unit["criticalReasons"] = [{
            "code": "durability_recovery",
            "locations": [{"symbol": "src/example.py::commit"}],
            "invariant": "The committed value remains available.",
            "materialConsequence": "Committed data can be lost.",
            "whyTierBInsufficient": "The symbol owns the durability boundary.",
        }]
        requirement = {
            "id": "SR-001",
            "angle": 3,
            "scope": {"kind": "whole_unit"},
        }
        unit["requiredSecondReviews"] = [requirement]
        manifest_path = self.review / unit["currentManifest"]
        manifest = load_json(manifest_path)
        manifest["riskTier"] = "A"
        manifest["requiredSecondReviews"] = [requirement]
        manifest["symbols"] = ["src/example.py::commit"]
        manifest_path.write_bytes(canonical_bytes(manifest))
        unit_hash = digest_bytes(manifest_path.read_bytes())
        unit["currentManifestHash"] = unit_hash
        unit["manifestHistory"][-1]["hash"] = unit_hash
        attempt = unit["reviewAttempts"][0]
        attempt["unitManifestHash"] = unit_hash
        attempt_manifest_path = self.review / attempt["manifest"]
        attempt_manifest = load_json(attempt_manifest_path)
        attempt_manifest["unitManifestHash"] = unit_hash
        attempt_manifest_path.write_bytes(canonical_bytes(attempt_manifest))
        attempt["manifestHash"] = digest_bytes(attempt_manifest_path.read_bytes())
        rewrite_canonical(self.review, "work-units.jsonl", units)
        issues = check_review(self.review, check_generated=False)["issues"]
        self.assertFalse(
            any("malformed Tier A criticalReasons" in issue for issue in issues),
            issues,
        )

    def test_v1_review_state_is_rejected_with_reinitialize_diagnostic(self):
        run = load_json(self.review / "run.json")
        run["reviewSpecVersion"] = 1
        (self.review / "run.json").write_bytes(canonical_bytes(run))
        self.assertIssue("re-initialize")
        with self.assertRaisesRegex(ReviewToolError, "re-initialize"):
            initialize(self.review, CONTRACT, PACK, "none")

    def test_malformed_security_profile_is_reported(self):
        run = load_json(self.review / "run.json")
        run["securityProfile"] = "off"
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("securityProfile is required and must be an object")

    def test_non_object_run_is_reported(self):
        rewrite_canonical(self.review, "run.json", None)
        self.assertIssue("run.json must contain an object")

    def test_malformed_or_missing_canonical_files_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = new_review(Path(temporary) / "missing")
            (missing / "paths.jsonl").unlink()
            checked = check_review(missing, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("missing JSONL file" in issue for issue in checked["issues"])
            )
        with tempfile.TemporaryDirectory() as temporary:
            malformed = new_review(Path(temporary) / "malformed")
            (malformed / "run.json").write_text("{")
            checked = check_review(malformed, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("invalid JSON in" in issue for issue in checked["issues"])
            )

    def test_unhashable_enums_and_references_are_reported(self):
        run = load_json(self.review / "run.json")
        run["status"] = {"malformed": True}
        run["runtimeCapability"] = {"malformed": True}
        run["specialistCapabilities"]["source"] = {"malformed": True}
        rewrite_canonical(self.review, "run.json", run)
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["status"] = {"malformed": True}
        units[0]["angles"]["1"]["status"] = {"malformed": True}
        rewrite_canonical(self.review, "work-units.jsonl", units)
        rewrite_canonical(
            self.review,
            "observations.jsonl",
            [
                {
                    "id": "OBS-000001",
                    "disposition": {"malformed": True},
                    "validationRefs": [{"malformed": True}],
                }
            ],
        )
        rewrite_canonical(
            self.review,
            "validations.jsonl",
            [
                {
                    "id": "VAL-000001",
                    "validationClass": "ordinary",
                    "securityLevel": "off",
                    "observationIds": [{"malformed": True}],
                }
            ],
        )
        rewrite_canonical(
            self.review,
            "audit-objections.jsonl",
            [
                {
                    "id": "AOB-000001",
                    "candidateRefs": [{"malformed": True}],
                }
            ],
        )
        self.assertIssue("run.json status is invalid")

    def test_uncommitted_staged_transaction(self):
        simulate_transaction(self.review, {"architecture.md": b"changed\n"}, committed=False)
        self.assertIssue("uncommitted staged")

    def test_committed_incomplete_transaction(self):
        simulate_transaction(self.review, {"architecture.md": b"changed\n"}, committed=True)
        self.assertIssue("committed-but-incomplete")

    def test_duplicate_and_withdrawal_mappings(self):
        observations = [
            {"id": "OBS-000001", "findingId": "DBR-0001", "disposition": "withdrawn", "withdrawal": {"reason": "fixed"}, "validationRefs": []},
            {"id": "OBS-000002", "findingId": None, "disposition": "duplicate", "duplicateOf": "DBR-0001", "validationRefs": []},
        ]
        rewrite_canonical(self.review, "observations.jsonl", observations)
        issues = check_review(self.review)["issues"]
        self.assertFalse(any("mapping" in issue for issue in issues))
        observations[1]["duplicateOf"] = "DBR-9999"
        rewrite_canonical(self.review, "observations.jsonl", observations)
        self.assertIssue("invalid duplicate mapping")

    def test_lifecycle_transition_rejected_before_commit(self):
        run = load_json(self.review / "run.json")
        run["status"] = "concluded"
        first = Path(self.temporary.name) / "first.json"
        first.write_bytes(canonical_bytes({"run.json": run}))
        apply_mutation(self.review, state_digest(self.review), first)
        digest = state_digest(self.review)
        run["status"] = "active"
        second = Path(self.temporary.name) / "second.json"
        second.write_bytes(canonical_bytes({"run.json": run}))
        with self.assertRaisesRegex(ReviewToolError, "invalid status transition"):
            apply_mutation(self.review, digest, second)
        self.assertEqual(state_digest(self.review), digest)


if __name__ == "__main__":
    unittest.main()
