"""Validator coverage meta-test.

Corrupts every field the tool writes into run.json, paths.jsonl, and
work-units.jsonl (including nested attempt, angle, and manifest-history
records) and asserts that check_review reports a targeted issue for it.

Fields whose corruption is only caught by the canonical-state digest chain
must be listed in DIGEST_ONLY with that intent made explicit; anything else
that degrades to digest-only detection is a missing check and fails here.
check_review must never raise, whatever the corruption.

Scope note: observations/validations/audit-objections field coverage lives in
result_schema.py and the broken-state tests; this sweep covers the files whose
validation is hand-written in checks.py.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import clean_unit, new_review, rewrite_canonical
from review_tool.checks import check_review
from review_tool.io import load_json, load_jsonl

# Issues that fire for ANY byte change to canonical state; they prove the
# digest chain works, not that the corrupted field is understood.
GENERIC_ISSUES = (
    "repository-content or canonical-state identity mismatch",
    "baseline repository-content identity mismatch",
)

CORRUPT_VALUE = {"__corrupted__": True}

# (label, mutation) pairs where digest-only detection is an accepted design
# decision, with the reason. Every other field must produce a targeted issue.
DIGEST_ONLY = {
    # run.json bookkeeping and free-text progress fields; advisory only.
    ("run.baselineCommit", "delete"), ("run.baselineCommit", "corrupt"),
    ("run.budget", "delete"), ("run.budget", "corrupt"),
    ("run.capabilitySource", "delete"), ("run.capabilitySource", "corrupt"),
    ("run.checkpointReason", "delete"), ("run.checkpointReason", "corrupt"),
    ("run.completedPhases", "delete"), ("run.completedPhases", "corrupt"),
    ("run.concludedAt", "delete"), ("run.concludedAt", "corrupt"),
    ("run.currentPhase", "delete"), ("run.currentPhase", "corrupt"),
    ("run.generatedStateDigest", "delete"), ("run.generatedStateDigest", "corrupt"),
    ("run.nextActions", "delete"), ("run.nextActions", "corrupt"),
    ("run.repositoryIdentity", "delete"), ("run.repositoryIdentity", "corrupt"),
    ("run.reviewDirectory", "delete"), ("run.reviewDirectory", "corrupt"),
    ("run.schemaMigrations", "delete"), ("run.schemaMigrations", "corrupt"),
    ("run.startedAt", "delete"), ("run.startedAt", "corrupt"),
    ("run.supersededBy", "delete"), ("run.supersededBy", "corrupt"),
    ("run.targetPolicy", "delete"), ("run.targetPolicy", "corrupt"),
    ("run.updatedAt", "delete"), ("run.updatedAt", "corrupt"),
    # finalAudit checks only apply once its status is "imported".
    ("run.finalAudit", "delete"), ("run.finalAudit", "corrupt"),
    # Absent field is equivalent to its documented null/empty default.
    ("run.verdict", "delete"),
    ("run.diagnosticAcknowledgements", "delete"),
    # Provenance/source strings preserved for the operator, never re-read.
    ("run.specification.contractPreserved", "delete"),
    ("run.specification.contractPreserved", "corrupt"),
    ("run.specification.contractSource", "delete"),
    ("run.specification.contractSource", "corrupt"),
    ("run.specification.initializedAt", "delete"),
    ("run.specification.initializedAt", "corrupt"),
    ("run.specification.referencePackPreserved", "delete"),
    ("run.specification.referencePackPreserved", "corrupt"),
    ("run.specification.referencePackSource", "delete"),
    ("run.specification.referencePackSource", "corrupt"),
    # criticalReasons are validated only for Tier A units; the fixture is Tier B
    # and the Tier A path is covered by dedicated broken-state tests.
    ("unit.criticalReasons", "delete"), ("unit.criticalReasons", "corrupt"),
    # Unit bookkeeping fields; advisory only.
    ("unit.residualUncertainty", "delete"), ("unit.residualUncertainty", "corrupt"),
    ("unit.revisionEpoch", "delete"), ("unit.revisionEpoch", "corrupt"),
    ("unit.title", "delete"), ("unit.title", "corrupt"),
    ("unit.updatedAt", "delete"), ("unit.updatedAt", "corrupt"),
    # Absent collections are equivalent to their empty defaults.
    ("unit.completedSecondReviews", "delete"),
    ("unit.reviewAttempts", "delete"),
    # Absent hashes are equivalent to null on a non-imported attempt.
    ("unit.reviewAttempts[0].attemptEvidenceHash", "delete"),
    ("unit.reviewAttempts[0].resultHash", "delete"),
    # Angle evidence/specEpoch are only required once the angle is reviewed.
    ("unit.angles.1.evidence", "delete"), ("unit.angles.1.evidence", "corrupt"),
    ("unit.angles.1.specEpoch", "delete"), ("unit.angles.1.specEpoch", "corrupt"),
    ("unit.angles.5.evidence", "delete"), ("unit.angles.5.evidence", "corrupt"),
    # Free-text revision reason; the chain itself is hash-pinned.
    ("unit.manifestHistory[0].reason", "delete"),
    ("unit.manifestHistory[0].reason", "corrupt"),
    # Absent supersedes equals the expected null for the first revision.
    ("unit.manifestHistory[0].supersedes", "delete"),
}


def _mutate(review: Path, relative: str, navigate, kind: str) -> None:
    if relative.endswith(".jsonl"):
        document = load_jsonl(review / relative)
    else:
        document = load_json(review / relative)
    container, key = navigate(document)
    if kind == "delete":
        container.pop(key, None)
    else:
        container[key] = dict(CORRUPT_VALUE)
    rewrite_canonical(review, relative, document)


def _field_targets(review: Path):
    """Yield (label, relative, navigate) covering every written field."""
    run = load_json(review / "run.json")
    for key in run:
        yield f"run.{key}", "run.json", (lambda d, k=key: (d, k))
    for section in ("specification", "securityProfile", "specialistCapabilities"):
        for key in run[section]:
            yield (
                f"run.{section}.{key}",
                "run.json",
                (lambda d, s=section, k=key: (d[s], k)),
            )
    for key in load_jsonl(review / "paths.jsonl")[0]:
        yield f"path.{key}", "paths.jsonl", (lambda rows, k=key: (rows[0], k))
    unit = load_jsonl(review / "work-units.jsonl")[0]
    for key in unit:
        yield f"unit.{key}", "work-units.jsonl", (lambda rows, k=key: (rows[0], k))
    for key in unit["reviewAttempts"][0]:
        yield (
            f"unit.reviewAttempts[0].{key}",
            "work-units.jsonl",
            (lambda rows, k=key: (rows[0]["reviewAttempts"][0], k)),
        )
    for angle in ("1", "5"):
        for key in unit["angles"][angle]:
            yield (
                f"unit.angles.{angle}.{key}",
                "work-units.jsonl",
                (lambda rows, a=angle, k=key: (rows[0]["angles"][a], k)),
            )
    for key in unit["manifestHistory"][0]:
        yield (
            f"unit.manifestHistory[0].{key}",
            "work-units.jsonl",
            (lambda rows, k=key: (rows[0]["manifestHistory"][0], k)),
        )


class ValidatorCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name)
        cls.pristine = new_review(cls.base / "pristine")
        clean_unit(cls.pristine)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_pristine_fixture_is_valid(self):
        self.assertEqual(
            check_review(self.pristine, check_generated=False)["issues"], []
        )

    def test_every_field_corruption_is_detected(self):
        stale_allowlist = set(DIGEST_ONLY)
        for index, (label, relative, navigate) in enumerate(
            list(_field_targets(self.pristine))
        ):
            for kind in ("delete", "corrupt"):
                with self.subTest(field=label, mutation=kind):
                    copy = self.base / f"mutation-{index}-{kind}"
                    shutil.copytree(self.pristine, copy)
                    try:
                        _mutate(copy, relative, navigate, kind)
                        result = check_review(copy, check_generated=False)
                    finally:
                        shutil.rmtree(copy, ignore_errors=True)
                    specific = [
                        issue
                        for issue in result["issues"]
                        if not any(generic in issue for generic in GENERIC_ISSUES)
                    ]
                    stale_allowlist.discard((label, kind))
                    if (label, kind) in DIGEST_ONLY:
                        self.assertFalse(
                            specific,
                            f"{label} [{kind}] is allowlisted as digest-only but "
                            f"now has targeted detection; remove it from "
                            f"DIGEST_ONLY: {specific}",
                        )
                        self.assertTrue(
                            result["issues"],
                            f"{label} [{kind}] corruption was not detected at all",
                        )
                    else:
                        self.assertTrue(
                            specific,
                            f"{label} [{kind}] corruption produced no targeted "
                            f"issue; add a check or explicitly allowlist it "
                            f"(all issues: {result['issues']})",
                        )
        self.assertFalse(
            stale_allowlist,
            f"DIGEST_ONLY names fields that no longer exist: {stale_allowlist}",
        )


if __name__ == "__main__":
    unittest.main()
