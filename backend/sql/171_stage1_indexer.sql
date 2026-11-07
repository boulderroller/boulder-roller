-- Stage 1 finalized projections and boundary sources. Service-only, after 169/170.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE public.stage1_indexer_alerts (
 kind text PRIMARY KEY, attempts integer NOT NULL,
 first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.stage1_indexer_namespace (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),genesis text NOT NULL,program text NOT NULL
);
CREATE TABLE public.stage1_indexer_network (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), genesis text NOT NULL, program text NOT NULL,
 from_slot bigint NOT NULL, from_time bigint NOT NULL, through_slot bigint NOT NULL, through_time bigint NOT NULL,
 through_epoch bigint NOT NULL, cursor text, ready boolean NOT NULL DEFAULT false, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.stage1_indexer_checkpoints (
 digest text PRIMARY KEY, genesis text NOT NULL, program text NOT NULL, slot bigint NOT NULL,
 hill text NOT NULL DEFAULT '',
 block_time bigint NOT NULL, checkpoint jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(genesis,program,hill,slot)
);
CREATE INDEX stage1_checkpoint_hill_boundary ON public.stage1_indexer_checkpoints(genesis,program,hill,block_time);
CREATE TABLE public.stage1_indexer_activation (
 genesis text NOT NULL, program text NOT NULL, slot bigint, kind text, before text, PRIMARY KEY(genesis,program)
);
-- One finalized program history, with independent ingestion and consumer fences.
CREATE TABLE public.stage1_indexer_stream (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 cursor text, cursor_slot bigint, before text, pending_head text, pending_slot bigint,
 fence_slot bigint, fence_time bigint, fence_at timestamptz, observed_slot bigint, observed_time bigint,
 covered_slot bigint, covered_time bigint, covered_at timestamptz, observed_at timestamptz,
 last_capture_time bigint, last_capture_wall bigint, history_start bigint, legacy_attached boolean NOT NULL DEFAULT false,
 attempts integer NOT NULL DEFAULT 0, retry_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.stage1_indexer_dependencies (hill text NOT NULL,address text NOT NULL,PRIMARY KEY(hill,address));
-- Only non-personal topology, never account bytes, holders, owners or records.
CREATE TABLE public.stage1_indexer_links (address text PRIMARY KEY,type text NOT NULL,fields jsonb NOT NULL);
CREATE TABLE public.stage1_indexer_pending (
 signature text PRIMARY KEY, slot bigint NOT NULL, block_time bigint, block_index integer,
 ingested boolean NOT NULL DEFAULT false, legacy_done boolean NOT NULL DEFAULT false, legacy_required boolean NOT NULL DEFAULT false,
 done boolean NOT NULL DEFAULT false
);
CREATE INDEX stage1_pending_slot ON public.stage1_indexer_pending(slot) WHERE NOT done OR (legacy_required AND NOT legacy_done);
CREATE TABLE public.stage1_indexer_hill_coverage (
 genesis text NOT NULL,program text NOT NULL,hill text NOT NULL,from_slot bigint NOT NULL,from_time bigint NOT NULL,
 through_slot bigint NOT NULL,through_time bigint NOT NULL,through_epoch bigint NOT NULL,
 PRIMARY KEY(genesis,program,hill)
);
CREATE TABLE public.stage1_indexer_transactions (
 signature text PRIMARY KEY, slot bigint NOT NULL, block_time bigint NOT NULL,
 witness jsonb NOT NULL, digest text NOT NULL
);
CREATE INDEX stage1_transaction_range ON public.stage1_indexer_transactions(slot);
CREATE TABLE public.stage1_indexer_transaction_hills (
 signature text NOT NULL REFERENCES public.stage1_indexer_transactions(signature) ON DELETE CASCADE,
 hill text NOT NULL, PRIMARY KEY(hill,signature)
);
CREATE TABLE public.stage1_boundary_tasks (
 genesis text NOT NULL, program text NOT NULL, hill text NOT NULL, week bigint NOT NULL CHECK(week>=0),
 state text NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','held','complete')),
 attempts integer NOT NULL DEFAULT 0, retry_at timestamptz NOT NULL DEFAULT now(), error text,
 archive jsonb, digest text, exported_digest text, updated_at timestamptz NOT NULL DEFAULT now(),
 imported_at timestamptz,
 PRIMARY KEY(genesis,program,hill,week)
);
CREATE TABLE public.stage1_boundary_witnesses (
 digest text PRIMARY KEY, genesis text NOT NULL, program text NOT NULL, hill text NOT NULL,
 boundary bigint NOT NULL, witness jsonb NOT NULL, UNIQUE(genesis,program,hill,boundary)
);
CREATE TABLE public.stage1_boundary_alerts (
 genesis text NOT NULL, program text NOT NULL, hill text NOT NULL, week bigint NOT NULL,
 kind text NOT NULL, first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(genesis,program,hill,week,kind)
);
CREATE TABLE public.indexed_stage1_events (
 signature text NOT NULL, event_index integer NOT NULL, name text NOT NULL, data jsonb NOT NULL,
 chain_slot bigint NOT NULL, block_time bigint NOT NULL, PRIMARY KEY(signature,event_index)
);
CREATE INDEX stage1_event_name ON public.indexed_stage1_events(name);
CREATE TABLE public.indexed_stage1_payouts (
 claim_set text NOT NULL, leaf_index bigint NOT NULL, signature text NOT NULL,
 hill text NOT NULL, week numeric(20,0) NOT NULL, mint text NOT NULL, person text NOT NULL,
 recipient text NOT NULL, amount numeric(20,0) NOT NULL CHECK(amount>=0), kind text NOT NULL CHECK(kind IN ('cash','dung')),
 chain_slot bigint NOT NULL, PRIMARY KEY(claim_set,leaf_index)
);
CREATE INDEX stage1_owner_pay ON public.indexed_stage1_payouts(person,hill,week);
CREATE TABLE public.indexed_stage1_pauses (
 signature text NOT NULL, instruction_index text NOT NULL, city text NOT NULL, kind text NOT NULL,
 paused boolean NOT NULL, chain_slot bigint NOT NULL, PRIMARY KEY(signature,instruction_index)
);
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['cities','assets','hills','lots','withdrawals','funding','recipients','cursors',
   'claim_sets','cash','boosts','boost_hills','dung_state','dung_mints','dung_claim_sets','test_pools'] LOOP
  EXECUTE format('CREATE TABLE public.indexed_stage1_%I (address text PRIMARY KEY, data jsonb NOT NULL,
    chain_slot bigint NOT NULL, closed boolean NOT NULL DEFAULT false, indexed_at timestamptz NOT NULL DEFAULT now())',name);
  EXECUTE format('CREATE INDEX ON public.indexed_stage1_%I ((data->>''owner''))',name);
  EXECUTE format('CREATE INDEX ON public.indexed_stage1_%I ((data->>''hill''))',name);
 END LOOP;
END $$;

CREATE TABLE public.stage1_boundary_exports (
 id text PRIMARY KEY, path text NOT NULL, digest text NOT NULL, payload jsonb NOT NULL,
 suspended boolean NOT NULL DEFAULT false, request_id uuid, removed_at timestamptz, redacted_digest text
);
ALTER TABLE public.stage1_boundary_exports ADD prune_pending boolean NOT NULL DEFAULT false;
CREATE FUNCTION public.stage1_indexer_imported(p_scope text,p_week bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE scope public.stage1_keeper_scopes;
BEGIN
 SELECT s.* INTO scope FROM public.stage1_keeper_scopes s JOIN public.stage1_keeper_boundaries b ON b.scope_id=s.id WHERE s.id=p_scope AND b.week=p_week;
 IF NOT FOUND THEN RAISE EXCEPTION 'verified_keeper_archive_required'; END IF;
 UPDATE public.stage1_boundary_tasks t SET imported_at=now(),archive=NULL WHERE t.program=scope.program AND t.hill=scope.hill AND t.week=p_week AND t.state='complete'
 AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(t.archive) e WHERE NOT EXISTS(
  SELECT 1 FROM public.stage1_keeper_boundaries b JOIN public.stage1_keeper_scopes s ON s.id=b.scope_id
  WHERE s.program=t.program AND s.hill=t.hill AND s.mint=e->'inputs'->'context'->>4 AND s.kind=coalesce(e->'inputs'->>'kind','cash') AND b.week=t.week
  AND b.inputs->'opening'->>'producer_witness'=e->'inputs'->'opening'->>'producer_witness'
  AND b.inputs->'closing'->>'producer_witness'=e->'inputs'->'closing'->>'producer_witness'));
 UPDATE public.stage1_boundary_exports e SET suspended=true,prune_pending=true WHERE NOT suspended AND NOT EXISTS(
  SELECT 1 FROM pg_catalog.jsonb_array_elements(e.payload) item WHERE NOT EXISTS(
   SELECT 1 FROM public.stage1_boundary_tasks t WHERE t.program=item->'inputs'->'context'->>0 AND t.hill=item->'inputs'->'context'->>2 AND t.week=(item->>'week')::bigint AND t.imported_at IS NOT NULL));
 PERFORM public.stage1_indexer_prune_sources();
END $$;
CREATE FUNCTION public.stage1_boundary_export_pruned(p_id text,p_digest text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 DELETE FROM public.stage1_boundary_exports WHERE id=p_id AND digest=p_digest AND prune_pending AND suspended;
 IF NOT FOUND THEN RAISE EXCEPTION 'boundary_prune_manifest_changed'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.stage1_indexer_imported(text,bigint),public.stage1_boundary_export_pruned(text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.stage1_indexer_imported(text,bigint),public.stage1_boundary_export_pruned(text,text) TO service_role;
CREATE TABLE public.stage1_indexer_maintenance (transaction_id bigint PRIMARY KEY);
REVOKE ALL ON public.stage1_indexer_maintenance FROM PUBLIC,anon,authenticated,service_role;

-- Producer and retention use the same covered banks. A fully pre-boundary
-- bank survives a mixed multi-batch capture that cannot be rewound.
CREATE FUNCTION public.stage1_boundary_banks(g text,p text,h text,b bigint)
RETURNS SETOF public.stage1_indexer_checkpoints LANGUAGE sql STABLE SET search_path='' AS $$
 WITH eligible AS (
  SELECT c.*,coalesce((SELECT max((a->>'observed_time')::bigint) FROM pg_catalog.jsonb_array_elements(c.checkpoint->'accounts') a),c.block_time) AS last_time
  FROM public.stage1_indexer_checkpoints c JOIN public.stage1_indexer_hill_coverage v USING(genesis,program,hill)
  WHERE c.genesis=g AND c.program=p AND c.hill=h AND coalesce((c.checkpoint->>'through_slot')::bigint,c.slot)<=v.through_slot
 ), ids AS (
  (SELECT digest FROM eligible WHERE last_time<b ORDER BY block_time DESC,slot DESC LIMIT 1)
  UNION (SELECT digest FROM eligible WHERE block_time<b ORDER BY block_time DESC,slot DESC LIMIT 1)
  UNION (SELECT digest FROM eligible WHERE block_time>=b ORDER BY block_time,slot LIMIT 1)
 ) SELECT c.* FROM public.stage1_indexer_checkpoints c JOIN ids USING(digest)
$$;
REVOKE ALL ON FUNCTION public.stage1_boundary_banks(text,text,text,bigint) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.stage1_boundary_banks(text,text,text,bigint) TO service_role;
CREATE FUNCTION public.stage1_indexer_prune_sources() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 INSERT INTO public.stage1_indexer_maintenance VALUES(pg_catalog.txid_current()) ON CONFLICT DO NOTHING;
 DELETE FROM public.stage1_indexer_checkpoints p WHERE p.hill<>'' AND NOT EXISTS(
  SELECT 1 FROM public.stage1_boundary_tasks t
  JOIN public.indexed_stage1_hills h ON h.address=t.hill JOIN public.indexed_stage1_cities c ON c.address=h.data->>'city'
  CROSS JOIN LATERAL (VALUES((c.data->>'seasonAnchor')::bigint+t.week*604800),((c.data->>'seasonAnchor')::bigint+(t.week+1)*604800)) b(at)
  CROSS JOIN LATERAL public.stage1_boundary_banks(t.genesis,t.program,t.hill,b.at) bank
  WHERE t.imported_at IS NULL AND bank.digest=p.digest)
 AND p.slot<>(SELECT max(q.slot) FROM public.stage1_indexer_checkpoints q WHERE q.hill=p.hill AND q.genesis=p.genesis AND q.program=p.program)
 AND EXISTS(SELECT 1 FROM public.stage1_indexer_hill_coverage v WHERE v.genesis=p.genesis AND v.program=p.program AND v.hill=p.hill AND v.through_slot>=coalesce((p.checkpoint->>'through_slot')::bigint,p.slot));
 DELETE FROM public.stage1_boundary_witnesses w WHERE EXISTS(
  SELECT 1 FROM public.stage1_boundary_tasks t WHERE t.hill=w.hill AND t.genesis=w.genesis AND t.program=w.program AND t.imported_at IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM public.stage1_boundary_tasks t
  JOIN public.indexed_stage1_hills h ON h.address=t.hill JOIN public.indexed_stage1_cities c ON c.address=h.data->>'city'
  WHERE t.hill=w.hill AND t.genesis=w.genesis AND t.program=w.program AND t.imported_at IS NULL
  AND w.boundary IN ((c.data->>'seasonAnchor')::bigint+t.week*604800,(c.data->>'seasonAnchor')::bigint+(t.week+1)*604800));
 DELETE FROM public.stage1_indexer_transactions x WHERE NOT EXISTS(
  SELECT 1 FROM public.stage1_indexer_pending p WHERE p.signature=x.signature AND (NOT p.done OR (p.legacy_required AND NOT p.legacy_done)))
 AND NOT EXISTS(
  SELECT 1 FROM public.stage1_indexer_transaction_hills r
  LEFT JOIN public.stage1_indexer_hill_coverage v ON v.hill=r.hill
  WHERE r.signature=x.signature AND (v.hill IS NULL OR x.slot>v.through_slot))
 AND NOT EXISTS(
  SELECT 1 FROM public.stage1_indexer_transaction_hills r JOIN public.stage1_boundary_tasks t ON t.hill=r.hill
  JOIN public.indexed_stage1_hills h ON h.address=t.hill JOIN public.indexed_stage1_cities c ON c.address=h.data->>'city'
  CROSS JOIN LATERAL (VALUES((c.data->>'seasonAnchor')::bigint+t.week*604800),((c.data->>'seasonAnchor')::bigint+(t.week+1)*604800)) b(at)
  WHERE r.signature=x.signature AND t.imported_at IS NULL
  AND NOT EXISTS(SELECT 1 FROM public.stage1_boundary_witnesses w WHERE w.hill=t.hill AND w.boundary=b.at AND w.genesis=t.genesis AND w.program=t.program)
  AND x.slot>=coalesce((SELECT min(p.slot) FROM public.stage1_boundary_banks(t.genesis,t.program,t.hill,b.at) p WHERE p.block_time<b.at),0)
  AND x.slot<=coalesce((SELECT coalesce((p.checkpoint->>'through_slot')::bigint,p.slot) FROM public.stage1_boundary_banks(t.genesis,t.program,t.hill,b.at) p WHERE p.block_time>=b.at ORDER BY p.block_time,p.slot LIMIT 1),9223372036854775807));
 DELETE FROM public.stage1_indexer_pending WHERE done AND (NOT legacy_required OR legacy_done);
 DELETE FROM public.stage1_indexer_maintenance WHERE transaction_id=pg_catalog.txid_current();
END $$;
REVOKE ALL ON FUNCTION public.stage1_indexer_prune_sources() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.stage1_indexer_prune_sources() TO service_role;

-- Pending/deleted identities are omitted from future copies. The same wallet
-- lock as deletion closes the check/write race when used inside a transaction.
CREATE FUNCTION public.stage1_indexer_personal_allowed(value jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE wallet text;
BEGIN
 FOR wallet IN SELECT DISTINCT matched[1] FROM public.stage1_wallet_strings(value) s
 CROSS JOIN LATERAL pg_catalog.regexp_matches(s,'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') matched ORDER BY 1 LOOP
  BEGIN
   PERFORM public.br_account_deletion_assert_wallet_write_allowed(wallet);
  EXCEPTION WHEN SQLSTATE '55000' THEN RETURN false;
  END;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION public.stage1_source_layout() RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path='' AS $layout$ SELECT '{"ProgramConfig":{"kind":"struct","fields":[{"name":"adminAuthority","docs":["Admin authority (can update config, perform admin operations)"],"type":"publicKey"},{"name":"backendAuthority","docs":["Backend authority (can credit/debit CAL, record completions)"],"type":"publicKey"},{"name":"programVersion","docs":["Program/account-layout version gate for external clients"],"type":"u8"},{"name":"initialized","docs":["Whether the config has been initialized"],"type":"bool"},{"name":"bump","docs":["PDA bump"],"type":"u8"},{"name":"calMint","docs":["CAL SPL mint pubkey (immutable after configure_mints)"],"type":"publicKey"},{"name":"dungMint","docs":["DUNG SPL mint pubkey (immutable after configure_mints)"],"type":"publicKey"},{"name":"calMintAuthBump","docs":["Bump for CAL_MINT_AUTH_PDA"],"type":"u8"},{"name":"dungMintAuthBump","docs":["Bump for DUNG_MINT_AUTH_PDA"],"type":"u8"},{"name":"polTokenAccount","docs":["POL token account (DUNG ATA for protocol-owned liquidity)"],"type":"publicKey"},{"name":"treasuryTokenAccount","docs":["Treasury token account (DUNG ATA for protocol treasury)"],"type":"publicKey"},{"name":"vaultCreationDung","docs":["DUNG burn required for DUNG-only vault creation"],"type":"u64"},{"name":"vaultCreationCal","docs":["CAL burn/deposit threshold for CAL-backed vault creation paths"],"type":"u64"},{"name":"harvestFeeBps","docs":["Harvest fee in basis points"],"type":"u64"},{"name":"minterRightsEpochs","docs":["Founder metadata/culture rights duration in settlement weeks"],"type":"u64"},{"name":"localLegendTermEpochs","docs":["Local Legend term duration in settlement weeks"],"type":"u64"},{"name":"epochsPerHalving","docs":["Settlement weeks between emission halvings"],"type":"u64"},{"name":"usdcMint","docs":["USDC SPL mint pubkey for supported app payments"],"type":"publicKey"},{"name":"usdcTreasuryTokenAccount","docs":["Treasury USDC token account receiving supported app payments"],"type":"publicKey"},{"name":"vaultCreationUsdc","docs":["USDC amount required for CAL+USDC vault creation"],"type":"u64"},{"name":"settlementClockV2StartsAt","docs":["Immutable Monday-clock cutover. The canonical anchor means a fresh V2-only clock."],"type":"i64"},{"name":"settlementClockVersion","docs":["Stored explicitly so clients and indexers can reject unknown clock layouts."],"type":"u8"}]},"Stage1CityConfig":{"kind":"struct","fields":[{"name":"version","type":"u8"},{"name":"lineLamports","type":"u64"},{"name":"liveLamports","type":"u64"},{"name":"seasonAnchor","type":"i64"},{"name":"seasonWeeks","type":"u16"},{"name":"tokenCapLamports","type":"u64"},{"name":"hillCapLamports","type":"u64"},{"name":"totalCapLamports","type":"u64"},{"name":"heldLots","type":"u64"},{"name":"heldBasisLamports","type":"u64"},{"name":"assetCount","type":"u8"},{"name":"rateEpochs","type":{"array":["u64",32]}},{"name":"freshUntil","type":{"array":["i64",32]}},{"name":"bump","type":"u8"},{"name":"providerSlots","docs":["Real providers use epoch freshness; local fixtures retain seconds."],"type":"u32"},{"name":"admittedEpochs","type":{"array":["u64",32]}},{"name":"publisher","type":"publicKey"},{"name":"dungTssCeilingMicros","type":"u64"},{"name":"dungStartWeekPlusOne","docs":["Zero means disabled; otherwise the configured start week plus one."],"type":"u64"},{"name":"guardian","docs":["Separate emergency signer. It can pause and resume intake and settlement."],"type":"publicKey"},{"name":"intakePaused","type":"bool"},{"name":"settlementPaused","type":"bool"},{"name":"registrar","docs":["Admits ratified climbs and hills only; rotation remains admin-only."],"type":"publicKey"}]},"Stage1AssetConfig":{"kind":"struct","fields":[{"name":"version","type":"u8"},{"name":"city","type":"publicKey"},{"name":"mint","type":"publicKey"},{"name":"enabled","type":"bool"},{"name":"adapter","type":"u8"},{"name":"rateNumerator","type":"u64"},{"name":"rateDenominator","type":"u64"},{"name":"observedAt","type":"i64"},{"name":"observationAdmitted","type":"bool"},{"name":"lastFreshUntil","type":"i64"},{"name":"admittedNumerator","type":"u64"},{"name":"admittedDenominator","type":"u64"},{"name":"slot","type":"u8"},{"name":"heldBasisLamports","type":"u64"},{"name":"harvestedUnits","docs":["Deployment-wide lifetime accumulator, never reset on exits/fee payment."],"type":"u128"},{"name":"feesAssessed","type":"u128"},{"name":"bump","type":"u8"},{"name":"providerAccount","type":"publicKey"},{"name":"admittedEpoch","type":"u64"},{"name":"providerStaleSince","docs":["First successful authenticated observation of an expired provider."],"type":"i64"},{"name":"outageProviderEpoch","type":"u64"},{"name":"outageIsOpaque","docs":["Authenticated unparseable/impossible state has no native update witness."],"type":"bool"},{"name":"ledger","type":{"defined":"Stage1Ledger"}}]},"Stage1Ledger":{"kind":"struct","fields":[{"name":"deposited","type":"u128"},{"name":"ownerCustody","docs":["Sum of lot.units + lot.owner_units, including exit partitions."],"type":"u128"},{"name":"ownerReturns","type":"u128"},{"name":"earnings","type":"u128"},{"name":"paid","type":"u128"},{"name":"claimable","type":"u128"},{"name":"held","type":"u128"},{"name":"pool","type":"u128"},{"name":"admittedCashLifetime","type":"u128"}]},"Stage1HillBond":{"kind":"struct","fields":[{"name":"version","type":"u8"},{"name":"city","type":"publicKey"},{"name":"climb","type":"publicKey"},{"name":"canonId","type":{"array":["u8",16]}},{"name":"commitmentHash","type":{"array":["u8",32]}},{"name":"bonded","type":"bool"},{"name":"bondedAt","type":"i64"},{"name":"founder","type":"publicKey"},{"name":"foundingCount","type":"u64"},{"name":"foundingCutoff","docs":["Membership also requires the lot''s bit in the immutable founding mask."],"type":"u64"},{"name":"foundingFreshSlots","type":"u32"},{"name":"lastSequence","type":"u64"},{"name":"heldBasisLamports","type":"u64"},{"name":"campaignCount","type":"u64"},{"name":"assetLots","type":{"array":["u64",32]}},{"name":"rateEpochs","type":{"array":["u64",32]}},{"name":"quotedCount","type":{"array":["u64",32]}},{"name":"quotedBacking","type":{"array":["u64",32]}},{"name":"quotedNumerators","docs":["Current per-slot quotes, frozen at bond; excluded slots have zero rates."],"type":{"array":["u64",32]}},{"name":"quotedDenominators","type":{"array":["u64",32]}},{"name":"bump","type":"u8"},{"name":"foundingLaggingSlots","docs":["Prior-epoch quotes retained for founding only; zero bonding-line value."],"type":"u32"},{"name":"admittedWeek","docs":["Settlement starts at admission, never at the city''s week zero."],"type":"u64"},{"name":"dungDepositedBasis","docs":["Conservative historical bounds for publisher-attested DUNG openings.","Never compare a past opening to today''s (possibly withdrawn) basis."],"type":"u128"},{"name":"dungFoundingBasis","type":"u64"},{"name":"dungLockEnds","docs":["Latest ordinary deposit lock end. Complete only when no campaign lot","was excluded at bonding (excluded conversions have a readonly hill)."],"type":{"array":["i64",3]}},{"name":"dungNextWeek","type":"u64"},{"name":"dungPublicationCommitment","type":{"array":["u8",32]}}]},"Stage1PledgeLot":{"kind":"struct","fields":[{"name":"version","type":"u8"},{"name":"city","type":"publicKey"},{"name":"hill","type":"publicKey"},{"name":"owner","type":"publicKey"},{"name":"mint","type":"publicKey"},{"name":"assetSlot","type":"u8"},{"name":"depositId","type":"u64"},{"name":"depositedAt","type":"i64"},{"name":"sequence","type":"u64"},{"name":"cancelled","type":"bool"},{"name":"quoteEpoch","type":"u64"},{"name":"quoteNumerator","type":"u64"},{"name":"quoteDenominator","type":"u64"},{"name":"quotedBacking","type":"u64"},{"name":"units","type":"u64"},{"name":"basisLamports","type":"u64"},{"name":"lockWeeks","type":"u16"},{"name":"lockEnd","type":"i64"},{"name":"founding","type":"bool"},{"name":"converted","docs":["Owner converted an excluded pre-bond lot into ordinary, non-founding stake."],"type":"bool"},{"name":"exiting","type":"bool"},{"name":"exitRequest","type":"publicKey"},{"name":"pendingRequest","type":"publicKey"},{"name":"ownerUnits","docs":["These units have separate token custody and never count as backing."],"type":"u64"},{"name":"prebondUnitsFrozen","type":"u64"},{"name":"harvestedUnits","type":"u64"},{"name":"observedLossLamports","docs":["Shortfall at the last validated observation, not a promise of recovery."],"type":"u64"},{"name":"realizedLossLamports","docs":["None when returned without a fresh rate; never invent a SOL loss."],"type":{"option":"u64"}},{"name":"returnedUnits","type":"u64"},{"name":"bump","type":"u8"}]},"Climb":{"kind":"struct","fields":[{"name":"canonCommitment","type":{"array":["u8",64]}},{"name":"commitmentHash","type":{"array":["u8",32]}},{"name":"canonId","type":{"array":["u8",16]}},{"name":"canonVersion","type":"u16"},{"name":"canonicalProfileHash","type":{"array":["u8",32]}},{"name":"predecessorClimb","type":"publicKey"},{"name":"successorClimb","docs":["Set exactly once when the admin registers the next exact canon version.","A nonzero successor makes this Climb stale for new Vault activation."],"type":"publicKey"},{"name":"recordContinuityPolicy","type":{"defined":"RecordContinuityPolicy"}},{"name":"vault","docs":["The sole economic activation of this exact canon version."],"type":"publicKey"},{"name":"name","type":{"array":["u8",64]}},{"name":"vertM","type":"u32"},{"name":"distanceM","type":"u32"},{"name":"avgGradientPct","type":"u16"},{"name":"registeredAt","type":"i64"},{"name":"registeredBy","type":"publicKey"},{"name":"bump","type":"u8"}]},"RecordContinuityPolicy":{"kind":"enum","variants":[{"name":"NewRecordBoard"},{"name":"CarryRecordsForward"}]},"Vault":{"kind":"struct","fields":[{"name":"id","type":"u64"},{"name":"signature","type":{"array":["u8",64]}},{"name":"signatureHash","type":{"array":["u8",32]}},{"name":"minter","type":"publicKey"},{"name":"mintEpoch","type":"u64"},{"name":"rightsExpiresEpoch","type":"u64"},{"name":"komHolder","type":"publicKey"},{"name":"komTimeS","type":"u32"},{"name":"komSetEpoch","type":"u64"},{"name":"name","type":{"array":["u8",64]}},{"name":"avatarIpfs","type":{"array":["u8",46]}},{"name":"slogan","type":{"array":["u8",128]}},{"name":"calTributeAccumulated","type":"u64"},{"name":"calTributeAccumulatedNext","type":"u64"},{"name":"totalCalBurned","type":"u64"},{"name":"totalDungEmitted","type":"u64"},{"name":"totalCompletions","type":"u64"},{"name":"totalCalStaked","type":"u64"},{"name":"stakerCount","type":"u32"},{"name":"rewardPerTokenStored","type":"u64"},{"name":"lastUpdateTime","type":"i64"},{"name":"rewardRate","docs":["Retired Synthetix slot. Stores STAKER_REMAINDER_POLICY_MARKER after the","one-time legacy carry cutover; the account layout remains unchanged."],"type":"u64"},{"name":"pendingRewards","type":"u64"},{"name":"pendingRewardsNextWeek","type":"u64"},{"name":"openSettlementWeek","type":"u64"},{"name":"carryRecordRoyalty","type":"u64"},{"name":"carryStakers","docs":["Already-unlocked staker pro-rata integer dust only."],"type":"u64"},{"name":"carryLocalLegend","type":"u64"},{"name":"carryPol","type":"u64"},{"name":"carryTreasury","type":"u64"},{"name":"totalStaked","type":"u64"},{"name":"lastDistributionEpoch","type":"u64"},{"name":"vertM","type":"u32"},{"name":"distanceM","type":"u32"},{"name":"avgGradientPct","type":"u16"},{"name":"createdAt","type":"i64"},{"name":"bump","type":"u8"},{"name":"climb","docs":["V4-B append-only link to the immutable canon Climb account."],"type":"publicKey"}]},"VaultLeaderboard":{"kind":"struct","fields":[{"name":"vaultId","type":"u64"},{"name":"entries","type":{"vec":{"defined":"LeaderEntry"}}},{"name":"lastUpdated","type":"i64"},{"name":"bump","type":"u8"}]},"LeaderEntry":{"kind":"struct","fields":[{"name":"user","type":"publicKey"},{"name":"timeS","type":"u32"},{"name":"recordedAt","type":"i64"}]},"LocalLegend":{"kind":"struct","fields":[{"name":"vaultId","type":"u64"},{"name":"holder","type":"publicKey"},{"name":"electionPeriod","type":"u64"},{"name":"termStartEpoch","type":"u64"},{"name":"termEndEpoch","type":"u64"},{"name":"completionsAtElection","type":"u32"},{"name":"runnerUp","type":"publicKey"},{"name":"runnerUpCompletions","type":"u32"},{"name":"totalEarned","type":"u64"},{"name":"isActive","type":"bool"},{"name":"isBootstrap","type":"bool"},{"name":"bump","type":"u8"}]}}'::jsonb $layout$;
-- Decode original Borsh before issuing an erasure receipt. Neither supplied
-- field labels nor supplied span paths can authorize erasing different bytes.
CREATE FUNCTION public.stage1_source_pubkey(raw bytea) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE n numeric:=0; result text:=''; alphabet text:='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'; i int;
BEGIN
 FOR i IN 0..pg_catalog.length(raw)-1 LOOP n:=n*256+pg_catalog.get_byte(raw,i); END LOOP;
 WHILE n>0 LOOP result:=pg_catalog.substr(alphabet,mod(n,58)::int+1,1)||result;n:=div(n,58); END LOOP;
 FOR i IN 0..pg_catalog.length(raw)-1 LOOP EXIT WHEN pg_catalog.get_byte(raw,i)<>0;result:='1'||result; END LOOP;
 RETURN result;
END $$;
CREATE FUNCTION public.stage1_source_read(t jsonb,raw bytea,pos int,path text[],defs jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE scalar text; width int; start int:=pos; n numeric:=0; value jsonb; spans jsonb:='[]'; child jsonb; item jsonb; i int; count int; tag int; kind text;
BEGIN
 IF t IS NULL THEN RAISE EXCEPTION 'unknown_source_layout'; END IF;
 IF pg_catalog.jsonb_typeof(t)='string' THEN
  scalar:=t#>>'{}';kind:=scalar;
  IF scalar='publicKey' THEN width:=32;
  ELSIF scalar='bool' THEN width:=1;
  ELSIF scalar ~ '^[ui][0-9]+$' THEN width:=pg_catalog.substr(scalar,2)::int/8;
  ELSIF scalar IN ('bytes','string') THEN
   child:=public.stage1_source_read('"u32"',raw,pos,path||ARRAY['$length'],defs);pos:=(child->>'end')::int;width:=(child->>'value')::int;spans:=child->'spans';
  ELSE RAISE EXCEPTION 'unsupported_source_scalar'; END IF;
  IF width<0 OR pos+width>pg_catalog.length(raw) THEN RAISE EXCEPTION 'truncated_source'; END IF;
  IF scalar='publicKey' THEN value:=pg_catalog.to_jsonb(public.stage1_source_pubkey(pg_catalog.substr(raw,pos+1,width)));
  ELSIF scalar='bool' THEN
   IF pg_catalog.get_byte(raw,pos)>1 THEN RAISE EXCEPTION 'invalid_source_bool'; END IF;
   value:=pg_catalog.to_jsonb(pg_catalog.get_byte(raw,pos)=1);
  ELSIF scalar='string' THEN value:=pg_catalog.to_jsonb(pg_catalog.convert_from(pg_catalog.substr(raw,pos+1,width),'UTF8'));
  ELSIF scalar='bytes' THEN
   value:='[]';FOR i IN 0..width-1 LOOP value:=value||pg_catalog.jsonb_build_array(pg_catalog.get_byte(raw,pos+i)); END LOOP;
  ELSE
   FOR i IN REVERSE width-1..0 LOOP n:=n*256+pg_catalog.get_byte(raw,pos+i); END LOOP;
   IF pg_catalog.left(scalar,1)='i' AND pg_catalog.get_byte(raw,pos+width-1)>=128 THEN n:=n-power(256::numeric,width); END IF;
   value:=CASE WHEN width>=8 THEN pg_catalog.to_jsonb(trunc(n)::text) ELSE pg_catalog.to_jsonb(n) END;
  END IF;
  spans:=spans||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('path',path,'kind',kind,'offset',pos,'length',width));pos:=pos+width;
 ELSIF t ? 'defined' THEN RETURN public.stage1_source_read(defs->(t->>'defined'),raw,pos,path,defs);
 ELSIF t ? 'array' OR t ? 'vec' THEN
  IF t ? 'array' THEN count:=(t->'array'->>1)::int;item:=t->'array'->0;
  ELSE child:=public.stage1_source_read('"u32"',raw,pos,path||ARRAY['$length'],defs);pos:=(child->>'end')::int;count:=(child->>'value')::int;spans:=child->'spans';item:=t->'vec'; END IF;
  IF count<0 OR count>65536 THEN RAISE EXCEPTION 'invalid_source_count'; END IF;
  value:='[]';start:=pos;
  FOR i IN 0..count-1 LOOP child:=public.stage1_source_read(item,raw,pos,path||i::text,defs);value:=value||pg_catalog.jsonb_build_array(child->'value');pos:=(child->>'end')::int;spans:=spans||(child->'spans'); END LOOP;
  IF t ? 'array' AND item='"u8"'::jsonb THEN spans:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('path',path,'kind','u8array','offset',start,'length',count)); END IF;
 ELSIF t ? 'option' THEN
  child:=public.stage1_source_read('"u8"',raw,pos,path||ARRAY['$option'],defs);pos:=(child->>'end')::int;tag:=(child->>'value')::int;spans:=child->'spans';value:='null';
  IF tag=1 THEN child:=public.stage1_source_read(t->'option',raw,pos,path,defs);pos:=(child->>'end')::int;value:=child->'value';spans:=spans||(child->'spans');
  ELSIF tag<>0 THEN RAISE EXCEPTION 'invalid_source_option'; END IF;
 ELSIF t->>'kind'='struct' THEN
  value:='{}';FOR item IN SELECT * FROM pg_catalog.jsonb_array_elements(t->'fields') LOOP
   child:=public.stage1_source_read(item->'type',raw,pos,path||(item->>'name'),defs);pos:=(child->>'end')::int;value:=value||pg_catalog.jsonb_build_object(item->>'name',child->'value');spans:=spans||(child->'spans');
  END LOOP;
 ELSIF t->>'kind'='enum' THEN
  child:=public.stage1_source_read('"u8"',raw,pos,path||ARRAY['$variant'],defs);pos:=(child->>'end')::int;spans:=child->'spans';item:=t->'variants'->((child->>'value')::int);
  IF item IS NULL OR coalesce(pg_catalog.jsonb_array_length(item->'fields'),0)>0 THEN RAISE EXCEPTION 'invalid_source_enum'; END IF;
  scalar:=item->>'name';value:=pg_catalog.jsonb_build_object(pg_catalog.lower(pg_catalog.left(scalar,1))||pg_catalog.substr(scalar,2),'{}'::jsonb);
 ELSE RAISE EXCEPTION 'unsupported_source_type'; END IF;
 RETURN pg_catalog.jsonb_build_object('value',value,'end',pos,'spans',spans);
END $$;
-- Independently validate lot PDAs before erasing their owner/seed preimages.
CREATE FUNCTION public.stage1_source_key(s text) RETURNS bytea
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE alphabet text:='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'; n numeric:=0; digit int; result bytea:=''::bytea; i int;
BEGIN
 IF pg_catalog.length(s) NOT BETWEEN 32 AND 44 THEN RAISE EXCEPTION 'invalid_source_key'; END IF;
 FOR i IN 1..pg_catalog.length(s) LOOP
  digit:=pg_catalog.strpos(alphabet,pg_catalog.substr(s,i,1))-1;
  IF digit<0 THEN RAISE EXCEPTION 'invalid_source_key'; END IF;
  n:=n*58+digit;
 END LOOP;
 FOR i IN 1..32 LOOP result:=pg_catalog.decode(pg_catalog.lpad(pg_catalog.to_hex(mod(n,256)::int),2,'0'),'hex')||result;n:=pg_catalog.div(n,256); END LOOP;
 IF n<>0 OR public.stage1_source_pubkey(result)<>s THEN RAISE EXCEPTION 'invalid_source_key'; END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.stage1_source_on_curve(raw bytea) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE p numeric:=57896044618658097711785492504343953926634992332820282019728792003956564819949;
 d numeric:=37095705934669439343138083508754565189542113879843219016388785533085940283555;
 y numeric:=0; u numeric; v numeric; base numeric; exponent numeric; result numeric:=1; i int;
BEGIN
 IF pg_catalog.length(raw)<>32 THEN RAISE EXCEPTION 'invalid_curve_bytes'; END IF;
 -- Dalek accepts noncanonical y modulo p and either sign, including x=0.
 FOR i IN REVERSE 31..0 LOOP y:=y*256+CASE WHEN i=31 THEN pg_catalog.get_byte(raw,i)%128 ELSE pg_catalog.get_byte(raw,i) END; END LOOP;
 y:=mod(y*y,p);u:=mod(y-1+p,p);v:=mod(d*y+1,p);
 IF v=0 THEN RETURN u=0; END IF;
 base:=mod(u*v,p);exponent:=pg_catalog.div(p-1,2);
 WHILE exponent>0 LOOP
  IF mod(exponent,2)=1 THEN result:=mod(result*base,p); END IF;
  base:=mod(base*base,p);exponent:=pg_catalog.div(exponent,2);
 END LOOP;
 RETURN result IN (0,1);
END $$;
CREATE FUNCTION public.stage1_source_lot_address(program text,f jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE seeds bytea; n numeric; id bytea:=''::bytea; candidate bytea; bump int; i int;
BEGIN
 IF (f->>'exiting')::boolean THEN
  seeds:=pg_catalog.convert_to('s1v1_exit','UTF8')||public.stage1_source_key(f->>'exitRequest');
 ELSE
  n:=(f->>'depositId')::numeric;
  IF n<0 OR n>18446744073709551615 OR n<>trunc(n) THEN RAISE EXCEPTION 'invalid_lot_id'; END IF;
  FOR i IN 1..8 LOOP id:=id||pg_catalog.decode(pg_catalog.lpad(pg_catalog.to_hex(mod(n,256)::int),2,'0'),'hex');n:=pg_catalog.div(n,256); END LOOP;
  seeds:=pg_catalog.convert_to('s1v1_lot','UTF8')||public.stage1_source_key(f->>'owner')||id;
 END IF;
 FOR bump IN REVERSE 255..1 LOOP
  candidate:=pg_catalog.sha256(seeds||pg_catalog.decode(pg_catalog.lpad(pg_catalog.to_hex(bump),2,'0'),'hex')||public.stage1_source_key(program)||pg_catalog.convert_to('ProgramDerivedAddress','UTF8'));
  IF NOT public.stage1_source_on_curve(candidate) THEN RETURN public.stage1_source_pubkey(candidate); END IF;
 END LOOP;
 RAISE EXCEPTION 'source_lot_pda_unavailable';
END $$;
REVOKE ALL ON FUNCTION public.stage1_source_key(text),public.stage1_source_on_curve(bytea),public.stage1_source_lot_address(text,jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.stage1_source_pristine(v jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE item jsonb; part jsonb; raw bytea:=''; data bytea; spans jsonb:='[]'; decoded jsonb; defs jsonb; manifest jsonb:='[]'; padding boolean:=false; last_end int:=0; kind text;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='array' THEN
  FOR item IN SELECT * FROM pg_catalog.jsonb_array_elements(v) LOOP PERFORM public.stage1_source_pristine(item); END LOOP;RETURN;
 ELSIF pg_catalog.jsonb_typeof(v)<>'object' THEN RETURN; END IF;
 IF v ?| ARRAY['erased','replacement','missing','record_order','record_not_before','record_term','registered_before','erasure_basis','redacted','omitted','lot_identity_digest','lot_source_digest','lot_owner_rank'] THEN RAISE EXCEPTION 'source_must_be_pristine'; END IF;
 IF v ? 'accounts' AND v ? 'program' THEN
  FOR item IN SELECT a FROM pg_catalog.jsonb_array_elements(v->'accounts') a WHERE a->>'type'='Stage1PledgeLot' LOOP
   IF public.stage1_source_lot_address(v->>'program',item->'fields') IS DISTINCT FROM item->>'address' THEN RAISE EXCEPTION 'source_lot_pda_mismatch'; END IF;
  END LOOP;
 END IF;
 IF NOT v ? 'parts' THEN
  IF v ? 'type' AND v ? 'fields' THEN RAISE EXCEPTION 'source_account_parts_required'; END IF;
  FOR item IN SELECT value FROM pg_catalog.jsonb_each(v) LOOP PERFORM public.stage1_source_pristine(item); END LOOP;RETURN;
 END IF;
 FOR part IN SELECT * FROM pg_catalog.jsonb_array_elements(v->'parts') LOOP
  IF part ?| ARRAY['erased','replacement','missing'] OR (part->>'offset')::int<>last_end OR (part->>'length')::int<0 OR padding THEN RAISE EXCEPTION 'invalid_source_span'; END IF;
  last_end:=last_end+(part->>'length')::int;
  IF part->'path'='["$padding"]'::jsonb THEN padding:=true; END IF;
  IF coalesce((part->>'discarded')::boolean,false) THEN
   IF NOT padding OR part ? 'data' THEN RAISE EXCEPTION 'invalid_discarded_source'; END IF;
   data:=pg_catalog.decode(pg_catalog.repeat('00',(part->>'length')::int),'hex');
  ELSE
   data:=pg_catalog.decode(part->>'data','base64');
   IF pg_catalog.length(data)<>(part->>'length')::int OR pg_catalog.encode(pg_catalog.sha256(data),'hex')<>part->>'digest' THEN RAISE EXCEPTION 'source_span_digest_mismatch'; END IF;
  END IF;
  raw:=raw||data;manifest:=manifest||pg_catalog.jsonb_build_array(part-'data'-'discarded');
  IF NOT padding THEN spans:=spans||pg_catalog.jsonb_build_array(part-'data'-'discarded'-'digest'); END IF;
 END LOOP;
 IF public.stage1_json_digest(manifest)<>v->>'parts_digest' THEN RAISE EXCEPTION 'source_manifest_mismatch'; END IF;
 IF NOT coalesce((v->'parts'->-1->>'discarded')::boolean,false) AND pg_catalog.encode(pg_catalog.sha256(raw),'hex')<>v->>'raw_digest' THEN RAISE EXCEPTION 'source_account_digest_mismatch'; END IF;
 kind:=v->>'type';
 IF pg_catalog.substr(raw,1,8)<>pg_catalog.substr(pg_catalog.sha256(pg_catalog.convert_to('account:'||kind,'UTF8')),1,8) THEN RAISE EXCEPTION 'source_discriminator_mismatch'; END IF;
 defs:=public.stage1_source_layout();
 IF kind='LocalLegend' AND pg_catalog.length(raw)=122 THEN defs:=pg_catalog.jsonb_set(defs,'{LocalLegend,fields}',(SELECT pg_catalog.jsonb_agg(f) FROM pg_catalog.jsonb_array_elements(defs->'LocalLegend'->'fields') f WHERE f->>'name'<>'isBootstrap')); END IF;
 decoded:=public.stage1_source_read(defs->kind,raw,8,ARRAY[]::text[],defs);
 IF kind='LocalLegend' AND pg_catalog.length(raw)=122 THEN decoded:=pg_catalog.jsonb_set(decoded,'{value,isBootstrap}',pg_catalog.to_jsonb((decoded->'value'->>'isActive')::boolean AND decoded->'value'->>'electionPeriod'='0' AND decoded->'value'->>'completionsAtElection'='0')); END IF;
 IF decoded->'value'<>v->'fields' OR spans<>pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('path',ARRAY['$discriminator'],'kind','bytes','offset',0,'length',8))||(decoded->'spans') THEN RAISE EXCEPTION 'source_layout_disagrees'; END IF;
 IF padding AND (decoded->>'end')::int<>(v->'parts'->-1->>'offset')::int THEN RAISE EXCEPTION 'semantic_padding_forbidden'; END IF;
END $$;

REVOKE ALL ON FUNCTION public.stage1_source_layout(),public.stage1_source_pubkey(bytea),public.stage1_source_read(jsonb,bytea,int,text[],jsonb),public.stage1_source_pristine(jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.stage1_indexer_filter_checkpoint(value jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE wallet text; marker text; result jsonb:=value; validated boolean:=false;
BEGIN
 FOR wallet IN SELECT DISTINCT matched[1] FROM public.stage1_wallet_strings(value) s
 CROSS JOIN LATERAL pg_catalog.regexp_matches(s,'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') matched ORDER BY 1 LOOP
  BEGIN PERFORM public.br_account_deletion_assert_wallet_write_allowed(wallet); EXCEPTION WHEN SQLSTATE '55000' THEN NULL; END;
  SELECT 'anonymous:'||t.anonymous_marker::text INTO marker FROM public.deleted_account_tombstones t WHERE t.wallet_fingerprint=public.br_account_deletion_wallet_fingerprint(wallet);
  IF marker IS NOT NULL THEN
   IF NOT validated THEN PERFORM public.stage1_source_pristine(value);validated:=true; END IF;
   result:=public.stage1_indexer_redact(result,wallet,marker);
  ELSE PERFORM public.br_account_deletion_assert_wallet_write_allowed(wallet); END IF;
 END LOOP;
 IF result<>value THEN
  INSERT INTO public.stage1_source_redactions(digest,original_digest) VALUES(public.stage1_json_digest(result),public.stage1_json_digest(value)) ON CONFLICT DO NOTHING;
 END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.stage1_indexer_projection_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF public.stage1_keeper_erasing() OR public.stage1_indexer_personal_allowed(pg_catalog.to_jsonb(NEW)) THEN RETURN NEW; END IF;
 RETURN NULL;
END $$;

-- Namespace cannot be repointed, even by restarting with another RPC URL.
CREATE FUNCTION public.stage1_indexer_network_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF TG_OP='DELETE' OR NEW.genesis<>OLD.genesis OR NEW.program<>OLD.program OR NEW.from_slot<>OLD.from_slot
 OR NEW.from_time<>OLD.from_time OR NEW.through_slot<OLD.through_slot OR NEW.through_time<OLD.through_time THEN RAISE EXCEPTION 'Stage 1 indexer namespace/coverage is immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_indexer_network_guard BEFORE UPDATE OR DELETE ON public.stage1_indexer_network
 FOR EACH ROW EXECUTE FUNCTION public.stage1_indexer_network_guard();

-- Every shared compatibility observation is fenced to the retained namespace.
ALTER FUNCTION public.observe_program_version(text,text,smallint) RENAME TO observe_program_version_pre_indexer;
CREATE FUNCTION public.observe_program_version(p_genesis_hash text,p_program_id text,p_version smallint) RETURNS smallint
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.stage1_indexer_network WHERE genesis<>p_genesis_hash OR program<>p_program_id)
 THEN RAISE EXCEPTION 'Stage 1 indexer database genesis/program mismatch'; END IF;
 RETURN public.observe_program_version_pre_indexer(p_genesis_hash,p_program_id,p_version);
END $$;
REVOKE ALL ON FUNCTION public.observe_program_version(text,text,smallint) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.stage1_indexer_source_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF public.stage1_keeper_erasing() OR EXISTS(SELECT 1 FROM public.stage1_indexer_maintenance WHERE transaction_id=pg_catalog.txid_current()) THEN RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END IF;
 RAISE EXCEPTION 'Stage 1 finalized source is immutable';
END $$;
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['stage1_indexer_namespace','stage1_indexer_checkpoints','stage1_indexer_transactions','stage1_boundary_witnesses'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_source BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.stage1_indexer_source_guard()',name);
 END LOOP;
 FOR name IN SELECT tablename FROM pg_tables WHERE schemaname='public'
  AND tablename<>'stage1_indexer_maintenance' AND (tablename LIKE 'indexed_stage1_%%' OR tablename LIKE 'stage1_indexer_%%' OR tablename LIKE 'stage1_boundary_%%') LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',name);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',name);
  IF name LIKE 'indexed_stage1_%%' THEN
   EXECUTE format('CREATE TRIGGER personal_write_fence BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.stage1_indexer_projection_fence()',name);
  ELSIF name='stage1_boundary_exports' THEN
   EXECUTE 'CREATE TRIGGER personal_write_fence BEFORE INSERT OR UPDATE OF payload ON public.stage1_boundary_exports FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence()';
  ELSE
   EXECUTE format('CREATE TRIGGER personal_write_fence BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence()',name);
  END IF;
 END LOOP;
END $$;

-- Public explorer receipts retain Stage 1 names/fees/slots, never personal
-- arguments, pay amounts or Merkle proofs. Private typed projections own them.
UPDATE public.indexed_transactions SET instruction_args='{}',instruction_accounts='{}'
 WHERE instruction_name LIKE '%Stage1%' OR instruction_name IN
 ('pledge','bond','initCityConfig','configureAsset','initHillBond','refreshCampaignLot','convertExcludedPledge',
  'cancelPledge','withdrawPrebond','requestWithdrawal','cancelWithdrawal','beginWithdrawal','completeWithdrawal');

-- Indexed reverse dependencies are maintained on changed rows, never discovered
-- by scanning retained history during a deletion request.
CREATE TABLE public.stage1_wallet_rows (
 fingerprint text NOT NULL, relation text NOT NULL, row_key jsonb NOT NULL, job_id text,
 PRIMARY KEY(fingerprint,relation,row_key)
);
CREATE INDEX stage1_wallet_row_reverse ON public.stage1_wallet_rows(relation,row_key);
REVOKE ALL ON public.stage1_wallet_rows FROM PUBLIC,anon,authenticated,service_role;
CREATE FUNCTION public.stage1_row_key(relation_name text,value jsonb) RETURNS jsonb
LANGUAGE sql STABLE SET search_path='' AS $$
 SELECT pg_catalog.jsonb_object_agg(a.attname,value->a.attname)
 FROM pg_catalog.pg_index i CROSS JOIN LATERAL pg_catalog.unnest(i.indkey) k(attnum)
 JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
 WHERE i.indrelid=pg_catalog.to_regclass('public.'||relation_name) AND i.indisprimary
$$;
CREATE FUNCTION public.stage1_wallet_strings(v jsonb) RETURNS SETOF text
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE r record; item jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  FOR r IN SELECT * FROM pg_catalog.jsonb_each(v-'raw'-'parts') LOOP
   RETURN NEXT r.key; RETURN QUERY SELECT * FROM public.stage1_wallet_strings(r.value);
  END LOOP;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  FOR item IN SELECT * FROM pg_catalog.jsonb_array_elements(v) LOOP RETURN QUERY SELECT * FROM public.stage1_wallet_strings(item); END LOOP;
 ELSIF pg_catalog.jsonb_typeof(v)='string' THEN RETURN NEXT v#>>'{}'; END IF;
END $$;
CREATE FUNCTION public.stage1_index_wallet_row(relation_name text,value jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE key jsonb; job text; proof record;
BEGIN
 IF relation_name='indexed_events' AND coalesce(value->>'event_name','') NOT LIKE 'Stage1%' THEN RETURN; END IF;
 key:=public.stage1_row_key(relation_name,value);
 job:=CASE WHEN relation_name='stage1_keeper_jobs' THEN value->>'id' ELSE value->>'job_id' END;
 DELETE FROM public.stage1_wallet_rows WHERE relation=relation_name AND row_key=key;
 INSERT INTO public.stage1_wallet_rows(fingerprint,relation,row_key,job_id)
 SELECT DISTINCT public.br_account_deletion_wallet_fingerprint(m[1]),relation_name,key,job
 FROM public.stage1_wallet_strings(value) s CROSS JOIN LATERAL pg_catalog.regexp_matches(s,
 '(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') m ON CONFLICT DO NOTHING;
 IF relation_name='stage1_keeper_payout_actions' THEN
  INSERT INTO public.stage1_wallet_rows(fingerprint,relation,row_key,job_id)
  SELECT DISTINCT public.br_account_deletion_wallet_fingerprint(w.person),relation_name,key,job
  FROM pg_catalog.jsonb_array_elements(coalesce(value->'operation'->'refs','[]')) ref
  JOIN public.stage1_keeper_proofs p ON p.job_id=ref->>'job_id' AND p.role=(ref->>'role')::smallint AND p.leaf_index=(ref->>'index')::integer
  CROSS JOIN LATERAL (VALUES(p.person),(p.leaf->>'recipient')) w(person) WHERE w.person IS NOT NULL ON CONFLICT DO NOTHING;
 END IF;
END $$;
CREATE FUNCTION public.stage1_wallet_row_trigger() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF TG_OP IN ('UPDATE','DELETE') THEN DELETE FROM public.stage1_wallet_rows WHERE relation=TG_TABLE_NAME AND row_key=public.stage1_row_key(TG_TABLE_NAME,pg_catalog.to_jsonb(OLD)); END IF;
 IF TG_OP<>'DELETE' THEN PERFORM public.stage1_index_wallet_row(TG_TABLE_NAME,pg_catalog.to_jsonb(NEW)); END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
DO $$
DECLARE name text; row record;
BEGIN
 FOR name IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' AND
 (tablename LIKE 'indexed_stage1_%' OR tablename IN ('stage1_indexer_checkpoints','stage1_indexer_transactions',
 'stage1_boundary_tasks','stage1_boundary_witnesses','stage1_boundary_exports','stage1_keeper_boundaries','stage1_keeper_measurements',
 'stage1_keeper_jobs','stage1_keeper_proofs','stage1_keeper_attempts','stage1_keeper_reconciliations','stage1_keeper_alerts',
 'stage1_keeper_erasure_exports','stage1_keeper_payout_actions','indexed_events')) LOOP
  EXECUTE format('CREATE TRIGGER stage1_wallet_dependencies AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.stage1_wallet_row_trigger()',name);
  FOR row IN EXECUTE format('SELECT to_jsonb(t) AS value FROM public.%I t',name) LOOP PERFORM public.stage1_index_wallet_row(name,row.value); END LOOP;
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION public.stage1_keeper_has_personal_data(wallet text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT CASE WHEN coalesce(wallet,'')='' THEN false ELSE EXISTS(SELECT 1 FROM public.stage1_wallet_rows WHERE fingerprint=public.br_account_deletion_wallet_fingerprint(wallet)) END
$$;
CREATE OR REPLACE FUNCTION public.stage1_keeper_personal_jobs(wallet text) RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT DISTINCT job_id FROM public.stage1_wallet_rows WHERE fingerprint=public.br_account_deletion_wallet_fingerprint(wallet) AND job_id IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION public.stage1_keeper_anonymize() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.deletion_requests; wallet text; marker text; targets jsonb; jobs text[];
BEGIN
 IF NEW.account_state <> 'anonymized' THEN RETURN NEW; END IF;
 SELECT d.* INTO r FROM public.deletion_requests d
 WHERE d.id::text=pg_catalog.current_setting('app.account_deletion_request_id',true);
 IF NOT FOUND THEN RAISE EXCEPTION 'keeper_erasure_finalizer_required'; END IF;
 IF NOT public.stage1_keeper_has_personal_data(r.wallet) THEN RETURN NEW; END IF;
 IF NOT public.stage1_keeper_erasing() THEN RAISE EXCEPTION 'keeper_erasure_finalizer_required'; END IF;
 SELECT d.* INTO r FROM public.deletion_requests d JOIN public.stage1_keeper_erasure_sessions s ON s.request_id=d.id
 WHERE s.transaction_id=pg_catalog.txid_current();
 wallet := r.wallet; marker := NEW.wallet;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t)),'[]') INTO targets FROM public.stage1_wallet_rows t WHERE fingerprint=public.br_account_deletion_wallet_fingerprint(wallet);
 SELECT coalesce(pg_catalog.array_agg(x),ARRAY[]::text[]) INTO jobs FROM public.stage1_keeper_personal_jobs(wallet) x;
 IF NEW.id IS DISTINCT FROM NEW.anonymous_marker OR marker IS DISTINCT FROM 'anonymous:'||NEW.id::text
 OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=r.user_id AND account_state='deletion_pending'
 AND account_deletion_request_id=r.id AND users.wallet=r.wallet) THEN RAISE EXCEPTION 'keeper_erasure_identity_fence'; END IF;
 IF EXISTS(SELECT 1 FROM public.stage1_keeper_jobs j WHERE export_path IS NOT NULL
 AND j.id=ANY(jobs)
 AND (NOT export_suspended OR NOT EXISTS(SELECT 1 FROM public.stage1_keeper_erasure_exports e
 WHERE e.request_id=r.id AND e.job_id=j.id AND e.path=j.export_path AND e.digest=j.export_digest AND e.redacted_digest IS NOT NULL AND e.removed_at IS NOT NULL)))
 THEN RAISE EXCEPTION 'keeper_erasure_exports_not_removed'; END IF;
 -- A paid transaction contains recoverable person/recipient bytes. Retain
 -- public signature/fee/slot and commitments, never those private preimages.
 UPDATE public.stage1_keeper_payout_actions a SET signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker),
 attempts=(SELECT coalesce(pg_catalog.jsonb_agg(public.stage1_keeper_redact(item-'bytes',wallet,marker)),'[]'::jsonb) FROM pg_catalog.jsonb_array_elements(a.attempts) item),
 operation=public.stage1_keeper_redact(operation-'addresses'-'lookup_addresses',wallet,marker),
 evidence=public.stage1_keeper_redact(evidence,wallet,marker),
 state=CASE WHEN a.state='ready' THEN 'complete' ELSE a.state END
 WHERE a.id IN (SELECT t->'row_key'->>'id' FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_payout_actions');
 UPDATE public.stage1_keeper_attempts a SET signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker)
 WHERE a.job_id=ANY(jobs)
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_jobs j WHERE j.id=a.job_id AND j.erasure_request_id=r.id);
 UPDATE public.stage1_keeper_reconciliations SET evidence=public.stage1_keeper_redact(evidence,wallet,marker)
 WHERE (id) IN (SELECT (t->'row_key'->>'id')::bigint FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_reconciliations');
 UPDATE public.stage1_keeper_boundaries SET inputs=public.stage1_keeper_redact(inputs,wallet,marker)
 WHERE (scope_id,week) IN (SELECT (t->'row_key'->>'scope_id')::text,(t->'row_key'->>'week')::bigint FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_boundaries');
 UPDATE public.stage1_keeper_measurements SET inputs=public.stage1_keeper_redact(inputs,wallet,marker)
 WHERE (program,hill,week) IN (SELECT (t->'row_key'->>'program')::text,(t->'row_key'->>'hill')::text,(t->'row_key'->>'week')::bigint FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_measurements');
 UPDATE public.stage1_keeper_jobs j SET snapshot=public.stage1_keeper_redact(snapshot,wallet,marker),
 sources=public.stage1_keeper_redact(sources,wallet,marker),allocation=public.stage1_keeper_redact(allocation,wallet,marker),
 claims=public.stage1_keeper_redact(claims,wallet,marker),
 operations=public.stage1_keeper_redact(operations,wallet,marker),
 signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker),
 publications=public.stage1_keeper_redact(publications,wallet,marker),
 funding_publication=public.stage1_keeper_redact(funding_publication,wallet,marker),
 dung_publication=public.stage1_keeper_redact(dung_publication,wallet,marker),
 export_digest=coalesce((SELECT e.redacted_digest FROM public.stage1_keeper_erasure_exports e WHERE e.request_id=r.id AND e.job_id=j.id),j.export_digest),
 export_suspended=false,erasure_request_id=NULL
 WHERE j.erasure_request_id=r.id OR j.id=ANY(jobs);
 UPDATE public.stage1_keeper_proofs SET person=CASE WHEN person=wallet THEN marker ELSE person END,
 leaf=public.stage1_keeper_redact(leaf,wallet,marker) WHERE (job_id,role,leaf_index) IN (SELECT (t->'row_key'->>'job_id')::text,(t->'row_key'->>'role')::smallint,(t->'row_key'->>'leaf_index')::integer FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_proofs');
 UPDATE public.stage1_keeper_alerts SET details=public.stage1_keeper_redact(details,wallet,marker)
 WHERE (id) IN (SELECT (t->'row_key'->>'id')::bigint FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_alerts');
 UPDATE public.stage1_keeper_erasure_exports SET payload=NULL WHERE request_id=r.id;
 FOR marker IN SELECT t->'row_key'->>'id' FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_keeper_payout_actions' LOOP
  PERFORM public.stage1_index_wallet_row('stage1_keeper_payout_actions',pg_catalog.to_jsonb(a)) FROM public.stage1_keeper_payout_actions a WHERE a.id=marker;
 END LOOP;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.br_account_deletion_db_blockers(p_user_id uuid,p_wallet text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE result jsonb; n bigint;
BEGIN
 result := public.br_account_deletion_db_blockers_pre_keeper(p_user_id,p_wallet);
 SELECT count(*) INTO n FROM public.stage1_keeper_proofs
 WHERE (job_id,role,leaf_index) IN (SELECT row_key->>'job_id',(row_key->>'role')::smallint,(row_key->>'leaf_index')::integer FROM public.stage1_wallet_rows WHERE fingerprint=public.br_account_deletion_wallet_fingerprint(p_wallet) AND relation='stage1_keeper_proofs') AND paid_slot IS NULL;
 SELECT n+count(*) INTO n FROM (
  SELECT DISTINCT ON(scope_id) allocation FROM public.stage1_keeper_jobs WHERE state='complete' AND scope_id IN (SELECT scope_id FROM public.stage1_keeper_jobs WHERE id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet))) ORDER BY scope_id,week DESC
 ) latest CROSS JOIN LATERAL pg_catalog.jsonb_each(coalesce(latest.allocation->'reserved','{}')) source
 WHERE coalesce((source.value->>p_wallet)::numeric,0)>0;
 SELECT n+count(*) INTO n FROM public.stage1_keeper_jobs j
 WHERE state <> 'complete' AND id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet));
 SELECT n+count(*) INTO n FROM public.stage1_keeper_jobs j CROSS JOIN LATERAL (
  SELECT value AS record FROM pg_catalog.jsonb_each(j.publications)
  UNION ALL SELECT j.funding_publication UNION ALL SELECT j.dung_publication
 ) retained WHERE j.id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet)) AND retained.record->'account'->>'rent_payer'=p_wallet
 AND coalesce(retained.record->'closed','null'::jsonb)='null'::jsonb;
 IF n>0 THEN result := result || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
  'code','claim_remains','category','claim','count',n,'source','stage1_keeper','action','contact_support')); END IF;
 SELECT count(*) INTO n FROM public.stage1_keeper_jobs j
 WHERE erasure_request_id IS NOT NULL AND erasure_request_id IS DISTINCT FROM
 (SELECT account_deletion_request_id FROM public.users WHERE id=p_user_id)
 AND id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet));
 IF n>0 THEN result := result || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
  'code','policy_review_required','category','policy','count',n,'source','stage1_keeper','action','contact_support')); END IF;
 RETURN result;
