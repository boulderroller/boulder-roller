import { describe, expect, it } from 'vitest';
import { classifySearchInput, searchFailureMessage, searchTarget } from './search';

describe('classifySearchInput', () => {
  it('routes numeric input to climb pages', () => {
    expect(classifySearchInput('142')).toEqual({ type: 'climb', value: '142' });
  });

  it('supports prefixed climb/vault aliases and account searches', () => {
    const pubkey = 'Gk4mA2yq8wtN2P2gS9f6q4b1nJ7tW3eK5vH9cLmR1Zq';
    expect(classifySearchInput('climb:142')).toEqual({ type: 'climb', value: '142' });
    expect(classifySearchInput('vault:142')).toEqual({ type: 'climb', value: '142' });
    expect(classifySearchInput(`account:${pubkey}`)).toEqual({ type: 'account', value: pubkey });
  });

  it('routes 32-44 char base58 strings to account pages', () => {
    const pubkey = 'Gk4mA2yq8wtN2P2gS9f6q4b1nJ7tW3eK5vH9cLmR1Zq';
    expect(classifySearchInput(pubkey)).toEqual({ type: 'account', value: pubkey });
  });

  it('routes base58 strings longer than 44 chars to transaction pages', () => {
    const signature = '3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh';
    expect(classifySearchInput(signature)).toEqual({ type: 'transaction', value: signature });
  });

  it('supports explorer URLs and route paths', () => {
    const signature = '3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh';
    expect(classifySearchInput('https://scan.boulderroller.xyz/climb/8')).toEqual({ type: 'climb', value: '8' });
    expect(classifySearchInput('https://scan.boulderroller.xyz/vault/8')).toEqual({ type: 'climb', value: '8' });
    expect(classifySearchInput(`/tx/${signature}`)).toEqual({ type: 'transaction', value: signature });
  });

  it('supports username lookups', () => {
    expect(classifySearchInput('@alpha_code_3')).toEqual({ type: 'username', value: 'alpha_code_3' });
    expect(classifySearchInput('rider:mountain_goat')).toEqual({ type: 'username', value: 'mountain_goat' });
  });

  it('rejects non-base58 search values', () => {
    expect(classifySearchInput('not a tx signature')).toBeNull();
    expect(classifySearchInput('@alpha-code-3')).toBeNull();
  });
});

describe('searchTarget', () => {
  it('returns the correct route for each match type', () => {
    expect(searchTarget('142')).toBe('/climb/142');
    expect(searchTarget('Gk4mA2yq8wtN2P2gS9f6q4b1nJ7tW3eK5vH9cLmR1Zq')).toBe(
      '/account/Gk4mA2yq8wtN2P2gS9f6q4b1nJ7tW3eK5vH9cLmR1Zq'
    );
    expect(
      searchTarget('3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh')
    ).toBe('/tx/3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh');
  });

  it('returns null for username searches because they require profile resolution', () => {
    expect(searchTarget('@alpha_code_3')).toBeNull();
  });
});

describe('searchFailureMessage', () => {
  it('uses rider-specific copy for unresolved public usernames', () => {
    expect(
      searchFailureMessage(
        Object.assign(new Error('Not found'), { status: 404 }),
        { type: 'username', value: 'dungbeetlephoenix' }
      )
    ).toBe('No public rider found for @dungbeetlephoenix.');
  });

  it('keeps generic API errors for non-username searches', () => {
    expect(
      searchFailureMessage(
        new Error('Transaction unavailable'),
        { type: 'transaction', value: '3'.repeat(88) }
      )
    ).toBe('Transaction unavailable');
  });
});
