# Changelog

All notable changes to this project are documented here.

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
