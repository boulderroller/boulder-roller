// Palette preview: re-renders a workshop room on the shared palette without touching any candidate's files.
// Every stylesheet rule that sets a colour gets a twin under :root[data-palette], with the same declarations
// and each colour swapped for its nearest palette token. The prefix adds the same specificity to every twin,
// so twins keep the original cascade among themselves and win over the originals. Off, nothing is injected.
import { LEGACY, LEGACY_SELECTORS, PALETTE, type PaletteRole } from './palette';
import { deltaE2000, parseColour, toLab, type Rgba } from './colour';

export const PALETTE_PARAM = 'palette';
const STORE = 'br-workshop-palette';
const CHANNEL = 'br-workshop-palette';
const STYLE_ID = 'br-palette-preview';
const SCOPE = '[data-palette]';
// A colour further than this from every token is left as authored and reported.
const MAX_DISTANCE = 15;

type Role = PaletteRole | 'any';
const tokens = PALETTE.map(t => ({ ...t, lab: toLab(parseColour(t.value)!) }));
const cache = new Map<string, { name: string; distance: number } | null>();
const unmapped = new Set<string>();
// palette=identity keeps every colour as authored while still injecting the twins: a check that the twins
// preserve the cascade exactly (the room must render identically to palette off).
let identity = false;

export function roleFor(prop: string): Role | null {
  if (prop.startsWith('--')) {
    if (/bg|paper|surface|ground|card|band|shell|panel|wash|tint|fill/.test(prop)) return 'surface';
    if (/line|rule|border|stroke|grid|divider|edge/.test(prop)) return 'line';
    if (/ink|text|fg|label|muted|copy|title/.test(prop)) return 'text';
    return 'any';
  }
  if (prop === 'box-shadow' || prop === 'text-shadow') return 'shadow';
  if (prop === 'background-color' || prop === 'background-image') return 'surface';
  if (/^border-.*color$|^outline-color$|^column-rule-color$|^text-decoration-color$|^-webkit-text-stroke-color$/.test(prop)) return 'line';
  if (prop === 'fill' || prop === 'stroke' || prop === 'stop-color' || prop === 'flood-color' || prop === 'lighting-color') return 'svg';
  if (prop === 'color' || prop === 'caret-color' || prop === 'accent-color' || prop === '-webkit-text-fill-color') return 'text';
  return null;
}

export function nearestToken(rgba: Rgba, role: Role) {
  const key = `${Math.round(rgba[0])},${Math.round(rgba[1])},${Math.round(rgba[2])}|${role}`;
  if (cache.has(key)) return cache.get(key)!;
  const lab = toLab(rgba);
  const pick = (pool: typeof tokens) => pool.reduce<{ name: string; distance: number } | null>((best, t) => {
    const distance = deltaE2000(lab, t.lab);
    return !best || distance < best.distance ? { name: t.name, distance } : best;
  }, null);
  const scoped = role === 'any' ? tokens : tokens.filter(t => t.roles.includes(role));
  const best = pick(scoped.length ? scoped : tokens);
  const result = best && best.distance <= MAX_DISTANCE ? best : null;
  cache.set(key, result);
  return result;
}

