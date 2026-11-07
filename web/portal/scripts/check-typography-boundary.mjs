import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = path.join(portalRoot, 'src');
const activeStyles = [
  'src/index.css',
  'src/styles/portal-spine.css',
  'src/styles/portal-surface-polish.css',
  'src/styles/loading-system.css',
  'src/styles/portal-climb-detail.css',
  'src/styles/portal-ride-analysis.css',
  'src/styles/estimated-value.css',
];
const policySources = [
  ...activeStyles,
  'src/styles/globals.css',
  'src/constants/colors.ts',
];
const surfaceAliases = [
  '--portal-font-sans',
  '--portal-font-mono',
  '--access-font',
  '--access-mono',
  '--public-preview-font',
  '--public-preview-mono',
];
const roleBoundary = (roles) => new RegExp(
  `(?:^|[^a-z0-9])(?:${roles.join('|')})(?=$|[^a-z0-9])`,
  'i',
);
const headingSelectorPattern = roleBoundary(['title', 'heading', 'headline']);
const labelSelectorPattern = roleBoundary([
  'label',
  'status',
  'state',
  'badge',
  'pill',
  'eyebrow',
  'kicker',
  'meta',
  'caption',
  'legend',
  'header',
  'name',
  'rider',
  'actor',
  'mark',
  'brand',
  'avatar',
  'option',
  'warning',
  'alert',
  'empty',
  'pending',
  'loading',
  'current',
  'back',
  'attribution',
]);
const controlSelectorPattern = roleBoundary([
  'button',
  'action',
  'link',
  'nav',
  'control',
  'input',
  'select',
  'tab',
  'toggle',
  'trigger',
  'menuitem',
  'menu-item',
  'view-all',
]);
const bodySelectorPattern = roleBoundary([
  'body',
  'copy',
  'description',
  'message',
  'note',
  'footnote',
  'subtitle',
  'subline',
  'intro',
  'helper',
  'hint',
  'explanation',
  'instructions',
  'lede',
]);
const dataSelectorPattern = roleBoundary([
  'value',
  'amount',
  'balance',
  'rank',
  'time',
  'date',
  'age',
  'count',
  'metric',
  'metrics',
  'fact',
  'facts',
  'score',
  'level',
  'progress',
  'price',
  'reward',
  'cost',
  'code',
  'signature',
  'hash',
  'address',
  'power',
  'distance',
  'speed',
  'cadence',
  'heart',
  'vam',
  'cal',
  'dung',
  'allocation',
  'supply',
  'total',
  'index',
  'delta',
  'streak',
  'stat',
  'stats',
  'number',
  'position',
  'duration',
  'distribution',
  'payout',
  'carry',
  'record',
  'pr',
  'kom',
  'grade',
  'percent',
  'pct',
  'gpd',
  'elevation',
  'persistence',
]);
const allowedFontWeights = new Set([
  '400',
  '500',
  '600',
  '700',
  '800',
  '900',
  'inherit',
  'initial',
  'unset',
  'var(--font-weight-normal)',
  'var(--font-weight-medium)',
  'var(--font-weight-semibold)',
  'var(--font-weight-bold)',
]);
const failures = [];

function read(relativePath) {
  return fs.readFileSync(path.join(portalRoot, relativePath), 'utf8');
}

function lineNumber(source, offset) {
  return source.slice(0, offset).split('\n').length;
}

function fail(relativePath, source, offset, message) {
  failures.push(`${relativePath}:${lineNumber(source, offset)} ${message}`);
}

function failRule(relativePath, rule, message) {
  failures.push(`${relativePath}:${rule.source?.start?.line ?? 1} ${message}`);
}

function fontSizePixels(value) {
  const fixed = value.match(/^(\d*\.?\d+)(px|rem)$/i);
  if (fixed) {
    return Number(fixed[1]) * (fixed[2].toLowerCase() === 'rem' ? 16 : 1);
  }
  if (value.includes('var(--br-label-size)')) return 12;
  return null;
}

function fontWeightNumber(value) {
  if (!value) return null;
  if (/^\d+$/.test(value)) return Number(value);
  return {
    'var(--font-weight-normal)': 400,
    'var(--font-weight-medium)': 500,
    'var(--font-weight-semibold)': 600,
    'var(--font-weight-bold)': 700,
  }[value] ?? null;
}

