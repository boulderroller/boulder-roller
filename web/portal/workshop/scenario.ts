export type Sample = { lon: number; lat: number; d: number; t: number; elevation: number | null; power: number | null; cadence?: number | null; speed?: number | null; heartRate?: number | null };
export type Climb = { id: string; name: string; start: number; end: number; history: { date: string; duration: number }[] };
export type Rider = { displayName: string; source: 'provided' | 'illustrative'; avatarDataUrl?: string };
export type Scenario = {
  version: 1; id: string; label: string;
  source: { description: string; kind: 'recorded' | 'illustrative'; history: 'none' | 'recorded' | 'illustrative'; sha256?: string };
  ride: { title: string; startedAt: string; location: string; samples: Sample[]; rider?: Rider };
  climbs: Climb[];
};

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
function check(condition: unknown, message: string): asserts condition { if (!condition) throw new Error(message); }
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
function word(v: unknown, name: string): string {
  check(typeof v === 'string' && v.trim().length > 0 && v.length <= 600, `${name} must be text (1–600 characters).`);
  return v.trim();
}

/** Import one explicit format. A failed import never replaces the active scenario. */
export function parseScenario(input: unknown): Scenario {
  check(object(input) && input.version === 1, 'Choose a workshop scenario with version: 1. Export a scenario for the format.');
  const id = word(input.id, 'ID'), label = word(input.label, 'Label');
  check(object(input.source), 'Include the source of the ride data.');
  const description = word(input.source.description, 'Source description');
  check(['recorded', 'illustrative'].includes(input.source.kind), 'Declare source kind as recorded or illustrative.');
  check(['none', 'recorded', 'illustrative'].includes(input.source.history), 'Declare history as none, recorded, or illustrative.');
  check(object(input.ride), 'Include a ride.');
  const title = word(input.ride.title, 'Ride title'), location = word(input.ride.location, 'Location');
  const startedAt = word(input.ride.startedAt, 'Ride date');
  check(Number.isFinite(Date.parse(startedAt)), 'The ride date must be a valid ISO date.');
  let rider: Rider | undefined;
  if (input.ride.rider !== undefined) {
    const supplied = input.ride.rider;
    check(object(supplied), 'Rider identity must be an object.');
    const displayName = word(supplied.displayName, 'Rider name');
    check(displayName.length <= 100, 'Rider name must be 100 characters or fewer.');
    check(['provided', 'illustrative'].includes(supplied.source), 'Declare rider identity as provided or illustrative.');
    const avatar = supplied.avatarDataUrl;
    check(avatar === undefined || (typeof avatar === 'string' && avatar.length <= 2800000 && /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(avatar)), 'Portrait must be an embedded PNG, JPEG or WebP image up to 2 MB.');
    rider = { displayName, source: supplied.source, ...(avatar === undefined ? {} : { avatarDataUrl: avatar }) };
  }
  check(Array.isArray(input.ride.samples) && input.ride.samples.length >= 2 && input.ride.samples.length <= 100000, 'Include 2–100,000 recorded samples.');
  let previousTime = -Infinity, previousDistance = -Infinity;
  const samples: Sample[] = input.ride.samples.map((p: unknown, i: number) => {
    check(object(p), `Sample ${i + 1} must be an object.`);
    check(finite(p.lon) && Math.abs(p.lon) <= 180 && finite(p.lat) && Math.abs(p.lat) <= 85, `Sample ${i + 1} has invalid coordinates.`);
    check(finite(p.t) && p.t >= 0 && p.t > previousTime, `Sample ${i + 1}: elapsed seconds must increase.`);
    check(finite(p.d) && p.d >= 0 && p.d >= previousDistance, `Sample ${i + 1}: distance must not decrease.`);
    check(p.elevation === null || finite(p.elevation), `Sample ${i + 1}: elevation must be a number or null.`);
    check(p.power === null || (finite(p.power) && p.power >= 0), `Sample ${i + 1}: power must be a positive number, zero, or null.`);
    for (const key of ['cadence', 'speed', 'heartRate'] as const) {
      check(p[key] === undefined || p[key] === null || (finite(p[key]) && p[key] >= 0), `Sample ${i + 1}: ${key} must be a positive number, zero, or null.`);
    }
    previousTime = p.t; previousDistance = p.d;
    return { lon: p.lon, lat: p.lat, d: p.d, t: p.t, elevation: p.elevation, power: p.power, cadence: p.cadence ?? null, speed: p.speed ?? null, heartRate: p.heartRate ?? null };
  });
  check(samples[0].t === 0 && samples[0].d === 0, 'Rebase the first sample to zero elapsed seconds and zero distance.');
  check(Array.isArray(input.climbs) && input.climbs.length <= 100, 'Include a climbs array with up to 100 climbs.');
  const times = new Set(samples.map(p => p.t)), ids = new Set<string>();
  const climbs: Climb[] = input.climbs.map((c: unknown) => {
    check(object(c), 'Each climb must be an object.');
    const climbId = word(c.id, 'Climb ID'), name = word(c.name, 'Climb name');
    check(!ids.has(climbId), 'Climb IDs must be unique.'); ids.add(climbId);
    check(finite(c.start) && finite(c.end) && c.end > c.start && times.has(c.start) && times.has(c.end), `${name}: start and end must match recorded sample times.`);
    check(Array.isArray(c.history) && c.history.length <= 100, `${name}: include a history array with up to 100 results.`);
    check(c.history.length === 0 || input.source.history !== 'none', 'Declare the source of the supplied history.');
    const history = c.history.map((h: unknown) => {
      check(object(h) && typeof h.date === 'string' && Number.isFinite(Date.parse(h.date)) && Date.parse(h.date) < Date.parse(startedAt), `${name}: previous results must precede this ride.`);
      check(finite(h.duration) && h.duration > 0, `${name}: previous result times must be positive.`);
      return { date: h.date, duration: h.duration };
    });
    return { id: climbId, name, start: c.start, end: c.end, history };
  });
  return { version: 1, id, label, source: { description, kind: input.source.kind, history: input.source.history, ...(typeof input.source.sha256 === 'string' ? { sha256: input.source.sha256 } : {}) }, ride: { title, location, startedAt, samples, ...(rider ? { rider } : {}) }, climbs };
}

