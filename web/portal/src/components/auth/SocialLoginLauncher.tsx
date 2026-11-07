import SocialLoginRuntime from './SocialLoginRuntime';
import type { AuthTransactionMethod, AuthTransactionStage } from '../../lib/authTransaction';

interface SocialLoginLauncherProps {
  authTransactionId?: string;
  authTransactionMethod?: AuthTransactionMethod;
  authTransactionStage?: AuthTransactionStage;
  autoSendCode?: boolean;
  hasValidatedInvite?: boolean;
  initialEmail?: string;
  onEmailChange?: (email: string) => void;
  inviteCode?: string | null;
  inviteRecoveryPending?: boolean;
  onBack: () => void;
  onAuthenticatedSessionResume?: () => void;
  onInviteRecovery: () => Promise<boolean>;
  onSignupRefused: () => void;
  onClose: () => void;
  resumeAuthenticatedSession?: boolean;
}

export default function SocialLoginLauncher(props: SocialLoginLauncherProps) {
  return <SocialLoginRuntime {...props} />;
}
