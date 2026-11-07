//! Stage 1 funded claim sets. Snapshot/allocation truth is publisher-attested;
//! membership never proves riding. See STAGE1_SPEC §§5,6,8.
use super::*;
use anchor_lang::solana_program::hash::hashv;

pub const S1_FUNDING: &[u8] = b"s1v1_funding";
pub const S1_CURSOR: &[u8] = b"s1v1_cursor";
pub const S1_SKIP_LIMIT: u64 = 16;
pub const S1_CLAIMS: &[u8] = b"s1v1_claims";
pub const S1_RECIPIENT: &[u8] = b"s1v1_recipient";
pub const S1_HELD_AGE: u64 = 26;
pub const S1_MAX_DEPTH: usize = 16;
pub const S1_MAX_LEAVES: u32 = 1 << S1_MAX_DEPTH;
// full, ascents, top ten, earned Legend, cap. Pool is a separate terminal field.
pub const S1_BUCKETS: usize = 5;

pub fn plus(a: u128, b: u128) -> Result<u128> {
    a.checked_add(b)
        .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
}
pub fn minus(a: u128, b: u128) -> Result<u128> {
    a.checked_sub(b)
        .ok_or_else(|| error!(ErrorCode::Stage1Solvency))
}
pub fn bucket_sum(buckets: &[u64; S1_BUCKETS]) -> Result<u64> {
    buckets.iter().try_fold(0u64, |a, b| {
        a.checked_add(*b)
            .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
    })
}

/// Available harvest and terminal pool are SUBSETS of held, not new income.
/// Cash is admitted once; fee withdrawal remains absent.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Default, InitSpace, Debug, PartialEq)]
pub struct Stage1Ledger {
    pub deposited: u128,
    /// Sum of lot.units + lot.owner_units, including exit partitions.
    pub owner_custody: u128,
    pub owner_returns: u128,
    pub earnings: u128,
    pub paid: u128,
    pub claimable: u128,
    pub held: u128,
    pub pool: u128,
    pub admitted_cash_lifetime: u128,
}
impl Stage1Ledger {
    pub fn check(&self, realized: u128, fees: u128) -> Result<()> {
        require!(
            plus(plus(self.paid, fees)?, plus(self.claimable, self.held)?)? == plus(realized, self.admitted_cash_lifetime)?,
            ErrorCode::Stage1Solvency
        );
        require!(
            self.earnings == plus(fees, plus(self.claimable, self.held)?)?,
            ErrorCode::Stage1Solvency
        );
        require!(
            plus(self.deposited, self.admitted_cash_lifetime)?
                == plus(
                    self.owner_custody,
                    plus(self.owner_returns, plus(self.earnings, self.paid)?)?
                )?,
            ErrorCode::Stage1Solvency
        );
        require!(self.pool <= self.held, ErrorCode::Stage1Solvency);
        Ok(())
    }
    pub fn deposit(&mut self, units: u64) -> Result<()> {
        self.deposited = plus(self.deposited, units as u128)?;
        self.owner_custody = plus(self.owner_custody, units as u128)?;
        Ok(())
    }
    pub fn admit_cash(&mut self, units: u64) -> Result<()> {
        require!(units > 0, ErrorCode::Stage1InvalidFunding);
        self.admitted_cash_lifetime = plus(self.admitted_cash_lifetime, units as u128)?;
        self.earnings = plus(self.earnings, units as u128)?;
        self.held = plus(self.held, units as u128)?;
        Ok(())
    }
    pub fn owner_return(&mut self, principal: u64, reserve: u64) -> Result<()> {
        self.owner_custody = minus(
            self.owner_custody,
            plus(principal as u128, reserve as u128)?,
        )?;
        self.owner_returns = plus(
            self.owner_returns,
            plus(principal as u128, reserve as u128)?,
        )?;
        Ok(())
    }
    pub fn harvest(&mut self, units: u64, fee: u64) -> Result<()> {
        self.owner_custody = minus(self.owner_custody, units as u128)?;
        self.earnings = plus(self.earnings, units as u128)?;
        self.held = plus(self.held, minus(units as u128, fee as u128)?)?;
        Ok(())
    }
    pub fn publish(&mut self, units: u64) -> Result<()> {
        self.held = minus(self.held, units as u128)?;
        require!(self.held >= self.pool, ErrorCode::Stage1Solvency);
        self.claimable = plus(self.claimable, units as u128)?;
        Ok(())
    }
    pub fn claim(&mut self, units: u64) -> Result<()> {
        self.claimable = minus(self.claimable, units as u128)?;
        self.earnings = minus(self.earnings, units as u128)?;
        self.paid = plus(self.paid, units as u128)?;
        Ok(())
    }
}
impl Stage1AssetConfig {
    pub fn check_accounting(&self) -> Result<()> {
        self.ledger.check(self.harvested_units, self.fees_assessed)
    }
    pub fn check_earnings(&self, info: &AccountInfo) -> Result<()> {
        self.check_accounting()?;
        let expected =
            Pubkey::find_program_address(&[S1_EARNINGS, self.mint.as_ref()], &crate::ID).0;
        require_keys_eq!(expected, *info.key, ErrorCode::Stage1InvalidCustody);
        let token: TokenAccount = stage1::read_owned(info)?;
        let authority = Pubkey::find_program_address(&[S1_ASSET, self.mint.as_ref()], &crate::ID).0;
        require!(
            token.mint == self.mint
                && token.owner == authority
                && token.amount as u128 >= self.ledger.earnings,
            ErrorCode::Stage1InvalidCustody
        );
        Ok(())
    }
}

/// One permanent cursor per hill/mint. In-order settlement makes each live
/// ring slot unambiguously the original week, never a refreshed hold age.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, InitSpace)]
pub struct Stage1CarriedHold {
    pub source: Pubkey,
    pub week: u64,
    pub holds: [u64; S1_BUCKETS],
    pub lineage: [u8; 32],
    pub revision: u64,
    pub pool: u64,
    pub proposed: bool,
    pub proposal_week: u64,
    pub proposal_snapshot: [u8; 32],
    pub proposal_revision: u64,
    pub proposal_remaining: [u64; S1_BUCKETS],
}

