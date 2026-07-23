# Security review levels

Version 0.1.1 introduced explicit security-review levels:

```text
off | low | medium | high
```

New reviews default to `off`. Security work is therefore opt-in rather than an
automatic consequence of running a full repository review.

## Why security review is controlled separately

An exhaustive code review and a security assessment are related, but they are
not the same activity. Security work can involve threat modelling, secret
discovery, malicious inputs, boundary probing, vulnerability reproduction, or
specialist scanning tools. Those activities may:

- require authority beyond ordinary source inspection;
- interact with credentials, services, or sensitive data;
- trigger cybersecurity safeguards in capable models or review environments;
- produce materially different risk and reporting expectations; and
- be inappropriate for a production or externally hosted target.

The levels make that intent explicit before workers are created. They give
users predictable control over review depth, keep workers within the same
boundary, and prevent repository contents or model capability from silently
expanding the review.

The default of `off` follows a least-authority principle: ordinary review can
proceed without automatically authorizing security analysis. It is a scope
choice, not a claim that the repository is secure.

## Choosing a level

| Level | Appropriate when | Security tools | Active security validation |
|---|---|---|---|
| `off` | You want an exhaustive non-security review | None | None |
| `low` | You want passive reasoning about security-sensitive source | None | None |
| `medium` | You also authorize local static security checks | Local static tools only | None |
| `high` | You also authorize defensive validation against isolated local fixtures | Local static tools | Non-destructive and isolated |

Use the lowest level that matches the intended review.

## `off`: security review excluded

At `off`, the workflow does not:

- create security-specific workers;
- perform threat modelling or a security review;
- assign the security and trust-boundaries review angle;
- run security scanners or security-focused dependency audits;
- enumerate secrets;
- construct malicious payloads or adversarial test cases;
- fuzz authentication, authorization, tenancy, parser, or trust boundaries; or
- reproduce or validate a suspected vulnerability.

Dedicated security-only paths are recorded as profile exclusions and are not
assigned for substantive review. Examples might include a security threat
model, a vulnerability-scanning harness, or security-review documentation.

Mixed-purpose files are handled more narrowly. A server module containing both
ordinary business logic and authorization checks is still reviewed for its
non-security behavior; the security properties are outside the declared scope.
Ordinary repository test suites remain allowed, but workers must not target,
expand, or reinterpret their security cases as security validation.

If a worker encounters an incidental security concern, it records only the
minimum location and deferral needed for traceability. It does not investigate,
elaborate, reproduce, or validate the concern.

Reports state:

```text
Security assessment: NOT PERFORMED
```

Any verdict applies only to the declared non-security scope.

## `low`: passive security review

`low` includes passive inspection and reasoning about security-sensitive
source. Workers may identify and report defensible security candidates, but
they do not run security tools or construct reproductions.

At `low`, workers must not:

- run SAST, security-focused CodeQL queries, secret scanners, or vulnerability
  audits;
- enumerate or extract secrets;
- construct malicious payloads;
- fuzz or probe a security boundary; or
- attempt to demonstrate exploitability.

Only ordinary validation is permitted.

## `medium`: local static security validation

`medium` includes `low` and permits repository-authorized, local static
security checks, including:

- SAST;
- CodeQL security queries;
- dependency vulnerability audits;
- secret scanning;
- static cryptography checks;
- static TLS and security-configuration checks; and
- similar checks that do not exercise a running target.

Discovered secrets must never be printed or copied. A report may retain only
the secret type, location, and a safe fingerprint.

Dynamic probing, adversarial requests, vulnerability reproduction, and
security fuzzing remain outside scope.

## `high`: active validation in an isolated environment

`high` includes `medium` and permits non-destructive dynamic validation only
against isolated local resources owned by the review, such as:

- temporary databases;
- disposable local fixtures;
- ephemeral services started for the review;
- synthetic accounts and credentials; and
- minimal defensive reproductions.

`high` is not unrestricted penetration testing. It does not authorize external
targets, production systems, real user data, persistence, destructive testing,
or open-ended network scanning.

## Boundaries that apply at every level

No security level authorizes:

