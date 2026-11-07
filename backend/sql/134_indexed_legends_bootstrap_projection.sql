-- Restore the explicit Local Legend bootstrap field to the canonical deploy
-- stream. Legacy projection rows predate the field, so infer their founder
-- bootstrap state once when the column is first introduced. Current account
-- layouts always supply the explicit on-chain value.

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'indexed_legends'
          AND column_name = 'is_bootstrap'
    ) THEN
        ALTER TABLE public.indexed_legends
            ADD COLUMN is_bootstrap BOOLEAN NOT NULL DEFAULT false;

        UPDATE public.indexed_legends
        SET is_bootstrap = true
        WHERE election_period = 0
          AND completions_at_election = 0
          AND is_active = true;
    END IF;
END
$migration$;

COMMENT ON COLUMN public.indexed_legends.is_bootstrap IS
    'True when the Local Legend seat is the founder bootstrap stint rather than an elected recent-participation win.';
