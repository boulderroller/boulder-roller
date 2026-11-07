-- Vesting schedules for large DUNG rewards
CREATE TABLE IF NOT EXISTS vesting_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    token_type VARCHAR(10) NOT NULL,
    total_amount NUMERIC NOT NULL,
    vested_amount NUMERIC NOT NULL DEFAULT 0,
    start_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    end_date TIMESTAMPTZ NOT NULL,
    cliff_date TIMESTAMPTZ,
    source_type VARCHAR(50),
    source_id UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vesting_user ON vesting_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_vesting_end ON vesting_schedules(end_date);
