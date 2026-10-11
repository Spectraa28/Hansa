// Labelled API fixtures only; this does not exercise real OAuth or GitHub.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const skill = process.argv[2]
assert(skill, 'Pass the installed web-designer skill directory as the first argument.')
const base = process.argv[3] || 'http://localhost:5173'
const out = process.argv[4] || '/tmp/hansa-app-check'
await fs.mkdir(out, { recursive: true })
const { launch } = await import(pathToFileURL(path.join(skill, 'scripts/lib/browser.mjs')))
const scanner = await fs.readFile(path.join(skill, 'scripts/lib/inpage.js'), 'utf8')
const { browser } = await launch()
const context = await browser.newContext()
// Keep clipboard assertions inside the test page; do not overwrite the host clipboard.
await context.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => {
  if (window.__denyClipboard) throw new Error('Fixture clipboard denial')
  window.__copiedPrompt = text
} } }))
const page = await context.newPage()
page.setDefaultTimeout(10000)
const errors = []
page.on('pageerror', error => errors.push(error.message))
const session = { user: { id: 'fixture-user', name: 'UI test user', email: 'fixture@example.com' }, csrf_token: 'fixture-only' }
const item = { id: 'fixture-import', repository_name: 'fixture-owner/test-agent', branch: 'main', commit_sha: 'a'.repeat(40), status: 'ready', failure_reason: null, created_at: 1791690000 }
const savedReport = JSON.parse(await fs.readFile(new URL('../src/data/swarm-report.json', import.meta.url), 'utf8'))
const savedPatches = JSON.parse(await fs.readFile(new URL('../src/data/swarm-patches.json', import.meta.url), 'utf8'))
const savedHandoffs = JSON.parse(await fs.readFile(new URL('../src/data/swarm-handoffs.json', import.meta.url), 'utf8'))
let artifactStatus = 200, artifactCalls = 0
let reportData = structuredClone(savedReport), reportStatus = 200, reportCalls = 0
let signedIn = false, loginFails = true, loginOffline = false, importsMode = 'populated'
let enabledProviders = { github: true, google: false, email: true }
let providerFails = false, importsPage = 1

await context.route(`${base}/auth/**`, async route => {
  const url = new URL(route.request().url())
  if (url.pathname === '/auth/providers') return route.fulfill({ status: providerFails ? 503 : 200, json: enabledProviders })
  if (url.pathname === '/auth/me') return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? session : { detail: 'Sign in to continue.' } })
  if (url.pathname === '/auth/login') {
    assert.deepEqual(route.request().postDataJSON(), { email: 'fixture@example.com', password: 'fixture-password' })
    if (loginOffline) return route.abort('failed')
    if (loginFails) return route.fulfill({ status: 401, json: { detail: 'Invalid email or password.' } })
    signedIn = true
    return route.fulfill({ json: session })
  }
  throw new Error(`Unexpected auth call: ${url.pathname}`)
})
await context.route(`${base}/github/imports?*`, async route => {
  importsPage = Number(new URL(route.request().url()).searchParams.get('page'))
  if (importsMode === 'expired') { signedIn = false; return route.fulfill({ status: 401, json: { detail: 'Sign in to continue.' } }) }
  if (importsMode === 'error') return route.fulfill({ status: 503, json: { detail: 'Storage unavailable. Try again.' } })
  return route.fulfill({ json: { imports: importsMode === 'empty' ? [] : [item], page: importsPage, has_next: importsPage === 1 && importsMode !== 'empty' } })
})
await context.route(`${base}/github/imports/*/report`, async route => {
  assert.equal(route.request().method(), 'GET', 'Viewing a report must not start work')
  reportCalls++
  if (reportStatus === 401) signedIn = false
  return route.fulfill({ status: reportStatus, json: reportStatus === 200 ? reportData : { detail: reportStatus === 404 ? 'Import not found.' : 'Sign in to continue.' } })
})
await context.route(`${base}/github/imports/*/contract`, route => route.fulfill({ json: { status: 'confirmed', stale: false, missing_requirements: [], contract: { limits: { max_spend_usd: 0.75 }, tasks: [] } } }))
await context.route(`${base}/github/imports/*/agent-jobs/*/*`, async route => {
  assert.equal(route.request().method(), 'GET', 'Exporting artifacts must not start work')
  artifactCalls++
  const segments = new URL(route.request().url()).pathname.split('/')
  const job = segments.at(-2), kind = segments.at(-1)
  assert.equal(segments[3], savedReport.import.import_id)
  assert(['patch', 'handoff'].includes(kind))
  if (artifactStatus === 401) signedIn = false
  return route.fulfill({ status: artifactStatus, contentType: artifactStatus === 200 ? 'text/plain' : 'application/json',
    body: artifactStatus === 200 ? (kind === 'patch' ? savedPatches : savedHandoffs)[job] : JSON.stringify({ detail: artifactStatus === 404 ? 'This job has no patch.' : 'Sign in to continue.' }) })
})