END $$;

-- Canonical JSON matches the two boundary implementations, including integers.
CREATE FUNCTION public.stage1_json_canonical(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE result text;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  SELECT '{'||coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(key)::text||':'||public.stage1_json_canonical(value),',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM pg_catalog.jsonb_each(v);
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  SELECT '['||coalesce(pg_catalog.string_agg(public.stage1_json_canonical(value),',' ORDER BY ord),'')||']' INTO result FROM pg_catalog.jsonb_array_elements(v) WITH ORDINALITY a(value,ord);
 ELSE result:=v::text; END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.stage1_json_digest(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS $$
 SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(public.stage1_json_canonical(v),'UTF8')),'hex')
$$;
CREATE FUNCTION public.stage1_indexer_redact(v jsonb,wallet text,marker text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE r record; result jsonb; personal boolean; part jsonb; parts jsonb; path text[]; old jsonb; changed jsonb; account jsonb; accounts jsonb; owners jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  IF v ? 'accounts' AND v ? 'program' THEN
   SELECT coalesce(pg_catalog.jsonb_agg(owner ORDER BY owner COLLATE "C"),'[]') INTO owners FROM
    (SELECT DISTINCT a->'fields'->>'owner' AS owner FROM pg_catalog.jsonb_array_elements(v->'accounts') a WHERE a->>'type'='Stage1PledgeLot') q;
   accounts:='[]';
   FOR account IN SELECT * FROM pg_catalog.jsonb_array_elements(v->'accounts') LOOP
    IF account->>'type'='Stage1PledgeLot' AND NOT account ? 'lot_identity_digest' THEN
     account:=account||pg_catalog.jsonb_build_object('lot_identity_digest',public.stage1_json_digest(pg_catalog.jsonb_build_array('stage1-lot-identity-v1',v->>'program',account->>'address')),
      'lot_source_digest',public.stage1_json_digest(account->'fields'),'lot_owner_rank',(SELECT ord-1 FROM pg_catalog.jsonb_array_elements_text(owners) WITH ORDINALITY a(owner,ord) WHERE owner=account->'fields'->>'owner'));
    END IF;
    accounts:=accounts||pg_catalog.jsonb_build_array(account);
   END LOOP;
   v:=pg_catalog.jsonb_set(v,'{accounts}',accounts);
  END IF;
  -- Freeze only sporting placement and coarse settlement-week provenance.
  -- Precise erased timestamps and binary identity spans are removed below.
  IF v->>'type'='VaultLeaderboard' AND NOT v ? 'record_order' THEN
   IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(v->'fields'->'entries') e WHERE (e->>'timeS')::bigint<=0 OR (e->>'recordedAt')::bigint<=0) THEN RAISE EXCEPTION 'invalid_original_record_provenance'; END IF;
   v:=v||pg_catalog.jsonb_build_object('record_order',(SELECT coalesce(pg_catalog.jsonb_agg(e->'user' ORDER BY (e->>'timeS')::bigint,(e->>'recordedAt')::bigint,(SELECT pg_catalog.decode(p->>'data','base64') FROM pg_catalog.jsonb_array_elements(v->'parts') p WHERE p->'path'=pg_catalog.to_jsonb(ARRAY['entries',(ord-1)::text,'user']))),'[]') FROM pg_catalog.jsonb_array_elements(v->'fields'->'entries') WITH ORDINALITY a(e,ord)),
    'record_not_before',coalesce((SELECT max(1704110400+((e->>'recordedAt')::bigint-1704110400)/604800*604800+604800) FROM pg_catalog.jsonb_array_elements(v->'fields'->'entries') e),0));
  ELSIF v->>'type'='LocalLegend' AND NOT v ? 'record_term' THEN
   v:=v||pg_catalog.jsonb_build_object('record_term',pg_catalog.jsonb_build_array(v->'fields'->'termStartEpoch',v->'fields'->'termEndEpoch'));
  ELSIF v->>'type'='Climb' AND v->'fields'->>'registeredBy'=wallet THEN
   v:=v||pg_catalog.jsonb_build_object('registered_before',1704110400+((v->'fields'->>'registeredAt')::bigint-1704110400)/604800*604800+604800);
  END IF;
  personal:=wallet=ANY(ARRAY[v->>'person',v->>'wallet',v->>'owner',v->>'user',v->>'rider',v->>'holder',v->>'registeredBy']);
  result:='{}';
  FOR r IN SELECT * FROM pg_catalog.jsonb_each(v-'raw'-'parts') LOOP
   IF v->'fields'->>'owner'=wallet AND r.key='address' THEN
    IF v->>'type'='Stage1PledgeLot' AND v ? 'lot_identity_digest' THEN result:=result||pg_catalog.jsonb_build_object('address','anonymous:lot:'||(v->>'lot_identity_digest')); END IF;
    CONTINUE;
   END IF;
   IF personal AND r.key=ANY(ARRAY['recorded_at','recordedAt','completedAt','term_start','term_end','termStartEpoch','termEndEpoch','registeredAt','depositedAt','deposited_at','ridden_at','ridden_at_us','uploaded_at','uploaded_at_us','verified_at','verified_at_us','ride_day_key']) THEN CONTINUE; END IF;
   IF v->>'owner'=wallet AND r.key=ANY(ARRAY['address','depositId','deposit_id','exitRequest','exit_request','pendingRequest','pending_request']) THEN CONTINUE; END IF;
   result:=result||pg_catalog.jsonb_build_object(CASE WHEN r.key=wallet THEN marker ELSE r.key END,public.stage1_indexer_redact(r.value,wallet,marker));
  END LOOP;
  IF v ? 'parts' THEN
   parts:='[]';
   FOR part IN SELECT * FROM pg_catalog.jsonb_array_elements(v->'parts') LOOP
    SELECT pg_catalog.array_agg(x) INTO path FROM pg_catalog.jsonb_array_elements_text(part->'path') x;
    old:=v->'fields'#>path;changed:=result->'fields'#>path;
    IF part->'path'='["$padding"]'::jsonb THEN
     part:=(part-'data')||pg_catalog.jsonb_build_object('discarded',true);
    ELSIF old IS DISTINCT FROM changed THEN
     part:=(part-'data')||pg_catalog.jsonb_build_object('erased',true,'replacement',changed,'missing',changed IS NULL);
    END IF;
    parts:=parts||pg_catalog.jsonb_build_array(part);
   END LOOP;
   result:=result||pg_catalog.jsonb_build_object('parts',parts);
  END IF;
  -- A boundary already carries independently checked frozen erasure inputs.
  IF v ? 'erasure_basis' AND v ? 'source_digest' THEN
   result:=result||pg_catalog.jsonb_build_object('opening',result->'erasure_basis'->'opening',
    'records',(result->'erasure_basis'->'records')-'boundary','redacted',true);
   result:=result||pg_catalog.jsonb_build_object('source_digest',public.stage1_json_digest(result->'source'),'records_digest',public.stage1_json_digest(result->'records'));
   result:=result||pg_catalog.jsonb_build_object('digest',public.stage1_json_digest(result-'digest'));
  END IF;
  RETURN result;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  SELECT coalesce(pg_catalog.jsonb_agg(public.stage1_indexer_redact(value,wallet,marker)),'[]') INTO result FROM pg_catalog.jsonb_array_elements(v);RETURN result;
 ELSIF pg_catalog.jsonb_typeof(v)='string' THEN RETURN pg_catalog.to_jsonb(pg_catalog.replace(v#>>'{}',wallet,marker));
 END IF;
 RETURN v;
END $$;
CREATE TABLE public.stage1_source_redactions (digest text PRIMARY KEY,original_digest text NOT NULL);
REVOKE ALL ON public.stage1_source_redactions FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.stage1_source_redactions TO service_role;
CREATE TABLE public.stage1_boundary_redactions (
 witness_id text NOT NULL, request_id uuid NOT NULL, previous_digest text NOT NULL,current_digest text NOT NULL,
 parts_commitments jsonb NOT NULL, PRIMARY KEY(witness_id,request_id)
);
CREATE TABLE public.stage1_boundary_failures (witness_id text PRIMARY KEY,retry_at timestamptz NOT NULL);
REVOKE ALL ON public.stage1_boundary_failures FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.stage1_boundary_failures TO service_role;
CREATE TABLE public.stage1_boundary_checks (witness_id text NOT NULL, digest text NOT NULL, PRIMARY KEY(witness_id,digest));
REVOKE ALL ON public.stage1_boundary_checks FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.stage1_boundary_checks TO service_role;
REVOKE ALL ON public.stage1_boundary_redactions FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.stage1_boundary_redactions TO service_role;

CREATE FUNCTION public.stage1_account_commitments(v jsonb) RETURNS SETOF jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE item jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  IF v ? 'parts_digest' THEN RETURN NEXT pg_catalog.jsonb_build_object('raw_digest',v->'raw_digest','parts_digest',v->'parts_digest');RETURN; END IF;
  FOR item IN SELECT value FROM pg_catalog.jsonb_each(v) LOOP RETURN QUERY SELECT * FROM public.stage1_account_commitments(item); END LOOP;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  FOR item IN SELECT * FROM pg_catalog.jsonb_array_elements(v) LOOP RETURN QUERY SELECT * FROM public.stage1_account_commitments(item); END LOOP;
 END IF;
END $$;
ALTER TABLE public.stage1_boundary_exports ADD prepared_payload jsonb;
-- Export suspension is durable across filesystem IO, under the producer lock.
ALTER FUNCTION public.stage1_keeper_prepare_erasure(uuid,uuid) RENAME TO stage1_keeper_prepare_erasure_pre_indexer;
CREATE FUNCTION public.stage1_keeper_prepare_erasure(p_request_id uuid,p_lease_token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE result jsonb; wallet text; entries jsonb;
BEGIN
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('stage1_boundaries',0));
 result:=public.stage1_keeper_prepare_erasure_pre_indexer(p_request_id,p_lease_token);
 IF result->'request'<>'null'::jsonb THEN RETURN result; END IF;
 SELECT d.wallet INTO wallet FROM public.deletion_requests d WHERE d.id=p_request_id;
 IF wallet IS NULL THEN RETURN result; END IF;
 IF EXISTS(SELECT 1 FROM public.stage1_boundary_witnesses w WHERE w.digest IN
  (SELECT row_key->>'digest' FROM public.stage1_wallet_rows WHERE relation='stage1_boundary_witnesses' AND fingerprint=public.br_account_deletion_wallet_fingerprint(wallet))
  AND w.witness ? 'erasure_basis' AND NOT EXISTS(SELECT 1 FROM public.stage1_boundary_checks c WHERE c.witness_id=w.digest AND c.digest=w.witness->>'digest')
  AND NOT EXISTS(SELECT 1 FROM public.stage1_boundary_redactions r WHERE r.witness_id=w.digest AND r.current_digest=w.witness->>'digest'))
 THEN RAISE EXCEPTION 'boundary_independent_verification_pending'; END IF;
 UPDATE public.stage1_boundary_exports SET suspended=true,request_id=p_request_id,removed_at=NULL,redacted_digest=NULL,
 prepared_payload=public.stage1_refresh_archive(public.stage1_indexer_redact(payload,wallet,'anonymous:erased:'||p_request_id::text),wallet,'anonymous:erased:'||p_request_id::text)
 WHERE id IN (SELECT row_key->>'id' FROM public.stage1_wallet_rows WHERE relation='stage1_boundary_exports' AND fingerprint=public.br_account_deletion_wallet_fingerprint(wallet));
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('kind','boundary','job_id',id,'path',path,
  'digest',digest,'payload',prepared_payload)),'[]'::jsonb) INTO entries FROM public.stage1_boundary_exports WHERE request_id=p_request_id;
 RETURN result||pg_catalog.jsonb_build_object('exports',(result->'exports')||entries);