#[account]
#[derive(InitSpace)]
pub struct Stage1SettlementCursor {
    pub city: Pubkey,
    pub hill: Pubkey,
    pub asset: Pubkey,
    pub mint: Pubkey,
    /// First unprocessed week (all smaller weeks were published or proven empty).
    pub next_week: u64,
    pub holds: [u64; 26],
    pub bump: u8,
    pub cash_sequence: u64,
    pub active_cash_streams: u64,
    pub future_cash: u64,
    pub pending_current_holds: u64,
    pub cash_holds: [u64; 26],
    /// Earliest unprocessed boost tranche; zero means no future cash. Kept
    /// through staging until the complete frozen set has been published.
    pub next_boost_due_week: u64,
    /// Minimum due strictly after next_week, rebuilt by every frozen stream
    /// and every new post. Publication promotes it only after count equality.
    pub following_boost_due_week: u64,
    /// Rolling digest of publication events; survives claim-set closure.
    pub publication_commitment: [u8; 32],
    /// At most one positive ordinary hold per original-age ring slot. Stored
    /// on the heap during decoding; full capacity is prepaid once at init.
    #[max_len(26)]
    pub carried_holds: Vec<Stage1CarriedHold>,
}
impl Stage1SettlementCursor {
    pub fn note_following_boost_due(&mut self, due: u64) -> Result<()> {
        require!(due > self.next_week, ErrorCode::Stage1InvalidFunding);
        if self.following_boost_due_week == 0 || due < self.following_boost_due_week {
            self.following_boost_due_week = due;
        }
        Ok(())
    }
    pub fn admit_boost_due(&mut self, due: u64) -> Result<()> {
        self.note_following_boost_due(due)?;
        if self.next_boost_due_week == 0 || due < self.next_boost_due_week {
            self.next_boost_due_week = due;
        }
        Ok(())
    }
    fn reseed_following_boost_due(&mut self) {
        self.following_boost_due_week = if self.next_boost_due_week > self.next_week {
            self.next_boost_due_week
        } else { 0 };
    }
    pub fn skip_end(&mut self, through: u64) -> Result<()> {
        require!(through >= self.next_week
            && through - self.next_week < S1_SKIP_LIMIT
            && self.pending_current_holds == 0
            && (self.future_cash == 0) == (self.next_boost_due_week == 0),
            ErrorCode::Stage1InvalidFunding);
        require!(self.next_boost_due_week == 0 || through < self.next_boost_due_week,
            ErrorCode::Stage1SkipBoostDue);
        for slot in 0..S1_HELD_AGE as usize {
            if self.holds[slot] == 0 && self.cash_holds[slot] == 0 { continue; }
            // In-order settlement and the maturity-slot check make this the
            // unique original-born + 26, even after many quiet-week skips.
            let distance = (slot as u64 + S1_HELD_AGE - self.next_week % S1_HELD_AGE) % S1_HELD_AGE;
            let maturity = self.next_week.checked_add(distance).ok_or(ErrorCode::Stage1Arithmetic)?;
            require!(through < maturity, ErrorCode::Stage1SkipHoldMaturity);
        }
        self.next_week = through.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
        self.reseed_following_boost_due();
        Ok(())
    }
    pub fn transition_hold(&mut self, born: u64, before: u64, after: u64) -> Result<()> {
        require!(born < self.next_week && after <= before, ErrorCode::Stage1InvalidHold);
        if before == 0 { return Ok(()); }
        let slot = (born % S1_HELD_AGE) as usize;
        require!(self.next_week - born <= S1_HELD_AGE && self.holds[slot] == before,
            ErrorCode::Stage1InvalidHold);
        self.holds[slot] = after;
        Ok(())
    }
    pub fn transition_cash_hold(&mut self, born: u64, before: u64, after: u64) -> Result<()> {
        require!(born < self.next_week && after <= before, ErrorCode::Stage1InvalidHold);
        if before == 0 { return Ok(()); }
        let slot = (born % S1_HELD_AGE) as usize;
        require!(self.next_week - born <= S1_HELD_AGE && self.cash_holds[slot] >= before,
            ErrorCode::Stage1InvalidHold);
        self.cash_holds[slot] -= before - after;
        Ok(())
    }
    pub fn finish_week(&mut self, week: u64, new_held: u64) -> Result<()> {
        require!(week == self.next_week, ErrorCode::Stage1WeekNotFinalizable);
        let slot = (week % S1_HELD_AGE) as usize;
        require!(self.holds[slot] == 0 && self.cash_holds[slot] == 0, ErrorCode::Stage1InvalidFunding);
        require!((self.future_cash == 0) == (self.following_boost_due_week == 0)
            && (self.following_boost_due_week == 0 || self.following_boost_due_week > week)
            && (self.next_boost_due_week == 0 || self.next_boost_due_week >= week),
            ErrorCode::Stage1InvalidFunding);
        let next = week.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
        self.holds[slot] = new_held;
        self.cash_holds[slot] = self.pending_current_holds;
        self.pending_current_holds = 0;
        self.next_week = next;
        self.next_boost_due_week = self.following_boost_due_week;
        self.reseed_following_boost_due();
        Ok(())
    }
    fn initialize(&mut self, city: Pubkey, hill: Pubkey, asset: Pubkey, mint: Pubkey,
        admitted_week: u64, bump: u8) {
        if self.city == Pubkey::default() {
            self.city = city;
            self.hill = hill;
            self.asset = asset;
            self.mint = mint;
            self.next_week = admitted_week;
            self.bump = bump;
        }
    }
    pub fn carry_closed_holds(&mut self, source: Pubkey, book: &Stage1WeekFunding) -> Result<()> {
        let held = bucket_sum(&book.holds)?;
        // A late zero-hold close must never overwrite a newer ring occupant.
        if held == 0 { return Ok(()); }
        require!(book.week < self.next_week && self.next_week - book.week <= S1_HELD_AGE
            && self.holds[(book.week % S1_HELD_AGE) as usize] == held
            && self.carried_holds.len() < S1_HELD_AGE as usize
            && self.carried_holds.iter().all(|h| h.week % S1_HELD_AGE != book.week % S1_HELD_AGE),
            ErrorCode::Stage1InvalidHold);
        self.carried_holds.push(Stage1CarriedHold::from_book(source, book));
        Ok(())
    }
}

