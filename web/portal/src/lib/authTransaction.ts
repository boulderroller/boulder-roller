import { AUTH_PHASES, type AuthPhase } from './authState';

export const AUTH_TRANSACTION_STAGE_VALUES = [
  'entry',
  'invite_entry',
  'method_choice',
  'email_provider',
  'wallet_provider',
  'request_invite',
  'waitlist_submitted',
  'how_it_works',
  'faq',
] as const;

export type AuthTransactionStage = typeof AUTH_TRANSACTION_STAGE_VALUES[number];
export type AuthTransactionMethod = 'email' | 'wallet';
export type AuthTransactionRecovery =
  | 'invite_validation'
  | 'email_origin_blocked'
  | 'provider_exchange'
  | 'wallet_connect'
  | null;

export interface AuthTransactionState {
  id: string;
  stage: AuthTransactionStage;
  phase: AuthPhase;
  inviteCode: string;
  inviteValidated: boolean;
  method: AuthTransactionMethod | null;
  recovery: AuthTransactionRecovery;
  error: string | null;
  isInviteValidating: boolean;
}

type AuthTransactionAction =
  | { type: 'bootstrap'; showLoginOptions: boolean; inviteValidated: boolean }
  | { type: 'show_entry' }
  | { type: 'show_invite_entry' }
  | { type: 'show_returning_sign_in' }
  | { type: 'show_request_invite' }
  | { type: 'show_waitlist_submitted' }
  | { type: 'show_how_it_works' }
  | { type: 'show_faq' }
  | { type: 'prefill_invite'; code: string }
  | { type: 'edit_invite'; code: string }
  | { type: 'validate_invite_start' }
  | { type: 'validate_invite_success'; code: string }
  | { type: 'validate_invite_failure'; error: string }
  | { type: 'choose_email' }
  | { type: 'choose_wallet' }
  | { type: 'back_to_methods' }
  | { type: 'surface_error'; error: string; recovery: AuthTransactionRecovery }
  | { type: 'clear_error' }
  | { type: 'reset_invite' };

function nextTransactionId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `auth_${crypto.randomUUID()}`;
  }

  return `auth_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function phaseForState(stage: AuthTransactionStage, error: string | null): AuthPhase {
  if (error) return AUTH_PHASES.recoverableError;
  if (
    stage === 'entry'
    || stage === 'invite_entry'
    || stage === 'request_invite'
    || stage === 'waitlist_submitted'
    || stage === 'how_it_works'
    || stage === 'faq'
  ) {
    return AUTH_PHASES.inviteGate;
  }
  if (stage === 'method_choice') return AUTH_PHASES.chooseAccessMethod;
  return AUTH_PHASES.providerPending;
}

function applyPhase(state: Omit<AuthTransactionState, 'phase'>): AuthTransactionState {
  return {
    ...state,
    phase: phaseForState(state.stage, state.error),
  };
}

interface AuthTransactionBootstrap {
  showLoginOptions: boolean;
  inviteValidated: boolean;
}

export function createAuthTransaction(
  initial: AuthTransactionBootstrap = { showLoginOptions: false, inviteValidated: false },
): AuthTransactionState {
  return applyPhase({
    id: nextTransactionId(),
    stage: initial.showLoginOptions ? 'method_choice' : 'entry',
    inviteCode: '',
    inviteValidated: initial.inviteValidated,
    method: null,
    recovery: null,
    error: null,
    isInviteValidating: false,
  });
}

export function authTransactionReducer(
  state: AuthTransactionState,
  action: AuthTransactionAction,
): AuthTransactionState {
  switch (action.type) {
    case 'bootstrap':
      return applyPhase({
        ...state,
        stage: action.showLoginOptions ? 'method_choice' : 'entry',
        inviteValidated: action.inviteValidated,
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_entry':
      return applyPhase({
        ...state,
        stage: 'entry',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_invite_entry':
      return applyPhase({
        ...state,
        stage: 'invite_entry',
        inviteCode: '',
        inviteValidated: false,
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_returning_sign_in':
      return applyPhase({
        ...state,
        stage: 'method_choice',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_request_invite':
      return applyPhase({
        ...state,
        stage: 'request_invite',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_waitlist_submitted':
      return applyPhase({
        ...state,
        stage: 'waitlist_submitted',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_how_it_works':
      return applyPhase({
        ...state,
        stage: 'how_it_works',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'show_faq':
      return applyPhase({
        ...state,
        stage: 'faq',
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'prefill_invite':
      return applyPhase({
        ...state,
        stage: 'invite_entry',
        inviteCode: action.code,
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'edit_invite':
      return applyPhase({
        ...state,
        inviteCode: action.code,
        recovery: null,
        error: null,
      });

    case 'validate_invite_start':
      return applyPhase({
        ...state,
        recovery: null,
        error: null,
        isInviteValidating: true,
      });

    case 'validate_invite_success':
      return applyPhase({
        ...state,
        stage: 'method_choice',
        inviteCode: action.code,
        inviteValidated: true,
        method: null,
        recovery: null,
        error: null,
        isInviteValidating: false,
      });

    case 'validate_invite_failure':
      return applyPhase({
        ...state,
        recovery: 'invite_validation',
        error: action.error,
        isInviteValidating: false,
      });

    case 'choose_email':
      return applyPhase({
        ...state,
        stage: 'email_provider',
        method: 'email',
        recovery: null,
        error: null,
      });

    case 'choose_wallet':
      return applyPhase({
        ...state,
        stage: 'wallet_provider',
        method: 'wallet',
        recovery: null,
        error: null,
      });

    case 'back_to_methods':
      return applyPhase({
        ...state,
        stage: 'method_choice',
        method: null,
        recovery: null,
        error: null,
      });

    case 'surface_error':
      return applyPhase({
        ...state,
        recovery: action.recovery,
        error: action.error,
        isInviteValidating: false,
      });

    case 'clear_error':
      return applyPhase({
        ...state,
        recovery: null,
        error: null,
      });

    case 'reset_invite':
      return createAuthTransaction();
  }
}
