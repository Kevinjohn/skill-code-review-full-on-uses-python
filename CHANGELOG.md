# Changelog

All notable changes to this project are documented here.

## 0.5.0 — 2026-07-25

### Fixed

- `check_review` no longer crashes with a raw `TypeError` when
  `currentManifest` or an attempt `importDisposition` is corrupted to a
  non-string value; both now produce targeted issues, and an unhashable
  disposition no longer aborts the remaining checks for its unit.
- `import-audit` no longer silently defaults a missing final-auditor
  `validationClass` to `ordinary`; the class permission check always runs.

### Added

- A validator-coverage meta-test that deletes and corrupts every field the
  tool writes into `run.json`, `paths.jsonl`, and `work-units.jsonl`
  (including nested attempt, angle, and manifest-history records) and
  requires a targeted issue for each; fields protected only by the
  canonical-state digest are named in an explicit allowlist with the reason.
- `review_tool/schema.py`: declarative field-rule tables for run, security
  profile, unit, angle, and attempt-lifecycle constraints — the single
  source of truth for field-shape validation, with messages verified
  byte-identical to the previous validator across a 424-state differential
  corpus.

### Changed

- Security-profile-dependent checks now always run and fail closed: a review
  whose profile is missing or malformed reports every resulting mismatch
  instead of suppressing profile-scoped validation.

### Removed

- The declared-profile compatibility scaffolding threaded through the
  validator and importers; the tool is single-operator, a security profile
  is mandatory, and legacy profile-less state is simply re-initialized.

## 0.4.0 — 2026-07-25

### Fixed

- Terminal `PASS`/`CONDITIONAL PASS` verdicts are now blocked by any material
  observation that is not explicitly rejected, duplicate, withdrawn, or
  profile-deferred; previously an `open` material observation passed the gate.
- `run.json` `verdict` and `currentEpoch` are now validated; a typo'd verdict
  can no longer bypass the material-concern gate.
- Attempt identifiers require exactly four digits (`ATTEMPT-NNNN`), closing an
  aliasing hole where `ATTEMPT-001` and `ATTEMPT-1` produced colliding local
  candidate/validation namespaces.
- Re-initializing an existing review now verifies the supplied contract and
  reference pack byte-for-byte against the preserved copies instead of
  silently reporting idempotent success.
- The state-event `operation` field is now a closed enum
  (`init|mutate|import|import_audit`) enforced at write and at every check;
  events carry their transaction identity so distinct same-second events can
  no longer alias and silently drop.
- Filesystem read errors are reported as read failures, not "invalid JSON",
  and directory-fsync failures other than unsupported-operation now surface
  instead of being swallowed.
- A missing attempt-manifest `outputDirectory` is reported as the actual
  defect instead of a phantom ownership collision.

### Added

- An exclusive advisory lock (`tooling/LOCK`) now serializes every
  state-writing operation; concurrent writers fail fast instead of silently
  clobbering canonical state.
- Crash recovery replays committed transactions in event-sequence order
  instead of random transaction-directory order, and both import paths run
  recovery before reading state.

### Removed

- Removed the specification-migration subsystem (`mutate --migrate-spec`,
  epoch chains, carry-forward attestations, successor capsules); editing the
  contract or reference pack now requires a new review, which is the honest
  cost for a monthly workflow.
- Removed private telemetry records and benchmark snapshots
  (`telemetry-record`, `benchmark-snapshot`) and the unused deterministic
  audit-sampling helper; none were exercised by the review workflow.

## 0.3.0 — 2026-07-23

### Added

- Added specification-version-2 primary-evidence identities, stable reviewer
  principals, lineage-gated warm reuse, structured Tier-A reasons, and pilot
  efficiency diagnostics.
- Added deterministic specialist packets, immutable orientation capsules,
  attempt-local result scaffolding and preflight validation.
- Added external-only private telemetry records and derived benchmark
  snapshots pinned to the 0.2.0 baseline.

### Changed

- Later intersecting primary imports now invalidate affected second reviews
  mechanically and return the unit to revalidation.
- Sealed assignments and attempt records are immutable; current v2 evidence,
  principals, specification identities, capsule structure, and unit-manifest
  authority are checked consistently at packet, preflight, import, and review
  gates.
- Stale second reviews can be replaced without invalidating preserved history;
  partial reviews cannot satisfy requirements, and duplicate imports are
  rejected.
- Specification migrations now create successor capsules and unit manifests,
  preserve historical attempt epochs, and supersede stale pending assignments.
- Review gates re-hash imported raw evidence, bind active completions to their
  imported attempts, require substantive second-review evidence, and enforce
  both principal and execution independence.
