/**
 * BR portal theme constants.
 *
 * The portal mirrors the ratified iOS color ledger from
 * docs/design/MOBILE_DESIGN_CONSTITUTION.md section 2. Cobalt is the only
 * action blue; persistent chrome and values stay on the warm ramp and ink.
 */
export const BR_PRIMARY_ALPHA_THEME = {
  id: 'ios-ledger',
  name: 'iOS Ledger',
  colors: {
    paper: '#0F0E0C',
    paperSoft: '#1B1A17',
    card: '#2A2825',
    ink: '#F1EEE8',
    inkSoft: '#9A9488',
    inkMuted: '#6A6660',
    inkFaint: '#4E4B46',
    line: '#4E4B46',
    terrain: '#5592E2',
    cal: '#5592E2',
    dung: '#F1EEE8',
    gold: '#E8C15A',
  },
  radius: {
    control: '7px',
    surface: '8px',
  },
  fonts: {
    sans: '"Geist", ui-sans-serif, system-ui, sans-serif',
    mono: '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
  },
} as const;

/**
 * SEMANTIC COLOR CONSTANTS
 * Single source of truth for special-purpose colors across Boulder Roller.
 * These complement the theme system and should be used for semantic meanings.
 */

export const SEMANTIC_COLORS = {
  // CAL - counted effort and balance values.
  calGlow: BR_PRIMARY_ALPHA_THEME.colors.cal,
  calGlowDark: BR_PRIMARY_ALPHA_THEME.colors.cal,

  // Persistent DUNG and weekly settlement values are ink, not reward gold.
  dungGlow: BR_PRIMARY_ALPHA_THEME.colors.dung,
  dungGlowDark: BR_PRIMARY_ALPHA_THEME.colors.dung,
  dungDisplay: BR_PRIMARY_ALPHA_THEME.colors.dung,
  crownGold: BR_PRIMARY_ALPHA_THEME.colors.ink,
  
  // Activity type colors
  activityRide: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  activityAchievement: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  activityReward: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,

  // Portal object colors
  routeLine: BR_PRIMARY_ALPHA_THEME.colors.terrain,
  climbLine: BR_PRIMARY_ALPHA_THEME.colors.terrain,
  terrainLine: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  proofGreen: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  warningOrange: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  gradeBrutal: BR_PRIMARY_ALPHA_THEME.colors.ink,
  gradeModerate: BR_PRIMARY_ALPHA_THEME.colors.inkMuted,
  gradeEasy: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  climbCategoryHc: BR_PRIMARY_ALPHA_THEME.colors.ink,
  climbCategory1: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  climbCategory2: BR_PRIMARY_ALPHA_THEME.colors.inkMuted,
  climbCategory3: BR_PRIMARY_ALPHA_THEME.colors.inkFaint,
  climbCategory4: BR_PRIMARY_ALPHA_THEME.colors.inkFaint,
  
  // Status & Feedback
  dangerRed: '#b84d4a',
  dangerDark: '#7a2927',
  statusDanger: '#b84d4a',
  successGreen: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  statusSuccess: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  warningYellow: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  
  // Rank colors
  rankS: BR_PRIMARY_ALPHA_THEME.colors.ink,
  rankA: BR_PRIMARY_ALPHA_THEME.colors.inkSoft,
  rankB: BR_PRIMARY_ALPHA_THEME.colors.inkMuted,
  rankC: BR_PRIMARY_ALPHA_THEME.colors.inkFaint,
  rankD: BR_PRIMARY_ALPHA_THEME.colors.inkMuted,
  
  // Overlays (for borders/backgrounds - theme-aware)
  overlayLight: 'rgba(241, 238, 232, 0.08)',
  overlayLightStrong: 'rgba(241, 238, 232, 0.14)',
  overlayDark: 'rgba(241, 238, 232, 0.12)',
  overlayDarkStrong: 'rgba(241, 238, 232, 0.2)',
  
  // Hover states
  hoverLight: 'rgba(85, 146, 226, 0.08)',
  hoverDark: 'rgba(85, 146, 226, 0.12)',
  
  // Dividers (very subtle)
  dividerLight: 'rgba(90, 87, 82, 0.45)',
  dividerDark: 'rgba(90, 87, 82, 0.45)',
} as const;

