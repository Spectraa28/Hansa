# neatHack: Rules, Requirements and Submission Handoff

Prepared October 10, 2026 for team Spectra. Read [prd.md](prd.md) for the product. This document separates published facts, organizer information supplied by the user and our implementation strategy.

Implementation roles are defined in [SPONSORS.md](SPONSORS.md). Current resource clarification, rechecked October 10 against the [official page](https://neatlogs.com/hackathon): AWS eligibility is now stated as the first 350 checked-in teams; the $25 allowance covers approved EC2/Lambda/IAM/load-balancer services in `us-east-1`, excludes Bedrock, and does not establish ECS/Fargate access. The older organizer-email allocation below remains a historical report. Actual account access and credit receipt remain unverified.

## 1. Published rule card

Source: [official page](https://neatlogs.com/hackathon), checked October 10, 2026. Later announcements override.

- Track: **Build an agent that works (literally)**; substantial tasks, feedback-guided action.
- Team: 1–4; matching registration/team names; one team per person.
- Planning beforehand allowed; code within build window; prebuilt/part-built entries excluded.
- Mandatory: Neatlogs, Entire, CFO.ai.
- Submit one public X quote-post of the official post: team/name/project, public repository, demo. Drafts alone are insufficient.
- Video ≤3 minutes: each tool's architecture, implementation, runtime, reasoning, result.
- Evidence: dated commits, improvement comparison, failure/recovery, traces, Entire output, business plan.
- Late entries excluded; bought/bot engagement disqualifies; plagiarism, spam, harassment prohibited.

| Milestone | IST |
| --- | --- |
| Check-in | October 10, 08:00 |
| Kickoff | October 10, 09:00 |
| Build starts | October 10, 12:30 |
| Submit | October 12, 19:00–23:55 |
| Results | October 16 |

| Scoring | Weight |
| --- | ---: |
| Agent | 30% |
| Required tools | 25% |
| Demo | 20% |
| Public work | 15% |
| Usefulness/originality | 10% |

Community award: separate; genuine interest over follower count. Judges' decision final.

### Timetable ambiguity

The 48-hour label conflicts with explicit timestamps. Confirm pinned announcements; use timestamps. Older October 10–11 headers do not override this timetable.

## 2. Organizer email supplied by the user

This is user-provided organizer correspondence, not independently authenticated account state.

| Item | Reported status/instruction | Unverified |
| --- | --- | --- |
| Spectra | Web check-in complete; leader receives setup instructions | Current organizer dashboard and complete member roster |
| Allocation | Credits once per team, not each member | Receipt and balances |
| Neatlogs | All paid plans free throughout the event | Project/key, application capture and readback |
| Entire | Connect GitHub repository, install CLI, capture first checkpoint; include accessible checkpoint link AND ID | Capture, sync and public permissions |
| CFO.ai | Any paid plan free via event signup; organizer provides credits separately; include business plan | Account, cancellation, credits and export |
| Crustdata | 5,000 credits; promo code NEATLOGS-OCT2026 | Redemption and API access |
| AWS | Eligible first-200 team; one shared $25 allowance; leader gets access separately | Access receipt, permitted services and balance |

The $25 allowance is not a confirmed inference balance or authorization to spend. Coding subscriptions do not establish hosted model API access. Do not assume Crustdata data or AWS infrastructure must be used in the product merely because credits are offered.

## 3. Intro-call clarifications supplied by the user

No recording was reviewed; preserve these as the user's account of organizer guidance.

- Entire may record coding-agent development history and decisions. It does not have to be a dependency in the customer's runtime.
- CFO.ai may produce the business budget/plan without runtime integration.
- A hosted website and a clean demo were emphasized. Treat hosting as a delivery target from this guidance, not an independently verified new written rule.
- Simple products are acceptable; substantial engineering solving a real problem was encouraged. This does not change scoring weights.
- Hiring-related encouragement mentioned technical lead Akshay. The event roster identifies Akshay Hangloo, but this is not a hiring guarantee or extra rubric.
- Asked about further changes, the user replied: **“No other changes announced.”**

For this project, demonstrate actual development/business contributions instead of inventing sponsor runtime roles. Do not publish a claim that each sponsor operates inside our optimization loop.

## 4. Sponsor setup and evidence

### Neatlogs

Start with the [dedicated setup guide](https://neatlogs.com/hackathon/neatlogs-setup-guide.html), then [framework documentation](https://docs.neatlogs.com). The guide was retrieved earlier in this session; no setup was executed.

Use the correct key type: SDK project key and `nlw_` HTTP-ingest key are distinct. Reading stored traces also needs appropriate read authentication; an ingestion key is not automatically a read token. Keep credentials out of source, chat and recordings.

First validate the diagnostic trace visibility/finalization, then verify actual application workflows. A diagnostic probe or local SDK event alone does not establish application tracing. Retain a finalized trace behind a real investigation and another behind the verified change.

Our proposed evidence: optimizer decisions/tools, original/candidate execution, failures/retries, usage and the implementation change caused by the trace evidence. Keep optimizer expense distinguishable from target expense. Ensure evidence links/screenshots are readable without exposing sensitive content.

### Entire

Follow the [dedicated event guide](https://hack.entire.io/neathacks-2026/), retrieved earlier this session. Its specific submission instruction and the newer email ask for **an accessible checkpoint link AND checkpoint ID**. Follow this even though the generic event evidence wording accepts graph output.

Enable supported capture before substantive coding. Retain a real session behind a reviewed committed change, verify synchronization and check evidence access. A URL does not grant permission by itself. Use platform/current CLI instructions; the guide's Mac examples are not automatically the right installation path on Arch Linux.

Graph, Brain and Trails are optional. Graph can support source/impact investigation; Brain is repository memory; Trails may require feature access. Do not add them just to inflate sponsor coverage or describe them as arbitrary customer memory. Advertised savings are not our measurements.

Our proposed evidence: a checkpoint showing the decision behind an implementation or recovery fix, with its ID, accessible link and corresponding diff. Custom optimizer logs do not become Entire checkpoints simply by being named that.

### CFO.ai

Organizer email instructs signup at [cfo.ai/neathacks](https://cfo.ai/neathacks). A card is required; immediately cancel in Settings → Billing after signup to avoid billing, according to that email. No signup, cancellation or credit receipt has been performed here; verify live terms during an authorized signup.

Produce the actual business plan in CFO.ai, using measured experiment expense and labelled pricing/volume assumptions. Cover customer pricing, costs, revenue and runway. Retain an accessible artifact/export and the assumptions behind it. Our own Markdown brief is not evidence that CFO.ai generated a plan.

CFO.ai is not our model-call budget controller or payment processor. Runtime integration is unnecessary under the reported clarification.

### Optional resources

AWS/Aivar account rules subsequently supplied by the user: one shared $25 allocation through the existing private IAM access link; `us-east-1` only; approved EC2, Lambda, IAM roles/policy attachment, and load balancers; existing `Hackathon_VPC` only; one EC2 instance per supplied IAM user, shared by the team; terminate before replacement; allowed `t2`/`t3`/`t3a` sizes `nano` through `large`; each EBS volume at most 50 GB. The access page does not meter spending. Only the leader receives AWS access; stop resources when finished. The email is user-provided correspondence, not a verified console session or balance. See [SPONSORS.md](SPONSORS.md) for the resulting single-host plan. ECS/Fargate is outside the supplied approved-service list.

- Crustdata: [signup](https://app.crustdata.com), choose “Have a promo code?” before email signup; add NEATLOGS-OCT2026. Email instructions say not to use Google signup for redemption. Existing-account issues go to organizers. [API documentation](https://www.crustdata.com/api-documentation).
- AWS: confirm the allocated account, service permissions, region and actual usable credits before choosing deployment. Do not provision speculative infrastructure during this documentation handoff.
- Help and authoritative updates: [neatHack Discord](https://neatlogs.com/discord).

## 5. Project evidence mapped to scoring

This is our strategy, not additional organizer rules, predicted scores or a guarantee of winning.

| Area | Evidence we intend to produce | Weak version to avoid |
| --- | --- | --- |
| Acting agent | Source-aware hypothesis, actual edits, feedback-guided revision/rejection and usable artifact | Advice only or scripted improvements |
| Sponsor contribution | Inspectable outputs that changed a development or business decision | Logos and installation screenshots alone |
| Demonstration | Clear starting task, actual experiment, failure/recovery, artifact and honest comparison | Dashboard tour or unexplained numbers |
| Public work | Technically useful progress, genuine tries/feedback and working interaction | Unsupported launch claims or artificial engagement |
| Customer value | Useful supported outcome and an honest baseline comparison | Universal savings or untouched-market claims |

Showing that the target became cheaper is not automatically proof that our optimizer improved during development. Preserve a development change to our optimizer and matched before/after evidence where possible.

### Technical credibility

Show why the optimizer retained a necessary expensive step, rejected an unsafe change or chose a fallback. Use independent checks and accounting. Ordinary prompt edits, extra agent counts and elaborate infrastructure alone do not establish substantial engineering.

The user wants winning-first planning and serious engineering. No judge's private tastes are known. Do not claim that a particular product category, performance percentage or community tactic guarantees placement or hiring.

## 6. Demo and community plan

Recommended three-minute narrative, scaled to the actual shipped behavior:

1. Explain the user's task and the optimization requirement.
2. Show the original behavior and an observed bottleneck.
3. Start our optimizer; show its actual source-aware action.
4. Show a failed/rejected candidate and the action prompted by feedback.
5. Show accepted results or an honest stop, plus the usable patch and trade-offs.
6. Show the real sponsor artifacts and what each contributed.

Use only observed results. If a failure is injected, label it. If inference is replayed or footage is time-compressed, label it. Do not imply that recorded runs are fresh interactive execution.

The hosted site should permit a bounded live challenge, not unlimited paid experimentation. Public browsing can inspect previous results without dispatching model calls. Define total spend and admission limits before opening live execution.

Share only authorized public material. A useful progress update explains a real technical obstacle, decision and observed outcome. Keep keys, private repository material, unrelated sessions and sensitive trace content out of posts. This handoff does not send messages or publish a submission.

## 7. Submission checklist

### Product and evidence readiness

- [ ] Original workflow runs with approved requirements.
- [ ] Our optimizer actually changes code and uses feedback to choose its next action.
- [ ] Accepted patch reproduces reported supported behavior.
- [ ] Comparison includes regressions, failures, retries, optimizer expense and limitations.
- [ ] Final-test boundary is documented; edited-after-feedback results are not called independent.
- [ ] Real application traces and development improvement evidence are retained.
- [ ] Entire checkpoint link AND ID are recorded; permissions are verified.
- [ ] Actual CFO.ai business artifact and assumptions are retained.
- [ ] Hosted journey, patch download and laptop/phone presentation work.
- [ ] Replay, simulations, synthetic inputs and injected faults are labelled.

### Packaging and publication readiness

- [ ] Team identifiers match Spectra registration; member details are confirmed.
- [ ] Public repository has eligible dated commits and reproducible setup instructions.
- [ ] Environment example contains names only, never credentials.
- [ ] Repository includes supporting evidence and the declared execution/evaluation limits.
- [ ] Video duration and actual tool coverage satisfy the rule card.
- [ ] Repository, demo, video and required evidence can be inspected by judges.
- [ ] Current pinned announcements, final deadline and actual official submission-post URL are checked.
- [ ] Exact post and claims are reviewed; no invented savings, adoption or capabilities.
- [ ] Publication is authorized and completed through the actual submission mechanism.
- [ ] Published post keeps the official quote attached and working artifact links.
- [ ] Submission URL, time and submitted revisions are retained.

An open draft or prepared post is not a completed submission.

## 8. State for the next chat

Team check-in is reported complete. All application, benchmark, checkpoint, business-plan and publication outputs remain unproduced. The working product is defined in prd.md; exact workflow, stack, model access, numerical budget and hosting remain unresolved.

Refresh organizer announcements before implementing or submitting. Continue with one supported target and explicit correctness criteria; do not restart broad ideation without a concrete failure of the initial feasibility gate.
