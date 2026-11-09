export type NumericValue = number | string | null;
export type TimestampValue = number | string | null;
export type TruthSource = 'onchain' | 'attested' | 'projected' | 'compatibility';

export type ScanFreshness = {
  contract_version?: 'scan_freshness.v1';
  source?: 'indexer';
  status?: 'live' | 'catching_up' | 'stale' | 'unknown';
  read_model?: string;
  tables?: string[];
  account_slot?: NumericValue;
  tx_slot?: NumericValue;
  max_observed_slot?: NumericValue;
  last_account_sync_at?: TimestampValue;
  last_tx_sync_at?: TimestampValue;
  stream_connected?: boolean;
  loaded_at?: TimestampValue;
};

export type CarryBuckets = {
  record_royalty: NumericValue;
  stakers: NumericValue;
  local_legend: NumericValue;
  pol: NumericValue;
  treasury: NumericValue;
  total: NumericValue;
};

export type VaultEconomy = {
  contract_version?: 'client.v1';
  truth_source?: TruthSource;
  has_vault: boolean;
  vault_id?: NumericValue;
  vault_signature?: string | null;
  total_staked?: NumericValue;
  total_completions?: NumericValue;
  current_carry?: CarryBuckets | null;
};

export type ExplorerEvent = {
  climb_id?: string;
  tx_signature: string;
  event_index: number;
  event_name: string;
  fields: Record<string, unknown>;
  slot: NumericValue;
  block_time: TimestampValue;
};

export type SupplySummary = {
  max_supply?: string | null;
  total_minted: string;
  total_burned: string;
  circulating: string | null;
  circulating_source?: 'spl_mint_supply' | 'unavailable';
  current_emission_rate_bps?: NumericValue;
  last_halving_epoch?: NumericValue;
  community_minted?: string | null;
  treasury_minted?: string | null;
  team_minted?: string | null;
  investor_minted?: string | null;
  pol_minted?: string | null;
};

export type VaultSummary = {
  contract_version?: 'client.v1';
  truth_source?: TruthSource;
  id: NumericValue;
  name: string | null;
  signature_hex?: string | null;
  minter: string;
  vert_m: NumericValue;
  distance_m: NumericValue;
  avg_gradient_pct: NumericValue;
  total_completions: NumericValue;
  total_cal_staked: string;
  staker_count: NumericValue;
  kom_holder: string | null;
  kom_time_s: NumericValue;
  created_at: TimestampValue;
  activation_status?: string | null;
  activation_is_active?: boolean | null;
  on_chain_seeding_status?: string | null;
  vault_economy?: VaultEconomy;
};

export type VaultDetail = VaultSummary & {
  signature_hash_hex?: string | null;
  pda?: string | null;
  mint_epoch?: NumericValue;
  rights_expires_epoch?: NumericValue;
  kom_set_epoch?: NumericValue;
  total_cal_burned?: string | null;
  total_dung_emitted?: string | null;
  pending_rewards?: string | null;
  pending_rewards_next_week?: string | null;
  open_settlement_week?: NumericValue;
  carry_record_royalty?: string | null;
  carry_stakers?: string | null;
  staker_remainder_policy_version?: NumericValue;
  carry_local_legend?: string | null;
  carry_pol?: string | null;
  carry_treasury?: string | null;
  cal_tribute_accumulated?: string | null;
  avatar_ipfs?: string | null;
  slogan?: string | null;
  polyline_json?: string | null;
  terrain?: string | null;
  activation_pda?: string | null;
  activation_seed_completions_written?: NumericValue;
  activation_leaderboard_seeded?: boolean | null;
  activation_created_at?: TimestampValue;
  activation_activated_at?: TimestampValue;
  activation_last_seed_at?: TimestampValue;
  activation_chain_slot?: NumericValue;
  activation_bump?: NumericValue;
  on_chain_seed_tx?: string | null;
  on_chain_leaderboard_tx?: string | null;
  on_chain_activate_tx?: string | null;
  on_chain_seeded_at?: TimestampValue;
  on_chain_activated_at?: TimestampValue;
  on_chain_seeding_error?: string | null;
};

export type LeaderboardEntry = {
  rank?: NumericValue;
  user: string;
  time_s: NumericValue;
  recorded_at: TimestampValue;
};

export type LocalLegend = {
  holder: string;
  election_period?: NumericValue;
  term_start_epoch: NumericValue;
  term_end_epoch: NumericValue;
  completions_at_election: NumericValue;
  runner_up?: string | null;
  runner_up_completions?: NumericValue;
  total_earned: string;
  is_active?: boolean;
  is_bootstrap?: boolean;
  seat_status?: 'bootstrap' | 'elected' | 'inactive';
};

export type ObservatoryResponse = {
  week?: WeekProjection; climbs?: GroundClimb[]; indexed?: {slot: number; at: string; age_seconds: number};
  program_id?: string; events_next_offset?: number | null;
  vault_count?: number;
  total_riders: number;
  total_completions: number;
  total_cal_staked: string;
  supply: SupplySummary | null;
  recent_events: DisplayEvent[];
  top_vaults: VaultSummary[];
  freshness?: ScanFreshness;
};

