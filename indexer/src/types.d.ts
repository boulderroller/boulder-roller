declare module 'bs58' {
  const bs58: {
    encode(buffer: Buffer | Uint8Array | number[]): string;
    decode(str: string): Buffer;
  };
  export = bs58;
}
