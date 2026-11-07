import { useQueryClient } from '@tanstack/react-query';
import { SlotRows } from '../loading/Slot';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bike, ChevronRight, Clock, FileCheck, MapPinned, Mountain, Search, X } from 'lucide-react';
import { api, ApiError, SearchResult, SearchResultType, SearchSuggestionSection, SearchType } from '../../lib/api';
import { getRiderInitials, getSearchRiderPresentation } from '../../lib/riderIdentity';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalClose,
} from '../ui/responsive-modal';

/*
 * Search — the sheet (Tim-ratified 2026-09-03, board "Guide and Search" on the
 * Night Ledger Rooms canvas).
 *
 * A field, then scope words, then rows. Under All the results group by kind
 * with See All in gray; a scope word narrows to one kind. Each result is the
 * row grammar: avatar or glyph · title / the backend's subtitle · one trailing
 * value, the first stat the backend sends. Before a query: Recent as rows,
 * then the backend's suggestion sections. Search map is the last row once the
 * query is three letters long. Proofs left the rider-facing scope list.
 */

interface SearchModalProps {
  onClose: () => void;
  initialCategory?: SearchCategory;
}

type SearchCategory = SearchType;

const SCOPES: Array<{ key: SearchCategory; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'riders', label: 'Riders' },
  { key: 'climbs', label: 'Climbs' },
  { key: 'rides', label: 'Rides' },
];
const GROUPS: Array<{ type: SearchResultType; title: string; scope: SearchCategory | null }> = [
  { type: 'rider', title: 'Riders', scope: 'riders' },
  { type: 'climb', title: 'Climbs', scope: 'climbs' },
  { type: 'ride', title: 'Rides', scope: 'rides' },
  { type: 'proof', title: 'Proofs', scope: null },
];
const GROUP_PREVIEW = 4;
const MAP_SEARCH_MIN_LENGTH = 3;
const RECENT_SEARCHES_KEY = 'br:search:recent:v1';
const MAX_RECENT_SEARCHES = 6;

function parseRecentSearches(value: string | null): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === 'string').slice(0, MAX_RECENT_SEARCHES);
  } catch {
    return [];
  }
}

function writeRecentSearches(next: string[]) {
  try {
    window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(next));
  } catch {
    // Storage can be denied; the list still lives for the sheet's lifetime.
  }
}

/** The one trailing value: the first stat the backend sends, with its word when the value is bare. */
function trailingValue(result: SearchResult): string | null {
  const stat = result.stats?.[0];
  if (!stat?.value) return null;
  const value = stat.value.trim();
  if (!value) return null;
  return /[a-z%]/i.test(value) ? value : `${value} ${stat.label.toLowerCase()}`;
}

function ResultLead({ result, displayName }: { result: SearchResult; displayName: string }) {
  if (result.type === 'rider') {
    const url = result.image?.kind === 'avatar' ? result.image.url : null;
    return url ? (
      <img className="search-modal-result__avatar" src={url} alt="" />
    ) : (
      <span className="search-modal-result__avatar" aria-hidden="true">{getRiderInitials(displayName)}</span>
    );
  }
  const glyph = result.type === 'climb'
    ? <Mountain size={16} aria-hidden="true" />
    : result.type === 'ride'
      ? <Bike size={16} aria-hidden="true" />
      : <FileCheck size={16} aria-hidden="true" />;
  return <span className="search-modal-result__glyph" aria-hidden="true">{glyph}</span>;
}