END $$;
CREATE FUNCTION public.stage1_boundary_validate_erasure(p_request_id uuid,p_lease_token uuid,p_job_id text,p_digest text,p_payload jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.stage1_boundary_exports e JOIN public.deletion_requests d ON d.id=e.request_id
 WHERE d.id=p_request_id AND d.status='processing' AND d.worker_lease_token=p_lease_token
 AND d.worker_lease_until>pg_catalog.clock_timestamp() AND d.storage_completed_at IS NOT NULL
 AND d.storage_authorized_at IS NOT NULL AND e.id=p_job_id AND e.digest=p_digest AND e.suspended AND e.prepared_payload=p_payload)
 THEN RAISE EXCEPTION 'boundary_erasure_lease_or_manifest_changed'; END IF;
 RETURN true;
END $$;
CREATE FUNCTION public.stage1_boundary_record_erasure(p_request_id uuid,p_lease_token uuid,p_job_id text,p_digest text,p_redacted_digest text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE payload jsonb;
BEGIN
 SELECT prepared_payload INTO payload FROM public.stage1_boundary_exports WHERE id=p_job_id;
 PERFORM public.stage1_boundary_validate_erasure(p_request_id,p_lease_token,p_job_id,p_digest,payload);
 IF p_redacted_digest<>pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(public.stage1_json_canonical(payload)||E'\n','UTF8')),'hex') THEN RAISE EXCEPTION 'boundary_redaction_digest_mismatch'; END IF;
 UPDATE public.stage1_boundary_exports SET removed_at=pg_catalog.clock_timestamp(),redacted_digest=p_redacted_digest WHERE id=p_job_id;
 RETURN true;
