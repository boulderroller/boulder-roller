import { Pool, PoolClient, QueryResult } from 'pg';
import { config } from './config';

let pool: Pool | null = null;

/**
 * Get or create the connection pool.
 * Uses the Supabase Postgres connection string from config.
 */
export function getPool(): Pool {
  if (!pool) {
    if (!config.databaseUrl) {
      throw new Error('DATABASE_URL is not set');
    }
    pool = new Pool({
      connectionString: config.databaseUrl,
      max: 10,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 10000,
    });

    pool.on('error', (err) => {
      console.error('[DB] Unexpected pool error:', err.message);
    });
  }
  return pool;
}

/**
 * Execute a query against the pool.
 */
export async function query(text: string, params?: any[]): Promise<QueryResult> {
  const p = getPool();
  const start = Date.now();
  const result = await p.query(text, params);
  const duration = Date.now() - start;
  if (duration > 1000) {
    console.warn(`[DB] Slow query (${duration}ms): ${text.slice(0, 100)}`);
  }
  return result;
}

/**
 * Get a client from the pool for transactions.
 */
export async function getClient(): Promise<PoolClient> {
  return getPool().connect();
}

/**
 * Gracefully shut down the pool.
 */
export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
    console.log('[DB] Connection pool closed');
  }
}
