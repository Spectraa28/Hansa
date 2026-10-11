# Scaffold verification

Scope: the navigation, logo and shared visual foundation only. The blank grid is explicitly requested. Whole landing-page criteria, product evidence, signature motion and alternate directions do not apply at this stage.

## Round 1

`npm run build` passed TypeScript and the production build. Web Designer's rendered scan passed at 390, 768, 1280 and 1440px with no failures. Its one warning is the deliberately selected Geist font; see [`DIRECTION.md`](DIRECTION.md).

An independent critic reviewed the code, the four viewport screenshots and matrix results:

| Applicable criterion | Score | Finding |
| --- | --- | --- |
| Typography | 4/5 | Clear hierarchy; no clipping. |
| Colour | 4/5 | Supplied ink, paper and faint grid are preserved. |
| Craft | 4/5 | Clean alignment, spacing and control radius. |
| Responsive | 4/5 | Deliberate two-row phone layout; balanced desktop row. |
| Platform checks | 3/5 | Available matrix passes are clean; browser-engine gaps remain. |

Scoped verdict: ready to ship the scaffold; no concrete visual defect requires an edit. No design changes followed this review.

## Round 2

Confirmation scans at 320, 390 and 1440px passed with no failures and the same deliberate font warning. This confirms the narrow layout; it is not a new critique or a claim of a complete landing page.

## API and platform checks

Direct and proxied unauthenticated requests to `/auth/me` and `/github/connection` each returned HTTP 401. The GitHub sign-in flow was not exercised.

The Chromium matrix passed Windows scaling at 125%/150%, forced colours, Linux/macOS/Android simulations, 320px reflow, reduced motion and expanded labels. These are simulations on the current host, not real-device checks. Firefox, Safari and Safari/iPhone passes were skipped because Firefox and WebKit are not installed. Screen readers and real-device performance were not checked.

Render artifacts are in `/tmp/hansa-nav-r1`, `/tmp/hansa-nav-r2` and `/tmp/hansa-nav-matrix`; these temporary files are not committed product assets.

## Sign-in and imports extension

The next request adds `/sign-in` and the authenticated `/app` imports list, redirects OAuth success to `FRONTEND_ORIGIN/app`, and moves the nav logo to a fixed left inset. The pinned design is preserved.

The initial live sign-in scan found subtitle contrast below 4.5:1 over grid lines. A 95% paper wash behind page content fixed that issue. Expected unauthenticated HTTP 401 responses and development StrictMode request cancellation appeared in the live scanner's request log; they are covered as expected behavior in the fixture checks.

`scripts/check-ui.mjs` passed with labelled API fixtures, capturing sign-in, populated imports and long values at 320, 390, 768, 1280 and 1440px. Every captured layout passed the skill's in-page scan and sideways-scroll assertion. The logo's actual left position is asserted as 20px on phones and 32px on larger screens. These fixtures cover enabled/disabled providers, provider errors/retry, email failure/success, signed-out access, pagination, list errors/retry, empty results and session expiry. No real account or import was created.

The independent reviewer scored typography, colour, craft and responsive behavior 4/5 each, with no concrete visual defect in the requested scope. Hero, product detail, import creation and agent runs remain outside the request.

The production build and 12 backend authentication tests passed. Both provider callbacks use mocked identities to verify the fixed frontend redirect, rejection of a caller-supplied redirect destination and creation of a usable HttpOnly session. These do not prove a fresh real Google/GitHub OAuth flow. The removed backend testing UI left a stale router import; that registration was removed so the API can start.

The second fixture round passed after adding plain-language network-error copy and wrapping long account names. It verifies those cases alongside the earlier flows; the production build also passed afterward. Latest fixture render artifacts: `/tmp/hansa-app-r2`.

The sign-in platform matrix in `/tmp/hansa-signin-matrix` passed every available Chromium simulation, with no failures. Firefox and WebKit remain unavailable. A running API needs a restart to load the redirect change. Development must consistently use `localhost` for OAuth state and session cookies.

## Import report extension

`/app/imports/:id` reads the stored report, with the design's left step rail, baseline measurements for each task and findings linked to file lines at the imported commit. This scope is read-only; stage execution and live event feeds remain separate work. The supplied Swarm JSON is a development-only preview, excluded from the production bundle.

