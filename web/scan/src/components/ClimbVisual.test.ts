import { describe, expect, it } from 'vitest';
import { decodePolylineJson } from './ClimbVisual';

describe('decodePolylineJson', () => {
  it('decodes object coordinate arrays', () => {
    expect(
      decodePolylineJson([
        { lat: 39.96184, lon: -105.0348, ele: 1620 },
        { lat: 39.962061, lon: -105.034797 },
      ])
    ).toEqual([
      { lat: 39.96184, lon: -105.0348, ele: 1620 },
      { lat: 39.962061, lon: -105.034797, ele: undefined },
    ]);
  });

  it('decodes live indexer tuple JSON strings', () => {
    expect(
      decodePolylineJson(
        '[[39.96184,-105.0348],[39.962061,-105.034797],[39.96231,-105.03463,1629.4]]'
      )
    ).toEqual([
      { lat: 39.96184, lon: -105.0348, ele: undefined },
      { lat: 39.962061, lon: -105.034797, ele: undefined },
      { lat: 39.96231, lon: -105.03463, ele: 1629.4 },
    ]);
  });

  it('drops placeholder and invalid points without dropping the whole route', () => {
    expect(
      decodePolylineJson([
        [0, 0],
        [91, -105],
        [39.962061, -105.034797],
        { lat: '39.96231', lng: '-105.03463', elevation: '1629.4' },
      ])
    ).toEqual([
      { lat: 39.962061, lon: -105.034797, ele: undefined },
      { lat: 39.96231, lon: -105.03463, ele: 1629.4 },
    ]);
  });
});
