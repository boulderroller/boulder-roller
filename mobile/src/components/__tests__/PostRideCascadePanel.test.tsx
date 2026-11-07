import React from 'react';
import { render, screen } from '@testing-library/react-native';

import { PostRideCascadePanel } from '../PostRideCascadePanel';
import type { PostRideCascadeView } from '../../lib/postRideCascade';

const BASE_CASCADE: PostRideCascadeView = {
  phase: 'uploaded',
  title: 'Ride saved',
  subtitle: 'Ride received.',
  hero: null,
  lines: [
    {
      key: 'uploaded',
      label: 'Ride saved',
      state: 'complete',
      truthSource: 'device',
    },
    {
      key: 'chain_record',
      label: 'Verification',
      state: 'pending',
      truthSource: 'onchain',
    },
  ],
};

describe('PostRideCascadePanel', () => {
  test('renders the cascade title and rider-facing lines', () => {
    render(<PostRideCascadePanel cascade={BASE_CASCADE} />);

    expect(screen.getByText('Ride result')).toBeTruthy();
    expect(screen.getAllByText('Ride saved').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Verification')).toBeTruthy();
  });

  test('renders a single verified mark only when the hero is on-chain verified', () => {
    render(
      <PostRideCascadePanel
        cascade={{
          ...BASE_CASCADE,
          phase: 'attested',
          hero: {
            label: 'Ride TSS',
            value: '123',
            truthSource: 'onchain',
            verified: true,
          },
        }}
      />,
    );

    expect(screen.getByText('Ride TSS')).toBeTruthy();
    expect(screen.getByText('123')).toBeTruthy();
    expect(screen.getAllByText('✓')).toHaveLength(2);
  });

  test('does not show the hero verified mark for provisional stats', () => {
    render(
      <PostRideCascadePanel
        cascade={{
          ...BASE_CASCADE,
          phase: 'provisional',
          hero: {
            label: 'Ride TSS',
            value: '123',
            truthSource: 'attested',
            verified: false,
          },
        }}
      />,
    );

    expect(screen.getAllByText('✓')).toHaveLength(1);
  });
});
