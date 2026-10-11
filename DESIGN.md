# Hansa design

The plan for the product interface and landing page. The landing hero, pinned How it works, saved real run, sign-in, imports list, import report/result, stage starts and polling run feed are implemented, along with the nav, logo, colour tokens, fonts and grid-paper background; editable setup and other landing sections are planned. The fonts and the mark are in `public/`.

## Direction

Teak's skeleton in Hansa's colours, with Billow's hero.

- From [Teak](https://teak.io): grid-paper background, ruled cells that share borders, mono tab labels on boxes, a stat row under the call to action, one highlighted phrase in the headline.
- From [Billow](https://billow.so): one large real product window directly under the headline, and a three-step row.
- Left out: Teak's candy palette and confetti, Billow's serif and painted clouds.

The page should read like a lab notebook for an agent: measured, annotated, a little playful in the type.

## Tokens

Same values as the launch video, so the two look like one product.

| Token | Value | Use |
| --- | --- | --- |
| `--paper` | `#EDF2F7` | Page background |
| `--surface` | `#FFFFFF` | Cards, product window |
| `--wash` | `#F5F8FB` | Window bars, table headers |
| `--ink` | `#0B1A2C` | Text, dark tiles, primary button |
| `--muted` | `#5C6C82` | Secondary text |
| `--line` | `#D5DEE9` | Every border and the grid |
| `--blue` / `--blue-soft` | `#1453F5` / `#E2EAFF` | Links, focus, the one accent |
| `--waste` / `--waste-soft` | `#FF6426` / `#FFE8DC` | Waste and regressions only |
| `--ok` / `--ok-soft` | `#0B9A69` / `#DAF4EA` | A proven gain only |

Rules: orange and green carry meaning, so they never decorate. Radius is 6px on controls, 14px on cards, 20px on the product window. Borders are 1px `--line`; shadows only on the product window and popovers. Light theme only for now.

The grid paper is a CSS background on `body`: two 1px `--line` gradients at 32px, at about 45% opacity, fading out behind text blocks.

## Type

| Role | Face | Settings |
| --- | --- | --- |
| Display | Bricolage Grotesque (variable) | weight 720–780, tracking −0.035em, line height 1.02 |
| Interface and body | Geist (variable) | 15px/1.55 body, weight 400–600 |
| Labels, numbers, code | Geist Mono (variable) | 12px uppercase labels with 0.06em tracking; `tabular-nums` on all figures |

Scale: 12, 13, 15, 18, 24, 34, 52, 84 (hero, clamped down to 44 on phones).

## Assets

| Asset | Where | Notes |
| --- | --- | --- |
| Fonts | `public/fonts/*.woff2` | Latin variable files, self-hosted, OFL licences alongside. Preload display and UI faces. |
| Mark | `public/brand/mark.svg`, `public/favicon.svg` | Swan on an ink tile with an orange beak. Inline it where the neck stroke animates. |
| Icons | `lucide-react` | 1.75 stroke, 16 or 18px. No other icon set. |
| Product visuals | Built in code | The hero window and step visuals are real components fed by a saved report, not screenshots. |
| Charts | Hand-built SVG | Paired bars and a per-call timeline. No chart library. |
| Launch video | `~/Documents/launch-video/out/hansa-launch.mp4` | Embedded lower on the page, not in the hero. |
| Social image | `public/og.png` | 1200×630, rendered from the hero. To do. |

No stock illustration, 3D or generated imagery. The product is the picture.

## Stack

| Need | Choice | Why |
| --- | --- | --- |
| App | React 19, Vite, TypeScript | Static build that nginx can serve next to the API on one instance. |
| Styling | Tailwind v4 with the tokens above as theme variables | Fast to write and easy to keep consistent. |
| Components | shadcn/ui, copied in as needed | Accessible Radix primitives we own and restyle. Only dialog, tabs, tooltip, popover, select, toast. |
| Animation | Motion (`motion/react`) | One library covers enter/exit, layout changes and scroll-linked values. |
| Numbers | `@number-flow/react` | Figures roll when a run updates. |
| Code and diffs | Shiki, loaded lazily | Accurate highlighting for the patch view. |
| Data | TanStack Query | Polling `events?after=N` with caching and retries. |
| Routing | React Router | Landing page plus a handful of app routes. |

Considered and not used:

- **GSAP ScrollTrigger**: stronger for long choreographed timelines, but it would be a second animation system next to Motion for one pinned section.
- **Lenis smooth scroll**: taking over the wheel feels laggy on trackpads and fights the pinned section. Native scroll stays.
- **Lottie or Rive**: nothing to play; the visuals are live components.
- **A chart library**: two chart types do not justify the weight or the default look.

## Motion

One easing for entrances, `cubic-bezier(.2, .8, .2, 1)` at 400–600ms. Springs (stiffness 260, damping 30) for things the user moves. Only `transform` and `opacity` animate. With `prefers-reduced-motion`, everything appears in place and the pinned section becomes a plain stacked list.

### Page load

1. Grid paper fades in.
2. Headline rises line by line, 60ms apart. The highlight wipes in behind the last phrase.
3. The swan's neck draws in the nav mark.
4. The product window rises 24px and settles, then starts its loop.

### Scrolling

| Section | Behaviour |
| --- | --- |
| Hero | Window scales from 1 to 0.96 and lifts slightly as it leaves. Nothing else moves. |
| How it works | **The one pinned section.** A sticky two-column block, about 400vh tall. Left: four steps, the active one lit by scroll position. Right: one product window whose contents change per step. Driven by `useScroll` on the section and `useTransform` per step. |
| Real run | Cells reveal once as they enter view, staggered by column. Figures count up once. |
| Everything below | A single fade-and-rise per block on first view. No parallax. |

The pinned steps:

1. **Import**: the repository row fills in; an annotation notes the commit is fixed and nothing runs on import.
2. **Baseline**: calls stream into a timeline; cost and time tick up.
3. **Findings**: three cards slide in, each with a file and line reference.
4. **Verdict**: paired bars draw, then the verdict stamps.

On phones the block unpins and the four steps stack, each with its own visual.

### Interaction

- **Hero window**: plays a short loop with a drawn cursor (import, baseline, finding, verdict). Hovering pauses it; clicking a tab jumps to that state.
- **Annotations**: small mono callouts with a leader line point at parts of the window, in the style of a blueprint. They appear on hover on desktop and in sequence during the loop.
- **Ruled cells**: border darkens to `--ink` and the tab label fills on hover. No lift, no shadow.
- **Buttons**: primary is an ink pill with an arrow that moves 3px on hover; press scales to 0.98.
- **Focus**: 2px `--blue` ring with 2px offset, everywhere.

## Landing page

### Hero

- **Nav**: mark and "Hansa", then `How it works`, `A real run`, `GitHub`. Right: `Sign in`.
- **Tag** (mono, above the headline): `FOR TEAMS RUNNING AI AGENTS`
- **Headline**: Make your agent cheaper and faster. **With proof.**
- **Sub**: Import your agent's repository. Hansa runs it, finds the calls it is wasting, tests the fix against your baseline, and hands you a patch that is measured to work.
- **Primary button**: `Import a repository`
- **Secondary**: `See a real run`
- **Stat row** (mono, what you get rather than a result):
  - `1 repo` in, no SDK to install
  - `File + line` on every finding
  - `Patch or prompt` out, ready for your coding agent
- **Product window**: the findings view of the Swarm run, with the three findings and their estimated savings. It shows the product doing the valuable thing.

The hero sells the outcome. It makes no claim about a result we have not measured: the stat row describes the product, and the window shows real findings.

The rejection moves to **A real run**, where it works as proof: the tested fix cut calls by 10% but failed one task in one of two repetitions, so Hansa refused to ship it. If a later run produces an accepted patch, its measured saving replaces the stat row.

Every figure on the page comes from a saved report. Nothing is illustrative.

### Sections

1. **Hero**
2. **How it works**: the pinned four steps.
3. **A real run**: the Swarm result in ruled cells: findings, the comparison table, the verdict and why. Links to the traces.
4. **What you get**: three cells: a patch, a prompt for your coding agent, a report with reproduction steps.
5. **How it stays safe**: sandboxed runs, throwaway keys with a spend cap, your source never leaves the snapshot.
6. **Built with**: Neatlogs for traces, Entire for checkpoints, each with one sentence on what it did.
7. **Launch video and closing call to action**

## Product screens

One import is one page with a step rail down the left: `Import → Setup → Baseline → Findings → Fix → Result`. The report's `next` field decides which step is offered.

| Screen | What matters |
| --- | --- |
| Imports | List of repositories with status and last verdict. One button: import. |
| Setup | Detected settings and tasks, editable, with a quick-mode default (3 tasks, 1 repetition). |
| Run (baseline, investigation, fix) | Live event feed on the left, running totals for calls, cost and time on the right. The spend cap is visible before starting. |
| Findings | Cards with evidence: file and line, the calls involved, estimated saving. One action each: test this fix. |
| Result | Paired bars for calls, cost and time; per-task pass or fail; the verdict in words. Then `Download patch`, `Copy prompt`, or `Run again to confirm`. |

Live feeds poll `events?after=N` every second while a job runs and stop when it ends. New rows slide in from the bottom; the view stays pinned to the latest unless the user scrolls up.

States each screen needs: empty, running, failed with the reason, rejected with the reason, and done. Rejected is styled as a result, not an error.

## Build order

1. Scaffold, tokens, fonts, grid background, base components.
2. Product screens against the live API, using the existing Swarm import.
3. Landing hero with the product window fed by a saved report.
4. Pinned section, then the remaining sections.
5. Reduced-motion and phone-width pass, social image.
