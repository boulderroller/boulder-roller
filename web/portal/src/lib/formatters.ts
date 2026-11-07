/**
 * Unit-aware formatting utilities
 *
 * All internal values are stored in metric (meters, kg, m/s).
 * These functions convert for display based on user preference.
 */

export type Units = 'metric' | 'imperial';

export const ABSENT_VALUE = '—';

const EXACT_INTEGER_PATTERN = /^[0-9]+$/;
const BASIS_POINTS_DENOMINATOR = 10_000n;

export function calculateNetAmountBaseUnits(
  grossBaseUnits: string,
  feeBps: string,
): { feeBaseUnits: string; netBaseUnits: string } | null {
  const gross = grossBaseUnits.trim();
  const basisPoints = feeBps.trim();
  if (!EXACT_INTEGER_PATTERN.test(gross) || !EXACT_INTEGER_PATTERN.test(basisPoints)) {
    return null;
  }

  const grossAmount = BigInt(gross);
  const feeBasisPoints = BigInt(basisPoints);
  if (feeBasisPoints > BASIS_POINTS_DENOMINATOR) return null;

  const feeAmount = grossAmount * feeBasisPoints / BASIS_POINTS_DENOMINATOR;
  return {
    feeBaseUnits: feeAmount.toString(),
    netBaseUnits: (grossAmount - feeAmount).toString(),
  };
}

export function formatBasisPointsPercentage(feeBps: string): string {
  const normalized = feeBps.trim();
  if (!EXACT_INTEGER_PATTERN.test(normalized)) return ABSENT_VALUE;
  const basisPoints = BigInt(normalized);
  if (basisPoints > BASIS_POINTS_DENOMINATOR) return ABSENT_VALUE;

  const whole = basisPoints / 100n;
  const fraction = (basisPoints % 100n).toString().padStart(2, '0').replace(/0+$/, '');
  return `${whole}${fraction ? `.${fraction}` : ''}%`;
}

// Conversion constants
const METERS_TO_FEET = 3.28084;
const METERS_TO_MILES = 0.000621371;
const KG_TO_LB = 2.20462;
const MPS_TO_KMH = 3.6;
const MPS_TO_MPH = 2.23694;
const KMH_TO_MPH = 0.621371;

export const MIN_WEIGHT_KG = 30;
export const MAX_WEIGHT_KG = 200;
export const MIN_WEIGHT_LB = Math.round(MIN_WEIGHT_KG * KG_TO_LB);
export const MAX_WEIGHT_LB = Math.round(MAX_WEIGHT_KG * KG_TO_LB);
export const WEIGHT_UNIT_CHECK_KG = 140;

/**
 * Format distance (meters -> km or mi)
 */
export function formatDistance(meters: number | null | undefined, units: Units): string {
  if (meters == null || !Number.isFinite(meters)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return `${formatNumber(meters * METERS_TO_MILES, 1, 1)} mi`;
  }

  return `${formatNumber(meters / 1000, 1, 1)} km`;
}

/**
 * Format distance value only (no unit suffix)
 */
export function formatDistanceValue(meters: number | null | undefined, units: Units): string {
  if (meters == null || !Number.isFinite(meters)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return formatNumber(meters * METERS_TO_MILES, 1, 1);
  }

  return formatNumber(meters / 1000, 1, 1);
}

/**
 * Format elevation (meters -> m or ft)
 */
export function formatElevation(meters: number | null | undefined, units: Units): string {
  if (meters == null || !Number.isFinite(meters)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return `${formatNumber(meters * METERS_TO_FEET, 0, 0)} ft`;
  }

  return `${formatNumber(meters, 0, 0)} m`;
}

/**
 * Format elevation value only (no unit suffix)
 */
export function formatElevationValue(meters: number | null | undefined, units: Units): string {
  if (meters == null || !Number.isFinite(meters)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return formatNumber(meters * METERS_TO_FEET, 0, 0);
  }

  return formatNumber(meters, 0, 0);
}

/**
 * Format speed (m/s -> km/h or mph)
 */
export function formatSpeed(mps: number | null | undefined, units: Units): string {
  if (mps == null || !Number.isFinite(mps)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return `${formatNumber(mps * MPS_TO_MPH, 1, 1)} mph`;
  }

  return `${formatNumber(mps * MPS_TO_KMH, 1, 1)} km/h`;
}

/**
 * Format speed from km/h (for pre-converted values)
 */
export function formatSpeedKmh(kmh: number | null | undefined, units: Units): string {
  if (kmh == null || !Number.isFinite(kmh)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return `${formatNumber(kmh * KMH_TO_MPH, 1, 1)} mph`;
  }

  return `${formatNumber(kmh, 1, 1)} km/h`;
}