function lineHeightPixels(value, fontSize) {
  if (!value || fontSize === null) return null;
  if (value.includes('var(--br-label-line-height)')) return 16;
  const fixed = value.match(/^(\d*\.?\d+)(px|rem)$/i);
  if (fixed) {
    return Number(fixed[1]) * (fixed[2].toLowerCase() === 'rem' ? 16 : 1);
  }
  if (/^\d*\.?\d+$/.test(value)) return Number(value) * fontSize;
  if (value === 'normal') return 1.2 * fontSize;
  return null;
}

function targetCompound(selector) {
  const withoutFunctionalContents = selector.replace(/\([^()]*(?:\([^()]*\)[^()]*)*\)/g, '');
  return withoutFunctionalContents.split(/\s+|[>+~]/).filter(Boolean).at(-1) ?? selector;
}

function semanticRoleTarget(target) {
  const classNames = [...target.matchAll(/\.([a-z0-9_-]+)/gi)].map((match) => match[1]);
  const className = classNames.at(-1);
  if (!className) return target;
  return className.includes('__') ? className.split('__').at(-1) : className;
}

function isTypeSelector(target, typePattern) {
  return new RegExp(`^(?:[a-z][a-z0-9-]*\\|)?${typePattern}(?=$|[.#:\\[])`, 'i').test(target);
}

const technicalDataSelectorOverrides = [
  /\.portfolio-balance-field\s+input\b/i,
  /\.share-modal-copy__input\b/i,
  /\.vault-detail-amount-field\s+input\b/i,
  /\.public-preview-ride-row__stats\b/i,
  /\.admin-v2-gpd-fit__header\s+span\b/i,
  /\.admin-v2-gpd-fit-tooltip\s+(?:span|em)\b/i,
  /\.admin-v2-gpd-fit__climbs\s+(?:em|b)\b/i,
  /\.admin-v2-elevation-profile__title\s+(?:span|p)\b/i,
  /\.admin-v2-elevation-tooltip\s+(?:strong|span|em)\b/i,
  /\.admin-v2-elevation-profile__pairs\s+header\s+span\b/i,
  /\.admin-v2-elevation-profile__pairs\s+p\b/i,
  /\.admin-v2-elevation-profile__pairs\s+li\s+(?:strong|b)\b/i,
  /\.admin-v2-elevation-profile__pairs\s+li\[data-status=['"]active['"]\]\s+small\b/i,
  /\.climbs-table-card__segment-time\s+strong\b/i,
  /\.climbs-table-card__effort-table-row\s+strong\b/i,
  /\.climbs-table-card__leaderboard-row\s+em\b/i,
  /\.vault-creation-success__meta-value\b/i,
  /\.settings-v2-privacy-zone-card__meta\b/i,
  /\.map-layer-controls__pill--data\b/i,
  /\.feed-activity-card__count-badge\b/i,
  /\.settings-v2-privacy-zone-radius-option__value\b/i,
];

const sansUiSelectorOverrides = [
  /\.portal-metric__value--sans\b/i,
  /\.public-preview-stat__value--sans\b/i,
  /\.public-preview-stat\s+span\b/i,
  /\.public-preview-board__row--header\b/i,
  /\.public-preview-board__metric\s+span\b/i,
  /\.public-preview-board__rider\s+span\b/i,
  /\.public-preview-footnote\b/i,
  /\.public-preview-ride-row__copy\s+span\b/i,
  /\.admin-v2-gpd-fit-state\s+strong\b/i,
  /\.admin-v2-gpd-fit__header\s+strong\b/i,
  /\.admin-v2-gpd-fit__climbs\s*>\s*strong\b/i,
  /\.admin-v2-gpd-fit__climbs\s+li\s*>\s*strong\b/i,
  /\.admin-v2-gpd-fit__climbs\s+small\b/i,
  /\.admin-v2-elevation-state\s+strong\b/i,
  /\.admin-v2-elevation-profile__title\s+strong\b/i,
  /\.admin-v2-elevation-profile__title\s+h3\b/i,
  /\.admin-v2-elevation-profile__empty\s+strong\b/i,
  /\.admin-v2-elevation-profile__pairs\s+header\s+strong\b/i,
  /\.admin-v2-elevation-profile__pairs\s+li\[data-status=['"]filtered['"]\]\s+small\b/i,
  /\.admin-v2-elevation-profile__pairs\s*>\s*small\b/i,
  /\.portal-stub-banner\b/i,
  /\.portfolio-balance-setup__row\b/i,
  /\.public-preview-metric__value--sans\b/i,
  /\.ride-detail-point-readout__summary-value--sans\b/i,
  /\.ride-detail-proof-datum__value--sans\b/i,
  /\.admin-v2-detail-grid__value--sans\b/i,
  /\.admin-v2-pipeline__stage-delta--sans\b/i,
];

const primaryDataSelectorOverrides = [
  /\.portal-metric__value(?:--mono)?\b/i,
  /\.climbs-table-card__segment-time\s+strong\b/i,
];

const bodyCopySelectorOverrides = [
  /\.profile-v2-setup-banner__copy\s+span\b/i,
  /\.profile-v2-muted-line\b/i,
  /\.portal-inline-alert\s*>\s*div\s*>\s*span\b/i,
  /\.portal-inline-alert\s*>\s*span\b/i,
  /\.upload-activity-modal-error-detail\b/i,
];

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) return walk(absolutePath);
    return [absolutePath];
  });
}