END $$;
CREATE FUNCTION public.stage1_refresh_archive(v jsonb,wallet text DEFAULT NULL,marker text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path='' AS $$
DECLARE entry jsonb; result jsonb:='[]'; o jsonb; c jsonb;
BEGIN
 FOR entry IN SELECT * FROM pg_catalog.jsonb_array_elements(v) LOOP
  -- Already imported assets retain their own frozen inputs. Export only the
  -- remaining assets so a redacted retry cannot conflict with an old request.
  IF EXISTS(SELECT 1 FROM public.stage1_keeper_boundaries b WHERE b.scope_id=entry->>'scope_id' AND b.week=(entry->>'week')::bigint) THEN CONTINUE; END IF;
  SELECT witness INTO o FROM public.stage1_boundary_witnesses WHERE digest=entry->'inputs'->'opening'->>'producer_witness';
  SELECT witness INTO c FROM public.stage1_boundary_witnesses WHERE digest=entry->'inputs'->'closing'->>'producer_witness';
  IF o IS NOT NULL AND c IS NOT NULL THEN
   IF wallet IS NOT NULL THEN
    IF EXISTS(SELECT 1 FROM public.stage1_wallet_strings(o) s WHERE pg_catalog.strpos(s,wallet)>0) THEN o:=public.stage1_indexer_redact(o,wallet,marker); END IF;
    IF EXISTS(SELECT 1 FROM public.stage1_wallet_strings(c) s WHERE pg_catalog.strpos(s,wallet)>0) THEN c:=public.stage1_indexer_redact(c,wallet,marker); END IF;
   END IF;
   entry:=pg_catalog.jsonb_set(entry,'{inputs,opening}',o->'opening'||pg_catalog.jsonb_build_object('producer_witness',entry->'inputs'->'opening'->'producer_witness'));
   entry:=pg_catalog.jsonb_set(entry,'{inputs,closing}',c->'records'||pg_catalog.jsonb_build_object('boundary',c->'boundary','slot',c->'slot','commitment','finalized','evidence',c->'source_digest','assets',c->'assets','records_digest',c->'records_digest','producer_witness',entry->'inputs'->'closing'->'producer_witness'));
  END IF;
  result:=result||pg_catalog.jsonb_build_array(entry);
 END LOOP;
 RETURN result;
END $$;
-- Redact exact indexed primary keys. Shared checkpoint rows stay complete;
-- surviving Borsh spans retain their original independent commitments.
CREATE FUNCTION public.stage1_indexer_erase() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE request uuid; wallet text; targets jsonb; target jsonb; predicate text; assignments text; old jsonb; changed jsonb; commitments jsonb; source jsonb;
BEGIN
 IF NEW.account_state<>'anonymized' OR NOT public.stage1_keeper_erasing() THEN RETURN NEW; END IF;
 SELECT request_id INTO request FROM public.stage1_keeper_erasure_sessions WHERE transaction_id=pg_catalog.txid_current();
 SELECT d.wallet INTO wallet FROM public.deletion_requests d WHERE d.id=request;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)),'[]') INTO targets FROM public.stage1_wallet_rows r
 WHERE fingerprint=public.br_account_deletion_wallet_fingerprint(wallet) AND
 (relation LIKE 'indexed_stage1_%' OR relation IN ('stage1_indexer_checkpoints','stage1_indexer_transactions','stage1_boundary_witnesses','stage1_boundary_tasks','stage1_boundary_exports','indexed_events'));
 IF EXISTS(SELECT 1 FROM public.stage1_boundary_exports e WHERE id IN (SELECT t->'row_key'->>'id' FROM pg_catalog.jsonb_array_elements(targets) t WHERE t->>'relation'='stage1_boundary_exports')
  AND (e.request_id IS DISTINCT FROM request OR NOT suspended OR removed_at IS NULL OR redacted_digest IS NULL)) THEN RAISE EXCEPTION 'boundary_exports_not_removed'; END IF;
 -- Sources precede archives, which resolve their refreshed view by stable ID.
 FOR target IN SELECT t FROM pg_catalog.jsonb_array_elements(targets) t ORDER BY CASE t->>'relation' WHEN 'stage1_boundary_witnesses' THEN 0 WHEN 'stage1_boundary_tasks' THEN 2 ELSE 1 END LOOP
  SELECT pg_catalog.string_agg(format('%I=(($1->>%L)::%s)',a.attname,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod)),' AND ')
  INTO predicate FROM pg_catalog.pg_index i CROSS JOIN LATERAL pg_catalog.unnest(i.indkey) k(attnum)
  JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
  WHERE i.indrelid=pg_catalog.to_regclass('public.'||(target->>'relation')) AND i.indisprimary;
  IF target->>'relation'='stage1_boundary_exports' THEN CONTINUE; END IF;
  IF target->>'relation'='stage1_indexer_checkpoints' THEN
   SELECT checkpoint INTO old FROM public.stage1_indexer_checkpoints WHERE digest=target->'row_key'->>'digest';
   IF NOT EXISTS(SELECT 1 FROM public.stage1_source_redactions WHERE digest=public.stage1_json_digest(old)) THEN PERFORM public.stage1_source_pristine(old); END IF;
   changed:=public.stage1_indexer_redact(old,wallet,NEW.wallet);
   INSERT INTO public.stage1_source_redactions VALUES(public.stage1_json_digest(changed),public.stage1_json_digest(old)) ON CONFLICT DO NOTHING;
  END IF;
  IF target->>'relation'='stage1_boundary_witnesses' THEN
   SELECT witness INTO old FROM public.stage1_boundary_witnesses WHERE digest=target->'row_key'->>'digest';
   IF old ? 'erasure_basis' AND NOT coalesce((old->>'redacted')::boolean,false) THEN
    FOR source IN SELECT value FROM pg_catalog.jsonb_each(old->'source') WHERE key IN ('checkpoint','admission') LOOP
     IF NOT EXISTS(SELECT 1 FROM public.stage1_source_redactions WHERE digest=public.stage1_json_digest(source)) THEN PERFORM public.stage1_source_pristine(source); END IF;
    END LOOP;
   END IF;
   changed:=public.stage1_indexer_redact(old,wallet,NEW.wallet);
   SELECT coalesce(pg_catalog.jsonb_agg(x ORDER BY x::text),'[]') INTO commitments FROM public.stage1_account_commitments(old->'source') x;
   INSERT INTO public.stage1_boundary_redactions VALUES(target->'row_key'->>'digest',request,coalesce(old->>'digest',target->'row_key'->>'digest'),coalesce(changed->>'digest',public.stage1_json_digest(changed)),commitments);
  END IF;
  SELECT pg_catalog.string_agg(CASE WHEN a.atttypid='jsonb'::regtype THEN format('%I=public.stage1_indexer_redact(%I,$2,$3)',a.attname,a.attname)
    ELSE format('%I=CASE WHEN %I=$2 THEN $3 ELSE %I END',a.attname,a.attname,a.attname) END,',') INTO assignments
  FROM pg_catalog.pg_attribute a WHERE a.attrelid=pg_catalog.to_regclass('public.'||(target->>'relation')) AND a.attnum>0 AND NOT a.attisdropped
   AND (a.atttypid='jsonb'::regtype OR (a.atttypid='text'::regtype AND a.attname IN ('person','recipient')));
  IF assignments IS NOT NULL THEN EXECUTE format('UPDATE public.%I SET %s WHERE %s',target->>'relation',assignments,predicate) USING target->'row_key',wallet,NEW.wallet; END IF;
  IF target->>'relation'='stage1_boundary_tasks' THEN
   UPDATE public.stage1_boundary_tasks SET archive=public.stage1_refresh_archive(archive),digest=public.stage1_json_digest(public.stage1_refresh_archive(archive))
   WHERE genesis=target->'row_key'->>'genesis' AND program=target->'row_key'->>'program' AND hill=target->'row_key'->>'hill' AND week=(target->'row_key'->>'week')::bigint;
  END IF;
 END LOOP;
 UPDATE public.stage1_boundary_exports SET payload=prepared_payload,prepared_payload=NULL,digest=redacted_digest,suspended=false,request_id=NULL WHERE request_id=request;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_indexer_erase AFTER INSERT ON public.users FOR EACH ROW EXECUTE FUNCTION public.stage1_indexer_erase();
