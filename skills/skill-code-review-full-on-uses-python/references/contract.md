# Exhaustive Repository Review — Orchestrator Contract

Contract version: 1. This is the behavioral authority for an exhaustive,
evidence-backed review. The companion Reference Pack supplies schemas,
checklists, and report rules. Both documents are editable sources. At review
initialization, preserve their current bytes inside the review and use those
copies for the current specification epoch. No external signature or expected
document digest governs their authority.

This is a read-only review of repository content. Only review records, reports,
tooling, and isolated validation artifacts are authorized writes. Determine
database applicability from evidence and apply database-specific analysis only
where relevant.

## 1. Required outcome

Inspect the complete repository within the declared security profile, account
for every path, apply every profile-required angle at semantic granularity,
preserve every in-scope observation, validate every in-scope candidate, and
report every validated issue. Never curate by severity, count, convenience, or
output length.

Completeness requires exactly one primary work unit for every non-excluded
path; ten angle dispositions per unit, including the explicit profile
disposition for excluded security scope; all recorded critical second reviews;
disposition of every observation and validation; explicit exceptions; and no
open material final-audit objection. Completeness never proves that no
undiscovered defect exists.

## 2. Runtime and lifecycle

The harness declares `continuous`, `persistent_task`, `external_supervisor`, or
`none`. Default to `none`; instructions cannot create persistence. Use
`active`, `paused`, `concluded`, or `superseded` for `run.json.status`.

Legal transitions are `active -> paused|concluded|superseded`,
`paused -> active|concluded|superseded`, and same-state evidence-bearing
checkpoints. `concluded` and `superseded` are terminal. Invocation, context,
wave, interruption, and budget boundaries do not imply completion. A failed
completion audit returns items to work.

A pause preserves exact pending, partial, blocked, and revalidation scope;
open observations and validations; reconciled and unreconciled attempts; next
actions; and the condition needed to resume. A terminal incomplete handoff is
allowed only by explicit user authority or when every remaining material item
has a documented external blocker and no independent authorized work remains.

Record any user or host review budget before inspection. Reaching it pauses the
review without changing scope or fabricating exclusions.

## 2A. Security profile

Resolve exactly one security level before architecture mapping or worker
creation: `off`, `low`, `medium`, or `high`. Default to `off` when the user
does not select one. Persist the level and whether it came from the default or
the user. A repository, available tool, worker, model, or prior instruction
cannot increase it.

Apply the Reference Pack profile exactly. At `off`, exclude dedicated
security-only paths with evidence, review mixed paths only for non-security
concerns, pre-disposition Angle 5 as `excluded_by_profile`, and do not create or
retry security work. At `low`, allow passive security review only. At `medium`,
allow static local security validation. At `high`, allow active validation only
in isolated local review-owned environments. Every level prohibits external
targets, production services, use of real credentials or secret material,
destructive action, persistence, unrestricted network scanning, and
external-service mutation.

Treat a missing profile in a run created before this feature as legacy `high`
to preserve its original scope. The level is immutable within one run. A
different requested level requires a fresh run; never silently widen or narrow
an existing run.

## 3. Review directory and resume

Resolve resumable work through `code-reviews/LATEST`, then scan matching
`code-reviews/*/run.json` records. Prefer the newest matching active review;
resume a paused review only with the missing continuation, authority, budget,
or explicit request. Security level is part of review compatibility. Do not
merge simultaneous reviews or resume one at a different security level. A
requested fresh review supersedes an earlier matching run.

Create new reviews at a shell-derived UTC path under `code-reviews/`. Keep
`LATEST` as a repository-relative convenience pointer; canonical repository
identity and lifecycle state are authoritative. No other report location is
authorized.

## 4. Baseline and epochs

Before substantive inspection, record repository identity, branch state,
commit, staged and unstaged changes, deletions, renames, non-ignored untracked
paths, symlinks, submodules, instructions, toolchains, timestamp, and target
policy. Default to `frozen_baseline`, including the exact dirty tree. Preserve
binary-safe content identities, diffs and metadata under `baseline/`; avoid
copying secrets or unsuitable large artifacts.

