/**
 * GradientClimbOverlay - Renders climb polylines with gradient coloring
 *
 * Uses leaflet-hotline for efficient gradient polyline rendering.
 * Cartographic Heritage palette: green (easy) → tan → brown → mauve (steep)
 */

import { useEffect, useRef, useMemo, useState } from 'react';
import L from 'leaflet';
import { GpsPoint, ClimbPattern } from '../../lib/api';
import { useFormatters } from '../../hooks/useFormatters';
import { useTheme } from '../../contexts/ThemeContext';
import { GRADIENT_PALETTE as MAP_GRADIENT_PALETTE, GRADIENT } from '../../lib/mapColors';
import { findGpsIndexForOffset } from '../../lib/rideTelemetry';
import { formatInteger, formatPercent } from '../../lib/formatters';

// Dynamic import of leaflet-hotline to handle bundling issues
let hotlineLoaded = false;
if (typeof window !== 'undefined') {
  import('leaflet-hotline').then(() => {
    hotlineLoaded = true;
  }).catch(() => {
    // leaflet-hotline failed to load - gradient overlay disabled
  });
}

// Extend Leaflet types for hotline
declare module 'leaflet' {
  function hotline(
    latlngs: [number, number, number][],
    options?: HotlineOptions
  ): L.Polyline;

  interface HotlineOptions extends L.PolylineOptions {
    min?: number;
    max?: number;
    palette?: Record<number, string>;
    weight?: number;
    outlineWidth?: number;
    outlineColor?: string;
  }
}

// Use Cartographic Heritage palette for gradients
const GRADIENT_PALETTE = MAP_GRADIENT_PALETTE;

// Gradient thresholds
const GRADIENT_MIN = 0;   // 0%
const GRADIENT_MAX = 15;  // 15% (anything above is clamped)

interface GradientClimbOverlayProps {
  map: L.Map | null;
  gpsPoints: GpsPoint[];
  climbPatterns: ClimbPattern[];
  visible?: boolean;
  selectedClimbIndex?: number | null;
  onClimbClick?: (index: number) => void;
}

/**
 * Compute gradient at each GPS point
 * Uses a sliding window for smoother values
 */
function computePointGradients(points: GpsPoint[]): number[] {
  const gradients: number[] = [];
  const windowSize = 3; // Average over 3 points for smoothing

  for (let i = 0; i < points.length; i++) {
    let totalGradient = 0;
    let count = 0;

    for (let j = Math.max(0, i - windowSize); j <= Math.min(points.length - 2, i + windowSize); j++) {
      const p1 = points[j];
      const p2 = points[j + 1];

      if (p1.elevationM != null && p2.elevationM != null && p1.distanceM != null && p2.distanceM != null) {
        const elevChange = p2.elevationM - p1.elevationM;
        const distChange = p2.distanceM - p1.distanceM;

        if (distChange > 0) {
          const gradient = (elevChange / distChange) * 100;
          // Only count positive gradients (climbs)
          totalGradient += Math.max(0, gradient);
          count++;
        }
      }
    }

    gradients.push(count > 0 ? totalGradient / count : 0);
  }

  return gradients;
}

