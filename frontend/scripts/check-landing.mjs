// Saved report only; auth is mocked and no stages or paid calls may start.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const skill = process.argv[2]
assert(skill, 'Pass the installed web-designer skill directory.')
const base = process.argv[3] || 'http://localhost:5173'
const out = process.argv[4] || '/tmp/hansa-hero-check'
await fs.mkdir(out, { recursive: true })
const report = JSON.parse(await fs.readFile(new URL('../src/data/swarm-report.json', import.meta.url), 'utf8'))
const { launch } = await import(pathToFileURL(path.join(skill, 'scripts/lib/browser.mjs')))
const scanner = await fs.readFile(path.join(skill, 'scripts/lib/inpage.js'), 'utf8')
const { browser } = await launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await context.route(`${base}/auth/me`, route => route.fulfill({ status: 401, json: { detail: 'Sign in to continue.' } }))
await context.route(`${base}/auth/providers`, route => route.fulfill({ json: { github: true, google: false, email: false } }))
const requests = [], errors = []
context.on('request', request => { if (request.method() !== 'GET' || new URL(request.url()).pathname.startsWith('/github/')) requests.push(request.url()) })
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
await page.clock.install()

async function selected(name) { assert.equal(await page.getByRole('tab', { name, exact: false }).getAttribute('aria-selected'), 'true') }
async function open() {
  await page.goto(base)
  await page.locator('#saved-run-panel .hero-findings li').first().waitFor()
  await page.evaluate(() => document.fonts.ready)
}

await open()
assert.match(await page.locator('h1').innerText(), /Make your agent cheaper\s+and faster\. With proof\./)
assert.equal(await page.getByRole('link', { name: 'Import a repository' }).getAttribute('href'), '/app')
await selected('Findings')
assert.equal(await page.locator('#saved-run-panel .hero-findings li').count(), report.investigation.findings.length)
assert.match(await page.locator('#saved-run-panel').innerText(), /\$0\.033/)
assert.match(await page.locator('#saved-run-panel').innerText(), /\$0\.005/)
assert.match(await page.locator('#saved-run-panel').innerText(), /Not quantified/)
assert.match(await page.locator('#saved-run-panel').innerText(), /not measured gains/)
assert.match(await page.locator('#saved-run-panel').innerText(), /Investigation incomplete/)
for (const finding of report.investigation.findings) for (const source of finding.source) {
  const line = `#L${source.start_line}${source.end_line !== source.start_line ? `-L${source.end_line}` : ''}`
  assert.equal(await page.locator('#saved-run-panel .hero-sources a').filter({ hasText: `${source.path}:${source.start_line}` }).getAttribute('href'), `https://github.com/${report.import.repository}/blob/${report.import.commit_sha}/${source.path}${line}`)
}

// Timers are accelerated, not real API runs.
await page.mouse.move(0, 0)
await page.clock.runFor(9200)
await selected('Verdict')
assert.match(await page.locator('#saved-run-panel').innerText(), /Fix rejected/)
assert.equal(await page.locator('#saved-run-panel [role=alert]').count(), 0)
await page.locator('#swarm-run').hover()
await page.clock.runFor(20000)
await selected('Verdict')
await page.locator('#saved-run-panel').focus()
await page.mouse.move(0, 0)
await page.clock.runFor(20000)
await selected('Verdict')
await page.locator('#saved-run-panel').evaluate(el => el.blur())
await page.clock.runFor(6200)
await selected('Import')
assert.match(await page.locator('#saved-run-panel').innerText(), new RegExp(report.import.commit_sha))
await page.getByRole('tab', { name: /Import/ }).focus()
await page.keyboard.press('ArrowRight')
await selected('Baseline')
assert.equal(await page.locator('#saved-run-panel .hero-task-list li').count(), report.baseline.tasks.length)
assert.match(await page.locator('#saved-run-panel .hero-baseline-totals').innerText(), /40/)
assert.match(await page.locator('#saved-run-panel .hero-baseline-totals').innerText(), /\$0\.2243538/)
await page.keyboard.press('End')
await selected('Verdict')
for (const key of ['model_calls', 'cost_usd', 'wall_time_seconds']) {
  const metric = report.optimizations.at(-1).comparison.totals[key]
  const unit = key === 'cost_usd' ? `$${metric.candidate.toLocaleString('en-US', { maximumSignificantDigits: 7 })}` : metric.candidate.toLocaleString('en-US', { maximumFractionDigits: 2 })
  assert((await page.locator('#saved-run-panel .hero-comparison').innerText()).includes(unit))
}
await page.getByRole('link', { name: 'See a real run', exact: true }).click()
await selected('Findings')
assert.equal(new URL(page.url()).hash, '#real-run')
await page.clock.runFor(30000)
await selected('Findings')