The first render review found overly long finding prose and small uncertainty copy. Prose now has a 65-character maximum width and uncertainty text is 13px. The independent critic also requested “Mean per full task set” instead of “Mean per complete task pass”, so that the aggregate cannot be confused with the count of passed correctness checks; the raw `per_pass` field name was removed from its explanatory note.

The final fixture suite passed at 320, 390, 768, 1280 and 1440px with no rendered scan failures or sideways scrolling. It checks import links, signed-out access, errors/retry, session expiry, step navigation/reload, missing stages, all six baseline tasks, precise costs, unknown measurements, fixed-commit source links and the isolated development preview. These are saved-report fixtures, not fresh API or agent-run evidence. Final screenshots are in `/tmp/hansa-report-final`.

The independent critic confirmed the wording correction resolves the remaining concern, scoring typography, colour, craft and responsive behavior 4/5 each, with no further concrete defect in this scope.

The production build passed. The report preview's second rendered scan passed with only the deliberately selected Geist warning. Every available Chromium platform simulation passed in `/tmp/hansa-report-matrix`; Firefox and WebKit remain unavailable. A live authenticated report fetch has not been exercised.

## Tested-fix result extension

Result now compares the selected optimization attempt against its own baseline, with paired calls/cost/time bars, full/partial task-set labels, per-task outcomes, the saved verdict/reason and patch/prompt exports. The two original Swarm fixes remain rejected. Their measurements and artifacts are available for review; rejection has a pale-orange result band and no alert/error treatment.

Round 1 passed the fixture scan at 320, 390, 768, 1280 and 1440px. The independent reviewer scored typography, colour, responsive behavior and information hierarchy 4/5, with craft 3/5 pending two corrections: zero/missing bars still drew tiny colored border ticks, and the task note displayed the raw `needs_review` field. Both were corrected in round 2; the empty bar fill is now hidden and the note says `Needs review`.

The second fixture round passed all earlier checks plus result selection/reload, full/partial scope, task outcomes, precise costs, zero/missing values, accepted and rejected filenames, downloaded patch contents, exact copied handoff, clipboard denial/manual copy, artifact failure and later success, and expired-session redirect. Clipboard checks use a page-local stub, leaving the host clipboard untouched. Accepted and unknown-result screens are explicitly synthetic UI fixtures, not measured Swarm acceptance. The saved preview's exports are checked to avoid live API calls. Latest screenshots: `/tmp/hansa-result-r2`.

The reviewer confirmed both corrections are visible, raised craft to 4/5 and found no further concrete visual defect in this scope.

The live development preview scan in `/tmp/hansa-result-preview-r1` passed with only the deliberate Geist warning and expected unauthenticated session responses. All available Chromium platform simulations passed in `/tmp/hansa-result-matrix`, including forced colours and 320px reflow; Firefox/WebKit were unavailable. These are simulations, not real-device checks.

The production build and whitespace checks passed. The preview route, saved report, patches and handoff prompts are verified absent from the production bundle. Live authenticated report/artifact requests, system clipboard permissions, Firefox and Safari remain unverified. No agent run or repository change was started by this page.

## Stage controls and polling feed

The stage forms show spend thresholds before launch. Baseline displays the confirmed contract's cap and submits repetitions only; fix testing separates agent and candidate-run caps. The active job hides launch controls and shows its own saved caps beside the feed. Reload reattaches using `active.kind` and `active.job_id`; no start request is made automatically. Stored result/artifact actions remain separate from stage launch.

Round 1's synthetic-job suite and the existing report/result suite passed. The independent critic scored typography, colour, responsiveness and information hierarchy 4/5, with craft 3/5 pending one label correction: terminal backend `ready` looked like a job waiting to start. Round 2 displays `completed`; the critic confirmed craft 4/5 and no further scoped visual defect.

The final run suite passed at 320, 390, 768, 1280 and 1440px with no scan failures or sideways scrolling. It verifies all four POST payloads and CSRF headers, duplicate-submit blocking, confirmed/stale/unavailable baseline caps, goal/finding selection, cursor/deduplication, reload reattachment, feed pause/resume, scroll-up retention, following latest, paginated terminal history, completion without a final event, rejected completion, start-response ambiguity and session expiry. The saved preview cannot launch a stage. These jobs are synthetic; no real model calls, Docker runs or imported-source execution were dispatched. Final screenshots: `/tmp/hansa-runs-final`; existing-flow regression screenshots: `/tmp/hansa-runs-regression`.

