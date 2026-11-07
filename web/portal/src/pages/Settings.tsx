import { Slot, SlotRows } from '../components/loading/Slot';
import React, { Suspense, lazy, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { type Location, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Camera, LogOut } from 'lucide-react';
import { Units, RideVisibility, api, type GeocodingSearchResponse } from '../lib/api';
import {
  PortalFrame,
  PortalPage,
  PortalTruthPill,
} from '../components/portal/PortalSpine';
import { cn } from '../components/ui/utils';
import { notify } from '../lib/notify';
import {
  ABSENT_VALUE,
  MAX_WEIGHT_KG,
  MAX_WEIGHT_LB,
  MIN_WEIGHT_KG,
  MIN_WEIGHT_LB,
  WEIGHT_UNIT_CHECK_KG,
  formatDate,
  formatInteger,
  formatWatts,
  formatWeight,
  formatWeightRange,
  isPlausibleWeightKg,
  parseWeight,
  weightForInput,
} from '../lib/formatters';
import RidePrivacyControls from '../components/privacy/RidePrivacyControls';
import { buildPrivacySettingsUpdate, useRidePrivacy } from '../hooks/useRidePrivacy';
import { useThresholdAuthority } from '../hooks/useThresholdAuthority';
import { Switch } from '../components/ui/switch';

// Settings — the avatar sheet on web (Tim-ratified 2026-09-02). Grouped rows
// on sheets: label in gray on the left, value in ink on the right, a chevron
// when a row opens something, words when the choice is one of a few. The
// privacy contract, zones, sessions, avatar crop and account deletion keep
// their markup and behaviour; only the room around them changed.

function Chevron() {
  return (
    <svg className="settings-row__chevron" width="8" height="12" viewBox="0 0 8 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 1.5 L6.5 6 L2 10.5" />
    </svg>
  );
}

// Bio character limit
const BIO_MAX_LENGTH = 250;
const AVATAR_ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,image/heif';
const AVATAR_MAX_BYTES = 15 * 1024 * 1024;
const AVATAR_CROP_VIEWPORT = 280;
const AVATAR_CROP_OUTPUT = 1024;

type AvatarCropDraft = {
  file: File;
  objectUrl: string;
  naturalWidth: number;
  naturalHeight: number;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

type AvatarCropGeometry = {
  baseScale: number;
  displayWidth: number;
  displayHeight: number;
  sourceX: number;
  sourceY: number;
  sourceSize: number;
  offsetX: number;
  offsetY: number;
};

function getClampedAvatarOffset(
  naturalWidth: number,
  naturalHeight: number,
  zoom: number,
  offsetX: number,
  offsetY: number,
): { offsetX: number; offsetY: number } {
  const baseScale = Math.max(AVATAR_CROP_VIEWPORT / naturalWidth, AVATAR_CROP_VIEWPORT / naturalHeight);
  const displayWidth = naturalWidth * baseScale * zoom;
  const displayHeight = naturalHeight * baseScale * zoom;
  const maxOffsetX = Math.max(0, (displayWidth - AVATAR_CROP_VIEWPORT) / 2);
  const maxOffsetY = Math.max(0, (displayHeight - AVATAR_CROP_VIEWPORT) / 2);
  return {
    offsetX: Math.min(maxOffsetX, Math.max(-maxOffsetX, offsetX)),
    offsetY: Math.min(maxOffsetY, Math.max(-maxOffsetY, offsetY)),
  };
}

function getAvatarCropGeometry(draft: AvatarCropDraft): AvatarCropGeometry {
  const { naturalWidth, naturalHeight, zoom } = draft;
  const { offsetX, offsetY } = getClampedAvatarOffset(
    naturalWidth,
    naturalHeight,
    zoom,
    draft.offsetX,
    draft.offsetY,
  );
  const baseScale = Math.max(
    AVATAR_CROP_VIEWPORT / naturalWidth,
    AVATAR_CROP_VIEWPORT / naturalHeight,
  );
  const displayScale = baseScale * zoom;
  const sourceSize = AVATAR_CROP_VIEWPORT / displayScale;
  const unclampedSourceX = naturalWidth / 2 - offsetX / displayScale - sourceSize / 2;
  const unclampedSourceY = naturalHeight / 2 - offsetY / displayScale - sourceSize / 2;
  const sourceX = Math.max(0, Math.min(naturalWidth - sourceSize, unclampedSourceX));
  const sourceY = Math.max(0, Math.min(naturalHeight - sourceSize, unclampedSourceY));

  return {
    baseScale,
    displayWidth: naturalWidth * displayScale,
    displayHeight: naturalHeight * displayScale,
    sourceX,
    sourceY,
    sourceSize,
    offsetX,
    offsetY,
  };
}

function readImageDimensions(objectUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error('Could not read that image. Try a JPEG, PNG, or WebP file.'));
    image.src = objectUrl;
  });
}

function loadCropImage(objectUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('Could not process avatar crop.'));
    image.src = objectUrl;
  });
}

function canvasToAvatarBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('Could not process avatar crop.'));
        return;
      }
      resolve(blob);
    }, 'image/jpeg', 0.9);
  });
}