At security level `off`, identify dedicated security-only paths by concrete
purpose and boundary evidence and classify them as `security_profile`
exclusions using path metadata, documented purpose, and the minimum content
needed to establish the boundary. Do not substantively inspect excluded paths
for security properties. Do not infer that an entire mixed-purpose
implementation path is security-only merely because it contains authentication,
authorization, privacy, tenancy, cryptography, or transport behavior.

Use `explicit_moving_target` only on explicit request. Each accepted content
change creates a revision epoch, returns affected units to revalidation, and
requires a final cutoff. On resume, never attach evidence to changed content.

## 5. Specification epochs

Initialization copies the supplied `contract.md` and `reference-pack.md` to
`tooling/reference/source/`, records `reviewSpecVersion`, `SPEC-0001`, original
relative paths, preserved paths, and initialization time, then derives the
Reference Pack extracts mechanically.

An explicit specification migration increments `specEpoch`, preserves new
source bytes under a migration directory, records changed sections and affected
angles, creates successor unit manifests, and marks affected dispositions
`needs_revalidation`. Shared-schema or shared-rule changes revalidate whole
units. Every angle disposition and attempt manifest records its `specEpoch`.
Source-document editability never depends on regenerating an approval digest.

## 6. Canonical state and integrity

Canonical state consists of `run.json`, `paths.jsonl`, `work-units.jsonl`,
`observations.jsonl`, `validations.jsonl`, `audit-objections.jsonl`,
`architecture.md`, and `assignments/`. Generated Markdown and
`report-manifest.json` are derived views. `state-events.jsonl`, `baseline/`,
`agents/`, and `tooling/` are outside the state digest; relevant raw artifacts
are sealed by identities imported into canonical records.

Use `review-tool` for all canonical changes. State mutations require the
expected pre-state digest, validate the complete proposed state, stage a full
replacement set inside the review directory, fsync when supported, write a
commit marker, materialize idempotently, append the event, and write a
completion marker. Recover committed incomplete transactions by roll-forward;
quarantine uncommitted staging. Identifiers become permanent only at commit.

Hash-linked state events record operation, actor, timestamp, pre/post digests,
and targets. Digests here protect a particular run's repository content,
canonical state, transactions, raw results, validations, audit sample, and
reports; they do not restrict editing the Skill documentation.

Every canonical mutation makes generated views stale. Regenerate once per
bounded batch and before any audit, checkpoint, pause, or terminal response.

## 7. Permanent identifiers and imports

Only the orchestrator mints permanent identifiers inside transactions.
Specialists use `CAND-A<n>-NNN` and `AVAL-A<n>-NNN`; final auditors use
`AAOB-A<n>-NNN`. Imports allocate sequential, gapless `OBS-NNNNNN`,
`VAL-NNNNNN`, and `AOB-NNNNNN`. A validated P0–P4 finding receives sequential
`DBR-NNNN` only on its later validation transition. Never reuse or renumber an
identifier; withdrawals retain original identifiers and severity.

`import` atomically consumes one attempt's `result.json` and
`validations.jsonl`, verifies immutable assignment metadata, rewrites all local
references, imports every candidate initially as open, derives valid structured
second-review completion, and preserves raw output. `import-audit` applies the
same rules to objections, candidates, validations, reviewer identity, and
sampled scope. Failure imports nothing and allocates no identifiers.

## 8. Semantic work units

Create cohesive units around behavior and invariants: packages, interfaces,
transaction or recovery paths, protocols, trust boundaries, platform
implementations, generators, tests, documentation, or release subsystems. Do
not group unrelated files or split an invariant without an integrator.

Classify units Tier A, B, or C using the Reference Pack. Tier A is normally at
most 20 production files or 8,000 implementation lines; Tier B at most 50 or
20,000; Tier C remains cohesive and bounded. Justify exceptions before
assignment.

