# Sponsor Roles & Integration Plan

Prepared October 10, 2026 for the Autonomous Agent Optimization Engineer. This defines the initial build plan; integrations and account access remain unverified. Paid model API access will be supplied later by the user.

## Required roles

| Sponsor | Role | Delivery evidence |
| --- | --- | --- |
| Neatlogs | Runtime observability for the optimizer and original/candidate agents; evidence for investigation and development improvements | Finalized application traces, comparison records, and a trace-backed engineering decision |
| Entire | Capture coding-session context and link development decisions to committed changes | Real checkpoint ID, accessible checkpoint link, and corresponding commit/diff |
| CFO.ai | Build the product's business plan from measured operating costs and explicit assumptions | Actual CFO.ai plan/export covering pricing, costs, revenue, and runway |

These roles match the [official event requirements](https://neatlogs.com/hackathon). Only Neatlogs is planned as a required customer-runtime integration in the first build.

## Neatlogs: evidence for the optimization loop

Instrument supported provider/framework clients and add workflow/tool spans using the [Python SDK](https://docs.neatlogs.com/sdk/python). Capture optimizer inspections, edits, experiments, failures, and retries, plus original/candidate model and tool calls. Instrument memory reads, writes, and context construction explicitly; model-call traces alone do not explain memory behavior.

Associate evidence with job, candidate, experiment, task, and source revision IDs. Keep optimizer expense separate from target expense. Redact sensitive inputs before export and supply tracing access through the trusted integration boundary.

Give the optimizer access to authorized stored evidence. The documented [MCP tools](https://docs.neatlogs.com/integrations/mcp-tools) include `search_traces` and `get_trace_context`; validate authentication, scope, and actual readback before depending on them. Missing spans or usage must remain unknown rather than being reported as zero.

Our controller enforces spending limits and maintains the usage ledger. Protected evaluators establish task correctness. Neatlogs supplies execution evidence; acceptance requires reproducible checks as well as traces.

Completion evidence: a finalized real baseline trace, candidate trace, and failed/rejected experiment with the optimizer's subsequent action. Also retain evidence of a development change that improved our optimizer itself.

## Entire: development provenance

Initialize Git and enable supported coding-agent capture before substantive application coding. Entire records the context behind our implementation decisions; its [checkpoint model](https://github.com/entireio/cli/blob/main/docs/architecture/sessions-and-checkpoints.md) supports linking sessions to code commits.

Retain a checkpoint behind a meaningful runner, recovery, memory, or evaluation change. Verify synchronization and evidence accessibility. Review captured content before publication; Entire can retain prompts, responses, and tool interactions in the repository. See [security and privacy](https://github.com/entireio/cli/blob/main/docs/security-and-privacy.md).

Candidate versioning, patch export, and experiment rollback use our own immutable revisions and isolated workspaces. Repository graph integration is optional and deferred until it helps a specific investigation. Checkpoints do not restore external service state.

## CFO.ai: business economics

Use measured experiment records to prepare input covering original/candidate expense, total optimization expense, infrastructure, and failed calls. Label estimated rates and unknown billing. Model customer pricing, usage, revenue, margins, and runway as assumptions; credits reduce immediate cash paid, not underlying operating cost.

Produce the actual business plan in CFO.ai and retain its export/link. Begin with manual transfer of a reviewed summary; automatic financial synchronization is outside the first build. Our Markdown inputs alone are not a CFO.ai artifact.

Signup and billing actions remain separate from this local build. The official event page describes card signup and immediate cancellation; verify live terms during authorized setup.

## Optional resources and implementation order

The current official page excludes Bedrock; model API billing is separate. The user supplied the AWS/Aivar account-rules email below. It establishes the allocation rules, not successful login or a live remaining balance. Crustdata is optional; no product dependency is planned.

### AWS/Aivar account rules supplied by the user

- One shared $25 allowance for team Spectra; the update adds no allocation. Use the existing private access link and supplied IAM login. No new AWS account, card, or credit code is needed.
- Region: `us-east-1` only. For EC2 and load balancers, use the existing `Hackathon_VPC`; creating a VPC is prohibited.
- Approved services: EC2, Lambda, IAM roles, and load balancers. Roles and policy attachment are permitted. ECS/Fargate is outside the supplied approved-service list.
- Permitted EC2 types: `t2`, `t3`, and `t3a`, each in `nano`, `micro`, `small`, `medium`, or `large` sizes.
- Maximum one EC2 instance per supplied IAM user, shared by the team. Terminate an existing instance before launching a replacement; automation will terminate an additional newly launched instance.
- Each EBS volume must be 50 GB or smaller. The $25 ceiling includes the team's resource usage; the access page does not meter spending.
- Only the leader receives access. Keep console passwords, private links, and CLI/SDK keys out of source, screenshots, recordings, and public chats. Stop resources when finished.

### Hosting implication

Plan one EC2 host for the API, optimizer worker, SQLite/artifacts, and bounded runner containers, with one active optimization job. The frontend may be served by the same host. A load balancer and Lambda are optional, not initial dependencies. Choose instance and disk sizes after a local resource check and verify account networking before provisioning.

Use reviewed workflows for the initial hosted demonstration. Containers on a shared host do not establish a production boundary for arbitrary submitted repositories. Candidate execution must still be restricted from controller secrets, host mounts, the Docker socket, protected labels, and the usage ledger; retain CPU/memory/runtime and network limits. General repository execution requires a separately validated isolation design.

Stopping EC2 does not remove EBS storage charges; include remaining storage and other retained resources in shutdown planning. See [EC2 stop/start billing](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html). No infrastructure has been provisioned.

1. Establish Git and Entire capture.
2. Build and test the local runner/controller with explicitly labelled fixtures; fixture metrics do not establish model savings.
3. Configure Neatlogs, verify its diagnostic probe, then verify real application traces when model access is available.
4. Run bounded real optimization experiments and protected comparisons.
5. Produce CFO.ai economics and package verified sponsor artifacts.

Public submission, checkpoint publication, paid signup, and infrastructure provisioning are not performed by this document.