#[account]
#[derive(InitSpace, Default)]
pub struct Stage1WeekFunding {
    pub city: Pubkey,
    pub hill: Pubkey,
    pub asset: Pubkey,
    pub mint: Pubkey,
    pub week: u64,
    pub due_week: u64,
    pub available: u64,
    pub harvested_net: u64,
    /// Rolling commitment to each delivered (lot, units, fee); events retain preimages.
    pub lineage: [u8; 32],
    pub snapshot: [u8; 32],
    pub frozen_at: i64,
    pub cap: u64,
    pub published: bool,
    pub holds: [u64; S1_BUCKETS],
    pub pool: u64,
    pub revision: u64,
    /// Proposal only: no funds move, no reservation or nonexpiry is conferred.
    pub proposed: bool,
    pub proposal_week: u64,
    pub proposal_snapshot: [u8; 32],
    pub proposal_revision: u64,
    pub proposal_remaining: [u64; S1_BUCKETS],
    pub bump: u8,
    pub admitted_cash: u64,
    pub cash_sequence: u64,
    pub cash_expected: u64,
    pub cash_processed: u64,
    pub boost_released: u64,
    pub boost_commitment: [u8; 32],
    pub rent_payer: Pubkey,
}
impl Stage1WeekFunding {
    pub fn validate(&self, key: Pubkey, hill: Pubkey, asset: Pubkey, mint: Pubkey) -> Result<()> {
        let (expected, bump) = Pubkey::find_program_address(
            &[
                S1_FUNDING,
                hill.as_ref(),
                mint.as_ref(),
                &self.week.to_le_bytes(),
            ],
            &crate::ID,
        );
        require!(
            key == expected
                && self.bump == bump
                && self.hill == hill
                && self.asset == asset
                && self.mint == mint
                && self.due_week == self.week,
            ErrorCode::Stage1InvalidFunding
        );
        Ok(())
    }
    fn changed(&mut self) -> Result<()> {
        self.revision = self
            .revision
            .checked_add(1)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
        self.proposed = false;
        Ok(())
    }
    pub fn expire(&mut self, week: u64, ledger: &mut Stage1Ledger) -> Result<()> {
        require!(
            self.published && week.checked_sub(self.week).unwrap_or(0) >= S1_HELD_AGE,
            ErrorCode::Stage1HoldNotExpired
        );
        let value = bucket_sum(&self.holds)?;
        self.pool = self
            .pool
            .checked_add(value)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
        ledger.pool = plus(ledger.pool, value as u128)?;
        self.holds = [0; S1_BUCKETS];
        self.changed()
    }
}

impl Stage1CarriedHold {
    fn from_book(source: Pubkey, book: &Stage1WeekFunding) -> Self {
        Self { source, week: book.week, holds: book.holds, lineage: book.lineage,
            revision: book.revision, pool: book.pool, proposed: book.proposed,
            proposal_week: book.proposal_week, proposal_snapshot: book.proposal_snapshot,
            proposal_revision: book.proposal_revision, proposal_remaining: book.proposal_remaining }
    }
    fn book(&self, cursor: &Stage1SettlementCursor) -> Stage1WeekFunding {
        let bump = Pubkey::find_program_address(&[S1_FUNDING, cursor.hill.as_ref(),
            cursor.mint.as_ref(), &self.week.to_le_bytes()], &crate::ID).1;
        Stage1WeekFunding { city: cursor.city, hill: cursor.hill, asset: cursor.asset,
            mint: cursor.mint, week: self.week, due_week: self.week, published: true, bump,
            holds: self.holds, lineage: self.lineage, revision: self.revision, pool: self.pool,
            proposed: self.proposed, proposal_week: self.proposal_week,
            proposal_snapshot: self.proposal_snapshot, proposal_revision: self.proposal_revision,
            proposal_remaining: self.proposal_remaining, ..Stage1WeekFunding::default() }
    }
}

/// Both live books and closed-book witnesses authenticate the same original
/// namespace. Unsolicited lamports on a closed PDA never resurrect its state.
fn read_hold(info: &AccountInfo, cursor: &Stage1SettlementCursor) -> Result<Stage1WeekFunding> {
    let book = if info.owner == &crate::ID {
        stage1::read_owned::<Stage1WeekFunding>(info)?
    } else {
        require_absent(info)?;
        cursor.carried_holds.iter().find(|h| h.source == *info.key)
            .ok_or(ErrorCode::Stage1InvalidHold)?.book(cursor)
    };
    book.validate(*info.key, cursor.hill, cursor.asset, cursor.mint)?;
    require!(book.city == cursor.city && book.published && book.week < cursor.next_week,
        ErrorCode::Stage1InvalidHold);
    Ok(book)
}

fn store_hold(info: &AccountInfo, cursor: &mut Stage1SettlementCursor, book: &Stage1WeekFunding) -> Result<()> {
    if info.owner == &crate::ID {
        book.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])?;
    } else {
        let index = cursor.carried_holds.iter().position(|h| h.source == *info.key)
            .ok_or(ErrorCode::Stage1InvalidHold)?;
        if bucket_sum(&book.holds)? == 0 { cursor.carried_holds.remove(index); }
        else { cursor.carried_holds[index] = Stage1CarriedHold::from_book(*info.key, book); }
    }
    Ok(())
}

pub fn require_absent(info: &AccountInfo) -> Result<()> {
    require!(info.owner == &System::id() && info.data_is_empty(), ErrorCode::Stage1ClaimStorage);
    Ok(())
}

