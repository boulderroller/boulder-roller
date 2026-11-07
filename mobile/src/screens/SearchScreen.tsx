import React, { type ComponentProps, useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Linking,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useNavigation } from '@react-navigation/native';
import Feather from '@expo/vector-icons/Feather';
import { api, ApiError, LinkTargetType, SearchResult, SearchSuggestionSection, SearchType } from '../lib/api';
import { bestScanTargetFromTargets } from '../lib/linkActions';
import { riderProfileRouteParamsFromIdentifier } from '../lib/riderNavigation';

const CATEGORIES: SearchType[] = ['all', 'rides', 'climbs', 'riders', 'proofs'];
const RECENT_SEARCHES_KEY = 'br:search:recent:v1';
const MAX_RECENT_SEARCHES = 6;

type Nav = {
  goBack: () => void;
  navigate: (screen: string, params?: object) => void;
};

function categoryLabel(category: SearchType): string {
  if (category === 'all') return 'All';
  if (category === 'proofs') return 'BoulderScan';
  return category.charAt(0).toUpperCase() + category.slice(1);
}

type FeatherName = ComponentProps<typeof Feather>['name'];

function resultIcon(type: SearchResult['type']): FeatherName {
  if (type === 'ride') return 'map';
  if (type === 'climb') return 'trending-up';
  if (type === 'rider') return 'user';
  return 'file-text';
}

function resultKind(result: SearchResult): string {
  if (result.type === 'ride') return 'Ride';
  if (result.type === 'climb') return 'Climb';
  if (result.type === 'rider') return 'Rider';
  return 'BoulderScan';
}

function resultTitle(result: SearchResult): string {
  if (result.type !== 'proof') return result.title;
  if (result.target.type === 'scan_account') return 'Account';
  if (result.target.type === 'scan_tx') return 'Transaction';
  return 'BoulderScan';
}

function resultSubtitle(result: SearchResult): string {
  if (result.type !== 'proof') return result.subtitle;
  return 'Open in BoulderScan';
}

function isScanTarget(type: LinkTargetType): boolean {
  return type === 'scan_tx' || type === 'scan_account' || type === 'proof';
}

function statusLabels(result: SearchResult): string[] {
  const labels: string[] = [];
  if (result.privacy?.visibility) labels.push(result.privacy.visibility);
  const status = typeof result.metadata?.status === 'string' ? result.metadata.status : null;
  if (status) labels.push(status.replace(/_/g, ' '));
  if (result.scanState && result.scanState !== 'missing') labels.push(result.scanState.replace(/_/g, ' '));
  return labels.slice(0, 2);
}

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

