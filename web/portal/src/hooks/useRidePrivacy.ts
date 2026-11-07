import { useCallback, useEffect, useState } from 'react';
import {
  api,
  type MapHideDistanceM,
  type PrivacySettings,
  type RidePrivacyChoice,
  type RideMapVisibility,
  type RideVisibility,
} from '../lib/api';

interface RidePrivacyLoadState {
  settings: PrivacySettings | null;
  choice: RidePrivacyChoice | null;
  shareWkg: boolean;
  setShareWkg: (share: boolean) => void;
  isLoading: boolean;
  error: string | null;
  setChoice: (choice: RidePrivacyChoice) => void;
  reload: () => void;
}

const RIDE_VISIBILITIES = new Set<RideVisibility>(['public', 'followers', 'private']);
const MAP_VISIBILITIES = new Set<RideMapVisibility>(['show_all', 'hide_start_end', 'hide_entire']);
const MAP_HIDE_DISTANCES = new Set<MapHideDistanceM>([0, 200, 400, 800, 1600]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseRidePrivacyChoice(value: unknown): RidePrivacyChoice | null {
  if (!isRecord(value)) return null;
  const visibility = value.visibility;
  const mapVisibility = value.mapVisibility;
  const mapHideStartM = value.mapHideStartM;
  const mapHideEndM = value.mapHideEndM;
  if (
    typeof visibility !== 'string'
    || !RIDE_VISIBILITIES.has(visibility as RideVisibility)
    || typeof mapVisibility !== 'string'
    || !MAP_VISIBILITIES.has(mapVisibility as RideMapVisibility)
    || typeof mapHideStartM !== 'number'
    || !Number.isInteger(mapHideStartM)
    || !MAP_HIDE_DISTANCES.has(mapHideStartM as MapHideDistanceM)
    || typeof mapHideEndM !== 'number'
    || !Number.isInteger(mapHideEndM)
    || !MAP_HIDE_DISTANCES.has(mapHideEndM as MapHideDistanceM)
    || (
      mapVisibility === 'hide_start_end'
      && (mapHideStartM === 0 || mapHideEndM === 0)
    )
  ) {
    return null;
  }
  return {
    visibility: visibility as RideVisibility,
    mapVisibility: mapVisibility as RideMapVisibility,
    mapHideStartM: mapHideStartM as MapHideDistanceM,
    mapHideEndM: mapHideEndM as MapHideDistanceM,
  };
}

function parsePrivacySettings(value: unknown): PrivacySettings | null {
  if (!isRecord(value)) return null;
  const choice = parseRidePrivacyChoice({
    visibility: value.defaultRideVisibility,
    mapVisibility: value.defaultMapVisibility,
    mapHideStartM: value.defaultMapHideStartM,
    mapHideEndM: value.defaultMapHideEndM,
  });
  const protocolPublicFields = value.protocolPublicFields;
  if (
    !choice
    || value.contractVersion !== 'privacy.v2'
    || (value.shareWkg !== undefined && typeof value.shareWkg !== 'boolean')
    || (value.profileVisibility !== 'public' && value.profileVisibility !== 'private')
    || value.defaultsApplyTo !== 'future_rides'
    || value.providerPrivacyInherited !== false
    || typeof value.privacyZoneCount !== 'number'
    || !Number.isInteger(value.privacyZoneCount)
    || value.privacyZoneCount < 0
    || value.privacyZonesLoaded !== true
    || value.rideOverrideMode !== 'optional'
    || !Array.isArray(protocolPublicFields)
    || !protocolPublicFields.every((field) => typeof field === 'string')
  ) {
    return null;
  }
  return { ...value, shareWkg: value.shareWkg === true } as unknown as PrivacySettings;
}

export function buildPrivacySettingsUpdate(
  choice: RidePrivacyChoice | null,
  settings: PrivacySettings | null,
  shareWkg?: boolean,
): Parameters<typeof api.updatePrivacySettings>[0] {
  if (!choice || !settings) return {};
  const updates: Parameters<typeof api.updatePrivacySettings>[0] = {};
  if (shareWkg !== undefined && shareWkg !== settings.shareWkg) {
    updates.shareWkg = shareWkg;
  }
  if (choice.visibility !== settings.defaultRideVisibility) {
    updates.defaultRideVisibility = choice.visibility;
  }
  if (choice.mapVisibility !== settings.defaultMapVisibility) {
    updates.defaultMapVisibility = choice.mapVisibility;
  }
  if (choice.mapHideStartM !== settings.defaultMapHideStartM) {
    updates.defaultMapHideStartM = choice.mapHideStartM;
  }
  if (choice.mapHideEndM !== settings.defaultMapHideEndM) {
    updates.defaultMapHideEndM = choice.mapHideEndM;
  }
  return updates;
}

export function useRidePrivacy(enabled = true): RidePrivacyLoadState {
  const [settings, setSettings] = useState<PrivacySettings | null>(null);
  const [choice, setChoice] = useState<RidePrivacyChoice | null>(null);
  const [shareWkg, setShareWkg] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setSettings(null);
      setChoice(null);
      setShareWkg(false);
      setError(null);
      setIsLoading(false);
      return undefined;
    }
    let active = true;
    setIsLoading(true);
    setError(null);

    api.getPrivacySettings()
      .then((response) => {
        if (!active) return;
        const settings = parsePrivacySettings(response);
        if (!settings) {
          throw new Error('privacy_contract_unavailable');
        }
        setSettings(settings);
        setShareWkg(settings.shareWkg);
        setChoice({
          visibility: settings.defaultRideVisibility,
          mapVisibility: settings.defaultMapVisibility,
          mapHideStartM: settings.defaultMapHideStartM,
          mapHideEndM: settings.defaultMapHideEndM,
        });
      })
      .catch(() => {
        if (!active) return;
        setSettings(null);
        setChoice(null);
        setShareWkg(false);
        setError('Privacy settings unavailable. Try again before uploading.');
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [enabled, loadVersion]);

  const reload = useCallback(() => {
    setLoadVersion((version) => version + 1);
  }, []);

  return {
    settings,
    choice,
    shareWkg,
    setShareWkg,
    isLoading,
    error,
    setChoice,
    reload,
  };
}
