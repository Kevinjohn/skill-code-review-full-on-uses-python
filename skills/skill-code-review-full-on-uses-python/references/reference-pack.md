# Review Reference Pack

Reference Pack version: 2. Companion to Orchestrator Contract version 2. The
state utility preserves these editable sources for the life of the review and
derives phase-specific files using Section R10. Runtime identities protect
the reviewed repository and review evidence, not this documentation.

## R1. Observation categories

Report every defensible observation within completed scope:

- correctness, data loss, corruption, security, concurrency, durability, and
  distributed-systems concerns;
- reliability, availability, performance, scalability, compatibility, API,
  protocol, observability, and operations concerns;
- test, documentation, accessibility, maintainability, and architecture issues;
- low-priority defects, nits, suggestions, and unresolved questions.

## R2. Canonical record schemas

Required fields appear below. Additional fields may enrich, but must not create
a second authority for the same fact. Mid-review schema changes are not
supported; start a new review against the edited specification.

### `run.json`

```json
{
  "schemaVersion": 1,
  "reviewSpecVersion": 2,
  "specEpoch": "SPEC-0001",
  "specification": {
    "initializedAt": "<UTC>",
    "contractSource": "<relative or supplied path>",
    "contractPreserved": "tooling/reference/source/contract.md",
    "referencePackSource": "<relative or supplied path>",
    "referencePackPreserved": "tooling/reference/source/reference-pack.md",
    "referenceManifestPreserved": "tooling/reference/source/manifest.json",
    "referenceManifestHash": "..."
  },
  "specMigrations": [],
  "repositoryIdentity": "...",
  "reviewDirectory": "code-reviews/...",
  "status": "active",
  "verdict": null,
  "runtimeCapability": "none",
  "capabilitySource": "absent_default_none",
  "specialistCapabilities": {
    "stableReviewerLineage": false,
    "source": "absent_default_false"
  },
  "diagnosticAcknowledgements": [],
  "securityProfile": {
    "level": "off|low|medium|high",
    "source": "default|user",
    "externalTargets": false
  },
  "targetPolicy": "frozen_baseline|explicit_moving_target",
  "currentEpoch": "EPOCH-0001",
  "baselineCommit": null,
  "baselineContentSetHash": null,
  "startedAt": "<UTC>",
  "updatedAt": "<UTC>",
  "concludedAt": null,
  "budget": null,
  "currentPhase": "baseline",
  "completedPhases": [],
  "checkpointReason": null,
  "nextActions": [],
  "schemaMigrations": [],
  "stateEventHead": "...",
  "supersededBy": null,
  "generatedStateDigest": null,
  "finalAudit": null
}
```

Do not store derived counts in `run.json`. Verdict remains null before a valid
terminal handoff. `runtimeCapability` is always `none` (this host has no
automatic continuation), `specMigrations` is always an empty array, and
`specEpoch` is always `SPEC-0001`: specification migration is not supported,
so editing the contract or Reference Pack requires a new review.

### `paths.jsonl`

One immutable row per `(revisionEpoch, path)`:

```json
{"path":"src/example.py","revisionEpoch":"EPOCH-0001","entryKind":"file","baselineState":"tracked","contentId":"git-blob-or-sha256","sizeBytes":1234,"implementationLines":120,"language":"python","subsystem":"storage","classification":"production","exclusion":null}
```

Include tracked, dirty, deleted, renamed, untracked, symlink, submodule,
generated, vendored, fixture, example, benchmark, platform, experimental,
deprecated, documentation, schema, script, and release paths. Exclude only VCS
internals, authorized review/validation output, or explicit user scope:

```json
{"category":"review_output|validation_output|security_profile|explicit_out_of_scope","rationale":"...","boundaryEvidence":["..."],"authorizedBy":"contract|securityProfile:off|user:<authority>"}
```

Every in-scope row has exactly one current primary assignment; excluded rows
have none. `security_profile` is valid only at level `off`, only for a path
whose primary purpose is security-specific, and requires concrete boundary
evidence. Mixed-purpose paths remain assigned for non-security scope. Derive
`baselineContentSetHash` from a canonical path-sorted array of current rows.
Derive each work-unit content identity equivalently. Derive the final
work-unit-set identity from current units sorted by ID and projected to ID,
epoch, current manifest identity, content-set identity, and tier.

### `work-units.jsonl`

```json
{
  "id":"WORK-0001",
  "revisionEpoch":"EPOCH-0001",
  "specEpoch":"SPEC-0001",
  "currentManifest":"assignments/WORK-0001/MANIFEST-0001.json",
  "currentManifestHash":"...",
  "manifestHistory":[{
    "revision":1,
    "path":"assignments/WORK-0001/MANIFEST-0001.json",
    "hash":"...",
    "supersedes":null,
    "reason":"initial",
    "preservedAttemptManifestHashes":[]
  }],
  "contentSetHash":"...",
  "paths":["src/example.py"],
  "title":"transaction commit path",
  "subsystem":"storage",
  "riskTier":"A",
  "securityLevel":"off",
  "criticalReasons":[{
    "code":"durability_recovery",
    "locations":[{"path":"src/example.py","symbol":"commit"}],
    "invariant":"Acknowledged state survives the documented boundary.",
    "materialConsequence":"Acknowledged data can be lost.",
    "whyTierBInsufficient":"The unit owns the durability boundary."
  }],
  "status":"pending",
  "reviewAttempts":[],
  "angles":{
    "1":{"status":"pending","evidence":[],"specEpoch":null},
    "5":{"status":"excluded_by_profile","evidence":[],"specEpoch":"SPEC-0001","profileExclusion":{"domain":"security","level":"off"}}
  },
  "requiredSecondReviews":[{"id":"SR-001","angle":3,"scope":{"kind":"whole_unit"}}],
  "completedSecondReviews":[],
  "secondReviewHistory":[],
  "residualUncertainty":[{"sourceAttempt":"WORK-0001/ATTEMPT-0001","value":"..."}],
  "updatedAt":"<UTC>"
}
```