#[account]
#[derive(InitSpace, Default)]
pub struct Stage1ClaimSet {
    pub city: Pubkey,
    pub hill: Pubkey,
    pub asset: Pubkey,
    pub mint: Pubkey,
    pub week: u64,
    pub root: [u8; 32],
    pub total: u128,
    pub leaf_count: u32,
    /// H(set address, cap, frozen time, H(full immutable audit fields)).
    pub metadata_hash: [u8; 32],
    /// First preparer owns the rent refund, even after publisher rotation.
    pub rent_payer: Pubkey,
    pub paid: u64,
    pub claimed_count: u32,
    pub bump: u8,
    pub storage_version: u8,
    pub sealed: bool,
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq)]
pub struct Stage1ClaimTerms {
    pub cap: u64,
    pub frozen_at: i64,
    pub audit_hash: [u8; 32],
}
impl Stage1ClaimTerms {
    pub fn commitment(&self, address: Pubkey) -> [u8; 32] {
        hashv(&[b"BR-stage1-v2:claim-terms\0", address.as_ref(),
            &self.cap.to_le_bytes(), &self.frozen_at.to_le_bytes(), &self.audit_hash]).to_bytes()
    }
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Stage1CashBatchLeaf {
    pub index: u32,
    pub amount: u64,
    pub proof: Vec<Stage1SumNode>,
    pub terms: Stage1ClaimTerms,
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Stage1CashAudit {
    pub snapshot: [u8; 32],
    pub source_lineage: [u8; 32],
    pub release_commitment: [u8; 32],
    pub boost_commitment: [u8; 32],
    pub new_holds: [u64; S1_BUCKETS],
}
impl Stage1CashAudit {
    pub fn commitment(&self) -> Result<[u8; 32]> {
        Ok(hashv(&[b"BR-stage1-v2:cash-audit\0", &self.try_to_vec()?]).to_bytes())
    }
}
#[event]
pub struct Stage1CashPublished {
    pub claim_set: Pubkey,
    pub city: Pubkey,
    pub hill: Pubkey,
    pub mint: Pubkey,
    pub week: u64,
    pub root: [u8; 32],
    pub total: u128,
    pub leaf_count: u32,
    pub rent_payer: Pubkey,
    pub terms: Stage1ClaimTerms,
    pub audit: Stage1CashAudit,
}
#[account]
#[derive(InitSpace)]
pub struct Stage1Recipient {
    pub person: Pubkey,
    pub recipient: Pubkey,
    pub registered_at: i64,
    pub bump: u8,
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq)]
pub struct Stage1SumNode {
    pub hash: [u8; 32],
    pub sum: u128,
}

pub fn context_json(
    deployment: Pubkey,
    city: Pubkey,
    hill: Pubkey,
    week: u64,
    mint: Pubkey,
) -> String {
    // Canonical JSON over base58 public keys has no characters requiring escaping.
    format!(
        "[\"{}\",\"{}\",\"{}\",{},\"{}\"]",
        deployment, city, hill, week, mint
    )
}
pub fn empty_node(context: &str) -> Stage1SumNode {
    Stage1SumNode {
        hash: hashv(&[b"BR-stage1-v1:empty\0", context.as_bytes()]).to_bytes(),
        sum: 0,
    }
}
pub fn leaf_node(
    context: &str,
    index: u32,
    person: Pubkey,
    recipient: Pubkey,
    amount: u64,
) -> Stage1SumNode {
    let json = format!(
        "[{},{},\"{}\",\"{}\",{}]",
        context, index, person, recipient, amount
    );
    Stage1SumNode {
        hash: hashv(&[b"BR-stage1-v1:leaf\0", json.as_bytes()]).to_bytes(),
        sum: amount as u128,
    }
}
pub fn parent_node(left: &Stage1SumNode, right: &Stage1SumNode) -> Result<Stage1SumNode> {
    Ok(Stage1SumNode {
        hash: hashv(&[
            b"BR-stage1-v1:parent\0",
            &left.hash,
            &left.sum.to_be_bytes(),
            &right.hash,
            &right.sum.to_be_bytes(),
        ])
        .to_bytes(),
        sum: plus(left.sum, right.sum)?,
    })
}
pub fn verify_proof(
    set: &Stage1ClaimSet,
    deployment: Pubkey,
    index: u32,
    person: Pubkey,
    recipient: Pubkey,
    amount: u64,
    proof: &[Stage1SumNode],
    cap: u64,
) -> Result<()> {
    require!(
        set.leaf_count > 0
            && set.leaf_count <= S1_MAX_LEAVES
            && index < set.leaf_count
            && amount > 0
            && amount <= cap,
        ErrorCode::Stage1InvalidProof
    );
    let depth = (32 - (set.leaf_count - 1).leading_zeros()) as usize;
    require!(proof.len() == depth, ErrorCode::Stage1InvalidProof);
    let context = context_json(deployment, set.city, set.hill, set.week, set.mint);
    let empty = empty_node(&context);
    let mut node = leaf_node(&context, index, person, recipient, amount);
    let (mut position, mut width) = (index, set.leaf_count);
    for sibling in proof {
        if (position ^ 1) >= width {
            require!(*sibling == empty, ErrorCode::Stage1InvalidProof);
        }
        node = if position & 1 == 0 {
            parent_node(&node, sibling)?
        } else {
            parent_node(sibling, &node)?
        };
        position /= 2;
        width = (width + 1) / 2;
    }
    require!(
        node.hash == set.root && node.sum == set.total,
        ErrorCode::Stage1InvalidProof
    );
    Ok(())
}
pub fn week_at(anchor: i64, now: i64) -> Result<u64> {
    require!(now >= anchor, ErrorCode::Stage1NotLaunched);
    Ok((now.checked_sub(anchor).ok_or(ErrorCode::Stage1Arithmetic)? / S1_WEEK) as u64)
}
fn finalizable(city: &Stage1CityConfig, week: u64) -> Result<()> {
    let end = (week as u128 + 1)
        .checked_mul(S1_WEEK as u128)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    let end = i64::try_from(end).map_err(|_| error!(ErrorCode::Stage1Arithmetic))?;
    let cutoff = city
        .season_anchor
        .checked_add(end)
        .and_then(|n| n.checked_add(86_400))
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(
        Clock::get()?.unix_timestamp >= cutoff,
        ErrorCode::Stage1WeekNotFinalizable
    );
    Ok(())
}

/// Only sweeps with a nonzero surplus need the last remaining account. Provider
/// state/mint still occupy the original first two positions for real adapters.
pub fn credit_harvest(
    info: Option<&AccountInfo>,
    city: Pubkey,
    hill: Pubkey,
    asset_key: Pubkey,
    mint: Pubkey,
    week: u64,
    lot: Pubkey,
    units: u64,
    fee: u64,
) -> Result<()> {
    let info = info.ok_or(ErrorCode::Stage1InvalidFunding)?;
    require!(info.is_writable, ErrorCode::Stage1InvalidFunding);
    let mut book: Stage1WeekFunding = stage1::read_owned(info)?;
    book.validate(*info.key, hill, asset_key, mint)?;
    require!(
        book.city == city && book.week == week && !book.published && book.snapshot == [0; 32],
        ErrorCode::Stage1InvalidFunding
    );
    let net = units.checked_sub(fee).ok_or(ErrorCode::Stage1Arithmetic)?;
    book.available = book
        .available
        .checked_add(net)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    book.harvested_net = book
        .harvested_net
        .checked_add(net)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    book.lineage = hashv(&[
        b"BR-stage1-v1:income\0",
        &book.lineage,
        lot.as_ref(),
        &units.to_be_bytes(),
        &fee.to_be_bytes(),
    ])
    .to_bytes();
    book.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])
}

