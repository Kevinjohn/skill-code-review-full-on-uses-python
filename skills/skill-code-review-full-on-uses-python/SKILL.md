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

## Start or resume safely

1. Capture the pre-artifact repository baseline before creating nonessential
   files. Include the commit plus staged, unstaged, deleted, renamed, symlink,
   submodule, and non-ignored untracked content. Default to a frozen baseline.
2. Resolve resumable work through `code-reviews/LATEST` and canonical
   `run.json` as the contract permits.
3. Establish the bundled utility with `scripts/review-tool --help` and a
   bounded self-test before relying on it.
4. Initialize a new review with:

   ```text
   scripts/review-tool init --review-dir <path> \
     --contract references/contract.md \
     --reference-pack references/reference-pack.md
   ```

   Initialization snapshots the editable specifications into the review and
   starts `SPEC-0001`; it does not require an external document signature.
5. Materialize the baseline and architecture in canonical state, construct
   semantic work units and immutable manifests, then run the representative
   pilot before repository-wide dispatch.

Use `scripts/review-tool check`, `mutate`, `import`, `import-audit`, `generate`,
and `audit` throughout. Use `--help` for exact interfaces. Treat generated
Markdown as views, never canonical state.

## Orchestrate complete coverage

Use the host's bounded specialist-agent mechanism when it exists and is
permitted. Reserve top-level capacity for architecture, assignments, imports,
validation, reconciliation, tail review, and audit. Send compact assignment
packets containing only assigned scope, immutable manifest identities,
relevant extracted references, output schemas, and the mandatory specialist
block. Never send the full contract, complete Reference Pack, conversation
history, or unrelated findings.

Persist partial evidence from interrupted attempts and reassign the exact
remaining paths, symbols, angles, and validations. An interruption is never an
exclusion, completion claim, or not-applicable rationale. When no specialist
mechanism exists, execute the same semantic units sequentially and record the
limitation honestly.

For every non-excluded baseline path, assign exactly one primary semantic work
unit. Apply all ten review angles to every unit. Require independent scoped
second review for each recorded Tier A requirement. Preserve every candidate,
including rejected, duplicate, unresolved, withdrawn, low-severity, test,
documentation, nit, suggestion, and question records. Continue after severe
findings. Run all seven phases, including cross-component reconciliation,
dedicated tail review, candidate validation, and independent final audit.

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
remaining work, and next action. Never claim inspection or tests prove the
absence of all defects.
