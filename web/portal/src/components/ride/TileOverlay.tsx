/**
 * TileOverlay - H3 Hexagon Visualization for Rides
 *
 * Renders H3 tiles on a Leaflet map with various color modes.
 * Uses Cartographic Heritage palette - warm earth tones for elevation.
 */

import { useEffect, useRef, useMemo } from 'react';
import L from 'leaflet';
import { cellToBoundary } from 'h3-js';
import { useTheme } from '../../contexts/ThemeContext';
import { useFormatters } from '../../hooks/useFormatters';
import { TileSample } from '../../lib/api';
import { formatInteger, formatWatts } from '../../lib/formatters';
import {
  getElevationColor,
  getGradientColor,
  getTimeColor,
  getPowerColor,
  ELEVATION,
  ROUTE,
  UI,
} from '../../lib/mapColors';

export type TileColorMode = 'time' | 'gradient' | 'power' | 'elevation';

interface TileOverlayProps {
  map: L.Map | null;
  tileSamples: TileSample[];
  colorMode?: TileColorMode;
  opacity?: number;
  visible?: boolean;
  onTileClick?: (tileId: string, samples: TileSample[]) => void;
  highlightedTiles?: string[];
}

// Color scales using Cartographic Heritage palette
const COLOR_SCALES = {
  time: {
    // Journey progress: deep teal → light teal
    getColor: (progress: number) => getTimeColor(progress),
  },
  gradient: {
    // Climb gradient: green → tan → brown → mauve
    getColor: (gradient: number) => getGradientColor(gradient),
  },
  power: {
    // Power output: uses elevation palette (green → brown)
    getColor: (powerPct: number) => getPowerColor(powerPct),
  },
  elevation: {
    // Altitude: full Havanna palette (green lowlands → mauve peaks)
    getColor: (elevPct: number) => getElevationColor(elevPct),
  },
};

const TOOLTIP_HTML_ESCAPE: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeTooltipHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => TOOLTIP_HTML_ESCAPE[char]);
}

