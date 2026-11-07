/**
 * Address label system for known protocol accounts.
 * Maps well-known pubkeys to human-readable names.
 */

const KNOWN_LABELS: Record<string, string> = {
  // Program
  'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH': 'Boulder Roller Program',
  '6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X': 'Boulder Roller Program',

  // Treasury & protocol
  '3boUdooZh5wDySPHP3E4BPkCzQVnFZMBdaxCjLcChSra': 'Treasury',
  'Ag6YsS8GTTDYF2DUWuet1SBu3ZcoThjK8Dym7BoWdZfx': 'Treasury DUNG',
  '9wkFkPSH9eL1XdifxzM7ASfqyVtSZWAuLGUXTx5ijwPr': 'Treasury DUNG',

  // POL
  'Ch8uwuNsWUaRqRhB3iGxPNzRTK1F3GKhTakvKb3dVK3m': 'POL Wallet',
  '5kwC6G8zqoTnWJqFyH59ABsVnniFYJxm9Wn8Y6XpadjF': 'POL DUNG',
  'FtKcTXoL7LaZXcZxrJ9HrivgFgUtpwHUYcCndXt6EU74': 'POL DUNG',

  // Mints
  'B9u8L5pkWTce2SXJCKvNSKTrSukvWoajEdzy9STLNh6K': 'CAL Mint',
  '4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh': 'CAL Mint',
  'AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn': 'DUNG Mint',
  'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk': 'DUNG Mint',

  // Mint authorities
  '6QyEhQtK4UM7yuJuL5yweFKeE4Wri6D39dHuPriM1dxn': 'CAL Mint Authority',
  '9zepBY6pQ5vzUkRszV22kwLcJPkC5wRiuPkfHv9Y8JNV': 'CAL Mint Authority',
  'ALb9wjsv6V2DY4in7Dsgvk3VV7kqfhbVFWtKHEhpry5D': 'CAL Mint Authority',
  'CH1xHESUrjqvurj4n94w3hG1yZeAXcFdXCKUaQgBTPE1': 'DUNG Mint Authority',
  'D7uuNwoaRxA8sCy5y7xf7qj5VENJ8xwYeK4StomSTLXk': 'DUNG Mint Authority',

  // Config PDA
  '3CJZG9H6e8pZZ6ey2K7PAiyDgsLiHTWH1gsSrJDqehmG': 'Program Config',
  'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8': 'Program Config',

  // System programs
  '11111111111111111111111111111111': 'System Program',
  'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA': 'Token Program',
  'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL': 'Associated Token Program',
};

/**
 * Look up a human-readable label for a known address.
 * Returns null if the address is not recognized.
 */
export function getAddressLabel(address: string): string | null {
  return KNOWN_LABELS[address] ?? null;
}

/**
 * Format an address with its label if known.
 * Returns "Label (short...addr)" for known addresses, or null if unknown.
 */
export function formatLabeledAddress(address: string, shortChars = 4): string | null {
  const label = KNOWN_LABELS[address];
  if (!label) return null;
  if (address.length <= shortChars * 2 + 3) return `${label} (${address})`;
  return `${label} (${address.slice(0, shortChars)}...${address.slice(-shortChars)})`;
}
