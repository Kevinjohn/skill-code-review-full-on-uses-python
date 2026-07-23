# Changelog

All notable changes to this project are documented here.

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