All ten string angle keys `1` through `10` are mandatory. Attempt status is
`assigned`, `complete`, `partial`, `blocked`, or `interrupted`; import
disposition is `pending`, `imported`, `rejected`, or
`reconciled_interruption`, or `superseded`. Only `(assigned, pending)`,
`(complete|partial|blocked, imported)`, and
`(interrupted, rejected|reconciled_interruption|superseded)` are valid
attempt lifecycle pairs. Imported and reconciled interruption rows retain
their result and evidence hashes; other rows do not. Work status is `pending`,
`assigned`, `partial`, `complete`, `blocked`, or `needs_revalidation`. Angle status is `pending`,
`reviewed`, `not_applicable`, `excluded_by_profile`, `blocked`, or
`needs_revalidation`.

Legal work transitions:

```text
pending -> assigned | blocked
assigned -> partial | complete | blocked | needs_revalidation
partial -> assigned | blocked | needs_revalidation
complete -> needs_revalidation
blocked -> pending | assigned | needs_revalidation
needs_revalidation -> assigned | blocked
```

Legal angle transitions are `pending -> reviewed|not_applicable|
excluded_by_profile|blocked`, `reviewed|not_applicable|excluded_by_profile ->
needs_revalidation`, `blocked -> pending`, and `needs_revalidation -> reviewed|
not_applicable|excluded_by_profile|blocked`. Same-state mutation must add
evidence or another fact. Reviewed requires semantic evidence; not-applicable
requires source- or architecture-backed applicability evidence.
`excluded_by_profile` is valid only for Angle 5 at security level `off` and
records `profileExclusion` plus the current `specEpoch`.

Evidence has this shape:

```json
{"sourceAttempt":"WORK-0001/ATTEMPT-0001","scopeCovered":{"kind":"whole_unit"},"locations":["src/example.py:10"],"claim":"Concrete semantic claim"}
```

Scope is `{"kind":"whole_unit"}` or typed unique items:

```json
{"kind":"items","items":[{"type":"path","value":"src/example.py"},{"type":"symbol","value":"src/example.py::commit"}]}
```

Each completed second review records requirement and attempt identities,
reviewer execution identity, independence set, primary evidence identity,
covered scope, evidence, conclusion (`concur`, `dissent`, or `expanded`), and
canonical observations. Whole-unit requirements need whole-unit coverage; item
requirements need the same valid typed item set. The reviewer
principal and execution identity must each differ from every primary
contributor. Re-derived primary evidence must remain equal.

For specification version 2, derive contributors from every imported
`primary_semantic` attempt whose assigned angle and typed path/symbol scope
intersect the requirement. `whole_unit` intersects any non-empty assigned
scope for the required angle. An item requirement intersects when at least one
typed path or symbol is shared.

Project each contributor to `attemptId`, `manifestHash`, `assignedScope`,
`resultHash`, `attemptEvidenceHash`, and `specEpoch`; sort by UTF-8 attempt ID
and hash the canonical array. `attemptEvidenceHash` is the canonical identity
of the complete attempt-local `result.json` value and parsed
`validations.jsonl` rows. Imported partial or interrupted evidence participates
whenever its immutable assignment intersects and records the run's
specification epoch. A later intersecting primary import changes
this identity, moves the completion to hash-pinned `secondReviewHistory`, and
returns the unit to revalidation. Recompute both imported identities from the
raw files whenever the evidence is checked.

Only the current pending second-review assignment and active completion are
validated against the current derived identity. Superseded attempts remain
sealed, and historical completions carry a `historyHash`,
`previousHistoryHash`, stale reason, attempt manifest identity, and immutable
raw-result claims. `manifestHistory` and `secondReviewHistory` are append-only;
their hashes form complete, ordered chains back to the initial manifest or
first stale completion. Every complete imported second-review attempt appears
exactly once as an active or historical completion. Retain a replacement as the
sole active completion. A later intersecting primary automatically marks a
pending second-review attempt `superseded`; create a fresh attempt against the
new identity. A partial or blocked second review never creates a completion.

An active completion resolves to exactly one complete imported
`independent_second_review` attempt and matches its sealed manifest, reviewer
identities, requirement, result, evidence, scope, and conclusion. Evidence is
non-empty and the conclusion is `concur`, `dissent`, or `expanded`.
`candidateRefs` are preserved verbatim and resolve exactly to the recorded
canonical observations.

Completion requires ten dispositioned angles: reviewed or validly
not-applicable angles plus the profile-excluded Angle 5 at level `off`. It also
requires all current second-review requirements, persisted observations, and
explicit uncertainty.

### Immutable unit manifest

