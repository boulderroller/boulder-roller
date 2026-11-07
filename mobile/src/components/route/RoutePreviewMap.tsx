import React from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import Feather from '@expo/vector-icons/Feather';
import MapView, { Polyline, type LatLng, type Region } from 'react-native-maps';
import Svg, { Path } from 'react-native-svg';

import type { RoutePreview, RoutePreviewBounds } from '../../lib/routePreview';
import { mobileColors, mobileRadii } from '../../theme/tokens';
import { mobileMapColors } from '../../theme/map';

const PREVIEW_WIDTH = 300;
const PREVIEW_HEIGHT = 122;
const PREVIEW_PADDING = 12;

interface RoutePreviewMapProps {
  preview?: RoutePreview | null;
  variant?: 'feed' | 'detail';
  height?: number;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 0.5;
  return Math.max(0, Math.min(1, value));
}

function previewSegments(preview: RoutePreview | null | undefined) {
  const segments = (preview?.segments ?? []).filter((segment) => segment.length >= 2);
  if (segments.length > 0) return segments;
  return (preview?.points?.length ?? 0) >= 2 ? [preview!.points] : [];
}

function routePaths(preview: RoutePreview | null | undefined): string[] {
  const width = PREVIEW_WIDTH - PREVIEW_PADDING * 2;
  const height = PREVIEW_HEIGHT - PREVIEW_PADDING * 2;
  return previewSegments(preview).map((points) => (
    points
      .map((point, index) => {
        const x = PREVIEW_PADDING + clamp(point.x) * width;
        const y = PREVIEW_PADDING + clamp(point.y) * height;
        return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ')
  ));
}

function validBounds(bounds: RoutePreviewBounds | null | undefined): bounds is RoutePreviewBounds {
  if (!bounds) return false;
  return [bounds.minLat, bounds.maxLat, bounds.minLon, bounds.maxLon].every(Number.isFinite)
    && bounds.minLat >= -90
    && bounds.maxLat <= 90
    && bounds.minLon >= -180
    && bounds.maxLon <= 180
    && bounds.maxLat > bounds.minLat
    && bounds.maxLon > bounds.minLon;
}

function regionFromBounds(bounds: RoutePreviewBounds): Region {
  const latitudeDelta = Math.max((bounds.maxLat - bounds.minLat) * 1.35, 0.01);
  const longitudeDelta = Math.max((bounds.maxLon - bounds.minLon) * 1.35, 0.01);

  return {
    latitude: (bounds.minLat + bounds.maxLat) / 2,
    longitude: (bounds.minLon + bounds.maxLon) / 2,
    latitudeDelta,
    longitudeDelta,
  };
}

function coordinateSegmentsFromPreview(preview: RoutePreview | null | undefined): LatLng[][] {
  const bounds = preview?.bounds;
  if (!validBounds(bounds)) return [];

  const latSpan = bounds.maxLat - bounds.minLat;
  const lonSpan = bounds.maxLon - bounds.minLon;
  return previewSegments(preview).map((points) => (
    points.map((point) => ({
      latitude: bounds.maxLat - clamp(point.y) * latSpan,
      longitude: bounds.minLon + clamp(point.x) * lonSpan,
    }))
  ));
}

function routeFallbackLabel(preview: RoutePreview | null | undefined): string {
  if (preview?.fallbackReason === 'privacy_redacted') return 'Private route';
  if (preview?.fallbackReason === 'missing_gps') return 'No GPS preview';
  return 'Route preview pending';
}

export default function RoutePreviewMap({
  preview,
  variant = 'feed',
  height,
  style,
  testID = 'route-preview-svg',
}: RoutePreviewMapProps) {
  const paths = routePaths(preview);
  const coordinateSegments = coordinateSegmentsFromPreview(preview);
  const mapRegion = validBounds(preview?.bounds) ? regionFromBounds(preview.bounds) : null;
  const hasRoute = paths.length > 0;
  const hasNativeMap = coordinateSegments.length > 0 && mapRegion != null;
  const isDetail = variant === 'detail';

  return (
    <View
      style={[
        styles.mapPreview,
        isDetail && styles.mapPreviewDetail,
        height != null && { height },
        style,
      ]}
      pointerEvents="none"
    >
      {hasNativeMap ? (
        <>
          <MapView
            testID={testID}
            style={styles.nativeMap}
            region={mapRegion}
            scrollEnabled={false}
            zoomEnabled={false}
            rotateEnabled={false}
            pitchEnabled={false}
            showsCompass={false}
            showsScale={false}
            showsUserLocation={false}
            showsMyLocationButton={false}
            mapType="mutedStandard"
            userInterfaceStyle="light"
            loadingEnabled
            loadingBackgroundColor={mobileMapColors.base}
            loadingIndicatorColor={mobileMapColors.route}
            tintColor={mobileMapColors.route}
          >
            {coordinateSegments.map((coordinates, index) => (
              <React.Fragment key={`route-segment-${index}`}>
                <Polyline
                  coordinates={coordinates}
                  strokeColor={mobileMapColors.routeHalo}
                  strokeWidth={8}
                  lineCap="round"
                  lineJoin="round"
                />
                <Polyline
                  coordinates={coordinates}
                  strokeColor={mobileMapColors.route}
                  strokeWidth={4}
                  lineCap="round"
                  lineJoin="round"
                />
              </React.Fragment>
            ))}
          </MapView>
          <View style={styles.mapTone} />
        </>
      ) : (
        <Svg
          width="100%"
          height="100%"
          viewBox={`0 0 ${PREVIEW_WIDTH} ${PREVIEW_HEIGHT}`}
          testID={testID}
        >
          {paths.map((path, index) => (
            <React.Fragment key={`route-path-${index}`}>
              <Path d={path} fill="none" stroke={mobileMapColors.routeHalo} strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
              <Path d={path} fill="none" stroke={mobileMapColors.route} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
            </React.Fragment>
          ))}
        </Svg>
      )}
      <View style={[styles.routeLabel, isDetail && styles.routeLabelDetail]}>
        <Text style={[styles.routeLabelText, isDetail && styles.routeLabelTextDetail]} numberOfLines={1}>
          {hasRoute ? preview?.placeLabel || 'Route preview' : routeFallbackLabel(preview)}
        </Text>
      </View>
      {!hasRoute ? (
        <View style={styles.routeFallback}>
          <Feather name="map" size={isDetail ? 21 : 17} color={mobileMapColors.labelText} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  mapPreview: {
    height: 122,
    backgroundColor: mobileMapColors.base,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    borderRadius: mobileRadii.md,
    overflow: 'hidden',
  },
  mapPreviewDetail: {
    backgroundColor: mobileMapColors.baseDetail,
    borderColor: mobileColors.borderStrong,
  },
  nativeMap: {
    ...StyleSheet.absoluteFillObject,
  },
  mapTone: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(255, 253, 247, 0.08)',
  },
  routeLabel: {
    position: 'absolute',
    left: 8,
    top: 8,
    maxWidth: 160,
    backgroundColor: mobileMapColors.labelBackground,
    borderRadius: 3,
    paddingHorizontal: 6,
    paddingVertical: 3,
  },
  routeLabelDetail: {
    backgroundColor: 'rgba(255, 253, 247, 0.86)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    maxWidth: 220,
  },
  routeLabelText: {
    color: mobileMapColors.labelText,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  routeLabelTextDetail: {
    color: mobileColors.textMuted,
  },
  routeFallback: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
