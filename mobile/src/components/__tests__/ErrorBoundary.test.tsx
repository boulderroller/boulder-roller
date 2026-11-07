/**
 * ErrorBoundary Tests
 *
 * Verifies that the error boundary catches render errors,
 * displays recovery UI, and reports to Sentry.
 */

import React from 'react';
import { Text, View } from 'react-native';
import { render, screen, fireEvent } from '@testing-library/react-native';
import * as Sentry from '@sentry/react-native';
import { ErrorBoundary } from '../ErrorBoundary';

// Component that throws on render
function BrokenComponent(): React.JSX.Element {
  throw new Error('Test render crash');
}

// Component that renders normally
function GoodComponent(): React.JSX.Element {
  return (
    <View>
      <Text>All good</Text>
    </View>
  );
}

// Suppress console.error for expected render errors
const originalError = console.error;
beforeAll(() => {
  console.error = jest.fn();
});
afterAll(() => {
  console.error = originalError;
});

describe('ErrorBoundary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <GoodComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('All good')).toBeTruthy();
  });

  test('shows error screen when child throws', () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Something went wrong')).toBeTruthy();
    expect(screen.getByText(/unexpected error/)).toBeTruthy();
    expect(screen.getByText('Restart')).toBeTruthy();
  });

  test('reports error to Sentry', () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );

    expect(Sentry.captureException).toHaveBeenCalledTimes(1);
    expect(Sentry.captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        contexts: expect.objectContaining({
          react: expect.any(Object),
        }),
      }),
    );
  });

  test('resets error state when Restart is pressed', () => {
    // Use a component that throws only on first render
    let hasThrown = false;
    function ThrowOnce(): React.JSX.Element {
      if (!hasThrown) {
        hasThrown = true;
        throw new Error('One-time error');
      }
      return <Text>Recovered</Text>;
    }

    render(
      <ErrorBoundary>
        <ThrowOnce />
      </ErrorBoundary>,
    );

    // Should show error screen
    expect(screen.getByText('Something went wrong')).toBeTruthy();

    // Press restart
    fireEvent.press(screen.getByText('Restart'));

    // Should show recovered content
    expect(screen.getByText('Recovered')).toBeTruthy();
  });

  test('renders custom fallback when provided', () => {
    const CustomFallback = <Text>Custom error page</Text>;

    render(
      <ErrorBoundary fallback={CustomFallback}>
        <BrokenComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Custom error page')).toBeTruthy();
    // Default error UI should not be shown
    expect(screen.queryByText('Something went wrong')).toBeNull();
  });
});