```json
{"workId":"WORK-0001","revision":1,"supersedes":null,"reason":"initial","revisionEpoch":"EPOCH-0001","reviewSpecVersion":2,"specEpoch":"SPEC-0001","riskTier":"A","securityLevel":"off","subsystem":"storage","orientationCapsule":{"path":"assignments/capsules/storage.json","hash":"..."},"contentSetHash":"...","paths":[{"path":"src/example.py","contentId":"..."}],"sizeTotals":{"productionFiles":1,"implementationLines":120},"limitException":null,"symbols":[],"requiredAngleDispositions":[1,2,3,4,6,7,8,9,10],"requiredSecondReviews":[{"id":"SR-001","angle":3,"scope":{"kind":"whole_unit"}}],"repositoryInstructions":[],"permittedValidationScope":[],"permittedValidationClasses":["ordinary"],"outputSchema":"specialist-result-schema.md","preservedAttemptManifestHashes":[]}
```

Successors increment revision, name the predecessor path and identity, explain
why, and list preserved attempt-manifest identities. Within one content epoch,
requirements may only grow or widen.

Published unit and attempt manifest files are immutable. Never replace a
published `assignments/...` file or rewrite sealed assignment fields in a
`reviewAttempts` row; create a successor manifest or a new attempt. Lifecycle
fields change only through import or the explicit pending-to-superseded
transition. An attempt manifest's
`reviewSpecVersion` and `specEpoch` must exactly match the run.

### Immutable attempt manifest

```json
{"workId":"WORK-0001","attemptId":"ATTEMPT-0001","unitManifest":"assignments/WORK-0001/MANIFEST-0001.json","unitManifestHash":"...","packetType":"primary_semantic","reviewerPrincipalId":"PRINCIPAL-001","reviewerExecutionId":"HOST-EXEC-1042","reviewerReuseMode":"cold","reviewerBatchId":null,"reviewSpecVersion":2,"specEpoch":"SPEC-0001","securityLevel":"off","assignedScope":{"paths":["src/example.py"],"symbols":[],"angles":[1,2,3,4,6,7,8,9,10]},"secondReviewRequirementId":null,"independentFromAttemptIds":[],"primaryEvidenceSetHash":null,"repositoryInstructions":[],"permittedValidationScope":[],"permittedValidationClasses":["ordinary"],"outputDirectory":"agents/WORK-0001/ATTEMPT-0001"}
```

Second-review manifests name one current requirement, its single angle, all
contributing primary attempts, and a sealed primary evidence identity. Their
paths and symbols match that requirement exactly. Every `outputDirectory` is a
unique child of `agents/`; assignment, tooling, and canonical-state namespaces
are never valid output targets.

### `observations.jsonl`

```json
{"id":"OBS-000001","sourceWorkUnits":["WORK-0001"],"sourceAttempt":"WORK-0001/ATTEMPT-0001","sourceLocalId":"CAND-A1-001","title":"...","category":"correctness","primaryLocation":{"path":"src/example.py","startLine":10,"endLine":12},"additionalLocations":[],"disposition":"open","proposedDisposition":"unresolved","reportClass":null,"findingId":null,"severity":null,"materiality":null,"proposedMateriality":"non_material","materialityRationale":null,"proposedMaterialityRationale":"...","confidence":"Medium","affectedComponents":[],"affectedConfigurations":[],"affectedDeployments":[],"evidence":[],"counterargument":"...","trigger":"...","expected":"...","actual":"...","impact":"...","likelihood":"...","blastRadius":"...","reachability":"...","existingChecks":"...","reproduction":"...","recommendation":"...","regressionTest":"...","residualUncertainty":"...","validationRefs":[],"duplicateOf":null,"withdrawal":null,"createdAt":"<UTC>","updatedAt":"<UTC>"}
```

Disposition is `open`, `validated`, `rejected`, `duplicate`, `unresolved`,
`withdrawn`, or `deferred_by_profile`. Legal ordinary transitions are `open ->
validated|rejected|duplicate|unresolved|deferred_by_profile`, `unresolved ->
open|validated|rejected|duplicate|deferred_by_profile`, and `validated ->
withdrawn`. `deferred_by_profile` is valid only for an incidental security
candidate at level `off`; retain only the minimum location and deferral
information needed for traceability in
`{"profileDeferral":{"securityLevel":"off","reason":"..."}}`, without developing
or validating the candidate. Validated and unresolved records use report class
`finding`, `nit`, `suggestion`, `question`, `test_gap`, or `documentation`,
and materiality `material` or `non_material` with rationale. P0/P1 is material. Duplicates
resolve to canonical OBS or DBR identifiers. Rejections preserve the defeating
evidence. Validated P0–P4 findings receive gapless DBR IDs.

### `validations.jsonl`

```json
{"id":"VAL-000001","sourceAttempt":"WORK-0001/ATTEMPT-0001","sourceLocalId":"AVAL-A1-001","workUnits":["WORK-0001"],"observationIds":["OBS-000001"],"securityLevel":"off","validationClass":"ordinary","command":"...","cwd":"...","environmentSummary":"...","startedAt":"<UTC>","endedAt":"<UTC>","exitStatus":0,"result":"passed","limitations":[],"createdArtifacts":[],"trackedTreeMutation":null}
```

Result is `passed`, `failed`, `blocked`, `not_run`, or `inconclusive`. The last
three require a limitation with description, materiality, rationale, and
remaining action. Validation class is `ordinary`, `security_static`, or
`security_dynamic_isolated` and must be permitted by the run security level.
Every observation reference resolves.

### `audit-objections.jsonl`

```json
{"id":"AOB-000001","sourceAttempt":"FINAL-AUDIT/ATTEMPT-0001","sourceLocalId":"AAOB-A1-001","affectedPaths":["src/example.py"],"workUnits":["WORK-0001"],"materiality":"material","evidence":["..."],"requiredResolution":"...","disposition":"open","resolutionEvidence":[],"candidateRefs":[],"createdAt":"<UTC>","updatedAt":"<UTC>"}
```

