import { formatDuration, formatWatts, formatKilometers } from '../src/lib/formatters';

// The existing RideBand needs only these pure formatters. The workshop has no
// authentication or wallet runtime; production's hook and providers are untouched.
export function useFormatters() {
  return { duration: formatDuration, watts: formatWatts, kilometers: formatKilometers };
}
