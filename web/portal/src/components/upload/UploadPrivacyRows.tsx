import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import RidePrivacyControls, { AUDIENCE_OPTIONS, MAP_OPTIONS } from '../privacy/RidePrivacyControls';
import type { useRidePrivacy } from '../../hooks/useRidePrivacy';
import { useFormatters } from '../../hooks/useFormatters';
import { formatInteger, formatMeters } from '../../lib/formatters';
import { ResponsiveModal, ResponsiveModalHeader, ResponsiveModalTitle, ResponsiveModalDescription, ResponsiveModalBody } from '../ui/responsive-modal';

export default function UploadPrivacyRows({ privacy, frozen }: {
  privacy: ReturnType<typeof useRidePrivacy>;
  frozen: boolean;
}) {
  const navigate = useNavigate();
  const formatters = useFormatters();
  const [picker, setPicker] = useState<'audience' | 'map' | null>(null);
  const { choice, settings } = privacy;
  const audience = AUDIENCE_OPTIONS.find((option) => option.value === choice?.visibility);
  const map = MAP_OPTIONS.find((option) => option.value === choice?.mapVisibility);
  const pickerTitle = picker === 'audience' ? 'Who can see this ride?' : 'Map visibility';
  const distance = choice?.mapVisibility === 'hide_start_end'
    && choice.mapHideStartM === choice.mapHideEndM
    ? formatters.units === 'metric' ? formatMeters(choice.mapHideStartM) : formatters.distance(choice.mapHideStartM)
    : '';

  return <section className="upload-sheet__privacy" aria-label="Who can see this ride?">
    <h2 className="upload-sheet__privacy-heading">Who can see this ride?</h2>
    {privacy.error || (!privacy.isLoading && (!choice || !settings)) ? (
      <div className="upload-sheet__error" role="alert">
        <p>Privacy settings unavailable. Try again before uploading.</p>
        <button type="button" className="upload-sheet__word" onClick={privacy.reload} disabled={frozen}>Try again</button>
      </div>
    ) : (
      <div className="upload-sheet__group">
        <button type="button" className="upload-sheet__kv" onClick={() => setPicker('audience')} disabled={frozen || !choice || privacy.isLoading} aria-label="Who can see this ride?" aria-haspopup="dialog">
          <span>{audience?.label}<small>{audience?.detail}</small></span>
          {!frozen && choice && <span className="upload-sheet__chevron" aria-hidden="true">›</span>}
        </button>
        <button type="button" className="upload-sheet__kv" onClick={() => setPicker('map')} disabled={frozen || !choice || privacy.isLoading} aria-label="Map visibility" aria-haspopup="dialog">
          <span>Map visibility<small>{map?.label}</small></span>
          <span><span className="upload-sheet__value">{distance}</span>{!frozen && choice && <span className="upload-sheet__chevron" aria-hidden="true">›</span>}</span>
        </button>
        <button type="button" className="upload-sheet__kv" onClick={() => navigate('/settings?tab=privacy')} disabled={frozen || !settings || privacy.isLoading} aria-label="Privacy zones">
          <span>Privacy zones</span>
          <span><span className="upload-sheet__value">{settings ? formatInteger(settings.privacyZoneCount) : ''}</span>{!frozen && settings && <span className="upload-sheet__chevron" aria-hidden="true">›</span>}</span>
        </button>
      </div>
    )}
    {picker && choice && settings && !frozen && (
      <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) setPicker(null); }}>
        <ResponsiveModalHeader className="portal-sheet__bar">
          <ResponsiveModalTitle className="portal-sheet__bar-title">{pickerTitle}</ResponsiveModalTitle>
          <ResponsiveModalDescription className="sr-only">{pickerTitle}</ResponsiveModalDescription>
          <button type="button" className="portal-sheet__done" onClick={() => setPicker(null)}>Close</button>
        </ResponsiveModalHeader>
        <ResponsiveModalBody className="portal-sheet upload-sheet__picker">
          <RidePrivacyControls value={choice} onChange={privacy.setChoice} privacyZoneCount={settings.privacyZoneCount} section={picker} idPrefix="upload-privacy" />
        </ResponsiveModalBody>
      </ResponsiveModal>
    )}
  </section>;
}
