# Frontend

The product interface for Hansa. The landing hero, pinned How it works, saved real run, sign-in, authenticated imports and report pages use the colour tokens, local fonts and grid-paper background from [`DESIGN.md`](DESIGN.md). Other landing sections and editable setup are planned.

## Development

From `frontend/`, with dependencies installed:

```sh
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/auth` and `/github` to the API at `http://localhost:8000`; start the backend separately using the instructions in [`../README.md`](../README.md). Use `localhost` consistently, including `APP_URL` and `FRONTEND_ORIGIN`, so OAuth state and session cookies share the same host.

`/sign-in` reads `/auth/providers` and offers enabled GitHub, Google and email sign-in methods. `/app` checks `/auth/me` and lists the signed-in owner's `/github/imports`, with refresh and pagination. Each repository opens `/app/imports/{id}`, reading `GET /github/imports/{id}/report`. Signed-out or expired sessions return to `/sign-in`. Imports are not created by these pages; stages start only through an explicit launch button.

The report page has the six-step rail from the design, per-task baseline measurements and file/line findings. Result compares the tested baseline and candidate on model calls, cost and wall time, then shows each task's outcomes, the verdict and its reason. Rejected changes remain completed results, with their measurements preserved and exports marked for review. Missing values display `Not recorded`; estimated savings stay hypotheses, and `needs_review` stays separate from passed checks.

The report's `next` field recommends the initial step; `?step=result` selects Result. It defaults to the latest optimization attempt; selecting another saves its job ID in `attempt`, so reloads and shared links preserve the choice. Bars use the selected comparison's own baseline and cover only its tested tasks. Automatic check counts appear when the API records them.

`Download patch` and `Copy prompt` fetch the selected job's `/patch` and `/handoff` endpoints. Downloads of changes that were not accepted have `-not-accepted.patch` filenames. Copy uses the API's exact Markdown handoff, including the rejected-change instructions. When clipboard access is denied, a selectable text field appears. Artifact failures keep the result visible and let the same button retry; an expired session returns to sign-in.

## Starting stages and following runs

Setup starts onboarding, Baseline starts a task baseline, Findings starts investigation, and Fix tests a saved finding or a custom goal. Finding links select the corresponding fix without launching it. Every start form shows its spend cap before the button and sends `X-CSRF-Token` from the current session. Agent stages default to $0.50 and allow up to $1.50; fix testing also has a separate candidate-run cap, default $0.50 and maximum $3.00. Baseline displays the current confirmed contract's spend limit, loaded from `/contract`; it sends only repetitions (1–5). A missing/stale/unconfirmed contract prevents launch. The baseline cap applies across all tasks and repetitions, not once per task.

These are recorded-spend thresholds. Calls and batches already underway can overshoot them; unknown costs stay unknown. This page does not alter task contracts or silently start prerequisite stages.

The report's `active.kind` and `active.job_id` reattach the live feed after reload. Events poll every second with `after` set to the highest received ID; rows are deduplicated and ordered. Agent stages use `/agent-jobs/{job}/events`; baselines use `/baseline-jobs/{job}/events`. The job endpoint is checked alongside events because an interrupted agent may finish without emitting a final event. Terminal jobs drain paginated history before polling stops, then refresh the report. Starts are hidden while a job runs.

The feed follows new rows until the reader scrolls up; `Follow latest` restores following. Desktop puts the feed beside recorded totals, while phones put totals first. Baseline totals sum completed run events; agent/target usage appears only when the job reports it. Elapsed time uses the server's creation timestamp and the browser clock. Failed reads keep existing rows and offer `Resume feed`. POST requests are never automatically retried; a lost or server-error response requires `Check run status` before another launch.

The public landing hero renders [`src/data/swarm-report.json`](src/data/swarm-report.json) in a read-only product window, opening on Findings. Every figure, source link and verdict comes from that saved report. The loop pauses on hover/focus, offscreen, in hidden tabs and under reduced motion; its controls also let visitors pause or select a view. Phone tabs become horizontal, with capability statements below the window. No stages, event polling or artifact exports are attached to this public preview. `Import a repository` leads to the existing authenticated imports page; import creation remains unimplemented.

How it works pins four scroll stages on desktop viewports at least 1024px wide and 720px tall. Step buttons select a scroll position. Phones, tablets, short screens and reduced motion show all four stages in normal flow. Changes to the system's motion preference apply while the page is open. A real run shows the last saved Swarm candidate's measured comparison, all six task outcomes, the rejection reason and findings. Its trace disclosure records queued export and unconfirmed readback; links require the import owner's session. These sections start no jobs or private API reads.

During development, `/app/dev/swarm-report?step=result` also previews the saved report, explicitly labelled as saved results. Its exports use [`swarm-patches.json`](src/data/swarm-patches.json) and [`swarm-handoffs.json`](src/data/swarm-handoffs.json). The latter was generated using the backend's deterministic handoff builder against the saved report and patches. The preview does not require sign-in or call live report/artifact endpoints. The preview route, patches and handoffs are excluded from production; the report itself is intentionally included for the landing hero. Live failures never fall back to these files.

Successful OAuth callbacks now redirect to the configured `FRONTEND_ORIGIN/app`; restart an already-running API to apply that code change. `/auth/me` remains a JSON endpoint for session checks. Navigation and the secondary hero action link to the implemented landing sections. The GitHub link opens GitHub's home page.

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
```

Pass a different skill directory as the first argument if needed, then an optional frontend URL and screenshot output directory. These checks use labelled API fixtures; they cover sign-in, imports/reports, selected result/reload, partial comparisons, task outcomes, bars with unknown/zero values, patch contents and filenames, prompt copying/manual fallback, artifact failures, expired sessions and layouts from 320px to 1440px. Accepted and unknown-result states are explicitly synthetic UI fixtures; the saved Swarm report remains rejected. They do not prove real OAuth or live authenticated exports.

The run checks use synthetic jobs for all four starts, exact caps/CSRF payloads, duplicate submission, ambiguous responses, reattachment, incremental/paginated events, scrolling, paused-feed recovery, terminal/restart status, rejected completion and expired sessions. They never dispatch a real model call or execute imported code. Stage launch is disabled in the saved preview.

The landing checks verify saved figures and fixed-commit links, keyboard tabs, preview pause/resume, motion preference changes, section links, four pinned and stacked stages, all task outcomes, trace links and 320–1440px layouts. They assert that no live job or private GitHub request starts.

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
