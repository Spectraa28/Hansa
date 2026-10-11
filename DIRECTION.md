# Initial Hansa scaffold

The user supplied the direction in [`DESIGN.md`](DESIGN.md): a cool grid-paper surface, Hansa's swan mark, Bricolage Grotesque display type, Geist interface type and Geist Mono labels. This is an implementation of that brief, not a new design exploration.

The supplied direction also pins the hero: one large saved product window below a two-line desktop headline, not a new concept exploration. The request now includes pinned How it works and A real run. Other landing sections, editable setup, dark mode and social assets remain outside this request.

## Hero content and signature

Tag: `FOR TEAMS RUNNING AI AGENTS`. Headline: `Make your agent cheaper and faster. With proof.` The last phrase has a flat blue highlight. Subheading and the three capability statements follow DESIGN.md verbatim. Actions: `Import a repository` opens the existing authenticated imports page; `See a real run` scrolls to the saved experiment's evidence section. Import creation remains a separate feature.

The window reads `Saved Swarm run`, the JSON's repository and fixed commit, and four views: Import, Baseline, Findings, Verdict. It opens on the three saved findings, showing their first waste sentence, file/line links and only recorded estimates. Missing estimates say `Not quantified`. The incomplete investigation and hypothetical scope remain visible. Baseline uses the saved per-pass figures and all task statuses. Verdict uses the latest saved comparison and rejection reason; cheaper measurements never become green success badges.

Signature: a small drawn cursor advances through the saved views at a slow pace (nine seconds on Findings, six elsewhere). Hover, focus, a hidden/offscreen window and reduced motion stop the loop. Tabs pause it; an explicit Play/Pause control restores it. Desktop uses a vertical step rail and phone a horizontal strip. A blueprint leader labels each view. Entrances rise in 60ms-separated headline lines, the highlight wipes behind the phrase, and the window rises 24px. Scroll lifts/scales the window gently. Reduced motion shows the complete still view with no loop or scroll transform. These animations change only opacity and transforms.

This is a public, read-only rendering of `src/data/swarm-report.json`; no run, event polling or artifact export is attached to it. The saved report is intentionally shipped in the landing bundle. Development-only patches, handoffs and the authenticated preview route remain excluded.

## How it works and a real run

Visitor questions: how does the experiment work, and what did it actually decide? `How it works` reads `From repository to a measured decision.` Four stages: `Import` — hold the commit fixed; importing starts no execution. `Baseline` — measure the same tasks before editing. `Findings` — inspect waste with file/line evidence; estimates remain hypotheses. `Verdict` — compare the candidate and keep or reject the change. A shared saved-report panel follows four scroll stages over about 400svh. Step buttons scroll to their stage. Phones, tablets, short laptop viewports and reduced motion show all four stages as ordinary stacked sections, each with its own visual. Nothing takes over native scrolling.

`A real run` reads `The cheaper fix Hansa refused to ship.` It names the saved Swarm repository, commit, model, task count and repetitions. Ruled cells compare calls, cost and wall time from the latest complete candidate, then show all per-task baseline/candidate outcomes. Saved findings retain source links and hypothetical estimates. The verdict remains `Fix rejected`; the saved explanation and automatic-check limits sit beside it. Trace links point to the existing owner-only read endpoints and disclose queued export, not confirmed delivery. This section never fetches private reports or exports until a visitor explicitly follows a link.

## Content and layout

The navigation reads `Hansa`, `How it works`, `A real run`, `GitHub`, `Sign in` (or `Imports` when signed in). On phones, the section labels occupy a second row while the logo and sign-in control stay together. The logo stays 20px from the viewport's left edge on phones and 32px on larger screens, with a 40px gap before the desktop links. The nav uses the full viewport width.

`A real run` and `How it works` scroll to their landing sections, including when reached from an app route. GitHub currently links to its home page; Sign in navigates to `/sign-in`. React Router handles the landing, sign-in and `/app` routes. TanStack Query handles provider discovery, session checks and owner-scoped paginated imports.

