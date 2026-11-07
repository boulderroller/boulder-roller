import { buildClimbRoom, publicHandle } from "./climb-room";
import {
  attestedNumber,
  projectIndexed,
  projectWeekClock,
  projectGround,
  projectRoomEvent,
} from "./observatory";
type Row = Record<string, any>;
type Query = (sql: string, params?: any[]) => Promise<{ rows: Row[] }>;
/** Wallet room composes the same canon/lineage and privacy projections as Climb. */
export async function buildAccountRoom(
  query: Query,
  wallet: string,
  freshness: Row,
  canon: Row[],
  balances: Row[],
) {
  const indexed = projectIndexed(freshness);
  const [profiles, first, clock, rides] = await Promise.all([
    query(
      `/* account-room:profile */ SELECT id, username, is_public, moderation_state, avatar_url, avatar_storage_path FROM users WHERE wallet=$1`,
      [wallet],
    ),
    query(
      `/* account-room:first */ SELECT block_time FROM indexed_events WHERE (user_pubkey=$1 OR fields->>'rider'=$1) AND block_time IS NOT NULL ORDER BY slot,event_index LIMIT 1`,
      [wallet],
    ),
    query(
      `/* account-room:clock */ SELECT settlement_clock_version, settlement_clock_v2_starts_at, chain_slot FROM indexed_program_config WHERE id=1`,
    ),
    query(
      `/* account-room:rides */ SELECT COUNT(*) AS rides FROM indexed_ride_attestations WHERE rider_pubkey=$1 AND finalized IS TRUE AND settled_slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id=1)`,
      [wallet],
    ),
  ]);
  const room: Row = {
    handle:
      profiles.rows.length === 1 ? publicHandle(profiles.rows[0]) : undefined,
    indexed,
    ground: canon.map((c) => ({
      ...projectGround(c, false),
      deposited: undefined,
    })),
    positions: [],
    completions: [],
    settlements: [],
    activity: [],
    balances,
  };
  const profile = profiles.rows[0];
  if (
    room.handle &&
    !profile.avatar_storage_path &&
    typeof profile.avatar_url === "string" &&
    profile.avatar_url.startsWith("https://")
  )
    room.avatar_url = profile.avatar_url;
  if (room.handle && profile.avatar_storage_path) {
    try {
      const response=await fetch(`https://api.boulderroller.xyz/public/previews/riders/${encodeURIComponent(profile.username)}`,{signal:AbortSignal.timeout(5000)});
      const body=response.ok?await response.json() as Row:undefined;
      const rider=body?.rider;
      if(rider?.id===String(profile.id) && rider?.isPublic===true && rider?.username===profile.username && typeof rider?.avatarUrl==='string' && rider.avatarUrl.startsWith('https://')) room.avatar_url=rider.avatarUrl;
    } catch { /* Public media unavailable: retain initials. */ }
  }
  if (!indexed) return room;
  const rawDate = first.rows[0]?.block_time;
  const date = rawDate != null && /^\d+$/.test(String(rawDate)) ? new Date(Number(rawDate)*1000).toISOString() : rawDate;
  if (date && Number.isFinite(Date.parse(String(date)))) {
    room.since_date = new Date(date).toISOString();
    room.since_week = attestedNumber(
      projectWeekClock(clock.rows[0], room.since_date).epoch,
    );
  }
  room.rides_attested = attestedNumber(rides.rows[0]?.rides);
  const relevant = await query(
    `/* account-room:related */ SELECT DISTINCT vault_id FROM indexed_stakes WHERE user_pubkey=$1 UNION SELECT DISTINCT vault_id FROM indexed_events WHERE (user_pubkey=$1 OR fields->>'rider'=$1)`,
    [wallet],
  );
  const ids = new Set(relevant.rows.map((r) => String(r.vault_id)));
  // Sequential room reads bound database/RPC pressure for wallets with many climbs.
  for (const c of canon.filter(
    (c) => c.vault_id != null && ids.has(String(c.vault_id)),
  )) {
    const details = await buildClimbRoom(
      query,
      { id: c.id, canonical_profile: c.canonical_profile },
      { id: c.vault_id, pda: c.vault_pda },
      freshness,
    );
    const ref = { id: String(c.id), name: c.display_name ?? c.route_name };
    const position = details.positions.find((p: Row) => p.wallet === wallet);
    if (position) room.positions.push({ ...position, climb: ref });
    const completions = details.completions.filter(
      (p: Row) => p.wallet === wallet,
    );
    room.completions.push(
      ...completions.map((p: Row) => ({ ...p, climb: ref })),
    );
    const ground = room.ground.find((p: Row) => p.id === ref.id);
    if (ground) {
      ground.attested = completions.length > 0;
      ground.deposited = position?.cal;
    }
  }
  const paid = await query(
    `/* account-room:paid */ SELECT tx_signature,event_index,event_name,fields,block_time,vault_id FROM indexed_events WHERE event_name='RewardsHarvested' AND (fields->>'user'=$1 OR fields->>'staker'=$1) AND slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id=1) ORDER BY slot DESC,event_index DESC`,
    [wallet],
  );
  for (const p of paid.rows) {
    const c = canon.find((c) => p.vault_id != null && c.vault_id != null && String(c.vault_id) === String(p.vault_id));
    if (
      !c ||
      !p.tx_signature ||
      !/^\d+$/.test(String(p.fields?.dung_received)) ||
      BigInt(p.fields.dung_received) <= 0n
    )
      continue;
    room.settlements.push({
      climb: { id: String(c.id), name: c.display_name ?? c.route_name },
      signature: p.tx_signature,
      event_index: p.event_index,
      week: attestedNumber(p.fields.epoch),
      date: p.block_time,
      dung: String(p.fields.dung_received),
    });
  }
  const activity = await query(
    `/* account-room:activity */ SELECT tx_signature,event_index,event_name,fields,slot,block_time,vault_id FROM indexed_events WHERE (user_pubkey=$1 OR fields->>'rider'=$1) AND slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id=1) ORDER BY slot DESC,event_index DESC LIMIT 20`,
    [wallet],
  );
  room.activity = activity.rows
    .map((e) => {
      const c = canon.find((c) => e.vault_id != null && c.vault_id != null && String(c.vault_id) === String(e.vault_id));
      return projectRoomEvent(
        { ...e, climb_id: c?.id, climb_name: c?.display_name },
        [],
      );
    })
    .filter((e) => e.kind);
  room.completions.sort(
    (a: Row, b: Row) => Date.parse(b.date ?? "") - Date.parse(a.date ?? ""),
  );
  room.completion_count = attestedNumber(room.completions.length);
  room.settlement_count = attestedNumber(room.settlements.length);
  room.seats = attestedNumber(
    room.positions.filter((p: Row) => p.rank > 1 && p.rank <= 10).length,
  );
  room.crowns = attestedNumber(
    room.positions.filter((p: Row) => p.rank === 1).length,
  );
  room.attested_climbs = attestedNumber(
    room.ground.filter((c: Row) => c.attested).length,
  );
  room.canon_count = attestedNumber(canon.length);
  return room;
}