function relativeToPortal(absolutePath) {
  return path.relative(portalRoot, absolutePath).replaceAll(path.sep, '/');
}

function assertContains(relativePath, expected, label) {
  const source = read(relativePath);
  if (!source.includes(expected)) {
    failures.push(`${relativePath} is missing ${label}: ${expected}`);
  }
}

function assertAllSelectorDeclarations(relativePath, selector, property, expected) {
  const root = postcss.parse(read(relativePath), { from: relativePath });
  const values = [];
  root.walkRules((rule) => {
    if (!rule.selectors.map((item) => item.trim().replace(/\s+/g, ' ')).includes(selector)) return;
    rule.walkDecls(property, (declaration) => values.push(declaration.value.trim()));
  });
  if (values.length === 0) {
    failures.push(`${relativePath} is missing ${property} for ${selector}`);
  } else if (values.some((value) => value !== expected)) {
    failures.push(
      `${relativePath} must keep every ${selector} ${property} at ${expected}; found ${values.join(', ')}`,
    );
  }
}

function selectorSpecificity(selector) {
  const normalized = selector.replace(/:where\([^)]*\)/g, '');
  const ids = normalized.match(/#[a-z0-9_-]+/gi)?.length ?? 0;
  const classesAndPseudoClasses = normalized.match(
    /\.[a-z0-9_-]+|\[[^\]]+\]|:(?!:)[a-z0-9_-]+(?:\([^)]*\))?/gi,
  )?.length ?? 0;
  const pseudoElements = normalized.match(/::[a-z0-9_-]+/gi)?.length ?? 0;
  const types = normalized.match(/(?:^|[\s>+~])(?:[a-z][a-z0-9-]*\|)?[a-z][a-z0-9-]*/gi)?.length ?? 0;
  return [ids, classesAndPseudoClasses, types + pseudoElements];
}

function compareSpecificity(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return 0;
}

function assertCascadeResolution(relativePath, matchingSelectors, property, expected) {
  const root = postcss.parse(read(relativePath), { from: relativePath });
  const normalizedMatches = new Set(
    matchingSelectors.map((selector) => selector.trim().replace(/\s+/g, ' ')),
  );
  const candidates = [];
  let sourceOrder = 0;

  root.walkRules((rule) => {
    for (const rawSelector of rule.selectors) {
      const selector = rawSelector.trim().replace(/\s+/g, ' ');
      if (!normalizedMatches.has(selector)) continue;
      for (const node of rule.nodes ?? []) {
        if (node.type !== 'decl' || node.prop !== property) continue;
        candidates.push({
          important: node.important,
          specificity: selectorSpecificity(selector),
          sourceOrder,
          selector,
          value: node.value.trim(),
        });
        sourceOrder += 1;
      }
    }
  });

  const winner = candidates.reduce((current, candidate) => {
    if (!current) return candidate;
    if (candidate.important !== current.important) return candidate.important ? candidate : current;
    const specificityOrder = compareSpecificity(candidate.specificity, current.specificity);
    if (specificityOrder !== 0) return specificityOrder > 0 ? candidate : current;
    return candidate.sourceOrder > current.sourceOrder ? candidate : current;
  }, null);

  if (!winner) {
    failures.push(
      `${relativePath} is missing a cascade candidate for ${property} on ${matchingSelectors.join(' | ')}`,
    );
  } else if (winner.value !== expected) {
    failures.push(
      `${relativePath} cascade resolves ${property} to ${winner.value} via ${winner.selector}; expected ${expected}`,
    );
  }
}