export default function TileOverlay({
  map,
  tileSamples,
  colorMode = 'time',
  opacity = 0.28,
  visible = true,
  onTileClick,
  highlightedTiles = [],
}: TileOverlayProps) {
  const { isDarkMode } = useTheme();
  const { elevation: formatElevation } = useFormatters();
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const highlightLayerRef = useRef<L.LayerGroup | null>(null);

  // Aggregate tiles - group samples by tile_id
  const aggregatedTiles = useMemo(() => {
    if (!tileSamples.length) return [];

    const tileMap = new Map<string, {
      samples: TileSample[];
      minT: number;
      maxT: number;
      avgElevation: number;
      avgPower: number;
      maxGradient: number;
    }>();

    // Group samples by tile
    tileSamples.forEach((sample) => {
      const existing = tileMap.get(sample.tileId);
      if (existing) {
        existing.samples.push(sample);
        existing.minT = Math.min(existing.minT, sample.t);
        existing.maxT = Math.max(existing.maxT, sample.t);
      } else {
        tileMap.set(sample.tileId, {
          samples: [sample],
          minT: sample.t,
          maxT: sample.t,
          avgElevation: 0,
          avgPower: 0,
          maxGradient: 0,
        });
      }
    });

    // Calculate aggregates
    const totalTime = Math.max(...tileSamples.map(s => s.t)) - Math.min(...tileSamples.map(s => s.t));
    const minTime = Math.min(...tileSamples.map(s => s.t));

    // Get elevation range for normalization
    const elevations = tileSamples.filter(s => s.elevationM != null).map(s => s.elevationM!);
    const minElev = elevations.length ? Math.min(...elevations) : 0;
    const maxElev = elevations.length ? Math.max(...elevations) : 100;
    const elevRange = maxElev - minElev || 1;

    // Get power range
    const powers = tileSamples.filter(s => s.powerW != null).map(s => s.powerW!);
    const maxPower = powers.length ? Math.max(...powers) : 400;

    return Array.from(tileMap.entries()).map(([tileId, data]) => {
      // Calculate averages
      const elevSamples = data.samples.filter(s => s.elevationM != null);
      data.avgElevation = elevSamples.length
        ? elevSamples.reduce((sum, s) => sum + (s.elevationM || 0), 0) / elevSamples.length
        : 0;

      const powerSamples = data.samples.filter(s => s.powerW != null);
      data.avgPower = powerSamples.length
        ? powerSamples.reduce((sum, s) => sum + (s.powerW || 0), 0) / powerSamples.length
        : 0;

      // Calculate gradient from elevation change
      if (elevSamples.length >= 2) {
        const sortedByT = [...elevSamples].sort((a, b) => a.t - b.t);
        const elevChange = (sortedByT[sortedByT.length - 1].elevationM || 0) - (sortedByT[0].elevationM || 0);
        // Rough gradient estimate (needs distance which we don't have per tile)
        data.maxGradient = Math.max(0, elevChange / 10); // Simplified
      }

      // Calculate time progress (0-1)
      const timeProgress = totalTime > 0 ? (data.minT - minTime) / totalTime : 0.5;

      // Calculate normalized values for coloring
      const elevPct = elevRange > 0 ? (data.avgElevation - minElev) / elevRange : 0.5;
      const powerPct = maxPower > 0 ? data.avgPower / maxPower : 0;

      return {
        tileId,
        samples: data.samples,
        timeProgress,
        avgElevation: data.avgElevation,
        avgPower: data.avgPower,
        maxGradient: data.maxGradient,
        elevPct,
        powerPct,
      };
    });
  }, [tileSamples]);

  // Get H3 boundary for a tile
  const getTileBoundary = (tileId: string): [number, number][] => {
    try {
      const boundary = cellToBoundary(tileId);
      // h3-js returns [lat, lng] pairs, Leaflet expects the same
      return boundary.map(([lat, lng]) => [lat, lng] as [number, number]);
    } catch {
      return [];
    }
  };

  // Get color for a tile based on mode
  const getTileColor = (tile: typeof aggregatedTiles[0]): string => {
    switch (colorMode) {
      case 'time':
        return COLOR_SCALES.time.getColor(tile.timeProgress);
      case 'gradient':
        return COLOR_SCALES.gradient.getColor(tile.maxGradient);
      case 'power':
        return COLOR_SCALES.power.getColor(tile.powerPct);
      case 'elevation':
        return COLOR_SCALES.elevation.getColor(tile.elevPct);
      default:
        return '#22d3ee'; // Default cyan
    }
  };

  // Render tiles
  useEffect(() => {
    if (!map) return;

    // Clear existing layer
    if (layerGroupRef.current) {
      map.removeLayer(layerGroupRef.current);
    }

    if (!visible || !aggregatedTiles.length) {
      layerGroupRef.current = null;
      return;
    }

    // Ensure map panes are initialized (prevents appendChild errors)
    if (!map.getPane('overlayPane')) {
      return;
    }

    const layerGroup = L.layerGroup();

    aggregatedTiles.forEach((tile) => {
      const boundary = getTileBoundary(tile.tileId);
      if (!boundary.length) return;

      const color = getTileColor(tile);
      const isHighlighted = highlightedTiles.includes(tile.tileId);

      const polygon = L.polygon(boundary, {
        color: isHighlighted ? ROUTE.climbHighlight : (isDarkMode ? UI.dark.border : UI.light.border),
        weight: isHighlighted ? 1.5 : 0.75,
        opacity: isHighlighted ? 0.7 : 0.34,
        fillColor: color,
        fillOpacity: isHighlighted ? 0.36 : opacity,
      });

      // Click handler
      if (onTileClick) {
        polygon.on('click', () => onTileClick(tile.tileId, tile.samples));
      }

      // Tooltip
      const tooltipRows = [
        `<div class="tile-overlay-tooltip__row">Samples: ${formatInteger(tile.samples.length)}</div>`,
        tile.avgElevation ? `<div class="tile-overlay-tooltip__row">Elev: ${formatElevation(tile.avgElevation)}</div>` : '',
        tile.avgPower ? `<div class="tile-overlay-tooltip__row">Power: ${formatWatts(tile.avgPower)}</div>` : '',
      ].filter(Boolean).join('');

      polygon.bindTooltip(
        `<div class="tile-overlay-tooltip">
          <div class="tile-overlay-tooltip__title">${escapeTooltipHtml(tile.tileId.substring(0, 12))}...</div>
          ${tooltipRows}
        </div>`,
        { direction: 'top', offset: [0, -5], className: 'tile-overlay-tooltip-shell' }
      );

      polygon.addTo(layerGroup);
    });

    layerGroup.addTo(map);
    layerGroupRef.current = layerGroup;

    return () => {
      if (layerGroupRef.current && map) {
        map.removeLayer(layerGroupRef.current);
      }
    };
  }, [formatElevation, map, aggregatedTiles, colorMode, opacity, visible, isDarkMode, highlightedTiles, onTileClick]);

  // Render highlighted tiles separately (for climb sequences)
  useEffect(() => {
    if (!map) return;

    // Clear existing highlight layer
    if (highlightLayerRef.current) {
      map.removeLayer(highlightLayerRef.current);
    }

    if (!highlightedTiles.length) {
      highlightLayerRef.current = null;
      return;
    }

    const highlightLayer = L.layerGroup();

    highlightedTiles.forEach((tileId, index) => {
      const boundary = getTileBoundary(tileId);
      if (!boundary.length) return;

      // Gradient color based on position in sequence (using elevation palette)
      const progress = highlightedTiles.length > 1 ? index / (highlightedTiles.length - 1) : 0.5;
      const color = getElevationColor(0.3 + progress * 0.5); // Tan to brown range

      const polygon = L.polygon(boundary, {
        color: ROUTE.climbHighlight,
        weight: 1.25,
        opacity: 0.72,
        fillColor: color,
        fillOpacity: 0.32,
      });

      polygon.addTo(highlightLayer);
    });

    highlightLayer.addTo(map);
    highlightLayerRef.current = highlightLayer;

    return () => {
      if (highlightLayerRef.current && map) {
        map.removeLayer(highlightLayerRef.current);
      }
    };
  }, [map, highlightedTiles]);

  return null; // This component only manages map layers
}

