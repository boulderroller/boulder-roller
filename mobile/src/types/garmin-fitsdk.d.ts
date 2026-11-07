/**
 * Ambient type declarations for @garmin/fitsdk.
 *
 * The official SDK ships JSDoc only (Garmin: "no plans" for .d.ts). These
 * types cover the minimum surface we use — Encoder write/close + Profile
 * message numbers. Add to this declaration when new SDK features are used.
 */
declare module '@garmin/fitsdk' {
  export class Encoder {
    constructor(options?: { fieldDescriptions?: Record<string, unknown> });
    writeMesg(mesg: { mesgNum: number; [key: string]: unknown }): this;
    close(): Uint8Array;
  }

  export class Decoder {
    constructor(stream: unknown);
  }

  /** Stream wraps a Uint8Array for Decoder input. */
  export const Stream: {
    fromByteArray(bytes: Uint8Array): unknown;
    fromBuffer(buffer: ArrayBufferLike): unknown;
  };

  /** Profile message numbers and enums. */
  export const Profile: {
    MesgNum: Record<string, number> & {
      FILE_ID: number;
      RECORD: number;
      SESSION: number;
      ACTIVITY: number;
      LAP: number;
      EVENT: number;
    };
    types: Record<string, unknown>;
  };

  export const CrcCalculator: unknown;
  export const Utils: unknown;
}