pub fn set_publisher(ctx: Context<Stage1SetPublisher>, publisher: Pubkey) -> Result<()> {
    // Default disables publication/hold transitions; it never grants principal authority.
    ctx.accounts.city.publisher = publisher;
    Ok(())
}
pub fn open_week(ctx: Context<Stage1OpenWeek>, week: u64) -> Result<()> {
    require!(week >= ctx.accounts.cursor.next_week
        && week <= week_at(ctx.accounts.city.season_anchor, Clock::get()?.unix_timestamp)?,
        ErrorCode::Stage1WeekNotFinalizable);
    let book = &mut ctx.accounts.funding;
    if book.city == Pubkey::default() {
        book.city = ctx.accounts.city.key();
        book.hill = ctx.accounts.hill_account.hill.key();
        book.asset = ctx.accounts.asset.key();
        book.mint = ctx.accounts.asset.mint;
        book.week = week;
        book.due_week = week;
        book.bump = ctx.bumps.funding;
        book.rent_payer = ctx.accounts.payer.key();
    }
    book.validate(
        book.key(),
        ctx.accounts.hill_account.hill.key(),
        ctx.accounts.asset.key(),
        ctx.accounts.asset.mint,
    )
}
pub fn init_settlement(ctx: Context<Stage1InitSettlement>) -> Result<()> {
    ctx.accounts.cursor.initialize(ctx.accounts.city.key(), ctx.accounts.hill_account.hill.key(),
        ctx.accounts.asset.key(), ctx.accounts.asset.mint,
        ctx.accounts.hill_account.hill.admitted_week, ctx.bumps.cursor);
    Ok(())
}
pub fn skip_empty(ctx: Context<Stage1SkipEmpty>, through: u64) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    finalizable(&ctx.accounts.city, through)?;
    let start = ctx.accounts.cursor.next_week;
    // Preserve every held balance and stop before its original maturity or
    // the next boost due. Canonical witnesses below exclude staged/new income.
    ctx.accounts.cursor.skip_end(through)?;
    require!(ctx.remaining_accounts.len() as u64 == through - start + 1,
        ErrorCode::Stage1InvalidFunding);
    for (week, info) in (start..=through).zip(ctx.remaining_accounts) {
        let expected = Pubkey::find_program_address(&[S1_FUNDING, ctx.accounts.hill.key().as_ref(),
            ctx.accounts.asset.mint.as_ref(), &week.to_le_bytes()], &crate::ID).0;
        require_keys_eq!(*info.key, expected, ErrorCode::Stage1InvalidFunding);
        if info.owner == &System::id() && info.data_is_empty() { continue; }
        let book: Stage1WeekFunding = stage1::read_owned(info)?;
        book.validate(*info.key, ctx.accounts.hill.key(), ctx.accounts.asset.key(), ctx.accounts.asset.mint)?;
        require!(book.city == ctx.accounts.city.key() && book.week == week
            && book.available == 0 && book.harvested_net == 0 && book.admitted_cash == 0 && book.lineage == [0; 32]
            && book.boost_released == 0 && book.cash_processed == 0
            && book.snapshot == [0; 32] && !book.published && !book.proposed
            && book.holds == [0; S1_BUCKETS] && book.pool == 0,
            ErrorCode::Stage1InvalidFunding);
    }
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())
}
pub fn register_recipient(ctx: Context<Stage1RegisterRecipient>, recipient: Pubkey) -> Result<()> {
    require!(
        recipient != Pubkey::default(),
        ErrorCode::Stage1InvalidRecipient
    );
    *ctx.accounts.registration = Stage1Recipient {
        person: ctx.accounts.person.key(),
        recipient,
        registered_at: Clock::get()?.unix_timestamp,
        bump: ctx.bumps.registration,
    };
    Ok(())
}
pub fn freeze_snapshot(
    ctx: Context<Stage1FreezeSnapshot>,
    snapshot: [u8; 32],
    cap: u64,
) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    finalizable(&ctx.accounts.city, ctx.accounts.funding.week)?;
    require!(
        snapshot != [0; 32]
            && ctx.accounts.funding.snapshot == [0; 32]
            && !ctx.accounts.funding.published,
        ErrorCode::Stage1SnapshotFrozen
    );
    let week = ctx.accounts.funding.week;
    require!(ctx.accounts.cursor.next_week == week, ErrorCode::Stage1WeekNotFinalizable);
    // Retained optional ABI witness; continuity is now established by cursor.
    if let Some(previous) = ctx.accounts.previous.as_ref() {
        require!(
            previous.city == ctx.accounts.city.key()
                && previous.hill == ctx.accounts.hill.key()
                && previous.asset == ctx.accounts.asset.key()
                && previous.week.checked_add(1) == Some(week),
            ErrorCode::Stage1WeekNotFinalizable
        );
    }
    ctx.accounts.funding.snapshot = snapshot;
    ctx.accounts.funding.cash_sequence = ctx.accounts.cursor.cash_sequence;
    ctx.accounts.funding.cash_expected = ctx.accounts.cursor.active_cash_streams;
    ctx.accounts.funding.cap = cap;
    ctx.accounts.funding.frozen_at = Clock::get()?.unix_timestamp;
    Ok(())
}
pub fn prepare_hold(ctx: Context<Stage1PrepareHold>, remaining: [u64; S1_BUCKETS]) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let mut source = read_hold(&ctx.accounts.source.to_account_info(), &ctx.accounts.cursor)?;
    let target = &ctx.accounts.target;
    finalizable(&ctx.accounts.city, target.week)?;
    require!(
        ctx.accounts.cursor.next_week == target.week && source.published
            && source.week < target.week
            && target.week - source.week < S1_HELD_AGE
            && target.snapshot != [0; 32]
            && !target.published,
        ErrorCode::Stage1InvalidHold
    );
    validate_remaining(&source.holds, &remaining)?;
    source.proposed = true;
    source.proposal_week = target.week;
    source.proposal_snapshot = target.snapshot;
    source.proposal_revision = source.revision;
    source.proposal_remaining = remaining;
    store_hold(&ctx.accounts.source.to_account_info(), &mut ctx.accounts.cursor, &source)?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())
}
pub fn validate_remaining(before: &[u64; S1_BUCKETS], after: &[u64; S1_BUCKETS]) -> Result<()> {
    require!(
        bucket_sum(after)? <= bucket_sum(before)? && after[0] <= before[0],
        ErrorCode::Stage1InvalidHold
    );
    // A whole non-live pot may split when live. Existing named buckets can only
    // pay their recipients or become cap excess, never become another role.
    let new_pieces = (1..4).try_fold(0u64, |a, i| {
        a.checked_add(after[i].saturating_sub(before[i]))
            .ok_or(ErrorCode::Stage1Arithmetic)
    })?;
    require!(
        new_pieces <= before[0] - after[0],
        ErrorCode::Stage1InvalidHold
    );
    Ok(())
}
pub fn expire_hold(ctx: Context<Stage1ExpireHold>, week: u64) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    finalizable(&ctx.accounts.city, week)?;
    require!(
        ctx.accounts.cursor.next_week == week && ctx.accounts.target.week == week
            && ctx.accounts.target.snapshot != [0; 32]
            && !ctx.accounts.target.published,
        ErrorCode::Stage1WeekNotFinalizable
    );
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())?;
    let mut source = read_hold(&ctx.accounts.source.to_account_info(), &ctx.accounts.cursor)?;
    let before = bucket_sum(&source.holds)?;
    source.expire(week, &mut ctx.accounts.asset.ledger)?;
    ctx.accounts.cursor.transition_hold(source.week, before, 0)?;
    store_hold(&ctx.accounts.source.to_account_info(), &mut ctx.accounts.cursor, &source)?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())
}
pub fn prepare_claim_set(ctx: Context<Stage1PrepareClaims>, leaf_count: u32) -> Result<()> {
    let book = &ctx.accounts.funding;
    // An unfrozen empty book may still be skipped. Do not strand an unsealed
    // set behind the cursor by preparing it before the week becomes final.
    require!(!book.published && book.snapshot != [0; 32], ErrorCode::Stage1ClaimStorage);
    let info = ctx.accounts.claim_set.to_account_info();
    let mut set = if info.owner == &System::id() && info.data_is_empty() {
        Stage1ClaimSet { city: book.city, hill: book.hill, asset: book.asset, mint: book.mint,
            week: book.week, bump: ctx.bumps.claim_set, rent_payer: ctx.accounts.publisher.key(),
            storage_version: stage1_claim_storage::CLAIM_STORAGE_VERSION, ..Stage1ClaimSet::default() }
    } else { stage1::read_owned::<Stage1ClaimSet>(&info)? };
    require!(!set.sealed && set.storage_version == stage1_claim_storage::CLAIM_STORAGE_VERSION
        && set.city == book.city && set.hill == book.hill && set.asset == book.asset
        && set.mint == book.mint && set.week == book.week && set.bump == ctx.bumps.claim_set
        && set.paid == 0 && set.claimed_count == 0,
        ErrorCode::Stage1ClaimStorage);
    let size = 8 + Stage1ClaimSet::INIT_SPACE + stage1_claim_storage::tail_size(leaf_count)?;
    stage1_claim_storage::grow(&info, &ctx.accounts.publisher.to_account_info(),
        &ctx.accounts.system_program.to_account_info(), size,
        &[S1_CLAIMS, book.hill.as_ref(), book.mint.as_ref(), &book.week.to_le_bytes(), &[set.bump]])?;
    set.leaf_count = leaf_count;
    set.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])?;
    Ok(())
}

