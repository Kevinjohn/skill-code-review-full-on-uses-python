# 0.3.0 release-confidence gate

This gate covers the correctness and integrity findings reported during the
0.3.0 efficiency work. Version-1 review state is intentionally unsupported;
the supported state model is review specification version 2 only.

Status meanings:

- **Verified** — the implementation has a focused regression test.
- **Retired** — the affected behavior was deliberately removed from scope.
- **Open** — the independent trust-critical review found an unresolved gap.

## Acceptance matrix

| ID | Reported failure or risk | Implementation authority | Regression evidence | Status |
|---|---|---|---|---|
| RC-01 | A stale second-review completion could satisfy a requirement and let a later non-intersecting import mark the unit complete. | `operations._invalidate_primary_dependent_reviews`, `operations._satisfied_second_reviews`, `evidence.validate_second_review_completion_provenance` | `test_late_primary_import_invalidates_completed_second_review`, `test_nonintersecting_primary_does_not_revalidate_second_review`, `test_stale_second_review_can_be_replaced` | Verified |
| RC-02 | An empty reviewer principal could permit self-verification. | `evidence.validate_attempt_manifest_data`, `evidence.validate_reviewer_independence` | `test_v2_import_rejects_empty_reviewer_principal`, `test_second_review_rejects_primary_principal` | Verified |
| RC-03 | Version-2 attempt checks could be skipped when `securityProfile` was absent. | `checks._verify_run_state`, `checks._verify_unit` | `test_v2_checks_do_not_depend_on_security_profile` | Verified |
| RC-04 | Missing `reviewSpecVersion` silently defaulted to version 1. | `evidence.validate_review_spec_version`, `operations._load_v2_run`, `checks._verify_run_state` | `test_missing_review_spec_version_is_reported`, `test_malformed_review_spec_version_is_reported` | Verified |
| RC-05 | Invalidated second-review history was checked against current evidence and could never become valid again. | `evidence.seal_second_review_history`, `evidence.validate_second_review_history` | `test_stale_second_review_can_be_replaced`, `test_second_review_history_is_hash_validated` | Verified |
| RC-06 | Missing `architecture.md` or the reference manifest escaped packet diagnostics as `FileNotFoundError`. | `packets.load_orientation_capsule` | `test_packet_capsule_and_attempt_scaffold_are_deterministic` | Verified |
| RC-07 | A malformed attempt identifier caused an indexing traceback. | `identifiers.attempt_token` | `test_attempt_check_reports_malformed_attempt_identifier` | Verified |
| RC-08 | Concurrent telemetry appends could lose records. | `telemetry.append_telemetry` | `test_private_telemetry_must_be_external` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-09 | The version-1 independence branch had no regression coverage. | Version-1 state and its independence branch were removed; version 2 fails closed. | `test_v1_review_state_is_rejected_with_reinitialize_diagnostic` | Retired |
| RC-10 | Reviewer-independence logic was duplicated across import, packet, and check paths. | `evidence.validate_reviewer_independence`, `evidence.validate_second_review_assignment` | `test_identity_and_independence_routing_are_centralized` | Verified |
| RC-11 | A specification migration compared completed attempts with the current epoch and permanently failed review checks. | `evidence.known_spec_epochs`, `evidence.migration_path`, `checks._verify_attempt` | `test_spec_migration_can_return_a_completed_review_to_validity`, `test_multi_migration_revalidation_and_late_primary_recovery` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-12 | Required second reviews could not be imported after migration because contributing primary evidence was re-sealed against the new epoch. | `evidence.primary_evidence_projection`, `evidence.primary_evidence_identity` | `test_unaffected_second_review_is_carried_across_spec_migration`, `test_multi_migration_revalidation_and_late_primary_recovery` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-13 | A later intersecting primary import could leave a pending second review permanently unimportable. | `operations._invalidate_primary_dependent_reviews` | `test_later_primary_supersedes_pending_second_review` | Verified |
| RC-14 | The version-2 independence path stopped comparing reviewer execution identities. | `evidence.validate_second_review_evidence` | `test_v2_independence_requires_distinct_execution` | Verified |
| RC-15 | Second-review scope accepted supersets and silently dropped malformed scope items. | `evidence.validate_second_review_assignment`, `evidence.scope_covers`, `evidence.scope_is_valid` | `test_second_review_assignment_must_exactly_match_requirement`, `test_invalid_whole_unit_second_review` | Verified |
| RC-16 | Attempt preflight could pass a result that import then rejected. | `packets.validate_attempt_result_data`, shared by preflight, import, and whole-review checks | `test_attempt_check_matches_import_requirement_validation`, `test_check_revalidates_imported_result_schema_after_hash_reseal` | Verified |
| RC-17 | `diagnosticAcknowledgements: null` crashed whole-review checking. | `checks._verify_run_state` | `test_null_diagnostic_acknowledgements_is_reported` | Verified |
| RC-18 | Attempt-token parsing was duplicated and positioned to drift. | `identifiers.attempt_token` | `test_identity_and_independence_routing_are_centralized` | Verified |
| RC-19 | Migration could force `blocked -> needs_revalidation` even though the transition validator rejected it. | `operations._validate_work_unit_transitions` | `test_blocked_unit_can_enter_revalidation_during_spec_migration`, `test_model_based_state_transition_fuzz_is_deterministic` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-20 | A migration capsule hashed the old architecture when the same transaction replaced `architecture.md`. | `operations._migrated_capsule_reference` | `test_spec_migration_capsule_hashes_proposed_architecture` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-21 | A later specialist import overwrote earlier residual uncertainty. | `operations._merge_residual_uncertainty` | `test_residual_uncertainty_is_merged_by_source_attempt` | Verified |
| RC-22 | Malformed `requiredSecondReviews` entries were reported and then dereferenced, causing `AttributeError`. | `checks._valid_second_review_requirements`, `operations._validate_import_unit` | `test_malformed_required_second_reviews_are_reported_without_crashing` | Verified |
| RC-23 | `criticalReasons: null` was reported and then enumerated, causing a traceback. | `checks._verify_tier_a_reasons` | `test_null_critical_reasons_are_reported_without_crashing` | Verified |
| RC-24 | A missing manifest-history hash pin skipped integrity verification. | `checks._verify_manifest_history` | `test_manifest_history_requires_a_hash_pin` | Verified |
| RC-25 | Whole-review checks repeatedly read and hashed the same sealed attempt artifacts. | `evidence.EvidenceCache`, used for one `checks.check_review` pass | `test_check_pass_reuses_identity_keyed_artifact_reads` | Verified |
| RC-26 | A combined `--changes` and `--migrate-spec` operation silently discards proposed `run.json` and `work-units.jsonl` changes. | `operations._validate_migration_request` rejects changes that overlap migration-owned state before preparing any replacement. | `test_spec_migration_rejects_overlapping_changes` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-27 | Prior `specMigrations` entries can be rewritten, changing the historical evidence-validity rules. | `operations._validate_run_mutation` keeps `specMigrations` immutable; `checks.verify_spec_migrations` requires the empty array and fixed `SPEC-0001` epoch. | `test_recorded_spec_migration_is_rejected` | Verified |
| RC-28 | After a later migration, deletion or tampering of an earlier epoch's preserved specification source is no longer detected. | Initialization and each migration preserve a hash-pinned manifest; `checks.verify_reference_install` verifies every recorded epoch. | `test_every_migration_preserves_verifiable_reference_sources` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-29 | `manifestHistory` can be deleted or rewritten without an append-only or complete-chain check. | `operations._validate_work_unit_transitions` enforces append-only mutation; `checks._verify_manifest_history` verifies revision, supersession, file, and attempt-pin chains. | `test_manifest_history_is_append_only_and_chain_validated` | Verified |
| RC-30 | `secondReviewHistory` can be deleted, removing invalidated completion evidence without detection. | Mutation enforces append-only history; `evidence.seal_second_review_history` hash-chains entries; `checks._verify_second_reviews` reconciles every complete imported attempt. | `test_second_review_history_is_append_only_and_complete` | Verified |
| RC-31 | A partial primary result can import an arbitrary or missing angle status into canonical state. | `packets._validate_angle_results` validates every supplied disposition before any complete, partial, or blocked import. | `test_partial_primary_rejects_invalid_angle_status_before_import` | Verified |
| RC-32 | Duplicate affected angles in migration input are committed even though the resulting state fails `check`. | `operations._validate_migration_request` rejects duplicate or invalid angles and sections before transaction preparation. | `test_spec_migration_rejects_duplicate_scope_inputs` | Retired (0.4.0: telemetry and specification migration removed) |
| RC-33 | Attempt row status, disposition, hashes, identifier, result status, and redundant manifest identities are not checked as one coherent lifecycle. | `checks._verify_attempt_lifecycle` and `checks._verify_attempt` validate the lifecycle tuple, hash ownership, sealed manifest projection, and result status together. | `test_attempt_row_lifecycle_must_match_imported_result` | Verified |
| RC-34 | Import parses agent evidence and later re-reads it for hashing, allowing one import to mix two filesystem snapshots. | `operations._read_specialist_evidence` reads result and validations once; parsing and both identities use those bytes. | `test_specialist_import_reads_result_snapshot_once` | Verified |
| RC-35 | Missing or malformed top-level canonical JSON/JSONL can escape `check_review` as an exception instead of a diagnostic result. | `checks._load_canonical_jsonl` and `checks.check_review` contain canonical-file failures and return diagnostic issues. | `test_malformed_or_missing_canonical_files_are_reported` | Verified |
| RC-36 | A primary result can carry structured `secondReviewResults` that are sealed but ignored. | `packets._validate_second_review_result` requires primary results to carry an empty array. | `test_primary_result_rejects_second_review_claims` | Verified |
| RC-37 | A primary attempt could claim paths, symbols, or angles outside its sealed work-unit manifest. | `evidence.validate_second_review_assignment` is the shared assignment-to-unit authority for both packet types. | `test_primary_assignment_cannot_escape_sealed_unit_scope` | Verified |
| RC-38 | Unit completion depended on the latest result status rather than aggregate inspected scope for every required angle. | `evidence.missing_primary_scope`, used by import and whole-review checking. | `test_complete_unit_requires_aggregate_primary_scope_coverage` | Verified |
| RC-39 | Partial and blocked results could omit or lie about their exact remaining scope. | `packets._validate_inspection_scope` requires an exact inspected/not-inspected partition and derives unresolved angles. | `test_partial_result_requires_exact_remaining_partition` | Verified |
| RC-40 | Angle evidence accepted malformed scope objects and empty or meaningless locations. | `packets._evidence_list` validates canonical scope, substantive locations, and assignment containment. | `test_angle_evidence_requires_valid_in_assignment_scope_and_location` | Verified |
| RC-41 | Attempt-local candidates and validations were graph-checked without validating their full result schema or closed result enum. | `result_schema.validate_candidate_schema`, `result_schema.validate_validation_schema`, routed through the shared preflight. | `test_attempt_local_candidate_schema_is_complete`, `test_attempt_local_validation_result_enum_is_closed` | Verified |
| RC-42 | `bulkDispatchAllowed` could remain true when mechanical review validation failed. | `checks.check_review` makes dispatch permission contingent on both diagnostics and zero issues. | `test_complete_unit_requires_aggregate_primary_scope_coverage` | Verified |
| RC-43 | Sealed manifests and capsules were hashed and parsed from separate filesystem reads. | `evidence.load_sealed_attempt_manifest`, `evidence.load_sealed_unit_manifest`, `packets.load_orientation_capsule`, and pinned reference loading parse the bytes they hash. | `test_sealed_packet_artifacts_are_hashed_and_parsed_from_one_read`, `test_specialist_import_reads_result_snapshot_once` | Verified |
| RC-44 | One `reviewerExecutionId` could be reused by multiple specialist attempts. | Mutation and whole-review validation maintain a global execution-owner map. | `test_reviewer_execution_id_is_globally_unique` | Verified |
| RC-45 | A benchmark fingerprint could combine canonical files from different committed states. | `telemetry.write_benchmark_snapshot` pins and rechecks the canonical state digest before and after capture. | `test_benchmark_rejects_a_mixed_state_snapshot` | Verified |
| RC-46 | Packet and result-scaffold generation could spend a model run on an imported, rejected, or superseded attempt. | `packets._require_executable_attempt` requires the assigned/pending lifecycle tuple. | `test_packet_and_scaffold_reject_reconciled_attempt` | Verified |
| RC-47 | Documentation still promised profile-less legacy state would resume as `high`, contradicting version-2 fail-closed behavior. | README and Reference Pack now require re-initialization for unsupported or profile-less state. | `test_documentation_does_not_claim_profileless_legacy_support` | Verified |
| RC-48 | Specification migrations omitted the documented operator authority. | CLI and `operations._validate_migration_request` require authority; migration history records and checks it. | `test_migration_requires_and_records_operator_authority` | Verified |
| RC-49 | Trust-critical mutation/import and whole-review modules had accumulated unrelated report, audit, graph, and result-schema responsibilities. | `reporting.py`, `canonical_checks.py`, and `result_schema.py` isolate those cohesive authorities while `operations.py` preserves its public re-exports. | `test_trust_critical_responsibilities_are_split`, full integration suite | Verified |
| RC-50 | Specialist item-scoped evidence read `kind` even though canonical scope items use the `type` discriminator. | `packets._evidence_list` validates the canonical `type: path|symbol` form. | `test_item_scoped_evidence_uses_canonical_type_discriminator` | Verified |
| RC-51 | String locations bypassed assignment containment, and sliced attempts could claim `whole_unit` evidence. | `packets._evidence_list` binds both structured/string locations to assigned paths or symbols and compares whole-unit claims with sealed unit scope. | `test_string_evidence_location_must_be_inside_assignment`, `test_sliced_assignment_cannot_claim_whole_unit_evidence` | Verified |
| RC-52 | Canonical observations and validations could be minted, deleted, detached from sealed attempts, or have imported provenance rewritten through supported mutation. | Mutation forbids canonical evidence creation outside import and protects existing rows; canonical checks require a known imported `sourceAttempt`, valid work-unit provenance, and full schemas. | `test_canonical_observation_imported_evidence_is_immutable`, `test_canonical_validation_evidence_is_append_only`, `test_canonical_validation_requires_full_schema`, `test_canonical_validation_requires_imported_provenance` | Verified |
| RC-53 | Duplicate second-review requirement IDs collapsed different obligations into one completion identity. | Import and whole-review authorities require unique requirement IDs before completion derivation. | `test_duplicate_second_review_requirement_ids_are_rejected` | Verified |
| RC-54 | Nested candidate locations/list items and validation limitations could contain empty or malformed values. | `result_schema` validates substantive locations, list entries, structured limitation fields, artifacts, and references before import. | `test_nested_candidate_and_limitation_items_must_be_substantive`, `test_blocked_validation_requires_structured_limitation` | Verified |
| RC-55 | Duplicate observations could self-reference or form cycles. | `canonical_checks._verify_canonical_graph` rejects self-targets and detects cycles among observation duplicate edges. | `test_duplicate_observation_cycles_are_rejected` | Verified |

