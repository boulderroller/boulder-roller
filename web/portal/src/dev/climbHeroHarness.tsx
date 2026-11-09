// Dev-only design bench: renders the climb identity object and the record
// board on real canon data + synthetic riders. Reached only via
// /harness-climb-hero.html on the dev server; not a build entry.
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import ClimbLeaderboard from '../components/climb/ClimbLeaderboard';
import '../index.css';
import '../styles/portal-spine.css';
import '../styles/portal-surfaces.css';
import ClimbProfileHero, { type ProfilePoint } from '../components/climb/ClimbProfileHero';
import PowerCurveChart from '../components/training/PowerCurveChart';
import ConsistencyHeatmap from '../components/training/ConsistencyHeatmap';
import { formatHoursMinutes, formatInteger, formatKilometers, formatPercent } from '../lib/formatters';

// Synthetic riders for design judgment only — never live evidence.
const FIXTURE_BOARD = [
  { rank: 1, userId: 'fx1', displayName: 'A. Okonkwo', timeS: 161, avgPowerW: 412, vam: 1432 },
  { rank: 2, userId: 'fx2', displayName: 'M. Duarte', timeS: 168, avgPowerW: 389, vam: 1371 },
  { rank: 3, userId: 'fx3', displayName: 'S. Lindqvist', timeS: 175, avgPowerW: 365, vam: 1318 },
  { rank: 4, userId: 'fx4', displayName: 'J. Whitfield', timeS: 187, avgPowerW: 341, vam: 1233 },
  { rank: 5, userId: 'fx5', displayName: 'R. Castellanos', timeS: 192, avgPowerW: 318, vam: 1201 },
  { rank: 6, userId: 'fx6', displayName: 'K. Brennan', timeS: 206, avgPowerW: 301, vam: 1119 },
  { rank: 7, userId: 'fx7', displayName: 'T. Nakamura', timeS: 221, avgPowerW: 288, vam: 1043 },
  { rank: 8, userId: 'fx8', displayName: 'E. Sorensen', timeS: 242, avgPowerW: 254, vam: 953 },
];

// Deterministic synthetic rhythm: ~4 rides/week with a two-week gap and a
// building block at the end — enough shape to judge the encoding honestly.
function syntheticRidingDays(endDate: string, weeks: number, tssMode = false) {
  const end = new Date(`${endDate}T00:00:00Z`);
  const out: Array<{ date: string; value: number; rides: number }> = [];
  let seed = 7;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let i = weeks * 7 - 1; i >= 0; i -= 1) {
    const d = new Date(end); d.setUTCDate(end.getUTCDate() - i);
    const dow = (d.getUTCDay() + 6) % 7;
    const gap = i > 60 && i < 74;
    const thresholdBlank = false && tssMode && i > 120;
    const rides = gap || thresholdBlank ? 0 : (dow === 5 || dow === 6 ? (rnd() < 0.8 ? 1 : 0) : rnd() < 0.45 ? 1 : 0) + (rnd() < 0.08 ? 1 : 0);
    if (!rides) continue;
    const base = dow >= 5 ? 5400 + rnd() * 7200 : 2400 + rnd() * 3600;
    const value = tssMode ? Math.round(base / 60 * 1.1) : Math.round(base * (i < 21 ? 1.25 : 1));
    out.push({ date: d.toISOString().slice(0, 10), value, rides });
  }
  return out;
}

const fmtHm = (s: number) => formatHoursMinutes(s);

function FixtureBoard() {
  return <ClimbLeaderboard entries={FIXTURE_BOARD.map((entry) => ({ key: String(entry.rank), seat: entry.rank, rank: entry.rank, name: entry.displayName, timeS: entry.timeS, avgPowerW: entry.avgPowerW, powerKind: 'measured' }))} />;
}

interface HarnessClimb {
  id: string;
  name: string;
  lengthM: number;
  avgPct: number | null;
  profile: ProfilePoint[];
}

