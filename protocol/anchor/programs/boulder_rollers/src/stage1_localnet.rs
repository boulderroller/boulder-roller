//! Compiled only under stage1-localnet. No test discriminators or setter in
//! the default dispatch. Anchor's normal account validation and exit hooks run.
//! Unmatched discriminators fall through to the localnet-only test setup
//! helpers in smoke_helpers.rs.
use super::*;
use std::collections::BTreeSet;

#[derive(AnchorDeserialize)]
struct RateArgs {
    n: u64,
    d: u64,
    observed_at: i64,
}
pub fn dispatch<'info>(
    program_id: &Pubkey,
    accounts: &'info [AccountInfo<'info>],
    data: &[u8],
) -> Result<()> {
    if data.len() < 8 {
        return Err(anchor_lang::error::ErrorCode::InstructionMissing.into());
    }
    // Also serves as an auditable artifact guard. The independent program ID
    // prevents this binary from executing under the deployable program ID.
    msg!("BOULDERROLLER_STAGE1_LOCALNET_ONLY");
    macro_rules! invoke {
        ($accounts:ty, $handler:expr) => {{
            let mut remaining = accounts;
            let mut bumps = <$accounts as anchor_lang::Bumps>::Bumps::default();
            let mut reallocs = BTreeSet::new();
            let mut validated = <$accounts>::try_accounts(
                program_id,
                &mut remaining,
                &data[8..],
                &mut bumps,
                &mut reallocs,
            )?;
            let ctx = Context::new(program_id, &mut validated, remaining, bumps);
            $handler(ctx)?;
            validated.exit(program_id)
        }};
    }
    let discriminator =
        |name: &str| anchor_lang::solana_program::hash::hash(name.as_bytes()).to_bytes();
    if data[..8] == discriminator("global:set_test_lst_rate")[..8] {
        let args = RateArgs::deserialize(&mut &data[8..])?;
        invoke!(Stage1TestRate<'info>, |ctx| stage1::test_rate(
            ctx,
            args.n,
            args.d,
            args.observed_at
        ))
    } else {
        crate::smoke_helpers::dispatch(program_id, accounts, data)
    }
}
