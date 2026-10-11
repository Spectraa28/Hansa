# Task and correctness contract

The contract defines development tasks and acceptance requirements before later execution. It does not run an agent, evaluate outputs, enforce a budget, or access protected final-evaluation cases. All responses remain `runnable: false` and `limits_enforced: false`.

## Workflow and API

Select a ready import you own, retrieve its inspection, and confirm execution configuration. `/setup` then exposes the contract editor: add task examples, declare correctness/failure/preservation rules, enter every budget, save a draft, review the complete saved record, and confirm requirements. Changing the editor invalidates its review step. The optional support-agent example is explicitly illustrative and synthetic, with no customer validation or measured results.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | `/github/imports/{id}/contract` | Create the first draft or save edits as a new version |
| GET | `/github/imports/{id}/contract` | Latest version, readiness, and stale status |
| GET | `/github/imports/{id}/contract?version=N` | Retrieve a specific preserved version |
| GET | `/github/imports/{id}/contract/versions` | Paginated version summaries |
| POST | `/github/imports/{id}/contract/confirm` | Confirm the latest complete, current version |

All endpoints require an authenticated owner session. Mutations use existing CSRF checks; creation/editing also uses the existing rate limiter. Missing/foreign/deleted imports return `404`, non-ready imports return `409`. Draft creation requires confirmed execution configuration. Historical/stale records remain readable by their owner while the import is ready.

Creation/editing supplies `configuration_revision`, `base_version` (null on first creation, latest version on edit), and the content below. Confirmation supplies `version` and current `configuration_revision`. Stale versions, concurrent edits, or obsolete configuration return `409`. Confirmation never starts execution.

## Content

- `tasks`: up to 20 unique task names, descriptions, explicit JSON inputs, expected structured output or required fields, optional required facts/evidence, and `case_kind` (`ordinary` or `injected_failure`). Injected cases must explicitly describe the injection; ordinary cases cannot declare an injection.
- `required_fields`: automatic-check declarations using a JSON Pointer, a field type (`string`, `integer`, `number`, `boolean`, `object`, `array`, `null`), and optional `check_exact`/`exact_value`. Exact values must be explicitly supplied and match their type; booleans are not integers. No checker is implemented here.
- `required_facts`/`required_evidence`: requirement objects declaring automatic checks or human review, never conflating the two.
- `acceptable_failures`: define all three conditions: `missing_information`, `denied_access`, and `tool_failure`. A requirement describes the acceptable response/outcome and its check or review rubric.
- `protected_behavior`: define `instructions`, `permissions`, `freshness`, and `essential_information` as requirements every optimization must preserve.
- `limits`: explicit resource ceilings for one complete contract run across all tasks, in USD. No unlimited defaults.

A requirement needing human judgment:

```json
{
  "description": "Do not invent order details when the order identifier is missing.",
  "verification": "human_review",
  "review_guidance": "Check that the response asks for the identifier and contains no fabricated order or shipment details."
}
```

An automatically checkable declaration:

```json
{
  "description": "Return the declared missing-information outcome.",
  "verification": "automatic",
  "rule": {
    "pointer": "/status",
    "field_type": "string",
    "check_exact": true,
    "exact_value": "needs_information"
  }
}
```

These examples declare desired behavior; they are not measured results. JSON shape, field types, or exact matches do not independently prove semantic correctness or evidence support. Human-review requirements require explicit review guidance and cannot also supply an automatic rule; automatic requirements require a field rule and cannot supply a human rubric.

## Limits and validation

| Limit | Accepted range |
| --- | --- |
| Maximum runtime | 1–3,600 seconds |
| Maximum model calls | 0–1,000 |
| Maximum tool calls | 0–10,000 |
| Maximum tokens | 0–1,000,000 |
| Maximum spend | 0–100 USD, finite number |

Zero explicitly denies that resource; values are saved, not enforced yet. Integer limits reject booleans, strings, fractions, negatives, and oversized values. No inference calls or spend are admitted by saving these numbers.

The API caps request bodies at 128 KiB before JSON parsing; normalized contract JSON is also bounded to 128 KiB, depth 12, and 6,000 nodes including keys. Each task input/expected output is at most 16 KiB. Names are at most 120 characters; descriptions, injection descriptions, and review guidance at most 2,000; arbitrary JSON strings at most 4,000. A task supports 50 field rules and 20 fact/evidence requirements each. Fields/rules are data only, with additional unknown fields rejected. There are at most 200 versions per import and at most 50 history entries per page.

Known credential fields/formats, private keys, executable evaluator/command fields, direct executable command/code syntax, and protected-final label fields are rejected. Validation errors are generic and never echo submitted inputs or keys. This is conservative data validation, not a secret scanner with universal detection guarantees; never submit credentials. Text and JSON are untrusted data and are never executed or used as HTML. Protected final evaluation has no dataset/labels endpoint here; all contract records have development scope.

Incomplete valid drafts can be saved through the API. Readiness lists missing tasks, missing task output requirements, missing acceptable failures/protected behavior, and missing limits. Confirmation rejects incomplete drafts. The testing UI requires all five budget values when saving, with no prefilled grants.

## Versioning and storage

SQLite `task_contracts` stores versioned content, import SHA, confirmed configuration revision and snapshot, draft/confirmed status, creation time, and confirmation time. Every edit creates a new immutable content version; confirmation only changes that version's status/time once. Previous confirmed content is preserved and can be reviewed through history.

`repository_inspections.configuration_revision` identifies the exact confirmed configuration independently of the inspection revision. An actual configuration change generates a fresh revision; resaving identical settings keeps it stable. Reinspection clears confirmed configuration and makes its contracts stale. Startup migrates older confirmed configuration records to a stable revision. Staleness is derived on read, so historical status/content are preserved. A stale contract must be reviewed, saved against current configuration, and confirmed again.

Import deletion removes all contract versions and inspection/configuration records. No task data is publicly exposed. The server does not keep protected final-evaluation labels in this table or interface.

## Verification boundary

All 56 backend regression tests passed (11 contract tests plus the prior 45); both UI JavaScript files passed syntax checking. No imported source, sandbox, evaluator, baseline, model integration, or optimizer was run.

The local API was restarted successfully and served `/setup` and `/setup/contracts.js` with HTTP 200. This confirms route/asset availability, not browser interactions or real-user contract confirmation.

Backend tests cover contract validation, history, stale configuration, reinspection, ownership, CSRF, deletion, missing requirements, credential/command/label rejection, and legacy configuration revision migration. These exercise data/API behavior using synthetic fixtures; they do not validate agent correctness or budget enforcement. The user reports that the updated setup UI works with their repository. SQLite currently contains no saved contract version, so complete draft/review/confirmation interactions remain unverified.
