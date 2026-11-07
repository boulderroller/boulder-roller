import { useEffect, useRef, useMemo, useState, type CSSProperties } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { GpsPoint } from '../../lib/api';
import { cn } from '../ui/utils';
import { ROUTE, BASE_MAP_STYLES, BaseMapStyle, DEFAULT_BASE_MAP } from '../../lib/mapColors';

// Fix Leaflet default marker icon issue
delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

function isLeafletTeardownRace(error: unknown): boolean {
  return error instanceof Error && error.message.includes('_leaflet_pos');
}

function removeLayerSafely(map: L.Map, layer: L.Layer | null) {
  if (!layer) return;

  try {
    if (map.hasLayer(layer)) {
      map.removeLayer(layer);
    }
  } catch (error) {
    if (!isLeafletTeardownRace(error)) {
      throw error;
    }
  }
}

function getRouteFitPadding(container: HTMLElement | null): L.PointExpression {
  return container && container.clientWidth < 640 ? [32, 32] : [52, 52];
}

interface RouteMapProps {
  gpsPoints: GpsPoint[];
  height?: number | string;
  className?: string;
  onHoverIndex?: (index: number | null) => void;
  hoverIndex?: number | null;
  selectedIndex?: number | null;
  onClickIndex?: (index: number) => void;
  climbs?: Array<{
    startIndex: number;
    endIndex: number;
    name?: string;
    id?: string;
  }>;
  selectedClimb?: {
    startIndex: number;
    endIndex: number;
    name?: string;
    id?: string;
  };
  hoveredClimb?: {
    startIndex: number;
    endIndex: number;
    name?: string;
    id?: string;
  };
  onMapReady?: (map: L.Map | null) => void;
  showTrack?: boolean;
  scopedRange?: { start: number; end: number } | null;
  baseMapStyle?: BaseMapStyle;
}

interface IndexedRouteCoordinate {
  index: number;
  coordinate: [number, number];
}

function visibleRouteRuns(
  gpsPoints: GpsPoint[],
  startIndex = 0,
  endIndex = gpsPoints.length - 1,
): IndexedRouteCoordinate[][] {
  const runs: IndexedRouteCoordinate[][] = [];
  let current: IndexedRouteCoordinate[] = [];
  const start = Math.max(0, startIndex);
  const end = Math.min(gpsPoints.length - 1, endIndex);

  for (let index = start; index <= end; index += 1) {
    const point = gpsPoints[index];
    const visible = point.redacted !== true
      && Number.isFinite(point.latitude)
      && Number.isFinite(point.longitude);
    if (!visible) {
      if (current.length > 0) runs.push(current);
      current = [];
      continue;
    }
    current.push({
      index,
      coordinate: [point.latitude, point.longitude],
    });
  }
  if (current.length > 0) runs.push(current);
  return runs;
}

