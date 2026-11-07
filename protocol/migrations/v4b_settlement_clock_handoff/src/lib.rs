#![allow(unexpected_cfgs)]

use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint,
    entrypoint::ProgramResult,
    msg,
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
};

const HANDOFF_INSTRUCTION: u8 = 1;
const V4B_PROGRAM_ID: Pubkey = pubkey!("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH");
const V4B_ADMIN_AUTHORITY: Pubkey = pubkey!("G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH");
const V4B_BACKEND_AUTHORITY: Pubkey = pubkey!("CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha");
const PROGRAM_CONFIG: Pubkey = pubkey!("59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D");
const VAULT_COUNTER: Pubkey = pubkey!("8qcexnhoo8YYfh73yLY54ng9vfpBG8YdJkA1w7E6C3dT");
const CAL_MINT: Pubkey = pubkey!("4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh");
const DUNG_MINT: Pubkey = pubkey!("CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk");
const PROGRAM_CONFIG_DISCRIMINATOR: [u8; 8] = [196, 210, 90, 231, 144, 149, 140, 63];
const VAULT_COUNTER_DISCRIMINATOR: [u8; 8] = [180, 127, 122, 230, 154, 126, 126, 98];
const PROGRAM_CONFIG_SIZE: usize = 334;
const VAULT_COUNTER_SIZE: usize = 17;
const PROGRAM_CONFIG_ADMIN_OFFSET: usize = 8;
const PROGRAM_CONFIG_BACKEND_OFFSET: usize = PROGRAM_CONFIG_ADMIN_OFFSET + 32;
const PROGRAM_CONFIG_VERSION_OFFSET: usize = PROGRAM_CONFIG_BACKEND_OFFSET + 32;
const PROGRAM_CONFIG_INITIALIZED_OFFSET: usize = PROGRAM_CONFIG_VERSION_OFFSET + 1;
const PROGRAM_CONFIG_CAL_MINT_OFFSET: usize = PROGRAM_CONFIG_INITIALIZED_OFFSET + 2;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET: usize = PROGRAM_CONFIG_CAL_MINT_OFFSET + 32;
const PROGRAM_CONFIG_CLOCK_OFFSET: usize = 325;
const PROGRAM_CONFIG_CLOCK_VERSION_OFFSET: usize = PROGRAM_CONFIG_CLOCK_OFFSET + 8;
const VAULT_COUNTER_COUNT_OFFSET: usize = 8;
const V4B_PROGRAM_VERSION: u8 = 0x4B;
const SETTLEMENT_CLOCK_VERSION_V2: u8 = 2;
const FRESH_V2_ONLY_ANCHOR: i64 = 1_704_110_400;
const RATIFIED_PRODUCTION_CUTOVER: i64 = 1_784_548_800;

#[repr(u32)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HandoffError {
    InvalidExecutingProgram = 0,
    InvalidAdmin = 1,
    InvalidProgramConfig = 2,
    InvalidVaultCounter = 3,
    EconomicStateExists = 4,
    InvalidSettlementClock = 5,
    AccountNotWritable = 6,
    UnexpectedAccounts = 7,
}