export type VaultResponse = {
  contract_version?: 'client.v1';
  truth_source?: TruthSource;
  vault: VaultDetail;
  leaderboard: LeaderboardEntry[];
  local_legend: LocalLegend | null;
  recent_events: ExplorerEvent[];
  distribution_history: ExplorerEvent[];
  activation_events: ExplorerEvent[];
  freshness?: ScanFreshness;
};

export type CanonicalProfileSample = {
  dist_m: number;
  elev_m: number;
};

export type ClimbSummary = {
  contract_version: 'client.v1';
  truth_source: 'projected';
  id: string;
  canon_id: string | null;
  version: number;
  revision_state: 'current' | 'retired';
  name: string | null;
  route_name: string | null;
  length_m: NumericValue;
  elev_gain_m: NumericValue;
  avg_gradient_pct: NumericValue;
  worthiness_score: NumericValue;
  canonical_profile: CanonicalProfileSample[];
  climb_pda: string | null;
  has_vault: boolean;
  vault_id: NumericValue;
  vault_pda: string | null;
  vault_signature: string | null;
  total_completions: NumericValue;
  total_cal_staked: string;
  staker_count: NumericValue;
  kom_holder: string | null;
  kom_time_s: NumericValue;
  created_at: TimestampValue;
};

export type ClimbDetail = ClimbSummary;

export type ClimbRegistration = {climb_account?:string;vault_account?:string;signature?:string;week?:number;climb_number?:number;canon_version?:number;point_count?:number};
export type ClimbRider = {wallet:string;handle?:string};
export type ClimbCompletion = ClimbRider & {signature:string;event_index?:number;date?:string;time_s?:number};
export type ClimbPosition = ClimbRider & {cal:string;rank?:number;since?:string};
export type ClimbSettlement = {signature:string;event_index?:number;date?:string;week:number;dung:string};
export type ClimbBoardEntry = ClimbRider & {rank:number;position?:number;time_s:number;power_w?:number;date?:string};
export type ClimbResponse = {
  place?:string;
  geometry?: GroundClimb['geometry'];
  registration?:ClimbRegistration;
  positions?:ClimbPosition[];completions?:ClimbCompletion[];settlements?:ClimbSettlement[];
  room_leaderboard?:ClimbBoardEntry[];room_legend?:ClimbRider & {completions:number};
  deposited?:string;leaderboard_pool?:string;completion_count?:number;position_count?:number;settlement_count?:number;
  indexed?:ObservatoryResponse['indexed'];
  contract_version: 'client.v1';
  truth_source: 'projected';
  climb: ClimbDetail;
  vault: VaultDetail | null;
  leaderboard: LeaderboardEntry[];
  local_legend: LocalLegend | null;
  recent_events: ExplorerEvent[];
  distribution_history: ExplorerEvent[];
  activation_events: ExplorerEvent[];
  freshness?: ScanFreshness;
};

export type InstructionAccountMeta = {
  pubkey: string;
  isMut?: boolean;
  isSigner?: boolean;
};

export type TransactionInstruction = {
  instruction_index: number;
  name: string;
  args: Record<string, unknown>;
  accounts: Record<string, string | InstructionAccountMeta>;
};

export type TokenFlow = {
  amount: string;
  raw_amount?: string | null;
  symbol: string;
  direction: 'positive' | 'negative' | 'neutral';
  target: string;
  source: 'event' | 'token_balance' | 'fee';
  label?: string | null;
  origin?: string | null;
  mint?: string | null;
  owner?: string | null;
  account?: string | null;
};

export type TransactionResponse = {
  receipt?: TransactionReceipt;
  signature: string;
  slot: NumericValue;
  block_time: TimestampValue;
  status: string;
  fee_lamports: string;
  compute_units: NumericValue;
  instructions: TransactionInstruction[];
  events: ExplorerEvent[];
  token_flows?: TokenFlow[];
  freshness?: ScanFreshness;
};

export type AccountUserState = {
  owner_pubkey?: string;
  legacy_cal_snapshot?: NumericValue;
  legacy_cal_earned_today?: NumericValue;
  legacy_last_cal_mint?: TimestampValue;
  total_rides: NumericValue;
  total_tss: NumericValue;
  bio_score?: NumericValue;
};

export type AccountProfile = {
  username: string;
  display_name?: string | null;
  wallet: string;
};

export type RiderSoulState = {
  rider_pubkey: string;
  created_at?: TimestampValue;
  total_rides: NumericValue;
  total_tss: NumericValue;
  total_distance_m?: NumericValue;
  total_vert_m?: NumericValue;
  total_cal_earned?: string;
  archetype?: string | null;
  bio_score?: NumericValue;
  climb_card?: NumericValue;
  steady_card?: NumericValue;
  explorer_card?: NumericValue;
};

