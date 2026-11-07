//! Publisher-prepaid index bitmap. Publisher allocation owns person uniqueness.
use super::*;
use anchor_lang::solana_program::{program::invoke_signed, system_instruction};

pub const CLAIM_STORAGE_VERSION: u8 = 2;
pub const CLAIM_GROWTH: usize = 10_240;
pub const CLAIM_BATCH_LIMIT: usize = 4;

pub fn tail_size(leaves: u32) -> Result<usize> {
    require!(leaves <= S1_MAX_LEAVES, ErrorCode::Stage1InvalidProof);
    let n = leaves as usize;
    Ok((n + 7) / 8)
}

pub fn ready(info: &AccountInfo, header: usize, leaves: u32, version: u8) -> Result<()> {
    require!(version == CLAIM_STORAGE_VERSION && info.data_len() == header + tail_size(leaves)?,
        ErrorCode::Stage1ClaimStorage);
    Ok(())
}

/// Only called after the canonical PDA and unsealed header have been checked.
/// Prefunding cannot reserve the namespace. Capacity corrections keep excess
/// lamports in the account; no withdrawal or refund authority is introduced.
pub fn grow<'info>(info: &AccountInfo<'info>, payer: &AccountInfo<'info>, system: &AccountInfo<'info>,
    required: usize, seeds: &[&[u8]]) -> Result<()> {
    let fresh = info.owner == &System::id();
    require!(!info.executable && (fresh && info.data_is_empty() || info.owner == &crate::ID),
        ErrorCode::Stage1ClaimStorage);
    let next = required.min(info.data_len().saturating_add(CLAIM_GROWTH));
    let top_up = Rent::get()?.minimum_balance(next).saturating_sub(info.lamports());
    if top_up > 0 {
        anchor_lang::system_program::transfer(CpiContext::new(system.clone(),
            anchor_lang::system_program::Transfer { from: payer.clone(), to: info.clone() }), top_up)?;
    }
    if fresh {
        invoke_signed(&system_instruction::allocate(info.key, next as u64),
            &[info.clone(), system.clone()], &[seeds])?;
        invoke_signed(&system_instruction::assign(info.key, &crate::ID),
            &[info.clone(), system.clone()], &[seeds])?;
    } else if next != info.data_len() {
        info.realloc(next, true)?;
    }
    Ok(())
}

/// Each index is payable once; a duplicated person is a publisher allocation
/// error, still bounded by the committed Merkle sum and funded custody.
pub fn mark(data: &mut [u8], leaves: u32, count: u32, index: u32) -> Result<()> {
    require!(data.len() == tail_size(leaves)? && index < leaves, ErrorCode::Stage1ClaimStorage);
    let byte = index as usize / 8;
    let mask = 1 << (index % 8);
    require!(data[byte] & mask == 0, ErrorCode::Stage1ClaimReplay);
    require!(count < leaves, ErrorCode::Stage1Solvency);
    data[byte] |= mask;
    Ok(())
}

pub fn fully_claimed(sealed: bool, paid: u64, total: u128, count: u32, leaves: u32) -> Result<()> {
    require!(sealed && paid as u128 == total && count == leaves, ErrorCode::Stage1ClaimStorage);
    Ok(())
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Stage1BatchLeaf {
    pub index: u32,
    pub amount: u64,
    pub proof: Vec<Stage1SumNode>,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn round2_storage_is_only_an_index_bitmap() {
        assert_eq!(tail_size(10).unwrap(), 2);
        assert_eq!(tail_size(65536).unwrap(), 8192);
    }
    #[test]
    fn all_indices_once_in_both_orders() {
        for reverse in [false, true] {
            let mut tail = vec![0; tail_size(1000).unwrap()];
            let mut indices: Vec<u32> = (0..1000).collect();
            if reverse { indices.reverse(); }
            for (count, index) in indices.into_iter().enumerate() {
                mark(&mut tail, 1000, count as u32, index).unwrap();
                let before = tail.clone();
                assert!(mark(&mut tail, 1000, count as u32 + 1, index).is_err());
                assert_eq!(tail, before);
            }
            assert!(tail.iter().all(|b| *b == 255));
        }
    }
    #[test]
    fn malformed_bitmap_and_partial_close_refuse() {
        assert!(tail_size(65537).is_err());
        assert!(mark(&mut [0; 1], 16, 0, 0).is_err());
        assert!(mark(&mut [0; 1], 8, 0, 8).is_err());
        assert!(fully_claimed(true, 9, 10, 2, 2).is_err());
        assert!(fully_claimed(true, 10, 10, 1, 2).is_err());
        assert!(fully_claimed(false, 0, 0, 0, 0).is_err());
        fully_claimed(true, 0, 0, 0, 0).unwrap();
        fully_claimed(true, 10, 10, 2, 2).unwrap();
    }
}
