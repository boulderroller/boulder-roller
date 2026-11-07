//! Host-level outcome probe of the production helper; no validator/deployment.
use super::*;
use anchor_lang::solana_program::{
    entrypoint::ProgramResult,
    instruction::Instruction,
    program::invoke,
    program_error::ProgramError,
    program_stubs::{set_syscall_stubs, SyscallStubs},
    system_instruction,
};
use std::sync::{Arc, Mutex};

struct SystemStubs(Arc<Mutex<Vec<u32>>>);

impl SyscallStubs for SystemStubs {
    fn sol_get_rent_sysvar(&self, address: *mut u8) -> u64 {
        // Rent::get supplies aligned storage for a Rent value.
        unsafe { std::ptr::write(address.cast::<Rent>(), Rent::default()) };
        0
    }

    fn sol_invoke_signed(
        &self,
        instruction: &Instruction,
        infos: &[AccountInfo],
        seeds: &[&[&[u8]]],
    ) -> ProgramResult {
        assert_eq!(instruction.program_id, anchor_lang::system_program::ID);
        let tag = u32::from_le_bytes(instruction.data[..4].try_into().unwrap());
        self.0.lock().unwrap().push(tag);
        let account = |index: usize| {
            infos
                .iter()
                .find(|info| *info.key == instruction.accounts[index].pubkey)
                .unwrap()
        };
        for meta in &instruction.accounts {
            let info = infos.iter().find(|info| *info.key == meta.pubkey).unwrap();
            assert!(info.is_writable);
            if meta.is_signer && !info.is_signer {
                assert!(seeds
                    .iter()
                    .any(|seed| Pubkey::create_program_address(seed, &crate::ID).ok()
                        == Some(*info.key)));
            }
        }
        let amount = || u64::from_le_bytes(instruction.data[4..12].try_into().unwrap());
        match tag {
            2 => {
                let from = account(0);
                let to = account(1);
                assert_eq!(*from.owner, anchor_lang::system_program::ID);
                assert!(from.data_is_empty());
                **from.try_borrow_mut_lamports()? -= amount();
                **to.try_borrow_mut_lamports()? += amount();
            }
            0 | 8 => {
                let to = account(if tag == 0 { 1 } else { 0 });
                if !to.data_is_empty()
                    || *to.owner != anchor_lang::system_program::ID
                    || (tag == 0 && to.lamports() != 0)
                {
                    return Err(ProgramError::AccountAlreadyInitialized);
                }
                let size = if tag == 0 {
                    **account(0).try_borrow_mut_lamports()? -= amount();
                    **to.try_borrow_mut_lamports()? += amount();
                    u64::from_le_bytes(instruction.data[12..20].try_into().unwrap())
                } else {
                    amount()
                };
                // Host AccountInfo has no runtime allocation; retain backing storage
                // for this test process, then let production serialization run.
                *to.try_borrow_mut_data()? = Box::leak(vec![0; size as usize].into_boxed_slice());
                if tag == 0 {
                    to.assign(&Pubkey::new_from_array(
                        instruction.data[20..52].try_into().unwrap(),
                    ));
                }
            }
            1 => {
                let to = account(0);
                assert_eq!(*to.owner, anchor_lang::system_program::ID);
                to.assign(&Pubkey::new_from_array(
                    instruction.data[4..36].try_into().unwrap(),
                ));
            }
            _ => panic!("unexpected system instruction {tag}"),
        }
        Ok(())
    }
}

struct RestoreStubs(Option<Box<dyn SyscallStubs>>);
impl Drop for RestoreStubs {
    fn drop(&mut self) {
        set_syscall_stubs(self.0.take().unwrap());
    }
}

