import { query } from '../db';

/** Allowlist of indexed tables the upsert helper may write to. */
const ALLOWED_TABLES = new Set([
  'indexed_vaults',
  'indexed_vault_counter',
  'indexed_vault_activations',
  'indexed_leaderboards',
  'indexed_legends',
  'indexed_stakes',
  'indexed_completions',
  'indexed_accounts',
  'indexed_beetle_cards',
  'indexed_supply',
  'indexed_program_config',
  'indexed_rider_souls',
  'indexed_ride_attestations',
  'indexed_held_ride_release_authorities',
  'indexed_cal_mint_receipts',
  'indexed_climb_completion_receipts',
]);

const ALLOWED_SYNC_STATE_FIELDS = new Set([
  'last_account_slot',
  'last_account_sync_at',
  'last_tx_signature',
  'last_tx_slot',
  'last_tx_sync_at',
  'last_snapshot_at',
  'last_snapshot_slot',
  'snapshot_account_count',
  'stream_connected',
  'stream_connected_since',
  'stream_disconnects',
]);

const SYNC_STATE_SLOT_GUARDS: Record<string, string> = {
  last_account_slot: 'last_account_slot',
  last_account_sync_at: 'last_account_slot',
  last_tx_signature: 'last_tx_slot',
  last_tx_slot: 'last_tx_slot',
  last_tx_sync_at: 'last_tx_slot',
  last_snapshot_at: 'last_snapshot_slot',
  last_snapshot_slot: 'last_snapshot_slot',
  snapshot_account_count: 'last_snapshot_slot',
};

const SYNC_STATE_SLOT_FIELDS = [
  'last_account_slot',
  'last_tx_slot',
  'last_snapshot_slot',
] as const;

let lastProjectionIndexedAtMs = 0;

function prepareProjectionRows(
  table: string,
  columns: string[],
  rows: any[][]
): any[][] {
  const slotIndex = columns.indexOf('chain_slot');
  const indexedAtIndex = columns.indexOf('indexed_at');
  if (slotIndex === -1 || indexedAtIndex === -1) {
    throw new Error(
      `[Upsert] ${table} projections must include chain_slot and indexed_at`
    );
  }

  return rows.map((row, rowIndex) => {
    if (row.length !== columns.length) {
      throw new Error(
        `[Upsert] ${table} row ${rowIndex} has ${row.length} values for ${columns.length} columns`
      );
    }

    const slot = row[slotIndex];
    if (!Number.isSafeInteger(slot) || slot < 0) {
      throw new Error(`[Upsert] ${table} row ${rowIndex} has invalid chain_slot`);
    }

    const indexedAt = new Date(row[indexedAtIndex]);
    if (Number.isNaN(indexedAt.getTime())) {
      throw new Error(`[Upsert] ${table} row ${rowIndex} has invalid indexed_at`);
    }

    // Program notifications can share a slot and a millisecond. Preserve their
    // observed order so reversed query completion cannot regress equal-slot data.
    const indexedAtMs = Math.max(indexedAt.getTime(), lastProjectionIndexedAtMs + 1);
    lastProjectionIndexedAtMs = indexedAtMs;

    const prepared = [...row];
    prepared[indexedAtIndex] = new Date(indexedAtMs);
    return prepared;
  });
}

function projectionConflictGuard(table: string): string {
  return `WHERE (
        ${table}.chain_slot IS NULL
        OR EXCLUDED.chain_slot > ${table}.chain_slot
        OR (
          EXCLUDED.chain_slot = ${table}.chain_slot
          AND (
            ${table}.indexed_at IS NULL
            OR EXCLUDED.indexed_at >= ${table}.indexed_at
          )
        )
      )`;
}

/**
 * Generic upsert helper.
 * Builds an INSERT ... ON CONFLICT DO UPDATE query.
 *
 * @param table - Target table name (must be in ALLOWED_TABLES)
 * @param columns - Column names
 * @param values - Column values (same order as columns)
 * @param conflictColumns - Columns forming the unique constraint / PK
 * @param updateColumns - Columns to update on conflict (defaults to all non-conflict columns)
 */
export async function upsert(
  table: string,
  columns: string[],
  values: any[],
  conflictColumns: string[],
  updateColumns?: string[]
): Promise<void> {
  if (!ALLOWED_TABLES.has(table)) {
    throw new Error(`[Upsert] Table "${table}" is not in the allowlist`);
  }

  const [preparedValues] = prepareProjectionRows(table, columns, [values]);
  const toUpdate = updateColumns || columns.filter(c => !conflictColumns.includes(c));
  if (!toUpdate.includes('chain_slot') || !toUpdate.includes('indexed_at')) {
    throw new Error(
      `[Upsert] ${table} conflict updates must advance chain_slot and indexed_at`
    );
  }

  const placeholders = preparedValues.map((_, i) => `$${i + 1}`).join(', ');
  const conflictClause = conflictColumns.join(', ');
  const updateClause = toUpdate
    .map(col => `${col} = EXCLUDED.${col}`)
    .join(', ');

  const sql = `
    INSERT INTO ${table} (${columns.join(', ')})
    VALUES (${placeholders})
    ON CONFLICT (${conflictClause})
    DO UPDATE SET ${updateClause}
    ${projectionConflictGuard(table)}
  `;

  await query(sql, preparedValues);
}