async function cropAvatarDraftToFile(draft: AvatarCropDraft): Promise<File> {
  const image = await loadCropImage(draft.objectUrl);
  const geometry = getAvatarCropGeometry(draft);
  const canvas = document.createElement('canvas');
  canvas.width = AVATAR_CROP_OUTPUT;
  canvas.height = AVATAR_CROP_OUTPUT;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Could not process avatar crop.');
  }

  ctx.drawImage(
    image,
    geometry.sourceX,
    geometry.sourceY,
    geometry.sourceSize,
    geometry.sourceSize,
    0,
    0,
    AVATAR_CROP_OUTPUT,
    AVATAR_CROP_OUTPUT,
  );
  const blob = await canvasToAvatarBlob(canvas);
  const baseName = draft.file.name.replace(/\.[^.]+$/, '') || 'avatar';
  return new File([blob], `${baseName}-avatar.jpg`, {
    type: 'image/jpeg',
    lastModified: Date.now(),
  });
}

// Valid tab IDs for deep linking
const VALID_TABS = ['profile', 'performance', 'display', 'connections', 'privacy', 'alerts'] as const;
type SettingsTabId = typeof VALID_TABS[number];

function isSettingsTab(value: string | null | undefined): value is SettingsTabId {
  return VALID_TABS.includes(value as SettingsTabId);
}

function readSettingsTab(location: Pick<Location, 'search' | 'hash'>): SettingsTabId {
  const queryTab = new URLSearchParams(location.search).get('tab');
  if (isSettingsTab(queryTab)) return queryTab === 'display' ? 'performance' : queryTab;

  const hashTab = location.hash.slice(1);
  if (isSettingsTab(hashTab)) return hashTab === 'display' ? 'performance' : hashTab;

  return 'profile';
}

function settingsTabSearch(search: string, tabId: SettingsTabId): string {
  const params = new URLSearchParams(search);
  params.set('tab', tabId);
  return `?${params.toString()}`;
}

const LazyPrivacyZones = lazy(() =>
  import('../components/settings/PrivacyZones').then((module) => ({ default: module.PrivacyZones })),
);
const LazySessionManager = lazy(() =>
  import('../components/settings/SessionManager').then((module) => ({ default: module.SessionManager })),
);
const AccountDeletionSettingsCard = lazy(() =>
  import('../components/account/AccountDeletionSettingsCard'),
);
const LazyAlertSwitches = lazy(() =>
  import('../components/settings/AlertSwitches').then((module) => ({ default: module.AlertSwitches })),
);

function preloadSettingsTab(tabId: SettingsTabId) {
  if (tabId === 'privacy') {
    void import('../components/settings/PrivacyZones');
    void import('../components/settings/SessionManager');
  }
  if (tabId === 'alerts') {
    void import('../components/settings/AlertSwitches');
  }
}

function DeferredSettingsSection({
  label,
}: {
  label: string;
}) {
  return <div className="settings-room__deferred" aria-busy="true"><SlotRows count={4} /><span className="sr-only" role="status">{`Loading ${label}`}</span></div>;
}

