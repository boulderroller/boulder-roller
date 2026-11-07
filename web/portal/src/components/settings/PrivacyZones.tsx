import { SlotRows } from '../loading/Slot';
/**
 * PrivacyZones - Settings component for GPS privacy zones
 *
 * Strava-clone approach:
 * - Up to 5 privacy zones per user
 * - Browser location or manually entered coordinates
 * - Radius choice: 200m, 400m, 800m, 1600m
 */

import { useState, useEffect, useRef } from 'react';
import { BeetleButton } from '../ui/beetle-button';
import { MapPin, Plus, Trash2, Shield, Edit2, X, Check } from 'lucide-react';
import { api } from '../../lib/api';
import { toast } from 'sonner';
import { cn } from '../ui/utils';
import { useFormatters } from '../../hooks/useFormatters';
import { formatCoordinate, formatInteger } from '../../lib/formatters';

interface PrivacyZone {
  id: string;
  latitude: number;
  longitude: number;
  radiusM: number;
  label?: string;
  createdAt: string;
  updatedAt: string;
}

const RADIUS_OPTIONS = [
  { value: 200, desc: 'Small area' },
  { value: 400, desc: 'Medium area' },
  { value: 800, desc: 'Large area' },
  { value: 1600, desc: 'Extra large' },
];

const MAX_ZONES = 5;

type CoordinateResult =
  | { coordinates: { latitude: number; longitude: number }; error?: never }
  | { coordinates?: never; error: string };

function parseCoordinates(latitudeValue: string, longitudeValue: string): CoordinateResult {
  if (!latitudeValue.trim() || !longitudeValue.trim()) {
    return { error: 'Enter both latitude and longitude.' };
  }

  const latitude = Number(latitudeValue);
  const longitude = Number(longitudeValue);

  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
    return { error: 'Latitude must be a number from -90 to 90.' };
  }

  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    return { error: 'Longitude must be a number from -180 to 180.' };
  }

  return { coordinates: { latitude, longitude } };
}