// Helper component for tile color legend - Cartographic Heritage palette
export function TileColorLegend({ mode }: { mode: TileColorMode }) {
  const legends: Record<TileColorMode, { label: string; swatches: number; labels?: string[] }> = {
    time: {
      label: 'Journey',
      swatches: 4,
      labels: ['Start', '', '', 'End'],
    },
    gradient: {
      label: 'Elevation change',
      swatches: 5,
      labels: ['Low', '', 'Mid', '', 'High'],
    },
    power: {
      label: 'Power',
      swatches: 5,
      labels: ['Low', '', 'Mid', '', 'Max'],
    },
    elevation: {
      label: 'Elevation',
      swatches: 7,
      labels: ['Low', '', '', '', '', '', 'Peak'],
    },
  };

  const legend = legends[mode];

  return (
    <div className="tile-color-legend">
      <div className="tile-color-legend__header">
        <span className="tile-color-legend__title">{legend.label}</span>
      </div>
      <div className="tile-color-legend__swatches">
        {Array.from({ length: legend.swatches }).map((_, i) => (
          <div
            key={i}
            className={`tile-color-legend__swatch tile-color-legend__swatch--${mode}-${i}`}
          />
        ))}
      </div>
      {legend.labels && (
        <div className="tile-color-legend__labels">
          <span>{legend.labels[0]}</span>
          <span>{legend.labels[legend.labels.length - 1]}</span>
        </div>
      )}
    </div>
  );
}
