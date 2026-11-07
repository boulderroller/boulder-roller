import { readFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'

const orgRoot = path.resolve(new URL('..', import.meta.url).pathname)
const repoRoot = path.resolve(orgRoot, '../..')

const failures = []

function check(condition, message) {
  if (!condition) failures.push(message)
}

async function readOrg(relativePath) {
  return readFile(path.join(orgRoot, relativePath), 'utf8')
}

async function readRepo(relativePath) {
  return readFile(path.join(repoRoot, relativePath), 'utf8')
}

function assertContains(haystack, needle, label) {
  check(haystack.includes(needle), `${label} must contain ${needle}`)
}

function assertNotContains(haystack, needle, label) {
  check(!haystack.includes(needle), `${label} must not contain ${needle}`)
}

function assertNotContainsAny(haystack, needles, label) {
  for (const needle of needles) {
    assertNotContains(haystack, needle, label)
  }
}

async function main() {
  const layout = await readOrg('src/app/layout.tsx')
  const header = await readOrg('src/components/Header.tsx')
  const hero = await readOrg('src/components/Hero.tsx')
  const proxy = await readOrg('src/proxy.ts')
  const investor = await readOrg('public/investor/index.html')
  const backendMetadata = await readRepo('backend/app/routes/metadata.py')
  const backendReadme = await readRepo('backend/README.md')
  const spec = await readRepo('docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md')

  assertContains(layout, "new URL('https://boulderroller.xyz')", 'org metadata')
  assertContains(layout, "canonical: 'https://boulderroller.xyz'", 'org metadata')
  assertContains(layout, "url: 'https://boulderroller.xyz'", 'org Open Graph metadata')
  assertNotContains(layout, 'boulderroller.org', 'org metadata')

  assertNotContains(header, 'https://docs.boulderroller.xyz', 'org header')
  assertContains(hero, 'href="https://docs.boulderroller.xyz/"', 'org hero docs destination')
  assertContains(hero, 'Read the docs', 'org hero docs action')
  assertNotContains(header, 'docs.boulderroller.org', 'org header docs link')
  assertNotContains(hero, 'docs.boulderroller.org', 'org hero docs link')
  assertNotContains(header, 'scan.boulderroller.xyz', 'org header')
  assertNotContains(hero, 'scan.boulderroller.xyz', 'org hero')

  assertNotContainsAny(layout, ['matched climbs', 'proof when available', 'BoulderScan'], 'org metadata')
  assertNotContainsAny(header, ['Docs', 'Climbs', 'BoulderScan', 'Read docs', 'Browse climbs'], 'org header')
  assertNotContainsAny(hero, ['proof when available', 'BoulderScan', 'Browse climbs'], 'org hero')

  for (const host of ['boulderroller.com', 'www.boulderroller.com', 'boulderroller.org', 'www.boulderroller.org']) {
    assertContains(proxy, `'${host}'`, 'org host redirect proxy')
  }
  assertContains(proxy, "const CANONICAL_PUBLIC_HOST = 'boulderroller.xyz'", 'org host redirect proxy')
  assertContains(proxy, 'export function proxy(request: NextRequest)', 'org host redirect proxy')
  assertContains(proxy, 'NextResponse.redirect(url, 308)', 'org host redirect proxy')

  assertContains(investor, 'https://boulderroller.xyz/investor', 'investor Open Graph URL')
  assertContains(investor, 'boulderroller.xyz', 'investor visible domain')
  assertNotContains(investor, 'boulderroller.org', 'investor public domain copy')

  assertContains(backendMetadata, '"external_url": "https://boulderroller.xyz"', 'DUNG metadata external URL')
  assertContains(backendReadme, 'https://app.boulderroller.xyz', 'backend README CORS guidance')
  assertContains(backendReadme, 'https://boulderroller.xyz', 'backend README CORS guidance')
  assertNotContains(backendReadme, 'https://www.boulderroller.com', 'backend README CORS guidance')

  for (const canonicalHost of [
    'boulderroller.xyz',
    'app.boulderroller.xyz',
    'docs.boulderroller.xyz',
    'scan.boulderroller.xyz',
    'api.boulderroller.xyz',
  ]) {
    assertContains(spec, canonicalHost, 'first traverse domain spine spec')
  }

  if (failures.length > 0) {
    console.error('Domain spine check failed:')
    for (const failure of failures) {
      console.error(`- ${failure}`)
    }
    process.exit(1)
  }

  console.log('Domain spine check passed.')
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
