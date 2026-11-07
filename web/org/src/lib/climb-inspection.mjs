/** @typedef {[number, number]} Point */

/**
 * Match the browser's object-fit: cover transform, including object-position.
 * @param {Point} point
 * @param {Point} image
 * @param {Point} box
 * @param {Point} position
 * @returns {Point}
 */
export function coverPoint(point, image, box, position = [0.5, 0.5]) {
  const scale = Math.max(box[0] / image[0], box[1] / image[1])
  return [
    point[0] * scale + (box[0] - image[0] * scale) * position[0],
    point[1] * scale + (box[1] - image[1] * scale) * position[1],
  ]
}

/**
 * Project onto the measured polyline in screen pixels. A nearby continuation
 * wins over another branch only when their pointer distances are similar.
 * @param {Point[]} points
 * @param {Point} pointer
 * @param {number} radius
 * @param {number|null} previous
 * @returns {number|null} Fractional sample position.
 */
export function nearestRoutePosition(points, pointer, radius = Infinity, previous = null) {
  /** @type {{position: number, distance: number}|null} */
  let nearest = null
  /** @type {{position: number, distance: number}|null} */
  let continuation = null
  for (let i = 0; i < points.length; i++) {
    const start = points[i]
    const end = points[Math.min(i + 1, points.length - 1)]
    const dx = end[0] - start[0]
    const dy = end[1] - start[1]
    const lengthSquared = dx * dx + dy * dy
    const fraction = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
      ((pointer[0] - start[0]) * dx + (pointer[1] - start[1]) * dy) / lengthSquared,
    ))
    const distance = (start[0] + dx * fraction - pointer[0]) ** 2
      + (start[1] + dy * fraction - pointer[1]) ** 2
    const candidate = { position: i + fraction, distance }
    if (distance > radius * radius) continue
    if (!nearest || distance < nearest.distance) nearest = candidate
    if (previous != null && Math.abs(candidate.position - previous) <= 8
      && (!continuation || distance < continuation.distance
        || (distance === continuation.distance
          && Math.abs(candidate.position - previous) < Math.abs(continuation.position - previous)))) {
      continuation = candidate
    }
  }
  if (nearest && continuation
    && Math.sqrt(continuation.distance) <= Math.sqrt(nearest.distance) + 3) {
    return continuation.position
  }
  return nearest?.position ?? null
}

/** @param {Point[]} points @param {number} position @returns {Point|null} */
export function pointAtPosition(points, position) {
  if (!points.length) return null
  const bounded = Math.max(0, Math.min(points.length - 1, position))
  const index = Math.floor(bounded)
  const fraction = bounded - index
  const start = points[index]
  const end = points[Math.min(index + 1, points.length - 1)]
  return [
    start[0] + (end[0] - start[0]) * fraction,
    start[1] + (end[1] - start[1]) * fraction,
  ]
}

/**
 * Ease the shared route position, rather than each marker's screen coordinates.
 * Clamp elapsed time so a resumed background frame cannot teleport the markers.
 * @param {number} current
 * @param {number} target
 * @param {number} elapsed
 */
export function settleRoutePosition(current, target, elapsed) {
  const next = current + (target - current)
    * (1 - Math.exp(-Math.max(0, Math.min(32, elapsed)) / 45))
  return Math.abs(target - next) < 0.01 ? target : next
}

/** @param {number|null} index @param {number} delta @param {number} count */
export function stepIndex(index, delta, count) {
  return index == null ? 0 : Math.max(0, Math.min(count - 1, Math.round(index) + delta))
}