Disposition is `open`, `resolved`, or `withdrawn`; terminal states require
resolution evidence.

### `state-events.jsonl`

```json
{"sequence":1,"previousEventHash":null,"eventHash":"...","operation":"init|mutate|import|import_audit","actor":"orchestrator","timestamp":"<UTC>","transaction":"TXN-...","preStateDigest":null,"postStateDigest":"...","targets":["run.json"]}
```

The event identity is calculated from all fields except `eventHash`. State
digest scope is the six canonical JSON/JSONL files, `architecture.md`, and all
assignment files, sorted by UTF-8 path. Canonicalize `run.json` with
`stateEventHead` omitted to avoid self-reference. Sequences start at one and
are gapless; each prior identity and digest must link. `agents/`, `baseline/`,
`tooling/`, generated views, and the event log are excluded.

### Specialist `result.json` (attempt-local)

```json
{"workId":"WORK-0001","attemptId":"ATTEMPT-0001","reviewerPrincipalId":"PRINCIPAL-001","reviewerExecutionId":"HOST-EXEC-1042","packetType":"primary_semantic","unitManifestHash":"...","attemptManifestHash":"...","specEpoch":"SPEC-0001","securityLevel":"off","status":"complete","inspected":{"paths":["src/example.py"],"symbols":[]},"notInspected":{"paths":[],"symbols":[]},"angleDispositions":{"1":{"status":"reviewed","evidence":[{"scopeCovered":{"kind":"whole_unit"},"locations":["src/example.py:1"],"claim":"Concrete semantic claim."}]}},"secondReviewResults":[],"candidates":[],"residualUncertainty":[],"remainingScope":{"paths":[],"symbols":[],"angles":[]}}
```

Primary packets disposition every assigned profile-required angle;
second-review packets disposition only the assigned angle and still preserve
incidental candidates. Each candidate uses its attempt token and includes
title, category, locations, `proposedDisposition`, `proposedMateriality`,
`proposedMaterialityRationale`, confidence, affected
components/configurations/deployments, trigger, expected and actual behavior,
impact, likelihood, blast radius, evidence, reachability, existing checks,
reproduction, `recommendation`, regression test, counterargument, residual
uncertainty, and validation references. Proposed values remain non-authoritative
until canonical validation. Use an empty value when a detail is not yet
established; never invent it.

A `complete` result inspects every assigned path and symbol, leaves
`notInspected` and `remainingScope` empty, and supplies substantive
`scopeCovered`, `locations`, and `claim` fields for every angle disposition.
On import, unit-level residual uncertainty is merged as
`{"sourceAttempt":"WORK-NNNN/ATTEMPT-NNNN","value":...}` records; one attempt
never erases another attempt's disclosure.

### Specialist `validations.jsonl` (attempt-local)

```json
{"localId":"AVAL-A1-001","validationClass":"ordinary","command":"...","cwd":"...","environmentSummary":"...","startedAt":"<UTC>","endedAt":"<UTC>","exitStatus":0,"result":"passed","limitations":[],"createdArtifacts":[],"supportsCandidates":["CAND-A1-001"]}
```

Attempt token `A<n>` is the numeric attempt index without leading zeroes.
Local identifiers have no authority outside their attempt directory.

### Immutable final-auditor attempt manifest

```json
{"attemptId":"ATTEMPT-0001","reviewerExecutionId":"HOST-EXEC-9001","independentFromReviewerExecutionIds":["HOST-EXEC-1042"],"deterministicSample":[],"baselineContentSetHash":"...","finalWorkUnitSetHash":"...","mechanicalAuditHash":"...","reportManifestHash":"...","securityLevel":"off","permittedValidationClasses":["ordinary"]}
```

### Final-auditor `result.json` (attempt-local)

```json
{"attemptId":"ATTEMPT-0001","reviewerExecutionId":"HOST-EXEC-9001","attemptManifestHash":"...","specEpoch":"SPEC-0001","securityLevel":"off","status":"complete","baselineContentSetHash":"...","finalWorkUnitSetHash":"...","mechanicalAuditHash":"...","reportManifestHash":"...","tierAUnitsInspected":[],"sampledUnits":[],"excludedClassesSampled":[],"notApplicableClassesSampled":[],"objections":[],"candidates":[],"residualUncertainty":[],"remainingScope":{"workUnits":[],"classes":[],"checks":[]}}
```

The audit import validates deterministic scope and independence, then rewrites
local objection, candidate, and validation references atomically. A partial,
blocked, or unimported audit never satisfies completion.

## R3. Risk tiers

### Tier A — critical

Use for durability, recovery, migration, backup/restore, isolation, shared
mutation, unsafe or concurrent code, authentication, authorization, secrets,
tenant boundaries, untrusted parsing, consensus, replication, fencing,
sharding, public protocol/storage/SDK/CLI compatibility, destructive
administration, externally visible acknowledgements, central high-fanout
control, or unusually complex weakly-tested behavior with material blast
radius. Normally limit to 20 production files and 8,000 implementation lines.
Require symbol-level evidence, failure sequences, non-empty authoritative
second-review requirements, and focused validation or a precise limitation.

