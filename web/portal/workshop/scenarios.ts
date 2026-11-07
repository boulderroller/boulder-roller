import recordedData from './data/in-the-bag.json';
import { parseScenario, cropScenario, type Scenario } from './scenario';

const recorded = parseScenario(recordedData);
const withHistory: Scenario = {
  ...recorded, id: 'history', label: 'New best · illustrative history',
  source: { ...recorded.source, history: 'illustrative', description: `${recorded.source.description} Previous result dates and times are illustrative, to test achievement and history presentation.` },
  climbs: recorded.climbs.map((c, i) => ({ ...c, history: [7, 21, 42, 63].map((days, j) => ({ date: new Date(Date.parse(recorded.ride.startedAt) - days * 86400000).toISOString(), duration: c.end - c.start + (i === 0 ? [8, 19, 5, 28][j] : [-4, 8, -2, 16][j]) })) })),
};
const excerpt = cropScenario(recorded, 5900, 7600);
excerpt.id = 'excerpt'; excerpt.label = 'Short ride · limited measurements';
excerpt.ride = { ...excerpt.ride, title: 'In the bag · Wises Mill excerpt', samples: excerpt.ride.samples.map(p => ({ ...p, power: null })) };
excerpt.source.description += ' Power is deliberately omitted in this scenario.';

export const identityScenario = parseScenario({
  ...recorded, id: 'identity', label: 'Rider identity · illustrative',
  ride: { ...recorded.ride, rider: { displayName: 'Example Rider', source: 'illustrative' } },
  source: { ...recorded.source, description: `${recorded.source.description} The rider name is illustrative, to compare identity presentation. The source recording has no rider name or portrait.` },
});

export const scenarios = [recorded, parseScenario(withHistory), parseScenario(excerpt), identityScenario];
