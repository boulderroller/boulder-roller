import {
  attestedAtomic,
  attestedNumber,
  projectIndexed,
  projectWeekClock,
} from "./observatory";
type Row = Record<string, any>;
type Query = (sql: string, params?: any[]) => Promise<{ rows: Row[] }>;
const key = (value: unknown): string | undefined =>
  typeof value === "string" && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(value)
    ? value
    : undefined;
const signature = (value: unknown): string | undefined =>
  typeof value === "string" && /^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(value)
    ? value
    : undefined;
const positive = attestedNumber;
const date = (value: unknown): string | undefined => {
  if (value == null || value === "") return undefined;
  const time =
    typeof value === "number" || /^\d+$/.test(String(value))
      ? Number(value) * 1000
      : Date.parse(String(value));
  return Number.isFinite(time) && time > 0
    ? new Date(time).toISOString()
    : undefined;
};
export function publicHandle(row: Row | undefined) {
  return row?.is_public === true &&
    row?.moderation_state === "visible" &&
    typeof row.username === "string" &&
    /^[a-zA-Z0-9_]{1,30}$/.test(row.username)
    ? `@${row.username}`
    : undefined;
}
/** The portal owns route privacy. Never reconstruct it from the chain board. */
export async function readPublicBoard(
  climbId: string,
  vaultId: number,
  fetcher: typeof fetch = fetch,
): Promise<Row[]> {
  try {
    const response = await fetcher(
      `https://api.boulderroller.xyz/climbs/${encodeURIComponent(climbId)}/leaderboard`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return [];
    const body = (await response.json()) as Row;
    if (
      body.climb_id !== climbId ||
      Number(body.vault_id) !== vaultId ||
      !Array.isArray(body.entries)
    )
      return [];
    return body.entries.filter(
      (r: Row) =>
        key(r.wallet) && positive(r.position) && positive(r.best_time_seconds),
    );
  } catch {
    return [];
  }
}

export async function buildClimbRoom(
  query: Query,
  climb: Row,
  vault: Row | null,
  freshness: Row,
  publicBoard = readPublicBoard,
) {
  const indexed = projectIndexed(freshness);
  const identity = await query(
    `/* climb-room:identity */ SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry,
      registered.pda, registered.canon_version, registered.registered_at, registered.chain_slot
    FROM public.canon_climbs canon LEFT JOIN public.indexed_climbs registered
      ON registered.canon_climb_id = canon.id AND registered.quarantined IS FALSE
      AND registered.successor_climb_pda IS NULL
    WHERE canon.id = $1::uuid`,
    [climb.id],
  );
  const row = identity.rows[0] ?? {};
  const registration: Row = {};
  const room: Row = {
    geometry: row.geometry,
    indexed,
    registration,
    positions: [],
    completions: [],
    settlements: [],
    room_leaderboard: [],
  };
  if (!indexed) return room;
  let currentWeek: number | undefined;
  if (key(row.pda) && positive(row.chain_slot)) {
    registration.climb_account = row.pda;
    registration.canon_version = positive(row.canon_version);
    // This is the committed canon's profile, not a resampled display line.
    registration.point_count = positive(climb.canonical_profile?.length);
    const [event, clock] = await Promise.all([
      query(
        `/* climb-room:registration */ SELECT tx_signature, fields, block_time FROM indexed_events
        WHERE event_name = 'ClimbRegistered' AND fields->>'climb' = $1
          AND slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
        ORDER BY slot ASC, event_index ASC LIMIT 1`,
        [row.pda],
      ),
      query(
        `/* climb-room:clock */ SELECT settlement_clock_version, settlement_clock_v2_starts_at, chain_slot FROM indexed_program_config WHERE id = 1`,
      ),
    ]);
    currentWeek = projectWeekClock(clock.rows[0], indexed.at).epoch;
    const registered = event.rows[0];
    registration.signature = signature(registered?.tx_signature);
    const at = date(
      registered?.fields?.timestamp ??
        registered?.block_time ??
        row.registered_at,
    );
    if (at)
      registration.week = positive(projectWeekClock(clock.rows[0], at).epoch);
  }
  if (!vault) return room;
  registration.vault_account = key(vault.pda);
  const [stakes, events, distributions, board] = await Promise.all([
    query(
      `/* climb-room:positions */ SELECT user_pubkey, cal_staked, staked_at, chain_slot FROM indexed_stakes
      WHERE vault_id = $1 AND cal_staked > 0 AND lp_tokens > 0
        AND chain_slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
      ORDER BY cal_staked DESC, user_pubkey ASC`,
      [vault.id],
    ),
    query(
      `/* climb-room:completions */ SELECT e.tx_signature, e.event_index, e.fields, e.block_time
      FROM indexed_events e JOIN indexed_ride_attestations a
        ON a.pda = COALESCE(e.fields->>'ride_attestation', e.fields->>'rideAttestation')
        AND a.rider_pubkey = e.fields->>'rider' AND a.finalized IS TRUE
      WHERE e.vault_id = $1 AND e.event_name IN ('ClimbCompleted', 'ClimbCompletedV2', 'ReleasedClimbCompleted')
        AND e.slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
        AND a.settled_slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
      ORDER BY e.block_time DESC NULLS LAST, e.slot DESC, e.event_index DESC`,
      [vault.id],
    ),
    query(
      `/* climb-room:settlements */ SELECT epoch, block_time, total_distributed, tx_signature, event_index
      FROM indexed_epoch_distributions WHERE vault_id = $1
        AND slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
      ORDER BY epoch DESC, slot DESC, event_index DESC`,
      [vault.id],
    ),
    publicBoard(String(climb.id), Number(vault.id)),
  ]);
  const wallets = [
    ...new Set(
      [
        ...stakes.rows.map((r) => r.user_pubkey),
        ...events.rows.map((r) => r.fields?.rider),
        ...board.map((r) => r.wallet),
        vault.legend?.holder,
      ].filter(key),
    ),
  ];
  const profiles = wallets.length
    ? await query(
        `/* climb-room:handles */ SELECT wallet, username, is_public, moderation_state
    FROM users WHERE wallet = ANY($1::text[]) AND is_public IS TRUE AND moderation_state = 'visible'`,
        [wallets],
      )
    : { rows: [] };
  const handle = (wallet: string) => {
    const matches = profiles.rows.filter((r) => r.wallet === wallet);
    return matches.length === 1 ? publicHandle(matches[0]) : undefined;
  };
  room.room_leaderboard = board.map((r) => {
    const matches = (vault.leaderboard ?? []).filter(
      (entry: Row) =>
        entry.user === r.wallet &&
        Number(entry.time_s) === Number(r.best_time_seconds) &&
        Number(entry.position) === Number(r.position) &&
        Number(entry.rank) === Number(r.competition_rank ?? r.position),
    );
    return {
      wallet: r.wallet,
      handle: handle(r.wallet),
      rank: Number(r.competition_rank ?? r.position),
      position: Number(r.position),
      time_s: Number(r.best_time_seconds),
      power_w: positive(r.avg_power_w),
      date:
        date(r.achieved_at) ??
        (matches.length === 1 ? date(matches[0].recorded_at) : undefined),
    };
  });
  room.positions = stakes.rows
    .filter((r) => key(r.user_pubkey) && attestedAtomic(r.cal_staked))
    .map((r) => {
      const rank = room.room_leaderboard.find(
        (b: Row) => b.wallet === r.user_pubkey,
      )?.rank;
      return {
        wallet: r.user_pubkey,
        handle: handle(r.user_pubkey),
        cal: attestedAtomic(r.cal_staked),
        since: date(r.staked_at),
        rank,
      };
    });
  room.position_count = positive(room.positions.length);
  room.deposited = attestedAtomic(vault.total_cal_staked);
  // carry_record_royalty is unallocated carry, not an indexed Leaderboard pool.
  // No authoritative pool projection is currently available; leave that slot absent.
  room.completions = events.rows
    .filter((r) => key(r.fields?.rider) && signature(r.tx_signature))
    .map((r) => ({
      wallet: r.fields.rider,
      handle: handle(r.fields.rider),
      signature: r.tx_signature,
      event_index: r.event_index,
      time_s: positive(r.fields.time_s ?? r.fields.timeS),
      date: date(r.fields.completed_at ?? r.fields.completedAt ?? r.block_time),
    }));
  room.completion_count = positive(room.completions.length);
  room.settlements = distributions.rows
    .filter(
      (r) =>
        signature(r.tx_signature) &&
        positive(r.epoch) &&
        attestedAtomic(r.total_distributed),
    )
    .map((r) => ({
      week: Number(r.epoch),
      date: date(r.block_time),
      dung: String(r.total_distributed),
      signature: r.tx_signature,
      event_index: r.event_index,
    }));
  room.settlement_count = positive(room.settlements.length);
  const legend = vault.legend;
  if (
    legend &&
    key(legend.holder) &&
    legend.is_active === true &&
    currentWeek != null &&
    positive(legend.term_end_epoch) &&
    Number(legend.term_end_epoch) > currentWeek &&
    positive(legend.completions_at_election)
  )
    room.room_legend = {
      wallet: legend.holder,
      handle: handle(legend.holder),
      completions: Number(legend.completions_at_election),
    };
  return room;
}
