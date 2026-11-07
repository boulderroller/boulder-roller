-- mint_events table
CREATE TABLE IF NOT EXISTS public.mint_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  proof_id uuid NOT NULL REFERENCES public.proofs(id),
  amount numeric,
  tx_hash text,
  status text
);

CREATE INDEX IF NOT EXISTS idx_mint_events_proof_id ON public.mint_events(proof_id);
