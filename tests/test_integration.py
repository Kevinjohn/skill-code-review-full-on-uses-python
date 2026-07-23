from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import CONTRACT, PACK, ROOT, TOOL
from review_tool.io import canonical_bytes, canonical_identity, digest_bytes, load_json, state_digest
from review_tool.transactions import simulate_transaction


class IntegrationTests(unittest.TestCase):
    def run_tool(self, *args: str, expected: int = 0):
        process = subprocess.run([os.fspath(Path(os.sys.executable)), os.fspath(TOOL), *args], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        return process

    def test_miniature_repository_smoke_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", repository], check=True)
            (repository / "example.py").write_text("VALUE = 1\n")
            subprocess.run(["git", "-C", repository, "add", "example.py"], check=True)
            review = repository / "code-reviews/fixture"
            self.run_tool("init", "--review-dir", str(review), "--contract", str(CONTRACT), "--reference-pack", str(PACK), "--security-level", "high")

            path_row = {"path": "example.py", "revisionEpoch": "EPOCH-0001", "entryKind": "file", "baselineState": "staged", "contentId": "blob-1", "sizeBytes": 10, "implementationLines": 1, "language": "python", "subsystem": "core", "classification": "production", "exclusion": None}
            content_set = canonical_identity([path_row])
            unit_manifest = {
                "workId": "WORK-0001", "revision": 1, "supersedes": None, "reason": "initial",
                "revisionEpoch": "EPOCH-0001", "reviewSpecVersion": 1, "specEpoch": "SPEC-0001", "riskTier": "B", "securityLevel": "high",
                "contentSetHash": content_set, "paths": [{"path": "example.py", "contentId": "blob-1"}],
                "sizeTotals": {"productionFiles": 1, "implementationLines": 1}, "limitException": None,
                "symbols": [], "entryPoints": [], "boundaries": [], "knownInvariants": [],
                "requiredAngleDispositions": list(range(1, 11)), "requiredSecondReviews": [],
                "repositoryInstructions": [], "permittedValidationScope": [],
                "permittedValidationClasses": ["ordinary", "security_static", "security_dynamic_isolated"],
                "outputSchema": "specialist-result-schema.md",
                "preservedAttemptManifestHashes": [],
            }
            unit_bytes = canonical_bytes(unit_manifest)
            unit_hash = digest_bytes(unit_bytes)
            attempt_manifest = {
                "workId": "WORK-0001", "attemptId": "ATTEMPT-0001",
                "unitManifest": "assignments/WORK-0001/MANIFEST-0001.json", "unitManifestHash": unit_hash,
                "packetType": "primary_semantic", "reviewerExecutionId": "EXEC-001", "reviewSpecVersion": 1,
                "securityLevel": "high",
                "specEpoch": "SPEC-0001", "assignedScope": {"paths": ["example.py"], "symbols": [], "angles": list(range(1, 11))},
                "secondReviewRequirementId": None, "independentFromAttemptIds": [], "primaryEvidenceSetHash": None,
                "repositoryInstructions": [], "permittedValidationScope": [],
                "permittedValidationClasses": ["ordinary", "security_static", "security_dynamic_isolated"],
                "outputDirectory": "agents/WORK-0001/ATTEMPT-0001",
            }
            attempt_bytes = canonical_bytes(attempt_manifest)
            attempt_hash = digest_bytes(attempt_bytes)
            run = load_json(review / "run.json")
            run.update({"repositoryIdentity": str(repository), "baselineCommit": "index-state", "baselineContentSetHash": content_set})
            angles = {str(number): {"status": "pending", "evidence": [], "specEpoch": None} for number in range(1, 11)}
            unit = {
                "id": "WORK-0001", "revisionEpoch": "EPOCH-0001", "specEpoch": "SPEC-0001",
                "currentManifest": "assignments/WORK-0001/MANIFEST-0001.json", "currentManifestHash": unit_hash,
                "manifestHistory": [{"revision": 1, "path": "assignments/WORK-0001/MANIFEST-0001.json", "hash": unit_hash}],
                "contentSetHash": content_set, "paths": ["example.py"], "title": "miniature module", "subsystem": "core",
                "riskTier": "B", "securityLevel": "high", "criticalReasons": [], "status": "assigned",
                "reviewAttempts": [{"attemptId": "ATTEMPT-0001", "manifest": "assignments/WORK-0001/ATTEMPT-0001.json", "manifestHash": attempt_hash, "unitManifestHash": unit_hash, "packetType": "primary_semantic", "reviewerExecutionId": "EXEC-001", "independentFromAttemptIds": [], "status": "assigned", "resultHash": None, "importDisposition": "pending"}],
                "angles": angles, "requiredSecondReviews": [], "completedSecondReviews": [], "residualUncertainty": [], "updatedAt": "2026-01-01T00:00:00Z",
            }
            changes = {
                "run.json": run, "paths.jsonl": [path_row], "work-units.jsonl": [unit],
                "assignments/WORK-0001/MANIFEST-0001.json": unit_manifest,
                "assignments/WORK-0001/ATTEMPT-0001.json": attempt_manifest,
            }
            changes_path = base / "changes.json"
            changes_path.write_text(json.dumps(changes))
            self.run_tool("mutate", "--review-dir", str(review), "--expected-digest", state_digest(review), "--changes", str(changes_path))

            attempt_dir = review / "agents/WORK-0001/ATTEMPT-0001"
            attempt_dir.mkdir(parents=True)
            evidence = [{"scopeCovered": {"kind": "whole_unit"}, "locations": ["example.py:1"], "claim": "The constant assignment has no stateful behavior in this fixture."}]
            result = {
                "workId": "WORK-0001", "attemptId": "ATTEMPT-0001", "reviewerExecutionId": "EXEC-001",
                "packetType": "primary_semantic", "unitManifestHash": unit_hash, "attemptManifestHash": attempt_hash,
                "specEpoch": "SPEC-0001", "securityLevel": "high", "status": "complete", "inspected": {"paths": ["example.py"], "symbols": []},
                "notInspected": {"paths": [], "symbols": []},
                "angleDispositions": {str(number): {"status": "reviewed", "evidence": evidence} for number in range(1, 11)},
                "secondReviewResults": [],
                "candidates": [{
                    "localId": "CAND-A1-001", "title": "Fixture question", "category": "question",
                    "primaryLocation": {"path": "example.py", "startLine": 1, "endLine": 1},
                    "proposedDisposition": "unresolved", "proposedMateriality": "non_material",
                    "proposedMaterialityRationale": "The fixture is informational.",
                    "confidence": "Low", "affectedConfigurations": ["fixture"], "evidence": ["fixture"],
                    "likelihood": "unlikely", "blastRadius": "fixture only", "reachability": "direct",
                    "existingChecks": "none", "reproduction": "read the constant",
                    "recommendation": "answer the question", "regressionTest": "retain the fixture",
                    "counterargument": "none", "residualUncertainty": "none",
                    "validationRefs": ["AVAL-A1-001"],
                }],
                "residualUncertainty": [], "remainingScope": {"paths": [], "symbols": [], "angles": []},
            }
            (attempt_dir / "result.json").write_text(json.dumps(result))
            validation = {"localId": "AVAL-A1-001", "validationClass": "ordinary", "command": "python3 -m py_compile example.py", "cwd": str(repository), "environmentSummary": "temporary fixture", "startedAt": "2026-01-01T00:00:00Z", "endedAt": "2026-01-01T00:00:00Z", "exitStatus": 0, "result": "passed", "limitations": [], "createdArtifacts": [], "supportsCandidates": ["CAND-A1-001"]}
            (attempt_dir / "validations.jsonl").write_text(json.dumps(validation) + "\n")
            self.run_tool("import", "--review-dir", str(review), "--work-id", "WORK-0001", "--attempt-id", "ATTEMPT-0001", "--expected-digest", state_digest(review))
            imported_observation = json.loads((review / "observations.jsonl").read_text())
            self.assertEqual(imported_observation["affectedConfigurations"], ["fixture"])
            self.assertEqual(imported_observation["proposedDisposition"], "unresolved")
            self.assertEqual(imported_observation["proposedMateriality"], "non_material")
            self.assertIsNone(imported_observation["materiality"])
            self.assertEqual(imported_observation["regressionTest"], "retain the fixture")
            self.assertEqual(imported_observation["residualUncertainty"], "none")
            self.run_tool("generate", "--review-dir", str(review))
            self.run_tool("check", "--review-dir", str(review), "--json")
            self.run_tool("audit", "--review-dir", str(review), "--mode", "checkpoint", "--json")

            transaction = simulate_transaction(review, {"architecture.md": b"# recovered architecture\n"}, committed=True)
            from review_tool.transactions import recover
            recovery = recover(review)
            self.assertEqual(recovery["rolledForward"], 1)
            self.assertTrue((transaction / "COMPLETE").exists())

    def test_cli_errors_and_unknown_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            process = self.run_tool("init", "--review-dir", str(base / "review"), "--contract", str(CONTRACT), "--reference-pack", str(PACK), "--unknown", expected=2)
            self.assertIn("unrecognized arguments", process.stderr)
            process = self.run_tool("check", "--review-dir", temporary, expected=2)
            self.assertIn("missing JSON", process.stderr)
            process = self.run_tool("init", "--review-dir", str(base / "invalid"), "--contract", str(CONTRACT), "--reference-pack", str(PACK), "--security-level", "extreme", expected=2)
            self.assertIn("invalid choice", process.stderr)

    def test_cli_persists_each_security_level_and_rejects_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for level in ("off", "low", "medium", "high"):
                review = base / level
                self.run_tool(
                    "init",
                    "--review-dir",
                    str(review),
                    "--contract",
                    str(CONTRACT),
                    "--reference-pack",
                    str(PACK),
                    "--security-level",
                    level,
                )
                run = load_json(review / "run.json")
                self.assertEqual(run["securityProfile"]["level"], level)
                self.assertEqual(run["securityProfile"]["source"], "user")
            process = self.run_tool(
                "init",
                "--review-dir",
                str(base / "off"),
                "--contract",
                str(CONTRACT),
                "--reference-pack",
                str(PACK),
                "--security-level",
                "high",
                expected=2,
            )
            self.assertIn("start a new review to change it", process.stderr)

    def test_final_auditor_atomic_import_with_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = base / "review"
            self.run_tool("init", "--review-dir", str(review), "--contract", str(CONTRACT), "--reference-pack", str(PACK), "--security-level", "high")
            self.run_tool("generate", "--review-dir", str(review))
            report_hash = digest_bytes((review / "report-manifest.json").read_bytes())
            manifest = {
                "attemptId": "ATTEMPT-0001", "reviewerExecutionId": "EXEC-AUDITOR",
                "independentFromReviewerExecutionIds": ["EXEC-PRIMARY"], "deterministicSample": [],
                "baselineContentSetHash": None, "finalWorkUnitSetHash": "empty-work-set",
                "mechanicalAuditHash": "mechanical", "reportManifestHash": report_hash, "securityLevel": "high",
                "permittedValidationClasses": ["ordinary", "security_static", "security_dynamic_isolated"],
            }
            manifest_path = review / "assignments/FINAL-AUDIT/ATTEMPT-0001.json"
            changes_path = base / "audit-assignment.json"
            changes_path.write_text(json.dumps({"assignments/FINAL-AUDIT/ATTEMPT-0001.json": manifest}))
            self.run_tool("mutate", "--review-dir", str(review), "--expected-digest", state_digest(review), "--changes", str(changes_path))
            attempt_dir = review / "agents/FINAL-AUDIT/ATTEMPT-0001"
            attempt_dir.mkdir(parents=True)
            result = {
                "attemptId": "ATTEMPT-0001", "reviewerExecutionId": "EXEC-AUDITOR",
                "attemptManifestHash": digest_bytes(manifest_path.read_bytes()), "specEpoch": "SPEC-0001", "securityLevel": "high",
                "status": "complete", "baselineContentSetHash": None, "finalWorkUnitSetHash": "empty-work-set",
                "mechanicalAuditHash": "mechanical", "reportManifestHash": report_hash,
                "tierAUnitsInspected": [], "sampledUnits": [], "excludedClassesSampled": [], "notApplicableClassesSampled": [],
                "candidates": [{
                    "localId": "CAND-A1-001", "title": "Audit candidate", "category": "audit",
                    "primaryLocation": None, "affectedConfigurations": ["audit fixture"],
                    "regressionTest": "retain the audit fixture",
                    "residualUncertainty": "none", "validationRefs": ["AVAL-A1-001"],
                }],
                "objections": [{"localId": "AAOB-A1-001", "affectedPaths": [], "workUnits": [], "materiality": "non_material", "evidence": ["fixture"], "requiredResolution": "Disposition candidate", "candidateRefs": ["CAND-A1-001"]}],
                "residualUncertainty": [], "remainingScope": {"workUnits": [], "classes": [], "checks": []},
            }
            (attempt_dir / "result.json").write_text(json.dumps(result))
            validation = {"localId": "AVAL-A1-001", "validationClass": "ordinary", "command": "fixture", "cwd": str(base), "environmentSummary": "fixture", "startedAt": "2026-01-01T00:00:00Z", "endedAt": "2026-01-01T00:00:00Z", "exitStatus": 0, "result": "passed", "limitations": [], "createdArtifacts": [], "supportsCandidates": ["CAND-A1-001"]}
            (attempt_dir / "validations.jsonl").write_text(json.dumps(validation) + "\n")
            self.run_tool("import-audit", "--review-dir", str(review), "--attempt-id", "ATTEMPT-0001", "--expected-digest", state_digest(review))
            observations = [json.loads(line) for line in (review / "observations.jsonl").read_text().splitlines()]
            validations = [json.loads(line) for line in (review / "validations.jsonl").read_text().splitlines()]
            objections = [json.loads(line) for line in (review / "audit-objections.jsonl").read_text().splitlines()]
            self.assertEqual(observations[0]["validationRefs"], ["VAL-000001"])
            self.assertEqual(observations[0]["affectedConfigurations"], ["audit fixture"])
            self.assertEqual(observations[0]["regressionTest"], "retain the audit fixture")
            self.assertEqual(validations[0]["observationIds"], ["OBS-000001"])
            self.assertEqual(objections[0]["candidateRefs"], ["OBS-000001"])


if __name__ == "__main__":
    unittest.main()