For specification version 2, use one or more controlled reason codes:
`durability_recovery`, `migration_backup_restore`,
`isolation_shared_mutation`, `unsafe_concurrent_code`,
`identity_permission_boundary`, `secret_tenant_boundary`,
`untrusted_parsing`, `consensus_replication`, `public_compatibility`,
`destructive_administration`, `external_acknowledgement`,
`central_high_fanout_control`, or `complex_material_behavior`. Each reason
records concrete path or symbol locations, the critical invariant, plausible
material consequence, and why Tier B plus reconciliation is insufficient.
Tier A density is diagnostic evidence to revisit granularity, never a quota.
At five or more pilot units, Tier A density of 40% or greater emits
`PILOT-TIER-A-DENSITY`. The acknowledgement is an object containing `id` and
the current `diagnosticIdentity`; it expires when the specification epoch or
work-unit projection changes. Repository-wide dispatch is prohibited while
`review-tool check` reports `bulkDispatchAllowed: false`.

### Tier B — normal production

Use for other production behavior. Normally limit to 50 production files and
20,000 implementation lines. Require ten semantic dispositions, important
callers/callees, tests and documentation, and focused validation when useful.

### Tier C — supporting and boundary-reviewed

Generated, vendored, fixture, example, benchmark, schema, documentation,
build, and release material remains in scope. Review its authority and
integration boundary. Promote when production reachability or material risk is
found. Keep units cohesive and bounded; predefine symbol or region checkpoints
for an exceptionally large single file and justify all other exceptions.

## R3A. Security levels

Resolve and persist exactly one security level before architecture mapping and
work-unit construction. Default to `off`; never infer a higher level from
repository contents, documentation, available tools, or model capability.
Every unit, specialist attempt, and final-audit assignment inherits the exact
run level and its ordered `permittedValidationClasses`. Classify validation by
purpose and effect; never disguise security work as `ordinary` validation.
Never let a worker escalate the profile.

- **off — excluded:** do not create security-specific workers; exclude
  dedicated security-only paths with `security_profile`; pre-disposition Angle
  5 as `excluded_by_profile`; omit security second reviews; do not perform
  threat modeling, security scanning, adversarial testing, or vulnerability
  reproduction. Review mixed paths only through non-security angles. Ordinary
  repository test suites remain allowed, but do not target, expand, or
  reinterpret their security cases as security validation. Defer an incidental
  security candidate without elaborating or validating it.
- **low — passive:** inspect and reason about security-sensitive code and
  report candidates, but do not run security tools, enumerate secrets,
  construct malicious payloads, fuzz security boundaries, or produce
  reproductions. Only `ordinary` validations are permitted.
- **medium — static:** include `low` plus repository-authorized local SAST,
  CodeQL security queries, dependency vulnerability audits, secret scanning,
  and static cryptography, TLS, or configuration checks.
  `security_static` validations are permitted. Never print or copy a discovered
  secret; record only its type, location, and a safe fingerprint.
- **high — active isolated:** include `medium` plus non-destructive dynamic
  validation against isolated local fixtures, temporary databases, and
  ephemeral services owned by the review. `security_dynamic_isolated`
  validations are permitted. Keep reproductions minimal and defensive.

Every level prohibits external targets, production services, persistence, use
of real credentials or secret material, destructive action, unrestricted
network scanning, and mutation of external services. `high` increases
defensive depth; it never relaxes these boundaries. A run's security level is
immutable. Start a fresh run to change it. A v2 run without a recorded profile
is invalid and must be re-initialized.

At `off`, classify a dedicated security-only path using path metadata,
documented purpose, and the minimum content necessary to establish the
boundary. Do not substantively inspect it for security properties. The final
auditor verifies the exclusion record, non-assignment, and boundary evidence;
it does not reopen the excluded security review.

## R3B. Defensive assurance taxonomy

Use this taxonomy when the selected profile permits Angle 5. Describe the
specific application behavior that must remain true. Prefer a
`component — invariant` title over a broad category label, then state the
expected invariant, authorized evidence, permitted validation, and prohibited
actions.

This taxonomy is for precise defensive communication. It is not a prohibited-
word list or a translation scheme for policy evasion. Keep `securityLevel`,
`permittedValidationClasses`, purpose, authority, and limits explicit. Do not
use different wording to change an activity's classification or to retry work
after a policy refusal.

