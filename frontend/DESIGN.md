# Hansa design

## Direction: light laboratory

Approved October 12, 2026. This replaces the earlier receipt and dark themes. Hansa is an optimization engineer for AI agents: it investigates source and execution, tests changes and reports the trade-offs. The page should make that work easy to understand and inspect.

Cool off-white, charcoal type, deep blue actions, thin rules and generous spacing. One closing band uses deep ink with light text and a light action button, giving the scroll a clear change in tone. The recorded experiment retains its light surface. Product evidence is the visual material. No decorative stock imagery, glass effects or simulated results.

## Tokens and assets

The shared tokens in `src/styles.css` apply to the landing and product pages.

| Role | Value |
| --- | --- |
| Page | `#F7F9FC` |
| Surface | `#FFFFFF` |
| Ink | `#182432` |
| Body | `#37485D` |
| Secondary text | `#45556A` |
| Borders | `#D5DFEA` |
| Blue action / focus | `#2458CA` |
| Blue wash | `#E9F0FF` |
| Hero loop highlight | `#08777D` on `#E4F4F1` |
| Passed checks | `#15734F` on `#E4F3EC` |
| Warning / regression | `#A75013` on `#FFF0DD` |

- Type: self-hosted Hanken Grotesk for headings and body; Geist Mono for code and short labels. Tabular figures for measurements.
- Reading scale: all captions, metadata and data labels have a 14px minimum; secondary explanations and form labels use 15px. Body and report prose remain 17px, walkthrough paragraphs 17–18px, step titles 20–22px and headings 28–36px. Reading text uses the darker body color, with 1.65–1.75 line height. Shared buttons/fields are 16px. On dark surfaces secondary text uses 80% light foreground. Shorten explanations before reducing type. Walkthrough columns stay wider on tablets.
- Recorded experiment proof: cost, latency, calls and input-token figures use 32–40px type, with 16px signed changes beside them. Resource reductions use the existing green token; increases use warning color. Labels and explanation captions are at least 14px. The grid becomes two columns at 1100px and one at 540px so larger figures stay readable.
- Logo: original side-profile swan SVG at `public/brand/mark.svg`, repeated at `public/favicon.svg`. Blue silhouette, curved neck, wing cutout and a small amber beak.
- Icons: the existing Lucide set.
- Landing content is limited to 1280px, with gutters shared with navigation. Product pages retain their existing wider layout.
- Two levels of depth: the hero diagram and recorded experiment use the same soft layered shadow with no outline. Process steps and app reading groups stay flat and borderless, separated by padding, gaps and section spacing. Form fields, selectable controls and keyboard focus retain visible boundaries; warning and outcome colors retain their meaning. Floating navigation controls keep their own interaction affordances.

## Landing structure

1. **Hero:** “An optimization engineer for your AI agent.” Explain source investigation, code changes, task testing and the reviewable result. `Analyze my agent` opens `/app/new`; `Explore the demo` goes to the saved experiment section. The diagram shows the saved Swarm run: original mean calls/cost → Hansa’s investigate/edit/test loop → tested patch, run scope and the rejected verdict. Its figures come from the saved report; the short hero cost is rounded to cents and the verdict counts regressions, not all changed answers.
2. **Demo run:** Baseline, Findings, Change and Verdict views from `src/data/swarm-report.json` and the matching saved patch. Tabs advance every five seconds while visible, with a thin progress line. Selecting a tab or interacting with the demo permanently stops autoplay. Its persistent summary shows six recorded fields: original/candidate cost, latency, model calls, input/output tokens, task behavior and run conditions. Spend/runtime caps are not present in this saved report and are not invented. Show failed baseline checks, review-needed answers, estimated findings and the rejected change. Link to the full `/demo` report and fixed-commit source. Browsing dispatches no jobs or private GitHub reads.
3. **How it works:** one connected sequence for connection, measurement, experimentation and review. Each step shows a saved Swarm artifact: a repository chip linking to the pinned commit, one bar segment per baseline model call, an actual added patch line linking to the full saved patch, and the rejected verdict with its regression count. Four connected steps run horizontally above 900px and vertically on smaller screens. These are saved examples, not live progress.
4. **Footer:** the page's single dark moment: a deep ink closing invitation with light text and a light action button, followed by the swan wordmark, recorded demo and existing author link on the same surface. Secondary text stays light enough to read; keyboard focus rings use the light foreground.

Section introductions stack directly beneath their headings, left aligned with a readable line length. Marketing headings have no numbered or mono eyebrows. Step descriptions use the main font. Mono is reserved for product data and code, including the tiny process artifacts. Homepage currency is shown to cents; time, counts and percentages are rounded to whole values. A note explains that percentages use the unrounded measurements. The app’s shared formatter and saved data retain their existing precision.

## Evidence and interaction

- Recorded results remain labelled. Automatic checks are not human confirmation or protected final evaluation.
- Findings are hypotheses; estimated savings are not measured improvements.
- Cost and time comparisons use their actual measurement boundaries. Missing values read `Not recorded`, never zero.
- The saved candidate has lower resource usage and a regression. Its patch is an experiment artifact, not an accepted recommendation.
- Demo tabs have explicit labels, a focusable panel and ArrowLeft/ArrowRight/Home/End keyboard navigation. Source details use native disclosures.
- Primary controls are at least 44px tall. Focus rings are visible; semantic outcomes appear in words as well as color.

## Motion

A single subtle 12px fade-and-rise for hero text and the diagram, 600–700ms. The diagram highlights Investigate → Edit → Test → Patch → Measurements → Verdict, 1.2 seconds per stage (7.2 seconds per loop). Highlight layers crossfade their opacity over 300ms with shared easing, without moving the text or changing the layout. Soft teal highlights distinguish the current step from blue actions and amber verdicts. Hover or keyboard focus holds the current stage; the diagram has no playback button. This is a visual walkthrough of saved evidence, with static measurements. Reduced motion disables the loop, renders the hero in place and disables smooth scrolling. Hover feedback uses 180–200ms transitions.

The demo's progress line fills over five seconds using a transform. An offscreen tab strip or a hidden document pauses autoplay; the current tab starts a fresh interval on return. Hover keeps the demo advancing. Keyboard focus or a click inside the demo hands control to the visitor for the rest of the visit. Verdict candidate figures tick from baseline to candidate over 1.1 seconds using eased interpolation. Intermediate frames are presentation only; accessible text always contains the final saved measurement. Reduced motion disables automatic tabs and renders final figures immediately. Frame callbacks and timers are cancelled when their views unmount.

Product buttons, tabs, links and row hovers respond in 120–160ms. New run events and resolved task labels slide up 8px and fade in over 180ms. The current step has a quiet 2.4-second pulse that stops when polling fails or the job finishes. Live task rows use the baseline contract or the current candidate experiment, and resolve only after their requested repetitions or a final task event arrive. Pending tasks remain incomplete when a job ends early; human review stays distinct from a pass. The trace panel slides in from the right over 220ms, with a 160ms backdrop fade. Reduced motion suppresses these animations through the shared preference rules.

## Implementation and checks

Reuse React/Vite/TypeScript, existing routing, shared components and dependencies. No new packages are needed for this redesign.

`npm run build` checks TypeScript and produces the static build. `scripts/check-landing.mjs` checks saved evidence, tab keyboard behavior, source links, navigation, reduced motion, readable contrast and layouts at 320, 375, 768, 1024 and 1440px. It mocks authentication and starts no model calls. See `README.md` for commands and API integration.
