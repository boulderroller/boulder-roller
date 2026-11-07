/** The ratified duration tokens are authored in milliseconds, including reduced motion. */
export function settleDuration() {
  return Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--t-settle')) || 0;
}

/** MapLibre receives the same CSS easing as sheets and the ground. */
export function settleEasing(t: number) {
  const curve = getComputedStyle(document.documentElement).getPropertyValue('--ease');
  const values = curve.match(/[\d.]+/g)?.map(Number);
  if (!values || values.length !== 4) return t;
  const [x1, y1, x2, y2] = values;
  const bezier = (u: number, a: number, b: number) => 3 * (1 - u) ** 2 * u * a + 3 * (1 - u) * u ** 2 * b + u ** 3;
  let lo = 0, hi = 1;
  for (let i = 0; i < 16; i++) {
    const u = (lo + hi) / 2;
    if (bezier(u, x1, x2) < t) lo = u; else hi = u;
  }
  return bezier((lo + hi) / 2, y1, y2);
}