export function summarize(samples: Sample[]) {
  let gain = 0, hasElevation = false, work = 0, covered = 0;
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i], dt = b.t - a.t;
    if (dt > 30) continue;
    if (a.elevation !== null && b.elevation !== null) { hasElevation = true; gain += Math.max(0, b.elevation - a.elevation); }
    if (a.power !== null) { work += a.power * dt; covered += dt; }
  }
  return { distance: samples.length ? samples.at(-1)!.d - samples[0].d : 0, gain: hasElevation ? gain : null, duration: samples.length ? samples.at(-1)!.t - samples[0].t : 0, power: covered ? work / covered : null };
}

export function climbSamples(scenario: Scenario, climb: Climb) {
  return scenario.ride.samples.filter(p => p.t >= climb.start && p.t <= climb.end);
}
export function climbResult(scenario: Scenario, climb: Climb) {
  const samples = climbSamples(scenario, climb), result = summarize(samples);
  const rise = samples[0].elevation !== null && samples.at(-1)!.elevation !== null ? samples.at(-1)!.elevation! - samples[0].elevation! : null;
  const previousBest = climb.history.length ? Math.min(...climb.history.map(h => h.duration)) : null;
  return { ...result, grade: rise !== null && result.distance > 0 ? rise / result.distance * 100 : null, previousBest, improvement: previousBest !== null ? previousBest - result.duration : null };
}

export function cropScenario(source: Scenario, from: number, to: number): Scenario {
  const points = source.ride.samples.filter(p => p.t >= from && p.t <= to);
  check(points.length >= 2, 'Choose a range with at least two samples.');
  const origin = points[0];
  return { ...source, id: `${source.id}-crop`, source: { ...source.source, description: `${source.source.description} Selected recorded interval.` }, ride: { ...source.ride, startedAt: new Date(Date.parse(source.ride.startedAt) + origin.t * 1000).toISOString(), samples: points.map(p => ({ ...p, t: p.t - origin.t, d: p.d - origin.d })) }, climbs: source.climbs.filter(c => c.start >= origin.t && c.end <= points.at(-1)!.t).map(c => ({ ...c, start: c.start - origin.t, end: c.end - origin.t })) };
}

export function timeLabel(seconds: number) {
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${m}:${String(s % 60).padStart(2, '0')}`;
}
export const distanceLabel = (m: number) => (m / 1000).toLocaleString('en-US', { maximumFractionDigits: m < 10000 ? 2 : 1 });
export const integer = (v: number) => Math.round(v).toLocaleString('en-US');