const runtimeSources = walk(sourceRoot)
  .filter((absolutePath) => /\.(?:css|tsx?|mts|mjs)$/.test(absolutePath))
  .map(relativeToPortal);

for (const relativePath of new Set([...runtimeSources, 'index.html'])) {
  const source = read(relativePath);
  for (const match of source.matchAll(/\b(?:Inter|Cousine)\b/g)) {
    fail(relativePath, source, match.index, `still names legacy font ${match[0]}`);
  }
}

for (const relativePath of policySources) {
  const source = read(relativePath);
  for (const alias of surfaceAliases) {
    const index = source.indexOf(alias);
    if (index >= 0) fail(relativePath, source, index, `still uses sunset alias ${alias}`);
  }
}

const indexHtml = read('index.html');
const expectedFontQuery =
  'family=Geist+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600;700;800;900&display=swap';
if (!indexHtml.includes(expectedFontQuery)) {
  failures.push(`index.html is missing the ratified Geist weight request`);
}

const indexCss = read('src/index.css');
for (const [expected, label] of [
  ['--br-font-sans: "Geist", ui-sans-serif, system-ui, sans-serif;', 'canonical Sans token'],
  [
    '--br-font-mono: "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;',
    'canonical Mono token',
  ],
  ['--font-sans: var(--br-font-sans);', 'Tailwind Sans bridge'],
  ['--font-mono: var(--br-font-mono);', 'Tailwind Mono bridge'],
  ['--br-label-size: 12px;', 'label-size token'],
  ['--br-label-line-height: 16px;', 'label-line-height token'],
]) {
  if (!indexCss.includes(expected)) failures.push(`src/index.css is missing ${label}`);
}

