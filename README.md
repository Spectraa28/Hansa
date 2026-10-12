# Frontend

The product interface for Hansa. The light laboratory design, shared colors, local fonts and original swan SVG follow [`DESIGN.md`](DESIGN.md). The landing page presents a measured hero, an interactive recorded experiment with six recorded fields, a connected process sequence with saved artifacts, and a footer. Section introductions sit beneath their headings. The product includes sign-in, imports, setup, reports, stage starts and recorded results.

## Development

From `frontend/`, with dependencies installed:

```sh
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/auth` and `/github` to the API at `http://localhost:8000`; start the backend separately using the instructions in [`../README.md`](../README.md). Use `localhost` consistently, including `APP_URL` and `FRONTEND_ORIGIN`, so OAuth state and session cookies share the same host.

`/sign-in` reads `/auth/providers` and offers enabled GitHub, Google and email sign-in methods. `/app` checks `/auth/me` and lists the signed-in owner's `/github/imports`, with refresh and pagination. Each repository opens `/app/imports/{id}`, reading `GET /github/imports/{id}/report`. Signed-out or expired sessions return to `/sign-in`. Import creation lives at `/app/new`; stages start only through an explicit launch button. The signed-in header always offers `Your agents` (`/app`) and `Import an agent` (`/app/new`). On phones, the folder button opens existing agents and the menu contains both destinations.

The agent list explains how to open an import, complete setup, establish a baseline, investigate/test a change and review the result. Import setup includes an expandable connection/repository/branch/folder walkthrough and explains what happens after the source copy is ready. These sections start no jobs and distinguish source import from execution.

The report page has the six-step rail from the design, per-task baseline measurements and file/line findings. Result compares the tested baseline and candidate on model calls, cost and wall time, then shows each task's outcomes, the verdict and its reason. Rejected changes remain completed results, with their measurements preserved and exports marked for review. Missing values display `Not recorded`; estimated savings stay hypotheses, and `needs_review` stays separate from passed checks.

The report's `next` field recommends the initial step; `?step=result` selects Result. It defaults to the latest optimization attempt; selecting another saves its job ID in `attempt`, so reloads and shared links preserve the choice. Bars use the selected comparison's own baseline and cover only its tested tasks. Automatic check counts appear when the API records them.

`Download patch` and `Copy prompt` fetch the selected job's `/patch` and `/handoff` endpoints. Downloads of changes that were not accepted have `-not-accepted.patch` filenames. Copy uses the API's exact Markdown handoff, including the rejected-change instructions. When clipboard access is denied, a selectable text field appears. Artifact failures keep the result visible and let the same button retry; an expired session returns to sign-in.

## Starting stages and following runs

Setup starts onboarding, Baseline starts a task baseline, Findings starts investigation, and Fix tests a saved finding or a custom goal. Finding links select the corresponding fix without launching it. Every start form shows its spend cap before the button and sends `X-CSRF-Token` from the current session. Agent stages default to $0.50 and allow up to $1.50; fix testing also has a separate candidate-run cap, default $0.50 and maximum $3.00. Baseline displays the current confirmed contract's spend limit, loaded from `/contract`; it sends only repetitions (1–5). A missing/stale/unconfirmed contract prevents launch. The baseline cap applies across all tasks and repetitions, not once per task.

These are recorded-spend thresholds. Calls and batches already underway can overshoot them; unknown costs stay unknown. This page does not alter task contracts or silently start prerequisite stages.

The report's `active.kind` and `active.job_id` reattach the live feed after reload. Events poll every second with `after` set to the highest received ID; rows are deduplicated and ordered. Agent stages use `/agent-jobs/{job}/events`; baselines use `/baseline-jobs/{job}/events`. The job endpoint is checked alongside events because an interrupted agent may finish without emitting a final event. Terminal jobs drain paginated history before polling stops, then refresh the report. Starts are hidden while a job runs.

The feed follows new rows until the reader scrolls up; `Follow latest` restores following. Desktop puts the feed beside recorded totals, while phones put totals first. Baseline totals sum completed run events; agent/target usage appears only when the job reports it. Elapsed time uses the server's creation timestamp and the browser clock. Failed reads keep existing rows and offer `Resume feed`. POST requests are never automatically retried; a lost or server-error response requires `Check run status` before another launch.

Live task rows update from recorded baseline and candidate events as polling receives them, without waiting for the final report. Results resolve after the requested repetitions; review-needed results remain labelled as such, and a new candidate experiment resets its own rows. Events slide in, the current step pulses quietly, and the pulse stops on feed errors or completion. Trace panels slide in from the right. Shared controls and row hover feedback take 120–160ms; reduced motion suppresses the animations.

The public landing hero feeds its engineering-loop diagram with saved Swarm calls/cost and the tested change’s rejection. Its cost is rounded to cents and every regression count comes from the saved comparison. The recorded experiment is the second section, followed by How it works and the closing invitation. Marketing eyebrows and numbered step tags have been removed; mono labels stay inside product blocks. The generic parameter section has been removed. `Analyze my agent` opens `/app/new`; `Explore the demo` scrolls to the recorded experiment. Navigation links follow the section order. Normal scrolling and a static reduced-motion hero are supported.

Only the hero diagram and recorded experiment use layered shadows. Other reading groups, process steps and app panels are flat and borderless, with padding and gaps separating them. Fields, selection controls and focus rings keep visible edges.