function Harness() {
  const [climbs, setClimbs] = useState<HarnessClimb[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/climbs/list')
      .then((r) => r.json())
      .then((d: { climbs?: Array<Record<string, unknown>> }) => {
        const rows = (d.climbs ?? [])
          .map((c) => {
            const raw = (c.elevation_profile ?? []) as Array<{ distance_m: number; elevation_m: number }>;
            const profile = raw.map((p) => ({ distanceM: p.distance_m, elevationM: p.elevation_m }));
            return {
              id: String(c.id ?? ''),
              name: String(c.name ?? ''),
              lengthM: Number(c.length_m ?? 0),
              avgPct: typeof c.avg_gradient_pct === 'number' ? c.avg_gradient_pct : null,
              profile,
            };
          })
          .filter((c) => c.profile.length >= 2);
        setClimbs(rows);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p style={{ padding: 24 }}>load failed: {error}</p>;
  if (!climbs.length) return <p style={{ padding: 24 }}>loading…</p>;

  const hero = climbs.find((c) => c.name.includes('Shawmont')) ?? climbs[0];
  const others = climbs
    .filter((c) => c.id !== hero.id)
    .sort((a, b) => (b.avgPct ?? 0) - (a.avgPct ?? 0));
  const picks = [
    others[0], // steepest
    others[Math.floor(others.length / 2)], // middling
    others[others.length - 1], // gentlest
    others.reduce((m, c) => (c.lengthM > m.lengthM ? c : m), others[0]), // longest
    others.reduce((m, c) => (c.lengthM < m.lengthM ? c : m), others[0]), // shortest
  ].filter((c, i, a) => c && a.indexOf(c) === i);

  const card = (c: HarnessClimb) => (
    <figure key={c.id} style={{ margin: 0, background: '#1B1A17', borderRadius: 8, padding: 16 }}>
      <ClimbProfileHero profile={c.profile} />
      <figcaption style={{ marginTop: 10, fontSize: 13, color: '#9A9488' }}>
        {c.name} · {formatKilometers(c.lengthM / 1000)}{c.avgPct != null ? ` · ${formatPercent(c.avgPct, 1)}` : ''}
      </figcaption>
    </figure>
  );

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: 32, display: 'grid', gap: 24 }}>
      {card(hero)}
      <FixtureBoard />
      {[
        { key: 'time', label: 'Consistency — Time read (default): riding time per day, 26 weeks', tss: false },
        { key: 'load', label: 'Consistency — Load read (once a Threshold exists): TSS per day, 26 weeks', tss: true },
      ].map((v) => (
        <figure key={v.key} style={{ margin: 0, background: '#1B1A17', borderRadius: 8, padding: 16 }}>
          <ConsistencyHeatmap
            days={syntheticRidingDays('2026-09-01', 26, v.tss)}
            endDate="2026-09-01"
            weeks={26}
            formatValue={v.tss ? (n) => `${formatInteger(n)} stress` : fmtHm}
          />
          <figcaption style={{ marginTop: 8, fontSize: 12, color: '#6A6660' }}>{v.label} — synthetic rider, design preview</figcaption>
        </figure>
      ))}
      <figure style={{ margin: 0, background: '#1B1A17', borderRadius: 8, padding: 16 }}>
        <PowerCurveChart
          series={{
            durationsS: [1, 5, 15, 30, 60, 120, 180, 300, 420, 600, 900, 1200, 1800, 2700, 3600],
            bestW: [842, 731, 612, 528, 441, 372, 341, 312, 298, 286, 274, 268, 259, 249, 241],
            sealedW: 262,
            candidateW: 271,
            anchorsS: [180, 420, 900],
          }}
        />
        <figcaption style={{ marginTop: 8, fontSize: 12, color: '#6A6660' }}>power curve — synthetic rider, design preview; sealed Threshold 262 W, candidate 271 W</figcaption>
      </figure>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
        {picks.map((c) => card(c))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
        {[hero, ...picks].map((c) => (
          <figure key={`compact-${c.id}`} style={{ margin: 0, background: '#1B1A17', borderRadius: 8, padding: 12 }}>
            <ClimbProfileHero profile={c.profile} compact />
            <figcaption style={{ marginTop: 8, fontSize: 12, color: '#6A6660' }}>{c.name}</figcaption>
          </figure>
        ))}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter>
      <Harness />
    </MemoryRouter>
  </StrictMode>,
);