export default function GradientClimbOverlay({
  map,
  gpsPoints,
  climbPatterns,
  visible = true,
  selectedClimbIndex,
  onClimbClick,
}: GradientClimbOverlayProps) {
  const { isDarkMode } = useTheme();
  const { elevation: formatElevation } = useFormatters();
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const selectedLayerRef = useRef<L.Polyline | null>(null);

  // Compute gradients for all GPS points
  const pointGradients = useMemo(() => {
    return computePointGradients(gpsPoints);
  }, [gpsPoints]);

  // Build climb polylines with gradient data
  const climbPolylines = useMemo(() => {
    if (gpsPoints.length === 0 || climbPatterns.length === 0) return [];

    return climbPatterns.map((climb, idx) => {
      // Use startOffsetS/endOffsetS (actual backend field names after camelCase conversion)
      const startIdx = findGpsIndexForOffset(gpsPoints, climb.startOffsetS ?? climb.startTimeOffsetS) ?? 0;
      const endIdx = findGpsIndexForOffset(gpsPoints, climb.endOffsetS ?? climb.endTimeOffsetS) ?? gpsPoints.length - 1;

      // Keep privacy-redacted points as hard boundaries. A single flattened
      // hotline would draw a false shortcut across a hidden endpoint or zone.
      const hotlineSegments: [number, number, number][][] = [];
      let currentSegment: [number, number, number][] = [];

      for (let i = startIdx; i <= endIdx && i < gpsPoints.length; i++) {
        const p = gpsPoints[i];
        const visible = p.redacted !== true
          && Number.isFinite(p.latitude)
          && Number.isFinite(p.longitude);
        if (!visible) {
          if (currentSegment.length >= 2) hotlineSegments.push(currentSegment);
          currentSegment = [];
          continue;
        }
        currentSegment.push([p.latitude, p.longitude, pointGradients[i] || 0]);
      }
      if (currentSegment.length >= 2) hotlineSegments.push(currentSegment);

      return {
        index: idx,
        segments: hotlineSegments,
        name: climb.name || climb.roadName || `Climb ${formatInteger(idx + 1)}`,
        vertM: climb.vertM,
        avgGradient: climb.avgGradientPct || 0,
      };
    });
  }, [gpsPoints, climbPatterns, pointGradients]);

  // Render climb overlays
  useEffect(() => {
    if (!map || !visible) {
      // Clean up when hidden
      if (layerGroupRef.current) {
        map?.removeLayer(layerGroupRef.current);
        layerGroupRef.current = null;
      }
      return;
    }

    // Remove existing layer group
    if (layerGroupRef.current) {
      map.removeLayer(layerGroupRef.current);
    }

    const layerGroup = L.layerGroup();

    // Check if hotline is available (may not load in all environments)
    if (typeof L.hotline !== 'function') {
      return;
    }

    // Ensure map panes are initialized (prevents appendChild errors)
    if (!map.getPane('overlayPane')) {
      return;
    }

    climbPolylines.forEach((polyline, idx) => {
      const isSelected = selectedClimbIndex === idx;
      polyline.segments.forEach((segment) => {
        const hotline = L.hotline(segment, {
          min: GRADIENT_MIN,
          max: GRADIENT_MAX,
          palette: GRADIENT_PALETTE,
          weight: isSelected ? 8 : 5,
          outlineWidth: isSelected ? 2 : 1,
          outlineColor: isSelected
            ? GRADIENT.hard // Brown outline for selected
            : isDarkMode ? 'rgba(42, 40, 36, 0.6)' : 'rgba(74, 69, 64, 0.4)',
        });

        if (onClimbClick) {
          hotline.on('click', () => onClimbClick(idx));
        }

        hotline.bindTooltip(
          `<div class="gradient-climb-tooltip">
            <div class="gradient-climb-tooltip__name">${polyline.name}</div>
            <div>${formatElevation(polyline.vertM)} • ${formatPercent(polyline.avgGradient)}</div>
          </div>`,
          { sticky: true, className: 'climb-tooltip' }
        );

        hotline.addTo(layerGroup);
        if (isSelected) selectedLayerRef.current = hotline;
      });
    });

    layerGroup.addTo(map);
    layerGroupRef.current = layerGroup;

    return () => {
      if (layerGroupRef.current && map) {
        map.removeLayer(layerGroupRef.current);
      }
    };
  }, [formatElevation, map, climbPolylines, visible, selectedClimbIndex, isDarkMode, onClimbClick]);

  // No visual output - this component manages Leaflet layers
  return null;
}

/**
 * Gradient legend component - Cartographic Heritage palette
 */
export function GradientLegend() {
  // Using the Havanna-inspired earth tones
  const legendItems = [
    { tone: 'easy', label: `${formatInteger(0)}-${formatPercent(3, 0)}`, description: 'Easy' },
    { tone: 'moderate', label: `${formatInteger(3)}-${formatPercent(6, 0)}`, description: 'Moderate' },
    { tone: 'challenging', label: `${formatInteger(6)}-${formatPercent(9, 0)}`, description: 'Challenging' },
    { tone: 'hard', label: `${formatInteger(9)}-${formatPercent(12, 0)}`, description: 'Hard' },
    { tone: 'extreme', label: `${formatPercent(12, 0)}+`, description: 'Extreme' },
  ];

  return (
    <div className="gradient-climb-legend">
      <div className="gradient-climb-legend__title">
        Gradient
      </div>
      <div className="gradient-climb-legend__swatches">
        {legendItems.map((item) => (
          <div
            key={item.label}
            className={`gradient-climb-legend__swatch gradient-climb-legend__swatch--${item.tone}`}
            title={`${item.label} - ${item.description}`}
          />
        ))}
      </div>
      <div className="gradient-climb-legend__labels">
        <span>Easy</span>
        <span>Extreme</span>
      </div>
    </div>
  );
}
