import test from 'node:test';
import assert from 'node:assert/strict';
import {PARTLY_COUNTED_COPY, ALREADY_COUNTED_COPY, getRideEffortTrimCopy, getRideProofStateCopy, getRideProofUiState} from '../src/lib/protocolStates.ts';

test('Tim copy slots remain empty without replacing existing state copy', () => {
  assert.equal(PARTLY_COUNTED_COPY, '');
  assert.equal(ALREADY_COUNTED_COPY, '');
  const input = {rewardPolicy: 'not_counted', coveredEffortSeconds: 3600, paidEffortSeconds: 0};
  assert.equal(getRideEffortTrimCopy(input), '');
  for (const extra of [{}, {finalizedAt: '2026-09-08T20:00:00Z'}, {attestationStatus: 'attested'}]) {
    assert.equal(getRideProofUiState({...input, ...extra}), 'not_counted');
    assert.deepEqual(getRideProofStateCopy({...input, ...extra}), {
      label: 'Not counted', detail: 'Logged. No CAL was counted.',
    });
  }
  assert.equal(getRideEffortTrimCopy({...input, paidEffortSeconds: null}), '');
});

test('other review and route-only reasons retain their copy', () => {
  assert.equal(getRideProofUiState({reviewReason: 'canonical_mismatch'}), 'needs_review');
  assert.deepEqual(getRideProofStateCopy({reviewReason: 'effort_source_route_estimate_only'}), {
    label: 'Saved', detail: 'Logged. Effort data needed before CAL.',
  });
});

test('empty trim slots preserve ordinary finalized and counting detail', () => {
  for (const input of [{finalizedAt: '2026-09-08T20:00:00Z'}, {status: 'processing'}]) {
    assert.deepEqual(getRideProofStateCopy({...input, rewardPolicy: 'rewardable', coveredEffortSeconds: 600, paidEffortSeconds: 3000}), getRideProofStateCopy(input));
  }
});

test('uncovered not-counted finality keeps its existing state', () => {
  assert.equal(getRideProofUiState({rewardPolicy: 'not_counted', finalizedAt: '2026-09-08T20:00:00Z'}), 'finalized');
});
