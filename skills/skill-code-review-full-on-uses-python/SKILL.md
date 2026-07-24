---
name: skill-code-review-full-on-uses-python
description: Run or resume an exhaustive, evidence-backed review of an entire repository. Use when the user explicitly requests complete repository coverage, a full-on code review, a comprehensive repository audit, database review where applicable, specialist review waves, validation, reconciliation, dedicated tail review, and independent final audit. Do not use for ordinary pull-request, diff-only, quick, severity-limited, or narrowly scoped reviews.
---

# Run an exhaustive repository review

Treat the directory containing this file as the Skill root. Resolve
`references/contract.md`, `references/reference-pack.md`, and
`scripts/review-tool` relative to it. Never assume an installation path.

Begin execution immediately. Do not stop after proposing a plan.

## Load authority

1. Read every applicable instruction file in the target repository.
2. Read `references/contract.md` completely before substantive inspection.
3. Route into `references/reference-pack.md` by phase. Load every applicable
   schema or checklist before using it. Treat the contract as behavioral
authority and the Reference Pack as schema, checklist, and reporting
authority. Mandatory clauses are not optional guidance.
4. Require review specification version 2. If canonical state uses another
   version, stop with the tool's re-initialization diagnostic.

## Declare the real runtime

Record exactly one runtime capability:

- `continuous`: the current controller can run sequential waves and survive
  context management;
- `persistent_task`: the host provides a real durable task or equivalent;
- `external_supervisor`: an actual supervisor will reinvoke the orchestrator
  from persisted state; or
- `none`: automatic continuation is unavailable.

Do not infer persistence from these instructions. Default to `none` unless the
runtime explicitly establishes a stronger capability. If the user explicitly
requests a durable task and the host supports one, create it before substantive
inspection. Otherwise do not pretend the Skill creates persistence.

## Resolve security level

Resolve exactly one level before architecture mapping or worker creation:

- `off` (default): exclude security review and security validation;
- `low`: passive security source review only;
- `medium`: include local static security validation;
- `high`: include active validation only in isolated local review-owned
  environments.

Accept `--security-level off|low|medium|high` or an equivalent explicit
natural-language request. Do not ask when omitted; use `off`. Never infer or
increase the level from repository contents, available tools, model capability,
or worker output. Read the Reference Pack security-level and defensive-assurance
extracts before constructing paths, units, manifests, or packets when they
exist.

## Start or resume safely

1. Capture the pre-artifact repository baseline before creating nonessential
   files. Include the commit plus staged, unstaged, deleted, renamed, symlink,
   submodule, and non-ignored untracked content. Default to a frozen baseline.
2. Resolve resumable work through `code-reviews/LATEST` and canonical
   `run.json` as the contract permits. Treat security level as part of run
   compatibility. A different level requires a fresh run.
3. Establish the bundled utility with `scripts/review-tool --help` and a
   bounded self-test before relying on it.
4. Initialize a new review with:

   ```text
   scripts/review-tool init --review-dir <path> \
     --contract references/contract.md \
     --reference-pack references/reference-pack.md \
     --security-level <off|low|medium|high>
   ```

   Initialization snapshots the editable specifications into the review and
   starts `SPEC-0001`; it does not require an external document signature.
5. Materialize the baseline and architecture in canonical state, construct
   cohesive semantic work units, immutable subsystem orientation capsules, and
   manifests, then run the representative
   pilot through the same adapter, argument boundary, packet path, result
   persistence, and import path intended for repository-wide dispatch. A pilot
   dispatch failure blocks scaling.

Use `scripts/review-tool check`, `mutate`, `packet`, `attempt-init`,
`attempt-check`, `import`, `import-audit`, `generate`, and `audit` throughout.
Use `--help` for exact interfaces. Treat generated Markdown as views, never
canonical state. Never publish model, host-task, or thread metadata.

## Orchestrate complete coverage

Use the host's bounded specialist-agent mechanism when it exists and is
permitted. Reserve top-level capacity for architecture, assignments, imports,
validation, reconciliation, tail review, and audit. Send compact assignment
packets containing only assigned scope, immutable manifest identities,
the inherited security level and permitted validation classes, relevant
extracted references, output schemas, and the mandatory specialist block.
Never send the full contract, complete Reference Pack, conversation history,
or unrelated findings.