export type BeetleCard = {
  card_type: string;
  scope: string;
  scope_id_hex?: string | null;
  score: NumericValue;
  level: NumericValue;
  rides_counted: NumericValue;
  total_dung_burned: string;
  created_at?: TimestampValue;
};

export type ActiveStake = {
  vault_id: NumericValue;
  cal_staked: string;
  lp_tokens: string;
  rewards_earned: string;
  staked_at?: TimestampValue;
};

export type CompletionSummary = {
  vault_id: NumericValue;
  completions: NumericValue;
  best_time_s: NumericValue;
  last_completed_at?: TimestampValue;
  total_cal_tributed: string;
};

export type RideAttestationSummary = {
  rider_pubkey: string;
  ride_hash_hex: string;
  attestation_commitment_hex: string;
  parser_version: NumericValue;
  source_kind: NumericValue;
  source_kind_label: string;
  completed_at: TimestampValue;
  started_at?: TimestampValue;
  total_tss?: NumericValue;
  total_distance_m?: NumericValue;
  total_vert_m?: NumericValue;
  cal_earned?: NumericValue;
  climbs_crossed?: NumericValue;
  attester?: string | null;
  settled_at?: TimestampValue;
  settled_slot?: NumericValue;
  economic_epoch?: NumericValue;
  finalized: boolean;
  pda?: string | null;
};

export type AccountResponse = {
  room?: AccountPageData;
  pubkey: string;
  profile?: AccountProfile | null;
  user_state: AccountUserState | null;
  rider_soul?: RiderSoulState | null;
  beetle_cards: BeetleCard[];
  active_stakes: ActiveStake[];
  completions: CompletionSummary[];
  recent_ride_attestations?: RideAttestationSummary[];
  spl_balances: {
    cal: string | null;
    dung: string | null;
  };
  recent_events: ExplorerEvent[];
  freshness?: ScanFreshness;
};

export type AccountResolutionResponse = {
  username: string;
  pubkey: string;
};

export type IndexerHealthResponse = {
  status: string;
  service: string;
  lag_slots: NumericValue;
  account_lag_slots?: NumericValue;
  tx_lag_slots?: NumericValue;
  last_indexed_slot: NumericValue;
  last_account_slot?: NumericValue;
  last_tx_slot?: NumericValue;
  current_chain_slot: NumericValue;
  last_account_sync_at?: TimestampValue;
  last_tx_sync_at?: TimestampValue;
  stream_connected: boolean;
  mode: string;
  timestamp: string;
};

export type GroundClimb = {
  id: string; name: string; geometry?: { type: 'LineString'; coordinates: number[][] };
  length_m?: number; elev_gain_m?: number; avg_gradient_pct?: number;
  registered?: boolean; deposited?: string; completions?: number; attested?:boolean;
};
export type WeekProjection = {
  epoch?: number; settles_at?: string; climbs_registered?: number; cal_deposited?: string;
  riders?: number; rides_attested?: number; dung_distributed?: string;
};
export type DisplayEvent = ExplorerEvent & {
  kind?: 'settlement' | 'attestation' | 'deposit' | 'legend' | 'registration';
  object?: {id: string; name: string; type: string}; actor?: string;
  value?: {amount: string | number; unit: string}; signature?: string; epoch?: number;
};

export type AccountPageData = {
 handle?:string; avatar_url?:string; since_week?:number; since_date?:string;
 rides_attested?:number; seats?:number; crowns?:number; attested_climbs?:number; canon_count?:number;
 indexed?:{slot:number;at:string;age_seconds:number};
 ground:GroundClimb[];
 positions:Array<{climb:{id:string;name:string};rank?:number;since?:string;cal?:string}>;
 balances:Array<{account:string;symbol:string;amount:string;custody?:'climb'}>;
 completions:Array<{climb:{id:string;name:string};signature:string;event_index?:number;time_s?:number;date?:string}>;
 settlements:Array<{climb:{id:string;name:string};signature:string;event_index?:number;week?:number;date?:string;rank?:number;dung?:string}>;
 activity:DisplayEvent[]; completion_count?:number;settlement_count?:number;
};

export type TransactionReceipt = {
 kind?:'attestation'|'settlement'|'deposit'|'withdrawal'|'collection'|'registration'|'legend';
 climb?:{id:string;name:string};rider?:{wallet:string;handle?:string};program?:string;
 fields:{week_starts_at?:string;week_ends_at?:string;week?:number;time_s?:number;previous_best_s?:number;ride_hash?:string;completed?:string;dung?:string;cal?:string;rank?:number;since?:string;canon_version?:number;point_count?:number;climb_account?:string;vault_account?:string;positions_paid?:number;completions?:number};
 accounts:Array<{role?:string;pubkey:string}>;paid?:Array<{wallet:string;handle?:string;rank?:number;dung:string}>;logs?:string[];
};
