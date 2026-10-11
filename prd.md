# PRD: Autonomous Agent Optimization Engineer

Prepared: October 10, 2026. Working product description; final branding is undecided.

Status: the prior 37 authentication/import tests passed after user authorization on October 10, 2026. Local authentication startup and real GitHub sign-in succeeded. The App key was saved and validated; live App authorization and fixed-commit imports remain unverified. Repository inspection and a testing UI are now written, with new tests unrun pending authorization. See [README.md](README.md), [GITHUB_IMPORT.md](backend/docs/GITHUB_IMPORT.md), and [REPOSITORY_INSPECTION.md](backend/docs/REPOSITORY_INSPECTION.md). Google sign-in, optimizer, agent sandbox, hosted execution, measured improvement, and customer validation remain unimplemented or unverified. Read [hackathon.md](hackathon.md) for event rules and submission requirements.

Build preparation: the user has requested implementation and will supply paid model API access later. Authentication and import code exist; bounded static inspection and configuration confirmation with a simple testing UI are now written. This step is untested pending user authorization; see [REPOSITORY_INSPECTION.md](backend/docs/REPOSITORY_INSPECTION.md). The saved App key was validated and the connector enabled, but live connection/import testing is deferred. Read [SPONSORS.md](SPONSORS.md) for the initial integration plan. Agent execution and sponsor outputs remain unverified.

Architecture discussion: [ARCHITECTURE.md](backend/docs/ARCHITECTURE.md) records the proposed Python/FastAPI backend, separate worker, execution boundaries, durable accounting, automatic setup journey, and later React/TypeScript frontend. It is a discussion draft; dependency versions and runtime behavior remain unverified.

## 1. Product definition

An autonomous optimization engineer for AI agents. It investigates context, memory and orchestration bottlenecks, tests targeted changes against the user's tasks, and delivers a patch showing what improved, what regressed and whether the change is worth adopting.

The user delegates the experimentation loop:

> Inspect execution → form a hypothesis → change code → rerun tasks → investigate regressions → compare results → keep or reject the change.

Our product owns that loop within declared permissions and a budget. The user supplies the agent, requirements and optimization goal, then reviews the result. We do not promise universal improvement, unchanged quality on every possible input or a fixed savings percentage.

### What the user has defined

- Bring an agent and provide permitted access to its code.
- Investigate expensive operations, bottlenecks, context and memory handling.
- Show an initial report and offer actionable optimization goals.
- After the user selects a goal, autonomously edit the implementation and evaluate it.
- Return improvements, regressions and a reviewable patch.
- Remove the headache of repeatedly supervising a coding assistant through small experiments.

Cost is the initial measurable focus. Latency, output validity and task reliability are additional objectives or constraints. The prototype recommendations below narrow supported environments; they do not replace the complete product journey with a report-only tool.

## 2. Who benefits and why

Proposed customer: an AI product developer or small team operating an editable workflow repeatedly. Today they manually connect traces to code, hypothesize changes, run tests, examine failures and decide whether an optimization is safe.

The value is reduced manual experimentation and a usable implementation backed by evidence. A customer with tiny usage, no reproducible environment or no meaningful acceptance criteria may not benefit. Payment intent, customer demand and advantage over existing tools remain unvalidated.

Positioning should emphasize completing the engineering work. “Apply best practices” is too generic: a practice must demonstrate benefit on this workflow. “100 iterations for 1% improvement” was conversational framing, not a measured claim to publish.

## 3. What is actually the agent?

Our optimizer is the agent. The user's existing agent is the software under investigation.

| Actor | Responsibility |
| --- | --- |
| User | Provide the workflow, task requirements, allowed changes and budget; choose a goal; review delivery |
| Our optimizer agent | Decide what to inspect, which hypotheses to test, what code to change and how to respond to results |
| User's original/candidate agent | Execute the actual task using its existing framework, models and tools |
| Runner, verifier and ledger | Execute commands, enforce boundaries, measure activity and check results independently |
| Website | Let the visitor initiate work, inspect evidence and obtain artifacts |

An illustrative autonomous sequence: investigate repeated supervisor calls; identify a bounded routing decision; replace that decision with conventional code; discover an ambiguous case fails; add a selective model fallback; rerun; retain or reject based on evidence. This sequence is an example, not a scripted demonstration or observed result.