export default function Settings() {
  const { user, updatePreferences, logout, refreshUser } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const activeTab = readSettingsTab(location);
  const ridePrivacy = useRidePrivacy(Boolean(user));

  // -- State Management --
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isAvatarUploading, setIsAvatarUploading] = useState(false);
  const [avatarCropDraft, setAvatarCropDraft] = useState<AvatarCropDraft | null>(null);
  const [isAvatarProcessing, setIsAvatarProcessing] = useState(false);
  const hasInitialized = useRef(false);
  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  const avatarObjectUrlRef = useRef<string | null>(null);
  const avatarCropDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  // Username availability check
  const [usernameStatus, setUsernameStatus] = useState<'idle' | 'checking' | 'available' | 'taken'>('idle');
  const usernameCheckTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // GDPR data export
  const [isExporting, setIsExporting] = useState(false);

  // Logout confirmation modal
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const thresholdOwnerKey = user ? `${user.id}:${user.wallet}` : null;
  const thresholdQuery = useThresholdAuthority(thresholdOwnerKey);
  const threshold = thresholdQuery.data;

  // Form state - initialized from user profile
  const [formData, setFormData] = useState({
    displayName: '',
    username: '',
    bio: '',
    location: '',
    weight: '', // Displayed in user's preferred units
    units: 'metric' as Units,
    isPublic: true,
    defaultRideVisibility: 'public' as RideVisibility
  });

  const homeBaseButton = useRef<HTMLButtonElement>(null);
  const [homeSearchOpen, setHomeSearchOpen] = useState(false);
  const [homeQuery, setHomeQuery] = useState('');
  const [homeResults, setHomeResults] = useState<GeocodingSearchResponse | null>(null);
  const [homeSearchState, setHomeSearchState] = useState<'idle' | 'loading' | 'unavailable'>('idle');
  const homeRequest = useRef(0);
  const searchHome = async (event: React.FormEvent) => {
    event.preventDefault();
    if (homeQuery.trim().length < 3) return;
    const request = ++homeRequest.current;
    setHomeSearchState('loading');
    setHomeResults(null);
    try {
      const results = await api.searchLocations(homeQuery.trim());
      if (request !== homeRequest.current) return;
      setHomeResults(results);
      setHomeSearchState('idle');
    } catch {
      if (request === homeRequest.current) setHomeSearchState('unavailable');
    }
  };

  // Track original form data to detect unsaved changes
  const [originalFormData, setOriginalFormData] = useState<typeof formData | null>(null);

  // Sync form data from user profile ONLY on initial mount
  useEffect(() => {
    if (user && !hasInitialized.current) {
      hasInitialized.current = true;

      // Compute weight display value based on user's preferred units
      const profileUnits = user.preferredUnits || 'metric';
      const displayWeight = weightForInput(user.weightKg, profileUnits);

      const initialData = {
        displayName: user.displayName || '',
        username: user.username || '',
        bio: user.bio || '',
        location: user.location || '',
        weight: displayWeight,
        units: profileUnits,
        isPublic: user.isPublic ?? true,
        defaultRideVisibility: user.defaultRideVisibility || 'public'
      };

      setFormData(initialData);
      setOriginalFormData(initialData);
    }
  }, [user]);


  // Keep settings navigation in the URL so saves/remounts stay on the same section.
  useEffect(() => {
    const nextSearch = settingsTabSearch(location.search, activeTab);
    if (location.search !== nextSearch || location.hash) {
      navigate(
        { pathname: location.pathname, search: nextSearch, hash: '' },
        { replace: true },
      );
    }
  }, [activeTab, location.hash, location.pathname, location.search, navigate]);

  useEffect(() => {
    preloadSettingsTab(activeTab);
  }, [activeTab]);

  // Username availability check with debounce
  const checkUsernameAvailability = useCallback(async (username: string) => {
    // Clear any pending check
    if (usernameCheckTimeoutRef.current) {
      clearTimeout(usernameCheckTimeoutRef.current);
    }

    // Don't check if empty or same as current username
    if (!username || username === user?.username) {
      setUsernameStatus('idle');
      return;
    }

    // Validate format first (alphanumeric, 3-20 chars)
    if (!/^[a-zA-Z0-9_]{3,20}$/.test(username)) {
      setUsernameStatus('idle');
      return;
    }

    setUsernameStatus('checking');

    // Debounce the API call
    usernameCheckTimeoutRef.current = setTimeout(async () => {
      try {
        const result = await api.checkUsernameAvailability(username);
        setUsernameStatus(result.available ? 'available' : 'taken');
      } catch {
        setUsernameStatus('idle');
      }
    }, 500);
  }, [user?.username]);

  // Handle username change with availability check
  const handleUsernameChange = useCallback((value: string) => {
    setFormData(prev => ({ ...prev, username: value }));
    checkUsernameAvailability(value);
  }, [checkUsernameAvailability]);

  // GDPR data export handler
  const handleDataExport = useCallback(async () => {
    setIsExporting(true);
    try {
      const exportResponse = await api.exportUserData();
      if (!exportResponse.downloadUrl) {
        throw new Error('Export response did not include a download URL');
      }
      const a = document.createElement('a');
      a.href = exportResponse.downloadUrl;
      a.download = `boulder-roller-data-export-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      notify.success('Data export downloaded');
    } catch {
      notify.error('Could not export data');
    } finally {
      setIsExporting(false);
    }
  }, []);

  const privacyUpdates = useMemo(
    () => buildPrivacySettingsUpdate(ridePrivacy.choice, ridePrivacy.settings, ridePrivacy.shareWkg),
    [ridePrivacy.choice, ridePrivacy.settings, ridePrivacy.shareWkg],
  );
  const hasPrivacyChanges = Object.keys(privacyUpdates).length > 0;
  const hasWeightEntry = formData.weight.trim().length > 0;
  const enteredWeightKg = hasWeightEntry
    ? parseWeight(formData.weight, formData.units)
    : null;
  const weightIsInvalid = hasWeightEntry && !isPlausibleWeightKg(enteredWeightKg);
  const weightNeedsUnitCheck = formData.units === 'metric'
    && isPlausibleWeightKg(enteredWeightKg)
    && enteredWeightKg >= WEIGHT_UNIT_CHECK_KG;

  // Detect unsaved changes
  const hasUnsavedChanges = useMemo(() => {
    const profileChanged = originalFormData
      ? JSON.stringify(formData) !== JSON.stringify(originalFormData)
      : false;
    return profileChanged || hasPrivacyChanges;
  }, [formData, hasPrivacyChanges, originalFormData]);

  // Browser beforeunload warning for unsaved changes
  useEffect(() => {
    if (!hasUnsavedChanges) return;

    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Modern browsers ignore custom messages, but we set one for older browsers.
      e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
      return e.returnValue;
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Note: In-app navigation blocking requires createBrowserRouter (data router)
  // For now, only beforeunload handles browser close/refresh
  // TODO: Migrate to createBrowserRouter for full navigation blocking

  const handleSave = useCallback(async () => {
    setSaveError(null);
    if (activeTab === 'privacy' && (!ridePrivacy.choice || !ridePrivacy.settings)) {
      notify.error('Privacy settings unavailable. Try again before saving.');
      return;
    }
    if (weightIsInvalid) {
      notify.error(`Enter a weight between ${formatWeightRange(MIN_WEIGHT_KG, MAX_WEIGHT_KG, formData.units)}.`);
      return;
    }
    setIsSaving(true);
    try {
      if (hasPrivacyChanges && ridePrivacy.choice && ridePrivacy.settings) {
        await api.updatePrivacySettings(privacyUpdates);
        ridePrivacy.reload();
      }

      await updatePreferences({
        displayName: formData.displayName,
        username: formData.username || undefined,
        bio: formData.bio || undefined,
        location: formData.location || undefined,
        weightKg: enteredWeightKg ?? undefined,
        units: formData.units,
        ...(originalFormData && formData.isPublic !== originalFormData.isPublic
          ? { isPublic: formData.isPublic }
          : {}),
      });

      if (hasPrivacyChanges) {
        await refreshUser();
      }

      notify.success('Saved');
      // Reset original form data to current state after successful save
      setOriginalFormData({ ...formData });
    } catch {
      setSaveError('Could not save settings');
    } finally {
      setIsSaving(false);
    }
  }, [activeTab, enteredWeightKg, formData, hasPrivacyChanges, originalFormData, privacyUpdates, refreshUser, ridePrivacy, updatePreferences, weightIsInvalid]);

  const clearAvatarCropDraft = useCallback(() => {
    if (avatarObjectUrlRef.current) {
      URL.revokeObjectURL(avatarObjectUrlRef.current);
      avatarObjectUrlRef.current = null;
    }
    avatarCropDragRef.current = null;
    setAvatarCropDraft(null);
    setIsAvatarProcessing(false);
  }, []);

  useEffect(() => {
    return () => {
      if (avatarObjectUrlRef.current) {
        URL.revokeObjectURL(avatarObjectUrlRef.current);
        avatarObjectUrlRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!avatarCropDraft) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isAvatarProcessing) {
        clearAvatarCropDraft();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [avatarCropDraft, clearAvatarCropDraft, isAvatarProcessing]);

  const updateAvatarCropOffset = useCallback((offsetX: number, offsetY: number) => {
    setAvatarCropDraft((draft) => {
      if (!draft) return draft;
      const clamped = getClampedAvatarOffset(
        draft.naturalWidth,
        draft.naturalHeight,
        draft.zoom,
        offsetX,
        offsetY,
      );
      return { ...draft, ...clamped };
    });
  }, []);

  const handleAvatarCropPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!avatarCropDraft || isAvatarProcessing) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    avatarCropDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: avatarCropDraft.offsetX,
      originY: avatarCropDraft.offsetY,
    };
  }, [avatarCropDraft, isAvatarProcessing]);

  const handleAvatarCropPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = avatarCropDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    updateAvatarCropOffset(
      drag.originX + event.clientX - drag.startX,
      drag.originY + event.clientY - drag.startY,
    );
  }, [updateAvatarCropOffset]);

  const handleAvatarCropPointerEnd = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = avatarCropDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    avatarCropDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const handleAvatarZoomChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const zoom = Number(event.target.value);
    setAvatarCropDraft((draft) => {
      if (!draft) return draft;
      const clamped = getClampedAvatarOffset(
        draft.naturalWidth,
        draft.naturalHeight,
        zoom,
        draft.offsetX,
        draft.offsetY,
      );
      return { ...draft, zoom, ...clamped };
    });
  }, []);

  const handleAvatarFile = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || isAvatarUploading || isAvatarProcessing) return;
    if (file.size > AVATAR_MAX_BYTES) {
      notify.error('Image is too large');
      return;
    }

    if (avatarObjectUrlRef.current) {
      URL.revokeObjectURL(avatarObjectUrlRef.current);
      avatarObjectUrlRef.current = null;
    }

    const objectUrl = URL.createObjectURL(file);
    avatarObjectUrlRef.current = objectUrl;
    try {
      const { width, height } = await readImageDimensions(objectUrl);
      setAvatarCropDraft({
        file,
        objectUrl,
        naturalWidth: width,
        naturalHeight: height,
        zoom: 1,
        offsetX: 0,
        offsetY: 0,
      });
    } catch (error) {
      URL.revokeObjectURL(objectUrl);
      avatarObjectUrlRef.current = null;
      notify.error(error instanceof Error ? error.message : 'Could not read image');
    }
  }, [isAvatarProcessing, isAvatarUploading]);

  const handleAvatarCropConfirm = useCallback(async () => {
    if (!avatarCropDraft || isAvatarUploading || isAvatarProcessing) return;
    setIsAvatarUploading(true);
    setIsAvatarProcessing(true);
    try {
      const croppedFile = await cropAvatarDraftToFile(avatarCropDraft);
      await api.uploadAvatar(croppedFile);
      await refreshUser();
      clearAvatarCropDraft();
      notify.success('Profile photo updated');
    } catch {
      notify.error('Could not update profile photo');
    } finally {
      setIsAvatarUploading(false);
      setIsAvatarProcessing(false);
    }
  }, [avatarCropDraft, clearAvatarCropDraft, isAvatarProcessing, isAvatarUploading, refreshUser]);

  const handleRemoveAvatar = useCallback(async () => {
    if (isAvatarUploading || isAvatarProcessing) return;
    setIsAvatarUploading(true);
    try {
      await api.deleteAvatar();
      await refreshUser();
      notify.success('Profile photo removed');
    } catch {
      notify.error('Could not remove profile photo');
    } finally {
      setIsAvatarUploading(false);
    }
  }, [isAvatarProcessing, isAvatarUploading, refreshUser]);


  // Handle units change - also recalculate displayed weight
  const handleUnitsChange = useCallback((newUnits: Units) => {
    setFormData((previous) => {
      const currentWeightKg = parseWeight(previous.weight, previous.units);
      return {
        ...previous,
        units: newUnits,
        weight: currentWeightKg == null ? previous.weight : weightForInput(currentWeightKg, newUnits),
      };
    });
  }, []);

  // Reset form to user's saved values
  const handleReset = useCallback(() => {
    if (!user) return;

    hasInitialized.current = false; // Allow re-init
    const profileUnits = user.preferredUnits || 'metric';
    const displayWeight = weightForInput(user.weightKg, profileUnits);

    const savedData = {
      displayName: user.displayName || '',
      username: user.username || '',
      bio: user.bio || '',
      location: user.location || '',
      weight: displayWeight,
      units: profileUnits,
      isPublic: user.isPublic ?? true,
      defaultRideVisibility: user.defaultRideVisibility || 'public'
    };

    setFormData(savedData);
    setSaveError(null);
    setOriginalFormData(savedData);
    ridePrivacy.reload();
    notify.success('Restored saved setup');
  }, [ridePrivacy, user]);

  // Handle wallet disconnect - show confirmation first
  const handleDisconnectClick = useCallback(() => {
    setShowLogoutConfirm(true);
  }, []);

  // Confirm and execute logout
  const handleConfirmLogout = useCallback(() => {
    logout();
    setShowLogoutConfirm(false);
    notify.success('Wallet disconnected');
  }, [logout]);


  const navItems: Array<{ id: SettingsTabId; label: string }> = [
    { id: 'profile', label: 'Identity' },
    { id: 'performance', label: 'Performance' },
    { id: 'privacy', label: 'Privacy' },
    { id: 'connections', label: 'Connections' },
    { id: 'alerts', label: 'Alerts' },
  ];

  const handleTabChange = useCallback((tabId: SettingsTabId) => {
    preloadSettingsTab(tabId);
    navigate(
      {
        pathname: location.pathname,
        search: settingsTabSearch(location.search, tabId),
        hash: '',
      },
      { replace: true },
    );
  }, [location.pathname, location.search, navigate]);

  const walletLabel = user?.wallet ? `${user.wallet.slice(0, 4)}…${user.wallet.slice(-4)}` : null;
  const avatarCropGeometry = avatarCropDraft ? getAvatarCropGeometry(avatarCropDraft) : null;
  const avatarPreviewScale = 88 / AVATAR_CROP_VIEWPORT;
  const isAvatarBusy = isAvatarUploading || isAvatarProcessing;
  const section: SettingsTabId = activeTab === 'display' ? 'performance' : activeTab;
  const identityName = user?.displayName || formData.username.trim() || 'Rider';
  const identityMeta = [
    formData.username.trim() ? `@${formData.username.trim()}` : null,
    formData.location.trim() || null,
  ].filter(Boolean).join(' · ');
  const statusWord = isSaving ? 'Saving' : hasUnsavedChanges ? 'Unsaved' : 'Saved';
  const copyWallet = async () => {
    if (!user?.wallet) return;
    try {
      await navigator.clipboard.writeText(user.wallet);
      notify.success('Address copied');
    } catch {
      notify.error('Could not copy address');
    }
  };

  // -- Render --

  return (
    <PortalPage className="settings-v2-page settings-room" aria-busy={isSaving || isExporting || isAvatarBusy}>
      <PortalFrame>
        <div className="settings-room__header">
          <h1 className="settings-room__title">Settings</h1>
          <div className="settings-room__actions">
            <span className="settings-v2-actions__status">
              <PortalTruthPill tone={hasUnsavedChanges ? 'warning' : 'verified'}>
                {statusWord}
              </PortalTruthPill>
            </span>
            {hasUnsavedChanges ? (
              <>
                <button type="button" className="settings-room__action" onClick={handleReset} disabled={isSaving}>
                  Reset
                </button>
                <button type="button" className="settings-room__action settings-room__action--save" onClick={handleSave} disabled={isSaving}>
                  Save
                </button>
              </>
            ) : null}
          </div>
        </div>

        <div className="settings-room__grid">
          <nav className="settings-room__rail" aria-label="Settings sections">
            {navItems.map((item) => {
              const isActive = section === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className="settings-room__rail-word"
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => handleTabChange(item.id)}
                  onMouseEnter={() => preloadSettingsTab(item.id)}
                  onFocus={() => preloadSettingsTab(item.id)}
                  onTouchStart={() => preloadSettingsTab(item.id)}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>

          <div className="settings-room__column">
            {saveError && <p className="settings-sheet__note" role="alert">{saveError}</p>}
            {section === 'profile' ? (
              <>
                <section className="settings-sheet settings-v2-profile-photo-section" aria-label="Profile photo">
                  <div className="settings-identity">
                    <span className="settings-identity__who">
                      <span className="settings-identity__avatar" aria-hidden="true">
                        {user?.avatarUrl ? <img src={user.avatarUrl} alt="" /> : <span>{identityName.slice(0, 1).toUpperCase()}</span>}
                      </span>
                      <span className="settings-identity__copy">
                        <span className="settings-identity__name">{identityName}</span>
                        {identityMeta ? <span className="settings-identity__meta">{identityMeta}</span> : null}
                      </span>
                    </span>
                    <span className="settings-identity__actions">
                      <input
                        ref={avatarInputRef}
                        type="file"
                        accept={AVATAR_ACCEPT}
                        className="settings-v2-file-input"
                        onChange={handleAvatarFile}
                      />
                      <button
                        type="button"
                        className={cn('settings-room__text', !hasUnsavedChanges && 'settings-room__text--do')}
                        onClick={() => avatarInputRef.current?.click()}
                        disabled={isAvatarBusy}
                      >
                        {isAvatarBusy ? 'Working' : 'Change photo'}
                      </button>
                      {user?.avatarUrl ? (
                        <button type="button" className="settings-room__text" onClick={handleRemoveAvatar} disabled={isAvatarBusy}>
                          Remove
                        </button>
                      ) : null}
                    </span>
                  </div>
                </section>

                <section className="settings-sheet" aria-labelledby="settings-profile-heading">
                  <h2 id="settings-profile-heading" className="settings-sheet__eyebrow">Profile</h2>
                  <label className="settings-row">
                    <span className="settings-row__label">Name</span>
                    <input className="settings-row__input" value={formData.displayName} maxLength={50} autoComplete="name" onChange={e => setFormData({ ...formData, displayName: e.target.value })} />
                  </label>
                  <label className="settings-row">
                    <span className="settings-row__label">Username</span>
                    <input
                      className="settings-row__input"
                      value={formData.username}
                      onChange={(e) => handleUsernameChange(e.target.value)}
                      placeholder="3-20 characters, alphanumeric only"
                      autoComplete="off"
                    />
                  </label>
                  {usernameStatus === 'taken' ? (
                    <p className="settings-sheet__note settings-sheet__note--warning">This username is already taken</p>
                  ) : null}
                  {usernameStatus === 'available' ? (
                    <p className="settings-sheet__note">Username is available</p>
                  ) : null}
                  <button type="button" ref={homeBaseButton} className="settings-row settings-row--tap" aria-expanded={homeSearchOpen} aria-controls="settings-home-search" onClick={() => setHomeSearchOpen(!homeSearchOpen)}>
                    <span className="settings-row__label">Home base</span>
                    <span className="settings-row__trail"><span className="settings-row__value">{formData.location || ABSENT_VALUE}</span><Chevron /></span>
                  </button>
                  {homeSearchOpen && <form id="settings-home-search" onSubmit={searchHome} className="settings-home-search">
                    <label className="settings-row"><span className="settings-row__label">Search places</span><input className="settings-row__input" autoFocus value={homeQuery} maxLength={120} autoComplete="off" onChange={e => { homeRequest.current++; setHomeQuery(e.target.value); setHomeResults(null); setHomeSearchState('idle'); }} /></label>
                    <p className="settings-sheet__note">Search public places only. Do not enter personal or confidential information.</p>
                    <button type="submit" className="settings-room__text" disabled={homeQuery.trim().length < 3 || homeSearchState === 'loading'}>Search places</button>
                    {homeSearchState === 'loading' && <div aria-busy="true"><SlotRows count={4} /><span className="sr-only" role="status">Loading</span></div>}
                    {homeSearchState === 'unavailable' && <p role="status">{ABSENT_VALUE}</p>}
                    {homeResults?.results.map(result => <button type="button" className="settings-row settings-row--tap" key={`${result.latitude}:${result.longitude}`} onClick={() => { homeRequest.current++; setFormData({ ...formData, location: result.displayName }); setHomeSearchOpen(false); homeBaseButton.current?.focus(); }}><span className="settings-row__value">{result.displayName}</span><Chevron /></button>)}
                    {homeResults && homeResults.results.length === 0 && <p role="status">No places found.</p>}
                    {homeResults && <a className="settings-sheet__note" href={homeResults.attribution.url} target="_blank" rel="noreferrer">{homeResults.attribution.text}</a>}
                  </form>}
                  <label className="settings-row settings-row--block">
                    <span className="settings-row__label">Bio</span>
                    <textarea
                      className="settings-row__textarea"
                      value={formData.bio}
                      maxLength={BIO_MAX_LENGTH}
                      onChange={(e) => setFormData({ ...formData, bio: e.target.value.slice(0, BIO_MAX_LENGTH) })}
                    />
                    <span className="settings-row__count">{`${formatInteger(formData.bio.length)} / ${formatInteger(BIO_MAX_LENGTH)}`}</span>
                  </label>
                </section>
              </>
            ) : null}

            {section === 'performance' ? (
              <>
                <section className="settings-sheet" aria-labelledby="settings-threshold-heading">
                  <h2 id="settings-threshold-heading" className="settings-sheet__eyebrow">Threshold</h2>
                  {thresholdQuery.isError ? (
                    <div className="settings-row">
                      <span className="settings-row__label">Current</span>
                      <span className="settings-row__trail">
                        <span className="settings-row__value settings-row__value--mono">{formatWatts(null)}</span>
                        <button
                          type="button"
                          className="settings-room__text settings-room__text--do"
                          onClick={() => void thresholdQuery.refetch()}
                        >
                          Try again
                        </button>
                      </span>
                    </div>
                  ) : threshold ? (
                    threshold.state === 'establishing' ? (
                      <div className="settings-row">
                        <span className="settings-row__label">Status</span>
                        <span className="settings-row__value">Establishing</span>
                      </div>
                    ) : (
                      <>
                        <div className="settings-row">
                          <span className="settings-row__label">Current</span>
                          <span className="settings-row__trail">
                            <span className="settings-row__sub">derived from your rides</span>
                            <span className="settings-row__value settings-row__value--mono">{formatWatts(threshold.currentW)}</span>
                          </span>
                        </div>
                        <div className="settings-row">
                          <span className="settings-row__label">{threshold.lastRaisedAt ? 'Last raised' : 'Established'}</span>
                          <span className="settings-row__value">{formatDate(threshold.lastRaisedAt ?? threshold.establishedAt)}</span>
                        </div>
                        {threshold.pendingMonday ? (
                          <div className="settings-row">
                            <span className="settings-row__label">Next Monday</span>
                            <span className="settings-row__value settings-row__value--mono">{`${formatWatts(threshold.pendingMonday.watts)} · Pending`}</span>
                          </div>
                        ) : null}
                      </>
                    )
                  ) : (
                    <div className="settings-row" aria-busy="true">
                      <span className="settings-row__label">Current</span>
                      <span className="settings-row__value settings-row__value--mono">{formatWatts(null)}</span>
                    </div>
                  )}
                  {threshold?.state === 'established' ? (
                    <div className="settings-zones" aria-label="Power zones">
                      {[55, 75, 90, 105, 120, 150].map((limit, index) => {
                        const thresholdWatts = threshold.pendingMonday?.watts ?? threshold.currentW;
                        const zoneWatts = formatWatts(thresholdWatts == null ? null : thresholdWatts * (limit / 100));
                        return (
                          <div key={limit} className="settings-zones__cell">
                            <span>{`Z${formatInteger(index + 1)}`}</span>
                            <strong>{threshold.pendingMonday ? `${zoneWatts} · Pending` : zoneWatts}</strong>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </section>

                <section className="settings-sheet" aria-label="Weight and units">
                  <label className="settings-row">
                    <span className="settings-row__label">Weight</span>
                    <span className="settings-row__trail">
                      <input
                        type="number"
                        className="settings-row__input settings-row__input--short"
                        value={formData.weight}
                        onChange={(e) => setFormData({ ...formData, weight: e.target.value })}
                        min={formData.units === 'metric' ? MIN_WEIGHT_KG : MIN_WEIGHT_LB}
                        max={formData.units === 'metric' ? MAX_WEIGHT_KG : MAX_WEIGHT_LB}
                        step={formData.units === 'metric' ? 0.1 : 1}
                      />
                      <span className="settings-row__unit">{formData.units === 'imperial' ? 'lb' : 'kg'}</span>
                    </span>
                  </label>
                  {weightIsInvalid ? (
                    <p className="settings-sheet__note settings-sheet__note--warning">Enter a weight between 30–200 kg (66–441 lb).</p>
                  ) : weightNeedsUnitCheck ? (
                    <p className="settings-sheet__note settings-sheet__note--warning">
                      {`Check the unit: ${formatWeight(enteredWeightKg, 'metric')} is ${formatWeight(enteredWeightKg, 'imperial')}. If you entered pounds, switch units before saving.`}
                    </p>
                  ) : null}
                  <div className="settings-row">
                    <span className="settings-row__label">Units</span>
                    <span className="settings-words" role="group" aria-label="Units">
                      <button type="button" aria-pressed={formData.units === 'metric'} onClick={() => handleUnitsChange('metric')}>Kilometers</button>
                      <button type="button" aria-pressed={formData.units === 'imperial'} onClick={() => handleUnitsChange('imperial')}>Miles</button>
                    </span>
                  </div>
                </section>
              </>
            ) : null}

            {section === 'privacy' ? (
              <>
                <section className="settings-sheet" aria-labelledby="settings-privacy-heading">
                  <h2 id="settings-privacy-heading" className="settings-sheet__eyebrow">Privacy</h2>
                  <div className="settings-row">
                    <span className="settings-row__label">Who can see your profile</span>
                    <span className="settings-words" role="group" aria-label="Profile visibility">
                      <button type="button" aria-pressed={formData.isPublic} onClick={() => setFormData({ ...formData, isPublic: true })}>Public</button>
                      <button type="button" aria-pressed={!formData.isPublic} onClick={() => setFormData({ ...formData, isPublic: false })}>Private</button>
                    </span>
                  </div>
                  {user && <div className="settings-row settings-row--switch">
                    <span className="settings-row__copy">
                      <label htmlFor="settings-share-wkg" className="settings-row__label settings-row__label--ink">Show my W/kg</label>
                      <span id="settings-share-wkg-description" className="settings-row__sub">Other riders see your watts per kilo next to your power. Together they reveal your weight.</span>
                    </span>
                    <Switch id="settings-share-wkg" className="settings-row__switch"
                      checked={ridePrivacy.shareWkg}
                      disabled={isSaving || ridePrivacy.isLoading || !ridePrivacy.settings}
                      aria-describedby="settings-share-wkg-description"
                      onCheckedChange={ridePrivacy.setShareWkg} />
                  </div>}
                </section>

                <section className="settings-sheet" aria-label="New rides">
                  <span className="settings-sheet__eyebrow">New rides</span>
                  {ridePrivacy.isLoading ? (
                    <div aria-busy="true"><SlotRows count={3} /><span className="sr-only" role="status">Loading privacy settings</span></div>
                  ) : ridePrivacy.error || !ridePrivacy.choice || !ridePrivacy.settings ? (
                    <div className="ride-privacy-controls-status ride-privacy-controls-status--error" role="alert">
                      <p>{ridePrivacy.error || 'Privacy settings unavailable. Try again before saving.'}</p>
                      <button type="button" onClick={ridePrivacy.reload}>Try again</button>
                    </div>
                  ) : (
                    <RidePrivacyControls
                      value={ridePrivacy.choice}
                      onChange={ridePrivacy.setChoice}
                      privacyZoneCount={ridePrivacy.settings.privacyZoneCount}
                      audienceLegend="Who can see new rides?"
                      mapLegend="Map visibility for new rides"
                      idPrefix="settings-privacy"
                    />
                  )}
                  {ridePrivacy.choice && ridePrivacy.settings ? (
                    <p className="settings-sheet__note">
                      These defaults apply to future rides. Existing rides keep their current privacy.
                    </p>
                  ) : null}
                </section>

                <section className="settings-sheet" aria-label="Privacy zones">
                  <span className="settings-sheet__eyebrow">Privacy zones</span>
                  <Suspense fallback={<DeferredSettingsSection label="privacy zones" />}>
                    <LazyPrivacyZones onZonesChanged={ridePrivacy.reload} />
                  </Suspense>
                </section>

                <section className="settings-sheet" aria-label="Sessions">
                  <span className="settings-sheet__eyebrow">Sessions</span>
                  <Suspense fallback={<DeferredSettingsSection label="sessions" />}>
                    <LazySessionManager />
                  </Suspense>
                </section>

                <section className="settings-sheet" aria-label="Data">
                  <span className="settings-sheet__eyebrow">Data</span>
                  <button type="button" className="settings-row settings-row--tap" onClick={handleDataExport} disabled={isExporting}>
                    <span className="settings-row__label settings-row__label--ink">{isExporting ? 'Exporting' : 'Export your data'}</span>
                    <Chevron />
                  </button>
                  <Suspense fallback={<DeferredSettingsSection label="account deletion" />}>
                    <AccountDeletionSettingsCard />
                  </Suspense>
                </section>
              </>
            ) : null}

            {section === 'connections' ? (
              <section className="settings-sheet" aria-labelledby="settings-connections-heading">
                <h2 id="settings-connections-heading" className="settings-sheet__eyebrow">Connections</h2>
                <button type="button" className="settings-row settings-row--tap" onClick={() => void copyWallet()} disabled={!user?.wallet}>
                  <span className="settings-row__label">Wallet</span>
                  <span className="settings-row__trail">
                    <span className="settings-row__value settings-row__value--mono">{walletLabel ?? 'Not connected'}</span>
                  </span>
                </button>
                <button type="button" className="settings-room__action-row" onClick={handleDisconnectClick}>
                  Disconnect wallet
                </button>
              </section>
            ) : null}

            {section === 'alerts' ? (
              <section className="settings-sheet" aria-labelledby="settings-alerts-heading">
                <Suspense fallback={<DeferredSettingsSection label="alerts" />}>
                  <LazyAlertSwitches headingId="settings-alerts-heading" />
                </Suspense>
              </section>
            ) : null}
          </div>
        </div>
      </PortalFrame>

      {/* Avatar Crop Modal */}
      {avatarCropDraft && avatarCropGeometry && (
        <div className="settings-v2-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="settings-avatar-crop-title">
          <div className="settings-v2-avatar-crop-modal">
            <div className="settings-v2-avatar-crop-modal__header">
              <div>
                <h3 id="settings-avatar-crop-title" className="settings-v2-avatar-crop-modal__title">Crop profile photo</h3>
                <p className="settings-v2-avatar-crop-modal__subtitle">
                  Square avatar preview
                </p>
              </div>
              <div className="settings-v2-avatar-crop-preview" aria-hidden="true">
                <img
                  src={avatarCropDraft.objectUrl}
                  alt=""
                  draggable={false}
                  style={{
                    width: `${avatarCropGeometry.displayWidth * avatarPreviewScale}px`,
                    height: `${avatarCropGeometry.displayHeight * avatarPreviewScale}px`,
                    transform: `translate(calc(-50% + ${avatarCropGeometry.offsetX * avatarPreviewScale}px), calc(-50% + ${avatarCropGeometry.offsetY * avatarPreviewScale}px))`,
                  }}
                />
              </div>
            </div>

            <div
              className="settings-v2-avatar-crop-frame"
              onPointerDown={handleAvatarCropPointerDown}
              onPointerMove={handleAvatarCropPointerMove}
              onPointerUp={handleAvatarCropPointerEnd}
              onPointerCancel={handleAvatarCropPointerEnd}
            >
              <img
                src={avatarCropDraft.objectUrl}
                alt=""
                draggable={false}
                style={{
                  width: `${avatarCropGeometry.displayWidth}px`,
                  height: `${avatarCropGeometry.displayHeight}px`,
                  transform: `translate(calc(-50% + ${avatarCropGeometry.offsetX}px), calc(-50% + ${avatarCropGeometry.offsetY}px))`,
                }}
              />
              <div className="settings-v2-avatar-crop-frame__ring" aria-hidden="true" />
            </div>

            <label className="settings-v2-avatar-crop-zoom">
              <span>Zoom</span>
              <input
                type="range"
                min="1"
                max="3"
                step="0.01"
                value={avatarCropDraft.zoom}
                onChange={handleAvatarZoomChange}
                disabled={isAvatarProcessing}
              />
            </label>

            <div className="settings-v2-confirm-modal__actions">
              <button
                type="button"
                className="portal-sort-button settings-v2-modal-action"
                onClick={clearAvatarCropDraft}
                disabled={isAvatarProcessing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="portal-action-button settings-v2-modal-action"
                onClick={handleAvatarCropConfirm}
                disabled={isAvatarProcessing}
              >
                {isAvatarProcessing ? (
                  <>
                    Saving
                  </>
                ) : (
                  <>
                    <Camera size={14} aria-hidden="true" />
                    Use photo
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Wallet Logout Confirmation Modal */}
      {showLogoutConfirm && (
        <div className="settings-v2-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="settings-wallet-disconnect-title">
          <div className="settings-v2-confirm-modal settings-v2-confirm-modal--compact">
            <div className="settings-v2-confirm-modal__header settings-v2-confirm-modal__header--compact">
              <div className="settings-v2-confirm-modal__icon settings-v2-confirm-modal__icon--wallet">
                <LogOut size={16} aria-hidden="true" />
              </div>
              <h3 id="settings-wallet-disconnect-title" className="settings-v2-confirm-modal__title settings-v2-confirm-modal__title--compact">Disconnect wallet</h3>
            </div>
            <p className="settings-v2-confirm-modal__copy">
              Disconnect this wallet? You will need to sign in again to open the portal.
            </p>
            <div className="settings-v2-confirm-modal__actions">
              <button
                type="button"
                className="portal-sort-button settings-v2-modal-action"
                onClick={() => setShowLogoutConfirm(false)}
              >
                Cancel
              </button>
              <button type="button" className="settings-v2-danger-button settings-v2-modal-action" onClick={handleConfirmLogout}>
                Disconnect
              </button>
            </div>
          </div>
        </div>
      )}
    </PortalPage>
  );
}
