import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  StateRow,
  PortalFrame,
  PortalList,
  PortalListItem,
  PortalMetric,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalStack,
  PortalTruthPill,
} from '../components/portal/PortalSpine';
import { InlinePendingState } from '../components/loading/LoadingSystem';
import { useAuth } from '../contexts/AuthContext';
import { useFollowSuggestedRider, useSuggestedRiders } from '../hooks/queries';
import { api, ApiError, SearchResult, SuggestedRider } from '../lib/api';
import { getPublicRiderDisplayName, getPublicRiderPath, getRiderHandle, getSearchRiderPresentation } from '../lib/riderIdentity';
import { ArrowUpRight, Search, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { ABSENT_VALUE, formatInteger, roundToDigits } from '../lib/formatters';

type SuggestedRiderRecord = SuggestedRider & {
  display_name?: string | null;
  mutualFollowers?: number;
  mutual_followers?: number;
  isFollowing?: boolean;
  is_following?: boolean;
};

interface RiderDiscoveryCard {
  id: string;
  title: string;
  subtitle: string;
  path: string;
  initials: string;
  isFollowing?: boolean;
  canFollow?: boolean;
}

const minimumSearchLength = 2;

function formatMutuals(rider: SuggestedRiderRecord): string {
  const value = rider.mutualFollowers ?? rider.mutual_followers ?? 0;
  const count = Number.isFinite(value) ? Math.max(0, roundToDigits(value, 0)) : 0;
  return count > 0 ? `${formatInteger(count)} mutual${count === 1 ? '' : 's'}` : 'New rider';
}

function initials(value: string): string {
  const cleaned = value.replace(/^@+/, '').trim();
  if (!cleaned) return 'R';
  return cleaned.slice(0, 2).toUpperCase();
}

function suggestedRiderCard(rider: SuggestedRiderRecord): RiderDiscoveryCard {
  const handle = getRiderHandle(rider, `rider_${rider.id.slice(0, 6)}`);
  const displayName = getPublicRiderDisplayName(rider);

  return {
    id: rider.id,
    title: displayName,
    subtitle: `@${handle} · ${formatMutuals(rider)}`,
    path: getPublicRiderPath(rider),
    initials: initials(displayName),
    isFollowing: Boolean(rider.isFollowing ?? rider.is_following),
    canFollow: true,
  };
}

function searchResultCard(result: SearchResult): RiderDiscoveryCard {
  const riderPresentation = getSearchRiderPresentation(result);
  const title = riderPresentation?.displayName ?? result.title;
  const subtitle = [riderPresentation?.subtitle ?? result.subtitle, ...result.stats.slice(0, 2).map((stat) => `${stat.label}: ${stat.value}`)]
    .filter(Boolean)
    .join(' · ');

  return {
    id: result.id,
    title,
    subtitle: subtitle || 'Rider profile',
    path: riderPresentation?.path ?? result.webPath,
    initials: initials(title),
  };
}

export default function FindFriends() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const suggestedRidersQuery = useSuggestedRiders(8, true);
  const followSuggestedRider = useFollowSuggestedRider(user?.id ?? null);
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const normalizedQuery = query.trim();
  const suggestedCards = useMemo(
    () => ((suggestedRidersQuery.data ?? []) as SuggestedRiderRecord[]).map(suggestedRiderCard),
    [suggestedRidersQuery.data],
  );
  const resultCards = useMemo(
    () => searchResults.filter((result) => result.type === 'rider').map(searchResultCard),
    [searchResults],
  );
  const pendingFollowRiderId = followSuggestedRider.variables?.riderId;

  useEffect(() => {
    let cancelled = false;
    if (normalizedQuery.length < minimumSearchLength) {
      setSearchResults([]);
      setSearchLoading(false);
      setSearchError(null);
      return;
    }

    setSearchLoading(true);
    setSearchError(null);
    const timer = window.setTimeout(() => {
      api.search({ q: normalizedQuery, type: 'riders', limit: 12 })
        .then((response) => {
          if (!cancelled) setSearchResults(response.results ?? []);
        })
        .catch((err) => {
          if (cancelled) return;
          setSearchResults([]);
          setSearchError(err instanceof ApiError && err.type === 'network_error'
            ? 'Connection issue'
            : 'Rider search paused');
        })
        .finally(() => {
          if (!cancelled) setSearchLoading(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [normalizedQuery]);

  const handleFollow = async (riderId: string, title: string) => {
    try {
      await followSuggestedRider.mutateAsync({ riderId });
      toast.success(`Now following ${title}`);
    } catch {
      toast.error('Could not follow rider');
    }
  };

  const renderRiderCard = (card: RiderDiscoveryCard) => {
    const isFollowPending = followSuggestedRider.isPending && pendingFollowRiderId === card.id;

    return (
      <PortalListItem
        key={card.id}
        className="find-friends-rider"
      >
        <button
          type="button"
          className="find-friends-rider__main"
          onClick={() => navigate(card.path)}
        >
          <span className="find-friends-rider__avatar" aria-hidden="true">
            {card.initials}
          </span>
          <span className="find-friends-rider__copy">
            <span className="find-friends-rider__name">{card.title}</span>
            <span className="find-friends-rider__meta">{card.subtitle}</span>
          </span>
          {card.canFollow ? null : (
            <ArrowUpRight size={14} className="find-friends-rider__arrow" aria-hidden="true" />
          )}
        </button>
        {card.canFollow ? (
          <button
            type="button"
            className="find-friends-rider__follow"
            data-state={card.isFollowing || isFollowPending ? 'disabled' : 'idle'}
            onClick={(event) => {
              event.stopPropagation();
              if (!card.isFollowing && !isFollowPending) {
                void handleFollow(card.id, card.title);
              }
            }}
            disabled={card.isFollowing || isFollowPending}
          >
            {card.isFollowing ? 'Following' : isFollowPending ? 'Following...' : 'Follow'}
          </button>
        ) : null}
      </PortalListItem>
    );
  };

  return (
    <PortalPage className="find-friends-page">
      <PortalFrame>
        <PortalStack className="portal-stack--loose">
          <PortalPanel>
            <PortalPanelBody className="portal-page-hero find-friends-hero">
              <div className="portal-page-hero__copy">
                <h1 className="portal-page-hero__title">Find riders</h1>
              </div>

              <div className="portal-metric-row" aria-label="Rider search status">
                <PortalMetric
                  value={searchError ? 'Issue' : normalizedQuery.length >= minimumSearchLength ? 'Live' : 'Ready'}
                  label="Search"
                  align="right"
                  valueFamily="sans"
                />
                <PortalMetric
                  value={suggestedRidersQuery.isLoading ? ABSENT_VALUE : formatInteger(suggestedCards.length)}
                  label="Follow picks"
                  align="right"
                />
                <PortalMetric value="Live" label="Follows" align="right" accent valueFamily="sans" />
              </div>
            </PortalPanelBody>
          </PortalPanel>

          <PortalPanel>
            <PortalPanelHeader
              title="Find riders"
              meta={(
                <span className="portal-panel__meta-cluster">
                  <span>{normalizedQuery.length >= minimumSearchLength ? `${formatInteger(resultCards.length)} found` : `${formatInteger(minimumSearchLength)}+ letters`}</span>
                  <PortalTruthPill tone="verified">Live search</PortalTruthPill>
                </span>
              )}
            />
            <PortalPanelBody className="find-friends-search">
              <label className="portal-search-field find-friends-search__field">
                <Search size={15} aria-hidden="true" />
                <span className="sr-only">Search riders</span>
                <input
                  type="search"
                  placeholder="Search rider name or handle"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              {searchLoading ? <InlinePendingState label="Searching riders" /> : null}
              {searchError ? (
                <div className="find-friends-search__notice" role="status">
                  {searchError}
                </div>
              ) : null}
            </PortalPanelBody>
            {normalizedQuery.length >= minimumSearchLength && !searchLoading && !searchError ? (
              resultCards.length > 0 ? (
                <PortalList className="find-friends-list">
                  {resultCards.map(renderRiderCard)}
                </PortalList>
              ) : (
                <StateRow
                  icon={<Search size={30} aria-hidden="true" />}
                  title="No riders found"
                  description="Try a name, handle, or a shorter search."
                />
              )
            ) : null}
          </PortalPanel>

          <PortalPanel>
            <PortalPanelHeader
              title="Follow picks"
              meta={suggestedRidersQuery.isFetching ? 'Refreshing' : `${formatInteger(suggestedCards.length)} ready`}
            />
            {suggestedRidersQuery.isLoading ? (
              <PortalPanelBody>
                <InlinePendingState label="Loading rider suggestions" />
              </PortalPanelBody>
            ) : suggestedCards.length > 0 ? (
              <PortalList className="find-friends-list">
                {suggestedCards.map(renderRiderCard)}
              </PortalList>
            ) : (
              <StateRow
                icon={<UserPlus size={34} aria-hidden="true" />}
                title="No picks yet"
                description="Follow picks will appear as the network around your rides fills in."
              />
            )}
          </PortalPanel>
        </PortalStack>
      </PortalFrame>
    </PortalPage>
  );
}