| Assurance focus | Invariant to inspect |
|---|---|
| Actor identity continuity | Each protected operation acts for the identity established by the intended sign-in, session, renewal, recovery, and sign-out lifecycle. |
| Operation permission invariants | Every operation checks the expected role, ownership, state, and resource boundary before any externally visible effect. |
| Account and tenant separation | Reads, writes, caches, jobs, exports, and administrative paths remain scoped to the intended account or tenant. |
| Statement and data separation | Values originating outside the statement builder remain bound data and cannot alter database statement structure. |
| Process argument separation | External values remain distinct from executable names, shell syntax, flags, and process-control structure. |
| Rendered content separation | Untrusted display values remain content and cannot alter document structure, executable behavior, or navigation policy. |
| Filesystem root containment | User-influenced names, links, archives, and canonicalized paths remain within the intended application-owned roots. |
| Outbound destination control | Application-initiated requests reach only intended schemes, hosts, ports, redirects, and address ranges. |
| Request provenance and replay resistance | State-changing browser and API operations require the intended origin, session context, freshness, and one-time proofs where applicable. |
| Parser and decoder bounds | Parsers reject unsupported structures, external references, excessive nesting or size, ambiguous encodings, and unsafe object construction. |
| Sensitive-value lifecycle | Credentials, tokens, recovery material, and private values are minimally collected, narrowly exposed, safely stored, rotated, revoked, and excluded from logs. |
| Protected-channel and peer identity | Connection setup verifies the intended peer and transport properties without unsafe fallback. |
| Key, nonce, and randomness lifecycle | Maintained platform primitives receive suitable keys, uniqueness inputs, entropy, rotation, and failure handling. |
| Session and recovery lifecycle | Session creation, renewal, invalidation, recovery, reauthentication, and multi-step identity checks preserve the intended account guarantees. |
| Repeated-operation containment | Expensive or sensitive operations have appropriate frequency, concurrency, size, and resource-consumption limits. |
| Import, extension, and plugin boundaries | Imported data and executable extensions cross explicit format, capability, origin, and lifecycle boundaries before activation. |
| Dependency and build provenance | Declared packages, generated inputs, release artifacts, and build steps come from intended sources with reproducible integrity checks. |
| Audit record integrity | Material identity, permission, administrative, and state-changing events produce complete, ordered, attributable, and tamper-evident records. |
| Administrative-operation guards | Destructive or high-impact operations require the intended role, confirmation, scope, transaction behavior, and recovery path. |
| Transaction and approval integrity | Multi-step approvals and state transitions cannot be reordered, replayed, partially committed, or completed by an unintended actor. |
| Configuration fail-safe behavior | Missing, malformed, development, or contradictory settings fail safely and cannot silently weaken production boundaries. |
| Information exposure control | Responses, diagnostics, metrics, traces, logs, exports, and caches reveal no more internal or private detail than their audience requires. |

Construct worker scopes from the applicable rows. Examples:

- `Persistence layer — statement/data separation and account ownership`
- `Sign-in flows — identity and session lifecycle correctness`
- `Import pipeline — parser bounds and filesystem root containment`
- `Outbound clients — destination control and sensitive-value lifecycle`
- `Administrative operations — role, approval, transaction, and audit invariants`

Use this assignment shape:

```text
Defensive assurance purpose: <component and behavior>
Expected invariants: <specific properties that must remain true>
Authorized evidence: <source, configuration, documentation, and permitted tests>
Permitted validation: <exact inherited validation classes and local scope>
Prohibited actions: <profile limits plus repository-specific exclusions>
```

At `low`, inspect source, configuration, existing tests, and documentation
without constructing targeted executions. At `medium`, add only
repository-authorized local static checks. At `high`, add only non-destructive
checks against isolated, review-owned local fixtures. Canonical terminology may
still be used when repository language or reporting accuracy requires it; do
not trade clarity for synonym substitution.

## R4. Mandatory specialist block

<!-- BEGIN MANDATORY SPECIALIST BLOCK -->
> For a primary packet, review the entire assigned manifest. For every other
> packet, stay within its named angle, observation, seam, tail class, or audit
> sample and inspect only the supporting scope needed to establish the result.
> Do not proactively restart general review; preserve incidental observations
> and record exact follow-up scope when widening is required. Persist evidence
> while working and write only to your assigned attempt directory. Inspect
> implementation, important
> callers and callees, failure paths, tests, configuration, and relevant
> documentation. Disposition every required review angle. Report every
> defensible observation regardless of severity; there is no finding cap.
> Continue after severe issues and include low-severity defects, tests,
> documentation, observability, operations, accessibility, maintainability,
> nits, suggestions, and unresolved questions. Record candidates that fail
> validation instead of silently dropping them. Do not assume another reviewer
> will report an overlap. Use attempt-local candidate and validation identifiers
> only; permanent identifiers are assigned at import. Preserve the supplied
> reviewer execution identity, declared profile, and validation-class limits
> exactly; never expand or escalate them. For assigned defensive work, organize
> evidence around the supplied component invariants and preserve its purpose
> honestly. Before returning, enumerate inspected and uninspected paths and
> symbols, completed and pending angles, validations,
> observations, and residual uncertainty. Mark the result `complete`, `partial`,
> or `blocked`; partial or blocked results identify exact remaining scope.
> Persist the result before sending a compact receipt containing only status,
> result path, counts, and remaining scope. Do not repeat the persisted result
> in chat.
<!-- END MANDATORY SPECIALIST BLOCK -->

## R5. Phase 4 cross-component checklist

- success acknowledged before durable persistence;
- inconsistent validation or authorization across entry points;
- recovery violating normal-runtime invariants;
- migrations incompatible with current or mixed-version readers and writers;
- cancellation or retry exposing or duplicating partial mutations;
- caches surviving schema, ownership, leadership, epoch, or generation change;
- documentation promising stronger guarantees than implementation;
- dependent state persisted non-atomically across components;
- error translation changing retry or compatibility semantics;
- startup, reload, health, shutdown, or cleanup disagreement;
- backup and restore format disagreement;
- administrative tooling bypassing production invariants;
- test helpers modeling behavior unlike production;
- individually correct components composing unsafely;
- release, SDK, CLI, or packaging behavior inconsistent with core APIs;
- relevant TODO/FIXME/HACK/XXX, ignored errors, swallowed exceptions, aborts,
  unsafe operations, disabled checks, skipped tests, broad handlers, fallback
  defaults, unbounded work, process execution, persistence, and authorization
  markers. Validate markers before treating them as findings.

## R6. Validated finding format

Include category, severity, materiality and rationale, confidence, locations,
affected components/configurations/deployments, trigger or interleaving,
expected and actual behavior, impact, likelihood, blast radius, reachability,
why checks and tests do not prevent/detect it, smallest reproduction or missing
prerequisite, remediation, regression test, counterargument, and uncertainty.