If the implementation only displays expensive calls, recommends shorter prompts and executes predefined tweaks, it has not fulfilled this PRD. The optimizer must make consequential, source-aware decisions and use execution feedback to change its plan.

## 4. Inputs and onboarding

Implemented task-contract stage: [TASK_CONTRACT.md](backend/docs/TASK_CONTRACT.md) defines development tasks, correctness criteria, saved resource limits, version history, and configuration staleness. All 56 backend tests passed; contract browser interactions and agent execution remain unverified. Requirements are saved declarations, not measured correctness or enforced execution guarantees.

Code access alone is insufficient. A supported workflow must provide:

| Input | Purpose |
| --- | --- |
| Owned/permitted source revision | Reproducible original implementation and editable-file boundary |
| Entrypoint and adapter | Known invocation and structured task/result interface |
| Declared dependencies and runtime | Reproducible execution in an approved environment |
| Test inputs and task requirements | Establish what correct behavior means |
| Tool configuration and test accounts | Exercise supported behavior without production side effects |
| Model access | Actual API access for original, candidate and optimizer execution |
| Optimization goal and constraints | Define cost/latency objective and protected behavior |
| Experiment limits | Bound trials, calls, tokens, runtime and total spend |

Historical traces may help investigation, but fresh runs are needed to establish a comparable baseline. Missing fields are reported as onboarding blockers rather than silently guessed.

The adapter is built or reviewed once per supported repository. We do not claim automatic compatibility with every agent framework. Keep secrets separate from source, reports, public traces and browser inputs.

## 5. Complete product journey

1. **Connect a supported workflow.** Inspect its source revision, execution contract, dependencies and permitted tools. Validate readiness.
2. **Establish the original.** Run approved tasks; show outputs, correctness, calls, context usage, latency and estimated expense.
3. **Present findings.** Link each suspected bottleneck to source and execution evidence. Clearly distinguish observations from hypotheses.
4. **Choose a goal.** User selects a supported objective and requirements, approves the editable boundary and sets the experiment budget.
5. **Optimize autonomously.** Agent inspects, edits isolated candidates, runs experiments and responds to failures without needing approval for every permitted local change.
6. **Inspect experiments.** Visitor sees actual tool events, concise decision rationales, diffs, failed checks and consumed budget.
7. **Verify delivery.** Freeze the selected candidate and run the final protected comparison.
8. **Export.** Deliver patch, source hashes, evaluation report, unresolved cases, expense assumptions and reproduction instructions. If no acceptable useful change exists, return that conclusion explicitly.

Approval of an optimization goal does not authorize pushing to the user's repository, merging changes or modifying production. Those are separate actions outside the first prototype.

## 6. Recommended hackathon scope

This is a proposed implementation boundary, not an organizer requirement or user-approved stack.

- One supported Python invocation contract: JSON task in, structured result out.
- One reasonable representative workflow and a reviewed adapter.
- One tool-using optimizer; ordinary code handles state, money, validation and execution controls.
- Initial changes focus on context/memory handoffs and one meaningful orchestration pattern.
- Other goals may appear as measured findings, but do not advertise unsupported automatic transformations.
- Full hosted input-to-patch journey, real experiments and usable artifacts.
- Public demo executes approved workflows. Broad, unreviewed repository uploads are deferred until a validated isolation and dependency design exists.

Potential changes include task-specific state instead of full-history relay, eliminating demonstrably redundant context, avoiding repeated retrieval when freshness permits, narrowing a bounded model decision, or revising retries based on actual errors. Preserve instructions, essential facts, freshness, validation and permission separation.

Output-schema checks can detect malformed results. General semantic improvement of arbitrary outputs is not assumed merely because JSON is valid. Parallelization is only appropriate when dependencies, rate limits and side effects permit it.

The target workflow has not been selected. An email-thread-to-record task with later amendments is one possible bounded benchmark, not a confirmed customer domain. Do not manufacture a wasteful multi-agent baseline to produce impressive savings.

## 7. Execution: how the existing agent runs

The supported workflow remains a normal program using its own framework. A thin adapter standardizes invocation. A proposed local interface is:

```text
controller sends task JSON
    → isolated process executes runner.py
    → adapter invokes the existing agent
    → existing agent makes permitted model/tool calls
    → process returns structured output and execution evidence
```

For an approved Python adapter, `python runner.py < task.json` illustrates invocation. It is not an existing executable or a framework API. Structured output and diagnostic logs need separate channels so logs do not corrupt the result.

For each experiment:

1. Materialize the original or candidate at an immutable revision in an isolated workspace.
2. Use a pre-approved dependency image; do not run customer-controlled builds in the controller.
3. Supply only allowed task inputs, scoped permissions and broker access.
4. Enforce execution limits and capture actual outputs, failures and usage.
5. Send results to an evaluator outside the candidate's editable/execution boundary.
6. Store the result and expense before the optimizer chooses its next action.

The original and candidate execute the same task distribution with comparable tools, model availability and cache policy. Only the candidate implementation changes unless an experiment explicitly declares another variable.

The supplied AWS/Aivar rules permit one EC2 instance in the existing `Hackathon_VPC`, in `us-east-1`, with each EBS volume at most 50 GB. ECS/Fargate is outside the approved-service list. Plan a single-host demo with bounded containers for reviewed workflows and one active optimization job. A normal container on a shared VM does not establish a safe platform for arbitrary third-party code; general repository execution requires a separately validated isolation design. See [SPONSORS.md](SPONSORS.md) for the account restrictions and hosting plan.

Candidate code must not access verifier labels, the price ledger, host credentials, other jobs or a host Docker socket. Model/tool calls should be brokered with scoped authorization and limits. Disable unsupported network destinations and production-changing tools. Keep the evaluator and accounting outside candidate execution and editable paths; separation within one host remains a demo constraint requiring explicit validation.

## 8. Optimizer tools and control loop

| Tool | Returned evidence |
| --- | --- |
| Inspect source | Relevant files, definitions and source locations within allowed paths |
| Read run evidence | Authorized outputs, traces, usage, errors and timing |
| Create candidate | Parent revision, bounded patch, diff and validation outcome |
| Run experiment | Actual outputs, check failures, measured usage, duration and stop reason |
| Compare | Comparable original/candidate results and per-case differences |
| Freeze | Immutable candidate and evaluation-policy hashes |
| Export | Patch, experiment record and reproducible report |

The model chooses tools and hypotheses. Deterministic code validates arguments, admits work against the budget, enforces file/tool permissions and computes acceptance. A candidate cannot redefine success or forge its expense.

State should retain job/candidate/experiment IDs, current revision, dataset version, accumulated expense, previous results and stop reasons. Suggested states: ready, baselining, analyzing, awaiting_goal, experimenting, revising, final_check, completed, no_improvement, failed, cancelled.

A browser reconnect must not restart the search. A worker interruption must not erase completed experiments or known expense. Ambiguous provider completion/cost remains explicitly unknown until reconciled; do not claim universal exactly-once execution.

## 9. Evaluation contract

Define success before optimization. Requirements may include required facts, missing-data behavior, evidence support, output validity, permitted abstention and latency bounds. A failing original needs repair before claiming behavior-preserving savings.

| Dataset | Use |
| --- | --- |
| Development | Expose permitted examples/diagnostics to guide improvements |
| Selection/validation | Compare candidates; repeated access can overfit |
| Protected final | Evaluate frozen candidates without prior label access |
| Free-form visitor tasks | Run and inspect; remain unscored without independent expectations |

Use exact checks for bounded fields and schemas. Where semantic judging is necessary, use an explicit rubric, calibration and human-reviewed examples; do not let the optimizer's own confidence establish correctness. Schema validity alone is not semantic correctness.

Repeat fresh original/candidate trials as budget permits and report unique-case counts, repetitions and per-case failures. Keep model/settings, pricing assumptions, tool behavior and measurement boundaries comparable. Separate sandbox startup from workflow execution latency; separate cold/warm cache behavior. A small suite cannot establish universally unchanged quality or reliable tail-latency statistics.

If final feedback drives another edit, that set is no longer independent. Obtain new protected cases or disclose the changed evaluation boundary. Label mock tools, replay and deliberately injected failures; real model runs are necessary for fresh inference quality/cost claims.

