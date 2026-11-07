import { TrendingUp, Crown, Star, MapPin, Trophy, ArrowRight } from 'lucide-react';
import { BeetleButton } from '../ui/beetle-button';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
} from '../ui/responsive-modal';
import { useFormatters } from '../../hooks/useFormatters';
import { formatIdentifier, formatInteger, formatPercent, formatTokenAmount, formatWatts } from '../../lib/formatters';

interface ClimbDetailModalProps {
  climb: {
    id: string;
    name: string;
    location: string;
    distance: number;
    elevation: number;
    grade: number;
    attempts: number;
    personalRecord: {
      time: string;
      date: string;
      avgPower: number;
      dung: number;
      rank?: number;
    } | null;
    kom: {
      time: string;
      holder: string;
      beetleNumber: number;
    };
    isStarred: boolean;
    hasKOM: boolean;
  };
  onClose: () => void;
  onViewFull: () => void;
}

export default function ClimbDetailModal({ climb, onClose, onViewFull }: ClimbDetailModalProps) {
  const { distance: formatDistance, elevation: formatElevation } = useFormatters();
  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader className="climb-detail-modal-header">
        <div className="climb-detail-modal-title-row">
          {climb.isStarred && (
            <Star className="climb-detail-modal-title-icon climb-detail-modal-title-icon--starred" fill="currentColor" />
          )}
          <ResponsiveModalTitle className="climb-detail-modal-title">
            {climb.name}
          </ResponsiveModalTitle>
          {climb.hasKOM && (
            <Crown className="climb-detail-modal-title-icon climb-detail-modal-title-icon--kom" fill="currentColor" />
          )}
        </div>
        <ResponsiveModalDescription className="climb-detail-modal-location">
          <MapPin className="climb-detail-modal-location__icon" aria-hidden="true" />
          <span>{climb.location}</span>
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="climb-detail-modal-body">
        {/* Climb Stats */}
        <div className="climb-detail-modal-stats">
          <div className="climb-detail-modal-section-label">
            <TrendingUp className="climb-detail-modal-section-label__icon" />
            Climb Stats
          </div>
          <div className="climb-detail-modal-stat-grid">
            <div className="climb-detail-modal-stat">
              <div className="climb-detail-modal-stat__value">
                {formatDistance(climb.distance * 1000)}
              </div>
              <div className="climb-detail-modal-stat__label">
                Distance
              </div>
            </div>
            <div className="climb-detail-modal-stat">
              <div className="climb-detail-modal-stat__value">
                {formatElevation(climb.elevation)}
              </div>
              <div className="climb-detail-modal-stat__label">
                Elevation
              </div>
            </div>
            <div className="climb-detail-modal-stat">
              <div className="climb-detail-modal-stat__value">
                {formatPercent(climb.grade)}
              </div>
              <div className="climb-detail-modal-stat__label">
                Avg Grade
              </div>
            </div>
            <div className="climb-detail-modal-stat">
              <div className="climb-detail-modal-stat__value">
                {formatInteger(climb.attempts)}
              </div>
              <div className="climb-detail-modal-stat__label">
                Your Attempts
              </div>
            </div>
          </div>
        </div>

        {/* Personal Record */}
        {climb.personalRecord && (
          <div className="climb-detail-modal-pr-panel">
            <div className="climb-detail-modal-pr-label">
              <Trophy className="climb-detail-modal-pr-label__icon" />
              Your PR
            </div>
            <div className="climb-detail-modal-pr-grid">
              <div className="climb-detail-modal-pr-metric">
                <div className="climb-detail-modal-pr-metric__value">
                  {climb.personalRecord.time}
                </div>
                <div className="climb-detail-modal-pr-metric__label">
                  Best Time
                </div>
              </div>
              {(climb.personalRecord.rank ?? 0) > 0 && (
                <div className="climb-detail-modal-pr-metric">
                  <div className="climb-detail-modal-pr-metric__value">
                    #{formatInteger(climb.personalRecord.rank)}
                  </div>
                  <div className="climb-detail-modal-pr-metric__label">
                    Your Rank
                  </div>
                </div>
              )}
              <div className="climb-detail-modal-pr-metric">
                <div className="climb-detail-modal-pr-metric__value climb-detail-modal-pr-metric__value--cal">
                  {formatTokenAmount(climb.personalRecord.dung)}
                </div>
                <div className="climb-detail-modal-pr-metric__label">
                  CAL counted
                </div>
              </div>
            </div>
            <div className="climb-detail-modal-pr-meta">
              <div className="climb-detail-modal-pr-meta-row">
                <span className="climb-detail-modal-pr-meta__date">
                  <span>Set on</span>
                  {' '}
                  <span className="climb-detail-modal-pr-meta__date-value">{climb.personalRecord.date}</span>
                </span>
                <span className="climb-detail-modal-pr-meta__power">
                  {formatWatts(climb.personalRecord.avgPower)} avg
                </span>
              </div>
            </div>
          </div>
        )}

        {/* KOM/QOM */}
        <div
          className={`climb-detail-modal-kom-panel ${climb.hasKOM ? 'climb-detail-modal-kom-panel--owned' : 'climb-detail-modal-kom-panel--standard'}`}
        >
          <div className="climb-detail-modal-kom-label">
            <Crown className="climb-detail-modal-kom-label__icon" />
            {climb.hasKOM ? 'You Hold the KOM!' : 'Current KOM'}
          </div>
          <div className="climb-detail-modal-kom-row">
            <div className="climb-detail-modal-kom-time-group">
              <div className="climb-detail-modal-kom-time">
                {climb.kom.time}
              </div>
              <div className="climb-detail-modal-kom-caption">
                {climb.hasKOM ? 'Your best time!' : `Held by ${climb.kom.holder}`}
              </div>
            </div>
            <div className="climb-detail-modal-kom-holder">
              <div className="climb-detail-modal-kom-beetle-number">
                Beetle #{formatIdentifier(climb.kom.beetleNumber)}
              </div>
              <div className="climb-detail-modal-kom-beetle-mark" aria-hidden="true">BR</div>
            </div>
          </div>
        </div>
      </ResponsiveModalBody>

      <ResponsiveModalFooter className="climb-detail-modal-footer">
        <BeetleButton
          variant="secondary"
          onClick={onClose}
          className="climb-detail-modal-footer-button"
        >
          Close
        </BeetleButton>
        <BeetleButton
          variant="primary"
          onClick={onViewFull}
          className="climb-detail-modal-footer-button climb-detail-modal-footer-button--primary"
        >
          <span>View Full Climb</span>
          <ArrowRight className="climb-detail-modal-footer-button__icon" aria-hidden="true" />
        </BeetleButton>
      </ResponsiveModalFooter>
    </ResponsiveModal>
  );
}
