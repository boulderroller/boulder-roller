import { SignInDoor } from '../portal/FailureSpecies';
export type SessionErrorReason = 'token_expired' | 'network_error' | 'unknown';
export default function SessionRecoveryScreen({ reason = 'token_expired' }: { onReLogin: () => void; reason?: SessionErrorReason }) {
  if (reason === 'network_error' || !navigator.onLine) return null;
  return <SignInDoor help="Session has expired. Please sign in again." />;
}
