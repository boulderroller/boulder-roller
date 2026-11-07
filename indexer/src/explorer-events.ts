import { loadIdl } from './decoder';
import { visibleEvents } from './program-visibility';

const snakeCase = (name: string): string => name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
let eventTypes: Map<string, Map<string, unknown>> | undefined;

/** Add a renderable, typed view without changing the stored event payload. */
export function decodeExplorerEvents(events: Record<string, any>[]): Record<string, any>[] {
  events = visibleEvents(events);
  if (!eventTypes) {
    eventTypes = new Map((loadIdl().events || []).map((event: any) => [
      event.name,
      new Map(event.fields.map((field: any) => [snakeCase(field.name), field.type])),
    ]));
  }
  const decoded: Array<Record<string, any> & { decoded_fields: Array<{ name: string; type?: unknown; value: unknown }> }> = events.map(event => ({
    ...event,
    decoded_fields: Object.entries(event.fields || {})
      .filter(([, value]) => value !== null && value !== undefined && value !== '[object Object]')
      .map(([key, value]) => {
        const name = snakeCase(key);
        const type = eventTypes!.get(event.event_name)?.get(name);
        return { name, ...(type === undefined ? {} : { type }), value };
      }),
  }));
  const fieldsOf = (event: typeof decoded[number]): Record<string, any> =>
    Object.fromEntries(event.decoded_fields.map(field => [field.name, field.value]));

  return decoded.map(event => {
    if (event.event_name !== 'EpochRewardsDistributed') return event;
    const settlement = fieldsOf(event);
    if (settlement.vault_id == null || settlement.epoch == null) return event;
    // These are recorded allocations, not inferred transfers or leaderboard payouts.
    const allocations = decoded.filter(candidate => candidate.event_name === 'StakerAllocation')
      .flatMap(candidate => {
        const fields = fieldsOf(candidate);
        if (String(fields.vault_id) !== String(settlement.vault_id)
            || String(fields.epoch) !== String(settlement.epoch)
            || fields.staker == null || fields.amount == null) return [];
        return [{ event_index: candidate.event_index, wallet: fields.staker, dung_atomic: fields.amount }];
      });
    return { ...event, ...(allocations.length ? { position_allocations: allocations } : {}) };
  });
}
