/**
 * Topographic Color Palette - "Cartographic Heritage"
 *
 * Inspired by vintage USGS survey maps and the Havanna-2 palette.
 * Ride-data colors remain cartographic, while route and map furniture use the
 * ratified iOS ledger so cobalt stays the single interactive blue.
 *
 * Design Philosophy:
 * - Green lowlands transition naturally to tan/brown highlands
 * - Route lines use deep teal - like ink on aged paper
 * - No harsh blacks - everything feels printed, tactile
 */

// ============================================
// ELEVATION PALETTE (Land - Low to High)
// ============================================
export const ELEVATION = {
  // Lowest elevation (coastal, valleys)
  coastal: '#46AF64',
  // Low elevation (plains, low hills)
  lowland: '#96C869',
  // Mid-low elevation
  midLow: '#E1D791',
  // Mid elevation (foothills)
  mid: '#CDB991',
  // Mid-high elevation
  midHigh: '#A59173',
  // High elevation (mountains)
  highland: '#7D695A',
  // Peaks (rocky, exposed)
  peak: '#D2BEBE',
} as const;

// Ordered array for interpolation (0-1 scale)
export const ELEVATION_STOPS = [
  { stop: 0.0, color: '#46AF64' },  // Coastal green
  { stop: 0.15, color: '#96C869' }, // Lowland green
  { stop: 0.3, color: '#E1D791' },  // Pale yellow-green
  { stop: 0.45, color: '#CDB991' }, // Light tan
  { stop: 0.6, color: '#A59173' },  // Khaki
  { stop: 0.8, color: '#7D695A' },  // Brown
  { stop: 1.0, color: '#D2BEBE' },  // Peak mauve
];

// ============================================
// WATER/DEPTH PALETTE
// ============================================
export const WATER = {
  shallow: '#D7EBEB',
  light: '#96CDD2',
  mid: '#5AAFB9',
  deep: '#41A5B4',
  deepest: '#3C96AA',
} as const;

// ============================================
// ROUTE & TRACK COLORS
// ============================================
export const ROUTE = {
  primary: '#5592E2',
  ridePrimary: '#5592E2',
  rideCasing: '#0F0E0C',
  rideHover: '#5592E2',
  rideSelected: '#5592E2',
  highlight: '#5592E2',
  climb: '#5592E2',
  climbHighlight: '#5592E2',
  hover: '#5592E2',
  // The ledger explicitly preserves the pure-white map start dot.
  start: '#FFFFFF',
  end: '#F1EEE8',
} as const;

// ============================================
// THE GROUND (Profile — Ground, ratified 2026-09-02)
// ============================================
// Canon climbs on a rider's ground, by tier: faint for the canon itself
// (ink-muted), ink for climbs the rider has ridden, cobalt over the dark
// casing for climbs they hold, with the ledger's pure-white start dot.
export const GROUND = {
  faint: '#6A6660',
  ridden: '#F1EEE8',
  held: '#5592E2',
  casing: '#0A3268',
  start: '#FFFFFF',
} as const;

// ============================================
// GRADIENT SCALE (Climb Difficulty)
// ============================================
export const GRADIENT = {
  easy: '#96C869',      // 0-3% - light green
  moderate: '#CDB991',  // 3-6% - tan
  challenging: '#A59173', // 6-9% - khaki
  hard: '#7D695A',      // 9-12% - brown
  extreme: '#D2BEBE',   // 12%+ - mauve (rocky steep)
} as const;

// Gradient palette for leaflet-hotline (0-1 scale)
export const GRADIENT_PALETTE = {
  0.0: '#96C869',   // Easy (0-3%)
  0.25: '#CDB991',  // Moderate (3-6%)
  0.5: '#A59173',   // Challenging (6-9%)
  0.75: '#7D695A',  // Hard (9-12%)
  1.0: '#D2BEBE',   // Extreme (12%+)
} as const;

// ============================================
// UI COLORS (Panels, Controls)
// ============================================
export const UI = {
  // Map controls stay on the same warm ladder in either host color mode.
  light: {
    background: '#0F0E0C',
    backgroundAlt: '#1B1A17',
    border: 'rgba(78, 75, 70, 0.72)',
    text: '#F1EEE8',
    textMuted: '#9A9488',
    accent: '#5592E2',
  },
  dark: {
    background: '#0F0E0C',
    backgroundAlt: '#1B1A17',
    border: 'rgba(78, 75, 70, 0.72)',
    text: '#F1EEE8',
    textMuted: '#9A9488',
    accent: '#5592E2',
  },
} as const;

// ============================================
// BASE MAP STYLES
// ============================================
export type BaseMapStyle = 'dark' | 'voyager' | 'positron' | 'terrain' | 'terrainBg';