pub fn publish(
    ctx: Context<Stage1Publish>,
    root: [u8; 32],
    total: u128,
    leaf_count: u32,
    new_holds: [u64; S1_BUCKETS],
) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let set = &ctx.accounts.claim_set;
    stage1_claim_storage::ready(&set.to_account_info(), 8 + Stage1ClaimSet::INIT_SPACE, leaf_count, set.storage_version)?;
    require!(!set.sealed && set.leaf_count == leaf_count && set.paid == 0 && set.claimed_count == 0,
        ErrorCode::Stage1ClaimStorage);
    let book = &mut ctx.accounts.funding;
    finalizable(&ctx.accounts.city, book.week)?;
    require!(
        !book.published && book.snapshot != [0; 32] && ctx.accounts.cursor.next_week == book.week
            && book.cash_processed == book.cash_expected,
        ErrorCode::Stage1WeekNotFinalizable
    );
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())?;
    require!(
        leaf_count <= S1_MAX_LEAVES && total <= u64::MAX as u128,
        ErrorCode::Stage1InvalidProof
    );
    let context = context_json(crate::ID, book.city, book.hill, book.week, book.mint);
    if leaf_count == 0 {
        require!(
            total == 0 && root == empty_node(&context).hash,
            ErrorCode::Stage1InvalidProof
        );
    } else {
        require!(
            total >= leaf_count as u128 && total <= (leaf_count as u128) * (book.cap as u128),
            ErrorCode::Stage1AllocationCap
        );
    }
    let mut released = 0u128;
    let mut commitment = [0; 32];
    // Account keys in ascending byte order give a unique release commitment.
    let mut last = None;
    for info in ctx.remaining_accounts {
        require!(
            info.is_writable && last.map_or(true, |key: Pubkey| key < *info.key),
            ErrorCode::Stage1InvalidFunding
        );
        last = Some(*info.key);
        let mut source = read_hold(info, &ctx.accounts.cursor)?;
        require!(
            source.city == book.city && source.published && source.week < book.week,
            ErrorCode::Stage1InvalidFunding
        );
        let before_buckets = source.holds;
        let before_revision = source.revision;
        let before = bucket_sum(&source.holds)?;
        if book.week - source.week >= S1_HELD_AGE {
            source.expire(book.week, &mut ctx.accounts.asset.ledger)?;
        } else {
            require!(
                source.proposed
                    && source.proposal_week == book.week
                    && source.proposal_snapshot == book.snapshot
                    && source.proposal_revision == source.revision,
                ErrorCode::Stage1InvalidHold
            );
            validate_remaining(&source.holds, &source.proposal_remaining)?;
            let amount = before - bucket_sum(&source.proposal_remaining)?;
            released = plus(released, amount as u128)?;
            source.holds = source.proposal_remaining;
            source.changed()?;
        }
        ctx.accounts.cursor.transition_hold(source.week, before, bucket_sum(&source.holds)?)?;
        let before_bytes: Vec<u8> = before_buckets
            .iter()
            .flat_map(|v| v.to_be_bytes())
            .collect();
        let after_bytes: Vec<u8> = source.holds.iter().flat_map(|v| v.to_be_bytes()).collect();
        commitment = hashv(&[
            b"BR-stage1-v1:release\0",
            &commitment,
            info.key.as_ref(),
            &source.lineage,
            &source.week.to_be_bytes(),
            &before_revision.to_be_bytes(),
            &before_bytes,
            &after_bytes,
            &source.pool.to_be_bytes(),
        ])
        .to_bytes();
        store_hold(info, &mut ctx.accounts.cursor, &source)?;
    }
    let held = bucket_sum(&new_holds)?;
    require!(
        held <= book.available
            && plus(total, held as u128)? == plus(plus(book.available as u128, released)?, book.boost_released as u128)?,
        ErrorCode::Stage1InvalidFunding
    );
    ctx.accounts.cursor.finish_week(book.week, held)?;
    ctx.accounts.asset.ledger.publish(total as u64)?;
    book.holds = new_holds;
    book.available = 0;
    book.published = true;
    book.changed()?;
    let set = &mut ctx.accounts.claim_set;
    set.city = book.city;
    set.hill = book.hill;
    set.asset = book.asset;
    set.mint = book.mint;
    set.week = book.week;
    set.root = root;
    set.total = total;
    set.leaf_count = leaf_count;
    let audit = Stage1CashAudit { snapshot: book.snapshot, source_lineage: book.lineage,
        release_commitment: commitment, boost_commitment: book.boost_commitment, new_holds };
    let terms = Stage1ClaimTerms { cap: book.cap, frozen_at: book.frozen_at, audit_hash: audit.commitment()? };
    set.metadata_hash = terms.commitment(set.key());
    let event = Stage1CashPublished { claim_set: set.key(), city: set.city, hill: set.hill,
        mint: set.mint, week: set.week, root, total, leaf_count, rent_payer: set.rent_payer, terms, audit };
    ctx.accounts.cursor.publication_commitment = hashv(&[b"BR-stage1-v2:cash-publication\0",
        &ctx.accounts.cursor.publication_commitment, &event.try_to_vec()?]).to_bytes();
    emit!(event);
    set.sealed = true;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())
}
fn consume_claim(set: &mut Stage1ClaimSet, info: &AccountInfo, registration: &Stage1Recipient,
    destination: Pubkey, index: u32, person: Pubkey, amount: u64, proof: &[Stage1SumNode], terms: &Stage1ClaimTerms) -> Result<()> {
    require!(set.sealed, ErrorCode::Stage1ClaimStorage);
    stage1_claim_storage::ready(info, 8 + Stage1ClaimSet::INIT_SPACE, set.leaf_count, set.storage_version)?;
    require!(terms.commitment(*info.key) == set.metadata_hash, ErrorCode::Stage1InvalidProof);
    require!(registration.person == person && registration.registered_at <= terms.frozen_at
        && destination == registration.recipient, ErrorCode::Stage1InvalidRecipient);
    verify_proof(set, crate::ID, index, person, registration.recipient, amount, proof, terms.cap)?;
    stage1_claim_storage::mark(&mut info.try_borrow_mut_data()?[8 + Stage1ClaimSet::INIT_SPACE..],
        set.leaf_count, set.claimed_count, index)?;
    let paid = set.paid.checked_add(amount).ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(paid as u128 <= set.total, ErrorCode::Stage1Solvency);
    set.paid = paid;
    set.claimed_count += 1;
    Ok(())
}

