import { buildRoutePreviewFromGps } from '../routePreview';

describe('route preview privacy-safe sampling', () => {
  test('keeps sampled long routes as original edge segments instead of new chords', () => {
    const points = Array.from({ length: 1_001 }, (_unused, index) => {
      const angle = (2 * Math.PI * index) / 1_000;
      return {
        latitude: Math.sin(angle) * 0.0018,
        longitude: Math.cos(angle) * 0.0018,
      };
    });

    const preview = buildRoutePreviewFromGps(points, { source: 'local_gps' });

    expect(preview).not.toBeNull();
    expect(preview?.points).toEqual([]);
    expect(preview?.segments).toHaveLength(24);
    expect(preview?.segments?.every((segment) => segment.length === 2)).toBe(true);
    expect(preview?.segments?.flat()).toHaveLength(48);
  });

  test('keeps a short continuous route compatible with points and segments', () => {
    const preview = buildRoutePreviewFromGps(
      [
        { latitude: 39.95, longitude: -75.17 },
        { latitude: 39.96, longitude: -75.16 },
        { latitude: 39.97, longitude: -75.15 },
      ],
      { source: 'local_gps' },
    );

    expect(preview?.points).toHaveLength(3);
    expect(preview?.segments).toEqual([preview?.points]);
  });
});
