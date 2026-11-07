import { readFile } from 'node:fs/promises'
import path from 'node:path'

const orgRoot = path.resolve(new URL('..', import.meta.url).pathname)
const failures = []

function check(condition, message) {
  if (!condition) failures.push(message)
}

async function read(relativePath) {
  return readFile(path.join(orgRoot, relativePath), 'utf8')
}

function count(haystack, needle) {
  return haystack.split(needle).length - 1
}

async function main() {
  const page = await read('src/app/page.tsx')
  const header = await read('src/components/Header.tsx')
  const hero = `${await read('src/components/Hero.tsx')}\n${await read('src/components/ClimbExplorer.tsx')}`
  const css = await read('src/app/globals.css')
  const publicSurface = `${header}\n${hero}`

  check(
    count(publicSurface, 'https://app.boulderroller.xyz') === 0,
    'coming-soon composition must replace the app entrance with release status',
  )
  check(
    !header.includes('Log in'),
    'header must not duplicate the app entrance with Log in',
  )
  check(
    !header.includes('h-2.5 w-2.5'),
    'wordmark must not include the arbitrary square',
  )
  check(
    !header.includes('fixed'),
    'single-screen header must remain in document flow',
  )
  check(
    !header.includes('backdrop-blur'),
    'single-screen header must not use an ornamental blur',
  )

  check(
    page.indexOf('<Header />') < page.indexOf('<main'),
    'site header must sit outside the main landmark',
  )
  check(
    page.indexOf('<footer') > page.indexOf('</main>') &&
      page.includes('aria-label="Resources"') &&
      page.includes('href="https://docs.boulderroller.xyz/">Docs</a>') &&
      page.includes('href="https://docs.boulderroller.xyz/reference/faq">FAQ</a>'),
    'resources footer must follow main and name the actual docs and FAQ destinations',
  )
  check(
    hero.includes('href="https://docs.boulderroller.xyz/"') &&
      hero.includes('Read the docs') &&
      hero.indexOf('className="coming-soon"') < hero.indexOf('className="docs-button"'),
    'product status must precede the real documentation action',
  )
  check(
    hero
      .replace(/\s+/g, ' ')
      .includes(
        'A cycling app with leaderboards that pay riders in DUNG.',
      ),
    'hero must preserve the approved rider-first promise',
  )
  check(
    !hero.includes('After the ride'),
    'public root must not include the ceremonial After the ride section',
  )
  check(
    !hero.includes('On each climb'),
    'public root must not include the ceremonial On each climb section',
  )
  check(
    !hero.includes('Vault deposits'),
    'public root must not explain an unasked-for deposit concern',
  )
  check(
    !hero.includes('leaderboardRows'),
    'public visual must not contain a fictional leaderboard',
  )
  check(
    !hero.includes('M. Reyes'),
    'public visual must not contain fictional rider data',
  )
  check(
    !hero.includes('42.8 km'),
    'public visual must not contain fictional ride data',
  )
  check(
    !hero.includes('Example ride'),
    'public visual must not present invented data as an example ride',
  )
  check(
    hero.includes('<figure'),
    'recorded ride inset must use figure semantics',
  )
  check(
    hero.includes('Wises Mill Road'),
    'recorded inset must identify the real climb accessibly',
  )
  check(
    hero.includes('128.7 kilometer ride'),
    'elevation profile must describe the full recorded ride',
  )
  check(
    hero.includes('alt=""'),
    'decorative terrain must defer to the real map and profile descriptions',
  )
  check(
    /<span className="coming-soon" role="status">[\s\S]*?Coming soon\s*<\/span>/.test(
      hero,
    ),
    'release status must not masquerade as an actionable button',
  )
  check(
    !hero.includes('<button'),
    'public root must not invent an invite or information action',
  )
  check(
    !hero.includes('Ride workshop preview'),
    'public root must not expose workshop implementation copy',
  )
  check(
    !hero.includes('Terrain illustration'),
    'measured terrain must not carry fabricated illustration labeling',
  )

  check(
    !hero.includes('fade-in-up'),
    'hero copy must not use generic reveal motion',
  )
  check(
    !css.includes('@keyframes fadeInUp'),
    'generic copy reveal keyframes must be removed',
  )
  check(
    !css.includes('@keyframes'),
    'static measured relief must not introduce ornamental motion',
  )
  check(
    css.includes('a:focus-visible'),
    'all links must expose a visible keyboard focus treatment',
  )
  check(
    hero.includes('https://carto.com/attribution/'),
    'static map must retain visible CARTO attribution',
  )
  check(
    hero.includes('https://www.openstreetmap.org/copyright'),
    'static map must retain visible OSM attribution',
  )

  if (failures.length > 0) {
    console.error('Public root check failed:')
    for (const failure of failures) console.error(`- ${failure}`)
    process.exit(1)
  }

  console.log('Public root check passed.')
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
