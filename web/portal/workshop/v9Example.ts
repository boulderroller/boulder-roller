import type { Rider, Scenario } from './scenario';

const exampleRider: Rider = { displayName: 'Example Rider', source: 'illustrative' };
export function v9Identity(scenario: Scenario, bundled: boolean): Scenario {
  return bundled && !scenario.ride.rider ? { ...scenario, ride: { ...scenario.ride, rider: exampleRider } } : scenario;
}

export type ExampleCal = { amount: number; state: 'pending' | 'counted' };
export type ExampleEconomics = {
  source: 'illustrative'; riderCal: ExampleCal;
  tributes: { climbId: string; climbName: string; cal: ExampleCal }[];
};
// User-authorized design values, not calculated from the FIT or canonical Vault matches.
const tributeExamples: Record<string, number> = { '43f15658': 8, 'b51920f8': 3, '4fd1981e': 11 };
export function v9Economics(scenario: Scenario, bundled: boolean): ExampleEconomics | null {
  if (!bundled || !['identity', 'history', 'recorded'].includes(scenario.id)) return null;
  const tributes = scenario.climbs.flatMap(climb => {
    const amount = tributeExamples[climb.id];
    return amount === undefined ? [] : [{ climbId: climb.id, climbName: climb.name, cal: { amount, state: 'pending' as const } }];
  });
  if (tributes.length !== 3) return null;
  return { source: 'illustrative', riderCal: { amount: 312, state: 'pending' }, tributes };
}