```markdown
### DBR-NNNN — [P#] Short, specific title

- **Observation:** OBS-NNNNNN
- **Category:**
- **Severity:**
- **Materiality and rationale:**
- **Confidence:**
- **Locations:**
- **Affected components and configurations:**
- **Trigger or failure sequence:**
- **Expected / actual:**
- **Impact, likelihood, and blast radius:**
- **Evidence and reachability:**
- **Existing checks and tests:**
- **Smallest reproduction:**
- **Remediation and regression test:**
- **Counterargument:**
- **Residual uncertainty:**
```

Empty generated category files explicitly state zero results.

## R7. Severity and confidence ladders

- **P0:** immediate catastrophic, broadly exploitable, or unavoidable extreme
  release-blocking loss/corruption.
- **P1:** realistic loss/corruption, boundary bypass, distributed-safety
  violation, major outage, or fundamental correctness failure.
- **P2:** meaningful correctness, reliability, performance, compatibility,
  security, or operational problem under plausible conditions.
- **P3:** limited-impact defect, difficult edge, weak diagnostic, localized
  reliability, or maintainability issue with concrete cost.
- **P4:** minor quality, clarity, defensive, documentation, test, or
  maintainability issue worth fixing.
- **Nit:** trivial polish. **Suggestion:** non-defect improvement.
  **Question:** ambiguity unresolved by repository evidence.

Confidence is **High** when demonstrated or unambiguously proven, **Medium**
with one relevant assumption unverified, and **Low** when plausible and
evidence-backed but confirmation is needed.

## R8. Handoff contents

Generated `README.md` contains repository and revision identity, dirty state,
timestamps, lifecycle, runtime, verdict/checkpoint; counts by severity,
confidence, class, disposition, tier, unit, and angle; material findings and
verification gaps; manifest and independence status; architecture boundaries;
validation and limitations; links to all views; coverage, exclusions,
partials, uncertainty; remediation order; audit objections; and applicable gate.

Terminal communication includes review path/state; revision/epoch/dirty state;
verdict and recommendation; complete counts including withdrawn, rejected,
duplicate, unresolved, profile-deferred, and tail classes; path and tier
coverage; security-profile exclusions; unit statuses; validation limitations;
audit status; uncertainty; attempt, event-chain and verdict consistency; gate
result; and a link to the generated README and security-deferral view when
applicable.

## R9. Review-angle checklists

Disposition all ten angles for every work unit. Apply each relevant detailed
check and evidence why non-applicable checks do not apply.

### Angle 1 — Data correctness and semantics

Review invariants, transitions, results, missing/duplicate/boundary/partial
behavior, numeric precision and conversions, encoding and Unicode, locale,
time and ordering, identity resolution, caches, serialization symmetry,
format/version compatibility, ignored errors, misleading success, inconsistent
entry points, undefined behavior, and documentation promises. Construct the
smallest concrete input or transition for suspected defects.

### Angle 2 — Transactions, concurrency, and isolation

Review atomicity, commit/rollback/retry/cancellation, isolation anomalies,
locks/atomics/channels/queues, fairness/deadlock/starvation, races/TOCTOU,
publication/initialization/reentrancy/ownership, MVCC/snapshots/epochs and
wraparound, cleanup under abort and schema change, concurrent migration and
recovery, and production assumptions hidden by single-threaded tests. Describe
shared state, competing operations, synchronization gap, and harmful result.

### Angle 3 — Storage, durability, and crash recovery

Review journals, checkpoints, compaction, write/flush/sync/rename ordering,
partial writes, torn data, checksums, corruption, replay order/idempotency,
interrupted initialization/migration/backup/restore, storage failures,
temporary files and mappings, acknowledgment durability, process/host/power
boundaries, format upgrades and repair. Name the exact durability boundary.

### Angle 4 — Distributed systems and replication

Where applicable review safety/liveness, election/fencing/terms/epochs,
quorums/membership/split brain, log order and stale replicas, retry/idempotency/
timeouts/clocks, network faults, bootstrap/snapshot/rejoin, mixed versions,
sharding/rebalance, durability claims, regions and session guarantees. Describe
node-and-message timelines.

### Angle 5 — Security and trust boundaries

At level `off`, do not assign this angle; retain its orchestrator-created
`excluded_by_profile` disposition. At level `low`, perform passive source
review only. At level `medium`, permit static local security validation. At
level `high`, permit active isolated validation within R3A.

Review authentication and authorization on each operation, tenant/data/admin
isolation, injection, parser bypass, deserialization, traversal, symlinks,
server-side requests, secrets/cryptography/randomness/transport/revocation,
post-side-effect checks, extensions/imports/restores, denial of service,
defaults/debug/dependencies/audit logs, and inconsistent interface checks.
Trace attacker-controlled input to a sensitive sink and state prerequisites,
missing guard, crossed boundary, and impact.

### Angle 6 — Resource management and reliability

Review memory/descriptor/socket/thread/task/lock/transaction/cursor/snapshot/
temporary leaks, unbounded work, backpressure/quotas/overload, cancellation/
timeouts/retries/storms, exception containment and partial lifecycle, health and
workers, error causality/fallback, malformed or adversarial input, cascading
failure, poison work, and stuck operations.

### Angle 7 — Performance and scalability

Review complexity and pathological input, plans/indexes/scans, repeated work
and round trips, allocation/copy/synchronization/contention, cache correctness
and bounds, batching/amplification/background work, hot partitions and global
bottlenecks, event-loop blocking, startup/recovery/schema/connection scaling,
hot-path telemetry, and benchmark validity. Separate demonstrated defects from
ideas; state workload, complexity, bottleneck, impact, and needed measurement.

