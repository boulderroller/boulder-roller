#!/usr/bin/env node
/**
 * Boulder Rollers MCP Server
 *
 * Provides dynamic query tools for Claude Code:
 * - vault-status: Query on-chain vault state
 * - ride-trace: Trace ride processing pipeline
 * - droplet-health: Check staging server status
 * - wallet-state: Query wallet balances and stakes
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { execSync } from "child_process";
import pg from "pg";

// Configuration
const DROPLET_IP = process.env.DROPLET_IP || "localhost";

function getDbConfig(): pg.PoolConfig {
  const host = process.env.DB_HOST;
  const user = process.env.DB_USER;
  const password = process.env.DB_PASSWORD;
  const database = process.env.DB_NAME;
  const port = Number.parseInt(process.env.DB_PORT || "5432", 10);

  const missing: string[] = [];
  if (!host) missing.push("DB_HOST");
  if (!user) missing.push("DB_USER");
  if (!password) missing.push("DB_PASSWORD");
  if (!database) missing.push("DB_NAME");
  if (!Number.isFinite(port)) missing.push("DB_PORT");

  if (missing.length > 0) {
    throw new Error(`Missing required DB env vars: ${missing.join(", ")}`);
  }

  return { host, port, user, password, database };
}

const server = new Server(
  {
    name: "boulder-rollers-mcp",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Tool definitions
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "vault-status",
        description:
          "Query on-chain vault state by ID or signature. Returns staker count, KOM holder, total staked DUNG, minter rights remaining.",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Vault ID (number) or signature hash (hex string)",
            },
          },
          required: ["query"],
        },
      },
      {
        name: "ride-trace",
        description:
          "Trace a ride through the processing pipeline. Shows upload time, parse status, detected climbs, tile coverage, vault matches.",
        inputSchema: {
          type: "object",
          properties: {
            activity_id: {
              type: "string",
              description: "Activity/ride UUID",
            },
          },
          required: ["activity_id"],
        },
      },
      {
        name: "droplet-health",
        description:
          "Check DigitalOcean droplet status. Returns API health, running containers, memory usage.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "wallet-state",
        description:
          "Query wallet state. Returns CAL balance, DUNG balance, active stakes, owned vaults, BeetleCard level.",
        inputSchema: {
          type: "object",
          properties: {
            pubkey: {
              type: "string",
              description: "Solana wallet public key",
            },
          },
          required: ["pubkey"],
        },
      },
    ],
  };
});

// Tool implementations
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "vault-status":
        return await vaultStatus(args?.query as string);

      case "ride-trace":
        return await rideTrace(args?.activity_id as string);

      case "droplet-health":
        return await dropletHealth();

      case "wallet-state":
        return await walletState(args?.pubkey as string);

      default:
        return {
          content: [{ type: "text", text: `Unknown tool: ${name}` }],
          isError: true,
        };
    }
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `Error: ${error instanceof Error ? error.message : String(error)}`,
        },
      ],
      isError: true,
    };
  }
});

async function vaultStatus(query: string) {
  const pool = new pg.Pool(getDbConfig());

  try {
    // Determine if query is ID or signature
    const isId = /^\d+$/.test(query);

    const sql = isId
      ? `SELECT * FROM indexed_vaults WHERE id = $1`
      : `SELECT * FROM indexed_vaults WHERE signature_hash_hex ILIKE $1 OR signature_hex ILIKE $1`;

    const result = await pool.query(sql, [isId ? parseInt(query) : `%${query}%`]);

    if (result.rows.length === 0) {
      return {
        content: [{ type: "text", text: `No vault found matching: ${query}` }],
      };
    }

    const vault = result.rows[0];
    const output = `
=== Vault ${vault.id} ===
Name: ${vault.name}
PDA: ${vault.pda}

Metrics:
  Vert: ${vault.vert_m}m
  Distance: ${vault.distance_m}m
  Avg Grade: ${vault.avg_gradient_pct}%

Economics:
  Total Completions: ${vault.total_completions}
  Total Staked: ${vault.total_staked} DUNG

KOM:
  Holder: ${vault.kom_holder || "None"}
  Time: ${vault.kom_time_s ? `${vault.kom_time_s}s` : "N/A"}

Minter: ${vault.minter}
Created: ${vault.created_at}
Last Synced: ${vault.last_synced_at || vault.indexed_at}

Signature (first 32): ${vault.signature_hex?.substring(0, 32)}...
`;

    return { content: [{ type: "text", text: output }] };
  } finally {
    await pool.end();
  }
}

async function rideTrace(activityId: string) {
  const pool = new pg.Pool(getDbConfig());

  try {
    // Get ride info
    const rideResult = await pool.query(
      `SELECT * FROM rides WHERE id = $1`,
      [activityId]
    );

    if (rideResult.rows.length === 0) {
      return {
        content: [{ type: "text", text: `No ride found: ${activityId}` }],
      };
    }

    const ride = rideResult.rows[0];

    // Get detected climbs
    const climbsResult = await pool.query(
      `SELECT * FROM patterns_climb WHERE ride_id = $1 ORDER BY start_time`,
      [activityId]
    );

    // Get tile samples count
    const tilesResult = await pool.query(
      `SELECT COUNT(*) as count, COUNT(DISTINCT tile_id) as unique_tiles
       FROM activity_tile_samples WHERE activity_id = $1`,
      [activityId]
    );

    // Get vault matches
    const vaultResult = await pool.query(
      `SELECT v.id, v.name, pc.signature_hex
       FROM patterns_climb pc
       JOIN indexed_vaults v ON pc.signature_hex = v.signature_hex
       WHERE pc.ride_id = $1`,
      [activityId]
    );

    const tiles = tilesResult.rows[0];
    const output = `
=== Ride Trace: ${activityId} ===

Upload:
  Created: ${ride.created_at}
  Status: ${ride.processing_status || "unknown"}
  Source: ${ride.source || "unknown"}

Ride Data:
  Duration: ${ride.elapsed_time_s}s
  Distance: ${ride.distance_m}m
  TSS: ${ride.tss || "N/A"}

Climbs Detected: ${climbsResult.rows.length}
${climbsResult.rows
  .map(
    (c: any, i: number) =>
      `  ${i + 1}. ${c.road_name || "Unnamed"} - ${c.vert_gain_m}m @ ${c.avg_gradient_pct}%`
  )
  .join("\n")}

Tiles:
  Total Samples: ${tiles.count}
  Unique Tiles: ${tiles.unique_tiles}

Vault Matches: ${vaultResult.rows.length}
${vaultResult.rows.map((v: any) => `  - Vault ${v.id}: ${v.name}`).join("\n") || "  None"}
`;

    return { content: [{ type: "text", text: output }] };
  } finally {
    await pool.end();
  }
}

async function dropletHealth() {
  const results: string[] = ["=== Droplet Health ===", `IP: ${DROPLET_IP}`, ""];

  // Check SSH connectivity
  try {
    execSync(`nc -z -w2 ${DROPLET_IP} 22`, { encoding: "utf-8" });
    results.push("SSH: Reachable");
  } catch {
    results.push("SSH: UNREACHABLE");
    return { content: [{ type: "text", text: results.join("\n") }] };
  }

  // Check API health
  try {
    const health = execSync(
      `curl -s --max-time 5 http://${DROPLET_IP}:8000/health`,
      { encoding: "utf-8" }
    );
    results.push(`API: UP`);
    results.push(`Health: ${health.trim()}`);
  } catch {
    results.push("API: DOWN");
  }

  // Get container status
  try {
    const containers = execSync(
      `ssh -o ConnectTimeout=3 -o BatchMode=yes root@${DROPLET_IP} "docker ps --format '{{.Names}}: {{.Status}}'"`,
      { encoding: "utf-8" }
    );
    results.push("");
    results.push("Containers:");
    results.push(containers.trim());
  } catch (e) {
    results.push("Containers: Unable to query");
  }

  // Get memory usage
  try {
    const memory = execSync(
      `ssh -o ConnectTimeout=3 -o BatchMode=yes root@${DROPLET_IP} "free -h | grep Mem"`,
      { encoding: "utf-8" }
    );
    results.push("");
    results.push("Memory:");
    results.push(memory.trim());
  } catch {
    // Skip if unable to get
  }

  return { content: [{ type: "text", text: results.join("\n") }] };
}

async function walletState(pubkey: string) {
  const pool = new pg.Pool(getDbConfig());

  try {
    // Get user info
    const userResult = await pool.query(
      `SELECT * FROM users WHERE wallet = $1`,
      [pubkey]
    );

    if (userResult.rows.length === 0) {
      return {
        content: [{ type: "text", text: `No user found for wallet: ${pubkey}` }],
      };
    }

    const user = userResult.rows[0];

    // Get CAL balance
    const calResult = await pool.query(
      `SELECT cal_balance FROM user_balances WHERE user_id = $1`,
      [user.id]
    );

    // Get owned vaults
    const vaultsResult = await pool.query(
      `SELECT id, name FROM indexed_vaults WHERE minter = $1`,
      [pubkey]
    );

    // Get active stakes
    const stakesResult = await pool.query(
      `SELECT vault_id, amount_dung FROM vault_stakes WHERE wallet = $1 AND active = true`,
      [pubkey]
    );

    // Get BeetleCard info
    const cardResult = await pool.query(
      `SELECT level, xp FROM beetle_cards WHERE user_id = $1`,
      [user.id]
    );

    // Get tile count
    const tileResult = await pool.query(
      `SELECT COUNT(*) as count FROM wallet_tile_history WHERE wallet = $1`,
      [pubkey]
    );

    const cal = calResult.rows[0]?.cal_balance || 0;
    const card = cardResult.rows[0];
    const tiles = tileResult.rows[0]?.count || 0;

    const output = `
=== Wallet State ===
Pubkey: ${pubkey}
User ID: ${user.id}

Balances:
  CAL: ${cal}
  DUNG: (query on-chain)

BeetleCard:
  Level: ${card?.level || 1}
  XP: ${card?.xp || 0}

Territory:
  Unique Tiles: ${tiles}

Owned Vaults: ${vaultsResult.rows.length}
${vaultsResult.rows.map((v: any) => `  - ${v.id}: ${v.name}`).join("\n") || "  None"}

Active Stakes: ${stakesResult.rows.length}
${stakesResult.rows.map((s: any) => `  - Vault ${s.vault_id}: ${s.amount_dung} DUNG`).join("\n") || "  None"}

Joined: ${user.created_at}
`;

    return { content: [{ type: "text", text: output }] };
  } finally {
    await pool.end();
  }
}

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Boulder Rollers MCP server running on stdio");
}

main().catch(console.error);