Available Chromium platform simulations passed in `/tmp/hansa-runs-matrix` for the disabled spend-cap preview, including scaling, forced colours, 320px reflow and reduced motion. This matrix does not establish live-feed behavior on those platforms; the feed was checked against synthetic jobs at the five viewport widths. Firefox and WebKit remain unavailable.

The production build, script syntax and whitespace checks passed. Saved development data remains excluded from the production bundle. Live authenticated stage execution, actual spend/runner enforcement, Firefox/Safari and real devices remain unverified by this frontend change. Caps are soft recorded-spend thresholds: an in-flight call or batch can exceed the shown amount.

## Landing hero, pinned walkthrough and real run

The hero follows the supplied DESIGN.md headline and layout, with four read-only saved-report views. How it works pins those four stages only on roomy desktop screens; other viewports and reduced motion show complete stacked stages. A real run preserves the latest Swarm candidate's rejected decision, full task comparison, hypotheses and queued trace status. The public saved report is now intentionally included in production; development-only patch/handoff artifacts and their preview route remain excluded.

Hero round 1 requested uncertainty above the findings, larger muted unknown-value copy on phones, space before the highlighted phrase, a compact phone introduction and ruled capability rows. Round 2 incorporates all five. The complete 27-second loop was captured and reviewed at all four views; reduced motion produces a still panel.

The new sections' first critique found a narrow phone regression explanation and a raw `needs_review` value in the limits note. Round 2 gives the explanation a full-width table row and displays `Needs review`. Both corrections were independently confirmed. Final scores:

| Criterion | Round 1 | Round 2 |
| --- | --- | --- |
| Concept | 4 | 4 |
| Category distinction | 4 | 4 |
| Avoids slop faces | 4 | 4 |
| First screen | 3 | 3 |
| Typography | 4 | 4 |
| Colour | 4 | 4 |
| Richness | 4 | 4 |
| Structure/rhythm | 4 | 4 |
| Craft | 3 | 4 |
| Responsive | 3 | 4 |
| Everyone's computer | 3 | 3 |
| Signature | 4 | 4 |
| Screenshot test | 4 | 4 |

Done by the skill's stop rule: 11 of 13 scores at 4, none below 3, no scan failures. The phone first screen introduces the product window before a complete finding; the pinned headline and minimum display scale remain intentional.

All scan warnings are accounted for: Geist and the two-part headline are explicitly supplied in DESIGN.md; 11px mono text is product-window metadata, source references and supplementary captions; 13px copy is compact saved-product evidence and uncertainty, with section prose at 15px or larger. Uppercase labels identify distinct report views repeated in the walkthrough. The window surrounds actual interface rows rather than decorative cards; the real-run evidence uses shared rules. Long-line warnings include source identifiers and saved explanation text; prose is capped at 65ch. Expected unauthenticated 401 responses and StrictMode cancellation are not landing failures. Blank full-page slices represent the sticky scroll track; individual viewport captures confirm all four stages are visible during scrolling.

Final scans and visual review covered 320, 390, 768, 1280 and 1440px, every numbered full-page slice and each pinned state. Assert-based checks cover saved measurements/links, keyboard navigation, pause conditions, live changes to reduced-motion preference, section routes, pinned/static fallbacks, task outcomes and trace URLs. They assert no GitHub requests or job starts. Existing sign-in/report/result checks and stage/feed regressions also pass with labelled fixtures. The build and 12 mocked backend authentication tests pass.

Artifacts: `/tmp/hansa-landing-sections-r2`, `/tmp/hansa-landing-sections-final`, `/tmp/hansa-hero-loop`, `/tmp/hansa-how-film`, `/tmp/hansa-landing-matrix-final` and `/tmp/hansa-final-run-regression`. Chromium platform checks are host simulations, not real-device proof. Firefox/WebKit, screen readers, fresh OAuth, live stage execution and authenticated trace readback remain unverified. Remaining landing sections and collateral were outside the requested scope.