- Packet and attempt tooling now verifies reference extracts, uses one sealed
  output-directory authority, rejects malformed nested records, and shares
  identifier and independence routing.
- Mutation, migration, import, and whole-review checks now compose shared
  manifest and result validators through focused phases instead of duplicating
  gate logic in monolithic command handlers.
- Private telemetry is source-repository-external and concurrency-safe.
  Benchmark snapshots are retained, validate source state, and separate stable
  fingerprints from capture-time identities.
- Specialist phase scopes prohibit accidental general re-review while
  preserving incidental observations and explicit follow-up.
- New reviews use review specification version 2; version-1 reviews are
  unsupported and fail fast with a re-initialization diagnostic.
- Specification migration now carries forward only unaffected second-review
  evidence, seals invalidated completions in tamper-evident history, and
  validates imported attempts against the recorded v2 epoch chain.
- Attempt output is confined to unique directories beneath `agents/`; complete
  results must exhaust assigned scope and provide substantive angle evidence.
- Preserved specification sources and extracts are hash-pinned, sealed artifact
  verification is cached per check pass, and concurrent benchmark snapshots
  allocate unique files atomically.
- Specification, migration, unit-manifest, and invalidated second-review
  histories are append-only and verified as complete chains across every
  recorded epoch.
- Specialist imports validate and hash one evidence snapshot, enforce coherent
  attempt lifecycles, reject primary-authored second-review claims, and fail
  malformed canonical state as diagnostics instead of tracebacks.
- Primary assignments are bounded by sealed unit scope; completion now requires
  aggregate inspected coverage for every required angle, and partial results
  preserve an exact remaining-scope partition.
- Candidate, validation, evidence-location, execution-identity, benchmark
  snapshot, packet lifecycle, and migration-authority checks now fail closed;
  report/audit, canonical graph, and local result schemas have focused modules.

## 0.2.0 — 2026-07-23

### Added

- Added portable dispatch-conformance cases for object-shaped and serialized
  inputs, malformed or missing assignments, duplicates, unknown work,
  zero-scheduled waves, and canonical no-ops.

### Changed

- Expanded canonical observations and specialist output guidance to preserve
  complete diagnostic, remediation, regression-test, reachability, affected
  configuration, and uncertainty details.
- Representative pilots now exercise the same adapter and argument boundary as
  scaled waves. Dispatch records and reconciles intended, scheduled, and
  started identities and fails closed on invalid input.
- Generated review summaries now include severity counts and links to concise
  and detailed finding views.

### Fixed

- Generated reports now preserve and render the complete finding details
  required by the review specification, with readable path-and-line locations,
  stable detail links, and honest placeholders for unavailable legacy fields.
- Withdrawn findings now link to their retained detail instead of a severity
  page that no longer contains them.

## 0.1.3 — 2026-07-23

### Added

- Added a behaviour-based defensive assurance taxonomy for precise worker
  scopes covering application invariants, authorized evidence, validation
  limits, and prohibited actions.

### Changed

- Defensive worker assignments now prefer component-and-invariant descriptions
  while preserving the canonical security level and validation class.
- Policy refusals must be recorded and must not be reworded and resubmitted.

## 0.1.2 — 2026-07-23

### Added

- Added a detailed guide to the rationale, limits, enforcement, and reporting
  implications of each security-review level.
- Added a standard read-only diagnostic prompt that produces sanitized,
  consistently structured security-level interruption reports.
- Added a dedicated GitHub Issue Form for submitting the generated report,
  visible interruption message, and genuine screenshot evidence.

## 0.1.1 — 2026-07-23

### Added

- Added `off`, `low`, `medium`, and `high` security-review levels, with new
  reviews defaulting to `off`.
- Persisted immutable security profiles in review state and inherited them
  through work-unit, specialist-attempt, and final-audit manifests.
- Added validation-class allow-lists and import-time enforcement for ordinary,
  static-security, and isolated dynamic-security validation.
- Added profile exclusions, incidental security deferrals, scoped completion
  outcomes, and explicit security-assessment reporting.

### Changed

- Security-only workers, Angle 5 review, threat modelling, security scanning,
  adversarial testing, and vulnerability reproduction are excluded at `off`.
- Security depth can be selected with
  `--security-level off|low|medium|high` or an equivalent natural-language
  request.
- Legacy reviews without a stored security profile retain their original
  `high` behavior when resumed.

### Fixed

- Preserved compatibility with legacy reference snapshots that do not contain
  the security-level section.
- Rejected worker and final-auditor manifests or validation records that exceed
  the run's declared security profile.

## 0.1.0 — 2026-07-22

- Initial public implementation of the exhaustive repository-review skill,
  transactional review-state utility, reference contract, tests, and CI.
