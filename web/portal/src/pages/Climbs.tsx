import { StateRow } from '../components/portal/FailureSpecies';
import { Slot, SlotRows } from '../components/loading/Slot';
import { lazy, Suspense, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { ClimbDiscoveryCamera } from '../components/climbs/ClimbDiscoveryMap';
import { ChevronDown, ChevronRight, ChevronUp, MapPin, Search } from 'lucide-react';
import { climbMapPoint } from '../lib/climbGeometry';

import ClimbShapeGlyph from '../components/climbs/ClimbShapeGlyph';
import { InlinePendingState } from '../components/loading/LoadingSystem';
import { PortalPage } from '../components/portal/PortalSpine';
import { useAuth } from '../contexts/AuthContext';
import { useClimbs, useMyVaultStakes } from '../hooks/queries';
import { useFormatters, type Formatters } from '../hooks/useFormatters';
import {
  api,
  type Climb,
  type GeocodingAttribution,
  type GeocodingResult,
  type VaultStake,
} from '../lib/api';
import { formatBaseUnits } from '../lib/tokenAmounts';
import { ABSENT_VALUE } from '../lib/formatters';

const ClimbDiscoveryMap = lazy(() => import('../components/climbs/ClimbDiscoveryMap'));

// Climbs — the city room (Tim-ratified 2026-09-03). The map is the room and
// opens on the whole canon; the column is the index. Every row leads with the
// climb's own canon profile, then name, then the two facts not in the trailing
// slot, then one trailing value that follows the sort word. The row is the tap
// into the climb page; hovering a row lights the climb on the ground and shows
// the bottom card (the iOS map viewer's card: name, canon facts, chevron).
// Clicking a row chooses the climb: the ground moves to it and settles, the
// row stays lit, the card is the way in. A second click on the chosen row
// opens the climb too. On a phone the sheet drops so the hill can be seen.

type Tab = 'all' | 'vaults' | 'staked';
type SortKey = 'elevation' | 'distance' | 'grade' | 'deposited';
type PlaceSearchState = 'idle' | 'loading' | 'available' | 'empty' | 'unavailable';

const MOBILE_DRAWER_MEDIA_QUERY = '(max-width: 767px)';
const SORT_OPTIONS: { id: SortKey; label: string }[] = [
  { id: 'elevation', label: 'Elevation' },
  { id: 'distance', label: 'Distance' },
  { id: 'grade', label: 'Grade' },
  { id: 'deposited', label: 'Deposited' },
];

function initialDrawerExpanded() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
  return !window.matchMedia(MOBILE_DRAWER_MEDIA_QUERY).matches;
}

function vaultSignatureFor(climb: Climb): string | null {
  return climb.vaultEconomy?.vaultSignature ?? climb.vaultSignature ?? null;
}

function hasAttachedVault(climb: Climb): boolean {
  return climb.vaultEconomy?.hasVault ?? climb.hasVault ?? false;
}

function isBrowsableClimb(climb: Climb): boolean {
  return Boolean(
    climb.name?.trim()
    && typeof climb.lengthM === 'number'
    && climb.lengthM > 0
    && typeof climb.elevGainM === 'number'
    && climb.elevGainM > 0
    && typeof climb.avgGradientPct === 'number'
    && climb.avgGradientPct > 0
    && climbMapPoint(climb),
  );
}

function formatCal(baseUnits: string | null | undefined): string {
  if (!baseUnits) return ABSENT_VALUE;
  const formatted = formatBaseUnits(baseUnits, 9, 2);
  return formatted === ABSENT_VALUE ? ABSENT_VALUE : `${formatted} CAL`;
}

function totalStakedBaseUnitsFor(climb: Climb): string | null {
  return climb.vaultEconomy?.totalCalStakedBaseUnits
    ?? climb.vaultEconomy?.totalStakedBaseUnits
    ?? climb.totalCalStakedBaseUnits
    ?? climb.totalStakedBaseUnits
    ?? null;
}

function depositedBaseUnits(climb: Climb): bigint | null {
  if (!hasAttachedVault(climb)) return null;
  const raw = totalStakedBaseUnitsFor(climb);
  if (!raw || !/^\d+$/.test(raw)) return null;
  return BigInt(raw);
}