pub fn claim(
    ctx: Context<Stage1Claim>,
    index: u32,
    person: Pubkey,
    amount: u64,
    proof: Vec<Stage1SumNode>,
    terms: Stage1ClaimTerms,
) -> Result<()> {
    require!(ctx.accounts.destination.key() != ctx.accounts.earnings.key(), ErrorCode::Stage1InvalidRecipient);
    let info = ctx.accounts.claim_set.to_account_info();
    consume_claim(&mut ctx.accounts.claim_set, &info, &ctx.accounts.registration,
        ctx.accounts.destination.owner, index, person, amount, &proof, &terms)?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())?;
    let mint = ctx.accounts.asset.mint;
    let bump = [ctx.accounts.asset.bump];
    token::transfer(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.earnings.to_account_info(),
                to: ctx.accounts.destination.to_account_info(),
                authority: ctx.accounts.asset.to_account_info(),
            },
            &[&[S1_ASSET, mint.as_ref(), &bump]],
        ),
        amount,
    )?;
    ctx.accounts.asset.ledger.claim(amount)?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())
}

pub fn claim_batch(ctx: Context<Stage1ClaimBatch>, person: Pubkey, leaves: Vec<Stage1CashBatchLeaf>) -> Result<()> {
    require!(!leaves.is_empty() && leaves.len() <= stage1_claim_storage::CLAIM_BATCH_LIMIT
        && leaves.len() == ctx.remaining_accounts.len(), ErrorCode::Stage1InvalidBatch);
    require!(ctx.accounts.destination.key() != ctx.accounts.earnings.key(), ErrorCode::Stage1InvalidRecipient);
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())?;
    let mut amount = 0u64;
    for (i, (leaf, info)) in leaves.iter().zip(ctx.remaining_accounts).enumerate() {
        require!(info.is_writable && !ctx.remaining_accounts[..i].iter().any(|a| a.key == info.key), ErrorCode::Stage1InvalidBatch);
        let mut set: Stage1ClaimSet = stage1::read_owned(info)?;
        require!(set.city == ctx.accounts.city.key() && set.asset == ctx.accounts.asset.key()
            && set.mint == ctx.accounts.asset.mint, ErrorCode::Stage1InvalidAsset);
        let expected = Pubkey::create_program_address(&[S1_CLAIMS, set.hill.as_ref(), set.mint.as_ref(),
            &set.week.to_le_bytes(), &[set.bump]], &crate::ID).map_err(|_| error!(ErrorCode::Stage1ClaimStorage))?;
        require_keys_eq!(expected, *info.key, ErrorCode::Stage1ClaimStorage);
        consume_claim(&mut set, info, &ctx.accounts.registration, ctx.accounts.destination.owner,
            leaf.index, person, leaf.amount, &leaf.proof, &leaf.terms)?;
        set.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])?;
        amount = amount.checked_add(leaf.amount).ok_or(ErrorCode::Stage1Arithmetic)?;
    }
    let mint = ctx.accounts.asset.mint;
    let bump = [ctx.accounts.asset.bump];
    token::transfer(CpiContext::new_with_signer(ctx.accounts.token_program.to_account_info(), Transfer {
        from: ctx.accounts.earnings.to_account_info(), to: ctx.accounts.destination.to_account_info(),
        authority: ctx.accounts.asset.to_account_info() }, &[&[S1_ASSET, mint.as_ref(), &bump]]), amount)?;
    ctx.accounts.asset.ledger.claim(amount)?;
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())
}

#[derive(Accounts)]
pub struct Stage1SetPublisher<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub admin: Signer<'info>,
}
#[derive(Accounts)]
pub struct Stage1InitSettlement<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(init_if_needed, payer = payer, space = 8 + Stage1SettlementCursor::INIT_SPACE,
        seeds = [S1_CURSOR, hill_account.hill.key().as_ref(), asset.mint.as_ref()], bump)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
pub struct Stage1SkipEmpty<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CURSOR, hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = hill, has_one = asset, constraint = cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    pub publisher: Signer<'info>,
}
#[derive(Accounts)]
#[instruction(week: u64)]
pub struct Stage1OpenWeek<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(init_if_needed, payer = payer, space = 8 + Stage1WeekFunding::INIT_SPACE,
        seeds = [S1_FUNDING, hill_account.hill.key().as_ref(), asset.mint.as_ref(), &week.to_le_bytes()], bump)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
    #[account(seeds = [S1_CURSOR, hill_account.hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == hill_account.hill.key() && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
}
#[derive(Accounts)]
pub struct Stage1RegisterRecipient<'info> {
    #[account(init, payer = payer, space = 8 + Stage1Recipient::INIT_SPACE, seeds = [S1_RECIPIENT, person.key().as_ref()], bump)]
    pub registration: Account<'info, Stage1Recipient>,
    pub person: Signer<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