for (const relativePath of activeStyles) {
  const source = read(relativePath);

  for (const match of source.matchAll(/font-size\s*:\s*([^;}\n]+)/g)) {
    const value = match[1];
    for (const unitMatch of value.matchAll(/(\d*\.?\d+)(px|rem)\b/g)) {
      const numeric = Number(unitMatch[1]);
      const pixels = unitMatch[2] === 'rem' ? numeric * 16 : numeric;
      if (pixels < 12) {
        fail(relativePath, source, match.index, `font-size ${value.trim()} falls below 12px`);
      }
    }
  }

  for (const match of source.matchAll(/letter-spacing\s*:\s*([^;}\n]+)/g)) {
    const value = match[1].trim().replace(/\s*!important$/, '');
    if (!['0', 'normal', 'inherit', 'initial'].includes(value)) {
      fail(relativePath, source, match.index, `letter-spacing must resolve to zero, found ${value}`);
    }
  }

  for (const match of source.matchAll(/text-transform\s*:\s*([^;}\n]+)/g)) {
    const value = match[1].trim().replace(/\s*!important$/, '');
    if (!['none', 'inherit', 'initial'].includes(value)) {
      fail(relativePath, source, match.index, `text-transform must preserve authored casing, found ${value}`);
    }
  }

  for (const match of source.matchAll(/(?<!-)font-weight\s*:\s*([^;}\n]+)/g)) {
    const value = match[1].trim().replace(/\s*!important$/, '');
    if (!allowedFontWeights.has(value)) {
      fail(
        relativePath,
        source,
        match.index,
        `font weight must use a supported discrete token, found ${value}`,
      );
    }
  }

  const root = postcss.parse(source, { from: relativePath });
  root.walkRules((rule) => {
    const declarations = new Map();
    for (const node of rule.nodes ?? []) {
      if (node.type === 'decl') declarations.set(node.prop, node.value.trim());
    }

    const familyValue = declarations.get('font-family');
    const family = familyValue?.match(/^var\(--br-font-(sans|mono)\)$/i)?.[1];
    const declaredSize = declarations.get('font-size');
    const declaredPixels = declaredSize ? fontSizePixels(declaredSize) : null;
    const weightValue = declarations.get('font-weight');
    const numericWeight = fontWeightNumber(weightValue);

    for (const rawSelector of rule.selectors) {
      const selector = rawSelector.trim().replace(/\s+/g, ' ');
      const target = targetCompound(selector);
      const roleTarget = semanticRoleTarget(target);
      const rideOverviewException = /\.ride-detail-overview-stat__value\b/i.test(selector);
      const editorialDisplay =
        /(?:^|[^a-z0-9])(?:access|app-boot)(?=$|[^a-z0-9])/i.test(selector);
      const explicitTechnicalData = technicalDataSelectorOverrides.some((pattern) => pattern.test(selector));
      const explicitSansUi = sansUiSelectorOverrides.some((pattern) => pattern.test(selector));
      const explicitBodyCopy = bodyCopySelectorOverrides.some((pattern) => pattern.test(selector));
      const headingRole =
        isTypeSelector(target, 'h[1-6]')
        || (
          headingSelectorPattern.test(roleTarget)
          && !/^(?:meta|copy|description|subtitle|subline|note|caption|label|value|stat|stats|count|age|date)(?:--|$)/i.test(roleTarget)
        );
      const bodyRole =
        !headingRole
        && (
          explicitBodyCopy
          ||
          bodySelectorPattern.test(roleTarget)
          || isTypeSelector(target, 'p')
        );
      const labelRole =
        !bodyRole
        && (
          labelSelectorPattern.test(roleTarget)
          || isTypeSelector(target, 'label')
          || (
            /(?:^|[^a-z0-9])(?:status|state|action)(?=$|[^a-z0-9])/i.test(selector)
            && /^(?:strong|span|small|em|b|p)(?=$|[.#:\[])/i.test(target)
          )
        );
      const controlRole =
        !bodyRole
        && (
          controlSelectorPattern.test(roleTarget)
          || isTypeSelector(target, 'button|input|select|textarea|option|summary')
          || (
            controlSelectorPattern.test(selector)
            && roleBoundary(['item', 'label', 'meta', 'current']).test(roleTarget)
          )
        );
      const dataRole =
        explicitTechnicalData
        || (
          !explicitSansUi
          && !headingRole
          && !bodyRole
          && !labelRole
          && !controlRole
          && dataSelectorPattern.test(roleTarget)
        );
      const sansRole =
        explicitSansUi
        || (
          !explicitTechnicalData
          && (headingRole || bodyRole || labelRole || controlRole)
        );

      if (numericWeight && [800, 900].includes(numericWeight) && !editorialDisplay) {
        failRule(
          relativePath,
          rule,
          `${numericWeight} weight is outside public-root/app-entry display scope (${selector})`,
        );
      }

      if (family === 'mono' && sansRole) {
        failRule(relativePath, rule, `${selector} is UI/body/label copy and must use Geist Sans`);
      }
      if (family === 'sans' && dataRole && !rideOverviewException) {
        failRule(relativePath, rule, `${selector} is numeric/technical data and must use Geist Mono`);
      }

      if (bodyRole && !explicitTechnicalData) {
        if (family === 'mono') {
          failRule(relativePath, rule, `body/helper copy must use Geist Sans (${selector})`);
        }
        if (declaredPixels !== null && declaredPixels < 15) {
          failRule(relativePath, rule, `body/helper copy falls below 15px (${selector})`);
        }
        if (numericWeight !== null && ![400, 500].includes(numericWeight)) {
          failRule(relativePath, rule, `body/helper copy must use weight 400 or 500 (${selector})`);
        }
      }

      if (
        headingRole
        && !explicitTechnicalData
        && declaredSize !== 'inherit'
        && numericWeight !== null
        && ![600, 700, 800, 900].includes(numericWeight)
      ) {
        failRule(relativePath, rule, `heading must use weight 600 or 700 (${selector})`);
      }

      if (
        labelRole
        && !explicitTechnicalData
        && declaredPixels === 12
        && numericWeight !== null
        && ![500, 600].includes(numericWeight)
      ) {
        failRule(relativePath, rule, `12px label/status must use weight 500 or 600 (${selector})`);
      }

      if (
        !explicitTechnicalData
        && (labelRole || controlRole)
        && declaredPixels !== null
        && declaredPixels <= 14
      ) {
        const resolvedLineHeight = lineHeightPixels(declarations.get('line-height'), declaredPixels);
        if (resolvedLineHeight === null || resolvedLineHeight < 16) {
          failRule(
            relativePath,
            rule,
            `small label/control must use a line box of at least 16px (${selector})`,
          );
        }
      }

      if (
        dataRole
        && numericWeight === 700
        && !rideOverviewException
        && !primaryDataSelectorOverrides.some((pattern) => pattern.test(selector))
        && !roleBoundary(['primary', 'record', 'total']).test(selector)
      ) {
        failRule(relativePath, rule, `data weight 700 is reserved for a primary total or record (${selector})`);
      }
    }

    if (declaredPixels === 12) {
      const lineHeight = declarations.get('line-height');
      if (lineHeight !== 'var(--br-label-line-height)') {
        failRule(
          relativePath,
          rule,
          `12px app-authored text must use var(--br-label-line-height) (${rule.selector})`,
        );
      }
    }
  });
}

for (const relativePath of runtimeSources.filter((file) => /\.tsx?$/.test(file))) {
  const source = read(relativePath);
  for (const match of source.matchAll(/fontSize\s*:\s*(\d+(?:\.\d+)?)/g)) {
    if (Number(match[1]) < 12) {
      fail(relativePath, source, match.index, `inline fontSize ${match[1]} falls below 12px`);
    }
  }
  for (const match of source.matchAll(/(?:ctx\.)?font\s*=\s*["'`](\d+(?:\.\d+)?)px/g)) {
    if (Number(match[1]) < 12) {
      fail(relativePath, source, match.index, `canvas font ${match[1]}px falls below 12px`);
    }
  }
  // The map ground's park names are cartographic labels set in MapLibre's
  // symbol layout, not portal copy (the ground ratified 2026-09-06,
  // history/ground-2026-09-06/README.md decision 2). Only that one
  // 'text-transform': 'uppercase' value in the style builder is exempt.
  const mapLabelCasing = relativePath === 'src/components/climb/climbMapStyle.ts';
  for (const match of source.matchAll(/\b(?:tracking-(?:tighter|tight|wide|wider|widest)|uppercase|capitalize|lowercase)\b/g)) {
    if (mapLabelCasing && match[0] === 'uppercase' && /'text-transform'\s*:\s*'uppercase'/.test(source.slice(Math.max(0, match.index - 24), match.index + 12))) continue;
    fail(relativePath, source, match.index, `utility ${match[0]} violates authored casing or zero tracking`);
  }
  for (const match of source.matchAll(/\bfont-(?:black|extrabold)\b/g)) {
    fail(relativePath, source, match.index, `utility ${match[0]} is not allowed in portal product UI`);
  }
  if (relativePath === 'src/components/ui/label.tsx') {
    for (const match of source.matchAll(/\bleading-none\b/g)) {
      fail(
        relativePath,
        source,
        match.index,
        'shared labels may not compose the tight line-height utility',
      );
    }
  }
}

assertContains(
  'src/styles/portal-spine.css',
  '.portal-truth-pill',
  'truth/status label selector',
);
assertContains(
  'src/styles/portal-spine.css',
  'font-family: var(--br-font-mono);',
  'canonical technical-data family',
);
assertContains(
  'src/styles/portal-surface-polish.css',
  '.ride-detail-page .ride-detail-overview-stat__value',
  'Ride overview exception selector',
);
assertContains(
  'src/styles/portal-climb-detail.css',
  '.climb-result-rider strong',
  'Climb rider identity font rule',
);
assertContains(
  'src/components/ride/RideRoom.tsx',
  'ride-room-stats',
  'shared ride metric family hook',
);
for (const [relativePath, expected, label] of [
  ['src/pages/RideViewCore.tsx', 'valueFamily="sans"', 'semantic proof datum family assignment'],
  ['src/styles/portal-ride-room.css', 'var(--br-font-mono)', 'shared ride numerical family'],
  ['src/pages/PublicPreview.tsx', 'RideRoomIdentity', 'preview consumes shared ride typography'],
  // One record board per climb (idm63, 2026-09-01): the rider hook lives on ClimbView.
  ['src/components/climb/ClimbLeaderboard.tsx', 'climb-result-rider', 'record board rider family hook'],
  ['src/components/climb/ClimbLeaderboard.tsx', 'climb-result-value', 'climb result value family hook'],
  ['src/components/admin-significance/PipelineFunnel.tsx', 'admin-v2-pipeline__stage-delta--mono', 'pipeline delta family hook'],
  ['src/components/admin/StravaPanel.tsx', 'admin-v2-detail-grid__value--sans', 'admin detail state family hook'],
]) {
  assertContains(relativePath, expected, label);
}

const sansSemanticSelectors = [
  '.feed-activity-card__comment-submit',
  '.portal-filter-list__item',
  '.ride-detail-proof-chip',
  '.ride-detail-proof-summary',
  '.ride-detail-proof-datum__value--sans',
  '.admin-v2-review-dot',
  '.admin-v2-tier-dots',
  '.public-preview-metric > .public-preview-metric__value--sans',
  '.public-preview-stat > .public-preview-stat__value--sans',
  '.climb-detail-leaderboard__rider',
  '.ride-detail-point-readout__summary-value--sans',
  '.admin-v2-detail-grid__value--sans',
  '.admin-v2-pipeline__stage > .admin-v2-pipeline__stage-delta--sans',
  '.climb-detail-section-heading__count-label',
];
const monoSemanticSelectors = [
  '.feed-activity-card__count-badge',
  '.portal-filter-list__item-count',
  '.ride-detail-proof-datum__value--mono',
  '.public-preview-metric > .public-preview-metric__value--mono',
  '.public-preview-stat > .public-preview-stat__value--mono',
  '.vault-card__stake strong',
  '.vault-detail-leaderboard__time',
  '.vault-detail-leaderboard__power',
  '.climb-detail-modal-pr-meta__date-value',
  '.climb-detail-modal-pr-meta__power',
  '.ride-detail-point-readout__item strong',
  '.ride-detail-point-readout__range b',
  '.climb-detail-section-heading__count',
  '.settings-v2-privacy-zone-radius-option__value',
  '.admin-v2-pipeline__stage > .admin-v2-pipeline__stage-delta--mono',
  '.admin-v2-pipeline__dropoffs > span > strong',
  '.admin-v2-detail-grid__value--mono',
  '.profile-v2-ride-row__metrics span',
  '.profile-v2-featured-ride__metrics span',
];
for (const selector of sansSemanticSelectors) {
  assertAllSelectorDeclarations(
    'src/styles/portal-spine.css',
    selector,
    'font-family',
    'var(--br-font-sans)',
  );
}
for (const selector of monoSemanticSelectors) {
  assertAllSelectorDeclarations(
    'src/styles/portal-spine.css',
    selector,
    'font-family',
    'var(--br-font-mono)',
  );
}

for (const [matchingSelectors, property, expected] of [
  [
    [
      '.public-preview-metric > strong',
      '.public-preview-metric > .public-preview-metric__value--sans',
    ],
    'font-family',
    'var(--br-font-sans)',
  ],
  [
    [
      '.public-preview-stat > strong',
      '.public-preview-stat > .public-preview-stat__value--sans',
    ],
    'font-family',
    'var(--br-font-sans)',
  ],
  [
    [
      '.admin-v2-pipeline__stage em',
      '.admin-v2-pipeline__stage > .admin-v2-pipeline__stage-delta--mono',
    ],
    'font-family',
    'var(--br-font-mono)',
  ],
  [
    [
      '.climb-detail-section-heading span',
      '.climb-detail-section-heading__count',
    ],
    'font-family',
    'var(--br-font-mono)',
  ],
  [
    [
      '.climb-detail-section-heading span',
      '.climb-detail-section-heading__count',
    ],
    'font-size',
    'var(--br-label-size)',
  ],
  [
    [
      '.climb-detail-section-heading span',
      '.climb-detail-section-heading__count-label',
    ],
    'font-family',
    'var(--br-font-sans)',
  ],
  [
    [
      '.climb-detail-section-heading span',
      '.climb-detail-section-heading__count-label',
    ],
    'font-size',
    'var(--br-label-size)',
  ],
]) {
  assertCascadeResolution(
    'src/styles/portal-spine.css',
    matchingSelectors,
    property,
    expected,
  );
}

for (const selector of [
  '.profile-v2-setup-banner__copy span',
  '.profile-v2-muted-line',
  '.portal-inline-alert > div > span',
  '.portal-inline-alert > span',
]) {
  for (const [property, expected] of [
    ['font-family', 'var(--br-font-sans)'],
    ['font-size', '15px'],
    ['font-weight', '400'],
    ['line-height', '1.45'],
  ]) {
    const selectorExpected = expected;
    assertCascadeResolution(
      'src/styles/portal-spine.css',
      [selector],
      property,
      selectorExpected,
    );
  }
}

// Upload's 2026-09-06 board owns this detail slot in the shared sheet.
for (const [property, expected] of [
  ['font-family', 'var(--br-font-sans)'],
  ['font-size', '13px'],
  ['font-weight', '400'],
  ['line-height', '18px'],
]) {
  assertCascadeResolution(
    'src/styles/portal-upload-sheet.css',
    ['.upload-sheet', '.upload-sheet__error p', '.upload-sheet__error .upload-activity-modal-error-detail'],
    property,
    expected,
  );
}

for (const selector of [
  '.portal-shell-popover__view-all',
  '.portal-shell-popover__menu-item',
]) {
  assertCascadeResolution(
    'src/styles/portal-spine.css',
    [selector],
    'line-height',
    'var(--br-label-line-height)',
  );
}

for (const [relativePath, expected, label] of [
  ['src/components/ride/ElevationChart.tsx', 'for (let m = 0; m < totalDistance; m += kmInterval)', 'non-overlapping final distance marker'],
  ['src/components/ride/ElevationChart.tsx', "ctx.textAlign = 'right';", 'right-aligned final distance marker'],
  ['src/components/admin-significance/GpdFitChart.tsx', 'margin={{ top: 20, right: 24, bottom: 24, left: 12 }}', 'GPD chart label margin'],
  ['src/components/admin-significance/GpdFitChart.tsx', 'width={56}', 'GPD chart Y-axis width'],
  ['src/components/admin-significance/ElevationProfile.tsx', 'margin={{ top: 20, right: 24, bottom: 24, left: 12 }}', 'elevation chart label margin'],
  ['src/components/admin-significance/ElevationProfile.tsx', 'width={56}', 'elevation chart Y-axis width'],
]) {
  assertContains(relativePath, expected, label);
}

if (!/\.portal-truth-pill\s*\{[^}]*font-family:\s*var\(--br-font-sans\)/s.test(read('src/styles/portal-spine.css'))) {
  failures.push('src/styles/portal-spine.css must keep truth/status pill copy in Geist Sans');
}
if (
  !/\.ride-detail-page \.ride-detail-overview-stat__value,[^}]*\{[^}]*font-family:\s*var\(--br-font-sans\)/s.test(
    read('src/styles/portal-surface-polish.css'),
  )
) {
  failures.push('src/styles/portal-surface-polish.css must preserve the Ride overview Sans-numeric exception');
}
if (!/\.portfolio-fact__value\s*\{[^}]*font-family:\s*var\(--br-font-mono\)/s.test(read('src/styles/portal-spine.css'))) {
  failures.push('src/styles/portal-spine.css must render portfolio data values in Geist Mono');
}
if (failures.length > 0) {
  console.error(`Typography boundary gate failed with ${failures.length} violation(s):`);
  for (const failure of failures.slice(0, 250)) console.error(`- ${failure}`);
  if (failures.length > 250) console.error(`- …and ${failures.length - 250} more`);
  process.exit(1);
}

console.log(
  'Typography boundary gate passed: Geist roles, 12px/16px floor, authored casing, zero tracking, and supported weights are enforced.',
);
