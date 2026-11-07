import { describe, expect, it } from 'vitest';
import { describeExplorerEvent, extractEventReferences, summarizeTransaction } from './explorer';

describe('V2 completion event narratives', () => {
  it('renders exact tribute evidence without exposing the V2 event name as copy', () => {
    const story = describeExplorerEvent({
      tx_signature: 'signature',
      event_index: 0,
      event_name: 'ClimbCompletedV2',
      fields: {
        evidence_version: 2,
        vault_id: '9',
        time_s: 321,
        cal_tributed: '11000000000',
        is_new_kom: false,
      },
      slot: '123',
      block_time: 1_700_000_000,
    });

    expect(story.title).toBe('Completed Climb #9 in 5:21');
    expect(story.detail).toContain('tributed 11 CAL');
    expect(story.highlights).toContain('Evidence V2');
    expect(story.title).not.toContain('V2');
  });

  it('renders the credited Settlement Week for V2 flow evidence', () => {
    const story = describeExplorerEvent({
      tx_signature: 'signature',
      event_index: 1,
      event_name: 'ClimbCompletionFlowAssignedV2',
      fields: {
        evidence_version: 2,
        vault_id: '9',
        credited_settlement_week: '44',
        cal_tributed: '11000000000',
      },
      slot: '123',
      block_time: 1_700_000_000,
    });

    expect(story.title).toBe('Settlement flow assigned for Climb #9');
    expect(story.detail).toContain('11 CAL entered Settlement Week 44');
    expect(story.highlights).toContain('Evidence V2');
  });
});

describe('settlement event narratives', () => {
  it('uses compact Leaderboard language for weekly settlement', () => {
    const story = describeExplorerEvent({
      tx_signature: 'signature',
      event_index: 0,
      event_name: 'EpochRewardsDistributed',
      fields: {
        vault_id: 12,
        epoch: 14,
        total_distributed: '4200000000000',
        staker_distributed: '720000000000',
        local_legend_distributed: '126000000000',
      },
      slot: '123',
      block_time: 1_700_000_000,
    });

    expect(story.title).toBe('Climb #12 settlement');
    expect(story.detail).toBe('4,200 DUNG distributed in Week 14.');
    expect(story.highlights).toContain('Stakers 720 DUNG');
    expect(story.highlights).toContain('Local Legend 126 DUNG');
    expect(story.highlights).toContain('Week 14');
  });

  it('describes the one-time historical movement as a balance sweep', () => {
    const story = describeExplorerEvent({
      tx_signature: 'signature',
      event_index: 1,
      event_name: 'StakerRemainderPolicyApplied',
      fields: {
        vault_id: 12,
        settlement_week: 14,
        policy_version: 1,
        current_locked_reallocated: '540000000000',
        legacy_carry_reallocated: '2673',
      },
      slot: '123',
      block_time: 1_700_000_000,
    });

    expect(story.title).toBe('Staker balance sweep');
    expect(story.detail).toContain('Prior staker balance');
    expect(story.detail).toContain('Leaderboard pool');
    expect(story.detail).toContain('Week 14');
  });

  it('does not narrate event and instruction counts already shown in chain details', () => {
    const event = {
      tx_signature: 'signature',
      event_index: 0,
      event_name: 'EpochRewardsDistributed',
      fields: {
        vault_id: 12,
        epoch: 14,
        total_distributed: '4200000000000',
      },
      slot: '123',
      block_time: 1_700_000_000,
    };
    const story = summarizeTransaction({
      signature: 'signature',
      slot: '123',
      block_time: 1_700_000_000,
      status: 'success',
      fee_lamports: '5000',
      compute_units: '192224',
      instructions: [
        { instruction_index: 0, name: 'settle_week_v4_b', args: {}, accounts: {} },
      ],
      events: [event, { ...event, event_index: 1 }],
      token_flows: [],
    });

    expect(story.detail).toBe('4,200 DUNG distributed in Week 14.');
    expect(story.detail).not.toContain('signature emitted');
    expect(story.detail).not.toContain('indexed instruction');
  });
});


describe('attested climb references', () => {
  it('links the resolved canon UUID, never a raw Vault zero or generic id', () => {
    const event = { tx_signature: 'sig', event_index: 0, event_name: 'VaultCreated', fields: { id: 0 }, slot: 1, block_time: 1 };
    expect(extractEventReferences(event)).toEqual([]);
    expect(describeExplorerEvent(event).title).toBe('');
    expect(describeExplorerEvent(event).detail).toBe('');
    expect(extractEventReferences({ ...event, climb_id: '11111111-1111-4111-8111-111111111111' })).toEqual([
      { kind: 'climb', label: 'Climb', value: '11111111-1111-4111-8111-111111111111' },
    ]);
  });
});