### Angle 8 — Public API, protocol, and compatibility

Review contracts, parsing and state machines, malformed/fragmented/duplicated/
reordered/unknown fields, negotiation, wire/storage migration and mixed
versions, retry/idempotency/errors, pagination/order/defaults/deprecation,
CLI/SDK automation, handshakes/cancellation/streaming/framing/limits, examples,
and compatibility fixtures.

### Angle 9 — Tests, fuzzing, and verification

Review missing failure/concurrency/crash/corruption/partition branches, weak
assertions, accidental passes, mocking and unrealistic fixtures, races/order/
sleeps/skips, missing property/fuzz/differential/model/invariant/fault checks,
platform/migration/compatibility matrices, benchmarks, helpers hiding failure,
seed reproduction, sanitizers/race tools, power loss, restore, and upgrades.
Identify the smallest reliable regression test for each major finding.

### Angle 10 — Architecture, maintainability, operations, and documentation

Review boundaries, dependency direction, ownership/lifecycle/global state,
scattered invariants, leakage, oversized components with concrete consequence,
dead/compatibility/flag complexity, unsafe configuration and destructive
workflows, telemetry/audit/runbooks, recovery/backup/upgrade guidance,
implementation mismatch, contributor reproducibility, licensing, release
procedures, compatibility constraints, and accessibility where user-facing.
Prefer concrete consequences over taste.

## R10. Deterministic extraction

Initialization preserves exact supplied bytes at:

```text
tooling/reference/source/contract.md
tooling/reference/source/reference-pack.md
```

It derives:

```text
observation-categories.md
schemas.md
specialist-result-schema.md
specialist-validation-schema.md
final-auditor-result-schema.md
risk-tiers.md
security-levels.md
defensive-assurance.md
mandatory-specialist-block.md
cross-component.md
finding-format.md
severity-confidence.md
handoff.md
angle-index.md
angle-01.md through angle-10.md
installation.md
manifest.json
```

A section file is the exact source byte range from its heading to the next
heading of equal or higher level. Angle index is the R9 heading and preamble;
each angle is its level-three section. Compact schemas are exact matching R2
level-three sections. The specialist validation extract includes its following
attempt-token explanation. The mandatory block is the exact bytes between its
unique marker lines, excluding markers and surrounding blank lines. Preserve
bytes without newline normalization.

`manifest.json` records `reviewSpecVersion`, `specEpoch`, preserved source
paths, byte sizes, and SHA-256 identities, plus every derived file's path,
source section, source byte start/end, byte size, and SHA-256 identity. It does
not list itself. `run.json` pins the active manifest identity and an immutable
copy of the initial manifest. Verification regenerates all ranges and compares
source, manifest, and installed bytes; coordinated edits to a preserved source
and extract cannot pass.

The preserved sources and installed extracts are immutable for the life of the
run. Every review gate re-verifies the preserved source manifest, not only the
active installation. Never overwrite the preserved sources; editing the
specification documents requires a new review.

## R11. Specification-version-2 efficiency records

### Orientation capsule

Store each immutable subsystem capsule beneath `assignments/capsules/` so its
bytes participate in the canonical state digest. A capsule records
`capsuleId`, `baselineContentSetHash`, `specEpoch`, `subsystem`, component
role, entry points, public boundaries, dependency seams, important
callers/callees, relevant tests, documentation, configuration, commands,
shared invariants, failure boundaries, evidence locations, and applicable
architecture/reference identities. Unit manifests reference the complete
capsule path and hash and do not duplicate shared orientation facts.

A capsule is an index, never proof. Specialists verify material claims against
the assigned baseline source. A changed baseline, specification epoch, or
shared orientation fact requires a successor capsule and affected successor
unit manifests.

The exact identity fields are `architectureHash` (the SHA-256 identity of
`architecture.md`) and `referenceManifestHash` (the SHA-256 identity of
`tooling/reference/manifest.json`). Every capsule list field is structurally
validated. Missing identity files, malformed capsules, and subsystem mismatches
are structural failures; only a genuine identity or epoch freshness failure
may be temporarily tolerated while the unit is `needs_revalidation`.

### Packet and attempt tooling

Use `review-tool packet` to build a deterministic packet from the immutable
attempt manifest, assigned-angle extracts, output schema, and capsule. Use
`review-tool attempt-init` to create an attempt-local result skeleton and
`review-tool attempt-check` before import. These commands do not modify
canonical state. Packet generation verifies every consumed extract against the
preserved Reference Pack. Attempt initialization, preflight, and import all
resolve the same sealed `outputDirectory`. They report capsules above 32 KiB
and packets above 128 KiB so shared orientation does not silently erase the
token-efficiency gain. A complete result inspects all assigned paths and
symbols, leaves `notInspected` and `remainingScope` empty, and supplies
substantive scope, locations, and a claim for every completed angle.

### Reviewer reuse

Every attempt uses `cold` reviewer reuse: each `reviewerPrincipalId` is an
opaque run-local identity used for exactly one attempt, and
`reviewerExecutionId` identifies that attempt. Warm-batch reuse is prohibited
in this environment because no stable reviewer lineage exists; the tool
rejects any `warm_batch` manifest.
Every conclusion must stand on current-assignment evidence and must not
reference prior attempt-local candidates or dispositions unless explicitly
assigned.
