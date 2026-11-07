/**
 * Anonymous Name Generator
 *
 * Generates deterministic pseudonymous names from wallet addresses.
 * 1600s English vocabulary that resonates with contemporary crypto/cycling culture.
 *
 * Usage:
 *   import { generateAnonName } from './anonNames';
 *   const name = generateAnonName("0x1234..."); // -> "sovereign-wrought-leviathan"
 */

// =============================================================================
// WORD BANKS - 1600s English → 2025 Crypto/Cycling
// =============================================================================

const ADJECTIVES = [
  // Sovereignty/Power
  "sovereign", "ordained", "anointed", "hallowed", "consecrated", "exalted",
  "vanguard", "sentinel", "harbinger", "herald", "provident", "regnant",
  "imperious", "ascendant", "paramount", "preeminent", "illustrious",

  // State/Condition
  "forsaken", "unbowed", "undone", "unbroken", "unchained", "unvanquished",
  "dormant", "nascent", "risen", "fallen", "abased", "benighted",
  "steadfast", "resolute", "unwavering", "inexorable", "indomitable",
  "penitent", "zealous", "fervent", "devout", "apostate", "heretical",

  // Alchemy/Material
  "mercurial", "vitreous", "molten", "tempered", "wrought", "annealed",
  "leaden", "gilded", "burnished", "tarnished", "forged", "alloyed",
  "crystalline", "vitrified", "calcified", "fulgurite", "sulphuric", "pyrite",
  "ferric", "cupric", "phosphoric", "volcanic", "argentum", "aurum",

  // Nature/Elements
  "tempestuous", "fallow", "verdant", "barren", "perennial", "deciduous",
  "migratory", "nocturnal", "crepuscular", "umbral", "boreal", "austral",
  "tectonic", "glacial", "seismic", "abyssal", "littoral",

  // Philosophical/Moral
  "stoic", "spartan", "faustian", "pyrrhic", "promethean", "sisyphean",
  "quixotic", "machiavellian", "draconian", "arcadian", "utopian",
  "monastic", "ascetic", "hermetic", "gnostic", "esoteric", "occult",

  // Maritime/Exploration
  "nautical", "meridian", "cardinal", "equatorial", "polar", "celestial",
  "chartered", "uncharted", "fathomless", "becalmed", "windward",

  // Heraldic
  "rampant", "couchant", "passant", "salient", "sejant",
  "argent", "sable", "gules", "azure", "vert", "purpure",

  // Temporal
  "antediluvian", "primordial", "epochal", "vestigial",
  "perpetual", "sempiternal", "immemorial", "coeval", "synchronous",

  // Texture/Quality
  "gossamer", "adamantine", "ethereal", "corporeal", "spectral", "phantasmal",
  "lambent", "tenebrous", "luminous", "penumbral", "iridescent", "opalescent",
] as const;

const CREATURES = [
  // Illuminated Manuscript Beasts
  "basilisk", "cockatrice", "manticore", "chimera", "griffin", "wyvern",
  "wyrm", "leviathan", "behemoth", "kraken", "hydra", "cerberus",
  "sphinx", "minotaur", "harpy", "siren", "gorgon", "cyclops",

  // Heraldic Animals
  "lion", "leopard", "stag", "hart", "boar", "bear",
  "eagle", "falcon", "raven", "swan", "pelican", "martlet",
  "dragon", "unicorn", "yale", "enfield", "alphyn",

  // Alchemical/Symbolic
  "ouroboros", "phoenix", "salamander", "scarab", "ibis",
  "serpent", "asp", "viper", "adder", "python", "cobra",

  // Natural Philosophy
  "beetle", "cicada", "mantis", "hornet", "locust",
  "pangolin", "armadillo", "tapir", "capybara", "sloth", "anteater",

  // New World
  "condor", "jaguar", "ocelot", "puma", "quetzal", "toucan",
  "iguana", "caiman", "anaconda", "piranha", "manatee",

  // Old World Exotic
  "elephant", "rhinoceros", "hippopotamus", "crocodile", "ibex", "oryx",
  "chamois", "gazelle", "antelope", "jackal", "hyena", "vulture",

  // Deep Sea
  "nautilus", "coelacanth", "anglerfish", "viperfish", "gulper",

  // Insectum
  "bombardier", "deathwatch", "sexton", "carrion", "dung",
  "titan", "goliath", "hercules", "atlas",
] as const;