impl From<HandoffError> for ProgramError {
    fn from(value: HandoffError) -> Self {
        ProgramError::Custom(value as u32)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HandoffOutcome {
    Write,
    AlreadyApplied,
}

#[derive(Clone, Copy)]
struct HandoffPlan {
    executing_program: Pubkey,
    admin: Pubkey,
    admin_is_signer: bool,
    program_config_key: Pubkey,
    program_config_owner: Pubkey,
    program_config_writable: bool,
    program_config_discriminator: [u8; 8],
    program_config_admin: Pubkey,
    program_config_backend: Pubkey,
    program_version: u8,
    initialized: bool,
    cal_mint: Pubkey,
    dung_mint: Pubkey,
    settlement_clock_v2_starts_at: i64,
    settlement_clock_version: u8,
    vault_counter_key: Pubkey,
    vault_counter_owner: Pubkey,
    vault_counter_discriminator: [u8; 8],
    vault_count: u64,
}

fn validate_handoff_plan(plan: HandoffPlan) -> Result<HandoffOutcome, ProgramError> {
    if plan.executing_program != V4B_PROGRAM_ID {
        return Err(HandoffError::InvalidExecutingProgram.into());
    }
    if !plan.admin_is_signer || plan.admin != V4B_ADMIN_AUTHORITY {
        return Err(HandoffError::InvalidAdmin.into());
    }
    if !plan.program_config_writable {
        return Err(HandoffError::AccountNotWritable.into());
    }
    if plan.program_config_key != PROGRAM_CONFIG
        || plan.program_config_owner != V4B_PROGRAM_ID
        || plan.program_config_discriminator != PROGRAM_CONFIG_DISCRIMINATOR
        || plan.program_config_admin != V4B_ADMIN_AUTHORITY
        || plan.program_config_backend != V4B_BACKEND_AUTHORITY
        || plan.program_version != V4B_PROGRAM_VERSION
        || !plan.initialized
        || plan.cal_mint != CAL_MINT
        || plan.dung_mint != DUNG_MINT
    {
        return Err(HandoffError::InvalidProgramConfig.into());
    }
    if plan.vault_counter_key != VAULT_COUNTER
        || plan.vault_counter_owner != V4B_PROGRAM_ID
        || plan.vault_counter_discriminator != VAULT_COUNTER_DISCRIMINATOR
    {
        return Err(HandoffError::InvalidVaultCounter.into());
    }
    if plan.vault_count != 0 {
        return Err(HandoffError::EconomicStateExists.into());
    }
    if plan.settlement_clock_version != SETTLEMENT_CLOCK_VERSION_V2 {
        return Err(HandoffError::InvalidSettlementClock.into());
    }
    match plan.settlement_clock_v2_starts_at {
        FRESH_V2_ONLY_ANCHOR => Ok(HandoffOutcome::Write),
        RATIFIED_PRODUCTION_CUTOVER => Ok(HandoffOutcome::AlreadyApplied),
        _ => Err(HandoffError::InvalidSettlementClock.into()),
    }
}

fn read_pubkey(data: &[u8], start: usize) -> Result<Pubkey, ProgramError> {
    let end = start
        .checked_add(32)
        .ok_or(HandoffError::InvalidProgramConfig)?;
    let bytes: [u8; 32] = data
        .get(start..end)
        .ok_or(HandoffError::InvalidProgramConfig)?
        .try_into()
        .map_err(|_| HandoffError::InvalidProgramConfig)?;
    Ok(Pubkey::new_from_array(bytes))
}

fn read_program_config_plan(
    program_id: &Pubkey,
    admin: &AccountInfo<'_>,
    program_config: &AccountInfo<'_>,
    vault_counter: &AccountInfo<'_>,
) -> Result<HandoffPlan, ProgramError> {
    let config_data = program_config.try_borrow_data()?;
    if config_data.len() != PROGRAM_CONFIG_SIZE {
        return Err(HandoffError::InvalidProgramConfig.into());
    }
    let counter_data = vault_counter.try_borrow_data()?;
    if counter_data.len() != VAULT_COUNTER_SIZE {
        return Err(HandoffError::InvalidVaultCounter.into());
    }

    let program_config_discriminator = config_data[..8]
        .try_into()
        .map_err(|_| HandoffError::InvalidProgramConfig)?;
    let vault_counter_discriminator = counter_data[..8]
        .try_into()
        .map_err(|_| HandoffError::InvalidVaultCounter)?;
    let settlement_clock_v2_starts_at = i64::from_le_bytes(
        config_data[PROGRAM_CONFIG_CLOCK_OFFSET..PROGRAM_CONFIG_CLOCK_VERSION_OFFSET]
            .try_into()
            .map_err(|_| HandoffError::InvalidSettlementClock)?,
    );
    let vault_count = u64::from_le_bytes(
        counter_data[VAULT_COUNTER_COUNT_OFFSET..VAULT_COUNTER_COUNT_OFFSET + 8]
            .try_into()
            .map_err(|_| HandoffError::InvalidVaultCounter)?,
    );

    Ok(HandoffPlan {
        executing_program: *program_id,
        admin: *admin.key,
        admin_is_signer: admin.is_signer,
        program_config_key: *program_config.key,
        program_config_owner: *program_config.owner,
        program_config_writable: program_config.is_writable,
        program_config_discriminator,
        program_config_admin: read_pubkey(&config_data, PROGRAM_CONFIG_ADMIN_OFFSET)?,
        program_config_backend: read_pubkey(&config_data, PROGRAM_CONFIG_BACKEND_OFFSET)?,
        program_version: config_data[PROGRAM_CONFIG_VERSION_OFFSET],
        initialized: config_data[PROGRAM_CONFIG_INITIALIZED_OFFSET] == 1,
        cal_mint: read_pubkey(&config_data, PROGRAM_CONFIG_CAL_MINT_OFFSET)?,
        dung_mint: read_pubkey(&config_data, PROGRAM_CONFIG_DUNG_MINT_OFFSET)?,
        settlement_clock_v2_starts_at,
        settlement_clock_version: config_data[PROGRAM_CONFIG_CLOCK_VERSION_OFFSET],
        vault_counter_key: *vault_counter.key,
        vault_counter_owner: *vault_counter.owner,
        vault_counter_discriminator,
        vault_count,
    })
}

entrypoint!(process_instruction);

pub fn process_instruction(
    program_id: &Pubkey,
    accounts: &[AccountInfo<'_>],
    instruction_data: &[u8],
) -> ProgramResult {
    if instruction_data != [HANDOFF_INSTRUCTION] {
        return Err(ProgramError::InvalidInstructionData);
    }

    let mut accounts_iter = accounts.iter();
    let admin = next_account_info(&mut accounts_iter)?;
    let program_config = next_account_info(&mut accounts_iter)?;
    let vault_counter = next_account_info(&mut accounts_iter)?;
    if accounts_iter.next().is_some() {
        return Err(HandoffError::UnexpectedAccounts.into());
    }

    let outcome = validate_handoff_plan(read_program_config_plan(
        program_id,
        admin,
        program_config,
        vault_counter,
    )?)?;
    if outcome == HandoffOutcome::Write {
        let mut config_data = program_config.try_borrow_mut_data()?;
        config_data[PROGRAM_CONFIG_CLOCK_OFFSET..PROGRAM_CONFIG_CLOCK_VERSION_OFFSET]
            .copy_from_slice(&RATIFIED_PRODUCTION_CUTOVER.to_le_bytes());
    }

    msg!(
        "V4-B settlement clock lineage handoff complete: cutover={} idempotent={}",
        RATIFIED_PRODUCTION_CUTOVER,
        outcome == HandoffOutcome::AlreadyApplied
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_plan() -> HandoffPlan {
        HandoffPlan {
            executing_program: V4B_PROGRAM_ID,
            admin: V4B_ADMIN_AUTHORITY,
            admin_is_signer: true,
            program_config_key: PROGRAM_CONFIG,
            program_config_owner: V4B_PROGRAM_ID,
            program_config_writable: true,
            program_config_discriminator: PROGRAM_CONFIG_DISCRIMINATOR,
            program_config_admin: V4B_ADMIN_AUTHORITY,
            program_config_backend: V4B_BACKEND_AUTHORITY,
            program_version: V4B_PROGRAM_VERSION,
            initialized: true,
            cal_mint: CAL_MINT,
            dung_mint: DUNG_MINT,
            settlement_clock_v2_starts_at: FRESH_V2_ONLY_ANCHOR,
            settlement_clock_version: SETTLEMENT_CLOCK_VERSION_V2,
            vault_counter_key: VAULT_COUNTER,
            vault_counter_owner: V4B_PROGRAM_ID,
            vault_counter_discriminator: VAULT_COUNTER_DISCRIMINATOR,
            vault_count: 0,
        }
    }

    #[test]
    fn exact_fresh_lineage_is_writable() {
        assert_eq!(
            validate_handoff_plan(valid_plan()).unwrap(),
            HandoffOutcome::Write
        );
    }

    #[test]
    fn exact_ratified_lineage_is_idempotent() {
        let mut plan = valid_plan();
        plan.settlement_clock_v2_starts_at = RATIFIED_PRODUCTION_CUTOVER;
        assert_eq!(
            validate_handoff_plan(plan).unwrap(),
            HandoffOutcome::AlreadyApplied
        );
    }

    #[test]
    fn existing_vault_ids_fail_closed() {
        let mut plan = valid_plan();
        plan.vault_count = 1;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::EconomicStateExists.into())
        );
    }

    #[test]
    fn alternate_clock_fails_closed() {
        let mut plan = valid_plan();
        plan.settlement_clock_v2_starts_at = RATIFIED_PRODUCTION_CUTOVER + 604_800;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidSettlementClock.into())
        );
    }

    #[test]
    fn wrong_program_or_admin_fails_closed() {
        let mut plan = valid_plan();
        plan.executing_program = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidExecutingProgram.into())
        );

        let mut plan = valid_plan();
        plan.admin_is_signer = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidAdmin.into())
        );
    }

    #[test]
    fn mismatched_runtime_identity_fails_closed() {
        let mut plan = valid_plan();
        plan.program_config_backend = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidProgramConfig.into())
        );

        let mut plan = valid_plan();
        plan.vault_counter_key = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidVaultCounter.into())
        );
    }
}
