import { ridePresentationFacts, formatRidePresentation } from '../../server/ride-card-shape';
import { RideRoomDoor } from '../components/auth/PublicRoomDoor';
import RideRoomLedger from '../components/ride/RideRoomLedger';
import { useBrowserTitleObject } from '../contexts/BrowserTitleContext';
import { FailureSheet } from '../components/portal/FailureSpecies';
import { RoomLoading, RideAnalysisSlots } from '../components/loading/RoomLoading';
import {
  useState,
  useMemo,
  useCallback,
  useRef,
  useEffect,
  Suspense,
  lazy,
  type ReactNode,
} from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { displayRideTitle } from '../lib/rideTitle';
import { useFormatters } from '../hooks/useFormatters';
import {
  ABSENT_VALUE,
  formatDateTime,
  formatFixed,
  formatInteger,
  formatSecondsLabel,
} from '../lib/formatters';
import type { ClimbData } from '../components/ride/climbData';
import {
  useRide,
  useRideStatus,
  useRidePatterns,
  useRideTelemetry,
  useRideGps,
} from '../hooks/queries';
import { queryKeys } from '../lib/queryKeys';
import {
  AlertTriangle,
  ArrowLeft,
  Trash2,
  Flag,
  Route,
  ShieldCheck,
  ExternalLink,
  Star,
  MessageCircle,
  Heart,
  ChevronLeft,
  ChevronRight,
  X,
  MoreHorizontal,
  Copy,
  Download,
} from 'lucide-react';
import { toast } from 'sonner';
import { LoadingRows } from '../components/loading/LoadingSystem';
import { cn } from '../components/ui/utils';
import {
  StateRow,
  PortalFrame,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
} from '../components/portal/PortalSpine';
import {
  api,
  Ride,
  RideInteractions,
  RideMedia,
  RideStatus,
  TruthSource,
  GpsPoint,
  ClimbPattern,
  TelemetryData,
  type RidePrivacyChoice,
} from '../lib/api';
import {
  buildEstimatedPowerStream,
  hasTelemetryStreamData,
} from '../lib/estimatedPower';
import { solanaExplorerUrl } from '../lib/solana';
import {
  getRideProofStateCopy,
  getRideProofUiState,
} from '../lib/protocolStates';
import type { RideProofUiState } from '../lib/protocolStates';
import {
  getPublicRiderDisplayName,
  getPublicRiderPath,
} from '../lib/riderIdentity';
import {
  buildDistanceSeries,
  calculateGradeAtIndex,
} from '../lib/rideTelemetry';
import {
  RideRoomIdentity,
  RideRoomGeography,
} from '../components/ride/RideRoom';
import {
  rideRoomModel,
  type RideSample,
} from '../components/ride/rideRoomModel';
import '../styles/portal-ride-room.css';
const RideAnalysisRoom = lazy(
  () => import('../components/ride/RideAnalysisRoom'),
);
import RidePrivacyControls from '../components/privacy/RidePrivacyControls';
import {
  parseRidePrivacyChoice,
  useRidePrivacy,
} from '../hooks/useRidePrivacy';
const DeleteConfirmModal = lazy(
  () => import('../components/modals/DeleteConfirmModal'),
);

const sortRideMedia = (media: RideMedia[]) =>
  [...media].sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));
const MAX_RIDE_MEDIA = 6;
const EMPTY_ROOM_TELEMETRY: TelemetryData = {
  gps: null,
  power: null,
  cadence: null,
  speed: null,
  heartRate: null,
  temperature: null,
};

type RideProofView = {
  visible: boolean;
  contractVersion?: string | null;
  truthSource?: TruthSource | null;
  status?: string | null;
  uiState: RideProofUiState;
  uiStateLabel: string;
  uiStateDetail: string;
  rideHash?: string | null;
  commitment?: string | null;
  attestationPda?: string | null;
  attestationTx?: string | null;
  creditTx?: string | null;
  calEarned?: number | null;
  dungEarned?: number | null;
  settlementWeek?: number | null;
  finalizedAt?: string | null;
  importSource?: string | null;
  importSourceId?: string | null;
  importQuality?: string | null;
  importTrackpoints?: number | null;
  importMaxGapS?: number | null;
  importFlags?: string[];
  effortSourceLabel?: string | null;
  thresholdEconomyState?: Ride['thresholdEconomyState'];
};

type RideWindowView = 'overview' | 'analysis' | 'log';

function hasText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function shortenProof(value?: string | null, chars = 6): string {
  if (!hasText(value)) return ABSENT_VALUE;
  if (value.length <= chars * 2 + 3) return value;
  return `${value.slice(0, chars)}...${value.slice(-chars)}`;
}