const NOUNS = [
  // Scripture → Chain
  "genesis", "exodus", "revelation", "covenant", "testament", "dominion",
  "sovereignty", "providence", "tribulation", "rapture", "apocalypse",
  "commandment", "parable", "prophecy", "sacrament", "benediction",

  // Court/Law → Contract
  "protocol", "decree", "edict", "mandate", "charter", "sanction",
  "tribunal", "compact", "accord", "statute", "ordinance", "writ",
  "regency", "protectorate", "vassal",

  // Alchemy → DeFi
  "transmutation", "crucible", "catalyst", "synthesis", "essence",
  "elixir", "quintessence", "philosopher", "opus", "materia",
  "tincture", "sublimation", "calcination", "dissolution", "conjunction",

  // Astronomy/Navigation
  "meridian", "zenith", "nadir", "apogee", "perigee", "ecliptic",
  "solstice", "equinox", "parallax", "azimuth", "declination",
  "constellation", "firmament", "empyrean", "orrery",

  // Time/Cycle
  "epoch", "aeon", "advent", "reckoning", "twilight", "vespers",
  "vigil", "sabbath", "jubilee", "millennia",

  // Transformation
  "metamorphosis", "apotheosis", "transfiguration", "resurrection",
  "ascension", "transcendence", "chrysalis", "emergence",

  // Maritime
  "armada", "flotilla", "galleon", "carrack", "caravel", "brigantine",
  "voyage", "expedition", "circumnavigation", "passage", "crossing",
] as const;

// =============================================================================
// STRUCTURE PATTERNS
// =============================================================================

type Structure = readonly ["adj", "adj", "creature"]
  | readonly ["creature", "adj", "noun"]
  | readonly ["adj", "creature", "noun"]
  | readonly ["noun", "adj", "creature"];

const STRUCTURES: Structure[] = [
  ["adj", "adj", "creature"],      // sovereign-wrought-leviathan
  ["creature", "adj", "noun"],     // phoenix-hallowed-covenant
  ["adj", "creature", "noun"],     // forsaken-wyrm-transmutation
  ["noun", "adj", "creature"],     // genesis-mercurial-ouroboros
];

const BANKS = {
  adj: ADJECTIVES,
  creature: CREATURES,
  noun: NOUNS,
} as const;

type BankType = keyof typeof BANKS;

// =============================================================================
// HASH UTILITY
// =============================================================================

/**
 * Simple hash function for browser environment.
 * Uses a variant of djb2 to produce deterministic bytes.
 */
function hashString(str: string): Uint8Array {
  const normalized = str.toLowerCase();
  const bytes = new Uint8Array(32);

  // Initialize with prime-derived values
  let h1 = 5381;
  let h2 = 52711;
  let h3 = 33;
  let h4 = 17;

  for (let i = 0; i < normalized.length; i++) {
    const c = normalized.charCodeAt(i);
    h1 = ((h1 << 5) + h1) ^ c;
    h2 = ((h2 << 5) + h2) ^ c;
    h3 = ((h3 << 5) + h3) + c;
    h4 = ((h4 << 5) + h4) + c;
  }

  // Distribute hash values across bytes
  for (let i = 0; i < 8; i++) {
    bytes[i] = (h1 >>> (i * 4)) & 0xFF;
    bytes[i + 8] = (h2 >>> (i * 4)) & 0xFF;
    bytes[i + 16] = (h3 >>> (i * 4)) & 0xFF;
    bytes[i + 24] = (h4 >>> (i * 4)) & 0xFF;
  }

  return bytes;
}

// =============================================================================
// GENERATOR
// =============================================================================

/**
 * Generate a deterministic anonymous name from a wallet address or seed.
 * The same input always produces the same output.
 *
 * @param walletOrSeed - Wallet address or any string seed
 * @returns Hyphenated name like "sovereign-wrought-leviathan"
 */
export function generateAnonName(walletOrSeed: string): string {
  const h = hashString(walletOrSeed);

  // Select structure based on first byte
  const structure = STRUCTURES[h[0] % STRUCTURES.length];

  // Build name from structure
  const parts: string[] = [];
  for (let i = 0; i < structure.length; i++) {
    const bankType = structure[i] as BankType;
    const bank = BANKS[bankType];
    // Use different bytes for each position to avoid collisions
    const idx = h[i + 1] % bank.length;
    parts.push(bank[idx]);
  }

  return parts.join("-");
}

/**
 * Get statistics about the name generator.
 */
export function getNameStats() {
  const adjCount = ADJECTIVES.length;
  const creatureCount = CREATURES.length;
  const nounCount = NOUNS.length;

  const combinations = {
    "adj-adj-creature": adjCount * adjCount * creatureCount,
    "creature-adj-noun": creatureCount * adjCount * nounCount,
    "adj-creature-noun": adjCount * creatureCount * nounCount,
    "noun-adj-creature": nounCount * adjCount * creatureCount,
  };

  return {
    banks: {
      adjectives: adjCount,
      creatures: creatureCount,
      nouns: nounCount,
    },
    structures: STRUCTURES.length,
    combinationsPerStructure: combinations,
    totalUniqueNames: Object.values(combinations).reduce((a, b) => a + b, 0),
  };
}

/**
 * Mask a wallet address for semi-anonymous display.
 *
 * @param wallet - Full wallet address
 * @param visibleChars - Number of chars to show at end
 * @returns Masked string like "****3xK9"
 */
export function maskWallet(wallet: string, visibleChars = 4): string {
  if (wallet.length <= visibleChars) {
    return wallet;
  }
  return "****" + wallet.slice(-visibleChars);
}
