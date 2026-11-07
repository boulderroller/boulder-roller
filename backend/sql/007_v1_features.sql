-- V1 feature tables: CAL state, staking claims, Swanny seats, epochs, leaderboard cache
CREATE TABLE IF NOT EXISTS public.user_state (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  cal_balance numeric NOT NULL DEFAULT 0,
  cal_earned_today numeric NOT NULL DEFAULT 0,
  last_cal_mint timestamptz,
  total_rides bigint DEFAULT 0,
  total_tss numeric DEFAULT 0,
  bio_score integer DEFAULT 1000,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.claims (
  user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
  segment_id uuid REFERENCES public.segments(id) ON DELETE CASCADE,
  amount numeric NOT NULL,
  lp_tokens numeric NOT NULL,
  staked_at timestamptz NOT NULL DEFAULT now(),
  last_harvest timestamptz,
  PRIMARY KEY (user_id, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_claims_segment ON public.claims(segment_id);

CREATE TABLE IF NOT EXISTS public.swanny_seats (
  segment_id uuid REFERENCES public.segments(id) ON DELETE CASCADE,
  seat_index smallint NOT NULL CHECK (seat_index IN (0, 1, 2)),
  holder_pubkey text,
  locked_at timestamptz,
  unlock_at timestamptz,
  tasks_completed smallint DEFAULT 0,
  PRIMARY KEY (segment_id, seat_index)
);

CREATE TABLE IF NOT EXISTS public.epochs (
  segment_id uuid REFERENCES public.segments(id) ON DELETE CASCADE,
  epoch_number bigint NOT NULL,
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  total_pot numeric,
  distributed boolean NOT NULL DEFAULT false,
  PRIMARY KEY (segment_id, epoch_number)
);
CREATE INDEX IF NOT EXISTS idx_epochs_end_time_active ON public.epochs(end_time) WHERE distributed = false;

CREATE TABLE IF NOT EXISTS public.leaderboard_entries (
  segment_id uuid REFERENCES public.segments(id) ON DELETE CASCADE,
  epoch_number bigint NOT NULL,
  user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
  rank integer,
  time_seconds integer,
  tss numeric,
  PRIMARY KEY (segment_id, epoch_number, user_id)
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_segment_epoch_rank ON public.leaderboard_entries(segment_id, epoch_number, rank);