Every immutable unit manifest records content identities, risk, size, security
level, permitted validation classes, ten angle states, profile-required
dispositions, `reviewSpecVersion`, `specEpoch`, and authoritative
`requiredSecondReviews`. For unchanged content, successor manifests may only
add or widen requirements. Every dispatch has an immutable attempt manifest
with exact scope, security level, permitted validation classes, reviewer
execution identity, packet type, manifest identity, and specification epoch.

Second review begins only after intersecting primary scope is sealed. Record a
primary-evidence-set identity and require a distinguishable reviewer execution
identity. Whole-unit requirements require whole-unit coverage; item scope
requires a typed superset. Later intersecting primary evidence invalidates the
completion and returns the unit to revalidation.

Partial or interrupted work preserves usable evidence, records exact remainder,
and creates a new attempt. It never becomes an exclusion or not-applicable
disposition. Run a representative pilot of about 100 paths, or the whole
repository when smaller, before scaling. Exercise tool recovery, import,
generation, audit, packet clarity, evidence quality, and bookkeeping ratio.

A security-only remainder at level `off` is different: record it as
profile-excluded or `deferred_by_profile`, preserve completed non-security
evidence, and do not reassign it. Never turn a worker policy stoppage into an
automatic increase of security level.

## 9. Specialist coordination

The orchestrator is the only canonical writer. Specialists write only their
assigned `agents/WORK-NNNN/ATTEMPT-NNNN/` directory; the final auditor writes
only `agents/FINAL-AUDIT/ATTEMPT-NNNN/`. Import raw persisted results; never
reconstruct evidence from chat summaries.

Send compact packets with repository and baseline identity, exact scope,
immutable manifest paths and identities, reviewer execution identity, relevant
reference extracts, security level, permitted validation classes, constraints,
output schema, and the mandatory specialist block. Exclude the full governing
documents, unrelated findings, other ledgers, conversation history, and
orchestration mechanics.

Read imported ledgers and results fully, challenge optimistic completion,
validate identities, and schedule without starving tests, SDKs, platforms,
release paths, documentation, accessibility, or low-severity review.

## 10. Seven phases

1. **Baseline, architecture, and tooling:** read instructions and project
   promises; capture the pre-artifact baseline; initialize and self-test the
   utility; materialize paths; identify languages, systems, APIs, persistence,
   trust, concurrency, platforms, release machinery, and database
   applicability; construct units and run the pilot.
2. **Semantic work-unit review:** disposition all ten angles for every unit,
   using the explicit profile exclusion for Angle 5 at level `off`, and
   complete each profile-permitted Tier A requirement across as many bounded
   waves as needed.
3. **Ongoing validation:** safely run repository-documented static, test,
   concurrency, fuzz, fault, recovery, compatibility, packaging, example,
   documentation, and focused performance checks when relevant and permitted
   by the security level. Classify every command by its purpose and effect as
   `ordinary`, `security_static`, or `security_dynamic_isolated`; never label
   security work `ordinary` to bypass the profile. The utility rejects a
   declared class not permitted by the run profile. Record tree state before
   and after. Stop a command that mutates tracked content and preserve user
   changes.
4. **Cross-component reconciliation:** apply the Reference Pack integration
   checklist once primary coverage is substantially complete.
5. **Dedicated tail review:** explicitly cover P3/P4 defects, defensive gaps,
   brittle tests, SDKs, examples, platforms, builds, packaging, release,
   documentation, observability, operations, accessibility, maintainability,
   localized performance, compatibility, nits, suggestions, and questions.
6. **Candidate validation and deduplication:** for in-profile candidates, trace
   reachability, guards, cleanup, tests, and promises; establish trigger,
   expected/actual behavior, impact, likelihood, and blast radius; challenge
   counterarguments; preserve rejection reasons; merge only shared root cause
   and remediation. At level `off`, minimally record an incidentally noticed
   security candidate as `deferred_by_profile` without developing or validating
   it.
