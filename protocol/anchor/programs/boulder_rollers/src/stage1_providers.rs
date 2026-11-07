//! Read-only, pinned mainnet provider layouts. Sources/offsets: STAGE1_SPEC §3.1.
//! No provider CPI and no second deduction of provider fees.
use super::*;

/// Explicit test asset, never a branded mainnet token.
pub const DEVNET_TEST_SPL: u8 = 5;
// Canonical current devnet SPL deployment, per solana-program.com/docs/stake-pool.
pub const DEVNET_SPL_PROGRAM: Pubkey = Pubkey::new_from_array([3, 44, 193, 229, 244, 147, 104, 86, 90, 217, 172, 54, 132, 195, 254, 171, 202, 127, 228, 56, 170, 164, 31, 64, 158, 24, 93, 79, 72, 162, 144, 244]);
pub const JITO: u8 = 2;
pub const MARINADE: u8 = 3;
pub const JUP: u8 = 4;
pub const JITO_MINT: Pubkey = Pubkey::new_from_array([
    252, 209, 65, 233, 131, 44, 175, 16, 173, 145, 116, 149, 202, 15, 39, 27, 91, 41, 60, 212, 112,
    39, 234, 115, 112, 7, 237, 64, 235, 57, 160, 189,
]);
pub const MSOL_MINT: Pubkey = Pubkey::new_from_array([
    11, 98, 186, 7, 79, 114, 44, 157, 65, 20, 242, 216, 247, 10, 0, 198, 96, 2, 51, 123, 155, 249,
    12, 135, 54, 87, 166, 210, 1, 219, 76, 128,
]);
pub const JUP_MINT: Pubkey = Pubkey::new_from_array([
    10, 254, 29, 145, 103, 20, 34, 199, 101, 199, 160, 106, 17, 57, 255, 97, 57, 211, 128, 252,
    180, 34, 186, 120, 247, 120, 190, 213, 60, 105, 125, 129,
]);

pub fn identity(kind: u8) -> Result<(Pubkey, Pubkey, Pubkey)> {
    Ok(match kind {
        JITO => (
            Pubkey::new_from_array([
                6, 129, 78, 212, 202, 246, 138, 23, 70, 114, 253, 172, 134, 3, 26, 99, 232, 78,
                161, 94, 250, 29, 68, 183, 34, 147, 246, 219, 219, 0, 22, 80,
            ]),
            Pubkey::new_from_array([
                4, 138, 62, 8, 195, 180, 149, 190, 23, 244, 84, 39, 216, 155, 236, 91, 128, 199,
                226, 105, 92, 24, 100, 215, 103, 67, 219, 57, 190, 211, 70, 214,
            ]),
            JITO_MINT,
        ),
        MARINADE => (
            Pubkey::new_from_array([
                5, 69, 227, 101, 190, 242, 113, 173, 117, 53, 3, 103, 86, 93, 164, 13, 163, 54,
                220, 28, 135, 155, 177, 84, 138, 122, 252, 197, 90, 169, 57, 30,
            ]),
            Pubkey::new_from_array([
                117, 17, 155, 49, 117, 128, 117, 134, 227, 244, 167, 229, 205, 15, 137, 14, 150,
                167, 83, 177, 15, 204, 199, 104, 30, 148, 115, 160, 8, 50, 112, 241,
            ]),
            MSOL_MINT,
        ),
        JUP => (
            Pubkey::new_from_array([
                6, 128, 202, 15, 153, 129, 125, 198, 134, 8, 196, 172, 91, 156, 165, 34, 163, 58,
                89, 41, 241, 107, 218, 130, 68, 164, 28, 3, 22, 185, 8, 237,
            ]),
            Pubkey::new_from_array([
                111, 99, 178, 34, 95, 150, 29, 23, 252, 84, 216, 218, 59, 220, 200, 67, 192, 162,
                13, 74, 141, 108, 170, 116, 154, 235, 212, 76, 163, 141, 31, 75,
            ]),
            JUP_MINT,
        ),
        _ => return err!(ErrorCode::Stage1AdapterDisabled),
    })
}
pub fn kind(mint: Pubkey) -> Option<u8> {
    [(JITO_MINT, JITO), (MSOL_MINT, MARINADE), (JUP_MINT, JUP)]
        .iter()
        .find(|(key, _)| *key == mint)
        .map(|(_, kind)| *kind)
}

#[derive(Clone, Copy)]
pub struct Observation {
    pub rate: Stage1Rate,
    pub current: bool,
    pub exits_verified: bool,
    pub update_epoch: Option<u64>,
}

