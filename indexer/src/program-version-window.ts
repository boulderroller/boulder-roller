/**
 * The version window is explicit; future releases must choose theirs. 0x4C is
 * legacy-only; Stage 1 is available at 0x4D and at 0x4E, which adds no Stage 1
 * surface. Ship services that accept a new version before the chain advances.
 */
export const SUPPORTED_PROGRAM_VERSIONS: readonly number[] = [0x4c, 0x4d, 0x4e];
export const STAGE1_PROGRAM_VERSIONS: readonly number[] = [0x4d, 0x4e];
export const STAGE1_UNAVAILABLE = 'Stage 1 is not available on this network';

export function requireProgramVersionByte(observed: unknown): number {
  if (!Number.isInteger(observed) || typeof observed !== 'number' || observed < 0 || observed > 255) {
    throw new Error('ProgramConfig version must be an unsigned byte');
  }
  return observed;
}

export function requireCompatibleProgramVersion(observed: unknown): number {
  const version = requireProgramVersionByte(observed);
  if (!SUPPORTED_PROGRAM_VERSIONS.includes(version)) {
    const expected = SUPPORTED_PROGRAM_VERSIONS.map(v => `0x${v.toString(16)}`).join(', ');
    throw new Error(`ProgramConfig version mismatch: expected ${expected}; got 0x${version.toString(16).padStart(2, '0')}`);
  }
  return version;
}

export class ProgramVersionWindow {
  private highest: number | null = null;
  private failure: Error | null = null;
  get programVersion(): number | null { return this.highest; }
  get stage1Available(): boolean {
    return this.failure === null && this.highest !== null && STAGE1_PROGRAM_VERSIONS.includes(this.highest);
  }

  invalidate(error: unknown): void {
    this.failure = error instanceof Error ? error : new Error(String(error));
  }

  observe(observed: unknown): number {
    try {
      const version = requireCompatibleProgramVersion(observed);
      if (this.highest !== null && version < this.highest) {
        throw new Error(`ProgramConfig version downgrade: saw 0x${this.highest.toString(16)}, got 0x${version.toString(16)}`);
      }
      this.highest = version;
      this.failure = null;
      return version;
    } catch (error) {
      this.failure = error as Error;
      throw error;
    }
  }

  requireStage1(): void {
    this.assertNoFailure();
    if (!this.stage1Available) throw new Error(STAGE1_UNAVAILABLE);
  }

  assertNoFailure(): void {
    if (this.failure) throw this.failure;
  }

  status() {
    this.assertNoFailure();
    return {
      program_version: this.programVersion,
      stage1: this.stage1Available ? 'available' : 'not available on this network',
    };
  }
}

export const programVersionWindow = new ProgramVersionWindow();

// These Stage 1 entrypoints predate the Stage1 name convention. All other
// Stage 1 instructions/events and account types carry that name explicitly.
export const STAGE1_UNPREFIXED_INSTRUCTION_NAMES = [
  'pledge', 'bond', 'initCityConfig', 'configureAsset', 'initHillBond',
  'refreshCampaignLot', 'convertExcludedPledge', 'cancelPledge', 'withdrawPrebond',
  'requestWithdrawal', 'cancelWithdrawal', 'beginWithdrawal', 'completeWithdrawal',
] as const;
const STAGE1_UNPREFIXED_INSTRUCTIONS = new Set<string>(STAGE1_UNPREFIXED_INSTRUCTION_NAMES);
export function isStage1Instruction(name: string): boolean {
  return name.includes('Stage1') || STAGE1_UNPREFIXED_INSTRUCTIONS.has(name);
}
