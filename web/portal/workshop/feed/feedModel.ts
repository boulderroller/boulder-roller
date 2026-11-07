import { cropScenario, parseScenario, type Scenario } from '../scenario';
import { scenarios } from '../scenarios';
export type FeedComment = {
    id: string;
    name: string;
    text: string;
};
export type FeedEntry = {
    id: string;
    ride: Scenario;
    followed: boolean;
    owned: boolean;
    description: string;
    companions: string[];
    kudos: number;
    comments: FeedComment[];
};
export type FeedScenario = {
    version: 1;
    id: string;
    label: string;
    source: string;
    viewer: string;
    entries: FeedEntry[];
};
const recorded = scenarios[0];
const rider = (ride: Scenario, id: string, name: string, title: string): Scenario => ({ ...ride, id, label: title, source: { ...ride.source, description: `${ride.source.description} Illustrative Feed context; this is a presentation study using the retained recording.` }, ride: { ...ride.ride, title, rider: { displayName: name, source: 'illustrative' } } });
const complete = rider(scenarios[1], 'feed-in-the-bag', 'Example Rider', 'In the bag');
const mill = rider(cropScenario(recorded, 5900, 7600), 'feed-mill', 'Alex', 'Wises Mill Road');
const short = rider(cropScenario(recorded, 14300, 16800), 'feed-evening', 'Jamie', 'Along the river');
short.climbs = [];
export const mixedFeed: FeedScenario = { version: 1, id: 'mixed', label: 'Mixed rides', viewer: 'Example Rider', source: 'Illustrative riders, social activity and history. All routes and measurements use one retained ride and its excerpts; these are not separate recorded activities.', entries: [
        { id: 'in-the-bag', ride: complete, followed: false, owned: true, description: '', companions: ['Alex', 'Jamie'], kudos: 12, comments: [{ id: 'c1', name: 'Alex', text: 'That last climb was a good one.' }, { id: 'c2', name: 'Jamie', text: 'Same loop next weekend?' }] },
        { id: 'mill', ride: mill, followed: true, owned: false, description: 'A little time in the hills.', companions: [], kudos: 6, comments: [] },
        { id: 'evening', ride: short, followed: true, owned: false, description: '', companions: [], kudos: 3, comments: [{ id: 'c3', name: 'Alex', text: 'Good to get out.' }] }
    ] };
export const feedScenarios: FeedScenario[] = [mixedFeed, { ...mixedFeed, id: 'quiet', label: 'Quiet ride · limited measurements', entries: [{ ...mixedFeed.entries[2], id: 'quiet', ride: { ...short, id: 'feed-quiet', ride: { ...short.ride, samples: short.ride.samples.map(p => ({ ...p, power: null, cadence: null })) } }, kudos: 0, comments: [] }] }, { ...mixedFeed, id: 'long-title', label: 'Long title & conversation', entries: [{ ...mixedFeed.entries[0], ride: { ...complete, id: 'feed-long', ride: { ...complete.ride, title: 'The long way home through the hills, down to the river, and back again before the afternoon rain' } }, description: 'A few familiar roads, a few extra turns, and a little longer outside than we planned.' }, ...mixedFeed.entries.slice(1)] }];
export function parseFeed(value: unknown): FeedScenario {
    if (!value || typeof value !== 'object')
        throw Error('Choose a Feed scenario.');
    const s = value as FeedScenario;
    if (s.version !== 1 || !s.id || !s.label || typeof s.viewer !== 'string' || typeof s.source !== 'string' || !Array.isArray(s.entries) || s.entries.length > 50)
        throw Error('Feed scenarios need a label, source, viewer and up to 50 rides.');
    const ids = new Set<string>();
    const entries = s.entries.map(e => {
        if (!e || typeof e.id !== 'string' || ids.has(e.id) || typeof e.description !== 'string' || typeof e.followed !== 'boolean' || typeof e.owned !== 'boolean' || !Number.isInteger(e.kudos) || e.kudos < 0 || !Array.isArray(e.companions) || !e.companions.every(x => typeof x === 'string') || !Array.isArray(e.comments))
            throw Error('Each ride needs a unique ID and valid social fields.');
        ids.add(e.id);
        const comments = e.comments.map(c => { if (!c || typeof c.id !== 'string' || typeof c.name !== 'string' || typeof c.text !== 'string')
            throw Error('Comments need an ID, rider and text.'); return { ...c }; });
        if (new Set(comments.map(c => c.id)).size !== comments.length)
            throw Error('Comment IDs must be unique within a ride.');
        return { ...e, ride: parseScenario(e.ride), comments };
    });
    return { ...s, entries };
}
export const feedImports = new Map<string, FeedScenario>();
export function feedById(id: string | null) { return feedScenarios.find(s => s.id === id) ?? feedImports.get(id ?? '') ?? mixedFeed; }
export function feedRide(id: string | null) { return [...feedScenarios, ...feedImports.values()].flatMap(s => s.entries).find(e => e.ride.id === id)?.ride; }
export function visibleEntries(scenario: FeedScenario, filter: string) { return scenario.entries.filter(e => filter !== 'following' || e.followed); }
export function rideHref(entry: FeedEntry, climb?: string) { const p = new URLSearchParams({ surface: 'ride', variant: 'candidate-v12', scenario: entry.ride.id, viewer: entry.owned ? 'owner' : 'visitor' }); if (climb) {
    p.set('view', 'analysis');
    p.set('climb', climb);
} return `/?${p}`; }
