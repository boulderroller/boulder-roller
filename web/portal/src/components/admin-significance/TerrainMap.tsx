import { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { cellToBoundary, cellToLatLng } from 'h3-js';
import type { TerrainCell, SignificanceClimb } from '../../lib/api';
import { formatFixed, formatInteger, formatMeters, formatPercent, formatSignificanceScore } from '../../lib/formatters';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIER_COLORS = ['#8a9070', '#d4c993', '#c89b5c', '#8ba87a'];
const TERRAIN_COLORS = {
  flat: '#8ba87a',
  rolling: '#c89b5c',
  mountain: '#d4af37',
} as const;

const POSITRON_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
const POSITRON_ATTR = '&copy; OpenStreetMap &copy; CARTO';

function terrainStrokeColor(xi: number): string {
  if (xi > 0.1) return TERRAIN_COLORS.mountain;
  if (xi > -0.05) return TERRAIN_COLORS.rolling;
  return TERRAIN_COLORS.flat;
}

function gScoreColor(g: number): string {
  if (g >= 0.7) return TERRAIN_COLORS.mountain;
  if (g >= 0.4) return TERRAIN_COLORS.rolling;
  if (g >= 0.15) return TERRAIN_COLORS.flat;
  return '#8a9070';
}

function gScoreRadius(g: number): number {
  // 4px minimum, 12px maximum, scaled by g score
  return 4 + Math.round(g * 8);
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TerrainMapProps {
  cells: TerrainCell[];
  climbs: SignificanceClimb[];
  selectedClimb: SignificanceClimb | null;
  selectedCell: string | null;
  onSelectClimb: (c: SignificanceClimb) => void;
  onSelectCell: (h3Index: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TerrainMap({
  cells,
  climbs,
  selectedClimb,
  selectedCell,
  onSelectClimb,
  onSelectCell,
}: TerrainMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const cellLayerRef = useRef<L.LayerGroup | null>(null);
  const climbLayerRef = useRef<L.LayerGroup | null>(null);
  const selectedCellLayerRef = useRef<L.Polygon | null>(null);
  const selectedClimbLayerRef = useRef<L.CircleMarker | null>(null);
  const [isReady, setIsReady] = useState(false);

  // --- Initialize map ---
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      zoomControl: true,
      attributionControl: true,
    });

    map.setView([39.8, -98.5], 4);

    L.tileLayer(POSITRON_URL, {
      attribution: POSITRON_ATTR,
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(map);

    mapRef.current = map;
    map.whenReady(() => setIsReady(true));

    return () => {
      map.remove();
      mapRef.current = null;
      setIsReady(false);
    };
  }, []);

  // --- Get H3 cell boundary for Leaflet ---
  const getCellBoundary = useCallback((h3Index: string): [number, number][] => {
    try {
      return cellToBoundary(h3Index).map(([lat, lng]) => [lat, lng] as [number, number]);
    } catch {
      return [];
    }
  }, []);

  // --- Get H3 cell center ---
  const getCellCenter = useCallback((h3Index: string): [number, number] | null => {
    try {
      const [lat, lng] = cellToLatLng(h3Index);
      return [lat, lng];
    } catch {
      return null;
    }
  }, []);

  // --- Draw cell polygons ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isReady) return;

    if (cellLayerRef.current) {
      map.removeLayer(cellLayerRef.current);
    }

    const layerGroup = L.layerGroup();

    cells.forEach((cell) => {
      const boundary = getCellBoundary(cell.h3Index);
      if (!boundary.length) return;

      const fillColor = TIER_COLORS[cell.confidenceTier] ?? TIER_COLORS[0];
      const strokeColor = terrainStrokeColor(cell.gpdXi);
      const isSelected = cell.h3Index === selectedCell;

      const polygon = L.polygon(boundary, {
        color: strokeColor,
        weight: isSelected ? 3 : 1,
        fillColor,
        fillOpacity: isSelected ? 0.5 : 0.25,
        dashArray: cell.tailDiagPass ? undefined : '4 4',
      });

      polygon.bindTooltip(
        `<div class="admin-v2-terrain-tooltip">
          <div class="admin-v2-terrain-tooltip__title">${cell.h3Index.substring(0, 12)}...</div>
          <div>n=${formatInteger(cell.nFeatures)} k=${formatInteger(cell.kExceedances)}</div>
          <div>xi=${formatFixed(cell.gpdXi, 3)} sigma=${formatFixed(cell.gpdSigma, 1)}</div>
          <div>diag: ${cell.tailDiagPass ? 'PASS' : 'FAIL'}</div>
        </div>`,
        { direction: 'top', offset: [0, -5], className: 'admin-v2-terrain-tooltip-shell' },
      );

      polygon.on('click', () => onSelectCell(cell.h3Index));
      polygon.addTo(layerGroup);
    });

    layerGroup.addTo(map);
    cellLayerRef.current = layerGroup;

    return () => {
      if (cellLayerRef.current && map) {
        map.removeLayer(cellLayerRef.current);
      }
    };
  }, [cells, selectedCell, isReady, getCellBoundary, onSelectCell]);

  // --- Draw climb markers ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isReady) return;

    if (climbLayerRef.current) {
      map.removeLayer(climbLayerRef.current);
    }

    const layerGroup = L.layerGroup();

    climbs.forEach((climb) => {
      if (!climb.significanceCellH3) return;

      const center = getCellCenter(climb.significanceCellH3);
      if (!center) return;

      // Slight jitter so overlapping climbs in same cell don't stack exactly
      const jitter = (s: string) => {
        let hash = 0;
        for (let i = 0; i < s.length; i++) hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
        return (hash % 100) / 100000;
      };
      const lat = center[0] + jitter(climb.id);
      const lng = center[1] + jitter(climb.id + 'x');

      const isSelected = selectedClimb?.id === climb.id;
      const radius = gScoreRadius(climb.significanceG);
      const color = gScoreColor(climb.significanceG);

      const marker = L.circleMarker([lat, lng], {
        radius: isSelected ? radius + 3 : radius,
        fillColor: color,
        color: isSelected ? '#fff' : color,
        weight: isSelected ? 3 : 1,
        fillOpacity: isSelected ? 1.0 : 0.7,
      });

      marker.bindTooltip(
        `<div class="admin-v2-terrain-tooltip">
          <div class="admin-v2-terrain-tooltip__title">${climb.roadName || 'Unnamed climb'}</div>
          <div>G=${formatSignificanceScore(climb.significanceG)} ${formatPercent(climb.significancePercentile)}</div>
          <div>${formatMeters(climb.vertM)} vert</div>
        </div>`,
        { direction: 'top', offset: [0, -radius - 2], className: 'admin-v2-terrain-tooltip-shell' },
      );

      marker.on('click', () => onSelectClimb(climb));
      marker.addTo(layerGroup);
    });

    layerGroup.addTo(map);
    climbLayerRef.current = layerGroup;

    return () => {
      if (climbLayerRef.current && map) {
        map.removeLayer(climbLayerRef.current);
      }
    };
  }, [climbs, selectedClimb, isReady, getCellCenter, onSelectClimb]);

  // --- Auto-fit bounds on initial data ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isReady) return;

    const allPoints: [number, number][] = [];

    cells.forEach((cell) => {
      const center = getCellCenter(cell.h3Index);
      if (center) allPoints.push(center);
    });

    climbs.forEach((climb) => {
      if (climb.significanceCellH3) {
        const center = getCellCenter(climb.significanceCellH3);
        if (center) allPoints.push(center);
      }
    });

    if (allPoints.length > 0) {
      const bounds = L.latLngBounds(allPoints);
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    }
  }, [cells.length, climbs.length, isReady, getCellCenter]);

  // --- Highlight selected cell ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isReady) return;

    if (selectedCellLayerRef.current) {
      map.removeLayer(selectedCellLayerRef.current);
      selectedCellLayerRef.current = null;
    }

    if (!selectedCell) return;

    const boundary = getCellBoundary(selectedCell);
    if (!boundary.length) return;

    const highlight = L.polygon(boundary, {
      color: '#fff',
      weight: 3,
      fillColor: 'transparent',
      fillOpacity: 0,
      dashArray: undefined,
    });

    highlight.addTo(map);
    selectedCellLayerRef.current = highlight;

    return () => {
      if (selectedCellLayerRef.current && map) {
        map.removeLayer(selectedCellLayerRef.current);
      }
    };
  }, [selectedCell, isReady, getCellBoundary]);

  // --- Highlight selected climb ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isReady) return;

    if (selectedClimbLayerRef.current) {
      map.removeLayer(selectedClimbLayerRef.current);
      selectedClimbLayerRef.current = null;
    }

    if (!selectedClimb?.significanceCellH3) return;

    const center = getCellCenter(selectedClimb.significanceCellH3);
    if (!center) return;

    const pulseMarker = L.circleMarker(center, {
      radius: gScoreRadius(selectedClimb.significanceG) + 6,
      fillColor: 'transparent',
      color: '#fff',
      weight: 2,
      fillOpacity: 0,
      opacity: 0.6,
      className: 'terrain-map-pulse',
    });

    pulseMarker.addTo(map);
    selectedClimbLayerRef.current = pulseMarker;

    return () => {
      if (selectedClimbLayerRef.current && map) {
        map.removeLayer(selectedClimbLayerRef.current);
      }
    };
  }, [selectedClimb, isReady, getCellCenter]);

  return (
    <div className="admin-v2-terrain-map">
      <div ref={mapContainerRef} className="admin-v2-terrain-map__canvas" />
      <div className="admin-v2-terrain-map__legend" aria-label="Terrain map legend">
        <strong>Legend</strong>
        <p>Polygons = H3 terrain cells (res-5, ~250 km&sup2;). Dots = scored climbs. Dot size = G score.</p>
        <section>
          <span>Cell stroke (terrain from GPD &xi;):</span>
          <div className="admin-v2-terrain-map__legend-items">
            <span><em className="admin-v2-terrain-map__line admin-v2-terrain-map__line--flat" />Flat (&xi;&lt;-0.05)</span>
            <span><em className="admin-v2-terrain-map__line admin-v2-terrain-map__line--rolling" />Rolling</span>
            <span><em className="admin-v2-terrain-map__line admin-v2-terrain-map__line--mountain" />Mountain (&xi;&gt;0.1)</span>
          </div>
        </section>
        <section>
          <span>Cell fill (confidence tier):</span>
          <div className="admin-v2-terrain-map__legend-items">
            <span><em className="admin-v2-terrain-map__chip admin-v2-terrain-map__chip--empirical" />Emp (k&lt;12)</span>
            <span><em className="admin-v2-terrain-map__chip admin-v2-terrain-map__chip--low" />Low (12-19)</span>
            <span><em className="admin-v2-terrain-map__chip admin-v2-terrain-map__chip--moderate" />Mod (20-29)</span>
            <span><em className="admin-v2-terrain-map__chip admin-v2-terrain-map__chip--full" />Full (30+)</span>
          </div>
        </section>
        <small>Dashed border = tail diagnostics failed</small>
      </div>
    </div>
  );
}
