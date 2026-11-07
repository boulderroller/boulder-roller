import { climbResult, type Climb, type Scenario } from '../scenario';
import type { ExampleEconomics } from '../v12Example';
import { feedScenarios, parseFeed, type FeedEntry, type FeedScenario } from './feedModel';

export type WorldSummary = {
  scope: 'platform'; periodStart: string; periodEnd: string; asOf: string;
  climbsRidden?: number; rideCal?: number; tributeCal?: number;
};
export type FeedEconomics = ExampleEconomics & { entryId: string; rideId: string };
export type FeedV2Scenario = FeedScenario & { workshopV2?: {
  source: string; world?: WorldSummary; rideEconomics: FeedEconomics[];
} };

const examples = new WeakMap<FeedScenario, FeedV2Scenario>();
export function withV2Example(scenario: FeedScenario): FeedV2Scenario {
  // Object membership is checked before serialization. Imports never inherit examples by ID.
  if (!feedScenarios.includes(scenario)) return scenario;
  const cached = examples.get(scenario); if (cached) return cached;
  const entry = scenario.entries.find(e => e.owned);
  const amounts: Record<string, number> = { '43f15658': 8, b51920f8: 3, '4fd1981e': 11 };
  const next: FeedV2Scenario = { ...scenario, workshopV2: {
    source: 'Feed V2 design values: platform totals and CAL are illustrative, independently supplied examples. They are not calculated from this feed or recording. Personal effort history is supplied in each climb; only the latest ride has a recording.',
    world: { scope: 'platform', periodStart: '2016-08-22T00:00:00-04:00', periodEnd: '2016-08-29T00:00:00-04:00', asOf: '2016-08-28T18:00:00-04:00', climbsRidden: 1284, rideCal: 86420, tributeCal: 6720 },
    rideEconomics: entry ? [{ entryId: entry.id, rideId: entry.ride.id, source: 'illustrative', riderCal: { amount: 312, state: 'pending' }, tributes: entry.ride.climbs.filter(c => amounts[c.id] !== undefined).map(c => ({ climbId: c.id, climbName: c.name, cal: { amount: amounts[c.id], state: 'pending' } })) }] : [],
  } };
  examples.set(scenario, next); return next;
}

function requireValue(value: unknown, message: string): asserts value { if (!value) throw Error(message); }
const amount = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0;
export function parseFeedV2(value: unknown): FeedV2Scenario {
  const feed = parseFeed(value) as FeedV2Scenario, context = feed.workshopV2;
  if (context === undefined) return feed;
  requireValue(context && typeof context.source === 'string' && context.source.trim() && Array.isArray(context.rideEconomics), 'V2 context needs a source and ride economics array.');
  const world = context.world;
  if (world !== undefined) {
    requireValue(world && world.scope === 'platform' && [world.periodStart, world.periodEnd, world.asOf].every(d => typeof d === 'string' && Number.isFinite(Date.parse(d))), 'World summary needs its platform scope and period.');
    requireValue(Date.parse(world.periodEnd) > Date.parse(world.periodStart) && Date.parse(world.asOf) >= Date.parse(world.periodStart) && Date.parse(world.asOf) <= Date.parse(world.periodEnd), 'World summary period must contain its as-of time.');
    for (const key of ['climbsRidden', 'rideCal', 'tributeCal'] as const) requireValue(world[key] === undefined || amount(world[key]), `Invalid world ${key}.`);
    requireValue(world.climbsRidden === undefined || Number.isInteger(world.climbsRidden), 'Climbs ridden must be a whole count.');
  }
  const seen = new Set<string>();
  const rideEconomics = context.rideEconomics.map(economics => {
    requireValue(economics && typeof economics.entryId === 'string' && !seen.has(economics.entryId), 'Duplicate or missing ride economics.');
    seen.add(economics.entryId);
    const entry = feed.entries.find(e => e.id === economics.entryId);
    requireValue(entry && entry.ride.id === economics.rideId, 'Economics must match the exact ride.');
    requireValue(entry.owned, 'Ride CAL requires the ride owner.');
    const validCal = (v: typeof economics.riderCal) => v && amount(v.amount) && ['pending', 'counted'].includes(v.state);
    requireValue(economics.source === 'illustrative' && validCal(economics.riderCal) && Array.isArray(economics.tributes), 'Ride CAL needs an explicit example amount and state.');
    const climbIds = new Set<string>();
    const tributes = economics.tributes.map(t => {
      requireValue(t && !climbIds.has(t.climbId) && validCal(t.cal), 'Invalid or duplicate climb tribute.');
      const climb = entry.ride.climbs.find(c => c.id === t.climbId);
      requireValue(climb, 'Tribute must match a climb on this ride.'); climbIds.add(t.climbId);
      return { ...t, climbName: climb.name };
    });
    return { ...economics, tributes };
  });
  return { ...feed, workshopV2: { source: context.source, ...(world ? { world: { ...world } } : {}), rideEconomics } };
}

export function personalTrend(scenario: FeedScenario) {
  for (const entry of scenario.entries.filter(e => e.owned).sort((a,b) => Date.parse(b.ride.ride.startedAt) - Date.parse(a.ride.ride.startedAt))) {
    const climb = entry.ride.climbs.find(c => c.history.length > 0);
    if (!climb) continue;
    const points = [...climb.history.map(p => ({ ...p, current: false })), { date: entry.ride.ride.startedAt, duration: climbResult(entry.ride, climb).duration, current: true }].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
    return { entry, climb, points };
  }
  return null;
}
export function climbBand(scenario: Scenario, climb: Climb) {
  const samples = scenario.ride.samples, start = samples.find(p => p.t === climb.start), end = samples.find(p => p.t === climb.end);
  const extent = samples.at(-1)!.d - samples[0].d;
  if (!start || !end || extent <= 0) return null;
  return { from: (start.d - samples[0].d) / extent, to: (end.d - samples[0].d) / extent };
}
export function economicsFor(scenario: FeedV2Scenario, entry: FeedEntry) {
  return entry.owned ? scenario.workshopV2?.rideEconomics.find(e => e.entryId === entry.id && e.rideId === entry.ride.id) : undefined;
}

export const formatFeedCal = (amount: number) => amount.toLocaleString('en-US', { maximumSignificantDigits: 21 });
