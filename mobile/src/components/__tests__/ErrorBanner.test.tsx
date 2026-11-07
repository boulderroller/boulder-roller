/**
 * ErrorBanner Tests
 *
 * Verifies the inline error banner renders correctly with
 * optional retry and dismiss actions.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react-native';
import { ErrorBanner } from '../ErrorBanner';

describe('ErrorBanner', () => {
  test('renders error message', () => {
    render(<ErrorBanner message="Connection issue" />);
    expect(screen.getByText('Connection issue')).toBeTruthy();
  });

  test('shows retry button when onRetry is provided', () => {
    const onRetry = jest.fn();
    render(<ErrorBanner message="Error" onRetry={onRetry} />);
    expect(screen.getByText('Retry')).toBeTruthy();
  });

  test('does not show retry button when onRetry is not provided', () => {
    render(<ErrorBanner message="Error" />);
    expect(screen.queryByText('Retry')).toBeNull();
  });

  test('calls onRetry when retry button is pressed', () => {
    const onRetry = jest.fn();
    render(<ErrorBanner message="Error" onRetry={onRetry} />);
    fireEvent.press(screen.getByText('Retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test('shows dismiss button when onDismiss is provided', () => {
    const onDismiss = jest.fn();
    render(<ErrorBanner message="Error" onDismiss={onDismiss} />);
    expect(screen.getByText('Dismiss')).toBeTruthy();
  });

  test('calls onDismiss when dismiss button is pressed', () => {
    const onDismiss = jest.fn();
    render(<ErrorBanner message="Error" onDismiss={onDismiss} />);
    fireEvent.press(screen.getByText('Dismiss'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test('shows both retry and dismiss when both provided', () => {
    render(
      <ErrorBanner
        message="Error"
        onRetry={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.getByText('Retry')).toBeTruthy();
    expect(screen.getByText('Dismiss')).toBeTruthy();
  });
});
