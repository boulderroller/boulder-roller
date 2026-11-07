/**
 * TerritoryLayer - H3 Hexagon Territory Visualization
 *
 * Renders user's territory tiles on a Leaflet map.
 * Colors hexagons by visit count (light to dark gradient).
 * Only renders at zoom >= 12 to avoid overwhelming the map.
 */

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { cellToBoundary } from 'h3-js';
import { TerritoryTile } from '../../lib/api';
import { formatInteger } from '../../lib/formatters';
import { ROUTE } from '../../lib/mapColors';

interface TerritoryLayerProps {
  map: L.Map | null;
  tiles: TerritoryTile[];
  visible?: boolean;
  isDarkMode?: boolean;
}

function getVisitColor(visitCount: number, maxVisits: number, isDarkMode: boolean): string {
  // Normalize visit count to 0-1 range (log scale for better distribution)
  const t = maxVisits > 1
    ? Math.log(visitCount) / Math.log(maxVisits)
    : 1;
  const clamped = Math.max(0.15, Math.min(1, t));

  if (isDarkMode) {
    // Dark mode: teal gradient
    const r = Math.round(60 - clamped * 20);
    const g = Math.round(150 + clamped * 50);
    const b = Math.round(170 + clamped * 60);
    return `rgb(${r}, ${g}, ${b})`;
  } else {
    // Light mode: green-teal gradient
    const r = Math.round(70 - clamped * 30);
    const g = Math.round(140 + clamped * 40);
    const b = Math.round(90 + clamped * 80);
    return `rgb(${r}, ${g}, ${b})`;
  }
}

export default function TerritoryLayer({
  map,
  tiles,
  visible = true,
  isDarkMode = false,
}: TerritoryLayerProps) {
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const zoomHandlerRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!map) return;

    // Create layer group
    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
    }

    const layerGroup = layerGroupRef.current;
    layerGroup.clearLayers();

    if (!visible || !tiles.length) {
      layerGroup.remove();
      return;
    }

    const maxVisits = Math.max(...tiles.map(t => t.visitCount || 1));

    function renderTiles() {
      if (!map || !layerGroup) return;
      layerGroup.clearLayers();

      const zoom = map.getZoom();
      // Only render at zoom >= 12
      if (zoom < 12) return;

      const bounds = map.getBounds();

      for (const tile of tiles) {
        try {
          // h3-js cellToBoundary returns [[lat, lng], ...]
          const boundary = cellToBoundary(tile.tileId);
          if (!boundary.length) continue;

          // Check if tile is in view (use first point as proxy)
          const [lat, lng] = boundary[0];
          if (!bounds.contains([lat, lng])) continue;

          const polygon = L.polygon(
            boundary.map(([la, ln]) => [la, ln] as [number, number]),
            {
              fillColor: getVisitColor(tile.visitCount || 1, maxVisits, isDarkMode),
              fillOpacity: 0.45,
              weight: 1,
              color: isDarkMode ? 'rgba(90, 175, 185, 0.3)' : 'rgba(60, 150, 170, 0.3)',
              opacity: 0.5,
            }
          );

          polygon.bindTooltip(
            `Visits: ${formatInteger(tile.visitCount || 1)}`,
            { sticky: true, className: 'territory-tooltip' }
          );

          layerGroup.addLayer(polygon);
        } catch {
          // Invalid H3 index — skip
        }
      }
    }

    renderTiles();
    layerGroup.addTo(map);

    // Re-render on zoom/move
    const handler = () => renderTiles();
    zoomHandlerRef.current = handler;
    map.on('moveend', handler);
    map.on('zoomend', handler);

    return () => {
      map.off('moveend', handler);
      map.off('zoomend', handler);
      layerGroup.clearLayers();
      layerGroup.remove();
    };
  }, [map, tiles, visible, isDarkMode]);

  return null;
}