/**
 * Format speed value only (no unit suffix) from m/s
 */
export function formatSpeedValue(mps: number | null | undefined, units: Units): string {
  if (mps == null || !Number.isFinite(mps)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return formatNumber(mps * MPS_TO_MPH, 1, 1);
  }

  return formatNumber(mps * MPS_TO_KMH, 1, 1);
}

/**
 * Format weight (kg -> kg or lb)
 */
export function formatWeight(kg: number | null | undefined, units: Units): string {
  if (kg == null || !Number.isFinite(kg)) return ABSENT_VALUE;

  if (units === 'imperial') {
    return `${formatNumber(kg * KG_TO_LB, 0, 0)} lb`;
  }

  return `${formatNumber(kg, 1, 1)} kg`;
}

export function formatWeightRange(
  minimumKg: number | null | undefined,
  maximumKg: number | null | undefined,
  units: Units,
): string {
  if (
    minimumKg == null
    || maximumKg == null
    || !Number.isFinite(minimumKg)
    || !Number.isFinite(maximumKg)
  ) return ABSENT_VALUE;
  if (units === 'imperial') {
    return `${formatNumber(minimumKg * KG_TO_LB, 0)}–${formatNumber(maximumKg * KG_TO_LB, 0)} lb`;
  }
  return `${formatNumber(minimumKg, 0)}–${formatNumber(maximumKg, 0)} kg`;
}

/**
 * Parse weight input to kg (accepts kg or lb based on units)
 */
export function parseWeight(value: string, units: Units): number | null {
  const num = parseFloat(value);
  if (!Number.isFinite(num)) return null;

  if (units === 'imperial') {
    const kilograms = num / KG_TO_LB;
    if (num >= MIN_WEIGHT_LB && num <= MAX_WEIGHT_LB) {
      return Math.min(MAX_WEIGHT_KG, Math.max(MIN_WEIGHT_KG, kilograms));
    }
    return kilograms;
  }

  return num;
}

export function isPlausibleWeightKg(value: number | null | undefined): value is number {
  return typeof value === 'number'
    && Number.isFinite(value)
    && value >= MIN_WEIGHT_KG
    && value <= MAX_WEIGHT_KG;
}

/**
 * Format weight for input display (shows in user's units)
 */
export function weightForInput(kg: number | null | undefined, units: Units): string {
  if (kg == null || !Number.isFinite(kg)) return '';

  if (units === 'imperial') {
    return Math.round(kg * KG_TO_LB).toString();
  }

  return formatFixed(kg, 1);
}

/**
 * Get weight unit label
 */
export function getWeightUnit(units: Units): string {
  return units === 'imperial' ? 'lb' : 'kg';
}

/**
 * Get distance unit label (short)
 */
export function getDistanceUnit(units: Units): string {
  return units === 'imperial' ? 'mi' : 'km';
}

/**
 * Get elevation unit label
 */
export function getElevationUnit(units: Units): string {
  return units === 'imperial' ? 'ft' : 'm';
}

/**
 * Get speed unit label
 */
export function getSpeedUnit(units: Units): string {
  return units === 'imperial' ? 'mph' : 'km/h';
}

/**
 * Format duration (seconds -> h:mm:ss or mm:ss)
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

/** Match the iOS short-duration ledger: seconds, minutes, then h:mm. */
export function formatDurationCompact(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;

  const totalSeconds = Math.max(Math.round(seconds), 1);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}`;
  }
  if (minutes > 0) return `${minutes} min`;
  return `${totalSeconds} s`;
}

/** Hours and minutes with an explicit zero-minute value, matching profile summaries. */
export function formatHoursMinutes(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;
  const totalSeconds = Math.max(Math.round(seconds), 1);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours === 0 && minutes === 0) return `${totalSeconds} s`;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

/** Format a timed effort as minutes and seconds, or h:mm:ss above one hour. */
export function formatRaceTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;
  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

/** Preserve the portal ride-summary convention: h mm for long rides, mm:ss otherwise. */
export function formatRideDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;
  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes.toString().padStart(2, '0')}m`;
  return formatRaceTime(totalSeconds);
}

export function formatDurationWords(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return ABSENT_VALUE;
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
}

/**
 * Locale-independent fixed decimal output. Use this for technical ASCII
 * serialization (SVG, GPX, query bounds) and exact diagnostic precision.
 */
export function formatFixed(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  const safeDigits = Math.min(20, Math.max(0, Math.trunc(digits)));
  return value.toFixed(safeDigits);
}

export function roundToDigits(value: number, digits: number): number {
  if (!Number.isFinite(value)) return value;
  const safeDigits = Math.min(15, Math.max(0, Math.trunc(digits)));
  const factor = 10 ** safeDigits;
  return Math.round(value * factor) / factor;
}

