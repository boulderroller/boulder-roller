import { readFile, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

const root = resolve(new URL('..', import.meta.url).pathname)
const read = (file) => readFile(resolve(root, file))
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex')

try {
  const manifest = JSON.parse(await read('terrain-source/delivery.json'))
  const rideBytes = await read('../portal/workshop/data/in-the-bag.json')
  const { ride, climbs } = JSON.parse(rideBytes)
  const climb = climbs.find((c) => c.id === manifest.climb.id)
  assert.ok(climb, 'rendered climb must exist in the recorded ride')
  assert.equal(
    hash(rideBytes),
    manifest.ride.sha256,
    'recorded ride source changed; regenerate the profile and provenance',
  )
  const points = ride.samples.filter(
    (p) => p.t >= climb.start && p.t <= climb.end,
  )
  const modelBytes = await read('src/data/wises-inspection.json')
  assert.equal(hash(modelBytes), manifest.inspection.clientModelSha256)
  const inspection = JSON.parse(modelBytes)
  const projections = JSON.parse(
    await read('terrain-source/inspection/source-projections.json'),
  )
  assert.equal(inspection.samples.length, points.length)
  assert.deepEqual(
    projections.fixedSceneFingerprints,
    JSON.parse(await read('terrain-source/source-provenance.json'))
      .expected_final_fixed_fingerprints,
  )
  const mercator = (lon, lat) => [
    (lon + 180) / 360,
    (180 -
      (180 / Math.PI) *
        Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) /
      360,
  ]
  for (const [i, point] of points.entries()) {
    const sample = inspection.samples[i]
    assert.deepEqual(
      [sample.t, sample.d, sample.elevation],
      [point.t, point.d, point.elevation],
    )
    for (const frame of [
      'terrain',
      'mapDesktop',
      'mapMobile',
      'profileDesktop',
      'profileMobile',
    ]) {
      assert.deepEqual(inspection.frames[frame], {
        width: projections.frames[frame].width,
        height: projections.frames[frame].height,
      })
      let expected = projections.samples[i][frame]
      if (frame.startsWith('map')) {
        const source = projections.frames[frame]
        const center = mercator(...source.camera.center)
        const location = mercator(point.lon, point.lat)
        const scale = 512 * 2 ** source.camera.zoom
        expected = [
          ((location[0] - center[0]) * scale) / source.logicalWidth + 0.5,
          ((location[1] - center[1]) * scale) / source.logicalHeight + 0.5,
        ]
      } else if (frame.startsWith('profile')) {
        const left = frame === 'profileMobile' ? 0.1 : 0.085
        expected = [
          left + (point.d / ride.samples.at(-1).d) * (0.994 - left),
          0.77 - (point.elevation / 175) * 0.65,
        ]
      }
      for (let axis = 0; axis < 2; axis++)
        assert.ok(
          Math.abs(sample[frame][axis] - expected[axis]) < 1e-7,
          `recorded sample ${i} projection ${frame}`,
        )
    }
  }
  const route = JSON.parse(await read('terrain-source/route.json'))
  assert.deepEqual(
    route.coordinates,
    points.map((p) => [p.lon, p.lat]),
    'terrain route must contain the exact recorded GPS points',
  )
  assert.equal(points.length, 236)
  assert.equal(
    manifest.terrain.verticalExaggeration,
    1,
    'measured relief cannot exaggerate elevation',
  )
  assert.equal(manifest.terrain.contourIntervalMeters, 2)
  assert.equal(
    manifest.profile.sampleCount,
    ride.samples.filter((p) => p.elevation != null).length,
  )
  assert.equal(
    manifest.profile.gapCount,
    ride.samples.slice(1).filter((p, i) => p.t - ride.samples[i].t > 30).length,
  )
  assert.equal(
    manifest.profile.gapThresholdSeconds,
    30,
    'profile must preserve recording gaps',
  )
  assert.equal(manifest.profile.distanceKm, ride.samples.at(-1).d / 1000)
  for (const input of manifest.inputs) {
    const bytes = await read(input.path)
    assert.equal(hash(bytes), input.sha256, `source integrity: ${input.path}`)
    if (input.path.endsWith('.gz'))
      assert.equal(hash(gunzipSync(bytes)), input.uncompressedSha256)
  }
  for (const asset of manifest.assets) {
    const bytes = await read(`public${asset.url}`)
    assert.equal(
      hash(bytes),
      asset.sha256,
      `delivered asset integrity: ${asset.url}`,
    )
    assert.equal(bytes.length, asset.bytes)
    assert.ok(
      bytes.length <= asset.budgetBytes,
      `asset exceeds delivery budget: ${asset.url}`,
    )
    if (asset.kind === 'terrain')
      assert.equal(
        asset.width * 31,
        asset.height * 44,
        'terrain aspect ratio changed',
      )
  }
  const hero = `${await read('src/components/Hero.tsx')}\n${await read('src/components/ClimbExplorer.tsx')}`
  assert.ok(
    hero.includes('type="image/avif"') && hero.includes('type="image/webp"'),
    'production must deliver both optimized terrain formats',
  )
  assert.ok(
    !hero.includes('maplibre') && !hero.includes('Canvas'),
    'SVG inspection must not boot a map or 3D engine',
  )
  assert.ok(
    hero.includes('https://www.openstreetmap.org/copyright') &&
      hero.includes('https://carto.com/attribution/'),
    'map attribution needs real visible destinations',
  )
  assert.ok(
    (await stat(resolve(root, 'terrain-source/render_wises.py'))).isFile(),
    'measured relief must have a reproducible source renderer',
  )
  console.log(
    'Terrain delivery passed: exact recorded GPS, native relief, gap-preserving full-ride profile, source hashes and asset budgets.',
  )
} catch (error) {
  console.error(`Terrain delivery failed: ${error.message}`)
  process.exitCode = 1
}