function formatProofLabel(value?: string | null): string {
  if (!hasText(value)) return ABSENT_VALUE;
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatProofNumber(value?: number | null): string {
  return formatInteger(value);
}

function formatProofInteger(value?: number | null): string {
  return formatInteger(value);
}

function formatImportSource(value?: string | null): string {
  if (!hasText(value)) return 'Ride file';
  return value
    .replace(/^strava_/, 'Strava ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function displayInitials(value: string): string {
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 'R';
  const first = words[0]?.[0] ?? '';
  const last =
    words.length > 1
      ? (words[words.length - 1]?.[0] ?? '')
      : (words[0]?.[1] ?? '');
  return `${first}${last}`.toUpperCase();
}

function formatSeconds(value?: number | null): string {
  return formatSecondsLabel(value);
}

function xmlEscape(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function stripGeneratedClimbNameSuffix(value: string): string {
  const trimmed = value.trim();
  return trimmed.replace(/\s+\d{10,13}$/, '').trim() || trimmed;
}

function getClimbDisplayName(climb: ClimbPattern): string {
  const candidates = [climb.vaultMatch?.name, climb.name, climb.roadName]
    .filter(
      (value): value is string =>
        typeof value === 'string' && value.trim().length > 0,
    )
    .map(stripGeneratedClimbNameSuffix);
  const namedCandidate = candidates.find(
    (value) => !/^climb\s*\(\s*[\d.]+\s*m\s*\)$/i.test(value.trim()),
  );
  return namedCandidate?.trim() || '';
}

function getClimbObjectHref(climb: ClimbData): string | null {
  if (climb.objectClimbId) {
    return `/climbs/${encodeURIComponent(climb.objectClimbId)}`;
  }
  return null;
}

function formatEffortSource(status: RideStatus | null, ride: Ride): string {
  const policy = status?.effortPolicy ?? null;
  const effortTier =
    policy?.effortEvidenceTier ?? ride.effortEvidenceTier ?? null;
  if (effortTier === 'power_verified') return 'Power';
  if (effortTier === 'sensor_supported') return 'Heart rate';
  if (effortTier === 'route_only') return 'GPS effort';
  if (effortTier === 'manual_review') return 'Review';

  const metrics = status?.metrics ?? null;
  const quality = status?.inputQuality ?? null;
  const powerCoverage = quality?.powerCoverage ?? null;
  const heartRateCoverage = quality?.heartRateCoverage ?? null;
  const hasPower =
    Boolean(
      ride.avgPowerW ||
        ride.normalizedPowerW ||
        metrics?.avgPowerW ||
        metrics?.normalizedPowerW,
    ) ||
    (typeof powerCoverage === 'number' && powerCoverage > 0);
  const hasHeartRate =
    typeof heartRateCoverage === 'number' && heartRateCoverage > 0;

  if (hasPower) return 'Power';
  if (hasHeartRate) return 'Heart rate';
  if (quality?.sensorDataState === 'absent' || powerCoverage === 0)
    return 'GPS effort';
  return 'Estimated';
}

function buildRideProofView(
  status: RideStatus | null,
  ride: Ride,
): RideProofView {
  const earnings = status?.earnings ?? ride.earnings ?? null;
  const settlement = earnings?.settlementStatus ?? null;
  const rideHash =
    status?.rideHashHex ??
    ride.rideHashHex ??
    status?.preliminaryRideHashHex ??
    ride.preliminaryRideHashHex ??
    null;
  const commitment =
    status?.attestationCommitmentHex ?? ride.attestationCommitmentHex ?? null;
  const attestationPda =
    status?.rideAttestationPda ?? ride.rideAttestationPda ?? null;
  const attestationTx =
    status?.rideAttestationTxSignature ??
    ride.rideAttestationTxSignature ??
    null;
  const creditTx = status?.txSignature ?? null;
  const importDiagnostics =
    status?.importDiagnostics ?? ride.importDiagnostics ?? null;
  const importSource =
    status?.importSource ??
    ride.importSource ??
    importDiagnostics?.importSource ??
    null;
  const finalizedAt =
    status?.finalizedAt ??
    ride.finalizedAt ??
    earnings?.finalizedAt ??
    settlement?.finalizedAt ??
    null;
  const rawStatus =
    status?.attestationStatus ??
    ride.attestationStatus ??
    status?.status ??
    null;
  const uiStateInput = {
    attestationStatus:
      status?.attestationStatus ?? ride.attestationStatus ?? null,
    status: status?.status ?? null,
    canonicalMatch: status?.canonicalMatch ?? ride.canonicalMatch ?? null,
    reviewReason: status?.reviewReason ?? ride.reviewReason ?? null,
    rewardPolicy:
      status?.effortPolicy?.rewardPolicy ?? ride.rewardPolicy ?? null,
    coveredEffortSeconds: status?.coveredEffortSeconds ?? ride.coveredEffortSeconds,
    paidEffortSeconds: status?.paidEffortSeconds ?? ride.paidEffortSeconds,
    errorMessage: status?.errorMessage ?? null,
    finalizedAt,
  };
  const uiState = getRideProofUiState(uiStateInput);
  const uiStateCopy = getRideProofStateCopy(uiStateInput);
  const thresholdEconomyState =
    status?.effortPolicy?.thresholdEconomyState ??
    ride.thresholdEconomyState ??
    null;

  const proofish =
    Boolean(status) ||
    hasText(rideHash) ||
    hasText(commitment) ||
    hasText(attestationPda) ||
    hasText(attestationTx) ||
    hasText(importSource) ||
    Boolean(earnings);

  return {
    visible: proofish,
    contractVersion:
      status?.contractVersion ??
      ride.contractVersion ??
      earnings?.contractVersion ??
      null,
    truthSource:
      status?.truthSource ?? ride.truthSource ?? earnings?.truthSource ?? null,
    status: rawStatus,
    uiState,
    uiStateLabel: uiStateCopy.label,
    uiStateDetail: uiStateCopy.detail,
    rideHash,
    commitment,
    attestationPda,
    attestationTx,
    creditTx,
    calEarned:
      thresholdEconomyState === 'held'
        ? null
        : (earnings?.calEarned ??
          status?.calEarned ??
          ride.calEarned ??
          status?.effortPolicy?.rewardableCal ??
          ride.rewardableCal ??
          null),
    thresholdEconomyState,
    dungEarned:
      earnings?.dungEarned ?? status?.dungMinted ?? ride.dungEarned ?? null,
    settlementWeek: settlement?.settlementWeek ?? settlement?.epoch ?? null,
    finalizedAt,
    importSource,
    importSourceId:
      status?.importSourceId ??
      ride.importSourceId ??
      importDiagnostics?.sourceActivityId ??
      null,
    importQuality: importDiagnostics?.qualityTier ?? null,
    importTrackpoints: importDiagnostics?.trackpointCount ?? null,
    importMaxGapS: importDiagnostics?.maxGapS ?? null,
    importFlags: importDiagnostics?.flags ?? [],
    effortSourceLabel: formatEffortSource(status, ride),
  };
}

export default function RideView() {
  const { activityId } = useParams<{ activityId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { isAuthenticated, user } = useAuth();
  const mediaFileInputRef = useRef<HTMLInputElement>(null);
  const formatters = useFormatters();
  const {
    distance: formatDistance,
    elevation: formatElevation,
    duration: formatDuration,
    integer: formatIntegerLabel,
    percent: formatPercent,
    watts: formatWatts,
    heartRate: formatHeartRate,
    cadence: formatCadence,
  } = formatters;

  // Core state - fetched via React Query
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showPrivacyModal, setShowPrivacyModal] = useState(false);
  const [privacyDraft, setPrivacyDraft] = useState<RidePrivacyChoice | null>(
    null,
  );
  const [isSavingPrivacy, setIsSavingPrivacy] = useState(false);
  const [rideActionsOpen, setRideActionsOpen] = useState<
    'masthead' | 'analysis' | null
  >(null);
  const privacyReturnFocusRef = useRef<HTMLElement | null>(null);
  const privacyCloseRef = useRef<HTMLButtonElement>(null);
  const privacyDialogRef = useRef<HTMLDivElement>(null);
  const privacySavingRef = useRef(false);
  const {
    data: ride = null,
    isLoading: rideLoading,
    error: rideError,
    refetch: refetchRide,
  } = useRide(activityId);
  useBrowserTitleObject(ride?.id === activityId ? ride.title || null : null);
  const { data: rideStatus = null } = useRideStatus(activityId);
  const { data: gpsData = null, isFetched: gpsFetched } =
    useRideGps(activityId);
  const { data: patterns = null } = useRidePatterns(activityId);
  const [rideInteractions, setRideInteractions] =
    useState<RideInteractions | null>(null);
  const [isReportingRide, setIsReportingRide] = useState(false);
  const [isMediaBusy, setIsMediaBusy] = useState(false);
  const [selectedMediaIndex, setSelectedMediaIndex] = useState(0);
  const [lightboxMediaIndex, setLightboxMediaIndex] = useState<number | null>(
    null,
  );

  const isLoading = rideLoading;
  const error = rideError
    ? rideError instanceof Error
      ? rideError.message
      : 'Failed to load ride'
    : null;

  // Pattern state
  const rideWindowView: RideWindowView = location.pathname.endsWith('/analysis')
    ? 'analysis'
    : location.pathname.endsWith('/log')
      ? 'log'
      : 'overview';
  const [climbRead, setClimbRead] = useState('Time');
  const [kudosBusy, setKudosBusy] = useState(false);

  const isRouteRedacted =
    Boolean(ride?.privacy?.redactGps) ||
    Boolean(gpsData?.gpsPoints?.some((point) => point.redacted === true));
  const shouldLoadAnalysisStreams =
    gpsFetched &&
    !isRouteRedacted &&
    (rideWindowView === 'analysis' ||
      Boolean(patterns?.patterns?.climbPatterns?.length));
  const { data: streamTelemetry = null } = useRideTelemetry(
    activityId,
    shouldLoadAnalysisStreams,
  );
  // Owner-only actions require either an API owner flag or an authenticated rider match.
  const isOwner =
    ride?.isOwner === true ||
    (!!ride?.riderId && !!user?.id && ride.riderId === user.id);
  const accountPrivacy = useRidePrivacy(isAuthenticated && isOwner);
  const { data: publicRiderProfile = null } = useQuery({
    queryKey: ['riders', 'public-profile', ride?.riderId],
    queryFn: () => api.getPublicProfile(ride!.riderId!),
    enabled: !isOwner && Boolean(ride?.riderId),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    let cancelled = false;
    if (!activityId) {
      setRideInteractions(null);
      return;
    }

    void api
      .getRideInteractions(activityId)
      .then((interactions) => {
        if (!cancelled) setRideInteractions(interactions);
      })
      .catch(() => {
        if (!cancelled) setRideInteractions(null);
      });

    return () => {
      cancelled = true;
    };
  }, [activityId, isOwner]);

  const rideProof = useMemo(
    () => (ride ? buildRideProofView(rideStatus, ride) : null),
    [rideStatus, ride],
  );
  const telemetry = useMemo<TelemetryData>(
    () => ({
      gps: gpsData,
      power: streamTelemetry?.power ?? null,
      heartRate: streamTelemetry?.heartRate ?? null,
      cadence: streamTelemetry?.cadence ?? null,
      speed: streamTelemetry?.speed ?? null,
      temperature: streamTelemetry?.temperature ?? null,
    }),
    [gpsData, streamTelemetry],
  );

  // Extract GPS points
  const gpsPoints: GpsPoint[] = useMemo(() => {
    return telemetry?.gps?.gpsPoints || [];
  }, [telemetry]);
  const gpsDistances = useMemo(
    () => buildDistanceSeries(gpsPoints),
    [gpsPoints],
  );

  // Get climb patterns
  const climbPatterns: ClimbPattern[] = useMemo(() => {
    return patterns?.patterns?.climbPatterns || [];
  }, [patterns]);
  // Convert patterns to ClimbData for the ride ledger (with extended data for vault creation)
  const climbs: ClimbData[] = useMemo(() => {
    return climbPatterns.map((c, i) => {
      const effortBounds = c.matchTrace?.detection?.effortBounds;
      const detectedStartOffset = Number.isFinite(effortBounds?.[0])
        ? effortBounds?.[0]
        : undefined;
      const detectedEndOffset = Number.isFinite(effortBounds?.[1])
        ? effortBounds?.[1]
        : undefined;
      const startOffset =
        c.startOffsetS ?? c.startTimeOffsetS ?? detectedStartOffset;
      const endOffset = c.endOffsetS ?? c.endTimeOffsetS ?? detectedEndOffset;
      const canonicalClimbId =
        c.climbId || c.vaultMatch?.vaultClimbId || undefined;

      return {
        id: canonicalClimbId || `climb-${i}`,
        objectClimbId: canonicalClimbId,
        name: getClimbDisplayName(c),
        distanceM: c.distanceM || 0,
        elevationM: c.vertM || 0,
        avgGradient: c.avgGradientPct || 0,
        category: c.category,
        timeS: c.durationS || 0,
        avgSpeedKmh: c.avgSpeedMps ? c.avgSpeedMps * 3.6 : undefined,
        vam: c.vam,
        startIndex: c.startIdx,
        endIndex: c.endIdx,
        startOffsetS: startOffset,
        endOffsetS: endOffset,
        vaultMatched: !!c.vaultMatch,
        // Extended data for vault creation flow
        signatureHex: c.signatureHex,
        roadName: c.roadName,
        tileCount: c.tileIds?.length,
        vaultMatch: c.vaultMatch
          ? {
              ...c.vaultMatch,
              isPR:
                c.vaultMatch.isPR ??
                (c.vaultMatch as typeof c.vaultMatch & { isPr?: boolean }).isPr,
              name: c.vaultMatch.name
                ? stripGeneratedClimbNameSuffix(c.vaultMatch.name)
                : c.vaultMatch.name,
            }
          : undefined,
      };
    });
  }, [climbPatterns]);

  const handleDelete = async () => {
    if (!activityId) return;
    try {
      await api.deleteRide(activityId);
      toast.success('Activity deleted');
      navigate('/');
    } catch {
      toast.error('Could not delete activity');
    }
  };

  const handleReportRide = async () => {
    if (!activityId || isReportingRide || rideInteractions?.viewerReported)
      return;

    try {
      setIsReportingRide(true);
      const report = await api.reportSocialContent(
        'ride',
        activityId,
        'other',
        'Reported from portal ride detail',
      );
      setRideInteractions((current) => ({
        rideId: activityId,
        kudosCount: current?.kudosCount ?? 0,
        commentCount: current?.commentCount ?? 0,
        viewerHasKudos: current?.viewerHasKudos ?? false,
        commentsEnabled: current?.commentsEnabled ?? true,
        canComment: current?.canComment ?? false,
        ...(current ?? {}),
        viewerReported: true,
        reportStatus: report.status,
      }));
      toast.success('Report sent');
    } catch {
      toast.error('Could not report ride');
    } finally {
      setIsReportingRide(false);
    }
  };

  const visibleRideMedia = useMemo(
    () =>
      sortRideMedia(
        Array.isArray(ride?.media) ? ride.media.filter((item) => item.url) : [],
      ),
    [ride?.media],
  );

  useEffect(() => {
    if (visibleRideMedia.length === 0) {
      if (selectedMediaIndex !== 0) setSelectedMediaIndex(0);
      if (lightboxMediaIndex !== null) setLightboxMediaIndex(null);
      return;
    }

    if (selectedMediaIndex >= visibleRideMedia.length) {
      setSelectedMediaIndex(visibleRideMedia.length - 1);
    }
    if (
      lightboxMediaIndex !== null &&
      lightboxMediaIndex >= visibleRideMedia.length
    ) {
      setLightboxMediaIndex(visibleRideMedia.length - 1);
    }
  }, [lightboxMediaIndex, selectedMediaIndex, visibleRideMedia.length]);

  const replaceRideMedia = useCallback(
    (nextMedia: RideMedia[]) => {
      if (!activityId) return;
      const normalized = sortRideMedia(nextMedia);
      queryClient.setQueryData<Ride>(
        queryKeys.rides.detail(activityId),
        (current) => {
          if (!current) return current;
          return { ...current, media: normalized };
        },
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.rides.all });
      void queryClient.invalidateQueries({ queryKey: ['feed'] });
    },
    [activityId, queryClient],
  );

  const handleRideMediaFilesSelected = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.currentTarget.files ?? []);
      event.currentTarget.value = '';
      if (!activityId || files.length === 0 || isMediaBusy) return;

      const remainingSlots = Math.max(
        0,
        MAX_RIDE_MEDIA - visibleRideMedia.length,
      );
      const filesToUpload = files.slice(0, remainingSlots);
      if (filesToUpload.length === 0) {
        toast.error(`Ride can hold ${formatInteger(MAX_RIDE_MEDIA)} photos`);
        return;
      }

      try {
        setIsMediaBusy(true);
        const uploaded: RideMedia[] = [];
        for (const [index, file] of filesToUpload.entries()) {
          uploaded.push(
            await api.uploadRideMedia(
              activityId,
              file,
              visibleRideMedia.length + index,
            ),
          );
        }
        const nextMedia = sortRideMedia([...visibleRideMedia, ...uploaded]);
        replaceRideMedia(nextMedia);
        setSelectedMediaIndex(Math.max(0, nextMedia.length - uploaded.length));
        toast.success(uploaded.length === 1 ? 'Photo added' : 'Photos added');
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : 'Could not add photos',
        );
      } finally {
        setIsMediaBusy(false);
      }
    },
    [activityId, isMediaBusy, replaceRideMedia, visibleRideMedia],
  );

  const handleSetRideMediaCover = useCallback(
    async (mediaId: string) => {
      if (!activityId || isMediaBusy) return;
      try {
        setIsMediaBusy(true);
        const updated = await api.updateRideMedia(activityId, mediaId, {
          role: 'cover',
        });
        replaceRideMedia(
          visibleRideMedia.map((item) =>
            item.id === mediaId ? updated : { ...item, role: 'photo' as const },
          ),
        );
        toast.success('Cover updated');
      } catch {
        toast.error('Could not update cover');
      } finally {
        setIsMediaBusy(false);
      }
    },
    [activityId, isMediaBusy, replaceRideMedia, visibleRideMedia],
  );

  const handleDeleteRideMedia = useCallback(
    async (mediaId: string) => {
      if (!activityId || isMediaBusy) return;
      try {
        setIsMediaBusy(true);
        await api.deleteRideMedia(activityId, mediaId);
        const remaining = visibleRideMedia.filter(
          (item) => item.id !== mediaId,
        );
        const normalized = remaining.map((item, index) => ({
          ...item,
          sortOrder: index,
          role: remaining.some((candidate) => candidate.role === 'cover')
            ? item.role
            : index === 0
              ? ('cover' as const)
              : ('photo' as const),
        }));
        replaceRideMedia(normalized);
        setSelectedMediaIndex((current) =>
          Math.min(current, Math.max(0, normalized.length - 1)),
        );
        toast.success('Photo deleted');
      } catch {
        toast.error('Could not delete photo');
      } finally {
        setIsMediaBusy(false);
      }
    },
    [activityId, isMediaBusy, replaceRideMedia, visibleRideMedia],
  );

  const handleReportRideMedia = useCallback(
    async (mediaId: string) => {
      if (isMediaBusy) return;
      try {
        setIsMediaBusy(true);
        await api.reportSocialContent(
          'ride_media',
          mediaId,
          'other',
          'Reported from portal ride photo',
        );
        toast.success('Report sent');
      } catch {
        toast.error('Could not report photo');
      } finally {
        setIsMediaBusy(false);
      }
    },
    [isMediaBusy],
  );

  useEffect(() => {
    if (!rideActionsOpen) return undefined;

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (target?.closest('.ride-detail-actions-popover')) return;
      setRideActionsOpen(null);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setRideActionsOpen(null);
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [rideActionsOpen]);

  useEffect(() => {
    privacySavingRef.current = isSavingPrivacy;
  }, [isSavingPrivacy]);

  useEffect(() => {
    if (!showPrivacyModal) return undefined;

    const priorOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !privacySavingRef.current) {
        setShowPrivacyModal(false);
        setPrivacyDraft(null);
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = privacyDialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), textarea, input:not(:disabled), select:not(:disabled)',
      );
      const first = focusable?.[0];
      const last = focusable?.[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const focusFrame = window.requestAnimationFrame(() =>
      privacyCloseRef.current?.focus(),
    );

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = priorOverflow;
      document.removeEventListener('keydown', handleKeyDown);
      privacyReturnFocusRef.current?.focus();
    };
  }, [showPrivacyModal]);

  // Loading state
  const roomPower = useMemo(
    () =>
      hasTelemetryStreamData(telemetry.power) ||
      isRouteRedacted ||
      rideWindowView !== 'analysis'
        ? null
        : buildEstimatedPowerStream({
            rideId: activityId,
            points: gpsPoints,
            speedStream: telemetry.speed,
            rideDurationS: ride?.durationS ?? null,
          }),
    [
      telemetry.power,
      telemetry.speed,
      gpsPoints,
      activityId,
      isRouteRedacted,
      rideWindowView,
      ride?.durationS,
    ],
  );
  const roomModel = useMemo(
    () =>
      rideRoomModel(
        gpsPoints,
        isRouteRedacted
          ? {
              gps: null,
              power: null,
              cadence: null,
              speed: null,
              heartRate: null,
              temperature: null,
            }
          : {
              ...telemetry,
              power: hasTelemetryStreamData(telemetry.power)
                ? telemetry.power
                : roomPower,
            },
        climbPatterns,
        ride?.startedAt ?? '',
      ),
    [
      gpsPoints,
      telemetry,
      roomPower,
      climbPatterns,
      ride?.startedAt,
      isRouteRedacted,
    ],
  );
  // Stream arrival must not replace the map or discard a rider's camera.
  const geographyModel = useMemo(
    () =>
      rideRoomModel(
        gpsPoints,
        EMPTY_ROOM_TELEMETRY,
        climbPatterns,
        ride?.startedAt ?? '',
      ),
    [gpsPoints, climbPatterns, ride?.startedAt],
  );
  const refreshInteractions = useCallback(() => {
    if (activityId)
      void api
        .getRideInteractions(activityId)
        .then(setRideInteractions)
        .catch(() => {});
  }, [activityId]);

  if (isLoading) return <RoomLoading />;

  if (error || !ride) {
    const isNotFound = /404|not.?found/i.test(error ?? '') || (!error && !ride);
    if (isNotFound) return <FailureSheet title="Ride not found" description="This ride is not in your log anymore." doors={[{ label: 'Rides', href: '/profile?tab=rides' }]} />;
    return <div className="portal-object-page portal-object-page--ride" data-object-page="ride"><RideRoomGeography samples={[]} spans={[]} power={[]} identity={<StateRow title="Could not open this ride." action={<button type="button" onClick={() => void refetchRide()}>Try again</button>} />} children={null} /></div>;
  }

  const rideStartedLabel = formatDateTime(ride.startedAt);
  const presentationFacts = ridePresentationFacts(ride, ride.id, isOwner ? 'owner' : 'public');
  const presentationText = formatRidePresentation(presentationFacts, formatters);
  const riderProfile = isOwner
    ? {
        id: user?.id,
        username: user?.username,
        displayName: user?.displayName,
        wallet: user?.wallet,
      }
    : publicRiderProfile;
  const riderDisplayName = isOwner
    ? user?.displayName || user?.username || 'You'
    : riderProfile
      ? getPublicRiderDisplayName(riderProfile)
      : 'Rider';
  const riderProfileHref = isOwner
    ? '/profile'
    : getPublicRiderPath(riderProfile ?? { userId: ride.riderId });
  const riderAvatarUrl = isOwner
    ? (user?.avatarUrl ?? null)
    : (publicRiderProfile?.avatarUrl ?? null);
  const riderInitials = displayInitials(riderDisplayName);
  const currentRidePrivacyChoice = parseRidePrivacyChoice(ride.privacy);
  const rideMedia = visibleRideMedia;
  const coverMedia =
    rideMedia.find((item) => item.role === 'cover') ?? rideMedia[0] ?? null;
  const selectedMedia = rideMedia[selectedMediaIndex] ?? coverMedia;
  const lightboxMedia =
    lightboxMediaIndex !== null ? rideMedia[lightboxMediaIndex] : null;
  const rideShareUrl =
    typeof window !== 'undefined'
      ? `${window.location.origin}/activities/${activityId}`
      : `/activities/${activityId}`;

  const handleCopyRideLink = async () => {
    try {
      await navigator.clipboard.writeText(rideShareUrl);
      toast.success('Ride link copied');
    } catch {
      toast.error('Could not copy ride link');
    } finally {
      setRideActionsOpen(null);
    }
  };

  const openPrivacyEditor = () => {
    if (!currentRidePrivacyChoice || !accountPrivacy.settings) {
      toast.error('Privacy settings unavailable. Try again.');
      return;
    }
    const activeElement =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    privacyReturnFocusRef.current =
      activeElement
        ?.closest('.ride-detail-actions-popover')
        ?.querySelector<HTMLElement>(
          'button[aria-label="More ride actions"]',
        ) ?? activeElement;
    setPrivacyDraft({ ...currentRidePrivacyChoice });
    setRideActionsOpen(null);
    setShowPrivacyModal(true);
  };

  const saveRidePrivacy = async () => {
    if (!activityId || !privacyDraft || !accountPrivacy.settings) return;
    setIsSavingPrivacy(true);
    try {
      await api.updateRide(activityId, privacyDraft);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.rides.detail(activityId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.rides.gps(activityId),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.rides.all }),
        queryClient.invalidateQueries({ queryKey: ['feed'] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.climbs.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.vaults.all }),
        queryClient.invalidateQueries({ queryKey: ['publicPreview'] }),
      ]);
      setShowPrivacyModal(false);
      setPrivacyDraft(null);
      toast.success('Ride privacy saved');
    } catch {
      toast.error('Could not save ride privacy');
    } finally {
      setIsSavingPrivacy(false);
    }
  };

  const hasRenderableGpsRoute = gpsPoints.some(
    (p, i) =>
      i > 0 &&
      !p.redacted &&
      !gpsPoints[i - 1].redacted &&
      Number.isFinite(p.latitude) &&
      Number.isFinite(p.longitude) &&
      Number.isFinite(gpsPoints[i - 1].latitude) &&
      Number.isFinite(gpsPoints[i - 1].longitude),
  );
  const handleExportRideGpx = () => {
    if (!hasRenderableGpsRoute) {
      toast.error('Route GPS is not available for export');
      return;
    }

    const trackSegments: string[] = [];
    let currentSegment: string[] = [];
    const flushSegment = () => {
      if (currentSegment.length > 0) {
        trackSegments.push(`<trkseg>${currentSegment.join('')}</trkseg>`);
        currentSegment = [];
      }
    };

    gpsPoints.forEach((point) => {
      if (
        point.redacted === true ||
        !Number.isFinite(point.latitude) ||
        !Number.isFinite(point.longitude)
      ) {
        flushSegment();
        return;
      }
      const elevation =
        typeof point.elevationM === 'number' &&
        Number.isFinite(point.elevationM)
          ? `<ele>${formatFixed(point.elevationM, 1)}</ele>`
          : '';
      const time = point.timestamp
        ? `<time>${xmlEscape(String(point.timestamp))}</time>`
        : '';
      currentSegment.push(
        `<trkpt lat="${point.latitude}" lon="${point.longitude}">${elevation}${time}</trkpt>`,
      );
    });
    flushSegment();

    if (trackSegments.length === 0) {
      toast.error('Route GPS is not available for export');
      return;
    }

    const gpx = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="BoulderRoller" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>${xmlEscape(ride.title || 'BoulderRoller ride')}</name>${trackSegments.join('')}</trk></gpx>\n`;
    const blob = new Blob([gpx], { type: 'application/gpx+xml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    // Preserve the shared formatter gate's technical filename waiver.
    // prettier-ignore
    const filename = (ride.title || ride.id || 'boulderroller-ride').replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase() || 'boulderroller-ride';
    link.download = `${filename}.gpx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setRideActionsOpen(null);
    toast.success('GPX export started');
  };

  const renderMoreRideActions = (placement: 'masthead' | 'analysis') => {
    const isActionsOpen = rideActionsOpen === placement;

    return (
      <div className="ride-detail-actions-popover">
        <button
          type="button"
          className={cn(
            'ride-detail-icon-button',
            isActionsOpen && 'ride-detail-icon-button--active',
          )}
          onClick={() =>
            setRideActionsOpen((current) =>
              current === placement ? null : placement,
            )
          }
          aria-haspopup="menu"
          aria-expanded={isActionsOpen}
          aria-label="More ride actions"
          title="More ride actions"
        >
          <MoreHorizontal size={17} aria-hidden="true" />
        </button>
        {isActionsOpen && (
          <div
            className="ride-detail-actions-menu"
            role="menu"
            aria-label="More ride actions"
          >
            <button
              type="button"
              role="menuitem"
              className="ride-detail-actions-menu__item"
              onClick={handleCopyRideLink}
            >
              <Copy size={14} aria-hidden="true" />
              <span>Copy ride link</span>
            </button>
            {isOwner && (
              <button
                type="button"
                role="menuitem"
                className="ride-detail-actions-menu__item"
                onClick={openPrivacyEditor}
              >
                <ShieldCheck size={14} aria-hidden="true" />
                <span>Edit privacy</span>
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              className="ride-detail-actions-menu__item"
              onClick={handleExportRideGpx}
            >
              <Download size={14} aria-hidden="true" />
              <span>Export GPX</span>
            </button>
            {isOwner ? (
              <button
                type="button"
                role="menuitem"
                className="ride-detail-actions-menu__item ride-detail-actions-menu__item--danger"
                onClick={() => {
                  setShowDeleteModal(true);
                  setRideActionsOpen(null);
                }}
              >
                <Trash2 size={14} aria-hidden="true" />
                <span>Delete ride</span>
              </button>
            ) : (
              <button
                type="button"
                role="menuitem"
                className="ride-detail-actions-menu__item"
                onClick={() => {
                  void handleReportRide();
                  setRideActionsOpen(null);
                }}
                disabled={isReportingRide || rideInteractions?.viewerReported}
              >
                <Flag size={14} aria-hidden="true" />
                <span>
                  {rideInteractions?.viewerReported
                    ? 'Reported'
                    : isReportingRide
                      ? 'Reporting'
                      : 'Report ride'}
                </span>
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  const formatClimbGrade = (selectedClimb: ClimbData) =>
    formatPercent(selectedClimb.avgGradient);
  const formatRoomReadout = (sample: RideSample | undefined) => {
    const activePointPower = sample?.power;
    const activePointHeartRate = sample?.heartRate;
    const activePointCadence = sample?.cadence;
    const activePointGrade = sample
      ? calculateGradeAtIndex(gpsPoints, gpsDistances, sample.index)
      : null;
    return {
      power: formatWatts(activePointPower),
      heartRate: formatHeartRate(activePointHeartRate),
      cadence: formatCadence(activePointCadence),
      grade: formatPercent(activePointGrade),
      elevation: formatters.meters(sample?.elevation),
      speed: formatters.speedKmh(sample?.speed),
    };
  };
  const roomTitle = displayRideTitle(
    ride.title,
    ride.startedAt,
    ride.routePreview?.placeLabel,
  );
  const roomCal =
    rideProof?.thresholdEconomyState === 'held'
      ? null
      : (rideProof?.calEarned ?? ride.calEarned);
  const roomCalText = roomCal == null ? ABSENT_VALUE : formatInteger(roomCal);
  const roomSummary = [
    patterns
      ? `${formatInteger(climbs.length)} climb${climbs.length === 1 ? '' : 's'}`
      : '',
    climbs.some((c) => c.vaultMatch?.isPR)
      ? `${formatInteger(climbs.filter((c) => c.vaultMatch?.isPR).length)} new best`
      : '',
    roomCal == null ? '' : `${roomCalText} CAL`,
  ]
    .filter(Boolean)
    .join(' · ');
  const roomProfile = roomModel.samples
    .filter((p) => p.elevation !== null)
    .map((p) => ({ distanceM: p.d, elevationM: p.elevation! }));
  const roomCounted = roomModel.spans.flatMap((span) => {
    const points = roomModel.samples.filter(
      (p) => p.t >= span.start && p.t <= span.end,
    );
    return points.length > 1
      ? [
          {
            startDistanceM: points[0].d,
            endDistanceM: points[points.length - 1].d,
          },
        ]
      : [];
  });
  const jumpToSocial = () =>
    document
      .getElementById('ride-social')
      ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  const toggleKudos = async () => {
    if (!activityId || !rideInteractions || kudosBusy || isOwner) return;
    setKudosBusy(true);
    try {
      await (rideInteractions.viewerHasKudos
        ? api.removeKudos(activityId)
        : api.giveKudos(activityId));
      setRideInteractions(await api.getRideInteractions(activityId));
    } catch {
      refreshInteractions();
    } finally {
      setKudosBusy(false);
    }
  };
  const identity = (
    <RideRoomIdentity
      riderProfileHref={riderProfileHref}
      riderDisplayName={riderDisplayName}
      riderAvatarUrl={riderAvatarUrl}
      riderInitials={riderInitials}
      rideStartedLabel={rideStartedLabel}
      placeLabel={ride.routePreview?.placeLabel}
      roomTitle={roomTitle}
      profile={roomProfile.length ? roomProfile : ride.elevationProfile}
      spans={roomProfile.length ? roomCounted : ride.countedSpans}
      stats={[
        ['Distance', presentationText.distance],
        ['Elevation', presentationText.elevation],
        ['Time', presentationText.time],
      ]}
      roomSummary={roomSummary}
      actions={renderMoreRideActions('masthead')}
      social={
        <div className="ride-room-social-footer">
          <button onClick={jumpToSocial}>
            {rideInteractions
              ? `${formatIntegerLabel(rideInteractions.kudosCount)} kudos`
              : ABSENT_VALUE}
          </button>
          <button onClick={jumpToSocial} aria-label="Comments">
            <MessageCircle size={16} />
            <span>
              {rideInteractions
                ? formatInteger(rideInteractions.commentCount)
                : ABSENT_VALUE}
            </span>
          </button>
        </div>
      }
    />
  );
  return (
    <PortalPage
      className="ride-detail-page ride-room-page portal-object-page portal-object-page--ride"
      data-object-page="ride"
    >
      <input
        ref={mediaFileInputRef}
        className="ride-detail-overview__file-input"
        type="file"
        accept="image/*"
        multiple
        onChange={handleRideMediaFilesSelected}
      />
      {rideWindowView === 'overview' ? (
        <RideRoomGeography
          samples={geographyModel.samples}
          spans={geographyModel.spans}
          power={roomModel.streams.power}
          identity={identity}
        >
          <RideRoomDoor href={`/activities/${activityId}/analysis`} />
          <RideRoomLedger
            climbRead={climbRead}
            setClimbRead={setClimbRead}
            climbs={climbs}
            getClimbObjectHref={getClimbObjectHref}
            roomModel={roomModel}
            climbPatterns={climbPatterns}
            formatDistance={formatDistance}
            formatElevation={formatElevation}
            formatClimbGrade={formatClimbGrade}
            formatDuration={formatDuration}
            formatWatts={formatWatts}
            formatIntegerLabel={formatIntegerLabel}
            rideInteractions={rideInteractions}
            kudosBusy={kudosBusy}
            isOwner={isOwner}
            toggleKudos={toggleKudos}
            activityId={activityId}
            refreshInteractions={refreshInteractions}
            mediaFileInputRef={mediaFileInputRef}
            isMediaBusy={isMediaBusy}
            rideMedia={rideMedia}
            selectedMedia={selectedMedia}
            setLightboxMediaIndex={setLightboxMediaIndex}
            selectedMediaIndex={selectedMediaIndex}
            ride={ride}
            setSelectedMediaIndex={setSelectedMediaIndex}
            handleSetRideMediaCover={handleSetRideMediaCover}
            handleDeleteRideMedia={handleDeleteRideMedia}
            handleReportRideMedia={handleReportRideMedia}
            roomCalText={roomCalText}
            roomCal={roomCal}
          />
        </RideRoomGeography>
      ) : rideWindowView === 'analysis' ? (
        <div data-object-layer="ride-stats">
          <Suspense fallback={<RideAnalysisSlots />}>
            <RideAnalysisRoom
              ride={ride}
              model={
                isRouteRedacted ? { ...roomModel, samples: [] } : roomModel
              }
              isOwner={isOwner}
              ownerId={user?.id ?? null}
              title={roomTitle}
              rider={riderDisplayName}
              date={rideStartedLabel}
              estimated={!!roomPower}
              formatReadout={formatRoomReadout}
            />
          </Suspense>
        </div>
      ) : (
        <div className="ride-room-log" data-object-layer="ride-record-proof">
          <Link className="ride-analysis-back" to={`/activities/${activityId}`}>
            <span>‹</span>
            <b>{roomTitle}</b>
          </Link>
          <h1>Ride log</h1>
          {rideProof?.visible && <ProtocolProofCard proof={rideProof} />}
        </div>
      )}

      {lightboxMedia && lightboxMediaIndex !== null && (
        <div
          className="ride-detail-photo-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Ride photo"
          onClick={() => setLightboxMediaIndex(null)}
        >
          <div
            className="ride-detail-photo-lightbox__frame"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="ride-detail-photo-lightbox__close"
              onClick={() => setLightboxMediaIndex(null)}
              title="Close photo"
              aria-label="Close photo"
            >
              <X size={18} aria-hidden="true" />
            </button>
            {rideMedia.length > 1 && (
              <button
                type="button"
                className="ride-detail-photo-lightbox__nav ride-detail-photo-lightbox__nav--prev"
                onClick={() =>
                  setLightboxMediaIndex((current) =>
                    current === null || current === 0
                      ? rideMedia.length - 1
                      : current - 1,
                  )
                }
                title="Previous photo"
                aria-label="Previous photo"
              >
                <ChevronLeft size={20} aria-hidden="true" />
              </button>
            )}
            <img
              src={lightboxMedia.url || ''}
              alt={lightboxMedia.fileName || `${ride.title || 'Ride'} photo`}
              className="ride-detail-photo-lightbox__image"
            />
            {rideMedia.length > 1 && (
              <button
                type="button"
                className="ride-detail-photo-lightbox__nav ride-detail-photo-lightbox__nav--next"
                onClick={() =>
                  setLightboxMediaIndex((current) =>
                    current === null || current >= rideMedia.length - 1
                      ? 0
                      : current + 1,
                  )
                }
                title="Next photo"
                aria-label="Next photo"
              >
                <ChevronRight size={20} aria-hidden="true" />
              </button>
            )}
            {rideMedia.length > 1 && (
              <div className="ride-detail-photo-lightbox__count">
                {formatInteger(lightboxMediaIndex + 1)}/
                {formatInteger(rideMedia.length)}
              </div>
            )}
          </div>
        </div>
      )}

      {showPrivacyModal && privacyDraft && (
        <div className="ride-privacy-edit-overlay">
          <div
            ref={privacyDialogRef}
            className="ride-privacy-edit-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ride-privacy-edit-title"
          >
            <header className="ride-privacy-edit-modal__header">
              <div>
                <h2 id="ride-privacy-edit-title">Edit ride privacy</h2>
                <p>This changes this ride only.</p>
              </div>
              <button
                ref={privacyCloseRef}
                type="button"
                onClick={() => {
                  setShowPrivacyModal(false);
                  setPrivacyDraft(null);
                }}
                disabled={isSavingPrivacy}
                aria-label="Close ride privacy"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </header>
            <RidePrivacyControls
              value={privacyDraft}
              onChange={setPrivacyDraft}
              privacyZoneCount={accountPrivacy.settings?.privacyZoneCount ?? 0}
              disabled={isSavingPrivacy || !accountPrivacy.settings}
              idPrefix="ride-edit-privacy"
            />
            <footer className="ride-privacy-edit-modal__actions">
              <button
                type="button"
                className="portal-sort-button"
                onClick={() => {
                  setShowPrivacyModal(false);
                  setPrivacyDraft(null);
                }}
                disabled={isSavingPrivacy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="portal-action-button"
                onClick={() => void saveRidePrivacy()}
                disabled={isSavingPrivacy || !accountPrivacy.settings}
              >
                {isSavingPrivacy ? 'Saving' : 'Save privacy'}
              </button>
            </footer>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {showDeleteModal && ride && (
        <Suspense fallback={null}>
          <DeleteConfirmModal
            activity={{
              id: ride.id,
              title: ride.title || 'Ride',
              date: formatters.date(ride.startedAt),
              distance: formatDistance(ride.distanceM),
              rewardValue: ride.calEarned ?? ride.dungEarned ?? 0,
              rewardAsset:
                ride.calEarned !== undefined && ride.calEarned !== null
                  ? 'CAL'
                  : 'DUNG',
            }}
            onClose={() => setShowDeleteModal(false)}
            onConfirm={handleDelete}
          />
        </Suspense>
      )}
    </PortalPage>
  );
}

// ============================================
// HELPER COMPONENTS
// ============================================

function ProtocolProofCard({ proof }: { proof: RideProofView }) {
  const hasFileDetails = Boolean(
    proof.importSourceId ||
      proof.importQuality ||
      proof.importTrackpoints ||
      proof.importMaxGapS ||
      (proof.importFlags?.length ?? 0) > 0,
  );

  return (
    <div className="ride-detail-section">
      <PortalPanel className="ride-detail-proof-panel" aria-label="Ride log">
        <PortalPanelBody className="ride-detail-proof">
          <div className="ride-detail-proof-header">
            <div className="ride-detail-proof-heading">
              <ShieldCheck size={18} className="ride-detail-proof-icon" />
              <div>
                <h2 className="ride-detail-proof-title">Verification</h2>
                <p className="ride-detail-proof-copy">File, effort, and CAL.</p>
              </div>
            </div>
            <div className="ride-detail-proof-chip-row">
              <span className="ride-detail-proof-chip">
                {proof.uiStateLabel}
              </span>
              <span className="ride-detail-proof-chip">
                {formatImportSource(proof.importSource)}
              </span>
            </div>
          </div>

          <div className="ride-detail-proof-grid ride-detail-proof-grid--summary">
            <ProofDatum
              label="Status"
              value={proof.uiStateLabel}
              valueFamily="sans"
            />
            {proof.thresholdEconomyState === 'held' ? (
              <ProofDatum label="CAL" value="Held" valueFamily="sans" />
            ) : (
              <ProofDatum
                label="Counted CAL"
                value={formatProofNumber(proof.calEarned)}
                valueFamily="mono"
                accent
              />
            )}
            <ProofDatum
              label="Effort"
              value={proof.effortSourceLabel ?? 'Estimated'}
              valueFamily="sans"
            />
            <ProofDatum
              label="Week"
              value={formatProofInteger(proof.settlementWeek)}
              valueFamily="mono"
            />
          </div>

          <p className="ride-detail-proof-detail-copy">
            {proof.thresholdEconomyState === 'held'
              ? 'Held — clears when your Threshold is established.'
              : proof.uiStateDetail}
          </p>

          <details className="ride-detail-proof-details">
            <summary className="ride-detail-proof-summary">Log trail</summary>

            <div className="ride-detail-proof-grid ride-detail-proof-grid--references">
              <ProofDatum
                label="Ride hash"
                value={shortenProof(proof.rideHash, 10)}
                valueFamily="mono"
              />
              <ProofDatum
                label="Commitment"
                value={shortenProof(proof.commitment, 10)}
                valueFamily="mono"
              />
              <ProofDatum
                label="RideAttestation"
                value={shortenProof(proof.attestationPda)}
                valueFamily="mono"
              />
              <ProofDatum
                label="Finalized"
                value={formatDateTime(proof.finalizedAt)}
                valueFamily="mono"
              />
            </div>

            {proof.importSource && (
              <div className="ride-detail-proof-source">
                Evidence source:{' '}
                <span className="ride-detail-proof-source-value">
                  {formatImportSource(proof.importSource)}
                </span>
              </div>
            )}

            <div className="ride-detail-proof-links">
              {proof.attestationPda && (
                <ProofLink
                  label="RideAttestation"
                  href={solanaExplorerUrl(proof.attestationPda, 'address')}
                />
              )}
              {proof.attestationTx && (
                <ProofLink
                  label="Entry tx"
                  href={solanaExplorerUrl(proof.attestationTx, 'tx')}
                />
              )}
              {proof.creditTx && (
                <ProofLink
                  label="CAL credit tx"
                  href={solanaExplorerUrl(proof.creditTx, 'tx')}
                />
              )}
            </div>
          </details>

          {hasFileDetails && (
            <details className="ride-detail-proof-details">
              <summary className="ride-detail-proof-summary">
                Technical source details
              </summary>
              <div className="ride-detail-proof-grid ride-detail-proof-grid--technical">
                <ProofDatum
                  label="Source quality"
                  value={formatProofLabel(proof.importQuality)}
                  valueFamily="sans"
                />
                <ProofDatum
                  label="Trackpoints"
                  value={formatProofNumber(proof.importTrackpoints)}
                  valueFamily="mono"
                />
                <ProofDatum
                  label="Max source gap"
                  value={formatSeconds(proof.importMaxGapS)}
                  valueFamily="mono"
                />
                <ProofDatum
                  label="Source ID"
                  value={shortenProof(proof.importSourceId)}
                  valueFamily="mono"
                />
                <ProofDatum
                  label="Protocol state"
                  value={formatProofLabel(proof.status)}
                  valueFamily="sans"
                />
              </div>
              {proof.importFlags && proof.importFlags.length > 0 && (
                <div className="ride-detail-proof-diagnostics">
                  Source diagnostics:{' '}
                  {proof.importFlags
                    .slice(0, 3)
                    .map(formatProofLabel)
                    .join(' · ')}
                </div>
              )}
            </details>
          )}
        </PortalPanelBody>
      </PortalPanel>
    </div>
  );
}

function ProofDatum({
  label,
  value,
  valueFamily,
  accent,
}: {
  label: string;
  value: string;
  valueFamily: 'sans' | 'mono';
  accent?: boolean;
}) {
  return (
    <div className="ride-detail-proof-datum">
      <div className="ride-detail-proof-datum__label">{label}</div>
      <div
        className={cn(
          'ride-detail-proof-datum__value',
          `ride-detail-proof-datum__value--${valueFamily}`,
          accent && 'ride-detail-proof-datum__value--accent',
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function ProofLink({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="ride-detail-proof-link"
    >
      {label}
      <ExternalLink size={11} />
    </a>
  );
}