export default function SearchScreen() {
  const navigation = useNavigation() as Nav;
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<SearchType>('all');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [suggestionSections, setSuggestionSections] = useState<SearchSuggestionSection[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const normalizedQuery = query.trim();

  useEffect(() => {
    let cancelled = false;

    AsyncStorage.getItem(RECENT_SEARCHES_KEY)
      .then((value) => {
        if (!cancelled) setRecentSearches(parseRecentSearches(value));
      })
      .catch(() => {
        if (!cancelled) setRecentSearches([]);
      });

    setSuggestionsLoading(true);
    api.getSearchSuggestions({ limit: 4 })
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

  const saveRecentSearch = useCallback(async (value: string) => {
    const cleaned = value.trim();
    if (!cleaned) return;

    setRecentSearches((previous) => {
      const next = [cleaned, ...previous.filter((item) => item.toLowerCase() !== cleaned.toLowerCase())]
        .slice(0, MAX_RECENT_SEARCHES);
      void AsyncStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(next)).catch(() => undefined);
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!normalizedQuery) {
      setResults([]);
      setError(null);
      setLoading(false);
      setHasMore(false);
      return;
    }

    setLoading(true);
    setError(null);
    const timer = setTimeout(() => {
      api.search({ q: normalizedQuery, type: category, limit: 20 })
        .then((response) => {
          if (cancelled) return;
          setResults(response.results ?? []);
          setHasMore(Boolean(response.hasMore));
        })
        .catch((err) => {
          if (cancelled) return;
          setResults([]);
          setHasMore(false);
          if (err instanceof ApiError) {
            setError(err);
          } else {
            setError(new ApiError('Search unavailable', 'unknown'));
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [normalizedQuery, category]);

  const emptyTitle = useMemo(() => {
    if (!normalizedQuery) return 'Search Boulder Roller';
    if (loading) return 'Searching';
    if (error) return error.retryable ? 'Connection issue' : 'Search unavailable';
    return 'No results found';
  }, [error, loading, normalizedQuery]);

  const emptySubtitle = useMemo(() => {
    if (!normalizedQuery) return 'Find rides, climbs, riders, accounts, and transactions.';
    if (loading) return 'Searching rides, climbs, riders, accounts, and transactions.';
    return 'Try another name, route, rider, account, or transaction.';
  }, [loading, normalizedQuery]);

  const openResult = async (result: SearchResult) => {
    if (normalizedQuery) void saveRecentSearch(normalizedQuery);

    const target = result.target;
    if (target.type === 'ride') {
      navigation.navigate('RideDetail', { serverRideId: target.id, backLabel: 'Search' });
      return;
    }
    if (target.type === 'rider') {
      const riderRef = result.metadata.rider;
      const metadataUserId = typeof result.metadata.userId === 'string' ? result.metadata.userId : null;
      const username = riderRef?.username ?? (target.id !== metadataUserId ? target.id : null);
      const route = riderProfileRouteParamsFromIdentifier(
        target.id,
        riderRef ?? {
          id: metadataUserId,
          username,
          displayName: result.title,
          avatarUrl: result.image?.url ?? null,
        },
        { backLabel: 'Search' },
      );
      if (route) navigation.navigate('RiderDetail', route);
      return;
    }
    if (target.type === 'record_board') {
      navigation.navigate('ClimbLeaderboard', { climbId: target.id, backLabel: 'Search' });
      return;
    }
    if (target.type === 'climb' || target.type === 'local_legend') {
      navigation.navigate('ClimbDetail', { climbId: target.id, backLabel: 'Search' });
      return;
    }
    if (isScanTarget(target.type)) {
      const url = bestScanTargetFromTargets(result.scanTargets)?.url;
      if (url) {
        await Linking.openURL(url);
      }
    }
  };

  const renderResult = ({ item }: { item: SearchResult }) => {
    const labels = statusLabels(item);
    return (
    <TouchableOpacity
      testID={`search-result-${item.id}`}
      style={styles.resultRow}
      activeOpacity={0.82}
      onPress={() => void openResult(item)}
    >
      <View style={styles.resultIcon}>
        <Feather name={resultIcon(item.type)} size={17} color="#b8b8b8" />
      </View>
      <View style={styles.resultBody}>
        <View style={styles.resultTitleRow}>
          <Text style={styles.resultTitle} numberOfLines={1}>{resultTitle(item)}</Text>
          <Text style={styles.resultKind}>{resultKind(item)}</Text>
        </View>
        <Text style={styles.resultSubtitle} numberOfLines={1}>{resultSubtitle(item)}</Text>
        {item.stats?.length ? (
          <View style={styles.statRow}>
            {item.stats.slice(0, 3).map((stat) => (
              <Text key={`${item.id}-${stat.label}`} style={styles.statText} numberOfLines={1}>
                {stat.label}: <Text style={styles.statValue}>{stat.value}</Text>
              </Text>
            ))}
          </View>
        ) : null}
        {labels.length ? (
          <View style={styles.statusRow}>
            {labels.map((label) => (
              <Text key={`${item.id}-${label}`} style={styles.statusPill} numberOfLines={1}>
                {label}
              </Text>
            ))}
          </View>
        ) : null}
      </View>
      <Feather name="chevron-right" size={18} color="#6f6f6f" />
    </TouchableOpacity>
    );
  };

  const renderEmpty = () => (
    !normalizedQuery && (recentSearches.length || suggestionSections.length || suggestionsLoading) ? (
      <View style={styles.discovery}>
        {recentSearches.length ? (
          <View style={styles.discoverySection}>
            <Text style={styles.discoveryTitle}>Recent searches</Text>
            <View style={styles.recentRow}>
              {recentSearches.map((item) => (
                <TouchableOpacity
                  key={item}
                  testID={`recent-search-${item}`}
                  style={styles.recentChip}
                  activeOpacity={0.82}
                  onPress={() => setQuery(item)}
                >
                  <Feather name="clock" size={13} color="#858585" />
                  <Text style={styles.recentText} numberOfLines={1}>{item}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ) : null}

        {suggestionsLoading ? (
          <View style={styles.suggestionLoading}>
            <ActivityIndicator color="#e5e5e5" />
            <Text style={styles.suggestionLoadingText}>Loading suggestions</Text>
          </View>
        ) : null}

        {suggestionSections.map((section) => (
          <View key={section.id} style={styles.discoverySection}>
            <Text style={styles.discoveryTitle}>{section.title}</Text>
            {section.results.map((result) => (
              <View key={`${section.id}-${result.id}`} style={styles.suggestionRowWrap}>
                {renderResult({ item: result })}
              </View>
            ))}
          </View>
        ))}
      </View>
    ) : (
    <View style={styles.emptyState}>
      {loading ? (
        <ActivityIndicator color="#e5e5e5" style={styles.emptyIcon} />
      ) : (
        <Feather name="search" size={30} color="#6f6f6f" style={styles.emptyIcon} />
      )}
      <Text style={styles.emptyTitle}>{emptyTitle}</Text>
      <Text style={styles.emptySubtitle}>{emptySubtitle}</Text>
    </View>
    )
  );

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity
          testID="search-back"
          style={styles.backButton}
          activeOpacity={0.82}
          onPress={() => navigation.goBack()}
        >
          <Feather name="chevron-left" size={22} color="#e5e5e5" />
        </TouchableOpacity>
        <View style={styles.inputWrap}>
          <Feather name="search" size={17} color="#7c7c7c" />
          <TextInput
            testID="search-input"
            value={query}
            onChangeText={setQuery}
            placeholder="Search rides, climbs, riders, accounts"
            placeholderTextColor="#6f6f6f"
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            style={styles.input}
            returnKeyType="search"
          />
          {query ? (
            <TouchableOpacity testID="search-clear" onPress={() => setQuery('')} activeOpacity={0.82}>
              <Feather name="x" size={16} color="#7c7c7c" />
            </TouchableOpacity>
          ) : null}
        </View>
      </View>

      <View style={styles.chips}>
        {CATEGORIES.map((item) => {
          const selected = item === category;
          return (
            <TouchableOpacity
              key={item}
              testID={`search-category-${item}`}
              activeOpacity={0.82}
              onPress={() => setCategory(item)}
              style={[styles.chip, selected && styles.chipSelected]}
              accessibilityState={{ selected }}
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {categoryLabel(item)}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      <FlatList
        data={results}
        keyExtractor={(item) => item.id}
        renderItem={renderResult}
        ListEmptyComponent={renderEmpty}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[
          styles.listContent,
          results.length === 0 && styles.listContentEmpty,
        ]}
        ListFooterComponent={hasMore ? <Text style={styles.footerHint}>More results available. Refine your search.</Text> : null}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 12,
  },
  backButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#242424',
    backgroundColor: '#111111',
    alignItems: 'center',
    justifyContent: 'center',
  },
  inputWrap: {
    flex: 1,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#242424',
    backgroundColor: '#111111',
    paddingHorizontal: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  input: {
    flex: 1,
    color: '#e5e5e5',
    fontSize: 15,
    fontWeight: '500',
    paddingVertical: 0,
  },
  chips: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 16,
    paddingBottom: 12,
  },
  chip: {
    minHeight: 32,
    paddingHorizontal: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#262626',
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipSelected: {
    backgroundColor: '#d7c76a',
    borderColor: '#d7c76a',
  },
  chipText: {
    color: '#a5a5a5',
    fontSize: 12,
    fontWeight: '700',
  },
  chipTextSelected: {
    color: '#0a0a0a',
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 28,
  },
  listContentEmpty: {
    flexGrow: 1,
  },
  resultRow: {
    minHeight: 78,
    borderBottomWidth: 1,
    borderBottomColor: '#181818',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 13,
  },
  resultIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#141414',
    borderWidth: 1,
    borderColor: '#242424',
    alignItems: 'center',
    justifyContent: 'center',
  },
  resultBody: {
    flex: 1,
    minWidth: 0,
  },
  resultTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  resultTitle: {
    flex: 1,
    color: '#ededed',
    fontSize: 15,
    fontWeight: '700',
  },
  resultKind: {
    color: '#8c8c8c',
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  resultSubtitle: {
    marginTop: 3,
    color: '#9a9a9a',
    fontSize: 12,
    fontWeight: '500',
  },
  statRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 7,
  },
  statText: {
    color: '#858585',
    fontSize: 11,
    fontWeight: '600',
  },
  statValue: {
    color: '#d8d8d8',
  },
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
  },
  statusPill: {
    maxWidth: 130,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#2a2a2a',
    backgroundColor: '#121212',
    color: '#9f9f9f',
    fontSize: 10,
    fontWeight: '800',
    overflow: 'hidden',
    paddingHorizontal: 7,
    paddingVertical: 3,
    textTransform: 'uppercase',
  },
  discovery: {
    flexGrow: 1,
    paddingTop: 10,
    paddingBottom: 24,
  },
  discoverySection: {
    marginBottom: 22,
  },
  discoveryTitle: {
    color: '#e0e0e0',
    fontSize: 13,
    fontWeight: '800',
    marginBottom: 8,
    textTransform: 'uppercase',
  },
  recentRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  recentChip: {
    maxWidth: '100%',
    minHeight: 34,
    borderRadius: 17,
    borderWidth: 1,
    borderColor: '#242424',
    backgroundColor: '#101010',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 11,
  },
  recentText: {
    color: '#d0d0d0',
    fontSize: 12,
    fontWeight: '700',
  },
  suggestionLoading: {
    minHeight: 70,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  suggestionLoadingText: {
    color: '#8f8f8f',
    fontSize: 12,
    fontWeight: '700',
  },
  suggestionRowWrap: {
    borderTopWidth: 1,
    borderTopColor: '#111111',
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 36,
  },
  emptyIcon: {
    marginBottom: 16,
  },
  emptyTitle: {
    color: '#ededed',
    fontSize: 18,
    fontWeight: '700',
    textAlign: 'center',
  },
  emptySubtitle: {
    color: '#8f8f8f',
    fontSize: 13,
    lineHeight: 19,
    textAlign: 'center',
    marginTop: 8,
  },
  footerHint: {
    color: '#858585',
    fontSize: 12,
    textAlign: 'center',
    paddingVertical: 18,
  },
});