## Release-confidence scenarios

- Replayed the Issue 6 topology with 77 semantic work units and 34 Tier-A
  second-review requirements. The state passes mechanical validation and the
  34/77 pilot diagnostic correctly blocks bulk dispatch pending calibration.
- Replayed five specification epochs containing unaffected second-review
  carry-forward, affected invalidation, revalidation imports, supersession of
  a pending second review by later primary evidence, replacement review, and
  final non-intersecting carry-forward.
- Exercised 1,000 deterministic model-based work-unit and angle transition
  pairs against an independent legal-transition oracle.
- Injected transaction failures before commit, after the first and second
  canonical targets, during event append, and during completion marking.
  Recovery either quarantines the uncommitted transaction or rolls the
  committed transaction forward exactly once.

## Branch coverage

Coverage was measured with branch tracking over the complete test suite.

| Trust-critical region | Statements | Branches |
|---|---:|---:|
| `evidence.py` | 437/540 (80.9%) | 221/320 (69.1%) |
| Migration (`operations.py:796-1220`) | 154/179 (86.0%) | 57/80 (71.2%) |
| Specialist import (`operations.py:1221-1850`) | 184/216 (85.2%) | 64/90 (71.1%) |
| Whole-review checks (`checks.py` + `canonical_checks.py`) | 680/817 (83.2%) | 249/322 (77.3%) |
| Transactions | 110/115 (95.7%) | 33/40 (82.5%) |

The suite has 171 passing tests. These percentages are evidence, not a release
claim: the remaining uncovered branches are a residual risk, especially
malformed historical evidence and migration error paths.

## Independent trust-critical review

The independent passes completed all four requested areas and reported the
trust failures captured in RC-26 through RC-55. Each now has an implementation
authority and focused regression in the acceptance matrix. A final scoped
re-check confirmed all six late findings closed and found no remaining defect
in evidence, migration, specialist import, or whole-review checks. The
implementation gate is **PASS WITH RESIDUAL COVERAGE RISK**.

The same pass found no additional defect in active second-review completion
provenance, principal/execution independence, affected-versus-unaffected
migration decisions, output-directory ownership, local candidate/validation
graphs, state-digest preconditions, or transaction recovery.

Report generation/audit, canonical graph checks, and attempt-local result
schemas now live in focused modules rather than extending the mutation/import
and whole-review check modules further.

## Limits

The representative replay preserves Issue 6's 77/34 state topology but does
not repeat the expensive 132-worker semantic review. It validates state,
identity, migration, import, and recovery mechanics; it does not re-measure
review quality or token savings. A like-for-like exhaustive benchmark remains
the acceptance evidence for the efficiency hypothesis itself.