const COLOUR = /(?<![-\w])(?:#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3,4}|rgba?\([^)]*\)|white|black)(?![-\w])/g;

const hex = (rgba: Rgba) => '#' + rgba.slice(0, 3).map(n => Math.round(n).toString(16).padStart(2, '0')).join('');
const byName = new Map(tokens.map(t => [t.name, t]));

// A legacy colour assigned by hand wins over the nearest token: for every role, or for one role.
export function tokenFor(rgba: Rgba, role: Role, forced?: string) {
  const legacy = LEGACY[hex(rgba)];
  const name = forced ?? (typeof legacy === 'string' ? legacy : role === 'any' ? undefined : legacy?.[role]);
  const token = name ? byName.get(name) : undefined;
  if (token) return { name: token.name, distance: deltaE2000(toLab(rgba), token.lab) };
  return nearestToken(rgba, role);
}

export function mapValue(value: string, role: Role, forced?: string, alpha?: number): string {
  if (identity) return value;
  return value.replace(COLOUR, (match, offset: number) => {
    if (/url\(\s*$/.test(value.slice(Math.max(0, offset - 6), offset))) return match;
    const rgba = parseColour(match);
    if (!rgba || rgba[3] === 0) return match;
    const token = tokenFor(rgba, role, forced);
    if (!token) { unmapped.add(match); return match; }
    const ref = `var(--pal-${token.name})`, a = alpha ?? rgba[3];
    return a >= 1 ? ref : `color-mix(in srgb, ${ref} ${+(a * 100).toFixed(2)}%, transparent)`;
  });
}

// A selector override names a property family (or one custom property exactly) and may also set the alpha.
export function selectorOverride(selector: string, prop: string) {
  return LEGACY_SELECTORS.find(o => selector.includes(o.selector)
    && (!o.property || o.property === prop || (!o.property.startsWith('--') && prop.startsWith(o.property + '-'))));
}

function splitTopLevel(selector: string): string[] {
  const parts: string[] = [];
  let depth = 0, quote = '', start = 0;
  for (let i = 0; i < selector.length; i++) {
    const c = selector[i];
    if (quote) { if (c === quote && selector[i - 1] !== '\\') quote = ''; continue; }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(' || c === '[') depth++;
    else if (c === ')' || c === ']') depth--;
    else if (c === ',' && depth === 0) { parts.push(selector.slice(start, i)); start = i + 1; }
  }
  parts.push(selector.slice(start));
  return parts.map(p => p.trim()).filter(Boolean);
}

// Every twin gains exactly (0,2,0): two attribute selectors on the root, or the root pair before a descendant.
export function prefixSelector(selector: string): string {
  return splitTopLevel(selector).map(part => {
    const root = part.match(/^(:root|html)(?![\w-])/);
    return root ? `${root[1]}${SCOPE}${SCOPE}${part.slice(root[1].length)}` : `:root${SCOPE} ${part}`;
  }).join(', ');
}

// Whole property families are twinned, shorthands included, read from the rule's own serialisation.
// A shorthand written with var() has no readable longhands, and a family twinned only in part would
// let an unrelated twin win where the original lost.
export function familyRole(prop: string): Role | null {
  if (prop.startsWith('--')) return roleFor(prop);
  if (prop === 'color') return 'text';
  if (prop.startsWith('background')) return 'surface';
  if (/^(border|outline|column-rule|text-decoration|-webkit-text-stroke)/.test(prop)) return 'line';
  if (prop === 'box-shadow' || prop === 'text-shadow') return 'shadow';
  if (/^(fill|stroke)/.test(prop) || ['stop-color', 'flood-color', 'lighting-color'].includes(prop)) return 'svg';
  if (['caret-color', 'accent-color', '-webkit-text-fill-color'].includes(prop)) return 'text';
  return null;
}

export function declarations(cssText: string): Array<{ prop: string; value: string; important: boolean }> {
  const out: Array<{ prop: string; value: string; important: boolean }> = [];
  let depth = 0, quote = '', start = 0;
  const push = (chunk: string) => {
    const colon = chunk.indexOf(':');
    if (colon < 0) return;
    const prop = chunk.slice(0, colon).trim().toLowerCase();
    let value = chunk.slice(colon + 1).trim();
    const important = /!\s*important$/i.test(value);
    if (important) value = value.replace(/!\s*important$/i, '').trim();
    if (prop && value) out.push({ prop, value, important });
  };
  for (let i = 0; i < cssText.length; i++) {
    const c = cssText[i];
    if (quote) { if (c === quote && cssText[i - 1] !== '\\') quote = ''; continue; }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(') depth++;
    else if (c === ')') depth--;
    else if (c === ';' && depth === 0) { push(cssText.slice(start, i)); start = i + 1; }
  }
  push(cssText.slice(start));
  return out;
}

export function twinDeclarations(style: CSSStyleDeclaration, selector = ''): string {
  const out: string[] = [];
  for (const { prop, value, important } of declarations(style.cssText)) {
    // Custom properties are all twinned, colour or not, so a later var() override still wins.
    const role = familyRole(prop);
    if (!role) continue;
    const override = selectorOverride(selector, prop);
    out.push(`${prop}:${mapValue(value, role, override?.token, override?.alpha)}${important ? ' !important' : ''}`);
  }
  return out.join(';');
}

function twinRules(rules: CSSRuleList, out: string[]) {
  for (const rule of Array.from(rules)) {
    if (rule instanceof CSSStyleRule) {
      const body = twinDeclarations(rule.style, rule.selectorText);
      if (body) out.push(`${prefixSelector(rule.selectorText)}{${body}}`);
    } else if (rule instanceof CSSImportRule) {
      try { if (rule.styleSheet) twinRules(rule.styleSheet.cssRules, out); } catch { /* cross-origin import */ }
    } else if ('cssRules' in rule && !(rule instanceof CSSKeyframesRule)) {
      const inner: string[] = [];
      twinRules((rule as CSSGroupingRule).cssRules, inner);
      if (inner.length) out.push(`${rule.cssText.slice(0, rule.cssText.indexOf('{'))}{${inner.join('')}}`);
    }
  }
}

function buildTwins(doc: Document): string[] {
  const twins: string[] = [];
  for (const sheet of Array.from(doc.styleSheets)) {
    if ((sheet.ownerNode as Element | null)?.id === STYLE_ID) continue;
    try { twinRules(sheet.cssRules, twins); } catch { /* cross-origin sheet, e.g. web fonts */ }
  }
  return twins;
}

// SVG presentation attributes written in code (chart fills, strokes). :where() keeps these below every twin.
const ATTRIBUTES = ['fill', 'stroke', 'stop-color'] as const;
function attributeValues(doc: Document): string[] {
  const found = new Set<string>();
  for (const el of Array.from(doc.querySelectorAll('[fill],[stroke],[stop-color]'))) {
    for (const name of ATTRIBUTES) {
      const value = el.getAttribute(name);
      if (value && parseColour(value)) found.add(`${name}\u0000${value}`);
    }
  }
  return [...found].sort();
}
const attributeRule = (entry: string) => {
  const [name, value] = entry.split('\u0000');
  return `:root${SCOPE} :where([${name}=${JSON.stringify(value)} i]){${name}:${mapValue(value, 'svg')}}`;
};
const VARIABLES = `:root${SCOPE}{${PALETTE.map(t => `--pal-${t.name}:${t.value}`).join(';')}}`;

// Some rooms rewrite the address as they load, so the palette parameter is also remembered for the tab.
type Mode = 'off' | 'on' | 'identity';
export function paletteMode(): Mode {
  try {
    const value = new URL(window.top!.location.href).searchParams.get(PALETTE_PARAM);
    if (value !== null) {
      const mode: Mode = value === 'identity' ? 'identity' : value === '1' ? 'on' : 'off';
      try { sessionStorage.setItem(STORE, mode); } catch { /* the parameter still applies */ }
      return mode;
    }
  } catch { /* top is not readable */ }
  try { const stored = sessionStorage.getItem(STORE); return stored === 'identity' || stored === 'on' ? stored : 'off'; } catch { return 'off'; }
}
export const paletteActive = () => paletteMode() !== 'off';

export function setPaletteActive(on: boolean) {
  try { sessionStorage.setItem(STORE, on ? 'on' : 'off'); } catch { /* the broadcast still reaches open frames */ }
  const url = new URL(location.href);
  url.searchParams.set(PALETTE_PARAM, on ? '1' : '0');
  history.replaceState(history.state, '', url);
  try { new BroadcastChannel(CHANNEL).postMessage({ on }); } catch { /* single frame */ }
}

declare global { interface Window { __palette?: { on: boolean; twins: number; attributes: number; unmapped: string[] } } }

// Preview frames only: the workbench chrome keeps its own colours.
export function installPalette(doc: Document = document) {
  if (window === window.top) { paletteMode(); return; }
  identity = paletteMode() === 'identity';
  let on = false, twins: string[] = [], attributes: string[] = [], stylesDirty = true, attributesDirty = true, timer = 0;
  const ours = (node: Node) => node === doc.getElementById(STYLE_ID) || node.parentNode === doc.getElementById(STYLE_ID);
  const apply = () => {
    let style = doc.getElementById(STYLE_ID) as HTMLStyleElement | null;
    if (!on) { style?.remove(); doc.documentElement.removeAttribute('data-palette'); window.__palette = { on, twins: 0, attributes: 0, unmapped: [] }; return; }
    if (stylesDirty) { twins = buildTwins(doc); stylesDirty = false; }
    if (attributesDirty) { attributes = attributeValues(doc); attributesDirty = false; }
    const css = [VARIABLES, ...attributes.map(attributeRule), ...twins].join('\n');
    if (!style) { style = doc.createElement('style'); style.id = STYLE_ID; }
    if (style.textContent !== css) style.textContent = css;
    if (doc.head.lastElementChild !== style) doc.head.append(style);
    doc.documentElement.setAttribute('data-palette', '');
    window.__palette = { on, twins: twins.length, attributes: attributes.length, unmapped: [...unmapped] };
  };
  const schedule = () => { if (!on) return; clearTimeout(timer); timer = window.setTimeout(apply, 120); };
  // New or hot-updated stylesheets, and newly rendered SVG colour attributes, refresh the preview.
  new MutationObserver(records => {
    if (records.some(r => !ours(r.target) && ![...r.addedNodes, ...r.removedNodes].every(ours))) { stylesDirty = true; schedule(); }
  }).observe(doc.head, { childList: true, subtree: true, characterData: true });
  new MutationObserver(() => { attributesDirty = true; schedule(); })
    .observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: [...ATTRIBUTES] });
  const set = (next: boolean) => { on = next; stylesDirty = attributesDirty = true; apply(); };
  try { new BroadcastChannel(CHANNEL).onmessage = e => set(Boolean(e.data?.on)); } catch { /* no live toggle; reload applies */ }
  set(paletteActive());
}
