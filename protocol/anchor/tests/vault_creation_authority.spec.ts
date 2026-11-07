import { expect } from 'chai';
import * as fs from 'fs';
import * as path from 'path';

const workspace = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const programDir = path.join(workspace, 'programs', 'boulder_rollers', 'src');
const programSource = fs.readdirSync(programDir)
  .filter((name) => name.endsWith('.rs'))
  .sort()
  .map((name) => fs.readFileSync(path.join(programDir, name), 'utf8'))
  .join('\n');

function instructionBody(start: string, end: string): string {
  const startIndex = programSource.indexOf(start);
  const endIndex = programSource.indexOf(end, startIndex + start.length);
  expect(startIndex, `${start} must exist`).to.be.greaterThan(-1);
  expect(endIndex, `${end} must follow ${start}`).to.be.greaterThan(startIndex);
  return programSource.slice(startIndex, endIndex);
}

describe('canonical Vault creation authority', () => {
  it('requires the configured backend sponsor before either wallet-funded constructor mutates the global counter', () => {
    const dung = instructionBody(
      'pub fn create_vault<',
      'pub fn create_vault_with_usdc<',
    );
    const usdc = instructionBody(
      'pub fn create_vault_with_usdc<',
      'pub fn initialize_vault_lp_mint',
    );
    const guard = [
      'require_backend_vault_creation_sponsor(',
      'config.backend_authority,',
      'ctx.accounts.sponsor_authority.key(),',
    ];

    for (const body of [dung, usdc]) {
      for (const line of guard) expect(body).to.contain(line);
      expect(body.indexOf('require_backend_vault_creation_sponsor(')).to.be.lessThan(
        body.indexOf('counter.count = counter.count.checked_add(1)'),
      );
    }
  });

  it('has no reservation-free backend constructor', () => {
    for (const removed of ['pub fn admin_create_vault', 'pub fn create_vault_from_balance_cal_usdc']) {
      expect(programSource).not.to.contain(removed);
    }
  });
});
