export const PORTAL_CSS_COLORS = {
  border: 'var(--portal-border)',
  divider: 'var(--portal-divider)',
  panel: 'var(--portal-panel)',
  surface: 'var(--portal-surface)',
  muted: 'var(--portal-muted)',
  text: 'var(--color-text, var(--foreground))',
  textMuted: 'var(--color-text-muted, var(--muted-foreground))',
  route: 'var(--portal-route)',
  climb: 'var(--portal-climb)',
  terrain: 'var(--portal-terrain)',
  reward: 'var(--portal-reward)',
  crown: 'var(--portal-crown)',
  warning: 'var(--portal-warning)',
  success: 'var(--portal-success)',
  danger: 'var(--portal-danger)',
  selected: 'var(--portal-selected)',
} as const;

export const PORTAL_STREAM_COLORS = {
  elevation: PORTAL_CSS_COLORS.terrain,
  power: PORTAL_CSS_COLORS.warning,
  hr: PORTAL_CSS_COLORS.danger,
  cadence: PORTAL_CSS_COLORS.route,
  speed: PORTAL_CSS_COLORS.success,
} as const;

const CANVAS_FALLBACKS = {
  panel: '#0F0E0C',
  surface: '#2A2825',
  text: '#F1EEE8',
  textMuted: '#9A9488',
  border: '#4E4B46',
  route: '#5592E2',
  terrain: '#9A9488',
  reward: '#F1EEE8',
  crown: '#F1EEE8',
  warning: '#9A9488',
  success: '#9A9488',
  danger: '#b84d4a',
  selected: '#5592E2',
};

export function cssVar(
  styles: CSSStyleDeclaration,
  name: string,
  fallback: string,
): string {
  return styles.getPropertyValue(name).trim() || fallback;
}

export function colorWithAlpha(color: string, alpha: number): string {
  const normalizedAlpha = Math.max(0, Math.min(1, alpha));
  const trimmed = color.trim();
  const shortHexMatch = /^#([0-9a-f]{3})$/i.exec(trimmed);
  if (shortHexMatch) {
    const [, hex] = shortHexMatch;
    const r = Number.parseInt(hex[0] + hex[0], 16);
    const g = Number.parseInt(hex[1] + hex[1], 16);
    const b = Number.parseInt(hex[2] + hex[2], 16);
    return `rgba(${r}, ${g}, ${b}, ${normalizedAlpha})`;
  }

  const hexMatch = /^#([0-9a-f]{6})$/i.exec(trimmed);
  if (hexMatch) {
    const [, hex] = hexMatch;
    const r = Number.parseInt(hex.slice(0, 2), 16);
    const g = Number.parseInt(hex.slice(2, 4), 16);
    const b = Number.parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${normalizedAlpha})`;
  }

  const rgbMatch = /^rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+[\d.]+)?\)$/i.exec(trimmed);
  if (rgbMatch) {
    const [, r, g, b] = rgbMatch;
    return `rgba(${r}, ${g}, ${b}, ${normalizedAlpha})`;
  }

  return trimmed;
}

export function readPortalCanvasPalette(element: Element) {
  const styles = getComputedStyle(element);
  const panel = cssVar(styles, '--color-bg', CANVAS_FALLBACKS.panel);
  const surface = cssVar(styles, '--color-bg-secondary', CANVAS_FALLBACKS.surface);
  const text = cssVar(styles, '--color-text', CANVAS_FALLBACKS.text);
  const textMuted = cssVar(styles, '--color-text-muted', CANVAS_FALLBACKS.textMuted);
  const border = cssVar(styles, '--color-border', CANVAS_FALLBACKS.border);
  const route = cssVar(styles, '--portal-route', CANVAS_FALLBACKS.route);
  const terrain = cssVar(styles, '--portal-terrain', CANVAS_FALLBACKS.terrain);
  const reward = cssVar(styles, '--portal-reward', CANVAS_FALLBACKS.reward);
  const crown = cssVar(styles, '--portal-crown', CANVAS_FALLBACKS.crown);
  const warning = cssVar(styles, '--portal-warning', CANVAS_FALLBACKS.warning);
  const success = cssVar(styles, '--portal-success', CANVAS_FALLBACKS.success);
  const danger = cssVar(styles, '--portal-danger', CANVAS_FALLBACKS.danger);
  const selected = cssVar(styles, '--portal-selected', CANVAS_FALLBACKS.selected);

  return {
    panel,
    surface,
    text,
    textMuted,
    border,
    route,
    terrain,
    reward,
    crown,
    warning,
    success,
    danger,
    selected,
    grid: colorWithAlpha(text, 0.06),
    mutedBand: colorWithAlpha(text, 0.07),
    label: colorWithAlpha(text, 0.52),
    hoverLine: colorWithAlpha(text, 0.7),
    bracket: colorWithAlpha(text, 0.15),
    dotStroke: panel,
  };
}