/**
 * GLOW EFFECTS
 * Box-shadow presets for making content "pop"
 */
export const GLOW_EFFECTS = {
  cal: '0 0 16px rgba(85, 146, 226, 0.3)',
  calSubtle: '0 0 10px rgba(85, 146, 226, 0.15)',
  dung: '0 0 20px rgba(241, 238, 232, 0.16)',
  dungSubtle: '0 0 12px rgba(241, 238, 232, 0.1)',
  dungStrong: '0 0 24px rgba(241, 238, 232, 0.2)',
  crown: '0 0 16px rgba(241, 238, 232, 0.18)',
  achievement: '0 0 12px rgba(241, 238, 232, 0.14)',
  liveIndicator: '0 0 8px rgba(85, 146, 226, 0.35)',
} as const;

/**
 * BRUTALIST SHADOWS
 * Hard-edge shadows for beetle UI components
 */
export const BEETLE_SHADOWS = {
  sm: '2px 2px 0px 0px',
  md: '3px 3px 0px 0px',
  lg: '4px 4px 0px 0px',
} as const;

/**
 * Helper to derive translucent variants from theme tokens or semantic colors.
 */
export function withAlpha(color: string, alpha: number): string {
  const normalizedAlpha = Math.max(0, Math.min(1, alpha));

  if (color.startsWith('#')) {
    const hex = color.slice(1);
    const fullHex = hex.length === 3
      ? hex.split('').map((char) => char + char).join('')
      : hex;

    if (fullHex.length !== 6) {
      return color;
    }

    const red = parseInt(fullHex.slice(0, 2), 16);
    const green = parseInt(fullHex.slice(2, 4), 16);
    const blue = parseInt(fullHex.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${normalizedAlpha})`;
  }

  const rgbMatch = color.match(/^rgba?\(([^)]+)\)$/i);
  if (rgbMatch) {
    const [red = '0', green = '0', blue = '0'] = rgbMatch[1]
      .split(',')
      .map((part) => part.trim());
    return `rgba(${red}, ${green}, ${blue}, ${normalizedAlpha})`;
  }

  return color;
}

/**
 * Helper function to get theme-aware overlay colors
 */
export function getOverlay(isDarkMode: boolean, strength: 'normal' | 'strong' = 'normal'): string {
  if (isDarkMode) {
    return strength === 'strong' ? SEMANTIC_COLORS.overlayDarkStrong : SEMANTIC_COLORS.overlayDark;
  }
  return strength === 'strong' ? SEMANTIC_COLORS.overlayLightStrong : SEMANTIC_COLORS.overlayLight;
}

/**
 * Helper function to get theme-aware hover colors
 */
export function getHoverBg(isDarkMode: boolean): string {
  return isDarkMode ? SEMANTIC_COLORS.hoverDark : SEMANTIC_COLORS.hoverLight;
}

/**
 * Helper function to get theme-aware divider colors
 */
export function getDivider(isDarkMode: boolean): string {
  return isDarkMode ? SEMANTIC_COLORS.dividerDark : SEMANTIC_COLORS.dividerLight;
}

/**
 * Helper function to get accent hover/highlight colors (for dung/selected states)
 */
export function getAccentHighlight(isDarkMode: boolean, intensity: 'subtle' | 'medium' | 'strong' = 'medium'): string {
  if (isDarkMode) {
    if (intensity === 'subtle') return 'rgba(85, 146, 226, 0.05)';
    if (intensity === 'medium') return 'rgba(85, 146, 226, 0.1)';
    return 'rgba(85, 146, 226, 0.15)';
  }
  if (intensity === 'subtle') return 'rgba(85, 146, 226, 0.05)';
  if (intensity === 'medium') return 'rgba(85, 146, 226, 0.1)';
  return 'rgba(85, 146, 226, 0.15)';
}