function readSortKey(value: string | null): SortKey {
  return SORT_OPTIONS.some((option) => option.id === value) ? (value as SortKey) : 'elevation';
}

function sortClimbs(climbs: Climb[], sort: SortKey): Climb[] {
  const byNumber = (pick: (climb: Climb) => number | undefined) => (a: Climb, b: Climb) => (pick(b) ?? 0) - (pick(a) ?? 0);
  if (sort === 'distance') return [...climbs].sort(byNumber((climb) => climb.lengthM));
  if (sort === 'grade') return [...climbs].sort(byNumber((climb) => climb.avgGradientPct));
  if (sort === 'deposited') {
    return [...climbs].sort((a, b) => {
      const left = depositedBaseUnits(a);
      const right = depositedBaseUnits(b);
      if (left === null && right === null) return (b.elevGainM ?? 0) - (a.elevGainM ?? 0);
      if (left === null) return 1;
      if (right === null) return -1;
      return left === right ? 0 : left > right ? -1 : 1;
    });
  }
  return [...climbs].sort(byNumber((climb) => climb.elevGainM));
}

function rowFacts(climb: Climb, sort: SortKey, formatters: Formatters): { trailing: string; sub: string } {
  const distance = formatters.distance(climb.lengthM);
  const elevation = formatters.elevation(climb.elevGainM);
  const grade = formatters.percent(climb.avgGradientPct);
  if (sort === 'distance') return { trailing: distance, sub: [elevation, grade].join(' · ') };
  if (sort === 'grade') return { trailing: grade, sub: [distance, elevation].join(' · ') };
  if (sort === 'deposited') {
    return {
      trailing: hasAttachedVault(climb) ? formatCal(totalStakedBaseUnitsFor(climb)) : ABSENT_VALUE,
      sub: [distance, grade].join(' · '),
    };
  }
  return { trailing: elevation, sub: [distance, grade].join(' · ') };
}

interface ClimbRowProps {
  climb: Climb;
  sort: SortKey;
  selected: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
  rowRef: (node: HTMLAnchorElement | null) => void;
}

function ClimbRow({ climb, sort, selected, hovered, onSelect, onHover, rowRef }: ClimbRowProps) {
  const formatters = useFormatters();
  const name = climb.name || 'Unnamed climb';
  const facts = rowFacts(climb, sort, formatters);

  return (
    <Link
      ref={rowRef}
      className={[
        'climb-discovery-result',
        'climbs-room__row',
        selected ? 'climb-discovery-result--selected' : '',
        hovered ? 'climb-discovery-result--hovered' : '',
      ].filter(Boolean).join(' ')}
      to={`/climbs/${encodeURIComponent(climb.id)}`}
      aria-label={`Open ${name}`}
      aria-current={selected ? 'true' : undefined}
      data-climb-id={climb.id}
      data-selected={selected ? 'true' : 'false'}
      onClick={(event) => {
        if (selected) return;
        event.preventDefault();
        onSelect();
      }}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
    >
      <ClimbShapeGlyph profile={climb.elevationProfile} className="climbs-room__glyph" />
      <span className="climbs-room__identity">
        <strong className="climbs-room__name">{name}</strong>
        <span className="climbs-room__sub">{facts.sub}</span>
      </span>
      <strong className="climbs-room__value">{facts.trailing}</strong>
    </Link>
  );
}