Required practical comparisons: sensible original and simple cheaper-model substitution where the goal is cost. A general coding assistant with equal tools/data/budget is an important differentiation baseline; disclose if it is not run. Existing optimizers are competitors, not proof that our product is novel.

## 10. Accounting and affordability

Running the original, candidate trials and optimizer costs money. We only need the target agent during experiments; the customer can keep operating the delivered implementation on their own infrastructure afterward.

Track separately:

- Original/candidate operating expense, including failed calls and retries.
- Total optimization expense, including optimizer reasoning, experiments and runner compute.
- Provider-rate estimates versus reconciled billing.
- Tool charges and ambiguous completions that are not yet known.
- Customer pricing assumptions, which are not validated revenue.

Avoid counting a billable call multiple times because it appears in several spans. Credits reduce immediate cash paid, not underlying operating expense. Coding subscriptions are not proof of hosted API access.

For comparable successful workloads and positive savings:

```text
break-even future tasks = total optimization expense / operating savings per task
```

If success rates or task mixes differ, compare expense to complete the same required workload rather than blindly using that shortcut. If savings are non-positive, there is no positive break-even claim.

Public browsing of existing results should not trigger inference. Live work starts on an explicit action. Limit active jobs, cases, trials, tokens, retries and runtime; reserve estimated maximum call expense before dispatch where possible and stop admitting work at the total ceiling. Cancellation does not guarantee a provider will refund an already dispatched request.

No numerical spend limit is selected yet. Determine it from actual model access, prices and the first measured experiment. Previous results/replay must be labelled; never simulate a live optimizer while claiming fresh execution.

## 11. Stress testing and recovery

Test these separately:

| Subject | Cases | Claim supported |
| --- | --- | --- |
| Target original/candidate | Long context, amendments, missing facts, malformed tool output, repeated trials | Observed task behavior and regressions |
| Our optimizer | Rejected patch, timeout, provider error, budget exhaustion, interruption | Result-guided recovery, stopping and retained state |
| Hosted service | Concurrent arrivals, cancel/reconnect, queue saturation | Admission and job-state behavior |

Simulated model responses can cheaply test infrastructure load. They do not establish real-model quality or savings. Use selected real live challenges and retain broader measured results. A deliberately injected fault must be labelled; it is not a naturally observed agent failure.

## 12. Interface and report requirements

The website must expose:

- Supported workflow readiness and baseline behavior.
- Evidence-linked findings and selectable optimization goal.
- Constraints, allowed changes and experiment budget.
- Persisted real experiment activity and consumed expense.
- Source diffs, output differences and reasons for rejection.
- Final acceptance status and downloadable patch/report.
- Unsupported requests, unknown measurements and no-improvement outcomes.

Decision explanations should be concise and tied to evidence, not private chain-of-thought dumps or fabricated progress percentages. Check the complete visitor path on laptop and phone.

Each final report records workflow/revision, goal, requirements, dataset hashes/counts, model/configuration and rate assumptions, actual trials, per-case regressions, aggregate metrics, optimization expense, unresolved cases, artifact hashes and reproduction instructions. Recommendation labels: observed bottleneck, estimated opportunity, verified on stated cases, rejected, inconclusive.

## 13. Proposed software and hardware

| Component | Starting proposal |
| --- | --- |
| Website | React/Vite |
| API and optimizer | Python/FastAPI with one tool-using model loop |
| Execution | Docker locally; one approved EC2 host with bounded containers for reviewed demo workflows |
| Evaluation | Pytest/custom protected checks; semantic evaluation only where necessary |
| Job state | SQLite for one controller instance with durable storage |
| Versions/artifacts | Git revisions, diffs and downloadable reports |
| Model access | Actual API credentials, declared rates and a spend limit |

These are proposals, not installed dependencies or a user-approved final stack. Reuse familiar patterns; do not add Redis, distributed search, a tracing replacement or a custom evolutionary framework without demonstrated need.

Current event resource clarification: the official page excludes Bedrock. The supplied account-rules email approves EC2/Lambda/IAM roles/load balancers in `us-east-1`, permits one EC2 instance in `Hackathon_VPC`, and limits each EBS volume to 50 GB. ECS/Fargate is outside that list. Access, networking, and remaining balance still require live verification. See [SPONSORS.md](SPONSORS.md).

