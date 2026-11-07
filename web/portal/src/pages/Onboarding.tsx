import { useEffect } from 'react';
import SetupModal, {
  type FirstRunDestination,
  type FirstRunStep,
  type IdentitySaveOutcome,
} from '../components/auth/SetupModal';

interface OnboardingProps {
  initialStep?: FirstRunStep;
  onComplete: (destination: FirstRunDestination) => void | Promise<void>;
  onIdentitySaved: () => IdentitySaveOutcome | Promise<IdentitySaveOutcome>;
  onReady?: () => void;
}

export default function Onboarding({
  initialStep,
  onComplete,
  onIdentitySaved,
  onReady,
}: OnboardingProps) {
  useEffect(() => {
    onReady?.();
  }, [onReady]);

  return (
    <SetupModal
      initialStep={initialStep}
      onComplete={onComplete}
      onIdentitySaved={onIdentitySaved}
    />
  );
}