pub struct Availability {
    pub observation: Option<Observation>,
}
impl Availability {
    pub fn current(&self) -> bool {
        self.observation.map_or(false, |o| o.current)
    }
    pub fn lagging(&self, epoch: u64) -> bool {
        epoch.checked_sub(1).map_or(false, |previous| {
            self.observation.map_or(false, |o| o.update_epoch == Some(previous))
        })
    }
    pub fn outage_marker(&self) -> (bool, u64) {
        match self.observation {
            Some(o) => (false, o.update_epoch.unwrap_or(0)),
            None => (true, 0),
        }
    }
}

fn invalid() -> anchor_lang::error::Error {
    error!(ErrorCode::Stage1InvalidProvider)
}
fn bytes(data: &[u8], start: usize, len: usize) -> Result<&[u8]> {
    data.get(start..start + len).ok_or_else(invalid)
}
fn number(data: &[u8], at: usize) -> Result<u64> {
    Ok(u64::from_le_bytes(
        bytes(data, at, 8)?.try_into().map_err(|_| invalid())?,
    ))
}
fn key(data: &[u8], at: usize) -> Result<Pubkey> {
    Ok(Pubkey::new_from_array(
        bytes(data, at, 32)?.try_into().map_err(|_| invalid())?,
    ))
}

// Borsh's optional keys and FutureEpoch<Fee> are variable width. Validate every
// tag and fee rather than trusting offsets past the fixed stake-pool prefix.
struct Reader<'a> {
    data: &'a [u8],
    at: usize,
}
impl Reader<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8]> {
        let start = self.at;
        self.at += n;
        bytes(self.data, start, n)
    }
    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    fn fee(&mut self) -> Result<(u64, u64)> {
        let d = number(self.data, self.at)?;
        let n = number(self.data, self.at + 8)?;
        self.at += 16;
        require!(n <= d, ErrorCode::Stage1InvalidProvider);
        Ok((n, d))
    }
    fn future_fee(&mut self) -> Result<bool> {
        match self.byte()? {
            0 => Ok(false),
            1 | 2 => {
                self.fee()?;
                Ok(true)
            }
            _ => Err(invalid()),
        }
    }
    fn optional_key(&mut self) -> Result<bool> {
        match self.byte()? {
            0 => Ok(false),
            1 => {
                self.take(32)?;
                Ok(true)
            }
            _ => Err(invalid()),
        }
    }
}

/// Strict admission: authenticated unreadability still cannot supply a quote.
pub fn observe(
    asset: &Stage1AssetConfig,
    accounts: &[AccountInfo],
    epoch: u64,
) -> Result<Observation> {
    inspect(asset, accounts, epoch)?.observation.ok_or_else(invalid)
}

/// Wrong supplied identities/owners are hard failures. Only the canonical
/// provider's unreadable or impossible accounting qualifies as unavailability.
pub fn inspect(
    asset: &Stage1AssetConfig,
    accounts: &[AccountInfo],
    epoch: u64,
) -> Result<Availability> {
    require!(accounts.len() == 2, ErrorCode::Stage1InvalidProvider);
    let (owner, address, mint) = if cfg!(feature = "stage1-devnet") && asset.adapter == DEVNET_TEST_SPL {
        // These fields are written once by the singleton registration handler.
        (DEVNET_SPL_PROGRAM, asset.provider_account, asset.mint)
    } else {
        identity(asset.adapter)?
    };
    let state = &accounts[0];
    let token = &accounts[1];
    require!(
        asset.provider_account == address
            && asset.mint == mint
            && *state.key == address
            && *state.owner == owner
            && !state.executable
            && *token.key == mint
            && *token.owner == token::ID
            && !token.executable,
        ErrorCode::Stage1InvalidProvider
    );
    let mint_data = token.try_borrow_data()?;
    let data = state.try_borrow_data()?;
    Ok(Availability {
        observation: decode(asset, &data, &mint_data, epoch).ok(),
    })
}

