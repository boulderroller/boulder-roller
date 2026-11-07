import type {
  MapHideDistanceM,
  RideMapVisibility,
  RidePrivacyChoice,
  RideVisibility,
} from '../../lib/api';
import { useFormatters } from '../../hooks/useFormatters';
import { formatInteger } from '../../lib/formatters';

export const AUDIENCE_OPTIONS: Array<{
  value: RideVisibility;
  label: string;
  detail: string;
}> = [
  { value: 'public', label: 'Everyone', detail: 'Anyone can open this ride.' },
  { value: 'followers', label: 'Followers', detail: 'Only you and your followers can open it.' },
  { value: 'private', label: 'Only you', detail: 'Only you can open it.' },
];

export const MAP_OPTIONS: Array<{
  value: RideMapVisibility;
  label: string;
}> = [
  { value: 'show_all', label: 'Show full map' },
  { value: 'hide_start_end', label: 'Hide first and last part' },
  { value: 'hide_entire', label: 'Hide entire map' },
];

const DISTANCES: MapHideDistanceM[] = [200, 400, 800, 1600];

interface RidePrivacyControlsProps {
  value: RidePrivacyChoice;
  onChange: (value: RidePrivacyChoice) => void;
  privacyZoneCount: number;
  disabled?: boolean;
  showProviderNotice?: boolean;
  idPrefix?: string;
  audienceLegend?: string;
  mapLegend?: string;
  /** A picker may show one group; Settings retains the complete controls. */
  section?: 'audience' | 'map';
}

export function ridePrivacySummary(
  value: RidePrivacyChoice,
  formatDistance: (meters: number) => string,
): string {
  const audience = AUDIENCE_OPTIONS.find((option) => option.value === value.visibility)?.label
    ?? 'Only you';
  if (value.mapVisibility === 'show_all') return `${audience} · Full map shown`;
  if (value.mapVisibility === 'hide_entire') return `${audience} · Map hidden`;
  if (value.mapHideStartM === value.mapHideEndM) {
    return `${audience} · First and last ${formatDistance(value.mapHideStartM)} hidden`;
  }
  return `${audience} · First ${formatDistance(value.mapHideStartM)} and last ${formatDistance(value.mapHideEndM)} hidden`;
}

export default function RidePrivacyControls({
  value,
  onChange,
  privacyZoneCount,
  disabled = false,
  showProviderNotice = false,
  idPrefix = 'ride-privacy',
  audienceLegend = 'Who can see this ride?',
  mapLegend = 'Map visibility',
  section,
}: RidePrivacyControlsProps) {
  const { distance: formatDistance } = useFormatters();
  const updateAudience = (visibility: RideVisibility) => {
    onChange({ ...value, visibility });
  };

  const updateMap = (mapVisibility: RideMapVisibility) => {
    if (mapVisibility === 'hide_start_end') {
      const distance = value.mapHideStartM || value.mapHideEndM || 200;
      onChange({
        ...value,
        mapVisibility,
        mapHideStartM: distance,
        mapHideEndM: distance,
      });
      return;
    }
    onChange({
      ...value,
      mapVisibility,
      mapHideStartM: 0,
      mapHideEndM: 0,
    });
  };

  const updateDistance = (distance: MapHideDistanceM) => {
    onChange({
      ...value,
      mapHideStartM: distance,
      mapHideEndM: distance,
    });
  };

  return (
    <div className="ride-privacy-controls">
      {section !== 'map' && <fieldset className="ride-privacy-controls__group" disabled={disabled}>
        <legend className={section ? 'sr-only' : undefined}>{audienceLegend}</legend>
        <div className="ride-privacy-controls__options">
          {AUDIENCE_OPTIONS.map((option) => {
            const id = `${idPrefix}-audience-${option.value}`;
            return (
              <label key={option.value} htmlFor={id} className="ride-privacy-controls__option">
                <input
                  id={id}
                  type="radio"
                  name={`${idPrefix}-audience`}
                  value={option.value}
                  aria-label={option.label}
                  checked={value.visibility === option.value}
                  onChange={() => updateAudience(option.value)}
                />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.detail}</small>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>}

      {section !== 'audience' && <fieldset className="ride-privacy-controls__group" disabled={disabled}>
        <legend className={section ? 'sr-only' : undefined}>{mapLegend}</legend>
        <div className="ride-privacy-controls__options">
          {MAP_OPTIONS.map((option) => {
            const id = `${idPrefix}-map-${option.value}`;
            return (
              <label key={option.value} htmlFor={id} className="ride-privacy-controls__option">
                <input
                  id={id}
                  type="radio"
                  name={`${idPrefix}-map`}
                  value={option.value}
                  aria-label={option.label}
                  checked={value.mapVisibility === option.value}
                  onChange={() => updateMap(option.value)}
                />
                <span><strong>{option.label}</strong></span>
              </label>
            );
          })}
        </div>

        {value.mapVisibility === 'hide_start_end' && (
          <label className="ride-privacy-controls__distance" htmlFor={`${idPrefix}-distance`}>
            <span>Distance at each end</span>
            <select
              id={`${idPrefix}-distance`}
              value={value.mapHideStartM}
              onChange={(event) => updateDistance(Number(event.target.value) as MapHideDistanceM)}
            >
              {DISTANCES.map((distance) => (
                <option key={distance} value={distance}>{formatDistance(distance)}</option>
              ))}
            </select>
          </label>
        )}
      </fieldset>}

      {!section && <>
      <p className="ride-privacy-controls__summary">{ridePrivacySummary(value, formatDistance).split(' · ')[1]}</p>
      <p className="ride-privacy-controls__zones">
        {privacyZoneCount === 0
          ? 'No privacy zones saved.'
          : `${formatInteger(privacyZoneCount)} privacy ${privacyZoneCount === 1 ? 'zone' : 'zones'} will also be applied.`}
      </p>
      {showProviderNotice && (
        <p className="ride-privacy-controls__provider-notice">
          Strava’s map visibility settings do not transfer. Boulder Roller applies the choices shown here.
        </p>
      )}
      </>}
    </div>
  );
}