async function visible(text) { await page.getByText(text, { exact: true }).waitFor({ state: 'visible' }) }
async function capture(name) {
  for (const width of [320, 390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 })
    await page.evaluate(() => document.fonts.ready)
    const logo = await page.getByRole('link', { name: 'Hansa home' }).boundingBox()
    assert.equal(logo.x, width < 640 ? 20 : 32, 'Logo must stay left aligned')
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No sideways scrolling')
    await page.evaluate(scanner)
    const scan = await page.evaluate(() => window.__wd.scan({ app: true }))
    assert.deepEqual(scan.fails, [], `${name} at ${width}px`)
    await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: true })
  }
}

try {
  await page.goto(`${base}/app/imports/${item.id}`)
  await page.waitForURL(`${base}/sign-in`)
  assert.equal(reportCalls, 0, 'Signed-out users do not request protected reports')
  await page.goto(`${base}/app`)
  await page.waitForURL(`${base}/sign-in`)
  await visible('Continue with GitHub')
  assert.equal(await page.getByText('Continue with Google').count(), 0)
  assert.equal(await page.getByRole('link', { name: 'Continue with GitHub' }).getAttribute('href'), '/auth/github/login')
  await capture('signin')
  await page.getByLabel('Email', { exact: true }).fill('fixture@example.com')
  await page.getByLabel('Password', { exact: true }).fill('fixture-password')
  await page.getByRole('button', { name: 'Sign in with email' }).click()
  await visible('Invalid email or password.')
  assert.equal(await page.getByLabel('Email', { exact: true }).inputValue(), 'fixture@example.com')
  loginOffline = true
  await page.getByRole('button', { name: 'Sign in with email' }).click()
  await visible('Could not sign in. Check your connection and try again.')
  loginOffline = false
  loginFails = false
  await page.getByRole('button', { name: 'Sign in with email' }).click()
  await page.waitForURL(`${base}/app`)
  await visible(item.repository_name)
  await capture('imports')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await visible('Page 2')
  assert.equal(importsPage, 2)
  await page.getByRole('button', { name: 'Previous', exact: true }).click()
  await visible('Page 1')
  importsMode = 'error'
  await page.getByRole('button', { name: 'Refresh imports' }).click()
  await visible('Storage unavailable. Try again.')
  importsMode = 'empty'
  await page.getByRole('button', { name: 'Try again' }).click()
  await visible('No repositories imported yet')
  importsMode = 'populated'
  item.repository_name = 'fixture-owner/' + 'long-repository-name-'.repeat(12)
  session.user.name = 'x'.repeat(100)
  item.branch = 'long-branch-'.repeat(20)
  item.status = 'failed'
  item.failure_reason = '<script>alert("fixture")</script> Import could not finish.'
  await page.reload()
  await visible(item.failure_reason)
  await page.getByRole('button', { name: 'Refresh imports' }).click()
  await visible(item.failure_reason)
  await capture('imports-long')
  await page.getByRole('link', { name: item.repository_name, exact: true }).click()
  await page.waitForURL(`${base}/app/imports/${item.id}`)
  await visible('Investigation incomplete. These findings were saved before it ended.')
  assert.equal(await page.getByRole('link', { name: /^Findings/ }).getAttribute('aria-current'), 'step')
  assert.equal(await page.getByRole('link', { name: 'examples/airline/configs/agents.py:49–57', exact: true }).getAttribute('href'), `https://github.com/Spectraa28/swarm/blob/${savedReport.import.commit_sha}/examples/airline/configs/agents.py#L49-L57`)
  await capture('report-findings')
  await page.getByText('Proposed change and risk', { exact: true }).first().click()
  await visible(savedReport.investigation.findings[0].proposed_change)
  await page.getByRole('link', { name: 'Baseline', exact: true }).click()
  await visible('Mean per full task set')
  for (const task of savedReport.baseline.tasks) await visible(task.name)
  await visible('0 passed · 2 failed · 4 need review')
  await visible('$0.2243538')
  await visible('$0.0389268')
  await capture('report-baseline')
  await page.reload()
  await visible('Mean per full task set')
  assert.equal(await page.getByRole('link', { name: 'Baseline', exact: true }).getAttribute('aria-current'), 'step')
  await page.goBack()
  await visible('Investigation incomplete. These findings were saved before it ended.')
  await page.getByRole('link', { name: 'Result', exact: true }).click()
  await visible('Fix rejected')
  await visible(savedReport.optimizations.at(-1).comparison.note.replaceAll('needs_review', 'Needs review'))
  assert.equal(await page.getByRole('alert').count(), 0, 'A rejected fix is a result, not an error')
  assert.equal(await page.getByLabel('Tested fix').inputValue(), savedReport.optimizations.at(-1).job_id)
  for (const task of savedReport.optimizations.at(-1).comparison.tasks) await visible(task.name)
  await visible('Full task set · 6 compared tasks · mean per compared task set')
  await visible('10% lower')
  await visible('$0.2092794')
  await capture('result-rejected')
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download patch', exact: true }).click()
  const download = await downloadEvent
  assert.equal(download.suggestedFilename(), `hansa-${savedReport.optimizations.at(-1).job_id.slice(0, 8)}-not-accepted.patch`)
  assert.equal(await fs.readFile(await download.path(), 'utf8'), savedPatches[savedReport.optimizations.at(-1).job_id])
  await page.getByRole('button', { name: 'Copy prompt', exact: true }).click()
  await visible('Prompt copied.')
  assert.equal(await page.evaluate(() => window.__copiedPrompt), savedHandoffs[savedReport.optimizations.at(-1).job_id])
  assert((await page.evaluate(() => window.__copiedPrompt)).includes('Do not apply it as it stands.'))
  await page.evaluate(() => { window.__denyClipboard = true })
  await page.getByRole('button', { name: 'Copy prompt', exact: true }).click()
  assert.equal(await page.getByLabel('Handoff prompt').inputValue(), savedHandoffs[savedReport.optimizations.at(-1).job_id])
  await page.evaluate(() => { window.__denyClipboard = false })
  artifactStatus = 404
  await page.getByRole('button', { name: 'Download patch', exact: true }).click()
  await visible('This job has no patch.')
  await visible('Fix rejected')
  artifactStatus = 200
  await page.getByLabel('Tested fix').selectOption(savedReport.optimizations[0].job_id)
  await visible('Partial task set · 2 compared tasks · mean per compared task set')
  await page.reload()
  await visible('Partial task set · 2 compared tasks · mean per compared task set')
  assert.equal(await page.getByLabel('Tested fix').inputValue(), savedReport.optimizations[0].job_id)
  await capture('result-partial')
  // Synthetic accepted/unknown states exercise UI branches; the saved Swarm fixes remain rejected.
  reportData = structuredClone(savedReport)
  const accepted = reportData.optimizations.at(-1)
  accepted.decision = 'accept'; accepted.patch_available = true; accepted.comparison_is_of = 'accepted candidate'
  accepted.comparison.verdict = 'improved'; accepted.summary = 'Synthetic accepted UI fixture; not a measured Swarm acceptance.'
  accepted.comparison.tasks.forEach(task => { task.regressed = false; task.candidate_status = 'passed'; task.candidate_automatic_passes = [2, 2] })
  await page.goto(`${base}/app/imports/${item.id}?step=result`)
  await visible('Fix accepted')
  await visible('Synthetic accepted UI fixture; not a measured Swarm acceptance.')
  const acceptedDownloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download patch', exact: true }).click()
  assert.equal((await acceptedDownloadEvent).suggestedFilename(), `hansa-${accepted.job_id.slice(0, 8)}.patch`)
  await capture('result-accepted-fixture')
  accepted.comparison.totals.model_calls = { baseline: 0, candidate: 0, change_percent: null }
  accepted.comparison.totals.cost_usd = { baseline: null, candidate: null, change_percent: null }
  accepted.comparison.totals.wall_time_seconds = { baseline: 1, candidate: 2, change_percent: 100 }
  accepted.patch_available = false; accepted.tried_patch_available = false
  await page.getByRole('button', { name: 'Refresh report' }).click()
  await visible('100% higher')
  assert.equal(await page.locator('[aria-hidden="true"] > div[hidden]').count(), 4, 'Unknown and zero values draw no filled bar')
  await visible('No patch or handoff prompt is available for this attempt.')
  assert.equal(await page.getByRole('button', { name: 'Download patch', exact: true }).count(), 0)
  await capture('result-unknown-fixture')
  accepted.comparison = null; accepted.decision = null
  await page.getByRole('button', { name: 'Refresh report' }).click()
  await visible('No tested comparison has been saved for this attempt.')
  reportData = structuredClone(savedReport)
  await page.getByRole('button', { name: 'Refresh report' }).click()
  await visible('Fix rejected')
  artifactStatus = 401
  await page.getByRole('button', { name: 'Copy prompt', exact: true }).click()
  await page.waitForURL(`${base}/sign-in`)
  artifactStatus = 200; signedIn = true
  await page.goto(`${base}/app/imports/${item.id}?step=findings`)
  await visible('Investigation incomplete. These findings were saved before it ended.')
  const formats = await page.evaluate(async () => {
    const { measurement, recommendedStep, sourceUrl, barWidth } = await import('/src/report.ts')
    return [measurement(null), measurement(0, 'usd'), measurement(1.5),
      sourceUrl('owner/repo', 'a'.repeat(40), { path: '../secret', start_line: 1, end_line: 1 }),
      sourceUrl('owner/repo', 'main', { path: 'agent.py', start_line: 1, end_line: 1 }),
      ...['onboard', 'baseline', 'investigate', 'optimize', 'review'].map(action => recommendedStep({ next: { action } })),
      recommendedStep({ next: { action: 'wait' }, active: { kind: 'baseline' } }),
      ...[[0, 0], [null, 4], [2, 4], [4, 2], [Infinity, 1], [-1, 1], [0.001, 0.002]].map(([a, b]) => barWidth(a, b))]
  })
  assert.deepEqual(formats, ['Not recorded', '$0', '1.5', null, null, 'setup', 'baseline', 'findings', 'fix', 'result', 'baseline', 0, 0, 50, 100, 0, 0, 50])
  reportData = { ...structuredClone(savedReport), baseline: null, investigation: null, adapter: null, optimizations: [], accepted: [], next: { action: 'onboard', reason: 'No adapter is stored for this import.' } }
  await page.goto(`${base}/app/imports/${item.id}`)
  await visible('Setup is pending')
  await page.getByRole('link', { name: 'Baseline', exact: true }).click()
  await visible('No baseline has been saved yet.')
  await page.getByRole('link', { name: 'Findings', exact: true }).click()
  await visible('No investigation has been saved yet.')
  await page.getByRole('link', { name: 'Result', exact: true }).click()
  await visible('No optimization result has been saved yet.')
  await page.getByRole('link', { name: 'Findings', exact: true }).click()
  reportStatus = 404
  await page.getByRole('button', { name: 'Refresh report' }).click()
  await visible('Import not found.')
  reportStatus = 200
  reportData = structuredClone(savedReport)
  await page.getByRole('button', { name: 'Try again' }).click()
  await visible('Investigation incomplete. These findings were saved before it ended.')
  reportStatus = 401
  await page.getByRole('button', { name: 'Refresh report' }).click()
  await page.waitForURL(`${base}/sign-in`)
  signedIn = true
  await page.goto(`${base}/app`)
  await visible(item.repository_name)
  importsMode = 'expired'
  await page.getByRole('button', { name: 'Refresh imports' }).click()
  await page.waitForURL(`${base}/sign-in`)
  await visible('Continue with GitHub')
  enabledProviders = { github: false, google: false, email: false }
  await page.reload()
  await visible('No sign-in methods are enabled. Contact the person running Hansa.')
  providerFails = true
  await page.reload()
  await visible('Could not load sign-in. Please try again.')
  providerFails = false
  enabledProviders = { github: false, google: true, email: false }
  await page.getByRole('button', { name: 'Try again' }).click()
  await visible('Continue with Google')
  assert.equal(await page.getByRole('link', { name: 'Continue with Google' }).getAttribute('href'), '/auth/google/login')
  const liveCalls = reportCalls
  await page.goto(`${base}/app/dev/swarm-report`)
  await visible('Saved Swarm report · development preview. These are saved results; no live run is started.')
  await visible('Investigation incomplete. These findings were saved before it ended.')
  assert.equal(reportCalls, liveCalls, 'Saved preview never falls back to the live report API')
  const liveArtifacts = artifactCalls
  await page.getByRole('link', { name: 'Result', exact: true }).click()
  await visible('Fix rejected')
  await page.getByRole('button', { name: 'Copy prompt', exact: true }).click()
  await visible('Prompt copied.')
  assert.equal(await page.evaluate(() => window.__copiedPrompt), savedHandoffs[savedReport.optimizations.at(-1).job_id])
  assert.equal(artifactCalls, liveArtifacts, 'Saved preview exports do not call the live artifact API')
  assert.deepEqual(errors, [], 'No React/browser runtime errors')
  console.log(`Fixture UI checks passed; screenshots: ${out}`)
} finally {
  await browser.close()
}
