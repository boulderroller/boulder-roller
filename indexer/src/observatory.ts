/** Additive Week-page projection. Never infer a chain value from a canon row. */
export function attestedNumber(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}
export function attestedAtomic(value: unknown): string | undefined {
  if (value == null || !/^\d+$/.test(String(value))) return undefined;
  return BigInt(String(value)) > 0n ? String(value) : undefined;
}
export function projectGround(row: Record<string, any>, indexed: boolean) {
  return {
    id: String(row.id),
    name: row.display_name ?? row.route_name,
    geometry: row.geometry,
    length_m: attestedNumber(row.length_m),
    elev_gain_m: attestedNumber(row.vert_m),
    avg_gradient_pct: attestedNumber(row.avg_gradient_pct),
    registered: indexed ? Boolean(row.climb_pda) : undefined,
    deposited:
      indexed && row.vault_id != null
        ? attestedAtomic(row.total_cal_staked)
        : undefined,
    completions:
      indexed && row.vault_id != null
        ? attestedNumber(row.total_completions)
        : undefined,
  };
}
export function projectIndexed(freshness: Record<string, any>) {
  const slots = [freshness.account_slot, freshness.tx_slot].map(attestedNumber);
  const dates = [freshness.last_account_sync_at, freshness.last_tx_sync_at].map(
    (v) => (v == null ? NaN : Date.parse(String(v))),
  );
  if (
    slots.some((v) => v === undefined) ||
    dates.some((v) => !Number.isFinite(v))
  )
    return undefined;
  const at = Math.min(...dates);
  return {
    slot: Math.min(...(slots as number[])),
    at: new Date(at).toISOString(),
    age_seconds: Math.max(0, Math.floor((Date.now() - at) / 1000)),
  };
}
/** Same immutable anchors and transition week as backend/app/settlement_clock.py. */
function settlementClock(config: Record<string, any> | undefined) {
  if (
    !config ||
    Number(config.settlement_clock_version) !== 2 ||
    !attestedNumber(config.chain_slot)
  ) return;
  const cutover = Number(config.settlement_clock_v2_starts_at),
    anchor = 1704110400,
    legacy = 1704020400,
    duration = 604800;
  if (
    !Number.isSafeInteger(cutover) ||
    cutover < anchor ||
    (cutover - anchor) % duration !== 0
  ) return;
  return {
    cutover, anchor, legacy, duration,
    transition: cutover > anchor ? (cutover - anchor) / duration : undefined,
  };
}
export function projectSettlementWeekStart(
  config: Record<string, any>, epoch: number,
): number | undefined {
  const clock = settlementClock(config);
  if (!clock || !Number.isSafeInteger(epoch) || epoch < 0) return;
  const { transition, legacy, anchor, duration } = clock;
  return (transition != null && epoch <= transition ? legacy : anchor) + epoch * duration;
}
export function projectWeekClock(
  config: Record<string, any> | undefined,
  asOf: string | undefined,
) {
  const clock = settlementClock(config);
  if (!clock || !asOf) return {};
  const { cutover, anchor, legacy, duration, transition } = clock;
  const timestamp = Date.parse(asOf) / 1000;
  const epoch = Math.max(0, Math.floor(
    (timestamp - (timestamp < cutover ? legacy : anchor)) / duration,
  ));
  const starts_at = projectSettlementWeekStart(config!, epoch)!;
  const ends_at = epoch === transition
    ? anchor + (epoch + 1) * duration
    : starts_at + duration;
  return { epoch, starts_at, ends_at, finalizes_at: ends_at + 86400 };
}
export function projectDisplayEvent(
  event: Record<string, any>,
  climbs: Record<string, any>[],
) {
  const f = event.fields ?? {};
  const get = (...keys: string[]) =>
    keys.map((k) => f[k]).find((v) => v != null);
  const climb =
    event.climb_id && event.climb_name
      ? {
          id: event.climb_id,
          name: event.climb_name,
          length_m: event.climb_length_m,
        }
      : climbs.find((c) => c.id === event.climb_id);
  let kind: string | undefined,
    value: { amount: string | number; unit: string } | undefined;
  const metric = (amount: unknown, unit: string, atomic = false) => {
    const n = atomic ? attestedAtomic(amount) : attestedNumber(amount);
    return n == null ? undefined : { amount: n, unit };
  };
  switch (event.event_name) {
    case "EpochRewardsDistributed":
      kind = "settlement";
      value = metric(
        get("total_distributed", "totalDistributed"),
        "DUNG",
        true,
      );
      break;
    case "RideAttestationRecorded":
      kind = "attestation";
      break;
    case "ClimbCompleted":
    case "ClimbCompletedV2":
    case "ReleasedClimbCompleted":
      kind = "attestation";
      value = metric(get("time_s", "timeS", "time"), "seconds");
      break;
    case "CalStaked":
      kind = "deposit";
      value = metric(get("amount"), "CAL", true);
      break;
    case "LocalLegendElected":
      kind = "legend";
      value = metric(
        get(
          "winner_completions",
          "winnerCompletions",
          "completions",
          "completions_at_election",
          "completionsAtElection",
        ),
        "rides",
      );
      break;
    case "ClimbRegistered":
      kind = "registration";
      value = metric(climb?.length_m, "meters");
      break;
  }
  const actor = get("rider", "user", "staker", "holder", "winner");
  return {
    ...event,
    kind,
    object: climb
      ? { id: climb.id, name: climb.name, type: "climb" }
      : typeof actor === "string"
        ? { id: actor, name: actor, type: "rider" }
        : undefined,
    actor: typeof actor === "string" ? actor : undefined,
    value,
    signature: event.tx_signature,
    epoch:
      kind === "settlement"
        ? attestedNumber(get("epoch", "settlement_week", "settlementWeek"))
        : undefined,
  };
}
