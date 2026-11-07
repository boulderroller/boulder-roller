// Strava/Garmin-style fallback title for unnamed rides (ratified 2026-08-11).
// One shape across portal and iOS (ios/BoulderRoller/Design/Format.swift
// displayRideTitle) until the backend generates titles at processing time:
// place-flavored when the route preview knows where ("Manayunk Ride"),
// time-of-day otherwise ("Afternoon Ride"). The backend's literal default
// "Ride" counts as unnamed.
export function displayRideTitle(
  title: string | null | undefined,
  startedAt: string | null | undefined,
  placeLabel: string | null | undefined,
): string {
  if (title && title !== 'Ride' && title !== 'Activity') return title;
  const place = placeLabel?.split(',')[0]?.trim();
  if (place) return `${place} Ride`;
  const parsed = startedAt ? new Date(startedAt) : null;
  const hour = parsed && !Number.isNaN(parsed.getTime()) ? parsed.getHours() : 12;
  const bucket =
    hour >= 4 && hour < 11 ? 'Morning'
    : hour >= 11 && hour < 14 ? 'Lunch'
    : hour >= 14 && hour < 17 ? 'Afternoon'
    : hour >= 17 && hour < 21 ? 'Evening'
    : 'Night';
  return `${bucket} Ride`;
}