export default function SearchModal({ onClose, initialCategory = 'all' }: SearchModalProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<SearchCategory>(initialCategory);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [suggestionSections, setSuggestionSections] = useState<SearchSuggestionSection[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizedQuery = query.trim();

  useEffect(() => {
    setRecentSearches(parseRecentSearches(window.localStorage.getItem(RECENT_SEARCHES_KEY)));

    let cancelled = false;
    setSuggestionsLoading(true);
    queryClient.fetchQuery({ queryKey: ['search-suggestions'], queryFn: () => api.getSearchSuggestions({ limit: 4 }), staleTime: 0, retry: false })
      .then((response) => {
        if (!cancelled) setSuggestionSections(response.sections ?? []);
      })
      .catch(() => {
        if (!cancelled) setSuggestionSections([]);
      })
      .finally(() => {
        if (!cancelled) setSuggestionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const saveRecentSearch = (value: string) => {
    const cleaned = value.trim();
    if (!cleaned) return;
    const next = [cleaned, ...recentSearches.filter((item) => item.toLowerCase() !== cleaned.toLowerCase())]
      .slice(0, MAX_RECENT_SEARCHES);
    setRecentSearches(next);
    writeRecentSearches(next);
  };

  const removeRecentSearch = (value: string) => {
    const next = recentSearches.filter((item) => item !== value);
    setRecentSearches(next);
    writeRecentSearches(next);
  };

  const clearRecentSearches = () => {
    setRecentSearches([]);
    writeRecentSearches([]);
  };

  useEffect(() => {
    let cancelled = false;
    if (!normalizedQuery) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      queryClient.fetchQuery({ queryKey: ['search', normalizedQuery, category], queryFn: () => api.search({ q: normalizedQuery, type: category, limit: 12 }), staleTime: 0, retry: false })
        .then((response) => {
          if (cancelled) return;
          setResults(response.results ?? []);
        })
        .catch((err) => {
          if (cancelled) return;
          setResults([]);
          setError(err instanceof ApiError && err.type === 'network_error'
            ? 'Connection issue'
            : 'Search unavailable');
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [normalizedQuery, category]);

  const handleResult = (result: SearchResult) => {
    if (normalizedQuery) saveRecentSearch(normalizedQuery);

    const riderPresentation = getSearchRiderPresentation(result);
    if (riderPresentation) {
      navigate(riderPresentation.path);
      onClose();
      return;
    }

    const scanUrl = result.scanTargets?.[0]?.url;
    if ((result.target.type === 'scan_tx' || result.target.type === 'scan_account' || result.target.type === 'proof') && scanUrl) {
      window.open(scanUrl, '_blank', 'noopener,noreferrer');
      onClose();
      return;
    }
    navigate(result.webPath);
    onClose();
  };

  const handlePlaceSearch = () => {
    if (!normalizedQuery) return;
    saveRecentSearch(normalizedQuery);
    navigate(`/climbs?search=${encodeURIComponent(normalizedQuery)}`);
    onClose();
  };

  const grouped = useMemo(() => (
    GROUPS
      .map((group) => ({ ...group, results: results.filter((result) => result.type === group.type) }))
      .filter((group) => group.results.length > 0)
  ), [results]);

  const renderResult = (result: SearchResult) => {
    const riderPresentation = getSearchRiderPresentation(result);
    const title = riderPresentation?.displayName ?? result.title;
    const value = trailingValue(result);

    return (
      <button
        key={result.id}
        type="button"
        onClick={() => handleResult(result)}
        className="search-modal-result"
        data-rider-path={riderPresentation?.path}
        data-kind={result.type}
      >
        <ResultLead result={result} displayName={title} />
        <span className="search-modal-result__identity">
          <span className="search-modal-result__title">{title}</span>
          <span className="search-modal-result__sub">{riderPresentation?.subtitle ?? result.subtitle}</span>
        </span>
        {value ? <span className="search-modal-result__value">{value}</span> : <span aria-hidden="true" />}
      </button>
    );
  };

  const renderGroup = (title: string, rows: SearchResult[], onSeeAll: (() => void) | null, key: string) => (
    <div key={key} className="search-sheet__group">
      <div className="search-sheet__group-head">
        <span>{title}</span>
        {onSeeAll ? (
          <button type="button" className="search-sheet__word" onClick={onSeeAll}>See All</button>
        ) : null}
      </div>
      {rows.map(renderResult)}
    </div>
  );

  const showBrowse = !normalizedQuery && (recentSearches.length > 0 || suggestionSections.length > 0 || suggestionsLoading);
  const stateWord = !normalizedQuery
    ? 'Start typing to search'
    : loading
      ? 'Searching'
      : error || 'No results found';

  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader className="portal-sheet__bar search-sheet__bar">
        <ResponsiveModalTitle className="search-sheet__bar-title">Search</ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">
          Search Boulder Roller rides, climbs, and riders.
        </ResponsiveModalDescription>
        <ResponsiveModalClose className="search-sheet__done">Done</ResponsiveModalClose>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="portal-sheet search-sheet">
        <label className="search-sheet__field">
          <Search size={18} aria-hidden="true" />
          <span className="sr-only">Search</span>
          <input
            type="text"
            placeholder="Search rides, climbs, riders"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
            className="search-modal-input"
          />
          {query ? (
            <button type="button" className="search-sheet__clear" aria-label="Clear search" onClick={() => setQuery('')}>
              <X size={14} aria-hidden="true" />
            </button>
          ) : null}
        </label>

        <div className="search-sheet__words">
          {SCOPES.map((scope) => (
            <button
              key={scope.key}
              type="button"
              onClick={() => setCategory(scope.key)}
              aria-pressed={category === scope.key}
              className={`search-modal-category${category === scope.key ? ' search-modal-category--active' : ''}`}
            >
              {scope.label}
            </button>
          ))}
        </div>

        <div className="search-sheet__list">
          {showBrowse ? (
            <>
              {recentSearches.length > 0 ? (
                <div className="search-sheet__group">
                  <div className="search-sheet__group-head">
                    <span>Recent</span>
                    <button type="button" className="search-sheet__word" onClick={clearRecentSearches}>Clear</button>
                  </div>
                  {recentSearches.map((item) => (
                    <div key={item} className="search-sheet__recent">
                      <button type="button" className="search-sheet__recent-query" onClick={() => setQuery(item)}>
                        <Clock size={16} aria-hidden="true" />
                        <span>{item}</span>
                      </button>
                      <button
                        type="button"
                        className="search-sheet__recent-remove"
                        aria-label={`Remove ${item}`}
                        onClick={() => removeRecentSearch(item)}
                      >
                        <X size={14} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              {suggestionsLoading ? <div aria-busy="true"><SlotRows count={5} /><span className="sr-only" role="status">Loading suggestions</span></div> : null}
              {suggestionSections.map((section) => renderGroup(section.title, section.results, null, section.id))}
            </>
          ) : loading || error || results.length === 0 ? (
            <div className="search-sheet__state" role="status">{loading ? <><SlotRows count={5} /><span className="sr-only">{stateWord}</span></> : stateWord}</div>
          ) : category === 'all' ? (
            grouped.map((group) => renderGroup(
              group.title,
              group.results.slice(0, GROUP_PREVIEW),
              group.scope && group.results.length > GROUP_PREVIEW ? () => setCategory(group.scope as SearchCategory) : null,
              group.type,
            ))
          ) : (
            <div className="search-sheet__group search-sheet__group--flat">{results.map(renderResult)}</div>
          )}
        </div>

        {normalizedQuery.length >= MAP_SEARCH_MIN_LENGTH ? (
          <button type="button" className="search-sheet__map search-modal-map-button" onClick={handlePlaceSearch}>
            <MapPinned size={16} aria-hidden="true" />
            <span className="search-sheet__map-word">Search map</span>
            <span className="search-sheet__map-query">{normalizedQuery}</span>
            <ChevronRight size={14} aria-hidden="true" className="search-sheet__map-chevron" />
          </button>
        ) : null}
      </ResponsiveModalBody>
    </ResponsiveModal>
  );
}
