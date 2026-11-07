#![allow(unexpected_cfgs)]

use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint,
    entrypoint::ProgramResult,
    msg,
    program::invoke_signed,
    program_error::ProgramError,
    program_option::COption,
    program_pack::Pack,
    pubkey,
    pubkey::Pubkey,
};
use spl_token::{instruction::AuthorityType, state::Mint};

const HANDOFF_INSTRUCTION: u8 = 1;
const V4A_PROGRAM_ID: Pubkey = pubkey!("HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst");
const V4A_ADMIN_AUTHORITY: Pubkey = pubkey!("G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH");
const V4B_BACKEND_AUTHORITY: Pubkey = pubkey!("CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha");
const CAL_MINT: Pubkey = pubkey!("4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh");
const DUNG_MINT: Pubkey = pubkey!("CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk");
const CAL_MINT_AUTH_SEED: &[u8] = b"cal_mint_auth";
const DUNG_MINT_AUTH_SEED: &[u8] = b"dung_mint_auth";
const PROGRAM_CONFIG_SEED: &[u8] = b"program_config";
const V4B_PROGRAM_VERSION: u8 = 0x4B;
const PROGRAM_CONFIG_DISCRIMINATOR: [u8; 8] = [196, 210, 90, 231, 144, 149, 140, 63];
const PROGRAM_CONFIG_ADMIN_OFFSET: usize = 8;
const PROGRAM_CONFIG_BACKEND_OFFSET: usize = PROGRAM_CONFIG_ADMIN_OFFSET + 32;
const PROGRAM_CONFIG_VERSION_OFFSET: usize = PROGRAM_CONFIG_BACKEND_OFFSET + 32;
const PROGRAM_CONFIG_INITIALIZED_OFFSET: usize = PROGRAM_CONFIG_VERSION_OFFSET + 1;
const PROGRAM_CONFIG_CAL_MINT_OFFSET: usize = PROGRAM_CONFIG_INITIALIZED_OFFSET + 2;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET: usize = PROGRAM_CONFIG_CAL_MINT_OFFSET + 32;
const PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET: usize = PROGRAM_CONFIG_DUNG_MINT_OFFSET + 32;
const PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET: usize =
    PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET + 1;
const PROGRAM_CONFIG_MIN_LEN: usize = PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET + 1;

#[repr(u32)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HandoffError {
    InvalidExecutingProgram = 0,
    InvalidAdmin = 1,
    InvalidMint = 2,
    InvalidCurrentAuthority = 3,
    InvalidTargetProgram = 4,
    InvalidTargetProgramConfig = 5,
    InvalidTokenProgram = 6,
    AccountNotWritable = 7,
    UnexpectedAccounts = 8,
}

impl From<HandoffError> for ProgramError {
    fn from(value: HandoffError) -> Self {
        ProgramError::Custom(value as u32)
    }
}

#[derive(Clone, Copy)]
struct HandoffPlan {
    executing_program: Pubkey,
    admin: Pubkey,
    admin_is_signer: bool,
    cal_mint: Pubkey,
    cal_mint_writable: bool,
    cal_authority_account: Pubkey,
    cal_mint_authority: Option<Pubkey>,
    dung_mint: Pubkey,
    dung_mint_writable: bool,
    dung_authority_account: Pubkey,
    dung_mint_authority: Option<Pubkey>,
    target_program: Pubkey,
    target_program_executable: bool,
    target_program_config: Pubkey,
    target_program_config_owner: Pubkey,
    target_program_config_data_len: usize,
    target_program_config_discriminator: [u8; 8],
    target_program_config_admin: Pubkey,
    target_program_config_backend: Pubkey,
    target_program_config_version: u8,
    target_program_config_initialized: bool,
    target_program_config_cal_mint: Pubkey,
    target_program_config_dung_mint: Pubkey,
    target_program_config_cal_mint_auth_bump: u8,
    target_program_config_dung_mint_auth_bump: u8,
    token_program: Pubkey,
    token_program_executable: bool,
}

#[derive(Clone, Copy)]
struct TargetProgramConfigSnapshot {
    discriminator: [u8; 8],
    admin: Pubkey,
    backend: Pubkey,
    version: u8,
    initialized: bool,
    cal_mint: Pubkey,
    dung_mint: Pubkey,
    cal_mint_auth_bump: u8,
    dung_mint_auth_bump: u8,
}

