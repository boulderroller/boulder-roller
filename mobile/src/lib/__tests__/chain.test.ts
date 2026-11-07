import {
  formatTokenAmount,
  getCalBalance,
  sumParsedTokenAccounts,
} from '../chain';
import { PublicKey, type Connection } from '@solana/web3.js';
import { SOLANA_PROGRAM_ID } from '../../constants/config';
import {
  CURRENT_PROGRAM_VERSION,
} from '../../generated/boulderRollersProgramVersion';

function programConfigData(programVersion: number): Buffer {
  const data = Buffer.alloc(75);
  Buffer.from('c4d25ae790958c3f', 'hex').copy(data, 0);
  data[72] = programVersion;
  data[73] = 1;
  return data;
}

function chainConnection(programVersion: number): {
  connection: Connection;
  tokenAccountReads: jest.Mock;
} {
  const programId = new PublicKey(SOLANA_PROGRAM_ID);
  const tokenAccountReads = jest.fn(async () => ({
    value: [
      {
        account: {
          data: {
            parsed: {
              info: {
                tokenAmount: { amount: '1000000000', decimals: 9 },
              },
            },
          },
        },
      },
    ],
  }));
  return {
    connection: {
      getAccountInfo: jest.fn(async () => ({
        owner: programId,
        data: programConfigData(programVersion),
      })),
      getParsedTokenAccountsByOwner: tokenAccountReads,
    } as unknown as Connection,
    tokenAccountReads,
  };
}

describe('chain token helpers', () => {
  test('formats raw token units without floating point rounding', () => {
    expect(formatTokenAmount('123450000000', 9)).toBe('123.45');
    expect(formatTokenAmount('1000000000', 9)).toBe('1');
    expect(formatTokenAmount('1', 9)).toBe('0.000000001');
  });

  test('sums parsed token accounts for one owner/mint', () => {
    const result = sumParsedTokenAccounts([
      {
        account: {
          data: {
            parsed: {
              info: {
                tokenAmount: { amount: '1000000000', decimals: 9 },
              },
            },
          },
        },
      },
      {
        account: {
          data: {
            parsed: {
              info: {
                tokenAmount: { amount: '2500000000', decimals: 9 },
              },
            },
          },
        },
      },
    ]);

    expect(result).toEqual({
      rawAmount: '3500000000',
      decimals: 9,
      uiAmountString: '3.5',
      accountCount: 2,
    });
  });

  test('empty owner balance is represented as zero', () => {
    expect(sumParsedTokenAccounts([])).toEqual({
      rawAmount: '0',
      decimals: 0,
      uiAmountString: '0',
      accountCount: 0,
    });
  });

  test('mixed decimals fail closed', () => {
    expect(() =>
      sumParsedTokenAccounts([
        {
          account: {
            data: {
              parsed: {
                info: {
                  tokenAmount: { amount: '1', decimals: 6 },
                },
              },
            },
          },
        },
        {
          account: {
            data: {
              parsed: {
                info: {
                  tokenAmount: { amount: '1', decimals: 9 },
                },
              },
            },
          },
        },
      ]),
    ).toThrow('mixed decimals');
  });

  test('CAL verification rejects an incompatible program before reading token accounts', async () => {
    const { connection, tokenAccountReads } = chainConnection(
      CURRENT_PROGRAM_VERSION ^ 0x01,
    );

    await expect(getCalBalance(PublicKey.default.toBase58(), connection)).rejects.toThrow(
      'ProgramConfig version mismatch',
    );
    expect(tokenAccountReads).not.toHaveBeenCalled();
  });

  test('CAL verification reads token accounts after exact program compatibility', async () => {
    const { connection, tokenAccountReads } = chainConnection(
      CURRENT_PROGRAM_VERSION,
    );

    await expect(
      getCalBalance(PublicKey.default.toBase58(), connection),
    ).resolves.toMatchObject({
      rawAmount: '1000000000',
      uiAmountString: '1',
    });
    expect(tokenAccountReads).toHaveBeenCalledTimes(1);
  });
});
