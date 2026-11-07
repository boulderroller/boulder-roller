/**
 * PostRideScreen — Ride Summary After Recording
 *
 * Shows ride summary from local SQLite data immediately.
 * Polls server for processing status after upload completes.
 * Progressive reveal: metrics first, then climbs, then CAL.
 *
 * Per MOBILE_DATA_CONTRACTS.md Part 2: Post-Ride Response.
 * Surface requirements mapping: proof state -> Verification; Ride hash -> Ride file;
 * Commitment -> Chain; Finalized -> Counted; CAL Earned -> Counted CAL.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Alert,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';

import { getDatabase, getRide, getUploadEntryForRide, type RideRow, type UploadQueueRow } from '../services/database';
import { api, type ResolvedLink, type RideMedia, type RideStatus } from '../lib/api';
import { prepareNativeImageUpload, type PreparedNativeImageUpload } from '../lib/imageUpload';
import { derivePostRideCascade } from '../lib/postRideCascade';
import {
  POST_RIDE_SERVER_STATUS_POLL_MS,
  POST_RIDE_UPLOAD_POLL_MS,
  derivePostRideUploadProgress,
  type PostRideUploadState,
} from '../lib/postRideProgress';
import {
  getRideValidationSummary,
  type RideValidationSummary,
} from '../lib/rideValidation';
import { PostRideCascadePanel } from '../components/PostRideCascadePanel';
import { openResolvedProof as openResolvedBoulderScanTarget, shareResolvedPayload } from '../lib/linkActions';
import { incompleteRideReason } from '../lib/rideCompletion';
import { buildPostRideDisplayModel } from '../lib/postRideDisplay';
import { deriveRideLifecycle, type RideLifecycleAction } from '../lib/rideLifecycle';
import {
  localLifecycleInputFromRide,
  uploadLifecycleInputFromEntry,
} from '../lib/rideLifecycleDisplay';
import { rideRecordRows } from '../lib/recordDisplay';
import RideLifecyclePanel from '../components/RideLifecyclePanel';
import { retryFailedUpload } from '../services/uploadQueue';
import { logout } from '../services/authService';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PostRideRouteParams = {
  PostRide: { rideId: string };
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PostRideScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<PostRideRouteParams, 'PostRide'>>();
  const { rideId } = route.params;

  const [localRide, setLocalRide] = useState<RideRow | null>(null);
  const [serverStatus, setServerStatus] = useState<RideStatus | null>(null);
  const [uploadState, setUploadState] = useState<PostRideUploadState>('uploading');
  const [uploadEntry, setUploadEntry] = useState<UploadQueueRow | null>(null);
  const [serverRideId, setServerRideId] = useState<string | null>(null);
  const [resolvedLink, setResolvedLink] = useState<ResolvedLink | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [pendingPhotoUploads, setPendingPhotoUploads] = useState<PreparedNativeImageUpload[]>([]);
  const [uploadedMedia, setUploadedMedia] = useState<RideMedia[]>([]);
  const [lifecycleBusyAction, setLifecycleBusyAction] = useState<RideLifecycleAction | null>(null);
  const [uploadRetryVersion, setUploadRetryVersion] = useState(0);
  const [validationSummary, setValidationSummary] = useState<RideValidationSummary | null>(null);
  const localIncompleteReason = localRide ? incompleteRideReason({
    status: localRide.status,
    distanceM: localRide.distance_m,
    durationMs: localRide.duration_ms,
    sampleCount: localRide.sample_count,
  }) : null;
  const isIncompleteRecording = localIncompleteReason != null;
  const cascade = derivePostRideCascade({
    uploadState,
    status: serverStatus,
    isIncomplete: isIncompleteRecording,
    incompleteReason: localIncompleteReason ?? undefined,
  });

  const refreshValidationSummary = useCallback(() => {
    if (!__DEV__) return;
    try {
      const db = getDatabase();
      setValidationSummary(getRideValidationSummary(db, rideId));
    } catch {
      setValidationSummary(null);
    }
  }, [rideId]);

  // Load local ride data immediately
  useEffect(() => {
    try {
      const db = getDatabase();
      const ride = getRide(db, rideId);
      setLocalRide(ride);
      refreshValidationSummary();
    } catch (err) {
      console.error('[PostRide] Error loading ride:', err);
    }
  }, [refreshValidationSummary, rideId]);

  // Poll local upload completion quickly. This is the decisive stop gate:
  // as soon as the backend accepts the file, the rider leaves "uploading"
  // even if scoring is still catching up.
  useEffect(() => {
    if (isIncompleteRecording) {
      setServerRideId(null);
      return undefined;
    }

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let mounted = true;

    const checkUpload = () => {
      const db = getDatabase();
      const entry = getUploadEntryForRide(db, rideId);

      const progress = derivePostRideUploadProgress(entry);
      if (!mounted) return;
      setUploadEntry(entry);
      setUploadState(progress.state);
      if (progress.serverRideId) {
        setServerRideId(progress.serverRideId);
      }
      refreshValidationSummary();
      if (progress.state !== 'uploading' && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    checkUpload();
    pollTimer = setInterval(checkUpload, POST_RIDE_UPLOAD_POLL_MS);

    return () => {
      mounted = false;
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [isIncompleteRecording, refreshValidationSummary, rideId, uploadRetryVersion]);

  // Poll server processing independently from local upload acceptance.
  // The old single-effect shape only fetched status once after upload.
  useEffect(() => {
    if (!serverRideId || isIncompleteRecording) return undefined;

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let mounted = true;
    let complete = false;
    let inFlight = false;

    const pollServerStatus = async () => {
      if (complete || inFlight) return;
      inFlight = true;
      try {
        const result = await api.getRideStatus(serverRideId);
        if (!mounted) return;
        setServerStatus(result);
        if (result.status === 'completed') {
          complete = true;
          if (pollTimer) clearInterval(pollTimer);
        }
      } catch {
        // Keep polling; the local ride is already safely uploaded.
      } finally {
        inFlight = false;
      }
    };

    pollServerStatus();
    pollTimer = setInterval(pollServerStatus, POST_RIDE_SERVER_STATUS_POLL_MS);

    return () => {
      mounted = false;
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [isIncompleteRecording, serverRideId]);

  useEffect(() => {
    if (!serverRideId || isIncompleteRecording) return;
    let cancelled = false;
    void (async () => {
      try {
        const link = await api.resolveLink('ride', serverRideId);
        if (!cancelled) setResolvedLink(link);
      } catch {
        if (!cancelled) setResolvedLink(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isIncompleteRecording, serverRideId]);

  const handleDone = useCallback(() => {
    navigation.goBack();
  }, [navigation]);

  const handleViewRide = useCallback(() => {
    if (!serverRideId) return;
    (
      navigation as {
        navigate: (screen: string, params: { rideId?: string; serverRideId?: string; backLabel?: string }) => void;
      }
    ).navigate('RideDetail', { rideId, serverRideId, backLabel: 'Post Ride' });
  }, [navigation, rideId, serverRideId]);

  const handleShareRide = useCallback(async () => {
    if (!serverRideId || shareBusy) return;
    setShareBusy(true);
    try {
      const link = resolvedLink ?? await api.resolveLink('ride', serverRideId);
      setResolvedLink(link);
      await shareResolvedPayload(link.share);
    } catch {
      Alert.alert('Share failed', 'Please try again in a moment.');
    } finally {
      setShareBusy(false);
    }
  }, [resolvedLink, serverRideId, shareBusy]);

  const handlePickRidePhotos = useCallback(async () => {
    if (!serverRideId) {
      Alert.alert('Ride still uploading', 'Photos can be attached once the ride is accepted.');
      return;
    }
    if (photoBusy) return;
    const remainingSlots = Math.max(0, 6 - pendingPhotoUploads.length - uploadedMedia.length);
    if (remainingSlots === 0) {
      Alert.alert('Photo limit reached', 'Rides can have up to 6 photos.');
      return;
    }

    setPhotoBusy(true);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Photo access needed', 'Allow photo access to attach ride photos.');
        return;
      }
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsMultipleSelection: true,
        selectionLimit: remainingSlots,
        quality: 1,
        exif: false,
      });
      if (picked.canceled) return;
      const prepared: PreparedNativeImageUpload[] = [];
      for (const asset of picked.assets.slice(0, remainingSlots)) {
        prepared.push(await prepareNativeImageUpload(asset, {
          fileNamePrefix: `ride-${serverRideId}-photo`,
          maxDimension: 2048,
          maxBytes: 4 * 1024 * 1024,
        }));
      }
      setPendingPhotoUploads((current) => [...current, ...prepared]);
    } catch (err) {
      Alert.alert('Photo processing failed', err instanceof Error ? err.message : 'Please try another image.');
    } finally {
      setPhotoBusy(false);
    }
  }, [pendingPhotoUploads.length, photoBusy, serverRideId, uploadedMedia.length]);

  const handleUploadRidePhotos = useCallback(async () => {
    if (!serverRideId || pendingPhotoUploads.length === 0 || photoBusy) return;
    setPhotoBusy(true);
    try {
      const uploaded: RideMedia[] = [];
      for (const [index, file] of pendingPhotoUploads.entries()) {
        uploaded.push(await api.uploadRideMedia(serverRideId, file, uploadedMedia.length + index));
      }
      setUploadedMedia((current) => [...current, ...uploaded]);
      setPendingPhotoUploads([]);
      Alert.alert('Photos attached', `${uploaded.length} photo${uploaded.length === 1 ? '' : 's'} added to this ride.`);
    } catch (err) {
      Alert.alert('Photo upload failed', err instanceof Error ? err.message : 'Please try again.');
    } finally {
      setPhotoBusy(false);
    }
  }, [pendingPhotoUploads, photoBusy, serverRideId, uploadedMedia.length]);

  const handleOpenBoulderScan = useCallback(() => {
    void openResolvedBoulderScanTarget(resolvedLink);
  }, [resolvedLink]);

  const handleLifecycleAction = useCallback(async (action: RideLifecycleAction) => {
    if (lifecycleBusyAction) return;
    setLifecycleBusyAction(action);
    try {
      if (action === 'retry_upload') {
        retryFailedUpload(rideId);
        setUploadState('uploading');
        setUploadRetryVersion((version) => version + 1);
        return;
      }
      if (action === 'reauthenticate') {
        await logout();
        return;
      }
      if (action === 'retry_processing' && serverRideId) {
        await api.reprocessRide(serverRideId);
        setServerStatus((current) => current ? {
          ...current,
          status: 'processing',
          processingStage: 'processing',
          errorMessage: null,
          failure: null,
          canRetryProcessing: false,
        } : current);
        return;
      }
      if (action === 'open_ride') {
        handleViewRide();
      }
    } catch {
      Alert.alert('Ride action failed', 'Please try again in a moment.');
    } finally {
      setLifecycleBusyAction(null);
    }
  }, [handleViewRide, lifecycleBusyAction, rideId, serverRideId]);

  if (!localRide) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.loading}>
          <ActivityIndicator size="large" color="#c4a035" />
        </View>
      </SafeAreaView>
    );
  }

  const displayModel = buildPostRideDisplayModel({
    localRide,
    serverStatus,
    uploadState,
    serverRideId,
    resolvedLink,
    isIncomplete: isIncompleteRecording,
    incompleteReason: localIncompleteReason,
  });
  const lifecycle = deriveRideLifecycle({
    localRide: localLifecycleInputFromRide(localRide),
    uploadEntry: uploadLifecycleInputFromEntry(uploadEntry),
    serverStatus,
  });
  const uploadMessage = displayModel.uploadMessage;
  const recordRows = rideRecordRows(serverStatus);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.header}>{displayModel.headerTitle}</Text>

        {/* Upload status */}
        <View style={styles.uploadStatus}>
          {uploadMessage ? (
            <>
              {uploadMessage.showSpinner ? <ActivityIndicator size="small" color="#c4a035" /> : null}
              <Text style={[
                styles.uploadText,
                uploadMessage.tone === 'success' && styles.uploadSuccess,
                uploadMessage.tone === 'failed' && styles.uploadFailed,
              ]}>
                {uploadMessage.text}
              </Text>
            </>
          ) : null}
        </View>

        <RideLifecyclePanel
          view={lifecycle}
          busyAction={lifecycleBusyAction}
          onPressAction={handleLifecycleAction}
          testID="postride-lifecycle"
        />

        <PostRideCascadePanel cascade={cascade} />

        {__DEV__ && validationSummary && (
          <View style={styles.validationCard} testID="postride-validation-summary">
            <Text style={styles.validationTitle}>Ride checks</Text>
            <Text style={styles.validationLine}>
              saved in {validationSummary.stopToQueuedMs ?? 'n/a'} ms
            </Text>
            <Text style={styles.validationLine}>
              accepted in {validationSummary.stopToUploadedMs ?? 'n/a'} ms
              {validationSummary.uploadedWithinOneSecond === true ? ' ok' : ''}
            </Text>
            <Text style={styles.validationLine}>
              ride file {validationSummary.preliminaryHashPresent ? 'ready' : 'missing'} | format {validationSummary.parserVersionPresent ? 'ready' : 'missing'}
            </Text>
            <Text style={styles.validationLine}>
              upload request {validationSummary.uploadInitObserved ? 'seen' : 'pending'} | ride file {validationSummary.uploadInitHadPreliminaryHash ? 'sent' : 'not sent'} | format {validationSummary.uploadInitHadParserVersion ? 'sent' : 'not sent'}
            </Text>
            <Text style={styles.validationLine}>
              recovery {validationSummary.hadCrashRecovery ? 'recovered' : 'clean'} | gps rejects {Object.values(validationSummary.rejectedSamples).reduce((sum, count) => sum + count, 0)}
            </Text>
          </View>
        )}

        {/* Summary stats */}
        <View style={styles.summaryCard}>
          {displayModel.summaryRows.map((row) => (
            <View style={styles.summaryRow} key={row.map((item) => item.label).join('-')}>
              {row.map((item) => (
                <View style={styles.summaryItem} key={item.label}>
                  <Text style={styles.summaryValue}>{item.value}</Text>
                  <Text style={styles.summaryLabel}>{item.label}</Text>
                </View>
              ))}
            </View>
          ))}
        </View>

        {/* Server-side ride outcome. */}
        {displayModel.earnings ? (
          <View style={styles.earningsCard}>
            <Text style={styles.earningsValue}>{displayModel.earnings.value}</Text>
            <Text style={styles.earningsLabel}>{displayModel.earnings.label}</Text>
          </View>
        ) : null}

        <View style={styles.photoCard}>
          <View style={styles.photoHeader}>
            <View>
              <Text style={styles.photoTitle}>Photos</Text>
              <Text style={styles.photoSubtitle}>
                {uploadedMedia.length > 0
                  ? `${uploadedMedia.length} uploaded`
                  : pendingPhotoUploads.length > 0
                    ? `${pendingPhotoUploads.length} ready`
                    : serverRideId ? 'No photos yet' : 'Available after upload'}
              </Text>
            </View>
            {photoBusy ? <ActivityIndicator size="small" color="#c4a035" /> : null}
          </View>
          {(uploadedMedia.length > 0 || pendingPhotoUploads.length > 0) ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.photoStrip}>
              {uploadedMedia.map((item) => item.url ? (
                <Image key={item.id} source={{ uri: item.url }} style={styles.photoThumb} resizeMode="cover" />
              ) : null)}
              {pendingPhotoUploads.map((item) => (
                <Image key={item.uri} source={{ uri: item.uri }} style={[styles.photoThumb, styles.photoThumbPending]} resizeMode="cover" />
              ))}
            </ScrollView>
          ) : null}
          <View style={styles.photoActions}>
            <TouchableOpacity
              style={[styles.secondaryButton, (!serverRideId || photoBusy || pendingPhotoUploads.length + uploadedMedia.length >= 6) && styles.secondaryButtonDisabled]}
              onPress={handlePickRidePhotos}
              disabled={!serverRideId || photoBusy || pendingPhotoUploads.length + uploadedMedia.length >= 6}
            >
              <Text style={styles.secondaryButtonText}>Add photos</Text>
            </TouchableOpacity>
            {pendingPhotoUploads.length > 0 ? (
              <TouchableOpacity
                style={[styles.secondaryButton, photoBusy && styles.secondaryButtonDisabled]}
                onPress={handleUploadRidePhotos}
                disabled={photoBusy}
              >
                <Text style={styles.secondaryButtonText}>{photoBusy ? 'Uploading' : 'Upload photos'}</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>

        {recordRows.length > 0 ? (
          <View style={styles.proofCard}>
            {recordRows.map(([label, value]) => (
              <View style={styles.proofRow} key={label}>
                <Text style={styles.proofLabel}>{label}</Text>
                <Text style={styles.proofValue}>{value}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {displayModel.action ? (
          <View style={styles.actionCard}>
            <Text style={styles.actionTitle}>{displayModel.action.title}</Text>
            <View style={styles.actionRow}>
              <TouchableOpacity style={styles.secondaryButton} onPress={handleViewRide}>
                <Text style={styles.secondaryButtonText}>View ride</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.secondaryButton, shareBusy && styles.secondaryButtonDisabled]}
                onPress={handleShareRide}
                disabled={shareBusy}
              >
                <Text style={styles.secondaryButtonText}>{shareBusy ? 'Sharing' : 'Share'}</Text>
              </TouchableOpacity>
              {displayModel.action.boulderScanCtaLabel ? (
                <TouchableOpacity style={styles.secondaryButton} onPress={handleOpenBoulderScan}>
                  <Text style={styles.secondaryButtonText}>{displayModel.action.boulderScanCtaLabel}</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        ) : null}

        {/* Done button */}
        <TouchableOpacity style={styles.doneButton} onPress={handleDone}>
          <Text style={styles.doneButtonText}>Done</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scroll: {
    padding: 20,
  },
  header: {
    fontSize: 28,
    fontWeight: '700',
    color: '#e5e5e5',
    marginBottom: 16,
  },

  // Upload status
  uploadStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 20,
    gap: 8,
  },
  uploadText: {
    fontSize: 14,
    color: '#888',
  },
  uploadSuccess: {
    color: '#4ade80',
  },
  uploadFailed: {
    color: '#ef4444',
  },

  // Dev-only validation evidence
  validationCard: {
    backgroundColor: '#111',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#333',
    padding: 14,
    marginBottom: 16,
  },
  validationTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#c4a035',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  validationLine: {
    fontSize: 12,
    color: '#aaa',
    marginBottom: 4,
  },

  // Summary card
  summaryCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 20,
    marginBottom: 16,
  },
  summaryRow: {
    flexDirection: 'row',
    marginBottom: 16,
  },
  summaryItem: {
    flex: 1,
  },
  summaryValue: {
    fontSize: 22,
    fontWeight: '600',
    color: '#e5e5e5',
    marginBottom: 2,
  },
  summaryLabel: {
    fontSize: 12,
    color: '#666',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },

  // Earnings card
  earningsCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 20,
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#c4a035',
  },
  earningsValue: {
    fontSize: 36,
    fontWeight: '700',
    color: '#c4a035',
    marginBottom: 4,
  },
  earningsLabel: {
    fontSize: 14,
    color: '#888',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  photoCard: {
    backgroundColor: '#111',
    borderRadius: 10,
    padding: 14,
    marginBottom: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#252525',
    gap: 12,
  },
  photoHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  photoTitle: {
    color: '#ededed',
    fontSize: 15,
    fontWeight: '800',
  },
  photoSubtitle: {
    color: '#858585',
    fontSize: 12,
    marginTop: 2,
  },
  photoStrip: {
    gap: 10,
    paddingRight: 8,
  },
  photoThumb: {
    width: 96,
    height: 72,
    borderRadius: 8,
    backgroundColor: '#1a1a1a',
  },
  photoThumbPending: {
    opacity: 0.72,
  },
  photoActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  proofCard: {
    backgroundColor: '#111',
    borderRadius: 10,
    padding: 14,
    marginBottom: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#252525',
  },
  proofRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 16,
    paddingVertical: 5,
  },
  proofLabel: {
    color: '#999',
    fontSize: 13,
  },
  proofValue: {
    color: '#e5e5e5',
    fontSize: 13,
    fontWeight: '600',
    flexShrink: 1,
    textAlign: 'right',
  },
  actionCard: {
    backgroundColor: '#141414',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#2a2a2a',
    borderRadius: 10,
    padding: 16,
    marginBottom: 16,
  },
  actionTitle: {
    color: '#ededed',
    fontSize: 15,
    fontWeight: '700',
    marginBottom: 12,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  secondaryButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#3b3320',
    backgroundColor: '#171309',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  secondaryButtonDisabled: {
    opacity: 0.55,
  },
  secondaryButtonText: {
    color: '#d0af48',
    fontSize: 12,
    fontWeight: '700',
  },

  // Done button
  doneButton: {
    backgroundColor: '#222',
    borderRadius: 8,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  doneButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#e5e5e5',
  },
});
