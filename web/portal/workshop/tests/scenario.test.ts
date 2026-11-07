import assert from 'node:assert/strict';
import test from 'node:test';
import { parseScenario, summarize, climbResult, cropScenario } from '../scenario.ts';

const fixture = () => ({
  version: 1, id: 'recorded', label: 'Recorded ride',
  source: { description: 'Recorded test source', kind: 'illustrative', history: 'none' },
  ride: { title: 'A ride', startedAt: '2026-09-10T10:00:00Z', location: 'Philadelphia',
    samples: [
      { lon: -75.2, lat: 40, d: 0, t: 0, elevation: 10, power: 100 },
      { lon: -75.199, lat: 40, d: 100, t: 10, elevation: 20, power: 200 },
      { lon: -75.198, lat: 40, d: 200, t: 30, elevation: 18, power: null },
      { lon: -75.197, lat: 40, d: 300, t: 40, elevation: 30, power: 300 },
    ] },
  climbs: [{ id: 'hill', name: 'A climb', start: 10, end: 40, history: [] }],
});

test('summary and selected climb use their exact recorded intervals', () => {
  const scenario = parseScenario(fixture());
  assert.deepEqual(summarize(scenario.ride.samples), { distance: 300, gain: 22, duration: 40, power: 5000 / 30 });
  const climb = climbResult(scenario, scenario.climbs[0]);
  assert.equal(climb.distance, 200);
  assert.equal(climb.duration, 30);
  assert.equal(climb.gain, 12);
  assert.equal(climb.power, 200);
});

test('rejects impossible geometry, nonmonotonic streams, and unbounded climb windows', () => {
  for (const mutate of [
    (s: any) => { s.ride.samples[1].lat = 200; },
    (s: any) => { s.ride.samples[1].t = -1; },
    (s: any) => { s.ride.samples[2].d = 20; },
    (s: any) => { s.climbs[0].end = 999; },
    (s: any) => { s.climbs[0].start = 11; },
    (s: any) => { s.climbs.push(s.climbs[0]); },
  ]) {
    const s = fixture(); mutate(s);
    assert.throws(() => parseScenario(s));
  }
});

test('missing measurements stay absent and are never bridged across recording gaps', () => {
  const s = fixture(); s.ride.samples.forEach(p => { p.power = null as any; p.elevation = null as any; });
  assert.equal(summarize(parseScenario(s).ride.samples).power, null);
  assert.equal(summarize(parseScenario(s).ride.samples).gain, null);
  assert.equal(summarize([{ ...s.ride.samples[0], power: 200 }, { ...s.ride.samples[1], t: 100, power: 300 }]).power, null);
});

test('crop rebases geometry and climb windows without changing elapsed time or measurements', () => {
  const s = cropScenario(parseScenario(fixture()), 10, 40);
  assert.equal(s.ride.samples[0].t, 0);
  assert.equal(s.ride.samples[0].d, 0);
  assert.equal(s.climbs[0].start, 0);
  assert.equal(s.climbs[0].end, 30);
  assert.equal(summarize(s.ride.samples).distance, 200);
  assert.doesNotThrow(() => parseScenario(s));
});

test('illustrative history must be declared and precede the ride', () => {
  const s = fixture();
  s.climbs[0].history = [{ date: '2026-09-01T10:00:00Z', duration: 34 }] as any;
  assert.throws(() => parseScenario(s));
  s.source.history = 'illustrative';
  assert.doesNotThrow(() => parseScenario(s));
  s.climbs[0].history = [{ date: '2026-09-12T10:00:00Z', duration: 34 }] as any;
  assert.throws(() => parseScenario(s));
});

test('optional sensor streams preserve measured zeros, missing values, and export round trips', () => {
  const input = fixture();
  Object.assign(input.ride.samples[0], { cadence: 0, speed: 0, heartRate: 124 });
  Object.assign(input.ride.samples[1], { cadence: 82, speed: 8.5, heartRate: null });
  const parsed = parseScenario(input);
  assert.equal(parsed.ride.samples[0].cadence, 0);
  assert.equal(parsed.ride.samples[0].speed, 0);
  assert.equal(parsed.ride.samples[0].heartRate, 124);
  assert.equal(parsed.ride.samples[1].cadence, 82);
  assert.equal(parsed.ride.samples[1].heartRate, null);
  assert.equal(parsed.ride.samples[2].heartRate, null);
  assert.deepEqual(parseScenario(JSON.parse(JSON.stringify(parsed))), parsed);
  Object.assign(input.ride.samples[0], { cadence: -1 });
  assert.throws(() => parseScenario(input), /cadence/);
});

test('supplied rider identity survives import, export and cropping without inferring an owner', () => {
  const input = fixture();
  const rider = { displayName: 'Example Rider', source: 'illustrative', avatarDataUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l/8AAAAASUVORK5CYII=' };
  Object.assign(input.ride, { rider });
  const parsed = parseScenario(input);
  assert.deepEqual(parsed.ride.rider, rider);
  assert.deepEqual(parseScenario(JSON.parse(JSON.stringify(parsed))).ride.rider, rider);
  assert.deepEqual(cropScenario(parsed, 10, 40).ride.rider, rider);
  assert.equal(parseScenario(fixture()).ride.rider, undefined);
});

test('rider metadata requires explicit provenance and a self-contained portrait', () => {
  const input = fixture();
  for (const rider of [
    { displayName: 'Example Rider' },
    { displayName: ' ', source: 'provided' },
    { displayName: 'Example Rider', source: 'recorded' },
    { displayName: 'Example Rider', source: 'provided', avatarDataUrl: 'https://example.com/photo.jpg' },
    { displayName: 'Example Rider', source: 'provided', avatarDataUrl: 'data:image/svg+xml;base64,PHN2Zz4=' },
  ]) {
    Object.assign(input.ride, { rider });
    assert.throws(() => parseScenario(input), /[Rr]ider|[Pp]ortrait/);
  }
});
