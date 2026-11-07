-- In-app delivery follows the finalized payout projection, in its transaction.
-- No push producer or provider call. Requires 099, 152 and 171.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE FUNCTION public.notify_stage1_payout() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE owner_id uuid; payload jsonb;
BEGIN
  -- The authenticated person owns the inbox. Their registered token recipient
  -- can be another wallet; it is not permission to expose their history there.
  SELECT id INTO owner_id FROM public.users
    WHERE wallet=NEW.person AND account_state='active' FOR UPDATE;
  IF owner_id IS NULL OR NEW.amount<=0 THEN RETURN NEW; END IF;
  IF EXISTS (SELECT 1 FROM public.notification_preferences WHERE user_id=owner_id
    AND (in_app_enabled=false OR payout_alerts=false OR payout_received=false)) THEN RETURN NEW; END IF;
  payload := pg_catalog.jsonb_build_object('stage1',true,'hill',NEW.hill,'week',NEW.week::text,
    'mint',NEW.mint,'kind',NEW.kind,'amountBaseUnits',NEW.amount::text,
    'signature',NEW.signature,'actionUrl','/profile?tab=portfolio');
  INSERT INTO public.notifications(user_id,wallet,notification_type,event_type,schema_version,
    title,message,metadata,data,occurred_at,delivery_status,delivery_channels,dedupe_key)
  VALUES(owner_id,NEW.person,'payout_received','payout_received','notification.v1',
    'payout_received',NULL,payload,payload,now(),'in_app_delivered','["in_app"]'::jsonb,
    'stage1:payout:'||NEW.claim_set||':'||NEW.leaf_index::text)
  ON CONFLICT(dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION public.notify_stage1_payout() FROM PUBLIC;
CREATE TRIGGER stage1_payout_notification AFTER INSERT ON public.indexed_stage1_payouts
FOR EACH ROW EXECUTE FUNCTION public.notify_stage1_payout();
COMMIT;
