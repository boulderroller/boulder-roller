import { Suspense, lazy, useState, useEffect, useRef, useCallback, useId } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { LayerGroup, Map as LeafletMap } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useTheme } from '../contexts/ThemeContext';
import { api, Vault, TerritoryTile, GpsPoint } from '../lib/api';
import { BASE_MAP_STYLES, DEFAULT_BASE_MAP, ROUTE } from '../lib/mapColors';
import { notify } from '../lib/notify';
import { formatInteger } from '../lib/formatters';
import { Layers3, Search } from 'lucide-react';
import {
  PortalMetric,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalTruthPill,
} from '../components/portal/PortalSpine';

const TerritoryLayer = lazy(() => import('../components/map/TerritoryLayer'));
const VaultMarkers = lazy(() => import('../components/map/VaultMarkers'));

interface RecentRoute {
  rideId: string;
  title: string;
  points: [number, number][];
}

interface SearchResult {
  displayName: string;
  lat: number;
  lon: number;
}

type LayerKey = 'territory' | 'routes' | 'vaults';

export default function Map() {
  const { isDarkMode } = useTheme();
  const [searchParams] = useSearchParams();
  const initialSearchQuery = searchParams.get('search') || '';
  const searchInputId = useId();
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const routeLayerRef = useRef<LayerGroup | null>(null);
  const leafletModuleRef = useRef<typeof import('leaflet') | null>(null);

  // Layer visibility
  const [activeLayers, setActiveLayers] = useState<Set<LayerKey>>(
    new Set(['territory', 'vaults'])
  );
  const [mapReady, setMapReady] = useState(false);

  // Data
  const [tiles, setTiles] = useState<TerritoryTile[]>([]);
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [routes, setRoutes] = useState<RecentRoute[]>([]);

  // Loading states
  const [loadingTiles, setLoadingTiles] = useState(false);
  const [loadingVaults, setLoadingVaults] = useState(false);
  const [loadingRoutes, setLoadingRoutes] = useState(false);

  // Search
  const [searchQuery, setSearchQuery] = useState(initialSearchQuery);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Territory stats
  const [stats, setStats] = useState<{ totalTiles: number; tilesThisWeek: number } | null>(null);

  useEffect(() => {
    const nextSearch = searchParams.get('search') || '';
    if (nextSearch) setSearchQuery(nextSearch);
  }, [searchParams]);

  const toggleLayer = useCallback((key: LayerKey) => {
    setActiveLayers(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // Initialize map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    let cancelled = false;
    let mapInstance: LeafletMap | null = null;
    let routeLayer: LayerGroup | null = null;

    const initMap = async () => {
      const L = await import('leaflet');
      if (cancelled || !mapContainerRef.current || mapRef.current) return;

      leafletModuleRef.current = L;

      // Fix Leaflet default marker icon issue
      delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      });

      const style = BASE_MAP_STYLES[DEFAULT_BASE_MAP];
      mapInstance = L.map(mapContainerRef.current, {
        center: [39.95, -75.16], // Philadelphia default
        zoom: 12,
        zoomControl: false,
      });

      L.tileLayer(style.url, {
        attribution: style.attribution,
        maxZoom: style.maxZoom,
        subdomains: style.subdomains || 'abc',
      }).addTo(mapInstance);

      // Add zoom control to bottom-right
      L.control.zoom({ position: 'bottomright' }).addTo(mapInstance);

      routeLayer = L.layerGroup().addTo(mapInstance);
      mapRef.current = mapInstance;
      routeLayerRef.current = routeLayer;
      setMapReady(true);
    };

    void initMap();

    return () => {
      cancelled = true;
      setMapReady(false);
      routeLayer?.clearLayers();
      routeLayer?.remove();
      if (routeLayerRef.current === routeLayer) {
        routeLayerRef.current = null;
      }
      mapInstance?.remove();
      if (mapRef.current === mapInstance) {
        mapRef.current = null;
      }
      leafletModuleRef.current = null;
    };
  }, []);

  // Fetch territory tiles
  useEffect(() => {
    if (!activeLayers.has('territory')) return;
    if (tiles.length > 0) return; // Already loaded

    setLoadingTiles(true);
    api.getTerritoryTiles(15000)
      .then(res => {
        setTiles(res.tiles || []);
      })
      .catch((err) => {
        console.error('Failed to load territory tiles:', err);
        notify.error('Could not load territory tiles');
      })
      .finally(() => setLoadingTiles(false));
  }, [activeLayers, tiles.length]);

  // Fetch territory stats
  useEffect(() => {
    api.getTerritoryStats()
      .then(setStats)
      .catch((err) => {
        console.error('Failed to load territory stats:', err);
      });
  }, []);

  // Fetch vaults with coordinates
  useEffect(() => {
    if (!activeLayers.has('vaults')) return;
    if (vaults.length > 0) return;

    setLoadingVaults(true);
    api.getVaults({ limit: 100 })
      .then(res => {
        setVaults(res.vaults || []);
      })
      .catch((err) => {
        console.error('Failed to load vaults:', err);
        notify.error('Could not load vault markers');
      })
      .finally(() => setLoadingVaults(false));
  }, [activeLayers, vaults.length]);

  // Fetch recent routes (GPS polylines from recent rides)
  useEffect(() => {
    if (!activeLayers.has('routes')) return;
    if (routes.length > 0) return;

    setLoadingRoutes(true);
    api.getRides({ limit: 10 })
      .then(async (rides) => {
        const routeData = await Promise.all(
          rides.slice(0, 5).map(async (ride) => {
            try {
              const gps = await api.getRideGps(ride.id);
              const points = (gps.gpsPoints || [])
                .filter((p: GpsPoint) => p.latitude && p.longitude)
                .map((p: GpsPoint) => [p.latitude, p.longitude] as [number, number]);

              if (points.length < 2) return null;

              return {
                rideId: ride.id,
                title: ride.title || 'Ride',
                points,
              } satisfies RecentRoute;
            } catch {
              return null;
            }
          }),
        );

        setRoutes(routeData.filter((route): route is RecentRoute => route !== null));
      })
      .catch((err) => {
        console.error('Failed to load routes:', err);
        notify.error('Could not load recent routes');
      })
      .finally(() => setLoadingRoutes(false));
  }, [activeLayers, routes.length]);

  // Render route polylines
  useEffect(() => {
    const layerGroup = routeLayerRef.current;
    const map = mapRef.current;
    const L = leafletModuleRef.current;
    if (!layerGroup || !map || !L) return;

    layerGroup.clearLayers();
    if (!activeLayers.has('routes') || !routes.length) return;

    for (const route of routes) {
      if (route.points.length < 2) continue;
      const polyline = L.polyline(route.points, {
        color: isDarkMode ? ROUTE.highlight : ROUTE.primary,
        weight: 3,
        opacity: 0.7,
      });
      polyline.bindTooltip(route.title, { sticky: true });
      layerGroup.addLayer(polyline);
    }
  }, [routes, activeLayers, isDarkMode]);

  // Search with Nominatim
  useEffect(() => {
    if (!searchQuery.trim() || searchQuery.length < 3) {
      setSearchResults([]);
      setSearchOpen(false);
      return;
    }

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const response = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(searchQuery)}&limit=5`,
          { headers: { 'User-Agent': 'BoulderRoller/1.0' } }
        );
        const data = await response.json();
        setSearchResults(
          data.map((r: { display_name: string; lat: string; lon: string }) => ({
            displayName: r.display_name,
            lat: parseFloat(r.lat),
            lon: parseFloat(r.lon),
          }))
        );
        setSearchOpen(true);
      } catch {
        setSearchResults([]);
      }
    }, 400);

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
  }, [searchQuery]);

  const handleSearchSelect = (result: SearchResult) => {
    if (mapRef.current) {
      mapRef.current.setView([result.lat, result.lon], 14);
    }
    setSearchQuery('');
    setSearchOpen(false);
    setSearchResults([]);
  };

  const isLoading = !mapReady || loadingTiles || loadingVaults || loadingRoutes;

  const layerConfig: { key: LayerKey; label: string; loading: boolean; count: number; unit: string }[] = [
    { key: 'territory', label: 'Tiles', loading: loadingTiles, count: tiles.length, unit: 'tiles' },
    { key: 'routes', label: 'Routes', loading: loadingRoutes, count: routes.length, unit: 'routes' },
    { key: 'vaults', label: 'Vaults', loading: loadingVaults, count: vaults.length, unit: 'vaults' },
  ];

  return (
    <PortalPage className="portal-page--map" aria-busy={isLoading} aria-live="polite">
      <div className="portal-map">
        <div ref={mapContainerRef} className="portal-map__canvas" />

        <Suspense fallback={null}>
          <TerritoryLayer
            map={mapRef.current}
            tiles={tiles}
            visible={activeLayers.has('territory')}
            isDarkMode={isDarkMode}
          />
          <VaultMarkers
            map={mapRef.current}
            vaults={vaults}
            visible={activeLayers.has('vaults')}
          />
        </Suspense>

        {!mapReady && (
          <div className="portal-map__loading">
            <div className="portal-map__loading-card">
              <span>Opening map</span>
            </div>
          </div>
        )}

        <PortalPanel className="portal-map__search-panel">
          <div className="portal-map-search">
            <Search className="portal-map-search__icon" aria-hidden="true" />
            <label className="sr-only" htmlFor={searchInputId}>
              Search map locations
            </label>
            <input
              id={searchInputId}
              type="search"
              placeholder="Search locations"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => searchResults.length > 0 && setSearchOpen(true)}
              onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
            />
          </div>

          {searchOpen && searchResults.length > 0 && (
            <div className="portal-map-search-results">
              {searchResults.map((result) => (
                <button
                  key={`${result.lat}:${result.lon}:${result.displayName}`}
                  type="button"
                  className="portal-map-search-results__item"
                  onMouseDown={() => handleSearchSelect(result)}
                >
                  {result.displayName.length > 88
                    ? `${result.displayName.slice(0, 88)}...`
                    : result.displayName}
                </button>
              ))}
            </div>
          )}
        </PortalPanel>

        <PortalPanel className="portal-map__layers-panel">
          <PortalPanelHeader
            title={(
              <span className="portal-map-panel-title">
                <Layers3 aria-hidden="true" />
                Layers
              </span>
            )}
            meta={<PortalTruthPill tone={isLoading ? 'warning' : 'verified'}>{isLoading ? 'Loading' : 'Live'}</PortalTruthPill>}
          />
          <PortalPanelBody className="portal-map-layer-list">
            {layerConfig.map(({ key, label, loading, count, unit }) => {
              const active = activeLayers.has(key);
              const layerMeta = loading
                ? 'Loading'
                : active && count > 0
                  ? `${formatInteger(count)} ${unit}`
                  : active
                    ? 'None yet'
                    : 'Hidden';

              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleLayer(key)}
                  className={`portal-map-layer-toggle ${active ? 'portal-map-layer-toggle--active' : ''}`}
                  aria-pressed={active}
                >
                  <span className="portal-map-layer-toggle__check" aria-hidden="true" />
                  <span className="portal-map-layer-toggle__label">{label}</span>
                  <span className="portal-map-layer-toggle__meta">
                    {loading ? null : null}
                    {layerMeta}
                  </span>
                </button>
              );
            })}
          </PortalPanelBody>
        </PortalPanel>

        {stats && (
          <PortalPanel className="portal-map__stats-panel">
            <PortalPanelHeader title="Explored tiles" meta={<PortalTruthPill tone="verified">Live</PortalTruthPill>} />
            <PortalPanelBody className="portal-map-stats">
              <PortalMetric
                value={formatInteger(stats.totalTiles)}
                label="Tiles"
                accent
              />
              <PortalMetric
                value={`+${formatInteger(stats.tilesThisWeek)}`}
                label="This week"
              />
            </PortalPanelBody>
          </PortalPanel>
        )}

        {activeLayers.has('territory') && tiles.length > 0 && (
          <ZoomHint map={mapRef.current} />
        )}

        {isLoading && (
          <p className="sr-only" role="status" aria-live="polite">
            Loading map layers and ride routes.
          </p>
        )}

      </div>
    </PortalPage>
  );
}

/** Shows a "Zoom in to see tiles" hint when zoomed out */
function ZoomHint({ map }: { map: LeafletMap | null }) {
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    if (!map) return;

    const check = () => setShowHint(map.getZoom() < 12);
    check();
    map.on('zoomend', check);
    return () => { map.off('zoomend', check); };
  }, [map]);

  if (!showHint) return null;

  return (
    <div className="portal-map__zoom-hint">
      Zoom in to see tiles
    </div>
  );
}
