-- Tighten read access policies while retaining service-role write capabilities.
-- Reads are scoped by wallet derived from JWT subject claim.

DROP POLICY IF EXISTS rides_wallet_read ON public.rides;
CREATE POLICY rides_wallet_read ON public.rides
  FOR SELECT USING (
    current_setting('request.jwt.claim.sub', true) = user_id::text
  );

DROP POLICY IF EXISTS proofs_wallet_read ON public.proofs;
CREATE POLICY proofs_wallet_read ON public.proofs
  FOR SELECT USING (
    current_setting('request.jwt.claim.sub', true) = user_id::text
  );

DROP POLICY IF EXISTS mint_events_wallet_read ON public.mint_events;
CREATE POLICY mint_events_wallet_read ON public.mint_events
  FOR SELECT USING (
    proof_id IN (
      SELECT id
      FROM public.proofs
      WHERE user_id::text = current_setting('request.jwt.claim.sub', true)
    )
  );
