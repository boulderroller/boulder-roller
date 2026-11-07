import { publicHandle } from "./climb-room";
import { attestedNumber, attestedAtomic } from "./observatory";
type Row = Record<string, any>;
type Query = (sql: string, params?: any[]) => Promise<{ rows: Row[] }>;
const key = (v: unknown) =>
  typeof v === "string" && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(v)
    ? v
    : undefined;
const normalized = (r: Row) =>
  Object.fromEntries(
    Object.entries(r).map(([k, v]) => [
      k.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase(),
      v,
    ]),
  );
const at = (v: unknown) => {
  if (v == null || v === "") return undefined;
  const n = /^\d+$/.test(String(v)) ? Number(v) * 1000 : Date.parse(String(v));
  return Number.isFinite(new Date(n).getTime()) && n > 0
    ? new Date(n).toISOString()
    : undefined;
};
const kinds: Record<string, string> = {
  RideAttestationRecorded: "attestation",
  ClimbCompleted: "attestation",
  ClimbCompletedV2: "attestation",
  ReleasedClimbCompleted: "attestation",
  EpochRewardsDistributed: "settlement",
  CalStaked: "deposit",
  CalUnstaked: "withdrawal",
  UnstakeWithFee: "withdrawal",
  RewardsHarvested: "collection",
  ClimbRegistered: "registration",
  LocalLegendElected: "legend",
};
const roles: Record<string, string> = {
  rider: "Rider",
  user: "Rider",
  staker: "Wallet",
  owner: "Wallet",
  wallet: "Wallet",
  climb: "Climb",
  vault: "Vault",
  ride_attestation: "Ride proof",
  ride_proof: "Ride proof",
  program: "Program",
  system_program: "Program",
  token_program: "Program",
};
/** Only fields in this transaction may supply receipt facts. No current account enrichment. */
export async function buildTransactionRoom(
  query: Query,
  transactions: Row[],
  events: Row[],
  canon: Row[],
) {
  const first = transactions[0] ?? {};
  const accounts: Row[] = [];
  for (const t of transactions)
    for (const [name, value] of Object.entries(t.instruction_accounts ?? {})) {
      const address = key(
        typeof value === "string" ? value : (value as Row)?.pubkey,
      );
      if (!address) continue;
      const roleName = name
        .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
        .toLowerCase();
      const role = roles[roleName];
      if (!accounts.some((a) => a.pubkey === address && a.role === role))
        accounts.push({ pubkey: address, role });
    }
  const applicable = events.filter((e) => kinds[e.event_name]);
  const uniqueKinds = [...new Set(applicable.map((e) => kinds[e.event_name]))];
  const room: Row = { accounts, fields: {} };
  const logs = transactions.flatMap((t) =>
    Array.isArray(t.log_messages)
      ? t.log_messages.filter((l: unknown) => typeof l === "string")
      : [],
  );
  if (logs.length) room.logs = logs;
  const program = key(first.program_id);
  if (program) room.program = program;
  if (uniqueKinds.length !== 1) return room;
  room.kind = uniqueKinds[0];
  // Prefer a sole completion to its parent ride event; multiple climb results stay unassociated.
  const completed = applicable.filter((e) =>
    e.event_name.includes("ClimbCompleted"),
  );
  const selected =
    completed.length === 1
      ? completed[0]
      : applicable.length === 1
        ? applicable[0]
        : undefined;
  if (!selected) return room;
  const f = normalized(selected.fields ?? {}),
    d = room.fields;
  const matches = canon.filter(
    (c) =>
      (f.vault_id != null &&
        c.vault_id != null &&
        String(c.vault_id) === String(f.vault_id)) ||
      (key(f.climb) && c.climb_pda === f.climb),
  );
  if (matches.length === 1)
    room.climb = {
      id: String(matches[0].id),
      name: matches[0].display_name ?? matches[0].route_name,
    };
  const wallet = key(
    f.rider ?? f.staker ?? f.user ?? f.winner ?? f.registered_by,
  );
  if (wallet) {
    room.rider = { wallet };
    const profiles = await query(
      `/* transaction-room:profile */ SELECT username,is_public,moderation_state FROM users WHERE wallet=$1`,
      [wallet],
    );
    if (profiles.rows.length === 1)
      room.rider.handle = publicHandle(profiles.rows[0]);
  }
  // A failed instruction did not perform the event's claimed outcome.
  if (first.status !== "success") return room;
  d.week = attestedNumber(
    f.week ?? f.epoch ?? f.economic_epoch ?? f.term_start_epoch,
  );
  if (room.kind === "attestation") {
    d.time_s = attestedNumber(f.time_s);
    d.completed = at(f.completed_at);
    d.ride_hash =
      typeof f.ride_hash === "string" && /^[a-f0-9]{64}$/i.test(f.ride_hash)
        ? f.ride_hash
        : undefined;
    // is_new_kom is a hill record, not the rider's new best; never relabel it.
    if (f.is_new_best === true)
      d.previous_best_s = attestedNumber(f.previous_best_s);
  }
  if (room.kind === "settlement") {
    d.dung = attestedAtomic(f.total_distributed);
    d.week_starts_at = at(f.week_starts_at);
    d.week_ends_at = at(f.week_ends_at);
    d.positions_paid = attestedNumber(f.positions_paid);
    d.completions = attestedNumber(f.completions_counted);
    // StakerAllocation only accrues pending rewards. Paid needs explicit transfer receipt rows.
    room.paid = [];
  }
  if (room.kind === "deposit" || room.kind === "withdrawal") {
    d.cal = attestedAtomic(room.kind === "deposit" ? f.amount : f.cal_returned);
    d.rank = attestedNumber(f.rank_after);
    d.since = at(f.since);
  }
  if (room.kind === "collection") d.dung = attestedAtomic(f.dung_received);
  if (room.kind === "registration") {
    d.canon_version = attestedNumber(f.canon_version);
    d.point_count = attestedNumber(f.point_count);
    d.climb_account = key(f.climb);
    d.vault_account = key(f.vault);
  }
  if (room.kind === "legend")
    d.completions = attestedNumber(f.winner_completions);

  return room;
}
