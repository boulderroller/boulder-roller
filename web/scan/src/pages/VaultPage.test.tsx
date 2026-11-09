vi.mock('@/components/ground/ObservatoryGround',()=>({default:()=>null}));
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { fixtureClimb, fixtureClimbWithVault } from '@/fixtures/data';
import { ClimbPageContent } from './VaultPage';

function renderClimb(data = fixtureClimb): string {
  return renderToStaticMarkup(
    <StaticRouter location={`/climb/${data.climb.id}`}>
      <ClimbPageContent data={data} id={data.climb.id} />
    </StaticRouter>
  );
}

describe('canonical climb detail contract', () => {
  it('renders the exact no-Vault indexer response without inventing a numeric Vault fallback', () => {
    const markup = renderClimb();

    expect(fixtureClimb.vault).toBeNull();
    expect(fixtureClimb.climb.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(markup).toContain('Manayunk Wall');
    expect(markup).toContain('547 m');
    expect(markup).toContain('59 m');
    expect(markup).toContain('10.9%');
    expect(markup).not.toContain('Not attached');
    expect(markup).not.toContain('No Leaderboard entries yet');
    expect(markup).not.toContain('Canonical registry projection');
    expect(markup).not.toContain('Proof Material');
    expect(markup).not.toContain('Climb #142');
    expect(markup).toContain('data-climb-identity');
    for (const label of ['Leaderboard', 'Local Legend', 'Completions', 'Positions', 'Settlements', 'Registration']) expect(markup).toContain(label);
  });

  it('renders an exact-active Vault only when the canonical response attaches one', () => {
    const markup = renderClimb(fixtureClimbWithVault);

    expect(fixtureClimbWithVault.climb.has_vault).toBe(true);
    expect(fixtureClimbWithVault.vault?.id).toBe(142);
    expect(markup).not.toContain('Vault Balances');
    expect(markup).not.toContain('All-time fastest recorded rides');
    expect(markup).toContain('Registration');
    expect(markup).not.toContain('data-climb-figure='); // Compatibility values never fill the new page.
  });
});