export default function RouteMap({
  gpsPoints,
  height = 300,
  className = '',
  onHoverIndex,
  hoverIndex,
  selectedIndex,
  onClickIndex,
  climbs = [],
  selectedClimb,
  hoveredClimb,
  onMapReady,
  showTrack = true,
  scopedRange,
  baseMapStyle = DEFAULT_BASE_MAP,
}: RouteMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const routeCasingRef = useRef<L.Polyline | null>(null);
  const polylineRef = useRef<L.Polyline | null>(null);
  const routeMarkersRef = useRef<L.LayerGroup | null>(null);
  const hoverMarkerRef = useRef<L.CircleMarker | null>(null);
  const selectedMarkerRef = useRef<L.CircleMarker | null>(null);
  const climbHighlightRef = useRef<L.Polyline | null>(null);
  const hoverClimbHighlightRef = useRef<L.Polyline | null>(null);
  const scopedRangeRef = useRef<L.Polyline | null>(null);
  const allClimbsRef = useRef<L.LayerGroup | null>(null);

  // Map ready state
  const [isMapReady, setIsMapReady] = useState(false);

  // Preserve redacted gaps as separate polylines. Flattening them would draw a
  // false line through a hidden home, workplace, or route endpoint.
  const routeRuns = useMemo(() => visibleRouteRuns(gpsPoints), [gpsPoints]);
  const indexedCoordinates = useMemo(() => routeRuns.flat(), [routeRuns]);
  const coordinates = useMemo(() => (
    indexedCoordinates.map((point) => point.coordinate)
  ), [indexedCoordinates]);
  const coordinateBySourceIndex = useMemo(() => {
    return new Map(indexedCoordinates.map((point) => [point.index, point.coordinate]));
  }, [indexedCoordinates]);
  const routeSegments = useMemo(() => {
    return routeRuns
      .filter((run) => run.length >= 2)
      .map((run) => run.map((point) => point.coordinate));
  }, [routeRuns]);

  // Calculate bounds
  const bounds = useMemo(() => {
    if (coordinates.length === 0) return null;
    return L.latLngBounds(coordinates);
  }, [coordinates]);

  const shellStyle = useMemo(() => ({
    '--route-map-height': typeof height === 'number' ? `${height}px` : height,
  }) as CSSProperties, [height]);

  // Initialize map
  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;
    let disposed = false;

    const map = L.map(mapRef.current, {
      zoomControl: true,
      attributionControl: true,
    });

    // CRITICAL: Set initial view - Leaflet won't load tiles without this
    // Default to US center, will be overridden by fitBounds when GPS loads
    map.setView([39.8283, -98.5795], 4);

    // Tile layer - configurable base map style
    const tileConfig = BASE_MAP_STYLES[baseMapStyle];

    L.tileLayer(tileConfig.url, {
      attribution: tileConfig.attribution,
      ...(tileConfig.subdomains && { subdomains: tileConfig.subdomains }),
      ...(tileConfig.tileClassName && { className: tileConfig.tileClassName }),
      maxZoom: tileConfig.maxZoom,
    }).addTo(map);

    mapInstanceRef.current = map;

    // Wait for map to fully initialize before allowing layer operations
    map.whenReady(() => {
      if (disposed) return;
      setIsMapReady(true);
      if (onMapReady) {
        onMapReady(map);
      }
    });

    return () => {
      disposed = true;
      map.stop();
      removeLayerSafely(map, polylineRef.current);
      removeLayerSafely(map, routeCasingRef.current);
      removeLayerSafely(map, routeMarkersRef.current);
      removeLayerSafely(map, hoverMarkerRef.current);
      removeLayerSafely(map, selectedMarkerRef.current);
      removeLayerSafely(map, climbHighlightRef.current);
      removeLayerSafely(map, hoverClimbHighlightRef.current);
      removeLayerSafely(map, scopedRangeRef.current);
      removeLayerSafely(map, allClimbsRef.current);
      polylineRef.current = null;
      routeCasingRef.current = null;
      routeMarkersRef.current = null;
      hoverMarkerRef.current = null;
      selectedMarkerRef.current = null;
      climbHighlightRef.current = null;
      hoverClimbHighlightRef.current = null;
      scopedRangeRef.current = null;
      allClimbsRef.current = null;
      if (onMapReady) {
        onMapReady(null);
      }
      try {
        map.remove();
      } catch (error) {
        if (!isLeafletTeardownRace(error)) {
          throw error;
        }
      }
      mapInstanceRef.current = null;
      setIsMapReady(false);
    };
  }, [onMapReady]);

  // Update tile layer when baseMapStyle changes
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Remove existing tile layers
    map.eachLayer((layer) => {
      if (layer instanceof L.TileLayer) {
        map.removeLayer(layer);
      }
    });

    // Add new tile layer
    const tileConfig = BASE_MAP_STYLES[baseMapStyle];
    L.tileLayer(tileConfig.url, {
      attribution: tileConfig.attribution,
      ...(tileConfig.subdomains && { subdomains: tileConfig.subdomains }),
      ...(tileConfig.tileClassName && { className: tileConfig.tileClassName }),
      maxZoom: tileConfig.maxZoom,
    }).addTo(map);
  }, [baseMapStyle]);

  // Draw route polyline
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    // Remove existing polyline
    if (polylineRef.current) {
      map.removeLayer(polylineRef.current);
      polylineRef.current = null;
    }
    if (routeCasingRef.current) {
      map.removeLayer(routeCasingRef.current);
      routeCasingRef.current = null;
    }
    if (routeMarkersRef.current) {
      map.removeLayer(routeMarkersRef.current);
      routeMarkersRef.current = null;
    }

    if (coordinates.length === 0) return;

    // Only draw if showTrack is true
    if (!showTrack) {
      // Still fit bounds even without track
      if (bounds) {
        map.fitBounds(bounds, { padding: getRouteFitPadding(mapRef.current) });
      }
      return;
    }

    const routeCasing = L.polyline(routeSegments, {
      color: ROUTE.rideCasing,
      weight: 8,
      opacity: 0.88,
      lineCap: 'round',
      lineJoin: 'round',
      interactive: false,
    }).addTo(map);

    const polyline = L.polyline(routeSegments, {
      color: ROUTE.ridePrimary,
      weight: 4,
      opacity: 0.96,
      lineCap: 'round',
      lineJoin: 'round',
    }).addTo(map);

    routeCasingRef.current = routeCasing;
    polylineRef.current = polyline;

    // Fit bounds with padding
    if (bounds) {
      map.fitBounds(bounds, { padding: getRouteFitPadding(mapRef.current) });
    }

    const routeMarkers = L.layerGroup();

    // Start marker (green - beginning of journey)
    if (coordinates.length > 0) {
      L.circleMarker(coordinates[0], {
        radius: 6.5,
        fillColor: ROUTE.start,
        color: ROUTE.rideCasing,
        weight: 2.5,
        fillOpacity: 1,
        className: 'route-map-endpoint route-map-endpoint--start',
      }).addTo(routeMarkers);
    }

    // End marker (brown - summit reached)
    if (coordinates.length > 1) {
      L.circleMarker(coordinates[coordinates.length - 1], {
        radius: 6.5,
        fillColor: ROUTE.ridePrimary,
        color: ROUTE.rideCasing,
        weight: 2.5,
        fillOpacity: 1,
        className: 'route-map-endpoint route-map-endpoint--finish',
      }).addTo(routeMarkers);
    }
    routeMarkers.addTo(map);
    routeMarkersRef.current = routeMarkers;

    return () => {
      if (polylineRef.current && map) {
        map.removeLayer(polylineRef.current);
        polylineRef.current = null;
      }
      if (routeCasingRef.current && map) {
        map.removeLayer(routeCasingRef.current);
        routeCasingRef.current = null;
      }
      if (routeMarkersRef.current && map) {
        map.removeLayer(routeMarkersRef.current);
        routeMarkersRef.current = null;
      }
    };
  }, [bounds, coordinates, isMapReady, routeSegments, showTrack]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const container = mapRef.current;
    if (!map || !container || !isMapReady) return undefined;

    let frame = 0;
    const resizeMap = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        map.invalidateSize({ pan: false });
        if (bounds && !selectedClimb && !scopedRange) {
          map.fitBounds(bounds, { padding: getRouteFitPadding(container) });
        }
      });
    };
    const observer = new ResizeObserver(resizeMap);
    observer.observe(container);
    resizeMap();

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [bounds, isMapReady, scopedRange, selectedClimb]);

  // Hover marker sync
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    // Remove existing hover marker
    if (hoverMarkerRef.current) {
      map.removeLayer(hoverMarkerRef.current);
      hoverMarkerRef.current = null;
    }

    // Keep climb hover in the terrain palette; generic point hover remains blue.
    const hoverCoordinate = hoverIndex === null ? undefined : coordinateBySourceIndex.get(hoverIndex);
    if (hoverCoordinate) {
      const marker = L.circleMarker(hoverCoordinate, {
        radius: 5,
        fillColor: hoveredClimb ? ROUTE.ridePrimary : ROUTE.rideHover,
        color: ROUTE.rideCasing,
        weight: 2,
        fillOpacity: 1,
        className: hoveredClimb
          ? 'route-map-hover-marker route-map-hover-marker--climb'
          : 'route-map-hover-marker',
      }).addTo(map);
      hoverMarkerRef.current = marker;
    }
  }, [coordinateBySourceIndex, hoverIndex, hoveredClimb, isMapReady]);

  // Selected point sync
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    if (selectedMarkerRef.current) {
      map.removeLayer(selectedMarkerRef.current);
      selectedMarkerRef.current = null;
    }

    const selectedCoordinate = selectedIndex == null
      ? undefined
      : coordinateBySourceIndex.get(selectedIndex);
    if (selectedCoordinate) {
      const marker = L.circleMarker(selectedCoordinate, {
        radius: 7,
        fillColor: ROUTE.rideSelected,
        color: ROUTE.rideCasing,
        weight: 2.5,
        fillOpacity: 1,
        opacity: 1,
      }).addTo(map);
      selectedMarkerRef.current = marker;
    }
  }, [coordinateBySourceIndex, selectedIndex, isMapReady]);

  // Handle polyline hover for sync
  useEffect(() => {
    const polyline = polylineRef.current;
    if (!polyline || (!onHoverIndex && !onClickIndex) || !isMapReady) return;

    const getClosestIndex = (e: L.LeafletMouseEvent) => {
      const latlng = e.latlng;
      let closestIndex = 0;
      let closestDist = Infinity;

      indexedCoordinates.forEach(({ coordinate, index }) => {
        const dist = latlng.distanceTo(L.latLng(coordinate[0], coordinate[1]));
        if (dist < closestDist) {
          closestDist = dist;
          closestIndex = index;
        }
      });

      return closestIndex;
    };

    const handleMouseMove = (e: L.LeafletMouseEvent) => {
      if (!onHoverIndex) return;
      const closestIndex = getClosestIndex(e);
      onHoverIndex(closestIndex);
    };

    const handleMouseOut = () => {
      onHoverIndex(null);
    };

    const handleClick = (e: L.LeafletMouseEvent) => {
      if (!onClickIndex) return;
      onClickIndex(getClosestIndex(e));
    };

    polyline.on('mousemove', handleMouseMove);
    polyline.on('click', handleClick);
    polyline.on('mouseout', handleMouseOut);

    return () => {
      polyline.off('mousemove', handleMouseMove);
      polyline.off('click', handleClick);
      polyline.off('mouseout', handleMouseOut);
    };
  }, [indexedCoordinates, onHoverIndex, onClickIndex, isMapReady]);

  // Highlight selected climb
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    // Remove existing climb highlight
    if (climbHighlightRef.current) {
      map.removeLayer(climbHighlightRef.current);
      climbHighlightRef.current = null;
    }

    // Add new climb highlight if selected
    if (selectedClimb && coordinates.length > 0) {
      const { startIndex, endIndex } = selectedClimb;
      const climbRuns = visibleRouteRuns(gpsPoints, startIndex, endIndex);
      const climbCoords = climbRuns
        .filter((run) => run.length >= 2)
        .map((run) => run.map((point) => point.coordinate));

      if (climbCoords.length > 0) {
        const highlight = L.polyline(climbCoords, {
          color: ROUTE.rideSelected,
          weight: 6,
          opacity: 1,
          lineCap: 'round',
          lineJoin: 'round',
          className: 'route-map-climb-highlight route-map-climb-highlight--selected',
        }).addTo(map);

        climbHighlightRef.current = highlight;

        // Fit bounds to climb with padding
        const climbBounds = L.latLngBounds(climbCoords.flat());
        map.fitBounds(climbBounds, { padding: [50, 50], maxZoom: 15 });
      }
    }
  }, [selectedClimb, coordinates, gpsPoints, isMapReady]);

  // Highlight the transient climb hover shared with the profile and row list
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    if (hoverClimbHighlightRef.current) {
      map.removeLayer(hoverClimbHighlightRef.current);
      hoverClimbHighlightRef.current = null;
    }

    if (hoveredClimb && coordinates.length > 0) {
      const { startIndex, endIndex } = hoveredClimb;
      const climbCoords = visibleRouteRuns(gpsPoints, startIndex, endIndex)
        .filter((run) => run.length >= 2)
        .map((run) => run.map((point) => point.coordinate));

      if (climbCoords.length > 0) {
        const highlight = L.polyline(climbCoords, {
          color: ROUTE.ridePrimary,
          weight: 7,
          opacity: 0.92,
          lineCap: 'round',
          lineJoin: 'round',
          dashArray: '6, 4',
          interactive: false,
          className: 'route-map-climb-highlight route-map-climb-highlight--hovered',
        }).addTo(map);

        hoverClimbHighlightRef.current = highlight;
      }
    }
  }, [hoveredClimb, coordinates, gpsPoints, isMapReady]);

  // Highlight scoped range from elevation chart rubber-band selection
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    // Remove existing scoped range highlight
    if (scopedRangeRef.current) {
      map.removeLayer(scopedRangeRef.current);
      scopedRangeRef.current = null;
    }

    // Add new scoped range highlight if present
    if (scopedRange && coordinates.length > 0) {
      const { start, end } = scopedRange;
      const rangeCoords = visibleRouteRuns(gpsPoints, start, end)
        .filter((run) => run.length >= 2)
        .map((run) => run.map((point) => point.coordinate));

      if (rangeCoords.length > 0) {
        const highlight = L.polyline(rangeCoords, {
          color: ROUTE.highlight, // Teal for scoped range
          weight: 5,
          opacity: 1,
          lineCap: 'round',
          lineJoin: 'round',
          dashArray: '8, 8', // Dashed to distinguish from climb highlight
        }).addTo(map);

        scopedRangeRef.current = highlight;
      }
    }
  }, [scopedRange, coordinates, gpsPoints, isMapReady]);

  // Show all climbs overlay
  // Note: Parent controls visibility by passing empty climbs array when disabled
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !isMapReady) return;

    // Remove existing all-climbs layer
    if (allClimbsRef.current) {
      map.removeLayer(allClimbsRef.current);
      allClimbsRef.current = null;
    }

    // Add all climbs if any are provided
    if (climbs.length > 0 && coordinates.length > 0) {
      const layerGroup = L.layerGroup();

      climbs.forEach((climb) => {
        const climbCoords = visibleRouteRuns(gpsPoints, climb.startIndex, climb.endIndex)
          .filter((run) => run.length >= 2)
          .map((run) => run.map((point) => point.coordinate));

        if (climbCoords.length > 0) {
          L.polyline(climbCoords, {
            color: ROUTE.rideSelected,
            weight: 5,
            opacity: 0.38,
            lineCap: 'round',
            lineJoin: 'round',
          }).addTo(layerGroup);
        }
      });

      layerGroup.addTo(map);
      allClimbsRef.current = layerGroup;
    }
  }, [climbs, coordinates, gpsPoints, isMapReady]);

  return (
    <div
      className={cn(
        'route-map-shell',
        coordinates.length > 0 && 'route-map-shell--ready',
        selectedClimb && 'route-map-shell--selected-climb',
        hoveredClimb && 'route-map-shell--hovered-climb',
      )}
      style={shellStyle}
    >
      <div
        ref={mapRef}
        className={cn('route-map-shell__leaflet', className)}
      />

      {/* Empty state overlay - shown while GPS data is loading or absent */}
      {coordinates.length === 0 && (
        <div className="route-map-shell__empty">
          <span className="route-map-shell__empty-text">Route GPS unavailable</span>
        </div>
      )}
    </div>
  );
}