- production services or externally hosted targets;
- use of real credentials, tokens, secret material, or user data;
- printing, copying, or disclosing discovered secrets;
- destructive actions or destructive test payloads;
- persistence or attempts to retain access;
- unrestricted network or port scanning;
- mutation of external services;
- bypassing an approval or sandbox boundary; or
- disguising security work as ordinary validation.

Increasing the level adds defensive review depth. It never relaxes these
boundaries.

## What counts as security work

Classification depends on the purpose and effect of the work, not only the
command or tool name.

| Work | Typical minimum level |
|---|---|
| Threat models, security reviews, or control inventories | `low` |
| Authentication, authorization, MFA, password reset, or account-recovery review | `low` |
| Tenant isolation, cross-account access, or privilege-boundary review | `low` |
| OIDC, TLS, cryptography, secret handling, or security-header review | `low` |
| CodeQL security queries, SAST, secret scanning, or dependency vulnerability audits | `medium` |
| Static cryptography, TLS, or security-configuration checks | `medium` |
| Security-focused fuzzing or malicious-input construction | `high` |
| Dynamic authorization bypass, transaction tampering, or vulnerability reproduction | `high` |
| ZAP or similar active scanning against an isolated local fixture | `high` |
| Ordinary functional tests that happen to cover an authentication module | `off`, provided they are not targeted or expanded as security tests |

A generic command does not make an activity ordinary. For example, using a
normal test runner to probe authorization bypasses is still active security
validation.

## How the boundary is enforced

The selected level is stored in the review's canonical state. Work-unit,
specialist-attempt, and final-audit manifests inherit both the level and an
ordered list of permitted validation classes:

| Level | Permitted validation classes |
|---|---|
| `off` | `ordinary` |
| `low` | `ordinary` |
| `medium` | `ordinary`, `security_static` |
| `high` | `ordinary`, `security_static`, `security_dynamic_isolated` |

The review utility checks those declarations and rejects mismatched manifests
or validation records whose declared class exceeds the run profile. At `off`,
it also rejects assignment of the security review angle and records
security-profile path exclusions and deferred observations explicitly.

The utility cannot reliably infer the intent of every arbitrary shell command.
Workers must classify validation by purpose and effect, and the skill expressly
forbids relabelling security work to bypass the selected level.

## Selecting the level

Users can state the level naturally:

```text
Run a complete review with security level medium.
```

Or pass it during review initialization:

```bash
skills/skill-code-review-full-on-uses-python/scripts/review-tool init \
  --review-dir code-reviews/20260723T120000Z \
  --contract skills/skill-code-review-full-on-uses-python/references/contract.md \
  --reference-pack skills/skill-code-review-full-on-uses-python/references/reference-pack.md \
  --security-level medium
```

Omitting the option creates a new `off` review.

## Resuming and changing levels

The level is immutable for one review run. Changing it requires a fresh run;
workers, repository contents, available tools, or model capability cannot
escalate it automatically.

Reviews created before security profiles existed retain their original `high`
behavior when resumed. This compatibility rule prevents an existing review
from silently changing scope partway through its lifecycle.

## Reporting an interruption

If a review stops or is blocked around security-related work:

1. Copy the [security-level interruption report
   prompt](SECURITY_LEVEL_REPORT_PROMPT.md).
2. Run it in the stopped task, or in a new task opened in the same repository.
3. Paste its Markdown output into the [security-level interruption issue
   form](https://github.com/Kevinjohn/skill-code-review-full-on-uses-python/issues/new?template=security-level-interruption.yml).
4. Attach a genuine, sanitized screenshot of the visible interruption.

The prompt is deliberately read-only. It gathers the recorded level, triggering
work, last visible agent activity, interruption, expected behavior, and
sanitized persisted state without retrying or deepening the security work.

## Important limitation

These levels govern what the skill intentionally assigns and validates. They do
not override the safety policies of a model, platform, tool, or execution
environment.

An `off` review is substantially less likely to request cybersecurity work, but
a safeguard may still react when ordinary review encounters authentication,
authorization, tenancy, privacy, cryptography, or similar code. Conversely,
selecting `medium` or `high` authorizes the skill's defined workflow but does
not guarantee that every model or environment will perform every permitted
activity.

Most importantly, `off` means that security was not assessed. It must never be
interpreted as evidence that no security defects exist.