export default function Climbs() {
  const { user } = useAuth();
  const formatters = useFormatters();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlPlaceSearchQuery = searchParams.get('search') || '';
  const urlHasVaultFilter = searchParams.get('hasVault') === 'true';
  const urlPositionsFilter = searchParams.get('positions') === 'true';
  const activeTab: Tab = urlHasVaultFilter ? 'vaults' : urlPositionsFilter ? 'staked' : 'all';
  const activeSort = readSortKey(searchParams.get('sort'));
  const climbSearchId = useId();
  const placeSearchId = useId();
  const mapRef = useRef<ClimbDiscoveryCamera | null>(null);
  const rowRefs = useRef(new Map<string, HTMLAnchorElement>());
  const placeSearchRequestId = useRef(0);

  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [activeBbox, setActiveBbox] = useState<string | null>(null);
  const [settledBbox, setSettledBbox] = useState<string | null>(null);
  const [pendingBbox, setPendingBbox] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [selectedClimbId, setSelectedClimbId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ climbId: string; nonce: number } | null>(null);
  const [hoveredClimbId, setHoveredClimbId] = useState<string | null>(null);
  const [drawerExpanded, setDrawerExpanded] = useState(initialDrawerExpanded);
  const [placeSearchQuery, setPlaceSearchQuery] = useState(urlPlaceSearchQuery);
  const [placeSearchResults, setPlaceSearchResults] = useState<GeocodingResult[]>([]);
  const [placeSearchState, setPlaceSearchState] = useState<PlaceSearchState>('idle');
  const [placeSearchAttribution, setPlaceSearchAttribution] = useState<GeocodingAttribution | null>(null);

  const invalidatePlaceSearchRequest = useCallback(() => {
    placeSearchRequestId.current += 1;
    setPlaceSearchResults([]);
    setPlaceSearchState('idle');
    setPlaceSearchAttribution(null);
  }, []);

  useEffect(() => {
    invalidatePlaceSearchRequest();
    setPlaceSearchQuery(urlPlaceSearchQuery);
  }, [invalidatePlaceSearchRequest, urlPlaceSearchQuery]);

  useEffect(() => {
    const mobileDrawer = window.matchMedia(MOBILE_DRAWER_MEDIA_QUERY);
    const syncDrawerToViewport = (event: MediaQueryListEvent) => setDrawerExpanded(!event.matches);
    mobileDrawer.addEventListener('change', syncDrawerToViewport);
    return () => mobileDrawer.removeEventListener('change', syncDrawerToViewport);
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim());
    }, 250);
    return () => window.clearTimeout(timeoutId);
  }, [searchQuery]);

  // The room opens on the whole canon (no bbox); a moved map and "Search this
  // area" narrow the query to the rider's viewport from then on.
  const {
    data: climbsData,
    isLoading: climbsLoading,
    isFetching: climbsFetching,
    error: climbsError,
    refetch: refetchClimbs,
  } = useClimbs({
    limit: 100,
    q: debouncedSearchQuery || undefined,
    bbox: activeBbox || undefined,
  });
  const {
    data: stakesData,
    isLoading: stakesLoading,
    error: stakesError,
    refetch: refetchStakes,
  } = useMyVaultStakes(Boolean(user));

  const climbs = useMemo(() => (climbsData?.climbs ?? []).filter(isBrowsableClimb), [climbsData]);
  const stakes = useMemo(() => (user ? (stakesData?.stakes ?? []) : []), [stakesData, user]);
  const stakeBySignature = useMemo(
    () => new Map(stakes.map((stake) => [stake.vaultSignature, stake])),
    [stakes],
  );
  // Positions join by canon climb id first (authoritative), signature as
  // fallback for stake rows that predate climbId being on the wire.
  const stakeByClimbId = useMemo(
    () => new Map(
      stakes
        .filter((stake) => stake.climbId)
        .map((stake) => [stake.climbId as string, stake as VaultStake]),
    ),
    [stakes],
  );
  const positionClimbs = useMemo(
    () => climbs.filter((climb) => {
      if (stakeByClimbId.has(climb.id)) return true;
      const signature = vaultSignatureFor(climb);
      return signature ? stakeBySignature.has(signature) : false;
    }),
    [climbs, stakeByClimbId, stakeBySignature],
  );
  const vaultClimbs = useMemo(() => climbs.filter(hasAttachedVault), [climbs]);
  const filteredClimbs = useMemo(() => sortClimbs(
    activeTab === 'staked' ? positionClimbs : activeTab === 'vaults' ? vaultClimbs : climbs,
    activeSort,
  ), [activeSort, activeTab, climbs, positionClimbs, vaultClimbs]);
  const searchPending = searchQuery.trim() !== debouncedSearchQuery;
  const initialLoading = climbsLoading && !climbsData;
  const refreshPending = !initialLoading && (climbsFetching || searchPending);
  const climbsErrorMessage = climbsError instanceof Error ? climbsError.message : null;
  const positionsErrorMessage = stakesError instanceof Error ? stakesError.message : null;
  const positionsUnavailable = Boolean(user) && (stakesLoading || Boolean(positionsErrorMessage));
  const hasPendingArea = Boolean(pendingBbox && pendingBbox !== settledBbox && pendingBbox !== activeBbox);
  const fitKey = JSON.stringify([activeBbox, debouncedSearchQuery, activeTab, filteredClimbs.map(climb => climb.id).sort()]);

  const handleSettledBounds = useCallback((bbox: string) => {
    setSettledBbox(bbox);
    setPendingBbox(bbox);
  }, []);
  const handleViewportChange = useCallback((bbox: string) => setPendingBbox(bbox), []);
  const handleMapReady = useCallback((map: ClimbDiscoveryCamera | null) => {
    mapRef.current = map;
    setMapReady(Boolean(map));
  }, []);

  const handleSelectClimb = useCallback((climbId: string) => {
    setSelectedClimbId(climbId);
  }, []);
  const handleChooseFromIndex = useCallback((climbId: string) => {
    setSelectedClimbId(climbId);
    setFocus((current) => ({ climbId, nonce: (current?.nonce ?? 0) + 1 }));
    if (window.matchMedia(MOBILE_DRAWER_MEDIA_QUERY).matches) setDrawerExpanded(false);
  }, []);
  const handleClearSelection = useCallback(() => setSelectedClimbId(null), []);

  const handleSearchArea = () => {
    if (!pendingBbox) return;
    setActiveBbox(pendingBbox);
    setSelectedClimbId(null);
  };

  const handleTabChange = (tab: Tab) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete('hasVault');
    nextSearchParams.delete('positions');
    if (tab === 'vaults') nextSearchParams.set('hasVault', 'true');
    if (tab === 'staked') nextSearchParams.set('positions', 'true');
    setSearchParams(nextSearchParams, { replace: true });
  };

  const handleSortChange = (sort: SortKey) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    if (sort === 'elevation') nextSearchParams.delete('sort');
    else nextSearchParams.set('sort', sort);
    setSearchParams(nextSearchParams, { replace: true });
  };

  const handlePlaceSearchSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = placeSearchQuery.trim();
    if (query.length < 3 || query.length > 120) return;

    const requestId = placeSearchRequestId.current + 1;
    placeSearchRequestId.current = requestId;
    setPlaceSearchState('loading');
    setPlaceSearchResults([]);
    setPlaceSearchAttribution(null);

    try {
      const response = await api.searchLocations(query);
      if (placeSearchRequestId.current !== requestId) return;
      setPlaceSearchAttribution(response.attribution);
      setPlaceSearchResults(response.results);
      setPlaceSearchState(response.results.length > 0 ? 'available' : 'empty');
    } catch {
      if (placeSearchRequestId.current !== requestId) return;
      setPlaceSearchState('unavailable');
      setPlaceSearchResults([]);
      setPlaceSearchAttribution(null);
    }
  };

  const handlePlaceSearchSelect = (result: GeocodingResult, originalEvent: MouseEvent) => {
    mapRef.current?.setView([result.latitude, result.longitude], 14, { animate: true, originalEvent });
    setPlaceSearchQuery(result.displayName.split(',')[0] || result.displayName);
    setPlaceSearchResults([]);
    setSelectedClimbId(null);
  };

  useEffect(() => {
    if (!selectedClimbId) return;
    rowRefs.current.get(selectedClimbId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selectedClimbId]);

  useEffect(() => {
    if (selectedClimbId && !filteredClimbs.some((climb) => climb.id === selectedClimbId)) {
      setSelectedClimbId(null);
    }
  }, [filteredClimbs, selectedClimbId]);

  const tabOptions: { id: Tab; label: string; available: boolean }[] = [
    { id: 'all', label: 'All climbs', available: true },
    { id: 'vaults', label: 'With vaults', available: true },
    { id: 'staked', label: 'My positions', available: !positionsUnavailable },
  ];
  // The chosen climb holds the card; hover previews only while nothing is chosen.
  const cardClimb = useMemo(() => {
    const id = selectedClimbId ?? hoveredClimbId;
    return id ? filteredClimbs.find((climb) => climb.id === id) ?? null : null;
  }, [filteredClimbs, hoveredClimbId, selectedClimbId]);

  return (
    <PortalPage className="climbs-room-page" aria-busy={initialLoading || climbsFetching}>
      <section className="climbs-room" aria-label="Climb discovery">
        <div className="climbs-room__map">
          <Suspense fallback={null}>
            <ClimbDiscoveryMap
              climbs={filteredClimbs}
              selectedClimbId={selectedClimbId}
              hoveredClimbId={hoveredClimbId}
              fitKey={fitKey}
              focus={focus}
              onSelectClimb={handleSelectClimb}
              onClearSelection={handleClearSelection}
              onHoverClimb={setHoveredClimbId}
              onSettledBounds={handleSettledBounds}
              onViewportChange={handleViewportChange}
              onMapReady={handleMapReady}
            />
          </Suspense>
        </div>

        {!mapReady && (
          <div className="climb-discovery__map-loading">
            <span className="sr-only" role="status">Opening map</span>
          </div>
        )}

        <aside
          className={`climb-discovery__drawer climbs-room__column ${drawerExpanded ? 'climb-discovery__drawer--expanded' : 'climb-discovery__drawer--collapsed'}`}
          data-expanded={drawerExpanded ? 'true' : 'false'}
        >
          <button
            type="button"
            className="climb-discovery__sheet-toggle"
            onClick={() => setDrawerExpanded((current) => !current)}
            aria-label={drawerExpanded ? 'Collapse climb results' : 'Expand climb results'}
            aria-expanded={drawerExpanded}
          >
            <span className="climb-discovery__sheet-handle" aria-hidden="true" />
            {drawerExpanded ? <ChevronDown aria-hidden="true" /> : <ChevronUp aria-hidden="true" />}
          </button>

          <header className="climbs-room__header">
            <h1>Climbs</h1>
            <span className="climbs-room__count">
              <strong>{initialLoading ? <Slot variant="number" /> : formatters.integer(filteredClimbs.length)}</strong> in view
            </span>
          </header>

          <label className="climbs-room__search" htmlFor={climbSearchId}>
            <Search aria-hidden="true" />
            <span className="sr-only">Search climbs</span>
            <input
              id={climbSearchId}
              type="search"
              placeholder="Search climbs"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />

          </label>

          <div className="climbs-room__words" aria-label="Climb view">
            {tabOptions.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className="climbs-room__word"
                aria-pressed={activeTab === tab.id}
                data-available={tab.available ? 'true' : 'false'}
                onClick={() => handleTabChange(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="climbs-room__sorts" aria-label="Sort climbs">
            {SORT_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className="climbs-room__sort"
                aria-pressed={activeSort === option.id}
                onClick={() => handleSortChange(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>

          {climbsErrorMessage && climbsData && (
            <StateRow title="Showing the last loaded climbs." action={<button type="button" onClick={() => void refetchClimbs()}>Try again</button>} />
          )}

          {positionsErrorMessage && activeTab === 'all' && (
            <StateRow title="Positions unavailable." action={<button type="button" onClick={() => void refetchStakes()}>Try again</button>} />
          )}

          <div className="climbs-room__list">
            {initialLoading ? (
              <SlotRows count={100} className="climbs-room__rows" />
            ) : climbsErrorMessage && !climbsData ? (
              <StateRow title="Could not load climbs" action={<button type="button" onClick={() => void refetchClimbs()}>Try again</button>} />
            ) : activeTab === 'staked' && positionsErrorMessage ? (
              <StateRow title="Could not load positions" action={<button type="button" onClick={() => void refetchStakes()}>Try again</button>} />
            ) : filteredClimbs.length === 0 ? (
              <StateRow title={activeTab === 'staked' ? 'No positions in view' : activeTab === 'vaults' ? 'No climbs with vaults in view' : 'No climbs in view'} action={activeTab !== 'all' && <button type="button" onClick={() => handleTabChange('all')}>All climbs</button>} />
            ) : (
              <div className="climbs-room__rows">
                {filteredClimbs.map((climb) => (
                  <ClimbRow
                    key={climb.id}
                    climb={climb}
                    sort={activeSort}
                    selected={selectedClimbId === climb.id}
                    hovered={hoveredClimbId === climb.id}
                    onSelect={() => handleChooseFromIndex(climb.id)}
                    onHover={(hovered) => setHoveredClimbId(hovered ? climb.id : null)}
                    rowRef={(node) => {
                      if (node) rowRefs.current.set(climb.id, node);
                      else rowRefs.current.delete(climb.id);
                    }}
                  />
                ))}
              </div>
            )}
            <div className="climbs-room__list-fade" aria-hidden="true" />
          </div>
        </aside>

        <div className="climbs-room__controls">
        <form className="climb-discovery__place-search climbs-room__places" onSubmit={handlePlaceSearchSubmit}>
          <div className="climbs-room__places-field">
            <button type="submit" className="climb-discovery__place-submit" disabled={placeSearchState === 'loading'}>
              {placeSearchState === 'loading' ? null : <MapPin aria-hidden="true" />}
              <span className="sr-only">Search places</span>
            </button>
            <label htmlFor={placeSearchId} className="sr-only">Search places</label>
            <input
              id={placeSearchId}
              type="search"
              placeholder="Search places"
              required
              minLength={3}
              maxLength={120}
              value={placeSearchQuery}
              onChange={(event) => {
                invalidatePlaceSearchRequest();
                setPlaceSearchQuery(event.target.value);
              }}
            />
          </div>
          <p className="climb-discovery__place-guidance">
            Search public places only. Do not enter personal or confidential information.
          </p>
          {placeSearchResults.length > 0 && (
            <div className="climb-discovery__place-results">
              {placeSearchResults.map((result) => (
                <button
                  key={`${result.latitude}:${result.longitude}:${result.displayName}`}
                  type="button"
                  onClick={(event) => handlePlaceSearchSelect(result, event.nativeEvent)}
                >
                  {result.displayName}
                </button>
              ))}
            </div>
          )}
          {placeSearchState === 'empty' && (
            <p className="climb-discovery__place-state" role="status">No places found.</p>
          )}
          {placeSearchState === 'unavailable' && (
            <p className="climb-discovery__place-state" role="status">
              Place search is unavailable right now. Move the map and Search this area.
            </p>
          )}
          {placeSearchAttribution && (
            <a
              className="climb-discovery__place-attribution"
              href={placeSearchAttribution.url}
              target="_blank"
              rel="noreferrer"
            >
              {placeSearchAttribution.text}
            </a>
          )}
        </form>
        {hasPendingArea && (
          <button type="button" className="climbs-room__search-area" onClick={handleSearchArea}>
            Search this area
          </button>
        )}
        </div>

        {refreshPending && (
          <div className="climb-discovery__map-pending">
            <InlinePendingState label={searchPending ? 'Updating climb search' : 'Refreshing climbs'} />
          </div>
        )}

        <div className="climbs-room__card-layer">
          {cardClimb && (
            <Link
              className="climbs-room__card"
              to={`/climbs/${encodeURIComponent(cardClimb.id)}`}
              data-climb-id={cardClimb.id}
            >
              <span className="climbs-room__card-identity">
                <strong>{cardClimb.name || 'Unnamed climb'}</strong>
                <span>
                  {[
                    formatters.distance(cardClimb.lengthM),
                    formatters.elevation(cardClimb.elevGainM),
                    formatters.percent(cardClimb.avgGradientPct),
                  ].join(' · ')}
                </span>
              </span>
              <ChevronRight aria-hidden="true" />
            </Link>
          )}
          <span className="climbs-room__canon-attribution">Climb data © OpenStreetMap contributors</span>
        </div>
      </section>
    </PortalPage>
  );
}