export function formatIntegerInput(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '';
  return formatFixed(value, 0);
}

export function formatPaddedInteger(value: number | null | undefined, width = 2): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return formatFixed(Math.trunc(value), 0).padStart(Math.max(1, Math.trunc(width)), '0');
}

export function formatNumber(
  value: number | null | undefined,
  maximumFractionDigits = 0,
  minimumFractionDigits = 0,
): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return value.toLocaleString('en-US', {
    maximumFractionDigits,
    minimumFractionDigits,
  });
}

export function formatInteger(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return Math.round(value).toLocaleString('en-US');
}

export function formatCappedInteger(
  value: number | null | undefined,
  maximum = 99,
): string {
  if (value == null || !Number.isFinite(value) || !Number.isFinite(maximum)) return ABSENT_VALUE;
  const roundedMaximum = Math.max(0, Math.round(maximum));
  return value > roundedMaximum ? `${formatInteger(roundedMaximum)}+` : formatInteger(value);
}

/** Exact technical identifiers: no locale grouping and no lost leading zeroes. */
export function formatIdentifier(value: string | number | null | undefined): string {
  if (typeof value === 'string') return value.length > 0 ? value : ABSENT_VALUE;
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return formatFixed(value, 0);
}

/** Admin significance score precision, shared across every diagnostic surface. */
export function formatSignificanceScore(value: number | null | undefined): string {
  return formatFixed(value, 3);
}

export function formatTokenAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  return value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  });
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 1_000_000_000) return `${formatFixed(value / 1_000_000_000, 1)}B`;
  if (absoluteValue >= 1_000_000) return `${formatFixed(value / 1_000_000, 1)}M`;
  if (absoluteValue >= 1_000) return `${formatFixed(value / 1_000, 1)}K`;
  return formatNumber(value, 3);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatNumber(value, digits, digits)}%`;
}

function validDate(value: Date | string | null | undefined): Date | null {
  if (!value) return null;
  if (typeof value === 'string') {
    const calendarMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (calendarMatch) {
      const year = Number(calendarMatch[1]);
      const monthIndex = Number(calendarMatch[2]) - 1;
      const day = Number(calendarMatch[3]);
      const calendarDate = new Date(year, monthIndex, day);
      return calendarDate.getFullYear() === year
        && calendarDate.getMonth() === monthIndex
        && calendarDate.getDate() === day
        ? calendarDate
        : null;
    }
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}

export function formatMonth(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', { month: 'short' }).format(date);
}

export function formatMonthYear(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' }).format(date);
}

/** The short weekday ("Wed"): the ride log's rows say which day, not which date. */
export function formatWeekday(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(date);
}

export function formatTime(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

/** The month and day ("Sep 3"): the ledger rail's date under its day word. */
export function formatMonthDay(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date);
}

const ORDINAL_RULES = new Intl.PluralRules('en-US', { type: 'ordinal' });
const ORDINAL_SUFFIX: Record<string, string> = { one: 'st', two: 'nd', few: 'rd', other: 'th' };

/** A rank as an ordinal ("4th"): the one value a leaderboard push carries. */
export function formatOrdinal(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return ABSENT_VALUE;
  const whole = Math.round(value);
  return formatInteger(whole) + (ORDINAL_SUFFIX[ORDINAL_RULES.select(whole)] ?? 'th');
}

export function formatDateTime(value: Date | string | null | undefined): string {
  const date = validDate(value);
  if (!date) return ABSENT_VALUE;
  const dateLabel = formatDate(date);
  const timeLabel = formatTime(date);
  return `${dateLabel} at ${timeLabel}`;
}

export function formatKilometers(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatNumber(value, 1, 1)} km`;
}

export function formatMeters(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatNumber(value, digits, digits)} m`;
}

export function formatWatts(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} W`;
}

export function formatVam(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} m/h`;
}

export function formatHeartRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} bpm`;
}

export function formatCadence(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} rpm`;
}

export function formatCalories(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatNumber(value, 0, 0)} kcal`;
}

export function formatDays(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} days`;
}

export function formatTemperature(value: number | null | undefined, unit: '°C' | '°F'): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)} ${unit}`;
}

export function formatWattsPerKilogram(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatFixed(value, 2)} W/kg`;
}

export function formatCoordinate(value: number | null | undefined, digits = 4): string {
  return formatFixed(value, digits);
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return ABSENT_VALUE;
  if (bytes >= 1024 * 1024) {
    return `${formatNumber(bytes / (1024 * 1024), 1)} MB`;
  }
  return `${formatNumber(bytes / 1024, 1)} KB`;
}

export function formatSecondsLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ABSENT_VALUE;
  return `${formatInteger(value)}s`;
}