For specification version 2, mechanically generate packets from immutable
assigned-angle extracts and the unit's hashed subsystem orientation capsule.
Use the capsule as an index and verify material claims against source. Keep
shared orientation facts in the capsule only. After persisting `result.json`,
return only a compact status/path/counts/remaining-scope receipt.
Treat packet or capsule size warnings as pilot calibration failures: remove
duplicated orientation or narrow the assignment before scaling.

Keep a stable opaque reviewer principal distinct from each attempt execution
identity. Use cold independent reviewers unless the host genuinely exposes
stable reviewer lineage. Only then may one principal process a bounded warm
batch of closely related requirements; every requirement retains a separate
manifest and result and must stand on current-assignment evidence.

Keep the default reviewer configuration uniform until equivalent-scope
benchmarks demonstrate comparable quality. Any later experiment routes by task
capability, not tier alone: architecture mapping, tier assignment, validation,
reconciliation, tail review, and final audit can all require strong semantic
reasoning. Record only neutral configuration classes in publishable state.

Fail closed at every dispatch boundary. Explicitly parse and validate assignment
input; reject missing, malformed, unintentionally empty, duplicate, or unknown
work identities instead of defaulting to an empty list. Record the intended
identities and count, reconcile scheduled and started identities, and treat
zero scheduled or started specialists for a non-empty intended wave as failure.
Allow an empty wave only when canonical state proves there is no executable
work and preserve the no-op reason.

At `low`, `medium`, or `high`, describe defensive work as concrete component
invariants using `defensive-assurance.md`. Prefer titles such as
`Persistence layer — statement/data separation and account ownership` over a
broad category label. State expected invariants, authorized evidence, permitted
validation, and prohibited actions. Preserve the exact security level and
validation class; the taxonomy clarifies purpose and never changes
classification. Do not build a prohibited-word list, conceal intent, or
rephrase and retry work after a policy refusal.

Persist partial evidence from interrupted attempts and reassign the exact
remaining paths, symbols, angles, and validations. An interruption is never an
exclusion, completion claim, or not-applicable rationale. When no specialist
mechanism exists, execute the same semantic units sequentially and record the
limitation honestly.

For every non-excluded baseline path, assign exactly one primary semantic work
unit. Keep all ten angle states, but at level `off` exclude dedicated
security-only paths, pre-disposition Angle 5 as `excluded_by_profile`, and omit
it from worker assignments. Review mixed paths through the remaining angles.
Do not create, retry, or reassign security work at level `off`; minimally defer
an incidental security candidate and continue with non-security scope. Require
independent scoped second review for each profile-permitted Tier A requirement.
Avoid fragmentation driven only by parallelism. During the pilot, challenge
tiny units and high Tier A density, require structured critical reasons, and
rerun affected pilot scope whenever calibration changes manifests or packets.
Preserve every in-profile candidate, including rejected, duplicate, unresolved,
withdrawn, low-severity, test, documentation, nit, suggestion, and question
records. Continue after severe findings. Run all seven phases, including
cross-component reconciliation, dedicated tail review, candidate validation,
and independent final audit.

## Preserve read-only scope

Do not edit the reviewed repository's source, tests, configuration,
documentation, generated source, lockfiles, or metadata. Write only authorized
review state, reports, tooling, and isolated validation artifacts. Run safe,
documented, non-destructive validation. Do not push, publish, open issues or
pull requests, contact external parties, or mutate external services.

## Continue to a valid boundary

Treat context limits, invocation endings, wave boundaries, specialist
interruptions, and finding volume as scheduling boundaries. Continue
automatically while the declared runtime supports it and executable work
remains. Otherwise generate current views and a mechanically valid paused
checkpoint with exact remaining scope and next actions.

Issue a terminal repository-wide verdict only when the full-completion or
terminal-incomplete-handoff gate permits it. Label all earlier communication as
a checkpoint, not release clearance. State reviewed revision, scope, status,
security level, remaining work, and next action. At level `off`, label security
assessment `NOT PERFORMED`, report completion with the declared security
exclusion, and qualify every verdict as applying only to the non-security
scope. Never claim inspection or tests prove the absence of all defects.