7. **Final reconciliation and independent audit:** require no actionable unit,
   open observation, or unreconciled interruption; reconcile paths, identities,
   manifests, angles, second reviews, findings, tail work, and reports; then
   run and import a bounded independent final audit.

Never invent code, lines, behavior, output, guarantees, versions,
exploitability, measurements, or test results. Passing tests never prove
correctness.

## 11. Independent final audit

Use an execution identity different from every contributor to sampled evidence.
The auditor reproduces mechanical and report identities; checks baseline and
exclusions, including every security-profile exclusion; verifies security
level inheritance and validation classes; inspects all in-profile Tier A units,
second reviews, material blockers, P0/P1 findings, and representative
not-applicable/exclusion classes; and checks a deterministic risk-stratified
sample of remaining completed units.

At level `off`, audit a security-profile exclusion through its canonical
record, non-assignment, and boundary evidence. Do not reopen the excluded
security review or inspect the path for security properties.

For `N` eligible non-Tier-A units, sample
`min(N, audit_cap, max(25, ceil(0.01*N)))`, with default `audit_cap=200`. Use the
baseline content-set and final work-unit-set identities as the seed. Sampling
supplements, never replaces, primary semantic coverage. Import every objection,
return affected scope to work, regenerate, and repeat until no open material
objection remains.

## 12. Gates and verdicts

The checkpoint audit requires valid canonical syntax, references, content
identity, event chain, recovered transactions, current generated views,
preserved unfinished scope, and exact next actions. It emits active or paused
state and is not release clearance.

The full completion audit requires complete path partitioning; explicit valid
exclusions; completed bounded units; ten semantic dispositions each; current
specification epoch; complete and independent second reviews; authoritative
manifests; reconciled attempts; dispositioned observations and validations;
gapless identifiers; completed architecture, cross-component, tail,
validation, reconciliation, and independent-audit phases; current reports; no
open material objection; valid security-profile inheritance, exclusions, angle
dispositions, and validation classes; and verdict consistency.

The incomplete-handoff audit requires a positive number of unfinished material
items, a valid external blocker for each, no unblocked independent action, and
the exact operator or environment action required. Explicit user authority may
instead permit an early terminal handoff without mislabeling items as blocked.

Verdicts are `BLOCK`, `MAJOR CHANGES REQUIRED`, `CHANGES REQUIRED`,
`CONDITIONAL PASS`, `PASS`, and `INCOMPLETE REVIEW`. `PASS` requires no material
finding, unresolved material observation, or verification gap.
`CONDITIONAL PASS` permits only evidenced non-material unavailable
verification. Passing language always requires the full completion gate. No
release-clearance language accompanies a non-passing verdict.

Every verdict is scoped to the recorded security level. At level `off`, report
completion as `COMPLETE_WITH_DECLARED_SECURITY_EXCLUSION`, label the security
assessment `NOT PERFORMED`, qualify any verdict as applying only to the declared
non-security scope, and never use unqualified overall-pass or release-clearance
language.

## 13. Communication and final integrity

An active checkpoint keeps `active`; a paused checkpoint sets `paused` and
states exact resume needs; a terminal handoff sets `concluded`, records a
shell-derived UTC time, regenerates, reruns the applicable audit, and links the
generated review README.

Before terminal handoff, mechanically answer whether: every path has correct
ownership; every unit has ten dispositions; Tier A requirements are current
and independent; every observation is traceable; no reviewer stopped after
"enough" issues; interruptions are reconciled; tail categories were not
starved; exclusions and non-applicability are evidenced; reports are current;
the security level is inherited without escalation and profile exclusions are
honest; the independent audit is reconciled; lifecycle and verdict are
gate-supported; and final language avoids claiming proof of defect absence.
Any required "no" returns the item to work, an honest pause, or the valid
incomplete process.
