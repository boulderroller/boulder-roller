import { ABSENT_VALUE } from './formatters.ts';

const U64_MAX = (1n << 64n) - 1n;
const U64_MAX_TEXT = U64_MAX.toString();
const BASE_UNITS_PATTERN = /^[0-9]+$/;
const DECIMAL_UNITS_PATTERN = /^[0-9]+(?:\.[0-9]+)?$/;

function parseBaseUnits(value: string): bigint | null {
  const normalized = value.trim();
  if (!BASE_UNITS_PATTERN.test(normalized)) return null;
  const significant = normalized.replace(/^0+/, '') || '0';
  if (
    significant.length > U64_MAX_TEXT.length
    || (significant.length === U64_MAX_TEXT.length && significant > U64_MAX_TEXT)
  ) return null;
  return BigInt(significant);
}

function requireBaseUnits(value: string): bigint {
  const amount = parseBaseUnits(value);
  if (amount == null) throw new RangeError('Token base units must be a u64 decimal string.');
  return amount;
}

function groupWholeUnits(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export function decimalToBaseUnits(value: string, decimals: number): string | null {
  const normalized = value.trim();
  if (!Number.isInteger(decimals) || decimals < 0) return null;
  if (!DECIMAL_UNITS_PATTERN.test(normalized)) return null;

  const [whole, fraction = ''] = normalized.split('.');
  if (fraction.length > decimals) return null;
  const paddedFraction = fraction.padEnd(decimals, '0');
  const raw = `${whole}${paddedFraction}`.replace(/^0+/, '') || '0';
  if (
    raw.length > U64_MAX_TEXT.length
    || (raw.length === U64_MAX_TEXT.length && raw > U64_MAX_TEXT)
  ) return null;
  return BigInt(raw).toString();
}

export function compareBaseUnits(left: string, right: string): -1 | 0 | 1 {
  const leftAmount = requireBaseUnits(left);
  const rightAmount = requireBaseUnits(right);
  if (leftAmount < rightAmount) return -1;
  if (leftAmount > rightAmount) return 1;
  return 0;
}

export function isPositiveBaseUnits(value: string | null | undefined): boolean {
  if (value == null) return false;
  const amount = parseBaseUnits(value);
  return amount != null && amount > 0n;
}

export function sumBaseUnits(values: readonly string[]): string {
  return values.reduce((total, value) => total + requireBaseUnits(value), 0n).toString();
}

export function formatBaseUnits(
  value: string,
  decimals: number,
  maximumFractionDigits = decimals,
): string {
  if (!Number.isInteger(decimals) || decimals < 0) return ABSENT_VALUE;
  if (!Number.isInteger(maximumFractionDigits) || maximumFractionDigits < 0) return ABSENT_VALUE;
  const amount = parseBaseUnits(value);
  if (amount == null) return ABSENT_VALUE;

  const visibleDecimals = Math.min(decimals, maximumFractionDigits);
  let visibleAmount = amount;
  if (visibleDecimals < decimals) {
    const divisor = 10n ** BigInt(decimals - visibleDecimals);
    visibleAmount = (amount + divisor / 2n) / divisor;
    if (amount > 0n && visibleAmount === 0n) {
      return visibleDecimals === 0
        ? '<1'
        : `<0.${'0'.repeat(visibleDecimals - 1)}1`;
    }
  }

  if (visibleDecimals === 0) return groupWholeUnits(visibleAmount.toString());
  const scale = 10n ** BigInt(visibleDecimals);
  const whole = visibleAmount / scale;
  const fraction = (visibleAmount % scale)
    .toString()
    .padStart(visibleDecimals, '0')
    .replace(/0+$/, '');
  const groupedWhole = groupWholeUnits(whole.toString());
  return fraction ? `${groupedWhole}.${fraction}` : groupedWhole;
}

/**
 * A base-unit amount as a plain decimal string an amount field can hold
 * (no grouping, no rounding): "12345000000" at 9 decimals → "12.345".
 */
export function baseUnitsToDecimalString(value: string, decimals: number): string {
  if (!Number.isInteger(decimals) || decimals < 0) return ABSENT_VALUE;
  const amount = parseBaseUnits(value);
  if (amount == null) return ABSENT_VALUE;
  if (decimals === 0) return amount.toString();
  const scale = 10n ** BigInt(decimals);
  const whole = amount / scale;
  const fraction = (amount % scale)
    .toString()
    .padStart(decimals, '0')
    .replace(/0+$/, '');
  return fraction ? `${whole.toString()}.${fraction}` : whole.toString();
}

export function formatCompactBaseUnits(
  value: string,
  decimals: number,
  maximumFractionDigits = 1,
): string {
  if (!Number.isInteger(decimals) || decimals < 0) return ABSENT_VALUE;
  if (!Number.isInteger(maximumFractionDigits) || maximumFractionDigits < 0) return ABSENT_VALUE;
  const amount = parseBaseUnits(value);
  if (amount == null) return ABSENT_VALUE;

  const scale = 10n ** BigInt(decimals);
  const thresholds = [
    { units: 1_000_000_000n, suffix: 'B' },
    { units: 1_000_000n, suffix: 'M' },
    { units: 1_000n, suffix: 'K' },
  ];
  const threshold = thresholds.find((candidate) => amount >= candidate.units * scale);
  if (!threshold) return formatBaseUnits(value, decimals, 2);

  const fractionScale = 10n ** BigInt(maximumFractionDigits);
  const denominator = threshold.units * scale;
  const rounded = (amount * fractionScale + denominator / 2n) / denominator;
  const whole = rounded / fractionScale;
  const fraction = maximumFractionDigits === 0
    ? ''
    : (rounded % fractionScale)
        .toString()
        .padStart(maximumFractionDigits, '0')
        .replace(/0+$/, '');
  return `${whole}${fraction ? `.${fraction}` : ''}${threshold.suffix}`;
}
