import { useBrowserTitle } from '../../contexts/BrowserTitleContext';
import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../../lib/api';
import { getInviteCodeFromLocation, getPendingInviteCode, hasAccessSignInIntent } from '../../lib/authHandoff';
import AccessPanel from './AccessPanel';
import { AuthHeader } from './AuthSurface';

interface InviteGateProps {
  onRetrySessionCheck?: () => void;
  sessionCheckError?: string | null;
  sessionPending?: boolean;
}

export default function InviteGate({
  onRetrySessionCheck,
  sessionCheckError = null,
  sessionPending = false,
}: InviteGateProps) {
  useBrowserTitle('Sign in');
  const location = useLocation();
  useEffect(() => {
    if (location.state?.fromPublicPreview !== true) return;
    const frame = requestAnimationFrame(() =>
      document.getElementById('access-sign-in-email')?.focus(),
    );
    return () => cancelAnimationFrame(frame);
  }, [location.key, location.state]);
  const inviteCodeFromLocation = useMemo(
    () => getInviteCodeFromLocation(location),
    [location],
  );
  const [initialShowLoginOptions, setInitialShowLoginOptions] = useState(false);
  const [initialInviteValidated, setInitialInviteValidated] = useState(false);
  const [initialInviteCode, setInitialInviteCode] = useState<string | null>(null);

  useEffect(() => {
    if (sessionPending || sessionCheckError) return;

    let mounted = true;
    const bootstrapState = async () => {
      try {
        const onboarding = await api.getOnboardingState();
        if (!mounted) return;
        const pendingInviteCode = getPendingInviteCode();
        const inviteValidated = onboarding.inviteValidated;
        const inviteCodeToValidate = inviteValidated
          ? null
          : inviteCodeFromLocation || pendingInviteCode;
        const canShowLoginOptions = inviteValidated
          || (!inviteCodeToValidate && (hasAccessSignInIntent() || !onboarding.inviteRequired));
        setInitialShowLoginOptions(canShowLoginOptions);
        setInitialInviteValidated(inviteValidated);
        setInitialInviteCode(inviteCodeToValidate);
      } catch {
        // Fail closed to the entry panel.
        if (mounted) {
          setInitialInviteCode(inviteCodeFromLocation);
        }
      }
    };

    void bootstrapState();

    return () => {
      mounted = false;
    };
  }, [inviteCodeFromLocation, sessionCheckError, sessionPending]);

  return (
    <main className="invite-gate access-gate">
      <div className="access-entry-page access-entry-page--app-threshold" data-public-meta-shape="app-entry">
        <AuthHeader />

        <div className="access-entry-page__intro">
          <div className="access-entry-page__panel-slot">
            <AccessPanel
              initialInviteCode={initialInviteCode}
              initialInviteValidated={initialInviteValidated}
              initialShowLoginOptions={initialShowLoginOptions}
              onRetrySessionCheck={onRetrySessionCheck}
              sessionCheckError={sessionCheckError}
              sessionPending={sessionPending}
            />
          </div>
        </div>
      </div>
    </main>
  );
}
