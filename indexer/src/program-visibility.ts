import { programVersionWindow, STAGE1_UNPREFIXED_INSTRUCTION_NAMES } from './program-version-window';

export function visibleEvents<T extends { event_name?: unknown }>(rows: T[]): T[] {
  return rows.filter(row => programVersionWindow.stage1Available || !String(row.event_name).startsWith('Stage1'));
}

/** SQL identifiers here are fixed callers, never request inputs. */
export function legacyTransactionPredicate(alias: string): string {
  const names = STAGE1_UNPREFIXED_INSTRUCTION_NAMES.map(name => `'${name}'`).join(',');
  return `NOT EXISTS (
    SELECT 1 FROM indexed_transactions hidden
    WHERE hidden.signature = ${alias}.signature
      AND (hidden.instruction_name LIKE '%Stage1%' OR hidden.instruction_name IN (${names}))
  ) AND NOT EXISTS (
    SELECT 1 FROM indexed_events hidden_event
    WHERE hidden_event.tx_signature = ${alias}.signature AND hidden_event.event_name LIKE 'Stage1%'
  )`;
}

export function eventVisibilitySql(): string {
  return programVersionWindow.stage1Available ? '' : " AND event_name NOT LIKE 'Stage1%'";
}

export const PRIVATE_STAGE1_INSTRUCTIONS = new Set(['claimStage1','claimStage1Batch','claimStage1Dung','claimStage1DungBatch']);
export function privatePayPredicate(alias: string): string {
  return `NOT EXISTS (SELECT 1 FROM indexed_transactions private_pay WHERE private_pay.signature=${alias}.signature
    AND private_pay.instruction_name IN ('claimStage1','claimStage1Batch','claimStage1Dung','claimStage1DungBatch'))`;
}
