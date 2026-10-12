// Synthetic session only. Account mutations are intercepted, never sent to the backend.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const skill = process.argv[2]
assert(skill, 'Pass the installed browser helper directory.')
const base = process.argv[3] || 'http://localhost:5173'
const out = process.argv[4] || '/tmp/hansa-profile-check'
await fs.mkdir(out, { recursive: true })
const { launch } = await import(pathToFileURL(path.join(skill, 'scripts/lib/browser.mjs')))
const scanner = await fs.readFile(path.join(skill, 'scripts/lib/inpage.js'), 'utf8')
const { browser } = await launch()
const context = await browser.newContext()
let user = { id: 'fixture-profile', name: 'UI test user', email: 'fixture@example.com', avatar_url: null }
const mutations = [], errors = []
await context.route(`${base}/auth/**`, async route => {
  const request = route.request()
  if (request.method() === 'GET' && new URL(request.url()).pathname === '/auth/me') return route.fulfill({ json: { user, csrf_token: 'fixture-only' } })
  mutations.push({ method: request.method(), path: new URL(request.url()).pathname, csrf: request.headers()['x-csrf-token'] })
  return route.fulfill({ status: 503, json: { detail: 'Fixture failure: try again.' } })
})
const imported = { id: 'fixture-agent', repository_name: 'fixture-owner/existing-agent', branch: 'main', commit_sha: 'a'.repeat(40), status: 'ready', failure_reason: null, created_at: 1791690000 }
const unexpected = []
await context.route(`${base}/github/**`, route => {
  const request = route.request(), pathname = new URL(request.url()).pathname
  assert.equal(request.method(), 'GET', 'Navigation cannot create imports or start jobs')
  if (pathname === '/github/imports') return route.fulfill({ json: { imports: [imported], page: 1, has_next: false } })
  if (pathname === `/github/imports/${imported.id}`) return route.fulfill({ json: imported })
  if (pathname === '/github/connection') return route.fulfill({ json: { configured: false, status: 'not_connected', github_login: null } })
  if (pathname === `/github/imports/${imported.id}/report`) return route.fulfill({ json: {
    import: { import_id: imported.id, repository: imported.repository_name, branch: imported.branch, commit_sha: imported.commit_sha },
    adapter: null, baseline: null, investigation: null, optimizations: [], accepted: [], limits: [],
    stages: { onboarded: false, baseline: false, investigated: false, optimized: false }, next: { action: 'import', reason: null },
  } })
  unexpected.push(pathname)
  return route.fulfill({ status: 404, json: { detail: 'Unexpected fixture request.' } })
})
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
try {
  for (const long of [false, true]) {
    user = long ? { ...user, name: 'LongUnbrokenProfileName'.repeat(4), email: `${'longemail'.repeat(12)}@example.com`, avatar_url: `${base}/brand/mark.svg` }
      : { ...user, name: 'UI test user', email: null, avatar_url: null }
    for (const width of [320, 375, 640, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`${base}/app/profile`)
      const account = page.getByRole('region', { name: 'Your account' })
      await account.waitFor()
      await page.evaluate(() => document.fonts.ready)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${width}px profile: no overflow`)
      const avatar = account.locator('img, span[aria-hidden=true]').first()
      const avatarBox = await avatar.boundingBox()
      assert.equal(avatarBox.width, width < 640 ? 64 : 72, 'Avatar keeps its size')
      const caption = await page.locator('#profile-account').boundingBox()
      assert(caption.y + caption.height <= avatarBox.y, 'Caption is above the identity row')
      const signout = await account.getByRole('button', { name: 'Sign out' }).boundingBox()
      const name = await account.locator('p').first().boundingBox()
      const email = await account.locator('p').last().boundingBox()
      const input = await page.getByLabel('Type delete to confirm').boundingBox()
      const remove = await page.getByRole('button', { name: 'Delete everything' }).boundingBox()
      if (width < 640) {
        assert(signout.y >= Math.max(avatarBox.y + avatarBox.height, email.y + email.height), 'Sign out stacks below the identity')
        assert(remove.y >= input.y + input.height, 'Delete controls stack on phones')
        assert(Math.abs(input.width - remove.width) < 1, 'Delete input and button have matching mobile widths')
      } else {
        assert(signout.x >= name.x + name.width, 'Desktop sign out sits beside identity')
        assert(remove.x >= input.x + input.width, 'Desktop delete controls share a row')
      }
      await page.evaluate(scanner)
      const scan = await page.evaluate(() => window.__wd.scan({ app: true }))
      await page.screenshot({ path: path.join(out, `${long ? 'long' : 'short'}-${width}.png`), fullPage: true })
      assert.deepEqual(scan.fails, [], `${width}px ${long ? 'long' : 'short'} profile: readable layout`)
    }
  }
  const remove = page.getByRole('button', { name: 'Delete everything' })
  assert.equal(await remove.isDisabled(), true)
  const disabledFill = await remove.evaluate(el => getComputedStyle(el).backgroundColor)
  await page.getByLabel('Type delete to confirm').fill('delete')
  assert.equal(await remove.isEnabled(), true)
  await page.waitForFunction(fill => getComputedStyle(document.querySelector('#confirm-delete + button')).backgroundColor !== fill, disabledFill)
  assert.notEqual(await remove.evaluate(el => getComputedStyle(el).backgroundColor), disabledFill, 'Delete confirmation has a visible enabled state')
  await remove.click()
  await page.getByRole('alert').waitFor()
  assert.equal(await remove.isEnabled(), true, 'Failed account action can be retried')
  assert.deepEqual(mutations, [{ method: 'DELETE', path: '/auth/me', csrf: 'fixture-only' }])
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('button', { name: 'Sign out' }).waitFor()
  assert.deepEqual(mutations.at(-1), { method: 'POST', path: '/auth/logout', csrf: 'fixture-only' })
  // Existing agents and new imports are both reachable from the signed-in home page.
  for (const width of [320, 375, 640, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(base)
    const navigation = page.getByRole('navigation', { name: 'Main navigation' })
    await navigation.getByRole('link', { name: 'Your agents', exact: true }).waitFor()
    await page.evaluate(() => document.fonts.ready)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${width}px signed-in navigation fits`)
    await navigation.getByRole('link', { name: 'Your agents', exact: true }).click()
    await page.waitForURL(`${base}/app`)
    const guide = page.getByRole('region', { name: 'How to work with your agents' })
    await guide.waitFor()
    const type = await guide.evaluate(el => Object.fromEntries(['h2', 'h3', 'p'].map(tag => [tag, parseFloat(getComputedStyle(el.querySelector(tag)).fontSize)])))
    assert(type.p >= 17 && type.h3 >= 20 && type.h2 > type.h3, 'Walkthrough text is readable with a clear heading hierarchy')
    assert.equal(await guide.getByRole('link', { name: 'Import another agent' }).getAttribute('href'), '/app/new')
    assert.equal(await guide.getByRole('link', { name: 'Explore the recorded demo' }).getAttribute('href'), '/demo')
    await page.evaluate(scanner)
    const agentsScan = await page.evaluate(() => window.__wd.scan({ app: true }))
    await page.screenshot({ path: path.join(out, `agents-guide-${width}.png`), fullPage: true })
    assert.deepEqual(agentsScan.fails, [], `${width}px agent list and walkthrough: readable layout`)
    await page.getByRole('link', { name: imported.repository_name, exact: true }).click()
    await page.waitForURL(`${base}/app/imports/${imported.id}`)
    await page.getByRole('heading', { name: /existing-agent/ }).waitFor()
    assert.equal(await navigation.getByRole('link', { name: 'Your agents', exact: true }).isVisible(), true, 'Existing agents stay accessible on report pages')
    if (width < 640) await navigation.getByLabel('Menu', { exact: true }).click()
    await navigation.getByRole('link', { name: 'Import an agent', exact: true }).filter({ visible: true }).click()
    await page.waitForURL(`${base}/app/new`)
    await page.getByRole('heading', { name: 'Bring an agent.' }).waitFor()
    const help = page.getByRole('region', { name: 'How to import your agent' })
    await help.waitFor()
    await help.locator('summary').click()
    await help.getByRole('heading', { name: '1. Connect GitHub' }).waitFor()
    await page.evaluate(scanner)
    const helpScan = await page.evaluate(() => window.__wd.scan({ app: true }))
    assert.deepEqual(helpScan.fails, [], `${width}px expanded import instructions: readable layout`)
    await help.locator('summary').click()
    await page.getByRole('region', { name: 'What happens after import?' }).waitFor()
    if (width < 1024) {
      await navigation.getByLabel('Menu', { exact: true }).click()
      assert.equal(await navigation.locator('details').getByRole('link', { name: 'Your agents', exact: true }).getAttribute('href'), '/app')
      assert.equal(await navigation.locator('details').getByRole('link', { name: 'Import an agent', exact: true }).getAttribute('href'), '/app/new')
      await navigation.getByLabel('Menu', { exact: true }).click()
    }
    await page.evaluate(scanner)
    const scan = await page.evaluate(() => window.__wd.scan({ app: true }))
    await page.screenshot({ path: path.join(out, `navigation-${width}.png`), fullPage: true })
    assert.deepEqual(scan.fails, [], `${width}px navigation: readable controls`)
  }
  assert.deepEqual(unexpected, [])
  assert.equal(mutations.length, 2, 'Browsing existing agents and opening import setup starts no mutations')
  assert.deepEqual(errors, [])
  console.log(`Profile passed: 320–1440px, long names/emails, avatars, mobile stacking, desktop rows, direct agent navigation, import/workflow guides, contrast and mocked action guards. Screenshots: ${out}. No real account changed.`)
} finally {
  await browser.close()
}
