/**
 * Hook that provides unit-aware formatters bound to user preferences
 * Reads units from AuthContext user data
 */

import { useMemo } from 'react';
import { useAuth } from '../contexts/AuthContext';
import {
  ABSENT_VALUE,
  formatDistance,
  formatDistanceValue,
  formatElevation,
  formatElevationValue,
  formatSpeed,
  formatSpeedKmh,
  formatSpeedValue,
  formatWeight,
  formatWeightRange,
  formatDuration,
  formatDurationCompact,
  formatDurationWords,
  formatHoursMinutes,
  formatRaceTime,
  formatRideDuration,
  formatFixed,
  formatNumber,
  formatInteger,
  formatCappedInteger,
  formatIdentifier,
  formatSignificanceScore,
  formatTokenAmount,
  formatCompactNumber,
  formatPercent,
  formatDate,
  formatMonth,
  formatDateTime,
  formatTime,
  formatKilometers,
  formatMeters,
  formatWatts,
  formatWattsPerKilogram,
  formatVam,
  formatHeartRate,
  formatCadence,
  formatCalories,
  formatDays,
  formatTemperature,
  formatCoordinate,
  formatFileSize,
  formatPaddedInteger,
  formatSecondsLabel,
  parseWeight,
  weightForInput,
  getWeightUnit,
  getDistanceUnit,
  getElevationUnit,
  getSpeedUnit,
  Units,
} from '../lib/formatters';

export interface Formatters {
  absentValue: string;
  // Core formatters (return value + unit)
  distance: (meters: number | null | undefined) => string;
  elevation: (meters: number | null | undefined) => string;
  speed: (mps: number | null | undefined) => string;
  speedKmh: (kmh: number | null | undefined) => string;
  weight: (kg: number | null | undefined) => string;
  weightRange: (minimumKg: number | null | undefined, maximumKg: number | null | undefined) => string;
  duration: (seconds: number | null | undefined) => string;
  durationCompact: (seconds: number | null | undefined) => string;
  durationWords: (seconds: number | null | undefined) => string;
  hoursMinutes: (seconds: number | null | undefined) => string;
  raceTime: (seconds: number | null | undefined) => string;
  rideDuration: (seconds: number | null | undefined) => string;
  fixed: (value: number | null | undefined, digits?: number) => string;
  number: (value: number | null | undefined, maximumFractionDigits?: number, minimumFractionDigits?: number) => string;
  integer: (value: number | null | undefined) => string;
  cappedInteger: (value: number | null | undefined, maximum?: number) => string;
  identifier: (value: string | number | null | undefined) => string;
  significanceScore: (value: number | null | undefined) => string;
  tokenAmount: (value: number | null | undefined) => string;
  compactNumber: (value: number | null | undefined) => string;
  percent: (value: number | null | undefined, digits?: number) => string;
  date: (value: Date | string | null | undefined) => string;
  month: (value: Date | string | null | undefined) => string;
  dateTime: (value: Date | string | null | undefined) => string;
  time: (value: Date | string | null | undefined) => string;
  secondsLabel: (value: number | null | undefined) => string;
  paddedInteger: (value: number | null | undefined, width?: number) => string;
  kilometers: (value: number | null | undefined) => string;
  meters: (value: number | null | undefined, digits?: number) => string;
  watts: (value: number | null | undefined) => string;
  wattsPerKilogram: (value: number | null | undefined) => string;
  vam: (value: number | null | undefined) => string;
  heartRate: (value: number | null | undefined) => string;
  cadence: (value: number | null | undefined) => string;
  calories: (value: number | null | undefined) => string;
  days: (value: number | null | undefined) => string;
  temperature: (value: number | null | undefined, unit: '°C' | '°F') => string;
  coordinate: (value: number | null | undefined, digits?: number) => string;
  fileSize: (bytes: number | null | undefined) => string;

  // Value-only formatters (no unit suffix)
  distanceValue: (meters: number | null | undefined) => string;
  elevationValue: (meters: number | null | undefined) => string;
  speedValue: (mps: number | null | undefined) => string;

  // Input helpers
  parseWeight: (value: string) => number | null;
  weightForInput: (kg: number | null | undefined) => string;

  // Current units setting
  units: Units;

  // Unit labels
  weightUnit: string;
  distanceUnit: string;
  elevationUnit: string;
  speedUnit: string;
}

export function useFormatters(): Formatters {
  const { user } = useAuth();

  // Match the persisted profile default when a surface has no rider preference yet.
  const units: Units = user?.preferredUnits || 'metric';

  return useMemo(
    () => ({
      absentValue: ABSENT_VALUE,
      // Core formatters
      distance: (m) => formatDistance(m, units),
      elevation: (m) => formatElevation(m, units),
      speed: (mps) => formatSpeed(mps, units),
      speedKmh: (kmh) => formatSpeedKmh(kmh, units),
      weight: (kg) => formatWeight(kg, units),
      weightRange: (minimumKg, maximumKg) => formatWeightRange(minimumKg, maximumKg, units),
      duration: formatDuration,
      durationCompact: formatDurationCompact,
      durationWords: formatDurationWords,
      hoursMinutes: formatHoursMinutes,
      raceTime: formatRaceTime,
      rideDuration: formatRideDuration,
      fixed: formatFixed,
      number: formatNumber,
      integer: formatInteger,
      cappedInteger: formatCappedInteger,
      identifier: formatIdentifier,
      significanceScore: formatSignificanceScore,
      tokenAmount: formatTokenAmount,
      compactNumber: formatCompactNumber,
      percent: formatPercent,
      date: formatDate,
      month: formatMonth,
      dateTime: formatDateTime,
      time: formatTime,
      secondsLabel: formatSecondsLabel,
      paddedInteger: formatPaddedInteger,
      kilometers: formatKilometers,
      meters: formatMeters,
      watts: formatWatts,
      wattsPerKilogram: formatWattsPerKilogram,
      vam: formatVam,
      heartRate: formatHeartRate,
      cadence: formatCadence,
      calories: formatCalories,
      days: formatDays,
      temperature: formatTemperature,
      coordinate: formatCoordinate,
      fileSize: formatFileSize,

      // Value-only formatters
      distanceValue: (m) => formatDistanceValue(m, units),
      elevationValue: (m) => formatElevationValue(m, units),
      speedValue: (mps) => formatSpeedValue(mps, units),

      // Input helpers
      parseWeight: (val) => parseWeight(val, units),
      weightForInput: (kg) => weightForInput(kg, units),

      // Current units
      units,

      // Unit labels
      weightUnit: getWeightUnit(units),
      distanceUnit: getDistanceUnit(units),
      elevationUnit: getElevationUnit(units),
      speedUnit: getSpeedUnit(units),
    }),
    [units]
  );
}
