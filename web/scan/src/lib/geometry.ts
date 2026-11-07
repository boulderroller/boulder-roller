/** Point along the canonical route by distance; vertex spacing need not be uniform. */
export function coordinateAtFraction(
  coordinates: number[][],
  fraction: number,
): number[] | null {
  if (
    coordinates.length < 2 ||
    !Number.isFinite(fraction) ||
    coordinates.some(
      (p) => p.length < 2 || !Number.isFinite(p[0]) || !Number.isFinite(p[1]),
    )
  )
    return null;
  const radians = (n: number) => (n * Math.PI) / 180;
  const lengths = coordinates.slice(1).map((b, i) => {
    const a = coordinates[i],
      dlat = radians(b[1] - a[1]),
      dlon = radians(b[0] - a[0]);
    const h =
      Math.sin(dlat / 2) ** 2 +
      Math.cos(radians(a[1])) *
        Math.cos(radians(b[1])) *
        Math.sin(dlon / 2) ** 2;
    return 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
  });
  const total = lengths.reduce((sum, n) => sum + n, 0);
  let remaining = total * Math.max(0, Math.min(1, fraction));
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i]) {
      const ratio = lengths[i] ? remaining / lengths[i] : 0;
      return [
        coordinates[i][0] + ratio * (coordinates[i + 1][0] - coordinates[i][0]),
        coordinates[i][1] + ratio * (coordinates[i + 1][1] - coordinates[i][1]),
      ];
    }
    remaining -= lengths[i];
  }
  return coordinates.at(-1)!.slice(0, 2);
}
