// Fails when the page's inline script no longer matches the hash allowed in vercel.json.
// Run after `npm run build`, whenever index.html changes: node scripts/check-csp.mjs
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

const html = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')
const policy = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'))
  .headers.flatMap(rule => rule.headers).find(header => header.key === 'Content-Security-Policy').value
const missing = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(match => `'sha256-${createHash('sha256').update(match[1]).digest('base64')}'`)
  .filter(hash => !policy.includes(hash))
if (missing.length) {
  console.error(`vercel.json does not allow the page's inline script. Add to script-src: ${missing.join(' ')}`)
  process.exit(1)
}
console.log('Inline script matches the policy in vercel.json.')