Starting hardware recommendations, not measured minimums: modern 4-core development laptop, 16 GB RAM preferred, around 20 GB free disk; approximately 2 vCPU/4 GB RAM for a small API/worker; runner sizing depends on the supported workflow. No GPU is required if inference uses hosted APIs. Begin with one active optimization job. Browser automation, local models and large repositories need separate sizing.

## 14. Acceptance criteria

| ID | Requirement | Evidence |
| --- | --- | --- |
| A1 | Supported target runs reproducibly | Actual original outputs and run records |
| A2 | Our agent takes consequential action | Source-aware hypothesis, actual patch and tool history |
| A3 | Results influence the next decision | Observed failure/rejection followed by a reasoned next action |
| A4 | Verification is independent | Candidate cannot alter evaluator, requirements or ledger |
| A5 | Result is usable | Frozen patch and clean supported reproduction |
| A6 | Trade-offs are honest | Improvements, regressions, failures, denominators and unknowns |
| A7 | Expense is bounded and reported | Admission limits and separate optimization accounting |
| A8 | Visitor completes the journey | Hosted input-to-artifact path, fresh run clearly distinguished from replay |
| A9 | Required sponsor contribution is real | Evidence described in hackathon.md |

These are our product criteria. An honest no-improvement outcome fulfills the stop behavior but does not, by itself, establish commercial value or a winning demonstration.

## 15. Build order and decision gate

1. Confirm current time against the event build window, usable model/AWS access and workspace instructions.
2. Select one sensible target, adapter, allowed dependencies and acceptance contract.
3. Run original plus simple cheaper-model baseline; verify trace capture and development checkpointing.
4. Establish one complete inspect → change → run → feedback → revise/reject → export loop.
5. Add the hosted journey and a supported live challenge; enforce spend/concurrency limits.
6. Freeze candidates, run protected comparisons, produce the business plan and assemble sponsor evidence.
7. Record the actual demonstration and complete the submission checklist in hackathon.md.

Aim to establish optimization headroom early in the build. If ordinary model substitution already solves the whole problem, meaningful labels are unavailable, or experiment expense cannot reasonably pay back, reconsider the target/claim. Do not rescue the pitch by making the original deliberately inefficient.

## 16. Risks and decisions still open

- Working product name; representative target workflow; approved adapter/dependencies.
- Framework/model selection, actual API access, hosting region and budget.
- Whether AWS allocation permits the selected services and networking.
- Usable Neatlogs trace readback and public evidence permissions.
- Entire checkpoint capture/access and CFO.ai artifact/export access.
- Reliable correctness labels and independent final evaluation.
- Useful improvement beyond simple substitution and ordinary coding assistance.
- Customer demand and willingness to pay.

GEPA already optimizes code/agent architectures; routing and prompt optimizers also exist. Source editing or reflection alone is not differentiation. The proposed advantage is completing a trustworthy optimization workflow with reviewable artifacts and less operator effort; this remains a hypothesis. [GEPA primary source](https://gepa-ai.github.io/gepa/blog/2026/02/18/introducing-optimize-anything/).

## 17. Continue in another chat

> Read prd.md and hackathon.md. Continue the Autonomous Agent Optimization Engineer project. Preserve the user's central promise: delegate context/memory/orchestration experimentation and deliver a tested patch with improvements and regressions. Our optimizer is the acting agent; the user's agent is its target; the runner/evaluator are tools. Inspect the current workspace, current time, organizer updates and available access without exposing secrets. The stack and narrow Python scope are recommendations, not established implementation. Choose a reasonable target and explicit acceptance contract before broad UI or architecture work. Run fair baselines, then build one complete autonomous loop and hosted visitor journey. Never manufacture inefficiency, invent metrics or claim general compatibility. Preserve sponsor roles and evidence requirements. These files authorize planning handoff, not automatic external publication, paid signup or production changes.

Current evidence: 37 passing regression tests, local authentication startup, and real GitHub sign-in with a persisted session. Import tests use mocked GitHub responses. Real repository imports and optimization results remain unverified.