pub struct Stage1FreezeSnapshot<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_FUNDING, hill.key().as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = funding.bump,
        has_one = city, has_one = hill, has_one = asset)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    pub previous: Option<Box<Account<'info, Stage1ClaimSet>>>,
    pub publisher: Signer<'info>,
    #[account(seeds = [S1_CURSOR, hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == hill.key() && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
}
#[derive(Accounts)]
pub struct Stage1PrepareHold<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    /// CHECK: live canonical book or exact closed-book witness in the cursor.
    #[account(mut)]
    pub source: UncheckedAccount<'info>,
    #[account(seeds = [S1_FUNDING, hill.key().as_ref(), asset.mint.as_ref(), &target.week.to_le_bytes()], bump = target.bump,
        has_one = city, has_one = hill, has_one = asset)]
    pub target: Box<Account<'info, Stage1WeekFunding>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    pub publisher: Signer<'info>,
    #[account(mut, seeds = [S1_CURSOR, hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == hill.key() && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
}
#[derive(Accounts)]
pub struct Stage1ExpireHold<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    /// CHECK: live canonical book or exact closed-book witness in the cursor.
    #[account(mut)]
    pub source: UncheckedAccount<'info>,
    #[account(seeds = [S1_FUNDING, hill.key().as_ref(), asset.mint.as_ref(), &target.week.to_le_bytes()], bump = target.bump,
        has_one = city, has_one = hill, has_one = asset)]
    pub target: Box<Account<'info, Stage1WeekFunding>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    pub publisher: Signer<'info>,
    #[account(mut, seeds = [S1_CURSOR, hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == hill.key() && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
}
#[derive(Accounts)]
pub struct Stage1PrepareClaims<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(seeds = [S1_FUNDING, funding.hill.as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = funding.bump,
        has_one = city, has_one = asset, constraint = funding.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    /// CHECK: canonical PDA; owner, unsealed header and allocation checked in handler.
    #[account(mut, seeds = [S1_CLAIMS, funding.hill.as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump)]
    pub claim_set: UncheckedAccount<'info>,
    #[account(mut)]
    pub publisher: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
pub struct Stage1Publish<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_FUNDING, hill_account.hill.key().as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = funding.bump,
        has_one = city, has_one = asset, constraint = funding.hill == hill_account.hill.key() @ ErrorCode::Stage1InvalidHill)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    #[account(mut, seeds = [S1_CLAIMS, hill_account.hill.key().as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = claim_set.bump,
        has_one = city, has_one = asset, constraint = claim_set.hill == hill_account.hill.key() && claim_set.mint == asset.mint
        && claim_set.week == funding.week @ ErrorCode::Stage1InvalidFunding)]
    pub claim_set: Box<Account<'info, Stage1ClaimSet>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub publisher: Signer<'info>,
    pub system_program: Program<'info, System>,
    #[account(mut, seeds = [S1_CURSOR, hill_account.hill.key().as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == hill_account.hill.key() && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
}
#[derive(Accounts)]
#[instruction(index: u32, person: Pubkey)]
pub struct Stage1Claim<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CLAIMS, claim_set.hill.as_ref(), asset.mint.as_ref(), &claim_set.week.to_le_bytes()], bump = claim_set.bump,
        has_one = city, has_one = asset, constraint = claim_set.mint == asset.mint @ ErrorCode::Stage1InvalidAsset)]
    pub claim_set: Box<Account<'info, Stage1ClaimSet>>,
    #[account(seeds = [S1_RECIPIENT, person.as_ref()], bump = registration.bump)]
    pub registration: Account<'info, Stage1Recipient>,
    #[account(mut, seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = asset.mint)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(person: Pubkey)]
pub struct Stage1ClaimBatch<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(seeds = [S1_RECIPIENT, person.as_ref()], bump = registration.bump)]
    pub registration: Account<'info, Stage1Recipient>,
    #[account(mut, seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = asset.mint)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

/// Permissionless rent recovery; original refund owner and publication guards
/// are immutable. The permanent cursor prevents recreating a closed week.
pub fn close_claim_set(ctx: Context<Stage1CloseClaims>) -> Result<()> {
    let set = &ctx.accounts.claim_set;
    stage1_claim_storage::ready(&set.to_account_info(), 8 + Stage1ClaimSet::INIT_SPACE, set.leaf_count, set.storage_version)?;
    stage1_claim_storage::fully_claimed(set.sealed, set.paid, set.total, set.claimed_count, set.leaf_count)
}
#[derive(Accounts)]
pub struct Stage1CloseClaims<'info> {
    #[account(mut, close = rent_payer, seeds = [S1_CLAIMS, claim_set.hill.as_ref(), claim_set.mint.as_ref(), &claim_set.week.to_le_bytes()],
        bump = claim_set.bump, has_one = rent_payer)]
    pub claim_set: Box<Account<'info, Stage1ClaimSet>>,
    /// CHECK: immutable refund address, never a signer or source of authority.
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,
}

/// No token or lifetime ledger changes: holds move to the permanent cursor,
/// while paid/expired values already live in the permanent asset ledger.
pub fn close_week_funding(ctx: Context<Stage1CloseWeekFunding>) -> Result<()> {
    let book = &ctx.accounts.funding;
    require!(ctx.accounts.cursor.next_week > book.week && book.available == 0,
        ErrorCode::Stage1ClaimStorage);
    require_absent(&ctx.accounts.claim_set.to_account_info())?;
    if book.published {
        require!(book.cash_processed == book.cash_expected, ErrorCode::Stage1InvalidFunding);
        ctx.accounts.cursor.carry_closed_holds(book.key(), book)?;
    } else {
        // The cursor crossed this untouched book through skip_empty.
        require!(book.harvested_net == 0 && book.admitted_cash == 0 && book.lineage == [0; 32]
            && book.boost_released == 0 && book.cash_processed == 0
            && book.snapshot == [0; 32] && !book.proposed
            && book.holds == [0; S1_BUCKETS] && book.pool == 0, ErrorCode::Stage1InvalidFunding);
    }
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())
}

#[derive(Accounts)]
pub struct Stage1CloseWeekFunding<'info> {
    #[account(mut, close = rent_payer, seeds = [S1_FUNDING, funding.hill.as_ref(), funding.mint.as_ref(), &funding.week.to_le_bytes()],
        bump = funding.bump, has_one = asset, has_one = rent_payer,
        constraint = funding.city == asset.city && funding.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    #[account(mut, seeds = [S1_CURSOR, funding.hill.as_ref(), funding.mint.as_ref()], bump = cursor.bump,
        has_one = asset, constraint = cursor.city == funding.city && cursor.hill == funding.hill && cursor.mint == funding.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
    #[account(seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    /// CHECK: exact canonical set must have closed, or never existed in a skipped week.
    #[account(seeds = [S1_CLAIMS, funding.hill.as_ref(), funding.mint.as_ref(), &funding.week.to_le_bytes()], bump)]
    pub claim_set: UncheckedAccount<'info>,
    /// CHECK: immutable original funding-account payer.
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,
}
