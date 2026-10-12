// Synthetic API jobs only: never starts a real model call or executes imported source.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const skill = process.argv[2]
assert(skill, 'Pass the installed web-designer skill directory.')
const base = process.argv[3] || 'http://localhost:5173'
const out = process.argv[4] || '/tmp/hansa-runs-check'
await fs.mkdir(out, { recursive: true })
const { launch } = await import(pathToFileURL(path.join(skill, 'scripts/lib/browser.mjs')))
const scanner = await fs.readFile(path.join(skill, 'scripts/lib/inpage.js'), 'utf8')
const { browser } = await launch()
const context = await browser.newContext()
const page = await context.newPage()
page.setDefaultTimeout(10000)
const errors = []
page.on('pageerror', error => errors.push(error.message))
const session = { user: { id: 'run-fixture-owner', name: 'Run fixture user', email: null }, csrf_token: 'fixture-run-csrf' }
const saved = JSON.parse(await fs.readFile(new URL('../src/data/swarm-report.json', import.meta.url), 'utf8'))
let report = structuredClone(saved), signedIn = true, contractStale = false, contractFails = false, eventsOffline = false, postMode = 'ok'
let current = null, counter = 0
const posts = [], cursors = []
const jobs = new Map()

function newJob(kind, body) {
  const job_id = String(++counter).padStart(32, '0')
  const item = { kind, job_id, status: 'running', created_at: Math.floor(Date.now() / 1000), result: { ...body }, events: [] }
  if (kind === 'baseline') item.contract = { limits: { max_spend_usd: 0.75 } }
  jobs.set(job_id, item); current = item
  report.active = { kind, job_id, events: `${kind === 'baseline' ? 'baseline-jobs' : 'agent-jobs'}/${job_id}/events` }
  report.next = { action: 'wait', reason: 'A job is running.' }
  append('started', { model: 'Synthetic run fixture' })
  return item
}
function append(kind, data) { current.events.push({ id: current.events.length + 1, kind, data, created_at: Math.floor(Date.now() / 1000) }) }
function finish(status = 'ready', result = {}) {
  current.status = status; current.result = { ...current.result, ...result }
  report.active = null; report.next = { action: 'review', reason: 'Synthetic stage complete.' }
  append('finished', { status, ...result })
}

await context.route(`${base}/auth/**`, route => route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? session : { detail: 'Sign in to continue.' } }))
await context.route(`${base}/github/**`, async route => {
  const request = route.request(), url = new URL(request.url()), parts = url.pathname.split('/')
  assert.equal(parts[3], saved.import.import_id)
  const endpoint = parts[4]
  if (request.method() === 'POST') {
    assert(['onboarding', 'baseline', 'investigation', 'optimization'].includes(endpoint))
    assert.equal(request.headers()['x-csrf-token'], session.csrf_token)
    const body = request.postDataJSON()
    posts.push({ kind: endpoint, body })
    if (postMode === 'conflict') return route.fulfill({ status: 409, json: { detail: 'Another agent job is running. Try again when it finishes.' } })
    if (postMode === 'expired') { signedIn = false; return route.fulfill({ status: 401, json: { detail: 'Sign in to continue.' } }) }
    const job = newJob(endpoint, body)
    if (postMode === 'lost') return route.abort('failed')
    return route.fulfill({ status: 202, json: endpoint === 'baseline' ? { baseline_id: job.job_id, status: job.status } : { job_id: job.job_id, status: job.status } })
  }
  assert.equal(request.method(), 'GET')
  if (endpoint === 'report') return route.fulfill({ json: report })
  if (endpoint === 'contract') return route.fulfill({ status: contractFails ? 503 : 200, json: contractFails ? { detail: 'Contract unavailable.' } : { status: 'confirmed', stale: contractStale, missing_requirements: [], contract: { limits: { max_spend_usd: 0.75 }, tasks: saved.baseline.tasks } } })
  assert(['agent-jobs', 'baseline-jobs'].includes(endpoint), `Unexpected request: ${url.pathname}`)
  const job = jobs.get(parts[5]); assert(job)
  assert.equal(endpoint, job.kind === 'baseline' ? 'baseline-jobs' : 'agent-jobs')
  if (parts[6] === 'events') {
    const after = Number(url.searchParams.get('after')); cursors.push({ job: job.job_id, after })
    if (eventsOffline) return route.abort('failed')
    return route.fulfill({ json: { events: job.events.filter(event => event.id > after).slice(0, 200) } })
  }
  return route.fulfill({ json: { ...job, events: undefined } })
})

