// Synthetic GET-only runs and trace readback; no execution or model calls.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const skill = process.argv[2]
assert(skill, 'Pass the installed browser helper directory.')
const base = process.argv[3] || 'http://localhost:5173'
const out = process.argv[4] || '/tmp/hansa-live-motion'
await fs.mkdir(out, { recursive: true })
const { launch } = await import(pathToFileURL(path.join(skill, 'scripts/lib/browser.mjs')))
const scanner = await fs.readFile(path.join(skill, 'scripts/lib/inpage.js'), 'utf8')
const { browser } = await launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
page.setDefaultTimeout(10000)
const errors = [], mutations = []
page.on('pageerror', error => errors.push(error.message))
const report = JSON.parse(await fs.readFile(new URL('../src/data/swarm-report.json', import.meta.url), 'utf8'))
const names = report.baseline.tasks.slice(0, 3).map(task => ({ name: task.name }))
report.baseline = null
report.active = { kind: 'baseline', job_id: 'synthetic-baseline-motion' }
let job = { status: 'running', created_at: Math.floor(Date.now() / 1000), repetitions: 2, contract: { limits: { max_spend_usd: 0.5 }, tasks: names } }
let events = [], offline = false
const append = (kind, data) => events.push({ id: events.length + 1, kind, data, created_at: Math.floor(Date.now() / 1000) })
append('started', {})
await context.route(`${base}/auth/**`, route => route.fulfill({ json: { user: { id: 'motion-fixture-owner', name: 'Motion fixture' }, csrf_token: 'fixture' } }))
await context.route(`${base}/github/**`, route => {
  const request = route.request(), url = new URL(request.url())
  if (request.method() !== 'GET') { mutations.push(url.pathname); return route.abort() }
  if (url.pathname.endsWith(`/${report.import.import_id}`)) return route.fulfill({ json: { ...report.import, id: report.import.import_id, status: 'ready' } })
  if (url.pathname.endsWith('/report')) return route.fulfill({ json: report })
  if (url.pathname.endsWith('/contract')) return route.fulfill({ json: { status: 'confirmed', stale: false, missing_requirements: [], contract: job.contract } })
  if (url.pathname.endsWith('/events')) return offline ? route.abort('failed') : route.fulfill({ json: { events: events.filter(event => event.id > Number(url.searchParams.get('after'))) } })
  if (url.pathname.includes('/traces/')) return route.fulfill({ json: { trace_id: 'synthetic-trace', name: 'Synthetic trace fixture', latency_ms: 1000, llm_calls: 1, tool_calls: 0, prompt_tokens: 10, completion_tokens: 5, has_error: false, span_count: 0, returned_span_count: 0, spans: [], detections: [], created_at: new Date().toISOString() } })
  assert(url.pathname.includes('-jobs/'), `Unexpected fixture request: ${url.pathname}`)
  return route.fulfill({ json: job })
})
const visit = step => page.goto(`${base}/app/imports/${report.import.import_id}?step=${step}`)
const progress = page.getByRole('region', { name: 'Task progress', exact: true })
const row = id => progress.locator(`[data-task-id="${id}"]`)
const expectText = (locator, text) => locator.getByText(text, { exact: true }).waitFor()
try {
  await visit('baseline')
  await progress.waitFor()
  assert.equal(await progress.locator('li').count(), 3)
  assert.equal(await progress.getByText('waiting for results', { exact: true }).count(), 3)
  const active = page.getByRole('region', { name: 'Live run', exact: true })
  assert.equal(await active.locator('[role=status] .live-dot').count(), 1)
  assert.equal(await active.locator('.live-dot').first().evaluate(el => getComputedStyle(el).animationDuration), '2.4s')
  append('run', { task_id: '1', repetition: 1, status: 'needs_review', model_calls: 2, cost_usd: 0.01 })
  await expectText(row('1'), '1 / 2 runs recorded')
  await expectText(row('1'), 'waiting for results')
  append('run', { task_id: '2', repetition: 1, status: 'failed' })
  append('run', { task_id: '2', repetition: 2, status: 'passed' })
  append('task', { task_id: '2', status: 'failed' })
  await expectText(row('2'), 'checks failed')
  await expectText(row('1'), 'waiting for results')
  await expectText(row('3'), 'waiting for results')
  assert.equal(await row('2').locator('.task-resolved').evaluate(el => getComputedStyle(el).animationDuration), '0.18s')
  assert.equal(await page.getByRole('log').locator('li').last().evaluate(el => getComputedStyle(el).animationName), 'run-event-enter')
  append('run', { task_id: '1', repetition: 2, status: 'needs_review' })
  append('task', { task_id: '1', status: 'needs_review' })
  await expectText(row('1'), 'needs review')
  assert.equal(await row('1').locator('.chip-ok').count(), 0, 'Human review never becomes an automatic pass')
  offline = true
  await page.getByRole('button', { name: 'Resume feed', exact: true }).waitFor()
  assert.equal(await active.locator('.live-dot').count(), 0, 'A disconnected feed does not pulse as live')
  offline = false
  await page.getByRole('button', { name: 'Resume feed', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('[aria-label="Live run"] .live-dot'))
  job.status = 'completed'; report.active = null; append('finished', { status: 'completed' })
  await expectText(row('3'), 'incomplete')
  assert.equal(await active.locator('.live-dot').count(), 0)

  report.baseline = { status: 'completed', tasks: names.map((task, index) => ({ task_id: String(index + 1), name: task.name })), per_pass: {}, repetitions: 2 }
  report.active = { kind: 'optimization', job_id: 'synthetic-candidate-motion' }
  job = { status: 'running', created_at: Math.floor(Date.now() / 1000), result: { max_spend_usd: 0.5, max_target_spend_usd: 0.5 } }
  events = []
  append('experiment_started', { experiment: 1, task_ids: ['1', '2'], repetitions: 2 })
  await visit('fix')
  await expectText(row('1'), 'waiting for results')
  append('candidate_run', { experiment: 1, task_id: '1', repetition: 1, status: 'failed', done: 1, of: 4 })
  await expectText(row('1'), '1 / 2 runs recorded')
  await expectText(row('1'), 'waiting for results')
  append('candidate_run', { experiment: 1, task_id: '1', repetition: 2, status: 'passed', done: 2, of: 4 })
  await expectText(row('1'), 'checks failed')
  append('candidate_run', { experiment: 1, task_id: '2', repetition: 1, status: 'needs_review', done: 3, of: 4 })
  append('candidate_run', { experiment: 1, task_id: '2', repetition: 2, status: 'needs_review', done: 4, of: 4 })
  await expectText(row('2'), 'needs review')
  append('experiment_started', { experiment: 2, task_ids: ['1', '2'], repetitions: 1 })
  await expectText(row('1'), '0 / 1 runs recorded')
  assert.equal(await progress.getByText('waiting for results', { exact: true }).count(), 2, 'A new experiment resets only its task results')
  append('candidate_run', { experiment: 1, task_id: '1', repetition: 1, status: 'passed' })
  append('candidate_run', { unchanged_agent: true, task_id: '1', repetition: 1, status: 'passed' })
  append('candidate_run', { experiment: 2, task_id: '2', repetition: 1, status: 'passed' })
  await expectText(row('2'), 'checks passed')
  await expectText(row('1'), 'waiting for results')
  assert(!(await page.getByRole('log').innerText()).includes('undefined'), 'Older events without progress counters stay readable')
  for (const width of [320, 375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.evaluate(scanner)
    assert.deepEqual((await page.evaluate(() => window.__wd.scan({ app: true }))).fails, [], `${width}px motion fixture layout`)
  }
  await page.screenshot({ path: path.join(out, 'live-task-results.png'), fullPage: true })
  await page.goto(`${base}/app/imports/${report.import.import_id}?step=fix&trace=synthetic-trace`)
  const panel = page.getByRole('dialog', { name: 'Trace', exact: true })
  await panel.waitFor()
  assert.equal(await panel.evaluate(el => getComputedStyle(el).animationName), 'trace-panel-enter')
  const slide = await panel.evaluate(el => {
    const animation = el.getAnimations()[0]
    animation.pause(); animation.currentTime = 0
    const distance = new DOMMatrix(getComputedStyle(el).transform).m41
    const width = el.offsetWidth
    animation.finish()
    return { distance, width }
  })
  assert.equal(slide.distance, slide.width, 'Trace starts one panel width to the right')
  await panel.getByText('Synthetic trace fixture run', { exact: true }).waitFor()
  const feedback = await panel.getByRole('button', { name: 'Close trace' }).evaluate(el => getComputedStyle(el).transitionDuration.split(',').map(Number.parseFloat))
  assert(feedback.every(seconds => seconds >= 0.12 && seconds <= 0.16))
  await panel.screenshot({ path: path.join(out, 'trace-slide.png') })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  assert(Number.parseFloat(await panel.evaluate(el => getComputedStyle(el).animationDuration)) < 0.001)
  assert(Number.parseFloat(await active.locator('.live-dot').first().evaluate(el => getComputedStyle(el).animationDuration)) < 0.001)
  await page.setViewportSize({ width: 375, height: 844 })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await panel.getByRole('button', { name: 'Close trace' }).click()
  await panel.waitFor({ state: 'hidden' })
  assert.deepEqual(mutations, [], 'Motion checks never launch or mutate a real run')
  assert.deepEqual(errors, [])
  console.log(`Live motion passed: incremental baseline/candidate tasks, repetition gates, review status, experiment reset, paused/finished pulses, event entrances, trace slide, fast feedback, reduced motion, 320–1440px layouts. Synthetic GET-only fixtures. Screenshots: ${out}`)
} finally { await browser.close() }
