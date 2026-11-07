// Localnet-only IDL fragment. scripts/build-stage1-localnet.py splices these
// wrappers into an isolated source copy before Anchor parses the localnet IDL;
// the localnet binary itself reaches the handlers through its fallback.
    /// Test setup only: rewind a pristine vault's open settlement week.
    pub fn admin_override_open_settlement_week(
        ctx: Context<AdminOverrideOpenSettlementWeek>,
        settlement_week: u64,
    ) -> Result<()> {
        smoke_helpers::admin_override_open_settlement_week(ctx, settlement_week)
    }
    /// Test setup only: seed a pristine vault's open week with pending rewards.
    pub fn admin_seed_pending_rewards(
        ctx: Context<AdminSeedPendingRewards>,
        settlement_week: u64,
        pending_rewards: u64,
    ) -> Result<()> {
        smoke_helpers::admin_seed_pending_rewards(ctx, settlement_week, pending_rewards)
    }
    /// Test setup only: make a fresh stake eligible from a rewound week.
    pub fn admin_override_stake_eligibility(
        ctx: Context<AdminOverrideStakeEligibility>,
        eligible_from_epoch: u64,
    ) -> Result<()> {
        smoke_helpers::admin_override_stake_eligibility(ctx, eligible_from_epoch)
    }