export function PrivacyZones({ onZonesChanged }: { onZonesChanged?: () => void }) {
  const { distance: formatDistance } = useFormatters();
  const [zones, setZones] = useState<PrivacyZone[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  // Form state
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [selectedRadius, setSelectedRadius] = useState(400);
  const [label, setLabel] = useState('');
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const locationRequestIdRef = useRef(0);

  // Fetch zones on mount
  useEffect(() => {
    const fetchZones = async () => {
      try {
        setLoading(true);
        const response = await api.get<{ zones: PrivacyZone[]; maxZones: number }>('/privacy/zones');
        setZones(response.zones || []);
      } catch {
        toast.error('Could not load privacy zones');
      } finally {
        setLoading(false);
      }
    };
    fetchZones();
  }, []);

  useEffect(() => () => {
    locationRequestIdRef.current += 1;
  }, []);

  const resetForm = () => {
    locationRequestIdRef.current += 1;
    setLatitude('');
    setLongitude('');
    setLabel('');
    setSelectedRadius(400);
    setLocating(false);
    setLocationError(null);
  };

  const showLocationError = (message: string) => {
    setLocationError(message);
    toast.error(message);
  };

  const handleUseCurrentLocation = () => {
    if (!navigator.geolocation) {
      showLocationError('Current location is not available in this browser. Enter coordinates instead.');
      return;
    }

    const locationRequestId = locationRequestIdRef.current + 1;
    locationRequestIdRef.current = locationRequestId;
    setLocating(true);
    setLocationError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (locationRequestIdRef.current !== locationRequestId) {
          return;
        }

        const nextLatitude = String(position.coords.latitude);
        const nextLongitude = String(position.coords.longitude);
        const result = parseCoordinates(nextLatitude, nextLongitude);

        if (!result.coordinates) {
          showLocationError('The browser returned an invalid location. Enter coordinates instead.');
          setLocating(false);
          return;
        }

        setLatitude(nextLatitude);
        setLongitude(nextLongitude);
        setLocating(false);
      },
      (error) => {
        if (locationRequestIdRef.current !== locationRequestId) {
          return;
        }

        const message = error.code === error.PERMISSION_DENIED
          ? 'Location permission was denied. Enter coordinates instead.'
          : error.code === error.TIMEOUT
            ? 'Getting your location timed out. Enter coordinates instead.'
            : 'Current location is unavailable. Enter coordinates instead.';
        showLocationError(message);
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  };

  const handleAddZone = async () => {
    const result = parseCoordinates(latitude, longitude);
    if (!result.coordinates) {
      showLocationError(result.error);
      return;
    }

    try {
      setSaving(true);
      setLocationError(null);
      const response = await api.post<PrivacyZone>('/privacy/zones', {
        latitude: result.coordinates.latitude,
        longitude: result.coordinates.longitude,
        radius_m: selectedRadius,
        label: label.trim() || undefined,
      });

      setZones((currentZones) => [...currentZones, response]);
      onZonesChanged?.();
      setAdding(false);
      resetForm();
      toast.success('Privacy zone added');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not add privacy zone');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteZone = async (id: string) => {
    try {
      await api.delete(`/privacy/zones/${id}`);
      setZones((currentZones) => currentZones.filter((zone) => zone.id !== id));
      onZonesChanged?.();
      toast.success('Privacy zone removed');
    } catch {
      toast.error('Could not remove privacy zone');
    }
  };

  const handleUpdateZone = async (id: string, updates: Partial<PrivacyZone>) => {
    try {
      const response = await api.put<PrivacyZone>(`/privacy/zones/${id}`, updates);
      setZones((currentZones) => currentZones.map((zone) => (zone.id === id ? response : zone)));
      onZonesChanged?.();
      setEditingId(null);
      toast.success('Privacy zone updated');
    } catch {
      toast.error('Could not update privacy zone');
    }
  };

  if (loading) {
    return (
      <div className="settings-v2-privacy-zones__loading" aria-label="Loading privacy zones">
        <SlotRows count={3} />
      </div>
    );
  }

  return (
    <div className="settings-v2-privacy-zones">
      {/* Header */}
      <div className="settings-v2-privacy-zones__header">
        <div className="settings-v2-privacy-zones__heading">
          <Shield className="settings-v2-privacy-zones__heading-icon" aria-hidden="true" />
          <h3 className="settings-v2-privacy-zones__title">
            Privacy zones
          </h3>
        </div>
        <span className="settings-v2-privacy-zones__count">
          {formatInteger(zones.length)}/{formatInteger(MAX_ZONES)}
        </span>
      </div>

      <p className="settings-v2-privacy-zones__copy">
        GPS data inside these zones is hidden from public maps.
        Your rides still count.
      </p>

      {/* Existing zones */}
      <div className="settings-v2-privacy-zone-list">
        {zones.map((zone) => (
          <div
            key={zone.id}
            className="settings-v2-privacy-zone-card"
          >
            <div className="settings-v2-privacy-zone-card__main">
              <div className="settings-v2-privacy-zone-card__icon">
                <MapPin size={16} aria-hidden="true" />
              </div>
              <div className="settings-v2-privacy-zone-card__content">
                <div className="settings-v2-privacy-zone-card__title">
                  {zone.label || 'Privacy zone'}
                </div>
                <div className="settings-v2-privacy-zone-card__meta">
                  {formatCoordinate(zone.latitude)}, {formatCoordinate(zone.longitude)} ({formatDistance(zone.radiusM)} radius)
                </div>
              </div>
            </div>

            <div className="settings-v2-privacy-zone-card__actions">
              {editingId === zone.id ? (
                <>
                  <select
                    value={zone.radiusM}
                    onChange={(e) => handleUpdateZone(zone.id, { radius_m: parseInt(e.target.value) as 200 | 400 | 800 | 1600 })}
                    className="settings-v2-privacy-zone-card__select"
                    aria-label="Privacy zone radius"
                  >
                    {RADIUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {formatDistance(opt.value)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="settings-v2-privacy-zone-card__icon-button settings-v2-privacy-zone-card__icon-button--success"
                    aria-label="Finish editing privacy zone"
                  >
                    <Check size={16} aria-hidden="true" />
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setEditingId(zone.id)}
                    className="settings-v2-privacy-zone-card__icon-button"
                    aria-label="Edit privacy zone radius"
                  >
                    <Edit2 size={16} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteZone(zone.id)}
                    className="settings-v2-privacy-zone-card__icon-button settings-v2-privacy-zone-card__icon-button--danger"
                    aria-label="Delete privacy zone"
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Add zone form */}
      {adding ? (
        <div className="settings-v2-privacy-zone-form">
          <div className="settings-v2-privacy-zone-form__header">
            <span className="settings-v2-privacy-zone-form__title">
              Add privacy zone
            </span>
            <button
              type="button"
              onClick={() => {
                setAdding(false);
                resetForm();
              }}
              className="settings-v2-privacy-zone-card__icon-button"
              aria-label="Cancel adding privacy zone"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>

          <div className="settings-v2-privacy-zone-field">
            <label
              htmlFor="privacy-zone-label"
              className="settings-v2-privacy-zone-field__label"
            >
              Label (optional)
            </label>
            <input
              id="privacy-zone-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g., Trailhead"
              className="settings-v2-privacy-zone-field__input"
            />
          </div>

          <div className="settings-v2-privacy-zone-field">
            <p
              id="privacy-zone-location-help"
              className="settings-v2-privacy-zones__copy"
            >
              This location is sent only to Boulder Roller to hide ride endpoints.
            </p>
            <button
              type="button"
              onClick={handleUseCurrentLocation}
              disabled={locating || saving}
              className="portal-sort-button"
            >
              <MapPin size={14} aria-hidden="true" />
              {locating ? 'Getting location…' : 'Use current location'}
            </button>
          </div>

          <div className="settings-v2-privacy-zone-field">
            <label
              htmlFor="privacy-zone-latitude"
              className="settings-v2-privacy-zone-field__label"
            >
              Latitude
            </label>
            <input
              id="privacy-zone-latitude"
              type="text"
              inputMode="decimal"
              value={latitude}
              onChange={(e) => {
                setLatitude(e.target.value);
                setLocationError(null);
              }}
              placeholder="e.g., 39.952583"
              autoComplete="off"
              aria-describedby={`privacy-zone-location-help${locationError ? ' privacy-zone-location-error' : ''}`}
              className="settings-v2-privacy-zone-field__input"
            />
          </div>

          <div className="settings-v2-privacy-zone-field">
            <label
              htmlFor="privacy-zone-longitude"
              className="settings-v2-privacy-zone-field__label"
            >
              Longitude
            </label>
            <input
              id="privacy-zone-longitude"
              type="text"
              inputMode="decimal"
              value={longitude}
              onChange={(e) => {
                setLongitude(e.target.value);
                setLocationError(null);
              }}
              placeholder="e.g., -75.165222"
              autoComplete="off"
              aria-describedby={`privacy-zone-location-help${locationError ? ' privacy-zone-location-error' : ''}`}
              className="settings-v2-privacy-zone-field__input"
            />
          </div>

          {locationError && (
            <p
              id="privacy-zone-location-error"
              role="alert"
              className="settings-v2-privacy-zones__copy"
            >
              {locationError}
            </p>
          )}

          <div className="settings-v2-privacy-zone-field">
            <label
              className="settings-v2-privacy-zone-field__label"
            >
              Radius
            </label>
            <div className="settings-v2-privacy-zone-radius-grid">
              {RADIUS_OPTIONS.map((opt) => (
                <button
                  type="button"
                  key={opt.value}
                  onClick={() => setSelectedRadius(opt.value)}
                  aria-pressed={selectedRadius === opt.value}
                  className={cn(
                    'settings-v2-privacy-zone-radius-option',
                    selectedRadius === opt.value && 'settings-v2-privacy-zone-radius-option--active',
                  )}
                >
                  <div className="settings-v2-privacy-zone-radius-option__value">
                    {formatDistance(opt.value)}
                  </div>
                  <div className="settings-v2-privacy-zone-radius-option__desc">
                    {opt.desc}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <BeetleButton
            onClick={handleAddZone}
            isLoading={saving}
            loadingLabel="Adding zone"
            disabled={!latitude.trim() || !longitude.trim() || locating || saving}
            variant="primary"
            size="sm"
            className="settings-v2-privacy-zone-form__submit"
          >
            <MapPin className="settings-v2-privacy-zone-form__submit-icon" aria-hidden="true" />
            Add zone
          </BeetleButton>
        </div>
      ) : zones.length < MAX_ZONES ? (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="portal-sort-button settings-v2-privacy-zone-add"
        >
          <Plus size={14} aria-hidden="true" />
          Add privacy zone
        </button>
      ) : (
        <p className="settings-v2-privacy-zones__max">
          Maximum {formatInteger(MAX_ZONES)} zones reached
        </p>
      )}
    </div>
  );
}