REVOKE ALL ON FUNCTION public.stage1_indexer_network_guard(),public.stage1_indexer_source_guard(),public.stage1_indexer_erase(),
 public.stage1_indexer_projection_fence(),public.stage1_keeper_has_personal_data(text),public.stage1_keeper_personal_jobs(text),
 public.stage1_keeper_prepare_erasure_pre_indexer(uuid,uuid),public.stage1_keeper_prepare_erasure(uuid,uuid),
 public.stage1_indexer_personal_allowed(jsonb),public.stage1_indexer_filter_checkpoint(jsonb),
 public.stage1_boundary_validate_erasure(uuid,uuid,text,text,jsonb),public.stage1_boundary_record_erasure(uuid,uuid,text,text,text),
 public.stage1_wallet_row_trigger(),public.stage1_index_wallet_row(text,jsonb),public.stage1_row_key(text,jsonb),public.stage1_wallet_strings(jsonb),
 public.stage1_json_canonical(jsonb),public.stage1_json_digest(jsonb),public.stage1_indexer_redact(jsonb,text,text),public.stage1_account_commitments(jsonb),public.stage1_refresh_archive(jsonb,text,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.stage1_keeper_prepare_erasure(uuid,uuid),public.stage1_indexer_personal_allowed(jsonb),
 public.stage1_indexer_filter_checkpoint(jsonb),public.stage1_boundary_validate_erasure(uuid,uuid,text,text,jsonb),
 public.stage1_boundary_record_erasure(uuid,uuid,text,text,text),public.stage1_refresh_archive(jsonb,text,text) TO service_role;
ALTER TABLE public.stage1_wallet_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_boundary_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_boundary_redactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_source_redactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_boundary_failures ENABLE ROW LEVEL SECURITY;
COMMIT;
