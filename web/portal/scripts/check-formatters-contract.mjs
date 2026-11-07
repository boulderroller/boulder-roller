#!/usr/bin/env node

import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import ts from 'typescript';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');
const sourceRoot = path.join(portalRoot, 'src');
const formatterPath = path.join(sourceRoot, 'lib/formatters.ts');
const failures = [];

const RAW_FORMAT_PATTERNS = [
  { label: '.toFixed(', pattern: /\.toFixed\s*\(/g },
  { label: '.toLocaleString(', pattern: /\.toLocaleString\s*\(/g },
  { label: '.toLocaleDateString(', pattern: /\.toLocaleDateString\s*\(/g },
  { label: '.toLocaleTimeString(', pattern: /\.toLocaleTimeString\s*\(/g },
  { label: 'new Intl.NumberFormat(', pattern: /new\s+Intl\.NumberFormat\s*\(/g },
  { label: 'new Intl.DateTimeFormat(', pattern: /new\s+Intl\.DateTimeFormat\s*\(/g },
  { label: 'new Intl.RelativeTimeFormat(', pattern: /new\s+Intl\.RelativeTimeFormat\s*\(/g },
  { label: '.toPrecision(', pattern: /\.toPrecision\s*\(/g },
  { label: '.toExponential(', pattern: /\.toExponential\s*\(/g },
];

const RAW_SOURCE_PATTERNS = [
  {
    label: 'direct absence literal',
    pattern: /(["'`])—\1/g,
    guidance: 'use ABSENT_VALUE from src/lib/formatters.ts',
  },
  {
    label: 'legacy absence marker',
    pattern: /(["'`])--(?:(?::--)|(?:\s+[^"'`\r\n]+))?\1/g,
    guidance: 'use ABSENT_VALUE from src/lib/formatters.ts',
  },
  {
    label: 'legacy JSX absence marker',
    pattern: />\s*(?:--:--|--)\s*</g,
    guidance: 'use ABSENT_VALUE from src/lib/formatters.ts',
  },
  {
    label: 'non-canonical date helper',
    // formatMonthYear() joined the shared formatter path on 2026-09-02 (the
    // profile's 'Since <Mon YYYY>' stamp); the name stays banned only as an
    // ad-hoc local helper, which the import check below catches.
    pattern: /\b(?:formatLongDate|formatShortDate|formatShortDateTime|formatRelativeDate|formatRelativeTime|formatTimeAgo|timeAgo)\b/g,
    guidance: 'use formatDate(), formatDateTime(), formatTime(), or formatMonthYear() from the shared formatter path',
  },
];

const RAW_DISPLAY_PATTERNS = [
  {
    label: 'single-character dash marker',
    pattern: /(["'])-\1/g,
    guidance: 'use ABSENT_VALUE unless this is an explicitly waived technical sign or slug separator',
  },
  {
    label: 'state-looking absence marker',
    pattern: /(["'])(?:Waiting|None|Never)\1/g,
    guidance: 'use ABSENT_VALUE unless this is an explicitly waived real product state',
  },
  {
    label: 'visible numeric rounding',
    pattern: /(?:\{|\$\{)Math\.(?:round|trunc)\s*\(/g,
    guidance: 'route the rendered numeral through the shared formatter path',
  },
  {
    label: 'unit without canonical spacing',
    pattern: /\b\d+(?:\.\d+)?(?:km²|km\/h|m\/h|W\/kg|kcal|bpm|rpm|mph|km|mi|kg|lb|ft|W|w)\b/g,
    guidance: 'use a semantic unit formatter or canonical spaced unit copy',
  },
  {
    label: 'manual numeric padding',
    pattern: /\.padStart\s*\(/g,
    guidance: 'use a duration or padded-integer formatter',
  },
  {
    label: 'ad-hoc capped count',
    pattern: /(?:\?|:)\s*(?:["'])\d+\+(?:["'])/g,
    guidance: 'use formatCappedInteger() from the shared formatter path',
  },
  {
    label: 'ad-hoc unit template',
    pattern: /\$\{[^}\n]+\}\s*(?:km\/h|m\/h|W\/kg|kcal|bpm|rpm|mph|km|mi|kg|lb|ft|W|w|m|s|h|%)(?=[^A-Za-z]|$)/g,
    guidance: 'use the semantic unit formatter',
  },
  {
    label: 'ad-hoc JSX unit',
    pattern: /(?<!\$)\{(?:Math\.round\([^}\n]+\)|[^{}\n]+)\}\s*(?:km\/h|m\/h|W\/kg|kcal|bpm|rpm|mph|km|mi|kg|lb|ft|W|w|m|s|h|%)(?=<|\s)/g,
    guidance: 'use the semantic unit formatter',
  },
];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function assertContains(content, needle, label) {
  check(content.includes(needle), `${label} must contain ${needle}`);
}

async function productionSources(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await productionSources(absolutePath));
      continue;
    }
    if (/\.(?:ts|tsx)$/.test(entry.name)) files.push(absolutePath);
  }
  return files;
}

function lineNumberAt(content, index) {
  return content.slice(0, index).split('\n').length;
}

function sourceLineAt(content, index) {
  const start = content.lastIndexOf('\n', Math.max(0, index - 1)) + 1;
  const end = content.indexOf('\n', index);
  return content.slice(start, end === -1 ? content.length : end);
}

function isCssPresentationLine(line) {
  return /(?:\bstyle\s*=|\b(?:rgb|rgba|hsl|hsla)\s*\(|^\s*(?:left|right|top|bottom|width|height)\s*:|--[a-z0-9-]+['"]?\s*:)/i.test(line);
}

const TECHNICAL_JSX_ATTRIBUTES = new Set([
  'key', 'id', 'className', 'style', 'to', 'href', 'src',
  'width', 'height', 'size', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
  'viewBox', 'strokeWidth', 'strokeOpacity', 'fillOpacity', 'offset', 'tabIndex',
]);

const CUSTOM_COMPONENT_DISPLAY_ATTRIBUTES = new Set([
  'value', 'meta', 'context', 'description', 'subtitle', 'message', 'title', 'alt', 'aria-label',
]);

const NATIVE_FORM_VALUE_ATTRIBUTES = new Set(['value', 'min', 'max', 'step']);
const DISPLAY_COLLECTION_ATTRIBUTES = new Set(['metrics', 'stats']);

function unwrapExpression(node) {
  let current = node;
  while (
    ts.isParenthesizedExpression(current)
    || ts.isAsExpression(current)
    || ts.isTypeAssertionExpression(current)
    || ts.isNonNullExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function isExactIdentifierExpression(node) {
  const expression = unwrapExpression(node);
  const name = ts.isIdentifier(expression)
    ? expression.text
    : ts.isPropertyAccessExpression(expression)
      ? expression.name.text
      : '';
  return /(?:^|_)(?:id|key)$/i.test(name) || /(?:Id|ID|Key)$/.test(name);
}

function typeIsDefinitelyNumber(type) {
  if (type.isUnion()) {
    const materialTypes = type.types.filter((member) => !(member.flags & (
      ts.TypeFlags.Null
      | ts.TypeFlags.Undefined
      | ts.TypeFlags.Never
    )));
    return materialTypes.length > 0 && materialTypes.every(typeIsDefinitelyNumber);
  }
  return Boolean(type.flags & (ts.TypeFlags.Number | ts.TypeFlags.NumberLiteral | ts.TypeFlags.NumberLike));
}

function syntaxLooksNumeric(node) {
  const expression = unwrapExpression(node);
  if (ts.isNumericLiteral(expression)) return true;
  if (ts.isPropertyAccessExpression(expression) && expression.name.text === 'length') return true;
  if (ts.isPrefixUnaryExpression(expression)) return syntaxLooksNumeric(expression.operand);
  if (ts.isBinaryExpression(expression)) {
    const arithmeticOperators = new Set([
      ts.SyntaxKind.MinusToken,
      ts.SyntaxKind.AsteriskToken,
      ts.SyntaxKind.SlashToken,
      ts.SyntaxKind.PercentToken,
      ts.SyntaxKind.AsteriskAsteriskToken,
    ]);
    if (arithmeticOperators.has(expression.operatorToken.kind)) return true;
    if (expression.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      return syntaxLooksNumeric(expression.left) || syntaxLooksNumeric(expression.right);
    }
  }
  return false;
}

function expressionCanRenderNumber(node, checker) {
  const expression = unwrapExpression(node);
  if (isExactIdentifierExpression(expression)) return false;
  if (ts.isConditionalExpression(expression)) {
    return expressionCanRenderNumber(expression.whenTrue, checker)
      || expressionCanRenderNumber(expression.whenFalse, checker);
  }
  if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken) {
    return expressionCanRenderNumber(expression.left, checker)
      || expressionCanRenderNumber(expression.right, checker);
  }
  const type = checker.getTypeAtLocation(expression);
  if (typeIsDefinitelyNumber(type)) return true;
  if (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) return syntaxLooksNumeric(expression);
  return false;
}

function jsxAttributeName(attribute) {
  return attribute.name.getText();
}

function nearestJsxAttribute(node) {
  let current = node.parent;
  while (current && !ts.isSourceFile(current)) {
    if (ts.isJsxAttribute(current)) return current;
    if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current)) return null;
    current = current.parent;
  }
  return null;
}

function jsxAttributeTagName(attribute) {
  const opening = attribute.parent?.parent;
  if (!opening || (!ts.isJsxOpeningElement(opening) && !ts.isJsxSelfClosingElement(opening))) return '';
  return opening.tagName.getText();
}

function isTechnicalTemplateContext(node, sourceFile) {
  const attribute = nearestJsxAttribute(node);
  if (attribute) {
    const name = jsxAttributeName(attribute);
    const tagName = jsxAttributeTagName(attribute);
    const isNativeFormValue = /^[a-z]/.test(tagName) && NATIVE_FORM_VALUE_ATTRIBUTES.has(name);
    if (TECHNICAL_JSX_ATTRIBUTES.has(name) || isNativeFormValue || name.startsWith('data-') || /^on[A-Z]/.test(name)) return true;
  }

  let current = node.parent;
  while (current && !ts.isSourceFile(current)) {
    if (ts.isCallExpression(current)) {
      const callee = current.expression.getText(sourceFile);
      if (/(?:navigate|encodeURIComponent|matchMedia|console\.|localStorage\.|sessionStorage\.|URLSearchParams|\.open$|\.style\.|\.setProperty$)/.test(callee)) {
        return true;
      }
    }
    if (ts.isPropertyAssignment(current)) {
      const name = current.name.getText(sourceFile).replace(/["']/g, '');
      if (/(?:^|_)(?:id|key|path|route|url|href|className|style)$/i.test(name) || /(?:Id|ID|Key|Path|Url|URL)$/.test(name)) {
        return true;
      }
    }
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name)) {
      if (/(?:id|key|path|route|url|href|className|style|width|height|size|offset)$/i.test(current.name.text)) return true;
    }
    if (ts.isFunctionLike(current) && current.name && /(?:id|key|path|route|url)$/i.test(current.name.getText(sourceFile))) {
      return true;
    }
    if (
      ts.isBinaryExpression(current)
      && current.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && /\.style\./.test(current.left.getText(sourceFile))
    ) {
      return true;
    }
    current = current.parent;
  }

  const line = sourceFile.getFullText().slice(
    sourceFile.getLineStarts()[sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line],
    sourceFile.getLineStarts()[sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1] ?? sourceFile.end,
  );
  return isCssPresentationLine(line) || /<(?:ele|time|trkpt)\b/.test(line);
}

function isCustomComponentAttribute(attribute) {
  return /^[A-Z]/.test(jsxAttributeTagName(attribute));
}

function checkInlineDisplayCollection(attribute, checker, sourceFile, relativePath) {
  if (!isCustomComponentAttribute(attribute)) return;
  if (!DISPLAY_COLLECTION_ATTRIBUTES.has(jsxAttributeName(attribute))) return;
  if (!attribute.initializer || !ts.isJsxExpression(attribute.initializer) || !attribute.initializer.expression) return;

  const visit = (node) => {
    if (ts.isPropertyAssignment(node)) {
      const propertyName = node.name.getText(sourceFile).replace(/["']/g, '');
      if (CUSTOM_COMPONENT_DISPLAY_ATTRIBUTES.has(propertyName) && expressionCanRenderNumber(node.initializer, checker)) {
        reportAstFailure(
          sourceFile,
          node.initializer,
          relativePath,
          `raw numeric ${propertyName} field in ${jsxAttributeName(attribute)}`,
          'route the displayed numeral through src/lib/formatters.ts or useFormatters()',
        );
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(attribute.initializer.expression);
}

function reportAstFailure(sourceFile, node, relativePath, label, guidance) {
  const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
  failures.push(`${relativePath}:${line} uses ${label}; ${guidance}`);
}

function checkRawNumericDisplays(sourceFile, checker, relativePath) {
  const visit = (node) => {
    if (ts.isTemplateSpan(node) && expressionCanRenderNumber(node.expression, checker) && !isTechnicalTemplateContext(node, sourceFile)) {
      reportAstFailure(
        sourceFile,
        node.expression,
        relativePath,
        'raw numeric template interpolation',
        'route the displayed numeral through src/lib/formatters.ts or useFormatters()',
      );
    }

    if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
      const expression = unwrapExpression(node.expression);
      const isNumericAndJsxChain = ts.isBinaryExpression(expression)
        && expression.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
        && expressionCanRenderNumber(expression.left, checker)
        && (ts.isJsxElement(unwrapExpression(expression.right)) || ts.isJsxSelfClosingElement(unwrapExpression(expression.right)));
      if (expressionCanRenderNumber(expression, checker) && !isNumericAndJsxChain) {
        reportAstFailure(
          sourceFile,
          expression,
          relativePath,
          'raw numeric JSX value',
          'route the displayed numeral through src/lib/formatters.ts or useFormatters()',
        );
      }
      if (isNumericAndJsxChain) {
        reportAstFailure(
          sourceFile,
          expression.left,
          relativePath,
          'numeric JSX short-circuit',
          'compare explicitly so a zero cannot render as text',
        );
      }
    }

    if (ts.isJsxAttribute(node) && node.initializer && ts.isJsxExpression(node.initializer) && node.initializer.expression) {
      const name = jsxAttributeName(node);
      const isDisplayAttribute = name === 'aria-label'
        || name === 'title'
        || name === 'alt'
        || (isCustomComponentAttribute(node) && CUSTOM_COMPONENT_DISPLAY_ATTRIBUTES.has(name));
      if (isDisplayAttribute && expressionCanRenderNumber(node.initializer.expression, checker)) {
        reportAstFailure(
          sourceFile,
          node.initializer.expression,
          relativePath,
          `raw numeric ${name} prop`,
          'route the displayed numeral through src/lib/formatters.ts or useFormatters()',
        );
      }
      checkInlineDisplayCollection(node, checker, sourceFile, relativePath);
    }

    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
}

const DISPLAY_PATTERN_WAIVERS = new Map([
  ['single-character dash marker', new Map([
    ['src/pages/VaultView.tsx', ["const sign = seconds > 0 ? '-' : '+';"]],
    ['src/pages/RideViewCore.tsx', [".replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '')"]],
  ])],
  ['state-looking absence marker', new Map([
    ['src/pages/MyActivities.tsx', ["const CONTRACT_WAITING = 'Waiting';"]],
    ['src/pages/ClimbView.tsx', ["? 'Waiting'"]],
  ])],
]);

function isDisplayPatternWaived(label, relativePath, line) {
  return DISPLAY_PATTERN_WAIVERS.get(label)?.get(relativePath)?.some((needle) => line.includes(needle)) ?? false;
}

const formatters = await readFile(formatterPath, 'utf8');
const useFormatters = await readFile(path.join(sourceRoot, 'hooks/useFormatters.ts'), 'utf8');
const packageJson = JSON.parse(await readFile(path.join(portalRoot, 'package.json'), 'utf8'));
const tsconfig = ts.readConfigFile(path.join(portalRoot, 'tsconfig.json'), ts.sys.readFile);
check(!tsconfig.error, 'formatter guard must be able to read tsconfig.json');
const parsedTsconfig = ts.parseJsonConfigFileContent(tsconfig.config ?? {}, ts.sys, portalRoot);
const typeProgram = ts.createProgram({
  rootNames: parsedTsconfig.fileNames,
  options: parsedTsconfig.options,
});
const typeChecker = typeProgram.getTypeChecker();
const sourcePaths = await productionSources(sourceRoot);

for (const formatter of [
  'ABSENT_VALUE',
  'formatFixed',
  'formatInteger',
  'formatTokenAmount',
  'formatCompactNumber',
  'formatPercent',
  'formatDate',
  'formatDateTime',
  'formatTime',
]) {
  check(
    formatters.includes(formatter === 'ABSENT_VALUE' ? 'export const ABSENT_VALUE' : `export function ${formatter}`),
    `shared formatter module must export ${formatter}`,
  );
  check(
    useFormatters.includes(formatter),
    `useFormatters bridge must expose ${formatter}`,
  );
}

for (const sourcePath of sourcePaths) {
  if (sourcePath === formatterPath) continue;
  const content = await readFile(sourcePath, 'utf8');
  const relativePath = path.relative(portalRoot, sourcePath);
  for (const { label, pattern } of RAW_FORMAT_PATTERNS) {
    pattern.lastIndex = 0;
    for (const match of content.matchAll(pattern)) {
      failures.push(
        `${relativePath}:${lineNumberAt(content, match.index ?? 0)} uses raw ${label}; route it through src/lib/formatters.ts or useFormatters()`,
      );
    }
  }

  for (const { label, pattern, guidance } of RAW_SOURCE_PATTERNS) {
    pattern.lastIndex = 0;
    for (const match of content.matchAll(pattern)) {
      failures.push(
        `${relativePath}:${lineNumberAt(content, match.index ?? 0)} uses ${label}; ${guidance}`,
      );
    }
  }

  const isDisplaySource = relativePath.endsWith('.tsx');
  if (isDisplaySource) {
    for (const { label, pattern, guidance } of RAW_DISPLAY_PATTERNS) {
      pattern.lastIndex = 0;
      for (const match of content.matchAll(pattern)) {
        const matchIndex = match.index ?? 0;
        const sourceLine = sourceLineAt(content, matchIndex);
        if (isDisplayPatternWaived(label, relativePath, sourceLine)) {
          continue;
        }
        if (label.startsWith('ad-hoc') && isCssPresentationLine(sourceLine)) {
          continue;
        }
        failures.push(
          `${relativePath}:${lineNumberAt(content, matchIndex)} uses ${label}; ${guidance}`,
        );
      }
    }

    const sourceFile = typeProgram.getSourceFile(sourcePath);
    check(Boolean(sourceFile), `formatter guard must parse ${relativePath}`);
    if (sourceFile) checkRawNumericDisplays(sourceFile, typeChecker, relativePath);
  }
}

// Preserve the existing Gate A formatter and measurement contracts while the
// global scan prevents the same drift from returning elsewhere.
const rideView = await readFile(path.join(sourceRoot, 'pages/RideViewCore.tsx'), 'utf8');
const activityFeedCore = await readFile(path.join(sourceRoot, 'components/feed/ActivityFeedCore.tsx'), 'utf8');
const activityFeedItem = await readFile(path.join(sourceRoot, 'components/feed/ActivityFeedItem.tsx'), 'utf8');
const spineCss = await readFile(path.join(sourceRoot, 'styles/portal-spine.css'), 'utf8');
const routeSpec = await readFile(path.join(portalRoot, 'e2e/portal-v2-routes.spec.ts'), 'utf8');
const dataInteractionContract = await readFile(
  path.join(repoRoot, 'docs/design/PORTAL_DATA_INTERACTION_CONTRACT.md'),
  'utf8',
);

for (const needle of [
  'duration: formatDuration',
  'integer: formatIntegerLabel',
  'percent: formatPercent',
  'watts: formatWatts',
  'heartRate: formatHeartRate',
  'cadence: formatCadence',
  'formatDateTime(proof.finalizedAt)',
  'formatPercent(selectedClimb.avgGradient)',
  'formatPercent(activePointGrade)',
  'formatWatts(activePointPower)',
  'formatHeartRate(activePointHeartRate)',
  'formatCadence(activePointCadence)',
]) {
  assertContains(rideView, needle, 'RideView formatter contract');
}

for (const needle of [
  'formatDateTime(createdDate)',
  'formatDurationCompact(meta?.durationS)',
  'formatDistance(meta.distanceM)',
  'formatElevation(elevationM)',
]) {
  assertContains(activityFeedCore, needle, 'ActivityFeed formatter contract');
}

for (const needle of [
  'formatTokenAmount(activity.calEarned)',
  'formatCappedInteger(likeCount)',
  'formatInteger(commentCount)',
  'formatCappedInteger(likeCount)',
  'formatInteger(commentCount)',
]) {
  assertContains(activityFeedItem, needle, 'ActivityFeedItem formatter contract');
}

for (const needle of [
  '.ride-detail-overview-stat__value',
  'font-variant-numeric: tabular-nums',
  '.feed-activity-card__metrics',
  '.feed-activity-card__compact-token',
]) {
  assertContains(spineCss, needle, 'portal-spine numeric contract');
}

for (const needle of [
  "test('gate a contract measurements'",
  'rideview-contract-measurements.json',
  'valueLabelRatio',
  'hoverLatencyMs',
  'toBeLessThanOrEqual(1)',
  'toBeLessThan(100)',
]) {
  assertContains(routeSpec, needle, 'Gate A contract measurement harness');
}

assertContains(
  dataInteractionContract,
  'test-results/gate-a/rideview-contract-measurements.json',
  'portal data-interaction contract',
);


const settings = await readFile(path.join(sourceRoot, 'pages/Settings.tsx'), 'utf8');
check(
  formatters.includes('export function isPlausibleWeightKg'),
  'shared formatter module must expose the ratified 30-200 kg sanity check',
);
check(
  settings.includes('weightNeedsUnitCheck') && settings.includes('isPlausibleWeightKg'),
  'Settings must surface invalid or suspicious weight entries before they can corrupt W/kg',
);

check(
  packageJson.scripts?.['qa:formatters-contract'] === 'node scripts/check-formatters-contract.mjs',
  'package.json must expose qa:formatters-contract',
);
check(
  packageJson.scripts?.['perf:release']?.includes('npm run qa:formatters-contract'),
  'package.json perf:release must run qa:formatters-contract so CI and Vercel fail on raw formatters',
);

if (failures.length > 0) {
  console.error('Formatter contract gate failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log('Formatter contract gate passed: production formatting has one guarded source path.');