/**
 * CARTO gates its basemaps behind a free key (carto.com/basemaps/apikey).
 * Keyless requests still serve tiles, watermarked "API KEY REQUIRED".
 * The key is a build-time env value; the URL form is documented by CARTO as
 * `.../rastertiles/<style>/{z}/{x}/{y}.png?key=<key>`.
 */
const CARTO_API_KEY = (import.meta.env.VITE_CARTO_API_KEY ?? '').trim();

function cartoTileUrl(style: string): string {
  const base = `https://basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}{r}.png`;
  return CARTO_API_KEY ? `${base}?key=${encodeURIComponent(CARTO_API_KEY)}` : base;
}

export const BASE_MAP_STYLES: Record<BaseMapStyle, {
  url: string;
  attribution: string;
  maxZoom: number;
  subdomains?: string;
  tileClassName?: string;
  label: string;
  description: string;
}> = {
  // CARTO Dark Matter - the night ledger's map: ink lines on warm-dark ground
  dark: {
    url: cartoTileUrl('dark_all'),
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    maxZoom: 19,
    tileClassName: 'br-map-tile--carto-dark',
    label: 'Dark',
    description: 'Night ledger',
  },
  // CARTO Voyager - clean, modern, has labels
  voyager: {
    url: cartoTileUrl('voyager'),
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    maxZoom: 19,
    tileClassName: 'br-map-tile--carto-voyager',
    label: 'Voyager',
    description: 'Rich standard',
  },
  // CARTO Positron - ultra minimal, light
  positron: {
    url: cartoTileUrl('light_all'),
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    maxZoom: 19,
    tileClassName: 'br-map-tile--carto-positron',
    label: 'Positron',
    description: 'Quiet analysis',
  },
  // OpenTopoMap - classic topographic style
  terrain: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenTopoMap contributors',
    subdomains: 'abc',
    maxZoom: 17,
    label: 'Terrain',
    description: 'Classic topo',
  },
  // Esri World Topo - cleaner, modern terrain
  terrainBg: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    attribution: '&copy; Esri',
    maxZoom: 19,
    label: 'Esri Topo',
    description: 'Modern terrain',
  },
};

// Default base map
export const DEFAULT_BASE_MAP: BaseMapStyle = 'dark';

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Interpolate elevation color from 0-1 scale
 */
export function getElevationColor(normalizedElevation: number): string {
  const t = Math.max(0, Math.min(1, normalizedElevation));

  // Find the two stops we're between
  for (let i = 0; i < ELEVATION_STOPS.length - 1; i++) {
    const curr = ELEVATION_STOPS[i];
    const next = ELEVATION_STOPS[i + 1];

    if (t >= curr.stop && t <= next.stop) {
      const localT = (t - curr.stop) / (next.stop - curr.stop);
      return interpolateColor(curr.color, next.color, localT);
    }
  }

  return ELEVATION_STOPS[ELEVATION_STOPS.length - 1].color;
}

/**
 * Get gradient color based on percentage
 */
export function getGradientColor(gradientPct: number): string {
  if (gradientPct < 3) return GRADIENT.easy;
  if (gradientPct < 6) return GRADIENT.moderate;
  if (gradientPct < 9) return GRADIENT.challenging;
  if (gradientPct < 12) return GRADIENT.hard;
  return GRADIENT.extreme;
}

/**
 * Interpolate between two hex colors
 */
function interpolateColor(color1: string, color2: string, t: number): string {
  const r1 = parseInt(color1.slice(1, 3), 16);
  const g1 = parseInt(color1.slice(3, 5), 16);
  const b1 = parseInt(color1.slice(5, 7), 16);

  const r2 = parseInt(color2.slice(1, 3), 16);
  const g2 = parseInt(color2.slice(3, 5), 16);
  const b2 = parseInt(color2.slice(5, 7), 16);

  const r = Math.round(r1 + (r2 - r1) * t);
  const g = Math.round(g1 + (g2 - g1) * t);
  const b = Math.round(b1 + (b2 - b1) * t);

  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

/**
 * Get time-based color (journey progress)
 * Uses water palette: deep start → light end
 */
export function getTimeColor(progress: number): string {
  const t = Math.max(0, Math.min(1, progress));
  const stops = [
    { stop: 0, color: WATER.deepest },
    { stop: 0.33, color: WATER.deep },
    { stop: 0.66, color: WATER.mid },
    { stop: 1, color: WATER.light },
  ];

  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i].stop && t <= stops[i + 1].stop) {
      const localT = (t - stops[i].stop) / (stops[i + 1].stop - stops[i].stop);
      return interpolateColor(stops[i].color, stops[i + 1].color, localT);
    }
  }
  return stops[stops.length - 1].color;
}

/**
 * Get power-based color
 * Uses warm progression: green → tan → brown
 */
export function getPowerColor(powerPct: number): string {
  const t = Math.max(0, Math.min(1, powerPct));
  return getElevationColor(t * 0.8); // Cap at highland, not peak
}
