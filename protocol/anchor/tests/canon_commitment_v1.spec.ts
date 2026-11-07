import { expect } from 'chai';
import { createHash } from 'node:crypto';
import { PublicKey } from '@solana/web3.js';
import boulderRollersIdl from '../idl/boulder_rollers.json' with { type: 'json' };

const PROGRAM_ID = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const EXPECTED_COMMITMENT =
  '0100112233445566778899aabbccddeeff01020000000000000000000000000000' +
  '0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';
const EXPECTED_COMMITMENT_HASH =
  '52badf1370ae44b876a6d10ccdae1397e5f4a315900c91ddcb4f1b89e776e3c0';

function canonCommitmentV1(
  canonId: Buffer,
  canonVersion: number,
  canonicalProfileHash: Buffer,
): Buffer {
  if (
    canonId.length !== 16 ||
    !canonId.some((byte) => byte !== 0) ||
    canonVersion <= 0 ||
    canonVersion > 0xffff ||
    canonicalProfileHash.length !== 32 ||
    !canonicalProfileHash.some((byte) => byte !== 0)
  ) {
    throw new Error('invalid canon commitment input');
  }

  const commitment = Buffer.alloc(64);
  commitment[0] = 0x01;
  canonId.copy(commitment, 1);
  commitment.writeUInt16BE(canonVersion, 17);
  canonicalProfileHash.copy(commitment, 32);
  return commitment;
}

describe('canon commitment v1', () => {
  it('matches the frozen Rust/Python D12 vector and commitment PDA', () => {
    const canonId = Buffer.from('00112233445566778899aabbccddeeff', 'hex');
    const profileHash = Buffer.from(Array.from({ length: 32 }, (_, index) => index));
    const commitment = canonCommitmentV1(canonId, 0x0102, profileHash);
    const commitmentHash = createHash('sha256').update(commitment).digest();
    const [climb] = PublicKey.findProgramAddressSync(
      [Buffer.from('climb'), commitmentHash],
      PROGRAM_ID,
    );

    expect(commitment.toString('hex')).to.equal(EXPECTED_COMMITMENT);
    expect(commitmentHash.toString('hex')).to.equal(EXPECTED_COMMITMENT_HASH);
    expect(commitment.subarray(19, 32).equals(Buffer.alloc(13))).to.equal(true);
    expect(climb.toBase58()).to.equal('GQp1tqDpnwKZJHDB4WnEdjj2YQmkJNMT3ro1NiCsWMFg');
  });

  it('rejects zero or malformed identity components', () => {
    expect(() => canonCommitmentV1(Buffer.alloc(16), 1, Buffer.alloc(32, 1))).to.throw(
      'invalid canon commitment input',
    );
    expect(() => canonCommitmentV1(Buffer.alloc(16, 1), 0, Buffer.alloc(32, 1))).to.throw(
      'invalid canon commitment input',
    );
    expect(() => canonCommitmentV1(Buffer.alloc(16, 1), 1, Buffer.alloc(32))).to.throw(
      'invalid canon commitment input',
    );
  });

  it('publishes writable predecessor linkage and Climb-gated creation accounts', () => {
    const instructions = (boulderRollersIdl as any).instructions as Array<any>;
    const registration = instructions.find(({ name }) => name === 'registerRatifiedClimb');
    const predecessor = registration?.accounts.find(
      ({ name }: { name: string }) => name === 'predecessorClimb',
    );
    expect(predecessor?.isMut).to.equal(true);
    expect(predecessor?.isOptional).to.equal(true);

    for (const name of ['createVault', 'createVaultWithUsdc']) {
      const instruction = instructions.find((candidate) => candidate.name === name);
      const climb = instruction?.accounts.find(
        ({ name: accountName }: { name: string }) => accountName === 'climb',
      );
      expect(climb?.isMut, `${name} must write the one-shot Climb linkage`).to.equal(true);
      const leaderboard = instruction?.accounts.find(
        ({ name: accountName }: { name: string }) => accountName === 'vaultLeaderboard',
      );
      expect(
        leaderboard?.isMut,
        `${name} must initialize the empty Record Board before activation`,
      ).to.equal(true);
    }

    const climbType = (boulderRollersIdl as any).accounts.find(
      ({ name }: { name: string }) => name === 'Climb',
    );
    expect(climbType?.type.fields.some(
      ({ name }: { name: string }) => name === 'successorClimb',
    )).to.equal(true);
  });
});
