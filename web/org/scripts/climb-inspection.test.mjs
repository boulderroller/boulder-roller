import test from 'node:test'
import assert from 'node:assert/strict'
import {
  coverPoint,
  nearestRoutePosition,
  pointAtPosition,
  stepIndex,
  settleRoutePosition,
} from '../src/lib/climb-inspection.mjs'

test('cover projection follows actual image cropping at desktop and phone aspect ratios', () => {
  assert.deepEqual(coverPoint([50, 50], [100, 100], [200, 100]), [100, 50])
  assert.deepEqual(coverPoint([0, 0], [100, 100], [200, 100]), [0, -50])
  assert.deepEqual(
    coverPoint([50, 50], [100, 100], [100, 200], [0.52, 0.45]),
    [48, 100],
  )
})

test('pointer projection respects its hit radius and clamps to the route endpoints', () => {
  const points = [[0, 0], [100, 0]]
  assert.equal(nearestRoutePosition(points, [25, 10], 18), 0.25)
  assert.equal(nearestRoutePosition(points, [150, 130], 18), null)
  assert.equal(nearestRoutePosition(points, [150, 130]), 1)
})

test('pointer inspection follows the line between recording samples', () => {
  assert.equal(nearestRoutePosition([[0, 0], [100, 0]], [50, 10], 24), 0.5)
})

test('the wider attached corridor follows until the pointer deliberately leaves', () => {
  const points = [[0, 0], [100, 0]]
  assert.equal(nearestRoutePosition(points, [50, 35], 24), null)
  assert.equal(nearestRoutePosition(points, [60, 35], 48, 0.5), 0.6)
  assert.equal(nearestRoutePosition(points, [60, 49], 48, 0.6), null)
})

test('nearby overlapping branches preserve continuity but allow intentional relocation', () => {
  const outward = Array.from({length: 11}, (_, i) => [i * 10, 0])
  const inward = Array.from({length: 11}, (_, i) => [100 - i * 10, 4])
  const points = [...outward, ...inward]
  assert.equal(nearestRoutePosition(points, [30, 2.1], 24), 18)
  assert.equal(nearestRoutePosition(points, [30, 2.1], 48, 3), 3)
  assert.equal(nearestRoutePosition(points, [30, 20], 48, 3), 18)
  assert.equal(nearestRoutePosition(points, [100, 4], 48, 0), 11)
})

test('continuous positions synchronize projected frames without inventing readout samples', () => {
  assert.deepEqual(pointAtPosition([[0, 0], [100, 20]], 0.25), [25, 5])
  assert.deepEqual(pointAtPosition([[50, 100], [70, 200]], 0.25), [55, 125])
  assert.deepEqual(pointAtPosition([[0, 0], [100, 20]], 5), [100, 20])
  assert.equal(pointAtPosition([], 0), null)
  assert.equal(nearestRoutePosition([[5, 5], [5, 5]], [5, 5], 24), 0)
})

test('keyboard navigation clamps at real recording bounds instead of wrapping or fabricating samples', () => {
  assert.equal(stepIndex(null, 1, 236), 0)
  assert.equal(stepIndex(0, -1, 236), 0)
  assert.equal(stepIndex(235, 1, 236), 235)
  assert.equal(stepIndex(80, 10, 236), 90)
  assert.equal(stepIndex(80.4, 1, 236), 81)
  assert.equal(stepIndex(80.6, -1, 236), 80)
})

test('pointer settling advances along the route without teleporting or overshooting', () => {
  const first = settleRoutePosition(20, 180, 16)
  assert.ok(first > 20 && first < 180)
  assert.ok(settleRoutePosition(first, 0, 16) < first)
  let current = 20
  for (let frame = 0; frame < 40; frame++) current = settleRoutePosition(current, 180, 16)
  assert.equal(current, 180)
  assert.equal(settleRoutePosition(20, 180, 0), 20)
  assert.ok(settleRoutePosition(20, 180, 1000) < 180)
})