Each import now opens `/app/imports/{id}`. On desktop the report uses a 180px rail down the left: `Import`, `Setup`, `Baseline`, `Findings`, `Fix`, `Result`. On phones it becomes a two-column step selector above the report; tablets use three columns. The selected panel lives in the `step` URL parameter, with the report's `next` recommendation as the default. The rail selects stored views and never dispatches a job.

Baseline content: model, repetitions, separate passed/failed/needs-review counts, `Mean per full task set`, then per-task model calls, input/output tokens, cost, wall time and check reasons. Missing measurements stay `Not recorded`; valid zero stays zero. Mean task values are not rounded to integer counts.

Findings content: saved investigation status and incomplete notice, each finding's file/line references at the fixed commit, waste description, explicitly hypothetical savings over cited runs, and expandable proposed change/risk/method text. Prose is capped at 65ch; important uncertainty notes are 13px. Fix shows saved attempt decisions and summaries.

Result content: `Tested fix` selector, `Fix accepted` / `Fix rejected` / `No improvement retained` / `No final verdict yet`, `Baseline vs candidate`, `Task outcomes`, `Why this verdict`, then `Take it to your coding agent`, `Download patch` and `Copy prompt`. The latest attempt is selected by default; the `attempt` query parameter records other choices. Full and partial task sets are labelled, with means over the compared tasks only. Task outcomes retain needs-review wording and automatic pass counts when stored. The candidate bars use blue, the baseline bars ink; every bar has a numeric label. Lower measurements remain neutral because cheaper does not imply correctness. Rejected results use an ink-on-pale-orange verdict band, with no error icon or alert. Accepted results use the existing pale green token.

The saved attempt summary explains the decision; its lightweight emphasis markers are removed for plain display, while the exact handoff stays intact. Accepted patch downloads have the normal filename; other patches have `-not-accepted` in their filename, and adjacent copy says not to apply unchanged. Clipboard denial reveals a selectable prompt field. Export errors stay beside the actions and do not replace the result. These artifact actions start no work.

Stage launch content: `Start onboarding`, `Start baseline`, `Start investigation`, `Test fix`, preceded by stage spend cap fields (USD) or the confirmed baseline contract's limit. Default stage caps are $0.50; fix testing shows optimizer and candidate caps separately plus their combined value. The recorded-spend caveat is directly above the launch action. Saved previews disable launch; prerequisite failures explain why. A finding's `Test this fix` link selects a fix form and starts no work. Lost start responses offer `Check run status`, never an automatic second POST.

An active job replaces the launch form with the live feed. Its saved spend caps appear with recorded totals, so a reload does not confuse default next-run caps with the active job's limits. Desktop uses feed left/totals right; phones put totals above the bounded scrolling log. Copy: `Updates every second`, `Feed paused`, `Resume feed`, `Follow latest`, `Polling stopped`; terminal backend `ready` renders `completed`. Rejected completion has a verdict line, not an error alert. Events enter with a 4px/180ms opacity/translate animation, disabled under reduced motion. Scrolling up pauses following; no forced page scroll. Completed-run totals and unknown agent usage retain their measurement boundaries.

`/app/dev/swarm-report` is a development-only preview of the supplied saved JSON. It is clearly labelled and excluded from the production build; the authenticated report route never substitutes it for an API failure.

Sign-in content: `Sign in to Hansa`, `Continue to your imported repositories.`, enabled `Continue with GitHub` / `Continue with Google` actions, and an email/password form when enabled. Loading, fetch error/retry, disabled-provider and failed-submission states are explicit.

Imports content: `Your imports`, the signed-in name, `Refresh imports`, repository name, status, branch, commit and imported date, then `Previous` / `Next`. The list uses a single ruled surface with no metric cards. Loading, empty, error/retry and expired-session states are explicit; long repository and branch names wrap. Page numbers live in the URL. No import creation or agent execution is added.

## Shared styles

[`src/styles.css`](src/styles.css) contains the exact colour variables from the design, their Tailwind v4 theme mappings, the three local font faces, control/card/window radii, focus ring and 32px grid at 45% line opacity. The navigation's paper surface fades the grid behind its text. Display and interface fonts are preloaded in [`index.html`](index.html).

Geist is deliberate: it is pinned by the supplied design and is the interface face shared with the planned product. The scan's default-font warning does not justify replacing it.
