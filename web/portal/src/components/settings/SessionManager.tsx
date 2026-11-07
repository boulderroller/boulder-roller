import { useState, useEffect, useCallback } from 'react';
import { api, SessionInfo } from '../../lib/api';
import { toast } from 'sonner';
import { Monitor, Smartphone, Globe, Clock, X, LogOut, RefreshCw, Shield } from 'lucide-react';
import { cn } from '../ui/utils';
import { formatDateTime, formatInteger } from '../../lib/formatters';

// Parse user agent to get device info
function parseUserAgent(userAgent?: string): { device: string; browser: string; icon: typeof Monitor } {
  if (!userAgent) {
    return { device: 'Unknown device', browser: 'Unknown', icon: Monitor };
  }

  // Detect device type
  const isMobile = /Mobile|Android|iPhone|iPad/i.test(userAgent);
  const isTablet = /iPad|Tablet/i.test(userAgent);

  // Detect browser
  let browser = 'Unknown browser';
  if (userAgent.includes('Chrome')) browser = 'Chrome';
  else if (userAgent.includes('Safari')) browser = 'Safari';
  else if (userAgent.includes('Firefox')) browser = 'Firefox';
  else if (userAgent.includes('Edge')) browser = 'Edge';

  // Detect OS
  let os = 'Unknown';
  if (userAgent.includes('Mac OS')) os = 'macOS';
  else if (userAgent.includes('Windows')) os = 'Windows';
  else if (userAgent.includes('Android')) os = 'Android';
  else if (userAgent.includes('iPhone') || userAgent.includes('iPad')) os = 'iOS';
  else if (userAgent.includes('Linux')) os = 'Linux';

  const device = isMobile ? `${os} Mobile` : isTablet ? `${os} Tablet` : os;
  const icon = isMobile || isTablet ? Smartphone : Monitor;

  return { device, browser, icon };
}

