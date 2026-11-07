import { useEffect, useRef, useState, type FormEvent } from 'react';

import { useAuth } from '../../contexts/AuthContext';
import { ApiError } from '../../lib/api';
import { BeetleButton } from '../ui/beetle-button';
import { BeetleInput } from '../ui/beetle-input';
import { ArrowRight, Mountain } from 'lucide-react';
import { AuthHeader, AuthNavigation, AuthNotice, AuthStatus } from './AuthSurface';

export type FirstRunDestination = '/' | '/climbs' | '/upload';
export type FirstRunStep = 'identity' | 'first_ride';
export type IdentitySaveOutcome = 'first_ride' | 'redirected';

interface SetupModalProps {
  initialStep?: FirstRunStep;
  onComplete: (destination: FirstRunDestination) => void | Promise<void>;
  onIdentitySaved: () => IdentitySaveOutcome | Promise<IdentitySaveOutcome>;
}

type PendingAction = FirstRunDestination | 'identity' | null;

function riderNameError(error: unknown) {
  if (!(error instanceof ApiError) || error.statusCode !== 400) {
    return 'Could not save your rider name.';
  }

  const message = error.message.toLowerCase();
  if (message.includes('already taken')) return 'That rider name is already taken.';
  if (message.includes('reserved')) return 'That rider name is reserved.';
  if (message.includes('3-20') || message.includes('3–20')) {
    return 'Use 3–20 letters, numbers, or underscores.';
  }

  return 'Could not save your rider name.';
}

function destinationError(destination: FirstRunDestination) {
  if (destination === '/upload') return 'Could not open ride upload.';
  if (destination === '/climbs') return 'Could not open climbs.';
  return 'Could not continue.';
}

export default function SetupModal({
  initialStep = 'identity',
  onComplete,
  onIdentitySaved,
}: SetupModalProps) {
  const { updatePreferences } = useAuth();
  const [step, setStep] = useState<FirstRunStep>(initialStep);
  const [riderName, setRiderName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [errorAction, setErrorAction] = useState<FirstRunDestination | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const riderNameInputRef = useRef<HTMLInputElement>(null);
  const firstRideHeadingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (step === 'identity') {
      riderNameInputRef.current?.focus();
      return;
    }

    firstRideHeadingRef.current?.focus();
  }, [step]);

  const handleIdentitySubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pendingAction) return;

    const username = riderName.trim().toLowerCase();
    if (!username) {
      setError('Enter a rider name.');
      riderNameInputRef.current?.focus();
      return;
    }
    if (!/^[a-z0-9_]{3,20}$/.test(username)) {
      setError('Use 3–20 letters, numbers, or underscores.');
      riderNameInputRef.current?.focus();
      return;
    }

    setError(null);
    setErrorAction(null);
    setPendingAction('identity');

    try {
      await updatePreferences({ username });
    } catch (saveError) {
      setError(riderNameError(saveError));
      setPendingAction(null);
      return;
    }

    try {
      const outcome = await onIdentitySaved();
      if (outcome === 'first_ride') {
        setStep('first_ride');
      }
    } catch {
      setError('Could not finish sign-in.');
    } finally {
      setPendingAction(null);
    }
  };

  const openDestination = async (destination: FirstRunDestination) => {
    if (pendingAction) return;

    setError(null);
    setErrorAction(null);
    setPendingAction(destination);

    try {
      await onComplete(destination);
    } catch {
      setError(destinationError(destination));
      setErrorAction(destination);
      setPendingAction(null);
    }
  };

  const heading = step === 'identity' ? 'Rider name' : 'First ride';

  return (
    <main className="invite-gate access-gate first-run-onboarding">
      <div className="access-entry-page access-entry-page--app-threshold first-run-onboarding__page" data-public-meta-shape="app-entry">
        <AuthHeader />
        <section className="access-entry-page__intro" aria-labelledby="first-run-title">
          <div className="auth-entry-heading">
            <div className="auth-entry-back-space" aria-hidden="true" />
            <h1 id="first-run-title" ref={step === 'first_ride' ? firstRideHeadingRef : undefined} tabIndex={step === 'first_ride' ? -1 : undefined}>{heading}</h1>
          </div>
          <AuthStatus>{pendingAction === 'identity' ? 'Saving' : pendingAction ? 'Opening' : ''}</AuthStatus>
          <div className="first-run-onboarding__panel">
            {step === 'identity' ? (
              <>
                <form noValidate className="auth-entry-sheet first-run-onboarding__form" onSubmit={handleIdentitySubmit}>
                  <div className="auth-entry-field">
                    <label htmlFor="first-run-rider-name">Rider name</label>
                    <BeetleInput ref={riderNameInputRef} id="first-run-rider-name" name="nickname" autoCapitalize="none" autoComplete="nickname"
                      maxLength={20} spellCheck={false} value={riderName} disabled={Boolean(pendingAction)}
                      onChange={(event) => { setRiderName(event.target.value); setError(null); setErrorAction(null); }}
                      aria-describedby={error ? 'first-run-helper first-run-error' : 'first-run-helper'} error={Boolean(error)} />
                  </div>
                  {error && <AuthNotice id="first-run-error" tone="error">{error}</AuthNotice>}
                  <BeetleButton type="submit" variant="primary" className="auth-entry-action" disabled={Boolean(pendingAction)} isLoading={pendingAction === 'identity'} loadingLabel="Saving">Continue</BeetleButton>
                </form>
                <p id="first-run-helper" className="auth-entry-footer">Shown with your rides and leaderboard positions.</p>
              </>
            ) : (
              <div role="group" aria-label="First ride choices">
                <div className="auth-entry-sheet">
                  {error && <AuthNotice id="first-run-error" tone="error">{error}</AuthNotice>}
                  <BeetleButton type="button" variant="primary" className="auth-entry-action" disabled={Boolean(pendingAction)}
                    isLoading={pendingAction === '/upload'} loadingLabel="Opening" aria-describedby={errorAction === '/upload' ? 'first-run-error' : undefined}
                    onClick={() => void openDestination('/upload')}>Upload ride</BeetleButton>
                </div>
                <p className="auth-entry-footer">Upload a ride to see its climbs, times, and leaderboard positions.</p>
                <div className="auth-entry-sheet">
                  <AuthNavigation icon={<Mountain aria-hidden="true" />} disabled={Boolean(pendingAction)} aria-busy={pendingAction === '/climbs' || undefined}
                    aria-describedby={errorAction === '/climbs' ? 'first-run-error' : undefined} onClick={() => void openDestination('/climbs')}>
                    {pendingAction === '/climbs' ? 'Opening climbs' : 'Browse climbs'}
                  </AuthNavigation>
                  <AuthNavigation icon={<ArrowRight aria-hidden="true" />} disabled={Boolean(pendingAction)} aria-busy={pendingAction === '/' || undefined}
                    aria-describedby={errorAction === '/' ? 'first-run-error' : undefined} onClick={() => void openDestination('/')}>
                    {pendingAction === '/' ? 'Opening Home' : 'Continue without upload'}
                  </AuthNavigation>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
