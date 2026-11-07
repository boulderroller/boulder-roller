import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { AccessibilityInfo, StyleSheet } from 'react-native';
import { useLoginWithEmail, usePrivy } from '@privy-io/expo';

import LoginScreen from '../LoginScreen';
import { useAuthStore } from '../../stores/authStore';

jest.mock('../../lib/api', () => ({
  api: {
    validateInviteCode: jest.fn(),
  },
}));

jest.mock('../../services/authService', () => ({
  loginWithExternalWallet: jest.fn(),
}));

jest.mock('../../services/wallet/mwaWallet', () => ({
  classifyMwaError: jest.fn(() => ({ message: 'Wallet sign-in failed.' })),
  isMwaSupported: jest.fn(() => false),
}));

const mockUsePrivy = usePrivy as jest.Mock;
const mockUseLoginWithEmail = useLoginWithEmail as jest.Mock;
const { api } = jest.requireMock('../../lib/api') as {
  api: {
    validateInviteCode: jest.Mock;
  };
};

function setPrivySession(user: object | null, logout = jest.fn(async () => undefined)) {
  mockUsePrivy.mockReturnValue({
    user,
    isReady: true,
    logout,
    getAccessToken: jest.fn(),
  });
  return logout;
}

describe('LoginScreen auth resume gating', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
    useAuthStore.getState().setUnauthenticated();
    mockUseLoginWithEmail.mockReturnValue({
      sendCode: jest.fn(),
      loginWithCode: jest.fn(),
    });
    api.validateInviteCode.mockResolvedValue({ valid: true });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('keeps a stale ready Privy session on the email path until an exchange is requested', () => {
    const logout = setPrivySession({ id: 'stale-privy-user' });

    render(<LoginScreen />);

    expect(screen.getByTestId('auth-phase-choose_access_method')).toBeTruthy();
    expect(screen.getByText('Email')).toBeTruthy();
    expect(screen.getByText('Sign in again.')).toBeTruthy();
    expect(screen.queryByText('Signing in…')).toBeNull();
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(false);
    expect(logout).not.toHaveBeenCalled();
  });

  test('keeps the landing copy minimal before the system needs to respond', () => {
    setPrivySession(null);

    render(<LoginScreen />);

    expect(screen.getByText('Boulder Roller')).toBeTruthy();
    expect(screen.getByText('Pre-alpha')).toBeTruthy();
    const emailInput = screen.getByPlaceholderText('you@example.com');
    expect(emailInput.props.accessibilityLabel).toBe('Email');
    expect(emailInput.props.placeholderTextColor).toBe('#a3a3a3');
    expect(StyleSheet.flatten(screen.getByText('Pre-alpha').props.style)).toMatchObject({
      color: '#888',
    });
    expect(screen.queryByText('Ride the climb. Prove the effort. Keep what you earn.')).toBeNull();
    expect(screen.queryByText('Pre-alpha. Returning riders continue with email.')).toBeNull();
    expect(screen.queryByText('New riders may need an alpha invite after email verification.')).toBeNull();
  });

  test('shows session exchange only for an explicit request and Start over returns to email', async () => {
    jest.useFakeTimers();
    const logout = setPrivySession({ id: 'active-privy-user' });
    useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');
    useAuthStore.getState().requestSessionExchange();

    render(<LoginScreen />);

    expect(screen.getByTestId('auth-phase-session_exchange')).toBeTruthy();
    expect(screen.getByText('Signing in…')).toBeTruthy();
    expect(screen.queryByText('Still signing in.')).toBeNull();
    expect(screen.queryByText('Start over')).toBeNull();

    act(() => {
      jest.advanceTimersByTime(6_000);
    });
    expect(screen.getByText('Still signing in.')).toBeTruthy();
    expect(screen.queryByText('Start over')).toBeNull();

    act(() => {
      jest.advanceTimersByTime(9_000);
    });
    expect(screen.getByText('Taking longer than usual.')).toBeTruthy();

    await act(async () => {
      fireEvent.press(screen.getByText('Start over'));
    });
    jest.useRealTimers();

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
    });
    expect(useAuthStore.getState()).toMatchObject({
      pendingInviteCode: null,
      sessionExchangeRequested: false,
      authError: null,
    });
    expect(screen.getByTestId('auth-phase-choose_access_method')).toBeTruthy();
  });

  test('email sign-in sends a neutral OTP before the backend invite decision', async () => {
    const loginWithCode = jest.fn(async () => undefined);
    const sendCode = jest.fn(async () => undefined);
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'rider@example.com');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(sendCode).toHaveBeenCalledWith({ email: 'rider@example.com' });
    });

    fireEvent.changeText(screen.getByPlaceholderText('123456'), '123456');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(loginWithCode).toHaveBeenCalledWith({
        code: '123456',
        email: 'rider@example.com',
      });
    });
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(true);
  });

  test('suppresses stale invalid-code copy when Privy authenticates during the code failure grace', async () => {
    jest.useFakeTimers();
    let privyUser: object | null = null;
    const loginWithCode = jest.fn(async () => {
      throw new Error('Provider callback raced auth state');
    });
    const sendCode = jest.fn(async () => undefined);
    mockUsePrivy.mockImplementation(() => ({
      user: privyUser,
      isReady: true,
      logout: jest.fn(async () => undefined),
      getAccessToken: jest.fn(),
    }));
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    const { rerender } = render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'rider@example.com');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(sendCode).toHaveBeenCalledWith({ email: 'rider@example.com' });
    });

    fireEvent.changeText(screen.getByPlaceholderText('123456'), '123456');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(loginWithCode).toHaveBeenCalledWith({
        code: '123456',
        email: 'rider@example.com',
      });
    });
    expect(screen.queryByText('Invalid or expired code')).toBeNull();

    privyUser = { id: 'privy-user' };
    rerender(<LoginScreen />);
    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(screen.getByText('Signing in…')).toBeTruthy();
    expect(screen.queryByText('Invalid or expired code')).toBeNull();
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(true);
  });

  test('shows invalid-code copy after the grace window when auth does not recover', async () => {
    jest.useFakeTimers();
    const loginWithCode = jest.fn(async () => {
      throw Object.assign(new Error('Invalid code'), { code: 'invalid_credentials' });
    });
    const sendCode = jest.fn(async () => undefined);
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'rider@example.com');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(sendCode).toHaveBeenCalledWith({ email: 'rider@example.com' });
    });

    fireEvent.changeText(screen.getByPlaceholderText('123456'), '000000');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(loginWithCode).toHaveBeenCalledWith({
        code: '000000',
        email: 'rider@example.com',
      });
    });
    expect(screen.queryByText('Invalid or expired code')).toBeNull();

    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(screen.getByText('Invalid or expired code')).toBeTruthy();
    expect(screen.getByPlaceholderText('123456')).toBeTruthy();
    expect(screen.queryByPlaceholderText('Invite code')).toBeNull();
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(false);
  });

  test('does not discard a validated invite when the provider still refuses signup', async () => {
    const refusal = Object.assign(new Error('Signup is disabled'), {
      code: 'allowlist_rejected',
    });
    const sendCode = jest.fn(async () => undefined);
    const loginWithCode = jest.fn(async () => {
      throw refusal;
    });
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    render(<LoginScreen />);
    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'new@example.com');
    fireEvent.press(screen.getByText('Continue'));
    await screen.findByText('Sent to new@example.com');
    const codeInput = screen.getByPlaceholderText('123456');
    expect(codeInput.props.accessibilityLabel).toBe('Email code');
    expect(codeInput.props.placeholderTextColor).toBe('#a3a3a3');

    act(() => {
      useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');
    });
    fireEvent.changeText(screen.getByPlaceholderText('123456'), '123456');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(loginWithCode).toHaveBeenCalledWith({
        code: '123456',
        email: 'new@example.com',
      });
      expect(screen.getByText('Account setup is unavailable. Try again.')).toBeTruthy();
    });
    expect(screen.getByPlaceholderText('123456')).toBeTruthy();
    expect(screen.queryByPlaceholderText('Invite code')).toBeNull();
    expect(useAuthStore.getState().pendingInviteCode).toBe('ALPHA-RIDE');
  });

  test('recoverable email-code failures stay in the login UI without console error', async () => {
    const sendCode = jest.fn(async () => {
      throw new Error('offline');
    });
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const infoSpy = jest.spyOn(console, 'info').mockImplementation(() => undefined);
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode: jest.fn() });

    render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'rider@example.com');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(screen.getByText("Couldn't continue.")).toBeTruthy();
    });
    expect(sendCode).toHaveBeenCalledWith({ email: 'rider@example.com' });
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
    infoSpy.mockRestore();
  });

  test('Privy native app allowlist failures use actionable login copy', async () => {
    const sendCode = jest.fn(async () => {
      const err = new Error(
        'Native app ID com.boulderroller.app has not been set as an allowed app identifier in the Privy dashboard.',
      ) as Error & { code: string };
      err.code = 'invalid_native_app_id';
      throw err;
    });
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const infoSpy = jest.spyOn(console, 'info').mockImplementation(() => undefined);
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode: jest.fn() });

    render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'rider@example.com');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(screen.getByText('Sign-in is not enabled for this build.')).toBeTruthy();
    });
    expect(sendCode).toHaveBeenCalledWith({ email: 'rider@example.com' });
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
    infoSpy.mockRestore();
  });

  test('provider signup refusal preserves the email and announces invite recovery', async () => {
    const refusal = Object.assign(new Error('Signup is disabled'), {
      privyErrorCode: 'allowlist_rejected',
    });
    const sendCode = jest.fn(async () => undefined);
    const loginWithCode = jest.fn(async () => {
      throw refusal;
    });
    const announceSpy = jest
      .spyOn(AccessibilityInfo, 'announceForAccessibility')
      .mockImplementation(() => undefined);
    setPrivySession(null);
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    render(<LoginScreen />);
    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'new@example.com');
    fireEvent.press(screen.getByText('Continue'));
    await screen.findByText('Sent to new@example.com');
    fireEvent.changeText(screen.getByPlaceholderText('123456'), '123456');
    fireEvent.press(screen.getByText('Continue'));

    const inviteInput = await screen.findByPlaceholderText('Invite code');
    expect(inviteInput.props.accessibilityLabel).toBe('Invite code');
    expect(screen.getByText('Enter your invite code to continue with new@example.com.')).toBeTruthy();
    await waitFor(() => {
      expect(announceSpy).toHaveBeenCalledWith('Invite code. Enter your invite code to continue.');
    });
    expect(sendCode).toHaveBeenCalledTimes(1);
    announceSpy.mockRestore();
  });

  test('backend invite recovery preserves the email and resumes the same provider session without another OTP', async () => {
    let privyUser: object | null = null;
    const sendCode = jest.fn(async () => undefined);
    const loginWithCode = jest.fn(async () => undefined);
    mockUsePrivy.mockImplementation(() => ({
      user: privyUser,
      isReady: true,
      logout: jest.fn(async () => undefined),
      getAccessToken: jest.fn(),
    }));
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });

    const { rerender } = render(<LoginScreen />);

    fireEvent.changeText(screen.getByPlaceholderText('you@example.com'), 'new@example.com');
    fireEvent.press(screen.getByText('Continue'));
    await screen.findByText('Sent to new@example.com');

    fireEvent.changeText(screen.getByPlaceholderText('123456'), '123456');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(loginWithCode).toHaveBeenCalledWith({
        code: '123456',
        email: 'new@example.com',
      });
    });

    privyUser = { id: 'new-privy-user' };
    act(() => {
      useAuthStore.getState().clearSessionExchangeRequest();
      useAuthStore.getState().setAuthError('Invite required.', 'invite_required');
    });
    rerender(<LoginScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('auth-phase-invite_gate')).toBeTruthy();
      expect(screen.getByText('Enter your invite code to continue with new@example.com.')).toBeTruthy();
    });

    fireEvent.changeText(screen.getByPlaceholderText('Invite code'), 'ALPHA-RIDE');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(api.validateInviteCode).toHaveBeenCalledWith('ALPHA-RIDE');
      expect(useAuthStore.getState().sessionExchangeRequested).toBe(true);
    });
    expect(sendCode).toHaveBeenCalledTimes(1);
    expect(loginWithCode).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().pendingInviteCode).toBe('ALPHA-RIDE');
  });

  test('invalid invite does not retry the authenticated provider session', async () => {
    const sendCode = jest.fn(async () => undefined);
    const loginWithCode = jest.fn(async () => undefined);
    setPrivySession({ id: 'new-privy-user' });
    mockUseLoginWithEmail.mockReturnValue({ sendCode, loginWithCode });
    api.validateInviteCode.mockResolvedValue({ valid: false });
    useAuthStore.getState().setAuthError('Invite required.', 'invite_required');

    render(<LoginScreen />);

    await screen.findByPlaceholderText('Invite code');

    fireEvent.changeText(screen.getByPlaceholderText('Invite code'), 'BAD-CODE');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(api.validateInviteCode).toHaveBeenCalledWith('BAD-CODE');
    });
    expect(sendCode).not.toHaveBeenCalled();
    expect(loginWithCode).not.toHaveBeenCalled();
    expect(screen.getByText('That invite is not active.')).toBeTruthy();
  });

  test('invite-required backend recovery validates the invite and retries exchange on the same Privy session', async () => {
    setPrivySession({ id: 'new-privy-user' });
    useAuthStore.getState().setAuthError(
      'Invite required.',
      'invite_required',
    );

    render(<LoginScreen />);

    expect(screen.getByTestId('auth-phase-invite_gate')).toBeTruthy();
    expect(screen.getByText('Invite required.')).toBeTruthy();

    fireEvent.changeText(screen.getByPlaceholderText('Invite code'), 'ALPHA-RIDE');
    fireEvent.press(screen.getByText('Continue'));

    await waitFor(() => {
      expect(api.validateInviteCode).toHaveBeenCalledWith('ALPHA-RIDE');
    });
    expect(useAuthStore.getState()).toMatchObject({
      pendingInviteCode: 'ALPHA-RIDE',
      sessionExchangeRequested: true,
      authError: null,
      authRecovery: null,
    });
  });

  test('hides the unsupported wallet path on iOS-style environments', () => {
    setPrivySession(null);

    render(<LoginScreen />);

    expect(screen.queryByText('Use wallet')).toBeNull();
    expect(screen.queryByText('Wallet sign-in is Android-only.')).toBeNull();
  });
});
