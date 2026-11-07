/**
 * RideDetailScreen — archival view of a single ride.
 *
 * The rider can land here from either a local ride row (device only) or
 * a merged row (local + server). The screen renders immediately from
 * local SQLite so offline always works (MOBILE_TRUTHS §9.1). When a
 * server ride id is available, we additionally fetch processing state
 * and CAL earned, treating that layer as a best-effort enrichment —
 * server reachability never blocks the rider from seeing their own
 * ride.
 *
 * Product shape: a ride receipt. The screen should show what the rider did,
 * what climbs they touched, and where to open the deeper BoulderScan record.
 *
 * Surface requirements mapping: proof state -> Verification; Ride hash -> Ride file;
 * Commitment -> Chain; Finalized -> Counted; CAL Earned -> CAL earned.
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Image,
  TouchableOpacity,
  Alert,
  TextInput,
  Switch,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';

import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import RoutePreviewMap from '../components/route/RoutePreviewMap';
import {
  getDatabase,
  getRide,
  getRideSamples,
  getUploadEntryForRide,
  type RideRow,
  type UploadQueueRow,
} from '../services/database';
import {
  api,
  type Comment,
  type ResolvedLink,
  type RideInteractions,
  type RideMedia,
  type RideStatus,
  type RideSummary,
  type RideVisibility,
} from '../lib/api';
import { prepareNativeImageUpload } from '../lib/imageUpload';
import { deriveAttestationView } from '../lib/attestation';
import { deriveProcessingStages } from '../lib/rideProcessing';
import { RideReviewBanner } from '../components/RideReviewBanner';
import { RideProcessingStages } from '../components/RideProcessingStages';
import { goBackOrReset } from '../navigation/backNavigation';
import SegmentedControl from '../components/surfaces/SegmentedControl';
import {
  LocalObjectTabs,
  MetricBand,
  ObjectWindow,
  QuietProofRow,
} from '../components/surfaces/MobileSpine';
import { buildRoutePreviewFromGps, type RoutePreview } from '../lib/routePreview';
import {
  bestScanTarget,
  hasResolvedBoulderScanTarget,
  openResolvedProof,
  shareResolvedPayload,
} from '../lib/linkActions';
import {
  buildRideDisplayModel,
  climbConsequenceLine,
  formatDurationSec,
  rideConsequenceLine,
  statusStepState,
} from '../lib/rideDisplay';
import {
  recordStateLabelFromLink,
  recordStateLabelFromScanState,
  recordTargetLabel,
  rideRecordRows,
  rideRecordStatusLabel,
  rideRecordSubtitle,
} from '../lib/recordDisplay';
import { riderProfileRouteParams } from '../lib/riderNavigation';
import { deriveRideLifecycle, type RideLifecycleAction } from '../lib/rideLifecycle';
import {
  localLifecycleInputFromRide,
  uploadLifecycleInputFromEntry,
} from '../lib/rideLifecycleDisplay';
import RideLifecyclePanel from '../components/RideLifecyclePanel';
import { retryFailedUpload } from '../services/uploadQueue';
import { logout } from '../services/authService';
import { mobileColors, mobileRadii } from '../theme/tokens';

const RIDE_VISIBILITY_ITEMS = [
  { key: 'public', label: 'Public' },
  { key: 'followers', label: 'Followers' },
  { key: 'private', label: 'Private' },
];

const RIDE_OBJECT_TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'analysis', label: 'Analysis' },
  { key: 'climbs', label: 'Climbs' },
  { key: 'record', label: 'Status' },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RideDetailRouteParams = {
  RideDetail: {
    /** Local ride id (preferred — resolves straight to encrypted SQLite). */
    rideId?: string;
    /**
     * Server ride id, used when this row is server-only (e.g., Strava
     * import from another device). Falls back to server-only rendering.
     */
    serverRideId?: string;
    backLabel?: string;
  };
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RideDetailScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<RideDetailRouteParams, 'RideDetail'>>();
  const {
    rideId,
    serverRideId: routeServerRideId,
    backLabel = 'Home',
  } = route.params ?? {};

  const [localRide, setLocalRide] = useState<RideRow | null>(null);
  const [uploadEntry, setUploadEntry] = useState<UploadQueueRow | null>(null);
  const [localRoutePreview, setLocalRoutePreview] = useState<RoutePreview | null>(null);
  const [serverRide, setServerRide] = useState<RideSummary | null>(null);
  const [serverStatus, setServerStatus] = useState<RideStatus | null>(null);
  const [resolvedLink, setResolvedLink] = useState<ResolvedLink | null>(null);
  const [rideInteractions, setRideInteractions] = useState<RideInteractions | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [serverError, setServerError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [isReportingRide, setIsReportingRide] = useState(false);
  const [isSharingRide, setIsSharingRide] = useState(false);
  const [isKudosBusy, setIsKudosBusy] = useState(false);
  const [isSettingsBusy, setIsSettingsBusy] = useState(false);
  const [isMediaBusy, setIsMediaBusy] = useState(false);
  const [selectedMediaIndex, setSelectedMediaIndex] = useState(0);
  const [lifecycleBusyAction, setLifecycleBusyAction] = useState<RideLifecycleAction | null>(null);
  const [reportingCommentId, setReportingCommentId] = useState<string | null>(null);
  const [newComment, setNewComment] = useState('');
  const [isPostingComment, setIsPostingComment] = useState(false);
  const calEarned = serverStatus?.earnings?.calEarned ?? serverStatus?.calEarned;
  const isThresholdHeld = serverStatus?.effortPolicy?.thresholdEconomyState === 'held';
  const targetServerRideId = routeServerRideId ?? localRide?.upload_id ?? null;
  const rideMedia = serverRide?.media ?? [];
  const selectedMedia = rideMedia[Math.min(selectedMediaIndex, Math.max(rideMedia.length - 1, 0))] ?? null;

  useEffect(() => {
    if (selectedMediaIndex >= rideMedia.length) {
      setSelectedMediaIndex(Math.max(0, rideMedia.length - 1));
    }
  }, [rideMedia.length, selectedMediaIndex]);

  // Load local ride synchronously on mount. Missing rows are not an
  // error — a server-only ride just means there's nothing local to
  // show and the detail screen renders from server data alone.
  useEffect(() => {
    if (!rideId) {
      setLoading(false);
      return;
    }
    try {
      const db = getDatabase();
      const row = getRide(db, rideId);
      setLocalRide(row);
      setUploadEntry(row ? getUploadEntryForRide(db, rideId) : null);
      if (row) {
        const samples = getRideSamples(db, rideId);
        setLocalRoutePreview(buildRoutePreviewFromGps(samples, { source: 'local_gps' }));
      }
    } catch (err) {
      console.error('[RideDetail] Error loading local ride:', err);
    } finally {
      setLoading(false);
    }
  }, [rideId]);

  // Best-effort server enrichment. If offline, we quietly leave the
  // local summary standing rather than surfacing an error — offline
  // is normal (MOBILE_TRUTHS §8).
  useEffect(() => {
    let cancelled = false;
    if (!targetServerRideId) return;

    (async () => {
      try {
        const detail = await api.getRideDetail(targetServerRideId);
        if (cancelled) return;
        setServerStatus(detail.status);
        setRideInteractions(detail.interactions);
        setComments(detail.comments?.comments ?? []);
        setServerRide(detail.ride);
        setResolvedLink(detail.link);
        return;
      } catch {
        // Older deployed APIs may not have the detail shell yet; keep the
        // resilient legacy fan-out as a compatibility path.
      }

      const [statusResult, interactionsResult, commentsResult, rideResult, linkResult] = await Promise.allSettled([
        api.getRideStatus(targetServerRideId),
        api.getRideInteractions(targetServerRideId),
        api.getRideComments(targetServerRideId),
        api.getRide(targetServerRideId),
        api.resolveLink('ride', targetServerRideId),
      ]);

      if (cancelled) return;

      if (statusResult.status === 'fulfilled') {
        setServerStatus(statusResult.value);
      } else {
        setServerError(true);
      }

      if (interactionsResult.status === 'fulfilled') {
        setRideInteractions(interactionsResult.value);
      }

      if (commentsResult.status === 'fulfilled') {
        setComments(commentsResult.value.comments ?? []);
      }

      if (rideResult.status === 'fulfilled') {
        setServerRide(rideResult.value);
      }

      if (linkResult.status === 'fulfilled') {
        setResolvedLink(linkResult.value);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [targetServerRideId]);

  const handleBack = () => {
    goBackOrReset(navigation, 'Home');
  };

  const handleClimbPress = (climbId: string) => {
    (
      navigation as {
        navigate: (screen: string, params: { climbId: string; backLabel?: string }) => void;
      }
    ).navigate('ClimbDetail', { climbId, backLabel: 'Ride' });
  };

  const handleOpenBoulderScan = () => {
    void openResolvedProof(resolvedLink);
  };

  const handleShareRide = async () => {
    if (!targetServerRideId || isSharingRide) return;
    try {
      setIsSharingRide(true);
      const link = resolvedLink ?? await api.resolveLink('ride', targetServerRideId);
      setResolvedLink(link);
      await shareResolvedPayload(link.share);
    } catch {
      Alert.alert('Share unavailable', 'We could not build a share link for this ride yet.');
    } finally {
      setIsSharingRide(false);
    }
  };

  const handleToggleKudos = async () => {
    if (!targetServerRideId || !rideInteractions || isKudosBusy) return;
    const wasKudos = rideInteractions.viewerHasKudos;
    setIsKudosBusy(true);
    setRideInteractions((current) => current ? {
      ...current,
      viewerHasKudos: !wasKudos,
      kudosCount: Math.max(0, current.kudosCount + (wasKudos ? -1 : 1)),
    } : current);
    try {
      if (wasKudos) {
        await api.removeRideKudos(targetServerRideId);
      } else {
        await api.giveRideKudos(targetServerRideId);
      }
    } catch {
      setRideInteractions((current) => current ? {
        ...current,
        viewerHasKudos: wasKudos,
        kudosCount: Math.max(0, current.kudosCount + (wasKudos ? 1 : -1)),
      } : current);
      Alert.alert('Kudos failed', 'Please try again in a moment.');
    } finally {
      setIsKudosBusy(false);
    }
  };

  const updateRideVisibility = async (key: string) => {
    if (!targetServerRideId || !serverRide || isSettingsBusy) return;
    const visibility = key as RideVisibility;
    const previous = serverRide;
    setServerRide({ ...serverRide, visibility });
    setIsSettingsBusy(true);
    try {
      await api.updateRide(targetServerRideId, { visibility });
    } catch {
      setServerRide(previous);
      Alert.alert('Privacy update failed', 'Please try again in a moment.');
    } finally {
      setIsSettingsBusy(false);
    }
  };

  const updateCommentsEnabled = async (enabled: boolean) => {
    if (!targetServerRideId || !serverRide || isSettingsBusy) return;
    const previousRide = serverRide;
    const previousInteractions = rideInteractions;
    setServerRide({ ...serverRide, commentsEnabled: enabled });
    setRideInteractions((current) => current ? {
      ...current,
      commentsEnabled: enabled,
      canComment: enabled && current.canComment,
    } : current);
    setIsSettingsBusy(true);
    try {
      await api.updateRide(targetServerRideId, { commentsEnabled: enabled });
    } catch {
      setServerRide(previousRide);
      setRideInteractions(previousInteractions);
      Alert.alert('Comment setting failed', 'Please try again in a moment.');
    } finally {
      setIsSettingsBusy(false);
    }
  };

  const replaceRideMedia = (media: RideMedia[]) => {
    setServerRide((current) => current ? { ...current, media } : current);
  };

  const handleAddRidePhoto = async () => {
    if (!targetServerRideId || !serverRide?.privacy?.isOwner || isMediaBusy) return;
    if (rideMedia.length >= 6) {
      Alert.alert('Photo limit reached', 'Rides can have up to 6 photos.');
      return;
    }
    setIsMediaBusy(true);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Photo access needed', 'Allow photo access to attach ride photos.');
        return;
      }
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsMultipleSelection: true,
        selectionLimit: Math.max(1, 6 - rideMedia.length),
        quality: 1,
        exif: false,
      });
      if (picked.canceled) return;
      const uploaded: RideMedia[] = [];
      for (const [index, asset] of picked.assets.slice(0, 6 - rideMedia.length).entries()) {
        const prepared = await prepareNativeImageUpload(asset, {
          fileNamePrefix: `ride-${targetServerRideId}-photo`,
          maxDimension: 2048,
          maxBytes: 4 * 1024 * 1024,
        });
        uploaded.push(await api.uploadRideMedia(targetServerRideId, prepared, rideMedia.length + index));
      }
      replaceRideMedia([...rideMedia, ...uploaded]);
      if (uploaded.length > 0) {
        setSelectedMediaIndex(rideMedia.length);
      }
    } catch (err) {
      Alert.alert('Photo upload failed', err instanceof Error ? err.message : 'Please try again.');
    } finally {
      setIsMediaBusy(false);
    }
  };

  const handleSetRideCover = async () => {
    if (!targetServerRideId || !selectedMedia || isMediaBusy) return;
    setIsMediaBusy(true);
    try {
      const updated = await api.updateRideMedia(targetServerRideId, selectedMedia.id, { role: 'cover' });
      replaceRideMedia(
        rideMedia
          .map((item) => ({
            ...item,
            role: item.id === updated.id ? 'cover' as const : 'photo' as const,
            sortOrder: item.id === updated.id ? 0 : item.sortOrder,
          }))
          .sort((a, b) => a.sortOrder - b.sortOrder),
      );
      setSelectedMediaIndex(0);
    } catch {
      Alert.alert('Cover update failed', 'Please try again in a moment.');
    } finally {
      setIsMediaBusy(false);
    }
  };

  const handleDeleteRidePhoto = async () => {
    if (!targetServerRideId || !selectedMedia || isMediaBusy) return;
    setIsMediaBusy(true);
    try {
      await api.deleteRideMedia(targetServerRideId, selectedMedia.id);
      const remaining = rideMedia.filter((item) => item.id !== selectedMedia.id);
      const normalized = remaining.map((item, index) => ({
        ...item,
        sortOrder: index,
        role: remaining.some((candidate) => candidate.role === 'cover')
          ? item.role
          : index === 0
            ? 'cover' as const
            : 'photo' as const,
      }));
      replaceRideMedia(normalized);
      setSelectedMediaIndex((current) => Math.max(0, Math.min(current, normalized.length - 1)));
    } catch {
      Alert.alert('Photo delete failed', 'Please try again in a moment.');
    } finally {
      setIsMediaBusy(false);
    }
  };

  const submitRideReport = async () => {
    if (!targetServerRideId || isReportingRide || rideInteractions?.viewerReported) return;

    try {
      setIsReportingRide(true);
      const report = await api.reportSocialContent(
        'ride',
        targetServerRideId,
        'other',
        'Reported from mobile ride detail',
      );
      setRideInteractions((current) => ({
        rideId: targetServerRideId,
        kudosCount: current?.kudosCount ?? 0,
        commentCount: current?.commentCount ?? 0,
        viewerHasKudos: current?.viewerHasKudos ?? false,
        commentsEnabled: current?.commentsEnabled ?? true,
        canComment: current?.canComment ?? false,
        ...(current ?? {}),
        viewerReported: true,
        reportStatus: report.status,
      }));
    } catch {
      Alert.alert('Report failed', 'Please try again in a moment.');
    } finally {
      setIsReportingRide(false);
    }
  };

  const handleReportRide = () => {
    if (rideInteractions?.viewerReported) return;
    Alert.alert(
      'Report ride',
      'Send this ride to the moderation queue for review?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Report',
          style: 'destructive',
          onPress: () => {
            void submitRideReport();
          },
        },
      ],
    );
  };

  const submitCommentReport = async (commentId: string) => {
    if (reportingCommentId) return;

    try {
      setReportingCommentId(commentId);
      const report = await api.reportSocialContent(
        'comment',
        commentId,
        'other',
        'Reported from mobile ride comments',
      );
      setComments((current) => current.map((comment) => (
        comment.id === commentId
          ? { ...comment, viewerReported: true, reportStatus: report.status }
          : comment
      )));
    } catch {
      Alert.alert('Report failed', 'Please try again in a moment.');
    } finally {
      setReportingCommentId(null);
    }
  };

  const handleReportComment = (comment: Comment) => {
    if (comment.viewerReported) return;
    Alert.alert(
      'Report comment',
      'Send this comment to the moderation queue for review?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Report',
          style: 'destructive',
          onPress: () => {
            void submitCommentReport(comment.id);
          },
        },
      ],
    );
  };

  const handleCommentAuthorPress = (comment: Comment) => {
    const route = riderProfileRouteParams({
      ...(comment.author ?? {}),
      id: comment.author?.id ?? comment.userId,
      username: comment.author?.username ?? comment.username,
      displayName: comment.author?.displayName ?? comment.displayName,
      avatarUrl: comment.author?.avatarUrl ?? comment.avatarUrl,
    }, { backLabel: 'Ride' });
    if (!route) return;
    (
      navigation as {
        navigate: (screen: string, params?: object) => void;
      }
    ).navigate('RiderDetail', route);
  };

  const handlePostComment = async () => {
    if (!targetServerRideId || isPostingComment) return;
    const content = newComment.trim();
    if (!content) return;

    try {
      setIsPostingComment(true);
      const comment = await api.addRideComment(targetServerRideId, content);
      setComments((current) => [...current, comment]);
      setNewComment('');
      setRideInteractions((current) => current ? {
        ...current,
        commentCount: current.commentCount + 1,
      } : current);
    } catch {
      Alert.alert('Comment failed', 'Please try again in a moment.');
    } finally {
      setIsPostingComment(false);
    }
  };

  const handleLifecycleAction = async (action: RideLifecycleAction) => {
    if (lifecycleBusyAction) return;
    setLifecycleBusyAction(action);
    try {
      if (action === 'retry_upload' && localRide?.id) {
        retryFailedUpload(localRide.id);
        const db = getDatabase();
        setUploadEntry(getUploadEntryForRide(db, localRide.id));
        return;
      }
      if (action === 'reauthenticate') {
        await logout();
        return;
      }
      if (action === 'retry_processing' && targetServerRideId) {
        await api.reprocessRide(targetServerRideId);
        setServerStatus((current) => current ? {
          ...current,
          status: 'processing',
          processingStage: 'processing',
          errorMessage: null,
          failure: null,
          canRetryProcessing: false,
        } : current);
      }
    } catch {
      Alert.alert('Ride action failed', 'Please try again in a moment.');
    } finally {
      setLifecycleBusyAction(null);
    }
  };

  // Initial blocking spinner only while local read is in flight.
  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={mobileColors.accent} />
        </View>
      </SafeAreaView>
    );
  }

  // If we have nothing local AND no server hint, show an empty state
  // rather than rendering a blank screen — something went wrong in
  // navigation wiring and the rider deserves a way back.
  if (!localRide && !routeServerRideId) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <DetailHeader
            backLabel={backLabel}
            title="Ride"
            subtitle="We couldn't locate this ride right now."
            onBack={handleBack}
          />
          <DetailModule title="Unavailable">
            <Text style={styles.emptySubtitle}>
              We couldn&apos;t locate this ride on your device.
            </Text>
          </DetailModule>
        </ScrollView>
      </SafeAreaView>
    );
  }

  const displayModel = buildRideDisplayModel({
    localRide,
    localRoutePreview,
    serverRide,
    serverStatus,
    resolvedLink,
    rideInteractions,
    targetServerRideId,
  });
  const climbMatches = serverStatus?.climbEarnings ?? [];
  const lifecycle = deriveRideLifecycle({
    localRide: localLifecycleInputFromRide(localRide),
    uploadEntry: uploadLifecycleInputFromEntry(uploadEntry),
    serverStatus,
  });
  const scanTarget = bestScanTarget(resolvedLink);
  const canOpenBoulderScan = hasResolvedBoulderScanTarget(resolvedLink);
  const lifecycleHasRepairAction = lifecycle.actions.some((action) => action !== 'open_ride');
  const headerStatusLabel = rideRecordStatusLabel(serverStatus, !!targetServerRideId);
  const recordRows = rideRecordRows(serverStatus);
  const primaryMedia = selectedMedia?.url
    ? selectedMedia
    : rideMedia.find((item) => item.role === 'cover' && item.url) ?? rideMedia.find((item) => item.url) ?? null;
  const trustItems = [
    {
      label: 'Source',
      value: displayModel.routePreview ? displayModel.routeLabel : 'Ride log',
      tone: 'muted' as const,
    },
    {
      label: 'Status',
      value: targetServerRideId ? headerStatusLabel : 'Local only',
      tone: targetServerRideId ? 'proof' as const : 'muted' as const,
    },
    {
      label: isThresholdHeld ? 'CAL' : 'Counted CAL',
      value: isThresholdHeld ? 'Held' : calEarned != null ? `+${calEarned}` : 'Pending',
      tone: isThresholdHeld || calEarned != null ? 'reward' as const : 'muted' as const,
    },
  ];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel={backLabel}
          eyebrow="Ride"
          title={displayModel.title}
          subtitle={displayModel.subtitle}
          statusLabel={headerStatusLabel}
          onBack={handleBack}
        >
          <QuietProofRow items={trustItems} />
        </DetailHeader>

        <RoutePreviewMap
          preview={displayModel.routePreview}
          variant="detail"
          height={252}
          style={styles.featuredMap}
          testID="ride-detail-route-preview"
        />

        <ObjectWindow style={styles.tabsWindow}>
          <LocalObjectTabs items={RIDE_OBJECT_TABS} activeKey="overview" />
        </ObjectWindow>

        {(primaryMedia?.url || serverRide?.privacy?.isOwner) ? (
          <DetailModule
            title="Photos"
            subtitle={primaryMedia?.url ? `${rideMedia.length} photo${rideMedia.length === 1 ? '' : 's'}` : 'Add context to this ride'}
          >
          {primaryMedia?.url ? (
            <View style={styles.ridePhotoGallery}>
              <View style={styles.ridePhotoFrame}>
                <Image
                  source={{ uri: primaryMedia.url }}
                  style={styles.ridePhoto}
                  resizeMode="cover"
                  accessibilityIgnoresInvertColors
                />
                {rideMedia.length > 1 ? (
                  <View style={styles.ridePhotoBadge}>
                    <Text style={styles.ridePhotoBadgeText}>{rideMedia.length} photos</Text>
                  </View>
                ) : null}
              </View>
              {rideMedia.length > 1 ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.ridePhotoStrip}>
                  {rideMedia.map((item, index) => item.url ? (
                    <TouchableOpacity
                      key={item.id}
                      onPress={() => setSelectedMediaIndex(index)}
                      activeOpacity={0.82}
                    >
                      <Image
                        source={{ uri: item.url }}
                        style={[
                          styles.ridePhotoThumb,
                          index === selectedMediaIndex && styles.ridePhotoThumbActive,
                        ]}
                        resizeMode="cover"
                        accessibilityIgnoresInvertColors
                      />
                    </TouchableOpacity>
                  ) : null)}
                </ScrollView>
              ) : null}
              {serverRide?.privacy?.isOwner ? (
                <View style={styles.mediaActionRow}>
                  <TouchableOpacity
                    style={[styles.mediaAction, (isMediaBusy || rideMedia.length >= 6) && styles.mediaActionDisabled]}
                    disabled={isMediaBusy || rideMedia.length >= 6}
                    onPress={handleAddRidePhoto}
                    activeOpacity={0.82}
                  >
                    <Text style={styles.mediaActionText}>Add</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.mediaAction, (isMediaBusy || primaryMedia.role === 'cover') && styles.mediaActionDisabled]}
                    disabled={isMediaBusy || primaryMedia.role === 'cover'}
                    onPress={handleSetRideCover}
                    activeOpacity={0.82}
                  >
                    <Text style={styles.mediaActionText}>Cover</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.mediaAction, styles.mediaActionDanger, isMediaBusy && styles.mediaActionDisabled]}
                    disabled={isMediaBusy}
                    onPress={handleDeleteRidePhoto}
                    activeOpacity={0.82}
                  >
                    <Text style={[styles.mediaActionText, styles.mediaActionDangerText]}>Delete</Text>
                  </TouchableOpacity>
                </View>
              ) : null}
            </View>
          ) : serverRide?.privacy?.isOwner ? (
            <View style={styles.ridePhotoEmpty}>
              <TouchableOpacity
                style={[styles.mediaAction, isMediaBusy && styles.mediaActionDisabled]}
                disabled={isMediaBusy}
                onPress={handleAddRidePhoto}
                activeOpacity={0.82}
              >
                <Text style={styles.mediaActionText}>{isMediaBusy ? 'Adding' : 'Add photos'}</Text>
              </TouchableOpacity>
            </View>
          ) : null}
          </DetailModule>
        ) : null}

        <DetailModule
          title="Ride"
          subtitle={rideConsequenceLine(localRide, serverStatus)}
        >
          <MetricBand items={displayModel.facts} columns={2} />
          {displayModel.summaryStats.length > 0 ? <MetricBand items={displayModel.summaryStats} /> : null}
          {localRide ? (
            <Text style={styles.supportingLine}>
              {(localRide.max_speed_mps * 3.6).toFixed(1)} km/h max speed • {localRide.sample_count} GPS points
            </Text>
          ) : (
            <Text style={styles.supportingLine}>
              {serverStatus?.metrics?.avgPowerW != null
                ? `${Math.round(serverStatus.metrics.avgPowerW)} W average power`
              : 'Checking ride'}
            </Text>
          )}
          {targetServerRideId ? (
            <View style={styles.socialRow}>
              <TouchableOpacity
                style={[styles.socialButton, isKudosBusy && styles.reportButtonDisabled]}
                disabled={isKudosBusy || !rideInteractions}
                onPress={handleToggleKudos}
                activeOpacity={0.82}
                testID="ride-detail-kudos"
              >
                <Text style={styles.socialButtonText}>
                  {rideInteractions?.viewerHasKudos ? 'Kudos given' : 'Give kudos'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.socialButton, isSharingRide && styles.reportButtonDisabled]}
                disabled={isSharingRide}
                onPress={handleShareRide}
                activeOpacity={0.82}
                testID="ride-detail-share"
              >
                <Text style={styles.socialButtonText}>{isSharingRide ? 'Sharing' : 'Share'}</Text>
              </TouchableOpacity>
              <Text style={styles.socialCounts}>
                {rideInteractions?.kudosCount ?? 0} kudos • {rideInteractions?.commentCount ?? comments.length} comments
              </Text>
            </View>
          ) : null}
          {targetServerRideId ? (
            <View style={styles.reportRow}>
              <Text style={styles.reportState}>
                {rideInteractions?.viewerReported
                  ? `Reported${rideInteractions.reportStatus ? ` • ${rideInteractions.reportStatus}` : ''}`
                  : 'Community safety'}
              </Text>
              <TouchableOpacity
                style={[
                  styles.reportButton,
                  (rideInteractions?.viewerReported || isReportingRide) && styles.reportButtonDisabled,
                ]}
                disabled={rideInteractions?.viewerReported || isReportingRide}
                onPress={handleReportRide}
                activeOpacity={0.82}
                testID="ride-detail-report"
              >
                <Text style={styles.reportButtonText}>
                  {rideInteractions?.viewerReported
                    ? 'Reported'
                    : isReportingRide
                      ? 'Reporting'
                      : 'Report ride'}
                </Text>
              </TouchableOpacity>
            </View>
          ) : null}
        </DetailModule>

        <DetailModule title="Climbs">
          {climbMatches.length > 0 ? (
            climbMatches.map((climb) => (
              <TouchableOpacity
                key={`${climb.climbId}-${climb.completedAt ?? 'pending'}`}
                style={styles.climbRow}
                onPress={() => handleClimbPress(climb.climbId)}
                activeOpacity={0.82}
              >
                <View style={styles.climbRowBody}>
                  <Text style={styles.climbName}>{climb.climbName ?? 'Unnamed Climb'}</Text>
                  <Text style={styles.climbMeta}>
                    {climb.completionTimeS != null ? formatDurationSec(climb.completionTimeS) : 'Matched climb'}
                  </Text>
                </View>
                <View style={styles.climbConsequence}>
                  <Text style={styles.climbConsequenceText}>{climbConsequenceLine(climb)}</Text>
                </View>
                <Text style={styles.climbChevron}>›</Text>
              </TouchableOpacity>
            ))
          ) : (
            <Text style={styles.sectionText}>
              No climbs on this ride
            </Text>
          )}
        </DetailModule>

        {serverRide?.privacy?.isOwner ? (
          <DetailModule title="Ride controls" subtitle="Per-ride privacy and comments">
            <SegmentedControl
              items={RIDE_VISIBILITY_ITEMS}
              activeKey={serverRide.visibility ?? serverRide.privacy?.visibility ?? 'public'}
              onChange={updateRideVisibility}
            />
            <View style={styles.settingRow}>
              <View style={styles.settingCopy}>
                <Text style={styles.settingTitle}>Comments</Text>
                <Text style={styles.settingSubtitle}>
                  {serverRide.commentsEnabled === false ? 'Closed on this ride' : 'Open on this ride'}
                </Text>
              </View>
              <Switch
                value={serverRide.commentsEnabled !== false}
                disabled={isSettingsBusy}
                onValueChange={updateCommentsEnabled}
                trackColor={{ false: mobileColors.surfaceMuted, true: mobileColors.accentSoft }}
                thumbColor={serverRide.commentsEnabled !== false ? mobileColors.accent : mobileColors.textSubtle}
              />
            </View>
          </DetailModule>
        ) : null}

        {targetServerRideId ? (
          <DetailModule
            title="Comments"
            subtitle={`${comments.length} message${comments.length === 1 ? '' : 's'}`}
          >
            {comments.length > 0 ? (
              comments.map((comment) => (
                <View key={comment.id} style={styles.commentRow}>
                  <View style={styles.commentBody}>
                    <TouchableOpacity
                      onPress={() => handleCommentAuthorPress(comment)}
                      activeOpacity={0.82}
                      testID={`comment-author-${comment.id}`}
                    >
                      <Text style={styles.commentAuthor}>
                        {comment.displayName || comment.username || 'Rider'}
                      </Text>
                    </TouchableOpacity>
                    <Text style={styles.commentText}>{comment.content}</Text>
                    {comment.viewerReported ? (
                      <Text style={styles.commentReported}>
                        Reported{comment.reportStatus ? ` • ${comment.reportStatus}` : ''}
                      </Text>
                    ) : null}
                  </View>
                  <TouchableOpacity
                    style={[
                      styles.commentReportButton,
                      (comment.viewerReported || reportingCommentId === comment.id) && styles.reportButtonDisabled,
                    ]}
                    disabled={comment.viewerReported || reportingCommentId === comment.id}
                    onPress={() => handleReportComment(comment)}
                    activeOpacity={0.82}
                    testID={`comment-report-${comment.id}`}
                  >
                    <Text style={styles.commentReportText}>
                      {comment.viewerReported ? 'Reported' : 'Report'}
                    </Text>
                  </TouchableOpacity>
                </View>
              ))
            ) : (
              <Text style={styles.sectionText}>No comments yet</Text>
            )}

            {rideInteractions?.canComment !== false ? (
              <View style={styles.commentComposer}>
                <TextInput
                  value={newComment}
                  onChangeText={setNewComment}
                  placeholder="Add a comment"
                  placeholderTextColor={mobileColors.textSubtle}
                  style={styles.commentInput}
                  multiline
                />
                <TouchableOpacity
                  style={[styles.postButton, (!newComment.trim() || isPostingComment) && styles.reportButtonDisabled]}
                  disabled={!newComment.trim() || isPostingComment}
                  onPress={handlePostComment}
                  activeOpacity={0.82}
                >
                  <Text style={styles.postButtonText}>{isPostingComment ? 'Posting' : 'Post'}</Text>
                </TouchableOpacity>
              </View>
            ) : null}
          </DetailModule>
        ) : null}

        <DetailModule title="Status" subtitle="Saved • climbs • verified">
          <RideLifecyclePanel
            view={lifecycle}
            compact
            busyAction={lifecycleBusyAction}
            onPressAction={lifecycleHasRepairAction ? handleLifecycleAction : undefined}
            testID="ride-detail-lifecycle"
          />
          <View style={styles.timeline}>
            {(['saved', 'uploaded', 'climbs', 'verified', 'paid'] as const).map((step) => {
              const state = statusStepState(serverStatus, step);
              const label = step.charAt(0).toUpperCase() + step.slice(1);
              return (
                <View key={step} style={styles.timelineItem}>
                  <View style={[styles.timelineDot, state === 'done' && styles.timelineDotDone]} />
                  <Text style={[styles.timelineLabel, state === 'done' && styles.timelineLabelDone]}>
                    {label}
                  </Text>
                </View>
              );
            })}
          </View>

          {serverStatus ? (
            <>
              <RideReviewBanner view={deriveAttestationView(serverStatus)} />
              <RideProcessingStages stages={deriveProcessingStages(serverStatus)} />
            </>
          ) : (
            <Text style={styles.sectionText}>
              {targetServerRideId
                ? 'Checking ride'
                : 'On this device. Upload to see climbs and CAL.'}
            </Text>
          )}

          {serverError && !serverStatus ? (
            <Text style={styles.offlineText}>Offline — showing local ride only</Text>
          ) : null}
        </DetailModule>

        {isThresholdHeld ? (
          <DetailModule title="CAL">
            <Text style={styles.calValue}>Held</Text>
            <Text style={styles.supportingLine}>
              Held — clears when your Threshold is established.
            </Text>
          </DetailModule>
        ) : (calEarned !== undefined || serverStatus?.earnings?.finalizedAt) ? (
          <DetailModule title="Counted CAL">
            <Text style={styles.calValue}>{calEarned != null ? `+${calEarned}` : '—'}</Text>
            <Text style={styles.calLabel}>CAL</Text>
            <Text style={styles.supportingLine}>
              {serverStatus?.finalizedAt ?? serverStatus?.earnings?.finalizedAt ? 'Credited' : 'Waiting to count'}
            </Text>
          </DetailModule>
        ) : null}

        {serverStatus ? (
          <DetailModule
            title="Verification"
            subtitle={recordStateLabelFromLink(resolvedLink) ?? rideRecordSubtitle(serverStatus)}
            ctaLabel={canOpenBoulderScan ? 'Open BoulderScan' : undefined}
            onPressCta={canOpenBoulderScan ? handleOpenBoulderScan : undefined}
          >
            <View style={styles.boulderScanSummary}>
              <Text style={styles.boulderScanState}>
                {resolvedLink
                  ? recordStateLabelFromScanState(scanTarget?.state ?? resolvedLink.scanState)
                  : rideRecordStatusLabel(serverStatus, true)}
              </Text>
              {scanTarget ? (
                <Text style={styles.supportingLine}>{recordTargetLabel(scanTarget)}</Text>
              ) : null}
              <QuietProofRow
                items={recordRows.map(([label, value]) => ({
                  label,
                  value,
                  tone: label === 'Status' ? 'proof' : label === 'Counted CAL' || label === 'CAL' ? 'reward' : 'muted',
                }))}
              />
            </View>
          </DetailModule>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Styles — intentionally minimal; designer will own the polish pass.
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: mobileColors.canvas,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  scroll: {
    padding: 14,
    paddingBottom: 28,
  },
  tabsWindow: {
    marginTop: -2,
    paddingHorizontal: 4,
    paddingVertical: 2,
  },
  featuredMap: {
    marginBottom: 10,
  },
  boulderScanSummary: {
    gap: 10,
  },
  boulderScanState: {
    fontSize: 16,
    fontWeight: '800',
    color: mobileColors.proof,
  },
  ridePhotoGallery: {
    gap: 10,
  },
  ridePhotoFrame: {
    position: 'relative',
    height: 224,
    backgroundColor: mobileColors.surfaceStrong,
    borderRadius: mobileRadii.md,
    overflow: 'hidden',
  },
  ridePhoto: {
    width: '100%',
    height: '100%',
  },
  ridePhotoStrip: {
    gap: 8,
    paddingRight: 8,
  },
  ridePhotoThumb: {
    width: 72,
    height: 54,
    borderRadius: mobileRadii.sm,
    backgroundColor: mobileColors.surfaceStrong,
    opacity: 0.68,
  },
  ridePhotoThumbActive: {
    opacity: 1,
    borderWidth: 2,
    borderColor: mobileColors.accent,
  },
  ridePhotoBadge: {
    position: 'absolute',
    right: 10,
    bottom: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255, 255, 255, 0.18)',
    backgroundColor: 'rgba(17, 17, 15, 0.78)',
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  ridePhotoBadgeText: {
    color: mobileColors.surface,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  ridePhotoEmpty: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    backgroundColor: mobileColors.surfaceStrong,
    borderRadius: mobileRadii.md,
    padding: 14,
    alignItems: 'flex-start',
  },
  mediaActionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  mediaAction: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    backgroundColor: mobileColors.surfaceMuted,
    paddingHorizontal: 11,
    paddingVertical: 8,
    borderRadius: mobileRadii.sm,
  },
  mediaActionDisabled: {
    opacity: 0.48,
  },
  mediaActionDanger: {
    borderColor: 'rgba(239, 68, 68, 0.42)',
    backgroundColor: 'rgba(127, 29, 29, 0.18)',
  },
  mediaActionText: {
    color: mobileColors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  mediaActionDangerText: {
    color: '#fca5a5',
  },
  calValue: {
    fontSize: 34,
    fontWeight: '800',
    color: mobileColors.reward,
    marginBottom: 4,
  },
  calLabel: {
    fontSize: 14,
    color: mobileColors.textMuted,
    marginBottom: 6,
  },
  offlineText: {
    fontSize: 12,
    color: mobileColors.textMuted,
    lineHeight: 18,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: mobileColors.text,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptySubtitle: {
    fontSize: 14,
    color: mobileColors.textMuted,
    textAlign: 'center',
    marginBottom: 16,
  },
  sectionText: {
    color: mobileColors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  supportingLine: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  reportRow: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  socialRow: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
  },
  socialButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(201, 99, 44, 0.28)',
    backgroundColor: mobileColors.accentSoft,
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  socialButtonText: {
    color: mobileColors.accent,
    fontSize: 12,
    fontWeight: '800',
  },
  socialCounts: {
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '700',
  },
  settingRow: {
    marginTop: 10,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  settingCopy: {
    flex: 1,
    minWidth: 0,
  },
  settingTitle: {
    color: mobileColors.text,
    fontSize: 14,
    fontWeight: '800',
  },
  settingSubtitle: {
    color: mobileColors.textMuted,
    fontSize: 12,
    marginTop: 4,
  },
  reportState: {
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '700',
  },
  reportButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(180, 90, 77, 0.32)',
    backgroundColor: mobileColors.dangerSoft,
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  reportButtonDisabled: {
    opacity: 0.55,
  },
  reportButtonText: {
    color: mobileColors.danger,
    fontSize: 12,
    fontWeight: '800',
  },
  commentRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: mobileColors.divider,
  },
  commentBody: {
    flex: 1,
    minWidth: 0,
  },
  commentAuthor: {
    color: mobileColors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  commentText: {
    color: mobileColors.textMuted,
    fontSize: 14,
    lineHeight: 20,
    marginTop: 4,
  },
  commentReported: {
    color: mobileColors.danger,
    fontSize: 11,
    fontWeight: '700',
    marginTop: 6,
  },
  commentReportButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(180, 90, 77, 0.32)',
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  commentReportText: {
    color: mobileColors.danger,
    fontSize: 11,
    fontWeight: '700',
  },
  commentComposer: {
    marginTop: 12,
    gap: 10,
  },
  commentInput: {
    minHeight: 44,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
    borderRadius: mobileRadii.sm,
    backgroundColor: mobileColors.surfaceStrong,
    color: mobileColors.text,
    paddingHorizontal: 12,
    paddingVertical: 9,
    fontSize: 14,
  },
  postButton: {
    alignSelf: 'flex-end',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(201, 99, 44, 0.28)',
    backgroundColor: mobileColors.accentSoft,
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  postButtonText: {
    color: mobileColors.accent,
    fontSize: 12,
    fontWeight: '700',
  },
  climbRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: mobileColors.divider,
  },
  climbRowBody: {
    flex: 1,
  },
  climbName: {
    color: mobileColors.text,
    fontSize: 15,
    fontWeight: '600',
  },
  climbMeta: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 4,
  },
  climbConsequence: {
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(168, 120, 40, 0.28)',
    backgroundColor: mobileColors.rewardSoft,
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  climbConsequenceText: {
    color: mobileColors.reward,
    fontSize: 12,
    fontWeight: '700',
  },
  climbChevron: {
    color: mobileColors.textSubtle,
    fontSize: 17,
  },
  timeline: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  timelineItem: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    paddingHorizontal: 9,
    paddingVertical: 6,
    gap: 6,
  },
  timelineDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: mobileColors.textSubtle,
  },
  timelineDotDone: {
    backgroundColor: mobileColors.proof,
  },
  timelineLabel: {
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '700',
  },
  timelineLabelDone: {
    color: mobileColors.text,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