/**
 * Batch upsert: insert multiple rows with a multi-row VALUES clause,
 * chunked into groups of 500 to stay within Postgres parameter limits.
 */
export async function batchUpsert(
  table: string,
  columns: string[],
  rows: any[][],
  conflictColumns: string[],
  updateColumns?: string[]
): Promise<number> {
  if (rows.length === 0) return 0;

  if (!ALLOWED_TABLES.has(table)) {
    throw new Error(`[BatchUpsert] Table "${table}" is not in the allowlist`);
  }

  const preparedRows = prepareProjectionRows(table, columns, rows);
  const toUpdate = updateColumns || columns.filter(c => !conflictColumns.includes(c));
  if (!toUpdate.includes('chain_slot') || !toUpdate.includes('indexed_at')) {
    throw new Error(
      `[BatchUpsert] ${table} conflict updates must advance chain_slot and indexed_at`
    );
  }
  const colCount = columns.length;
  const CHUNK_SIZE = 500;
  let total = 0;

  for (let i = 0; i < preparedRows.length; i += CHUNK_SIZE) {
    const chunk = preparedRows.slice(i, i + CHUNK_SIZE);
    const values: any[] = [];
    const rowPlaceholders: string[] = [];

    for (let r = 0; r < chunk.length; r++) {
      const offset = r * colCount;
      const ph = columns.map((_, c) => `$${offset + c + 1}`).join(', ');
      rowPlaceholders.push(`(${ph})`);
      values.push(...chunk[r]);
    }

    const conflictClause = conflictColumns.join(', ');
    const updateClause = toUpdate.map(col => `${col} = EXCLUDED.${col}`).join(', ');

    const sql = `
      INSERT INTO ${table} (${columns.join(', ')})
      VALUES ${rowPlaceholders.join(', ')}
      ON CONFLICT (${conflictClause})
      DO UPDATE SET ${updateClause}
      ${projectionConflictGuard(table)}
    `;

    await query(sql, values);
    total += chunk.length;
  }

  return total;
}

/**
 * Update the indexer sync state singleton.
 */
export async function updateSyncState(updates: Record<string, any>): Promise<void> {
  const keys = Object.keys(updates);
  if (keys.length === 0) return;

  for (const key of keys) {
    if (!ALLOWED_SYNC_STATE_FIELDS.has(key)) {
      throw new Error(`[SyncState] Field "${key}" is not in the allowlist`);
    }
  }

  for (const slotField of SYNC_STATE_SLOT_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(updates, slotField)) continue;
    const slot = updates[slotField];
    if (!Number.isSafeInteger(slot) || slot < 0) {
      throw new Error(`[SyncState] invalid ${slotField}`);
    }
  }

  if (
    Object.prototype.hasOwnProperty.call(updates, 'last_tx_signature')
    && !Object.prototype.hasOwnProperty.call(updates, 'last_tx_slot')
  ) {
    throw new Error('[SyncState] last_tx_signature requires last_tx_slot');
  }

  const parameterByKey = new Map(keys.map((key, index) => [key, index + 1]));
  const setClause = keys.map((key, index) => {
    const guardSlot = SYNC_STATE_SLOT_GUARDS[key];
    const guardParameter = guardSlot ? parameterByKey.get(guardSlot) : undefined;
    if (!guardParameter) {
      return `${key} = $${index + 1}`;
    }
    return `${key} = CASE
      WHEN $${guardParameter} >= COALESCE(${guardSlot}, 0) THEN $${index + 1}
      ELSE ${key}
    END`;
  }).join(', ');
  const values = keys.map(k => updates[k]);

  await query(
    `UPDATE indexer_sync_state SET ${setClause}, updated_at = now() WHERE id = 1`,
    values
  );
}

/**
 * Ensure the sync state singleton row exists.
 */
export async function ensureSyncState(): Promise<void> {
  await query(`
    INSERT INTO indexer_sync_state (id)
    VALUES (1)
    ON CONFLICT (id) DO NOTHING
  `);
}

/**
 * Read current sync state.
 */
export async function getSyncState(): Promise<Record<string, any> | null> {
  const result = await query('SELECT * FROM indexer_sync_state WHERE id = 1');
  return result.rows[0] || null;
}