#[test]
fn leaderboard_prefund_does_not_block_next_vault_creation() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let _restore = RestoreStubs(Some(set_syscall_stubs(Box::new(SystemStubs(
        calls.clone(),
    )))));
    let rent = Rent::default().minimum_balance(VaultLeaderboard::SIZE);
    // The counter fixes the next PDA; an unsolicited transfer must not reserve it.
    let counter = VaultCounter { count: 7, bump: 0 };
    let (key, bump) = Pubkey::find_program_address(
        &[VAULT_LEADERBOARD_SEED, &counter.count.to_le_bytes()],
        &crate::ID,
    );
    for prefund in [650_000, 0, rent, rent + 1] {
        let sponsor_key = Pubkey::new_unique();
        let mut sponsor_owner = anchor_lang::system_program::ID;
        let mut owner = anchor_lang::system_program::ID;
        let mut sponsor_lamports = rent * 10;
        let mut lamports = 0;
        let sponsor = AccountInfo::new(
            &sponsor_key,
            true,
            true,
            &mut sponsor_lamports,
            &mut [],
            &mut sponsor_owner,
            false,
            0,
        );
        let leaderboard = AccountInfo::new(
            &key,
            false,
            true,
            &mut lamports,
            &mut [],
            &mut owner,
            false,
            0,
        );
        let system_key = anchor_lang::system_program::ID;
        let mut system_lamports = 0;
        let system = AccountInfo::new(
            &system_key,
            false,
            false,
            &mut system_lamports,
            &mut [],
            &system_key,
            true,
            0,
        );
        if prefund > 0 {
            invoke(
                &system_instruction::transfer(&sponsor_key, &key, prefund),
                &[sponsor.clone(), leaderboard.clone(), system.clone()],
            )
            .unwrap();
        }
        calls.lock().unwrap().clear();
        let before = sponsor.lamports();
        let wrong_key = Pubkey::new_unique();
        let wrong_owner = Pubkey::new_unique();
        let mut invalid_lamports = prefund;
        let mut wrong_owner_lamports = prefund;
        let mut nonempty_lamports = prefund;
        let mut invalid_data = [0u8];
        for invalid in [
            AccountInfo::new(
                &wrong_key,
                false,
                true,
                &mut invalid_lamports,
                &mut [],
                &system_key,
                false,
                0,
            ),
            AccountInfo::new(
                &key,
                false,
                true,
                &mut wrong_owner_lamports,
                &mut [],
                &wrong_owner,
                false,
                0,
            ),
            AccountInfo::new(
                &key,
                false,
                true,
                &mut nonempty_lamports,
                &mut invalid_data,
                &system_key,
                false,
                0,
            ),
        ] {
            assert!(create_empty_vault_leaderboard_account(
                &invalid,
                &sponsor,
                &system,
                &crate::ID,
                counter.count,
                bump
            )
            .is_err());
        }
        assert!(create_empty_vault_leaderboard_account(
            &leaderboard,
            &sponsor,
            &system,
            &crate::ID,
            counter.count,
            bump.wrapping_add(1)
        )
        .is_err());
        assert!(
            calls.lock().unwrap().is_empty(),
            "invalid accounts must fail before CPI"
        );
        assert_eq!(sponsor.lamports(), before);
        let result = create_empty_vault_leaderboard_account(
            &leaderboard,
            &sponsor,
            &system,
            &crate::ID,
            counter.count,
            bump,
        );
        assert!(
            result.is_ok(),
            "pre-funded next leaderboard ({prefund} lamports) blocked vault creation: {result:?}"
        );
        assert_eq!(leaderboard.lamports(), rent.max(prefund));
        assert_eq!(before - sponsor.lamports(), rent.saturating_sub(prefund));
        assert_eq!(*leaderboard.owner, crate::ID);
        assert_eq!(leaderboard.data_len(), VaultLeaderboard::SIZE);
        let decoded =
            VaultLeaderboard::try_deserialize(&mut &leaderboard.try_borrow_data().unwrap()[..])
                .unwrap();
        assert_eq!(decoded.vault_id, counter.count);
        assert_eq!(decoded.bump, bump);
        assert!(decoded.entries.is_empty());
        assert_eq!(decoded.last_updated, 0);
        assert_eq!(
            *calls.lock().unwrap(),
            if prefund == 0 {
                vec![0]
            } else if prefund < rent {
                vec![2, 8, 1]
            } else {
                vec![8, 1]
            }
        );
        calls.lock().unwrap().clear();
        assert!(create_empty_vault_leaderboard_account(
            &leaderboard,
            &sponsor,
            &system,
            &crate::ID,
            counter.count,
            bump
        )
        .is_err());
        assert!(
            calls.lock().unwrap().is_empty(),
            "initialized account must fail before CPI"
        );
    }
}
