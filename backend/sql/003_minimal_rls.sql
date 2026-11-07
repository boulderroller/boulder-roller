-- Enable RLS where appropriate
ALTER TABLE public.rides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.proofs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mint_events ENABLE ROW LEVEL SECURITY;

-- rides: owner read/write
CREATE POLICY rides_owner_rw ON public.rides
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- proofs: owner read; writes by service role only
CREATE POLICY proofs_owner_read ON public.proofs
  FOR SELECT USING (user_id = auth.uid());

-- mint_events: owner read; writes by service role only
CREATE POLICY mint_events_owner_read ON public.mint_events
  FOR SELECT USING (
    proof_id IN (SELECT id FROM public.proofs WHERE user_id = auth.uid())
  );