#[derive(Debug, Eq, PartialEq)]
struct TargetAuthorities {
    old_cal_authority: Pubkey,
    old_dung_authority: Pubkey,
    new_cal_authority: Pubkey,
    new_dung_authority: Pubkey,
}

fn validate_handoff_plan(plan: HandoffPlan) -> Result<TargetAuthorities, ProgramError> {
    if plan.executing_program != V4A_PROGRAM_ID {
        return Err(HandoffError::InvalidExecutingProgram.into());
    }
    if !plan.admin_is_signer || plan.admin != V4A_ADMIN_AUTHORITY {
        return Err(HandoffError::InvalidAdmin.into());
    }
    if plan.cal_mint != CAL_MINT || plan.dung_mint != DUNG_MINT {
        return Err(HandoffError::InvalidMint.into());
    }
    if !plan.cal_mint_writable || !plan.dung_mint_writable {
        return Err(HandoffError::AccountNotWritable.into());
    }
    if plan.token_program != spl_token::id() || !plan.token_program_executable {
        return Err(HandoffError::InvalidTokenProgram.into());
    }
    if plan.target_program == V4A_PROGRAM_ID || !plan.target_program_executable {
        return Err(HandoffError::InvalidTargetProgram.into());
    }

    let (expected_target_config, _) =
        Pubkey::find_program_address(&[PROGRAM_CONFIG_SEED], &plan.target_program);
    let (new_cal_authority, new_cal_bump) =
        Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &plan.target_program);
    let (new_dung_authority, new_dung_bump) =
        Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &plan.target_program);
    if plan.target_program_config != expected_target_config
        || plan.target_program_config_owner != plan.target_program
        || plan.target_program_config_data_len < PROGRAM_CONFIG_MIN_LEN
        || plan.target_program_config_discriminator != PROGRAM_CONFIG_DISCRIMINATOR
        || plan.target_program_config_admin != V4A_ADMIN_AUTHORITY
        || plan.target_program_config_backend != V4B_BACKEND_AUTHORITY
        || plan.target_program_config_version != V4B_PROGRAM_VERSION
        || !plan.target_program_config_initialized
        || plan.target_program_config_cal_mint != CAL_MINT
        || plan.target_program_config_dung_mint != DUNG_MINT
        || plan.target_program_config_cal_mint_auth_bump != new_cal_bump
        || plan.target_program_config_dung_mint_auth_bump != new_dung_bump
    {
        return Err(HandoffError::InvalidTargetProgramConfig.into());
    }

    let (old_cal_authority, _) =
        Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
    let (old_dung_authority, _) =
        Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
    if plan.cal_authority_account != old_cal_authority
        || plan.dung_authority_account != old_dung_authority
        || plan.cal_mint_authority != Some(old_cal_authority)
        || plan.dung_mint_authority != Some(old_dung_authority)
    {
        return Err(HandoffError::InvalidCurrentAuthority.into());
    }

    Ok(TargetAuthorities {
        old_cal_authority,
        old_dung_authority,
        new_cal_authority,
        new_dung_authority,
    })
}

fn target_program_config_snapshot(
    account: &AccountInfo<'_>,
) -> Result<TargetProgramConfigSnapshot, ProgramError> {
    let data = account.try_borrow_data()?;
    if data.len() < PROGRAM_CONFIG_MIN_LEN {
        return Err(HandoffError::InvalidTargetProgramConfig.into());
    }
    let discriminator = data[..8]
        .try_into()
        .map_err(|_| HandoffError::InvalidTargetProgramConfig)?;
    let admin = Pubkey::new_from_array(
        data[PROGRAM_CONFIG_ADMIN_OFFSET..PROGRAM_CONFIG_BACKEND_OFFSET]
            .try_into()
            .map_err(|_| HandoffError::InvalidTargetProgramConfig)?,
    );
    let backend = Pubkey::new_from_array(
        data[PROGRAM_CONFIG_BACKEND_OFFSET..PROGRAM_CONFIG_VERSION_OFFSET]
            .try_into()
            .map_err(|_| HandoffError::InvalidTargetProgramConfig)?,
    );
    let cal_mint = Pubkey::new_from_array(
        data[PROGRAM_CONFIG_CAL_MINT_OFFSET..PROGRAM_CONFIG_DUNG_MINT_OFFSET]
            .try_into()
            .map_err(|_| HandoffError::InvalidTargetProgramConfig)?,
    );
    let dung_mint = Pubkey::new_from_array(
        data[PROGRAM_CONFIG_DUNG_MINT_OFFSET..PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET]
            .try_into()
            .map_err(|_| HandoffError::InvalidTargetProgramConfig)?,
    );
    Ok(TargetProgramConfigSnapshot {
        discriminator,
        admin,
        backend,
        version: data[PROGRAM_CONFIG_VERSION_OFFSET],
        initialized: data[PROGRAM_CONFIG_INITIALIZED_OFFSET] == 1,
        cal_mint,
        dung_mint,
        cal_mint_auth_bump: data[PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET],
        dung_mint_auth_bump: data[PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET],
    })
}