fn decode(asset: &Stage1AssetConfig, data: &[u8], mint_data: &[u8], epoch: u64) -> Result<Observation> {
    let mint = asset.mint;
    let parsed_mint = Mint::try_deserialize(&mut &mint_data[..]).map_err(|_| invalid())?;
    require!(
        mint_data.len() == 82 && parsed_mint.decimals == 9 && parsed_mint.is_initialized,
        ErrorCode::Stage1InvalidProvider
    );
    let result = if asset.adapter == MARINADE {
        require!(
            data.len() == 2616
                && data[..8] == [216, 146, 107, 94, 104, 75, 182, 177]
                && key(&data, 8)? == mint
                && data[608] <= 1
                && data[617] <= 1,
            ErrorCode::Stage1InvalidProvider
        );
        // Parse the known variable-width enum; padding is not a layout version.
        let mut tail = Reader {
            data: &data,
            at: 638,
        };
        match tail.byte()? {
            0 => {
                tail.take(20)?;
            }
            1 => {
                tail.take(12)?;
            }
            2 => {}
            _ => return Err(invalid()),
        }
        tail.take(8)?;
        // Marinade prices directly from this accounting state; it has no global
        // reward-update epoch. last_stake_delta_epoch is NOT a freshness witness.
        // Pause gates provider operations, not this accounting ratio. In-kind
        // custody never calls those operations or promises SOL liquidity.
        let total = [376, 226, 496, 568].iter().try_fold(0u64, |sum, at| {
            sum.checked_add(number(&data, *at)?).ok_or_else(invalid)
        })?;
        let n = total.checked_sub(number(&data, 528)?).ok_or_else(invalid)?;
        Observation {
            rate: Stage1Rate {
                n,
                d: number(&data, 504)?,
            },
            current: true,
            exits_verified: true,
            update_epoch: None,
        }
    } else {
        require!(
            data.len() == 611
                && data[0] == 1
                && key(&data, 162)? == mint
                && key(&data, 226)? == token::ID,
            ErrorCode::Stage1InvalidProvider
        );
        let updated = number(&data, 274)?;
        require!(updated <= epoch, ErrorCode::Stage1InvalidProvider);
        let mut tail = Reader {
            data: &data,
            at: 330,
        };
        tail.fee()?;
        tail.future_fee()?;
        tail.optional_key()?;
        let preferred_withdraw = tail.optional_key()?;
        tail.fee()?;
        let stake_fee = tail.fee()?;
        let pending_stake = tail.future_fee()?;
        require!(tail.byte()? <= 100, ErrorCode::Stage1InvalidProvider);
        tail.optional_key()?;
        tail.fee()?;
        require!(tail.byte()? <= 100, ErrorCode::Stage1InvalidProvider);
        let withdraw_authority = tail.optional_key()?;
        let sol_fee = tail.fee()?;
        let pending_sol = tail.future_fee()?;
        tail.take(16)?;
        // JupSOL admission binds the actually verified withdrawal configuration.
        // New enablement rechecks it; later changes do not confiscate held lots.
        let exits_verified = !preferred_withdraw
            && !withdraw_authority
            && !pending_stake
            && !pending_sol
            && data[282..330].iter().all(|b| *b == 0)
            && stake_fee == (1, 1000)
            && sol_fee == (1, 1000);
        Observation {
            rate: Stage1Rate {
                n: number(&data, 258)?,
                d: number(&data, 266)?,
            },
            current: updated == epoch,
            exits_verified,
            update_epoch: Some(updated),
        }
    };
    require!(
        result.rate.n > 0 && result.rate.d > 0 && parsed_mint.supply <= result.rate.d,
        ErrorCode::Stage1InvalidProvider
    );
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn account(address: Pubkey, owner: Pubkey, data: &[u8]) -> AccountInfo<'static> {
        AccountInfo::new(
            Box::leak(Box::new(address)),
            false,
            false,
            Box::leak(Box::new(1)),
            Box::leak(data.to_vec().into_boxed_slice()),
            Box::leak(Box::new(owner)),
            false,
            0,
        )
    }
    pub fn fixture(kind: u8) -> (Stage1AssetConfig, Vec<AccountInfo<'static>>) {
        let (owner, state, mint) = identity(kind).unwrap();
        let (bytes, mint_bytes): (&[u8], &[u8]) = match kind {
            JITO => (
                include_bytes!("../../../tests/fixtures/stage1_providers/jito-pool.bin"),
                include_bytes!("../../../tests/fixtures/stage1_providers/jito-mint.bin"),
            ),
            MARINADE => (
                include_bytes!("../../../tests/fixtures/stage1_providers/msol-state.bin"),
                include_bytes!("../../../tests/fixtures/stage1_providers/msol-mint.bin"),
            ),
            JUP => (
                include_bytes!("../../../tests/fixtures/stage1_providers/jup-pool.bin"),
                include_bytes!("../../../tests/fixtures/stage1_providers/jup-mint.bin"),
            ),
            _ => panic!("unknown fixture"),
        };
        let mut asset = Stage1AssetConfig::try_deserialize_unchecked(
            &mut &vec![0; 8 + Stage1AssetConfig::INIT_SPACE][..],
        )
        .unwrap();
        asset.adapter = kind;
        asset.mint = mint;
        asset.provider_account = state;
        (
            asset,
            vec![
                account(state, owner, bytes),
                account(mint, token::ID, mint_bytes),
            ],
        )
    }
    #[test]
    fn registered_test_pool_keeps_spl_validation_and_network_boundary() {
        let (mut asset, mut infos) = fixture(JITO);
        asset.adapter = DEVNET_TEST_SPL;
        asset.mint = Pubkey::new_unique();
        asset.provider_account = Pubkey::new_unique();
        infos[0].key = Box::leak(Box::new(asset.provider_account));
        infos[1].key = Box::leak(Box::new(asset.mint));
        infos[0].try_borrow_mut_data().unwrap()[162..194].copy_from_slice(asset.mint.as_ref());
        if !cfg!(feature = "stage1-devnet") {
            assert!(observe(&asset, &infos, 1057).is_err());
            return;
        }
        assert!(inspect(&asset, &infos, 1057).is_err()); // SPoo1 is not the devnet owner.
        infos[0].owner = Box::leak(Box::new(DEVNET_SPL_PROGRAM));
        assert!(observe(&asset, &infos, 1057).unwrap().current);
        assert!(!observe(&asset, &infos, 1058).unwrap().current);
        assert!(observe(&asset, &infos, 1056).is_err());
        let owner = infos[0].owner;
        infos[0].owner = Box::leak(Box::new(token::ID));
        assert!(inspect(&asset, &infos, 1057).is_err());
        infos[0].owner = owner;
        infos[0].try_borrow_mut_data().unwrap()[162] ^= 1;
        assert!(observe(&asset, &infos, 1057).is_err());
        infos[0].try_borrow_mut_data().unwrap()[162] ^= 1;
        infos[1].try_borrow_mut_data().unwrap()[36..44].copy_from_slice(&u64::MAX.to_le_bytes());
        assert!(observe(&asset, &infos, 1057).is_err());
        assert!(inspect(&asset, &infos, 1057).unwrap().observation.is_none());
    }
    #[test]
    fn snapshots_derive_exact_hand_computed_rates_and_verified_jup_exits() {
        for (kind, n, d) in [
            (JITO, 10650132353883915, 8153209489021421),
            (MARINADE, 2254985557764365, 1596971612132375),
            (JUP, 5194388907066853, 4277554095630348),
        ] {
            let (asset, infos) = fixture(kind);
            let observation = observe(&asset, &infos, 1057).unwrap();
            assert_eq!((observation.rate.n, observation.rate.d), (n, d));
            assert!(observation.current);
            if kind == JUP {
                assert!(observation.exits_verified);
            }
        }
    }
    #[test]
    fn provenance_is_validated_before_any_stale_classification() {
        for kind in [JITO, MARINADE, JUP] {
            for fault in 0..6 {
                let (asset, mut infos) = fixture(kind);
                match fault {
                    0 => infos[0].owner = Box::leak(Box::new(token::ID)),
                    1 => infos[0].key = Box::leak(Box::new(Pubkey::new_unique())),
                    2 => infos[1].key = Box::leak(Box::new(Pubkey::new_unique())),
                    3 => infos[0].try_borrow_mut_data().unwrap()[0] = 255,
                    4 => infos[1].owner = Box::leak(Box::new(Pubkey::new_unique())),
                    5 => infos[1].try_borrow_mut_data().unwrap()[44] = 8,
                    _ => unreachable!(),
                }
                assert!(
                    observe(&asset, &infos, 2000).is_err(),
                    "kind {kind}, fault {fault}"
                );
                if fault == 3 || fault == 5 {
                    assert!(inspect(&asset, &infos, 2000).unwrap().observation.is_none());
                } else {
                    assert!(inspect(&asset, &infos, 2000).is_err());
                }
            }
        }
    }
    #[test]
    fn spl_epoch_lag_is_distinct_from_a_malformed_future_epoch() {
        for kind in [JITO, JUP] {
            let (asset, infos) = fixture(kind);
            assert!(!observe(&asset, &infos, 1058).unwrap().current);
            assert!(observe(&asset, &infos, 1056).is_err());
        }
    }
    #[test]
    fn marinade_pause_does_not_erase_an_available_in_kind_accounting_quote() {
        let (asset, infos) = fixture(MARINADE);
        infos[0].try_borrow_mut_data().unwrap()[608] = 1;
        let rate = observe(&asset, &infos, 2000).unwrap();
        assert!(rate.current);
        assert_eq!(rate.rate.n, 2254985557764365);
        assert_eq!(rate.update_epoch, None);
    }
    #[test]
    fn unknown_borsh_tags_reject_admission_but_authenticate_unavailability() {
        for (kind, offset) in [(JITO, 346), (JUP, 346), (MARINADE, 638)] {
            let (asset, infos) = fixture(kind);
            infos[0].try_borrow_mut_data().unwrap()[offset] = 255;
            assert!(observe(&asset, &infos, 1058).is_err());
            assert!(inspect(&asset, &infos, 1058).unwrap().observation.is_none());
        }
    }
}