export function SessionManager() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRevoking, setIsRevoking] = useState<string | null>(null);
  const [isRevokingAll, setIsRevokingAll] = useState(false);
  const [showRevokeAllConfirm, setShowRevokeAllConfirm] = useState(false);

  const fetchSessions = useCallback(async () => {
    try {
      const response = await api.listSessions();
      setSessions(response.sessions);
    } catch (error) {
      toast.error('Could not load sessions');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleRevokeSession = async (sessionId: string) => {
    setIsRevoking(sessionId);
    try {
      await api.revokeSession(sessionId);
      setSessions(sessions.filter(s => s.id !== sessionId));
      toast.success('Signed out of device');
    } catch (error) {
      toast.error('Could not sign out of device');
    } finally {
      setIsRevoking(null);
    }
  };

  const handleRevokeAllOther = async () => {
    setIsRevokingAll(true);
    try {
      const result = await api.revokeAllOtherSessions();
      setSessions(sessions.filter(s => s.isCurrent));
      toast.success(`Signed out of ${formatInteger(result.count)} other session${result.count !== 1 ? 's' : ''}`);
      setShowRevokeAllConfirm(false);
    } catch (error) {
      toast.error('Could not sign out of other devices');
    } finally {
      setIsRevokingAll(false);
    }
  };

  const otherSessionsCount = sessions.filter(s => !s.isCurrent).length;

  if (isLoading) {
    return (
      <div className="settings-v2-session-manager__loading">
        <RefreshCw className="settings-v2-session-manager__loading-icon settings-v2-inline-spin" aria-hidden="true" />
        <span>Loading devices...</span>
      </div>
    );
  }

  return (
    <div className="settings-v2-session-manager">
      {/* Header */}
      <div className="settings-v2-session-manager__header">
        <div className="settings-v2-session-manager__heading">
          <Shield className="settings-v2-session-manager__heading-icon" aria-hidden="true" />
          <div className="settings-v2-session-manager__heading-copy">
            <h4 className="settings-v2-session-manager__title">Signed-in devices</h4>
            <p className="settings-v2-session-manager__meta">
              {formatInteger(sessions.length)} device{sessions.length !== 1 ? 's' : ''} signed in
            </p>
          </div>
        </div>
        {otherSessionsCount > 0 && (
          <button
            type="button"
            onClick={() => setShowRevokeAllConfirm(true)}
            className="portal-sort-button settings-v2-session-manager__danger-command"
          >
            <LogOut size={14} aria-hidden="true" />
            Sign out everywhere
          </button>
        )}
      </div>

      {/* Sessions List */}
      <div className="settings-v2-session-list">
        {sessions.map((session) => {
          const { device, browser, icon: DeviceIcon } = parseUserAgent(session.userAgent);
          const isRevokeLoading = isRevoking === session.id;

          return (
            <div
              key={session.id}
              className={cn('settings-v2-session-row', session.isCurrent && 'settings-v2-session-row--current')}
            >
              <div className="settings-v2-session-row__main">
                <div className={cn('settings-v2-session-row__icon', session.isCurrent && 'settings-v2-session-row__icon--current')}>
                  <DeviceIcon size={20} aria-hidden="true" />
                </div>
                <div className="settings-v2-session-row__content">
                  <div className="settings-v2-session-row__title-line">
                    <h5 className="settings-v2-session-row__title">{device}</h5>
                    {session.isCurrent && (
                      <span className="settings-v2-session-row__badge">
                        This device
                      </span>
                    )}
                  </div>
                  <p className="settings-v2-session-row__browser">
                    {browser}
                    {session.locationHint && ` • ${session.locationHint}`}
                  </p>
                  <div className="settings-v2-session-row__details">
                    <span className="settings-v2-session-row__detail">
                      <Clock size={10} aria-hidden="true" />
                      Last seen: {formatDateTime(session.lastUsedAt || session.createdAt)}
                    </span>
                    {session.ipAddress && (
                      <span className="settings-v2-session-row__detail">
                        <Globe size={10} aria-hidden="true" />
                        {session.ipAddress}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              {!session.isCurrent && (
                <button
                  type="button"
                  onClick={() => handleRevokeSession(session.id)}
                  disabled={isRevokeLoading}
                  className="settings-v2-session-row__revoke"
                >
                  {isRevokeLoading ? (
                    <RefreshCw className="settings-v2-session-row__button-icon settings-v2-inline-spin" aria-hidden="true" />
                  ) : (
                    <X className="settings-v2-session-row__button-icon" aria-hidden="true" />
                  )}
                  {isRevokeLoading ? 'Signing out' : 'Sign out'}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {sessions.length === 0 && (
        <div className="settings-v2-session-empty">
          <p>No signed-in devices</p>
        </div>
      )}

      {/* Revoke All Confirmation Modal */}
      {showRevokeAllConfirm && (
        <div className="settings-v2-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="settings-session-revoke-title">
          <div className="settings-v2-confirm-modal settings-v2-confirm-modal--compact">
            <div className="settings-v2-confirm-modal__header settings-v2-confirm-modal__header--compact">
              <div className="settings-v2-confirm-modal__icon settings-v2-confirm-modal__icon--danger">
                <LogOut size={20} aria-hidden="true" />
              </div>
              <h3 id="settings-session-revoke-title" className="settings-v2-confirm-modal__title settings-v2-confirm-modal__title--compact">Sign out everywhere</h3>
            </div>
            <p className="settings-v2-confirm-modal__copy">
              This will sign you out of all other devices ({formatInteger(otherSessionsCount)} session{otherSessionsCount !== 1 ? 's' : ''}).
              You will remain signed in on this device.
            </p>
            <div className="settings-v2-confirm-modal__actions">
              <button
                type="button"
                className="portal-sort-button settings-v2-modal-action"
                onClick={() => setShowRevokeAllConfirm(false)}
                disabled={isRevokingAll}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRevokeAllOther}
                disabled={isRevokingAll}
                className="settings-v2-danger-button settings-v2-modal-action"
              >
                {isRevokingAll ? 'Signing out' : 'Sign out all'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