fn mint_authority(account: &AccountInfo<'_>) -> Result<Option<Pubkey>, ProgramError> {
    if account.owner != &spl_token::id() {
        return Err(HandoffError::InvalidTokenProgram.into());
    }
    let mint = Mint::unpack(&account.try_borrow_data()?)?;
    Ok(match mint.mint_authority {
        COption::Some(authority) => Some(authority),
        COption::None => None,
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
    let cal_mint = next_account_info(&mut accounts_iter)?;
    let dung_mint = next_account_info(&mut accounts_iter)?;
    let cal_authority = next_account_info(&mut accounts_iter)?;
    let dung_authority = next_account_info(&mut accounts_iter)?;
    let target_program = next_account_info(&mut accounts_iter)?;
    let target_program_config = next_account_info(&mut accounts_iter)?;
    let token_program = next_account_info(&mut accounts_iter)?;
    if accounts_iter.next().is_some() {
        return Err(HandoffError::UnexpectedAccounts.into());
    }

    let target_config = target_program_config_snapshot(target_program_config)?;
    let targets = validate_handoff_plan(HandoffPlan {
        executing_program: *program_id,
        admin: *admin.key,
        admin_is_signer: admin.is_signer,
        cal_mint: *cal_mint.key,
        cal_mint_writable: cal_mint.is_writable,
        cal_authority_account: *cal_authority.key,
        cal_mint_authority: mint_authority(cal_mint)?,
        dung_mint: *dung_mint.key,
        dung_mint_writable: dung_mint.is_writable,
        dung_authority_account: *dung_authority.key,
        dung_mint_authority: mint_authority(dung_mint)?,
        target_program: *target_program.key,
        target_program_executable: target_program.executable,
        target_program_config: *target_program_config.key,
        target_program_config_owner: *target_program_config.owner,
        target_program_config_data_len: target_program_config.data_len(),
        target_program_config_discriminator: target_config.discriminator,
        target_program_config_admin: target_config.admin,
        target_program_config_backend: target_config.backend,
        target_program_config_version: target_config.version,
        target_program_config_initialized: target_config.initialized,
        target_program_config_cal_mint: target_config.cal_mint,
        target_program_config_dung_mint: target_config.dung_mint,
        target_program_config_cal_mint_auth_bump: target_config.cal_mint_auth_bump,
        target_program_config_dung_mint_auth_bump: target_config.dung_mint_auth_bump,
        token_program: *token_program.key,
        token_program_executable: token_program.executable,
    })?;

    let (_, cal_bump) = Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
    let cal_instruction = spl_token::instruction::set_authority(
        token_program.key,
        cal_mint.key,
        Some(&targets.new_cal_authority),
        AuthorityType::MintTokens,
        cal_authority.key,
        &[],
    )?;
    invoke_signed(
        &cal_instruction,
        &[
            cal_mint.clone(),
            cal_authority.clone(),
            token_program.clone(),
        ],
        &[&[CAL_MINT_AUTH_SEED, &[cal_bump]]],
    )?;

    let (_, dung_bump) = Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
    let dung_instruction = spl_token::instruction::set_authority(
        token_program.key,
        dung_mint.key,
        Some(&targets.new_dung_authority),
        AuthorityType::MintTokens,
        dung_authority.key,
        &[],
    )?;
    invoke_signed(
        &dung_instruction,
        &[
            dung_mint.clone(),
            dung_authority.clone(),
            token_program.clone(),
        ],
        &[&[DUNG_MINT_AUTH_SEED, &[dung_bump]]],
    )?;

    msg!(
        "V4-A mint authority handoff complete: target_program={} cal_authority={} dung_authority={}",
        target_program.key,
        targets.new_cal_authority,
        targets.new_dung_authority
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use solana_program::{
        instruction::Instruction,
        program_stubs::{set_syscall_stubs, SyscallStubs},
        system_program,
    };
    use spl_token::instruction::TokenInstruction;
    use std::sync::{Arc, Mutex};

    fn exact_plan(target_program: Pubkey) -> HandoffPlan {
        let (old_cal_authority, _) =
            Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
        let (old_dung_authority, _) =
            Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
        let (target_program_config, _) =
            Pubkey::find_program_address(&[PROGRAM_CONFIG_SEED], &target_program);
        let (_, target_cal_mint_auth_bump) =
            Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &target_program);
        let (_, target_dung_mint_auth_bump) =
            Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &target_program);
        HandoffPlan {
            executing_program: V4A_PROGRAM_ID,
            admin: V4A_ADMIN_AUTHORITY,
            admin_is_signer: true,
            cal_mint: CAL_MINT,
            cal_mint_writable: true,
            cal_authority_account: old_cal_authority,
            cal_mint_authority: Some(old_cal_authority),
            dung_mint: DUNG_MINT,
            dung_mint_writable: true,
            dung_authority_account: old_dung_authority,
            dung_mint_authority: Some(old_dung_authority),
            target_program,
            target_program_executable: true,
            target_program_config,
            target_program_config_owner: target_program,
            target_program_config_data_len: PROGRAM_CONFIG_MIN_LEN,
            target_program_config_discriminator: PROGRAM_CONFIG_DISCRIMINATOR,
            target_program_config_admin: V4A_ADMIN_AUTHORITY,
            target_program_config_backend: V4B_BACKEND_AUTHORITY,
            target_program_config_version: V4B_PROGRAM_VERSION,
            target_program_config_initialized: true,
            target_program_config_cal_mint: CAL_MINT,
            target_program_config_dung_mint: DUNG_MINT,
            target_program_config_cal_mint_auth_bump: target_cal_mint_auth_bump,
            target_program_config_dung_mint_auth_bump: target_dung_mint_auth_bump,
            token_program: spl_token::id(),
            token_program_executable: true,
        }
    }

    #[test]
    fn exact_live_v4a_authorities_can_target_one_initialized_v4b_program() {
        let target_program = Pubkey::new_unique();
        let targets = validate_handoff_plan(exact_plan(target_program)).unwrap();

        assert_eq!(
            targets.new_cal_authority,
            Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &target_program).0
        );
        assert_eq!(
            targets.new_dung_authority,
            Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &target_program).0
        );
        assert_ne!(targets.old_cal_authority, targets.new_cal_authority);
        assert_ne!(targets.old_dung_authority, targets.new_dung_authority);
    }

    #[test]
    fn wrong_or_unsigned_admin_is_rejected() {
        let target_program = Pubkey::new_unique();
        let mut plan = exact_plan(target_program);
        plan.admin = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidAdmin.into())
        );

        let mut plan = exact_plan(target_program);
        plan.admin_is_signer = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidAdmin.into())
        );
    }

    #[test]
    fn exact_live_mints_and_current_pda_authorities_are_required() {
        let target_program = Pubkey::new_unique();
        let mut plan = exact_plan(target_program);
        plan.cal_mint = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidMint.into())
        );

        let mut plan = exact_plan(target_program);
        plan.dung_mint_authority = Some(Pubkey::new_unique());
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidCurrentAuthority.into())
        );
    }

    #[test]
    fn target_must_be_a_distinct_executable_with_its_initialized_config_pda() {
        let target_program = Pubkey::new_unique();
        let mut plan = exact_plan(target_program);
        plan.target_program_executable = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgram.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_data_len = 0;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );
    }

    #[test]
    fn target_config_must_be_initialized_v4b_and_bound_to_exact_live_mints() {
        let target_program = Pubkey::new_unique();
        let mut plan = exact_plan(target_program);
        plan.target_program_config_admin = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_backend = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_version = 0x4A;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_initialized = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_cal_mint = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_dung_mint = Pubkey::new_unique();
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_cal_mint_auth_bump ^= 1;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );

        let mut plan = exact_plan(target_program);
        plan.target_program_config_discriminator = [0; 8];
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTargetProgramConfig.into())
        );
    }

    #[test]
    fn spl_token_program_and_writable_mints_are_required() {
        let target_program = Pubkey::new_unique();
        let mut plan = exact_plan(target_program);
        plan.token_program_executable = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::InvalidTokenProgram.into())
        );

        let mut plan = exact_plan(target_program);
        plan.cal_mint_writable = false;
        assert_eq!(
            validate_handoff_plan(plan),
            Err(HandoffError::AccountNotWritable.into())
        );
    }

    struct TokenSetAuthorityStub {
        calls: Arc<Mutex<Vec<Pubkey>>>,
    }

    impl SyscallStubs for TokenSetAuthorityStub {
        fn sol_invoke_signed(
            &self,
            instruction: &Instruction,
            account_infos: &[AccountInfo<'_>],
            signers_seeds: &[&[&[u8]]],
        ) -> ProgramResult {
            assert_eq!(instruction.program_id, spl_token::id());
            assert_eq!(account_infos.len(), 3);
            assert_eq!(instruction.accounts.len(), 2);
            assert_eq!(instruction.accounts[0].pubkey, *account_infos[0].key);
            assert_eq!(instruction.accounts[1].pubkey, *account_infos[1].key);
            assert!(instruction.accounts[1].is_signer);
            assert_eq!(signers_seeds.len(), 1);
            assert_eq!(
                Pubkey::create_program_address(signers_seeds[0], &V4A_PROGRAM_ID).unwrap(),
                *account_infos[1].key
            );

            let TokenInstruction::SetAuthority {
                authority_type,
                new_authority,
            } = TokenInstruction::unpack(&instruction.data).unwrap()
            else {
                panic!("expected SetAuthority CPI");
            };
            assert_eq!(authority_type, AuthorityType::MintTokens);
            let mut data = account_infos[0].try_borrow_mut_data().unwrap();
            let mut mint = Mint::unpack(&data).unwrap();
            mint.mint_authority = new_authority;
            Mint::pack(mint, &mut data).unwrap();
            self.calls.lock().unwrap().push(*account_infos[0].key);
            Ok(())
        }
    }

    struct StubGuard(Option<Box<dyn SyscallStubs>>);

    impl Drop for StubGuard {
        fn drop(&mut self) {
            if let Some(previous) = self.0.take() {
                set_syscall_stubs(previous);
            }
        }
    }

    #[test]
    fn instruction_cpis_both_exact_mints_to_the_target_program_pdas() {
        let target_program = Pubkey::new_unique();
        let (target_program_config, _) =
            Pubkey::find_program_address(&[PROGRAM_CONFIG_SEED], &target_program);
        let (old_cal_authority, _) =
            Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
        let (old_dung_authority, _) =
            Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &V4A_PROGRAM_ID);
        let (new_cal_authority, new_cal_bump) =
            Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], &target_program);
        let (new_dung_authority, new_dung_bump) =
            Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], &target_program);

        let mut admin_lamports = 1;
        let mut admin_data = [];
        let mut cal_lamports = 1;
        let mut cal_data = vec![0; Mint::LEN];
        let mut dung_lamports = 1;
        let mut dung_data = vec![0; Mint::LEN];
        let mut cal_authority_lamports = 0;
        let mut cal_authority_data = [];
        let mut dung_authority_lamports = 0;
        let mut dung_authority_data = [];
        let mut target_program_lamports = 1;
        let mut target_program_data = [];
        let mut target_config_lamports = 1;
        let mut target_config_data = vec![0; PROGRAM_CONFIG_MIN_LEN];
        let mut token_program_lamports = 1;
        let mut token_program_data = [];
        let system_owner = system_program::id();
        let loader_owner = pubkey!("BPFLoaderUpgradeab1e11111111111111111111111");
        let token_program_id = spl_token::id();

        Mint::pack(
            Mint {
                mint_authority: COption::Some(old_cal_authority),
                supply: 0,
                decimals: 9,
                is_initialized: true,
                freeze_authority: COption::None,
            },
            &mut cal_data,
        )
        .unwrap();
        Mint::pack(
            Mint {
                mint_authority: COption::Some(old_dung_authority),
                supply: 0,
                decimals: 9,
                is_initialized: true,
                freeze_authority: COption::None,
            },
            &mut dung_data,
        )
        .unwrap();
        target_config_data[..8].copy_from_slice(&PROGRAM_CONFIG_DISCRIMINATOR);
        target_config_data[PROGRAM_CONFIG_ADMIN_OFFSET..PROGRAM_CONFIG_BACKEND_OFFSET]
            .copy_from_slice(V4A_ADMIN_AUTHORITY.as_ref());
        target_config_data[PROGRAM_CONFIG_BACKEND_OFFSET..PROGRAM_CONFIG_VERSION_OFFSET]
            .copy_from_slice(V4B_BACKEND_AUTHORITY.as_ref());
        target_config_data[PROGRAM_CONFIG_VERSION_OFFSET] = V4B_PROGRAM_VERSION;
        target_config_data[PROGRAM_CONFIG_INITIALIZED_OFFSET] = 1;
        target_config_data[PROGRAM_CONFIG_CAL_MINT_OFFSET..PROGRAM_CONFIG_DUNG_MINT_OFFSET]
            .copy_from_slice(CAL_MINT.as_ref());
        target_config_data
            [PROGRAM_CONFIG_DUNG_MINT_OFFSET..PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET]
            .copy_from_slice(DUNG_MINT.as_ref());
        target_config_data[PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET] = new_cal_bump;
        target_config_data[PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET] = new_dung_bump;

        let accounts = vec![
            AccountInfo::new(
                &V4A_ADMIN_AUTHORITY,
                true,
                false,
                &mut admin_lamports,
                &mut admin_data,
                &system_owner,
                false,
                0,
            ),
            AccountInfo::new(
                &CAL_MINT,
                false,
                true,
                &mut cal_lamports,
                &mut cal_data,
                &token_program_id,
                false,
                0,
            ),
            AccountInfo::new(
                &DUNG_MINT,
                false,
                true,
                &mut dung_lamports,
                &mut dung_data,
                &token_program_id,
                false,
                0,
            ),
            AccountInfo::new(
                &old_cal_authority,
                false,
                false,
                &mut cal_authority_lamports,
                &mut cal_authority_data,
                &system_owner,
                false,
                0,
            ),
            AccountInfo::new(
                &old_dung_authority,
                false,
                false,
                &mut dung_authority_lamports,
                &mut dung_authority_data,
                &system_owner,
                false,
                0,
            ),
            AccountInfo::new(
                &target_program,
                false,
                false,
                &mut target_program_lamports,
                &mut target_program_data,
                &loader_owner,
                true,
                0,
            ),
            AccountInfo::new(
                &target_program_config,
                false,
                false,
                &mut target_config_lamports,
                &mut target_config_data,
                &target_program,
                false,
                0,
            ),
            AccountInfo::new(
                &token_program_id,
                false,
                false,
                &mut token_program_lamports,
                &mut token_program_data,
                &loader_owner,
                true,
                0,
            ),
        ];
        let calls = Arc::new(Mutex::new(Vec::new()));
        let previous = set_syscall_stubs(Box::new(TokenSetAuthorityStub {
            calls: Arc::clone(&calls),
        }));
        let _guard = StubGuard(Some(previous));

        process_instruction(&V4A_PROGRAM_ID, &accounts, &[HANDOFF_INSTRUCTION]).unwrap();

        assert_eq!(
            Mint::unpack(&accounts[1].try_borrow_data().unwrap())
                .unwrap()
                .mint_authority,
            COption::Some(new_cal_authority)
        );
        assert_eq!(
            Mint::unpack(&accounts[2].try_borrow_data().unwrap())
                .unwrap()
                .mint_authority,
            COption::Some(new_dung_authority)
        );
        assert_eq!(*calls.lock().unwrap(), vec![CAL_MINT, DUNG_MINT]);
    }
}