The recorded experiment reads [`src/data/swarm-report.json`](src/data/swarm-report.json) and its matching [`swarm-patches.json`](src/data/swarm-patches.json). Baseline, Findings, Tested change and Verdict tabs support arrow keys, Home and End. Its persistent six-field summary shows original/candidate cost, latency, calls and tokens, plus task regressions/review status and the recorded task/repetition/model conditions. Spend/runtime caps are not saved in this report and are not invented. All measurements and findings come from the saved report. Failed baseline checks and review-needed answers remain visible; findings are labelled hypotheses, and the tested patch is labelled not accepted. The comparison shows mean totals per pass of the task set. Homepage currency is rounded to cents and time/counts/percentages to whole values; percentages use the unrounded measurements. App formatting and saved reports retain their existing precision. No stages, event polling, downloads or private API reads are attached to this public section. Source links use the fixed commit; `Open full report` opens the corresponding `/demo` view.

`/demo?step=result` previews the saved report, explicitly labelled as saved results. Its exports use [`swarm-patches.json`](src/data/swarm-patches.json) and [`swarm-handoffs.json`](src/data/swarm-handoffs.json). The latter was generated using the backend's deterministic handoff builder against the saved report and patches. The preview does not require sign-in or call live report/artifact endpoints. The recorded demo, report, patches and handoffs are intentionally included in the public build; they must contain only approved public material. Live failures never fall back to these files.

Successful OAuth callbacks now redirect to the configured `FRONTEND_ORIGIN/app`; restart an already-running API to apply that code change. `/auth/me` remains a JSON endpoint for session checks. Navigation and the secondary hero action link to the implemented landing sections.

```sh
npm run build
npm run preview
```

The build checks TypeScript and writes `dist/`. The API proxy is development-only; preview and production hosting need same-site API routing plus a fallback to `index.html` for `/app` and `/sign-in`.

## UI checks

With the dev server running and the installed `$web-designer` skill:

```sh
node scripts/check-ui.mjs /home/spectra/.codex/skills/web-designer
node scripts/check-runs.mjs /home/spectra/.codex/skills/web-designer
node scripts/check-landing.mjs /home/spectra/.codex/skills/web-designer
node scripts/check-live-motion.mjs /home/spectra/.codex/skills/web-designer
node scripts/check-profile.mjs /home/spectra/.codex/skills/web-designer
```

Pass a different skill directory as the first argument if needed, then an optional frontend URL and screenshot output directory. These checks use labelled API fixtures; they cover sign-in, imports/reports, selected result/reload, partial comparisons, task outcomes, bars with unknown/zero values, patch contents and filenames, prompt copying/manual fallback, artifact failures, expired sessions and layouts from 320px to 1440px. Accepted and unknown-result states are explicitly synthetic UI fixtures; the saved Swarm report remains rejected. They do not prove real OAuth or live authenticated exports.

The run checks use synthetic jobs for all four starts, exact caps/CSRF payloads, duplicate submission, ambiguous responses, reattachment, incremental/paginated events, scrolling, paused-feed recovery, terminal/restart status, rejected completion and expired sessions. They never dispatch a real model call or execute imported code. Stage launch is disabled in the saved preview.

The profile checks use a synthetic session to verify mobile stacking, desktop rows, long names/emails, avatar sizing, action guards and navigation from home to existing agents, their reports and new import setup at 320–1440px. Account mutations are intercepted and never reach the backend.

The landing checks verify section order, baseline failures, actual comparison figures, fixed-commit source links, tab keyboard navigation, reduced motion and 320–1440px layouts. Virtual time verifies the hero's six-stage highlight loop, hover/focus pauses, teal highlights without playback controls and static reduced motion. It also checks visible-only demo autoplay, the progress line, permanent click/keyboard takeover, and baseline-to-candidate figure animation with exact saved endpoints. They capture screenshots and assert that no live job or private GitHub request starts. They also check the shared light theme on the recorded product pages.

It talks to the API in [`../backend`](../backend) over same-site requests with the session cookie (`credentials: "include"`). Mutations send the CSRF token from `GET /auth/me` in the `X-CSRF-Token` header. The backend allows one browser origin, set by `FRONTEND_ORIGIN` (default `http://localhost:5173`).

## What the backend already returns

| Screen | Endpoint |
| --- | --- |
| Sign in, current user | `/auth/providers`, `/auth/me`, `/auth/{google,github}/login` |
| Repositories and imports | `/github/connection`, `/github/repositories`, `/github/imports` |
| Detected settings | `/github/imports/{id}/inspection`, `/github/imports/{id}/configuration` |
| Tasks and pass rules | `/github/imports/{id}/contract` |
| Start a stage | `POST /github/imports/{id}/onboarding`, `/baseline`, `/investigation`, `/optimization` |
| Live progress | `/github/imports/{id}/agent-jobs/{job}/events?after=N`, `/github/imports/{id}/baseline-jobs/{job}/events?after=N` |
| Everything for one import | `/github/imports/{id}/report` (includes `next`, the step to offer) |
| Patch download | `/github/imports/{id}/agent-jobs/{job}/patch` |
| Coding-agent prompt | `/github/imports/{id}/agent-jobs/{job}/handoff` |
| Traces | `/github/imports/{id}/traces`, `/github/imports/{id}/traces/{trace_id}` |

Field-level detail is in [`../backend/docs`](../backend/docs).