await page.getByRole('button', { name: 'Play saved run preview' }).click()
await page.locator('#swarm-run').evaluate(el => el.contains(document.activeElement) && document.activeElement.blur())
await page.mouse.move(0, 0)
await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')) })
await page.clock.runFor(30000)
await selected('Findings')
await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: false }); document.dispatchEvent(new Event('visibilitychange')) })
await page.evaluate(() => scrollTo(0, 0))
await page.setViewportSize({ width: 1440, height: 500 })
await page.waitForTimeout(200)
assert((await page.locator('#swarm-run').boundingBox()).y > 500)
await page.clock.runFor(30000)
await selected('Findings')

await page.emulateMedia({ reducedMotion: 'reduce' })
for (const width of [320, 390, 768, 1280, 1440]) {
  await page.setViewportSize({ width, height: width < 640 ? 844 : 900 })
  await open()
  await page.clock.runFor(30000)
  await selected('Findings')
  assert.equal(await page.getByRole('button', { name: 'Still saved run preview' }).isDisabled(), true)
  assert.equal(await page.getByRole('tablist').getAttribute('aria-orientation'), width < 640 ? 'horizontal' : 'vertical')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.evaluate(scanner)
  const scan = await page.evaluate(() => window.__wd.scan())
  assert.deepEqual(scan.fails, [], `${width}px landing scan`)
  await page.locator('#swarm-run').screenshot({ path: path.join(out, `${width}.png`) })
  for (const view of ['Import', 'Baseline', 'Verdict']) {
    await page.getByRole('tab', { name: new RegExp(view) }).click()
    await selected(view)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.locator('#swarm-run').screenshot({ path: path.join(out, `${width}-${view.toLowerCase()}.png`) })
  }
}
await page.getByRole('link', { name: 'Import a repository' }).click()
await page.waitForURL('**/sign-in')
await page.getByRole('link', { name: 'A real run', exact: true }).click()
await page.locator('#saved-run-panel .hero-findings li').first().waitFor()
assert.equal(new URL(page.url()).pathname, '/')
assert.equal(new URL(page.url()).hash, '#real-run')
assert.equal(await page.locator('.real-task-summary').count(), report.optimizations.at(-1).comparison.tasks.length)
assert.equal(await page.locator('.real-task-reason td').getAttribute('colspan'), '3')
assert(!await page.locator('.real-limits').innerText().then(text => text.includes('needs_review')))
assert.equal(await page.locator('.real-task-table .is-regressed').count(), report.optimizations.at(-1).comparison.tasks.filter(task => task.regressed).length)
assert.match(await page.locator('.real-verdict').innerText(), /Fix rejected/)
assert.match(await page.locator('.real-verdict').innerText(), /not confirmed within the remaining budget/)
assert.match(await page.locator('.real-findings').innerText(), /not measured gains/)
await page.locator('.real-traces summary').click()
assert.equal(await page.locator('.real-traces').getByRole('link').count(), report.optimizations.at(-1).trace.trace_ids.length)
assert.match(await page.locator('.real-traces').innerText(), /export queued/)
assert.match(await page.locator('.real-traces').innerText(), /Readback is not confirmed/)
for (const id of report.optimizations.at(-1).trace.trace_ids) assert.equal(await page.locator(`.real-traces a[href$="/${id}"]`).count(), 1)

// Reduced motion stacks all four complete stages, with no 400vh spacer.
await page.setViewportSize({ width: 1440, height: 900 })
await page.goto(base)
assert.equal(await page.locator('.how-sticky').evaluate(el => getComputedStyle(el).position), 'static')
for (const scene of await page.locator('.how-scene').all()) assert(await scene.isVisible())
await page.emulateMedia({ reducedMotion: 'no-preference' })
await page.clock.runFor(200)
assert.equal(await page.locator('.how-sticky').evaluate(el => getComputedStyle(el).position), 'sticky')
assert((await page.locator('.how-track').boundingBox()).height >= 3600)
await page.getByRole('link', { name: 'How it works', exact: true }).click()
for (let index = 0; index < 4; index++) {
  await page.locator('.how-nav button').nth(index).click()
  await page.clock.runFor(300)
  await page.waitForTimeout(100)
  assert.equal(await page.locator('.how-nav button').nth(index).getAttribute('aria-current'), 'step')
  assert.equal(await page.locator('.how-scene.is-active').getAttribute('data-stage'), ['import', 'baseline', 'findings', 'verdict'][index])
  assert.equal(await page.locator('.how-scene.is-active').isVisible(), true)
  await page.screenshot({ path: path.join(out, `pinned-${index}.png`) })
}
for (const [width, height] of [[390, 844], [768, 900], [1280, 610]]) {
  await page.setViewportSize({ width, height })
  assert.equal(await page.locator('.how-sticky').evaluate(el => getComputedStyle(el).position), 'static')
  for (const scene of await page.locator('.how-scene').all()) assert(await scene.isVisible())
}
assert.deepEqual(requests, [], 'Landing preview must not dispatch stages or read protected GitHub endpoints.')
assert.deepEqual(errors, [])
await browser.close()
console.log('Landing checks passed: saved hero, four pinned/stacked stages, measured real run, trace links, keyboard, preview pause/reduced motion, routes and 320–1440px layouts. No live runs started.')