async function visible(text) { await page.getByText(text, { exact: true }).waitFor({ state: 'visible' }) }
async function visit(step) { await page.goto(`${base}/app/imports/${saved.import.import_id}?step=${step}`) }
async function shot(name) {
  for (const width of [320, 390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 })
    await page.evaluate(() => document.fonts.ready)
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.evaluate(scanner)
    assert.deepEqual((await page.evaluate(() => window.__wd.scan({ app: true }))).fails, [], `${name} at ${width}`)
    await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: true })
  }
}

try {
  await visit('setup')
  await page.getByLabel('Stage spend cap (USD)').waitFor()
  assert.equal(posts.length, 0)
  const capPosition = await page.getByLabel('Stage spend cap (USD)').boundingBox()
  assert(capPosition.y < (await page.getByRole('button', { name: 'Start onboarding', exact: true }).boundingBox()).y)
  await shot('stage-cap')
  await page.getByLabel('Stage spend cap (USD)').fill('0.25')
  // Submit twice in one frame to verify the guard, not just the disabled-button paint.
  await page.locator('form').evaluate(form => { form.requestSubmit(); form.requestSubmit() })
  await visible('Synthetic run fixture')
  assert.deepEqual(posts, [{ kind: 'onboarding', body: { max_spend_usd: 0.25 } }])
  append('smoke', { model_calls: 2, cost_usd: 0.004, wall_time_seconds: 2, stop_reason: 'completed' })
  append('note', { text: '<script>window.fixtureInjected = true</script>' })
  await visible('<script>window.fixtureInjected = true</script>')
  assert.equal(await page.evaluate(() => window.fixtureInjected), undefined)
  await shot('live-onboarding')
  const launched = posts.length
  await page.reload()
  await visible('A job is already running. Reattached to its live feed.')
  await visible('<script>window.fixtureInjected = true</script>')
  assert.equal(posts.length, launched, 'Reload only reattaches, never posts')
  assert.equal(await page.getByRole('button', { name: 'Start onboarding', exact: true }).count(), 0)
  eventsOffline = true
  await visible('Lost contact with Hansa for a moment. Your run is still going on the server; this feed reconnects by itself.')
  await visible('<script>window.fixtureInjected = true</script>')
  eventsOffline = false
  await page.getByRole('button', { name: 'Reconnect now', exact: true }).click()
  for (let i = 0; i < 40; i++) append('note', { text: `Synthetic scroll event ${i}` })
  await visible('Synthetic scroll event 39')
  await page.getByRole('log').evaluate(node => { node.scrollTop = 0 })
  await page.waitForTimeout(50)
  append('note', { text: 'Synthetic event while reading history' })
  await visible('Synthetic event while reading history')
  assert.equal(await page.getByRole('log').evaluate(node => node.scrollTop), 0, 'New rows do not pull readers away from history')
  await page.getByRole('button', { name: 'Follow latest', exact: true }).click()
  assert(await page.getByRole('log').evaluate(node => node.scrollHeight - node.scrollTop - node.clientHeight < 32))
  finish('ready', { agent_usage: { calls: 3, estimated_cost_usd: 0.01, unknown_cost_calls: 0 } })
  await visible('Polling stopped')
  await visible('Onboarding · completed')
  assert.equal(await page.getByRole('log').locator('li').count(), current.events.length, 'No duplicated event rows')
  const polled = cursors.length
  await page.waitForTimeout(1600)
  assert.equal(cursors.length, polled, 'Polling stops on completion')

  await visit('baseline')
  await page.getByText('$0.75', { exact: true }).waitFor()
  contractFails = true
  await visit('baseline')
  await visible('Could not load the confirmed spend cap.')
  assert(await page.getByRole('button', { name: 'Start baseline', exact: true }).isDisabled(), 'A cached cap cannot authorize a start after refresh fails')
  contractFails = false
  await page.getByRole('button', { name: 'Reload spend cap', exact: true }).click()
  await page.getByRole('button', { name: 'Start baseline', exact: true }).waitFor()
  await page.waitForFunction(() => !Array.from(document.querySelectorAll('button')).find(button => button.textContent === 'Start baseline')?.disabled)
  await page.getByLabel('Repetitions').selectOption('2')
  await page.getByRole('button', { name: 'Start baseline', exact: true }).click()
  await visible('Synthetic run fixture')
  assert.deepEqual(posts.at(-1), { kind: 'baseline', body: { repetitions: 2 } })
  append('run', { task_id: '1', status: 'needs_review', model_calls: 3, cost_usd: 0.01, wall_time_seconds: 4, unknown_cost_calls: 0 })
  await visible('Task 1 · needs review')
  await visible('$0.01')
  await shot('live-baseline')
  finish('completed')
  await visible('Polling stopped')
  assert(cursors.some(cursor => cursor.job === current.job_id && cursor.after > 0))

  await visit('findings')
  await page.getByLabel('Stage spend cap (USD)').fill('0.30')
  await page.getByRole('button', { name: 'Start investigation', exact: true }).click()
  await visible('Synthetic run fixture')
  assert.deepEqual(posts.at(-1), { kind: 'investigation', body: { max_spend_usd: 0.3, baseline_id: saved.baseline.baseline_id } })
  // Agent recovery can end without a 'finished' event. Status polling must still stop.
  current.status = 'failed'; current.result.reason = 'Interrupted by a backend restart.'; report.active = null
  await visible('Interrupted by a backend restart.')
  await visible('Polling stopped')

  await visit('fix')
  await page.getByLabel('Optimizer spend cap (USD)').fill('0.40')
  await page.getByLabel('Candidate-run spend cap (USD)').fill('0.60')
  await page.getByLabel('Finding to test').selectOption('2')
  await page.getByRole('button', { name: 'Test fix', exact: true }).click()
  await visible('Synthetic run fixture')
  assert.deepEqual(posts.at(-1), { kind: 'optimization', body: { max_spend_usd: 0.4, max_target_spend_usd: 0.6, investigation_job_id: saved.investigation.job_id, finding_id: '2' } })
  finish('ready', { decision: 'reject', summary: 'Synthetic tested candidate regressed a task.', target_usage: { calls: 4, estimated_cost_usd: null, unknown_cost_calls: 1 } })
  await visible('Verdict: Fix rejected')
  await visible('Fix testing · completed')
  assert.equal(await page.getByRole('alert').count(), 0, 'Rejected completion is not a run error')
  await visible('Polling stopped')
  await shot('live-rejected')

  postMode = 'conflict'
  await visit('fix')
  await page.getByLabel('Finding to test').selectOption('')
  const goal = 'Reduce context tokens while preserving the task contract.'
  await page.getByLabel('Optimization goal').fill(goal)
  await page.getByRole('button', { name: 'Test fix', exact: true }).click()
  await visible('Another agent job is running. Try again when it finishes.')
  assert.deepEqual(posts.at(-1).body, { max_spend_usd: 0.5, max_target_spend_usd: 0.5, goal })
  const conflicted = posts.length
  await page.waitForTimeout(1200)
  assert.equal(posts.length, conflicted, 'No automatic mutation retries')

  postMode = 'lost'
  await visit('setup')
  await page.getByRole('button', { name: 'Start onboarding', exact: true }).click()
  await visible('Start was not confirmed. Check run status before trying again; the job may already be running.')
  const ambiguous = posts.length
  await page.getByRole('button', { name: 'Check run status', exact: true }).click()
  await visible('A job is already running. Reattached to its live feed.')
  assert.equal(posts.length, ambiguous, 'Checking status does not repeat an ambiguous start')
  finish('ready')
  await visible('Polling stopped')

  // A terminal job with >200 saved events must drain all pages before stopping.
  const historical = newJob('investigation', { max_spend_usd: 0.5 })
  for (let i = 0; i < 220; i++) append('note', { text: `Synthetic paginated event ${i}` })
  historical.status = 'ready'
  // Keep report.active so reload exercises recovery and paginated history.
  await visit('findings')
  await visible('Synthetic paginated event 219')
  await visible('Polling stopped')
  assert.equal(await page.getByRole('log').locator('li').count(), 221)
  assert(cursors.some(cursor => cursor.job === historical.job_id && cursor.after === 200))
  report.active = null

  contractStale = true
  await visit('baseline')
  await page.getByText('$0.75', { exact: true }).waitFor()
  assert(await page.getByRole('button', { name: 'Start baseline', exact: true }).isDisabled())
  contractStale = false
  postMode = 'expired'
  await visit('setup')
  await page.getByRole('button', { name: 'Start onboarding', exact: true }).click()
  await page.waitForURL(`${base}/sign-in`)

  const posted = posts.length
  await page.goto(`${base}/app/dev/swarm-report?step=fix`)
  await visible('Starting stages is disabled in this saved preview.')
  assert(await page.getByRole('button', { name: 'Test fix', exact: true }).isDisabled())
  assert.equal(posts.length, posted)
  const merged = await page.evaluate(async () => {
    const { mergeEvents } = await import('/src/RunFeed.tsx')
    return mergeEvents([{ id: 2 }, { id: 1 }], [{ id: 2 }, { id: 3 }]).map(event => event.id)
  })
  assert.deepEqual(merged, [1, 2, 3])
  assert.deepEqual(errors, [])
  console.log(`Stage and polling fixture checks passed; screenshots: ${out}`)
} finally { await browser.close() }
