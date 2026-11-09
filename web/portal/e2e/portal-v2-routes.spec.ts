import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import fs from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { trainingRead } from '../src/components/ride/trainingRead';
import { estimateCopy } from '../src/lib/estimateCopy';
import { UPLOAD_PROCESSING_FAILURE } from '../src/components/upload/uploadCopy';
import path from 'node:path';

const NOW = new Date('2026-05-05T15:00:00Z');
const TEST_WALLET = '11111111111111111111111111111111';
const LONG_RIDER_WALLET = 'timwallet1111111111111111111111111111111';
const CANON_CLIMB_ROW_ID = '11111111-1111-4111-8111-111111111111';
const WALLET_SHAPED_TEXT = /(?:timw|timwallet)[a-z0-9.]*1111|111111111111111111/i;
const CANON_VAULT_CENTERLINE_POLYLINE = '}shsFxccjMAEACISGSIUGSISISGSISGSISIS?CISISGSISGUISGSCGCGCIISGSACISISCMCCECOKMKOKOIOKOKOKMIOKOKOKOKOIGEKIIGMMCCWWMKMMOMMMMMMMKKOMMMMMEEEECECG';

function decodeCanonicalPolyline(encoded: string): Array<[number, number]> {
  const coordinates: Array<[number, number]> = [];
  let index = 0;
  let latitude = 0;
  let longitude = 0;

  const decodeValue = () => {
    let result = 0;
    let shift = 0;
    let byte = 0;
    do {
      byte = encoded.charCodeAt(index) - 63;
      index += 1;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20 && index < encoded.length);
    return (result & 1) ? ~(result >> 1) : result >> 1;
  };

  while (index < encoded.length) {
    latitude += decodeValue();
    longitude += decodeValue();
    coordinates.push([latitude / 100_000, longitude / 100_000]);
  }
  return coordinates;
}

function buildCanonVaultRoutePreview(coordinates = decodeCanonicalPolyline(CANON_VAULT_CENTERLINE_POLYLINE)) {
  const latitudes = coordinates.map(([latitude]) => latitude);
  const longitudes = coordinates.map(([, longitude]) => longitude);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const previewPointLimit = 48;
  const stride = (coordinates.length - 1) / (previewPointLimit - 1);
  const sampled = coordinates.length <= previewPointLimit
    ? coordinates
    : [
      ...Array.from(
        { length: previewPointLimit - 1 },
        (_, sampleIndex) => coordinates[Math.round(sampleIndex * stride)],
      ),
      coordinates.at(-1)!,
    ];
  const round = (value: number, places: number) => {
    const factor = 10 ** places;
    return Math.round(value * factor) / factor;
  };

  return {
    contract_version: 'route_preview.v1',
    source: 'canon_centerline',
    points: sampled.map(([latitude, longitude]) => ({
      x: round((longitude - minLon) / (maxLon - minLon), 4),
      y: round(1 - ((latitude - minLat) / (maxLat - minLat)), 4),
    })),
    point_count: coordinates.length,
    bounds: {
      min_lat: round(minLat, 6),
      max_lat: round(maxLat, 6),
      min_lon: round(minLon, 6),
      max_lon: round(maxLon, 6),
    },
    place_label: 'Manayunk, Philadelphia',
    fallback_reason: null,
    privacy: { redacted_gps: false },
  };
}

const CANON_VAULT_ROUTE_PREVIEW = buildCanonVaultRoutePreview();
const CANON_VAULT_ELEVATION_PROFILE = [
  { distance_m: 0, elevation_m: 16.88 },
  { distance_m: 34.65, elevation_m: 19.75 },
  { distance_m: 74.65, elevation_m: 23.51 },
  { distance_m: 116.35, elevation_m: 27.67 },
  { distance_m: 166.35, elevation_m: 31.98 },
  { distance_m: 194.37, elevation_m: 34.26 },
  { distance_m: 231.15, elevation_m: 39.65 },
  { distance_m: 253.68, elevation_m: 42.72 },
  { distance_m: 303.68, elevation_m: 50.22 },
  { distance_m: 353.68, elevation_m: 57.73 },
  { distance_m: 389.1, elevation_m: 62.12 },
  { distance_m: 432.52, elevation_m: 66.28 },
  { distance_m: 482.52, elevation_m: 70.92 },
  { distance_m: 521.02, elevation_m: 74.68 },
  { distance_m: 546.66, elevation_m: 76.28 },
];

function iso(daysAgo = 0): string {
  return new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();
}

const user = {
  id: 'user-test-1',
  wallet: TEST_WALLET,
  username: 'dungbeetlephoenix',
  display_name: 'Dung Beetle Phoenix',
  beetle_id: 'BR-1542',
  beetle_number: 1542,
  bio: 'Portal V2 dogfood rider.',
  weight_kg: 74,
  rider_type: 'puncheur',
  avatar_url: null,
  theme_id: 'hoo-breddin',
  is_dark_mode: false,
  created_at: iso(150),
  last_active_at: iso(0),
};

function ride(
  id: string,
  daysAgo: number,
  title: string,
  distanceM = 42_195,
  elevationM = 540,
  calEarned = 88,
  overrides: Record<string, unknown> = {},
) {
  return {
    contract_version: 'client.v1',
    truth_source: 'backend',
    id,
    rider_id: user.id,
    title,
    started_at: iso(daysAgo),
    distance_m: distanceM,
    elevation_m: elevationM,
    duration_s: 5_400,
    avg_power_w: 216,
    normalized_power_w: 238,
    tss: 112,
    calories: 1320,
    cal_earned: calEarned,
    dung_earned: calEarned,
    attestation_status: 'finalized',
    ride_hash_hex: `hash-${id}`,
    finalized_at: iso(daysAgo),
    visibility: 'public',
    privacy: {
      visibility: 'public',
      can_view: true,
      is_owner: true,
      is_follower: false,
      redact_gps: false,
      map_visibility: 'hide_start_end',
      map_hide_start_m: 200,
      map_hide_end_m: 200,
      protocol_public: true,
      protocol_public_fields: [],
      reason: 'owner',
    },
    primary_media: null,
    media: [],
    route_preview: {
      contract_version: 'route_preview.v1',
      source: 'fixture',
      points: [
        { x: 0.08, y: 0.78 },
        { x: 0.26, y: 0.55 },
        { x: 0.44, y: 0.62 },
        { x: 0.61, y: 0.32 },
        { x: 0.82, y: 0.18 },
      ],
      point_count: 5,
      bounds: { min_lat: 40.0237, min_lon: -75.2265, max_lat: 40.0314, max_lon: -75.2162 },
      place_label: 'Fixture Loop',
      privacy: { redact_gps: false },
    },
    ...overrides,
  };
}

const rides = [
  ride('ride-1', 1, 'Morning Ride', 48_200, 620, 96),
  ride('ride-2', 6, 'Bridge Repeats', 26_300, 910, 121),
  ride('ride-3', 18, 'Recovery Spin', 17_400, 120, 28),
];

const cohortInviteCode = 'philly-alpha-01';
const cohortUploadedRide = ride('ride-uploaded-1', 0, 'First Counted Ride', 31_800, 524, 104, {
  route_preview: {
    contract_version: 'route_preview.v1',
    source: 'fixture',
    points: [
      { x: 0.07, y: 0.82 },
      { x: 0.22, y: 0.68 },
      { x: 0.39, y: 0.48 },
      { x: 0.58, y: 0.34 },
      { x: 0.81, y: 0.17 },
    ],
    point_count: 5,
    bounds: null,
    place_label: 'Manayunk',
    privacy: { redact_gps: false },
  },
});

// The list's cross-section (bead 24xry.19): a 24-point profile with one counted span.
const contractElevationProfile = Array.from({ length: 24 }, (_, index) => ({
  distance_m: index * 2_000,
  elevation_m: 40 + (index < 12 ? index * 9 : (23 - index) * 9) + (index % 3) * 4,
}));
// Local fixture: deliberately conflicting dates and residual figures on a failed upload.
// The owner list projects stored uploaded_at; its date differs from the placeholder start.
const failedUploadDate = '2026-05-02T15:00:00Z';
const failedUpload = ride('failed-upload', 3, 'Original file.gpx', 48_200, 620, 96, {
  status: 'failed',
  attestation_status: 'under_review',
  uploaded_at: failedUploadDate,
  started_at: '2026-04-30T15:00:00Z',
  elevation_profile: contractElevationProfile,
  counted_spans: [{ start_distance_m: 6_000, end_distance_m: 20_000 }],
  patterns: [{ type: 'climb' }, { type: 'climb' }],
});
const rideLogContractRides = [
  {
    ...rides[0],
    elevation_profile: contractElevationProfile,
    counted_spans: [{ start_distance_m: 6_000, end_distance_m: 20_000 }],
  },
  ride('ride-waiting', 0, 'Waiting Ride', 0, 0, 0, {
    distance_m: null,
    elevation_m: null,
    duration_s: null,
    avg_power_w: null,
    cal_earned: null,
    dung_earned: null,
    attestation_status: 'processing',
  }),
  ride('ride-not-counted', 5, 'Coffee Spin', 12_400, 84, 0, {
    cal_earned: 0,
    dung_earned: 0,
    attestation_status: 'finalized',
  }),
];

const uploadedRideMedia = {
  id: 'media-cover-1',
  ride_id: 'ride-1',
  url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900"%3E%3Crect width="1600" height="900" fill="%232f6f58"/%3E%3Cpath d="M0 640 C240 560 390 610 560 520 C790 400 910 430 1120 310 C1300 208 1460 196 1600 152 L1600 900 L0 900 Z" fill="%23e7eadf"/%3E%3Cpath d="M0 678 C245 590 395 645 575 548 C795 430 932 452 1146 333 C1324 234 1470 224 1600 184" fill="none" stroke="%23d2a85b" stroke-width="34" stroke-linecap="round"/%3E%3Ccircle cx="1146" cy="333" r="24" fill="%23f7f8f0"/%3E%3C/svg%3E',
  file_name: 'profile-cover.svg',
  mime_type: 'image/svg+xml',
  size_bytes: 1100,
  width: 1600,
  height: 900,
  sort_order: 0,
  role: 'cover',
  moderation_state: 'approved',
  created_at: iso(1),
};

const ridesWithUploadedMedia = rides.map((item, index) => (
  index === 0
    ? { ...item, primary_media: uploadedRideMedia, media: [uploadedRideMedia] }
    : item
));

const beetleCards = [
  {
    id: 'card-climb-1',
    wallet: TEST_WALLET,
    card_type: 'CLIMB',
    scope_id: 'vault-1',
    scope_name: 'Manayunk Wall',
    score: 1840,
    level: 4,
    patterns_scored: 18,
    next_level_threshold: 2400,
    progress_to_next: 0.74,
    upgrade_cost_dung: 200,
    created_at: iso(50),
    updated_at: iso(2),
  },
  {
    id: 'card-steady-1',
    wallet: TEST_WALLET,
    card_type: 'STEADY',
    scope_id: 'GLOBAL_SCOPE',
    score: 960,
    level: 3,
    patterns_scored: 22,
    next_level_threshold: 1200,
    progress_to_next: 0.8,
    upgrade_cost_dung: 100,
    created_at: iso(48),
    updated_at: iso(4),
  },
];

const publicBeetleCards = beetleCards.map(({ wallet: _wallet, ...card }) => ({
  ...card,
  id: `public-${card.id}`,
}));

function apiError(status: number, detail: string) {
  return { __api_error: true, status, detail };
}

function rideGpsPoint(sequence: number, offsetS: number, latitude: number, longitude: number, elevationM: number, distanceM: number) {
  return {
    sequence_num: sequence,
    timestamp: new Date(NOW.getTime() + offsetS * 1000).toISOString(),
    latitude,
    longitude,
    elevation_m: elevationM,
    distance_m: distanceM,
  };
}

const rideGpsPoints = [
  rideGpsPoint(0, 0, 39.9480, -75.1700, 18, 0),
  rideGpsPoint(1, 300, 39.9510, -75.1730, 42, 2_100),
  rideGpsPoint(2, 600, 39.9550, -75.1760, 86, 5_300),
  rideGpsPoint(3, 760, 39.9590, -75.1780, 154, 6_400),
  rideGpsPoint(4, 920, 39.9630, -75.1810, 238, 7_400),
  rideGpsPoint(5, 1_080, 39.9670, -75.1840, 332, 8_400),
  rideGpsPoint(6, 1_260, 39.9710, -75.1880, 498, 9_000),
  rideGpsPoint(7, 1_620, 39.9750, -75.1900, 520, 12_000),
  rideGpsPoint(8, 2_160, 39.9790, -75.1840, 414, 18_000),
  rideGpsPoint(9, 2_880, 39.9820, -75.1740, 320, 27_000),
  rideGpsPoint(10, 3_780, 39.9770, -75.1620, 180, 38_000),
  rideGpsPoint(11, 5_400, 39.9650, -75.1500, 42, 48_200),
];

const rideGpsPointsWithoutCoordinates = rideGpsPoints.map(({ latitude: _latitude, longitude: _longitude, ...point }) => point);
const rideGpsPointsRedacted = rideGpsPoints.map((point) => ({
  ...point,
  latitude: null,
  longitude: null,
  redacted: true,
}));

const publicRider = {
  id: 'tim-user',
  wallet: LONG_RIDER_WALLET,
  username: 'tim',
  display_name: 'Tim Trail',
  bio: 'Turns climb repeats into signal.',
  avatar_url: null,
  is_public: true,
  created_at: iso(120),
  total_rides: 12,
  total_distance_km: 482,
  total_elevation_m: 8_420,
  follower_count: 3,
  following_count: 7,
  current_streak: 4,
  longest_streak: 11,
  last_activity_date: iso(1),
};

function vault(id: number, name: string, active = true) {
  const totalStaked = 12_500 + id * 240;
  return {
    id,
    signature_hex: `vault-signature-${id}`,
    signature_hash_hex: `vault-hash-${id}`,
    name,
    vert_m: 412 + id,
    distance_m: 3_700 + id * 150,
    avg_gradient_pct: 7.4 + id * 0.1,
    total_completions: 42 + id,
    total_staked: String(totalStaked),
    total_staked_base_units: String(totalStaked * 1_000_000_000),
    total_cal_staked: String(totalStaked),
    total_cal_staked_base_units: String(totalStaked * 1_000_000_000),
    kom_holder: id % 2 ? TEST_WALLET : null,
    kom_time_s: 610 + id,
    minter: TEST_WALLET,
    pda: `vault-pda-${id}`,
    start_lat: 39.95 + id * 0.002,
    start_lon: -75.16 - id * 0.002,
    end_lat: 39.96 + id * 0.002,
    end_lon: -75.17 - id * 0.002,
    on_chain_active: active,
    on_chain_seeding_status: active ? 'active' : 'seeding',
  };
}

const vaults = [
  vault(1, 'Full Stack Smoke'),
  vault(2, 'Ellis Street Wall'),
  vault(3, 'Market Punch', false),
];

const canonicalClimbs = [
  {
    contract_version: 'client.v1',
    truth_source: 'attested',
    id: 'climb-1',
    name: 'Manayunk Wall',
    region: 'Philadelphia, PA',
    length_m: 840,
    elev_gain_m: 69,
    avg_gradient_pct: 8.2,
    category: '4',
    start_lat: 40.0237,
    start_lon: -75.2265,
    end_lat: 40.0314,
    end_lon: -75.2162,
    has_vault: true,
    vault_id: 1,
    vault_signature: 'vault-signature-1',
    total_staked: '12345.6789',
    total_staked_base_units: '12345678900000',
    total_cal_staked: '12345.6789',
    total_cal_staked_base_units: '12345678900000',
    total_completions: 42,
    vault_economy: {
      contract_version: 'client.v1',
      truth_source: 'attested',
      has_vault: true,
      vault_id: 1,
      vault_signature: 'vault-signature-1',
      total_staked: '12345.6789',
      total_staked_base_units: '12345678900000',
      total_cal_staked: '12345.6789',
      total_cal_staked_base_units: '12345678900000',
      total_completions: 42,
    },
    route_preview: {
      contract_version: 'route_preview.v1',
      source: 'canon_centerline',
      points: [
        { x: 0, y: 0.9 },
        { x: 0.24, y: 0.68 },
        { x: 0.5, y: 0.52 },
        { x: 0.72, y: 0.26 },
        { x: 1, y: 0.05 },
      ],
      point_count: 18,
      bounds: {
        min_lat: 40.0237,
        min_lon: -75.2265,
        max_lat: 40.0314,
        max_lon: -75.2162,
      },
      fallback_reason: null,
      privacy: { redacted_gps: false },
    },
  },
  {
    contract_version: 'client.v1',
    truth_source: 'attested',
    id: 'climb-2',
    name: 'Welsh Valley Road',
    region: 'Gladwyne, PA',
    length_m: 1_900,
    elev_gain_m: 104,
    avg_gradient_pct: 5.5,
    category: '4',
    start_lat: 40.0342,
    start_lon: -75.2538,
    end_lat: 40.0471,
    end_lon: -75.2384,
    has_vault: false,
    total_completions: 18,
    route_preview: {
      contract_version: 'route_preview.v1',
      source: 'fixture',
      points: [
        { x: 0, y: 0.9 },
        { x: 0.5, y: 0.5 },
        { x: 1, y: 0.1 },
      ],
      point_count: 3,
      bounds: {
        min_lat: 40.0342,
        min_lon: -75.2538,
        max_lat: 40.0471,
        max_lon: -75.2384,
      },
      fallback_reason: null,
      privacy: { redacted_gps: false },
    },
  },
  {
    contract_version: 'client.v1',
    truth_source: 'attested',
    id: 'climb-3',
    name: 'Lemon Hill',
    region: 'Philadelphia, PA',
    length_m: 620,
    elev_gain_m: 31,
    avg_gradient_pct: 5,
    category: '4',
    start_lat: 39.9708,
    start_lon: -75.191,
    end_lat: 39.9791,
    end_lon: -75.1818,
    has_vault: true,
    vault_id: 3,
    vault_signature: 'vault-signature-3',
    total_completions: 27,
    vault_economy: {
      contract_version: 'client.v1',
      truth_source: 'attested',
      has_vault: true,
      vault_id: 3,
      vault_signature: 'vault-signature-3',
      total_staked: null,
      total_staked_base_units: null,
      total_cal_staked: null,
      total_cal_staked_base_units: null,
      total_completions: 27,
    },
  },
  {
    contract_version: 'client.v1',
    truth_source: 'attested',
    id: 'climb-invalid',
    name: 'Invalid zero-length climb',
    region: 'Philadelphia, PA',
    length_m: 0,
    elev_gain_m: 80,
    avg_gradient_pct: 0,
    category: '4',
    start_lat: 40.01,
    start_lon: -75.24,
    end_lat: 40.03,
    end_lon: -75.2,
    has_vault: false,
    total_completions: 0,
  },
];

const routeExpectations = [
  { path: '/', shellTitle: 'Feed', browserTitle: 'Feed · Boulder Roller' },
  { path: '/settings', shellTitle: 'Settings', browserTitle: 'Settings · Boulder Roller' },
  { path: '/profile', shellTitle: 'Profile', browserTitle: 'Dung Beetle Phoenix · Profile · Boulder Roller', hidesWalletText: true },
  { path: '/rider/tim', shellTitle: 'Rider', browserTitle: 'Tim Trail · Rider · Boulder Roller', hidesWalletText: true },
  { path: '/profile?tab=portfolio', shellTitle: 'Portfolio', browserTitle: 'Dung Beetle Phoenix · Portfolio · Boulder Roller' },
  { path: '/climbs', shellTitle: 'Climbs', browserTitle: 'Map · Boulder Roller' },
  { path: '/vaults', shellTitle: 'Climbs', browserTitle: 'Map · Boulder Roller' },
  { path: '/vaults/1', shellTitle: 'Climb', browserTitle: 'Full Stack Smoke 1776366970 · Climb · Boulder Roller', hidesWalletText: true },
  { path: '/activities/ride-1', shellTitle: 'Ride', browserTitle: 'Morning Ride · Ride · Boulder Roller', hidesWalletText: true },
  { path: '/notifications', shellTitle: 'Notifications', browserTitle: 'Notifications · Boulder Roller' },
  { path: '/map', shellTitle: 'Climbs', browserTitle: 'Map · Boulder Roller' },
  { path: '/profile?tab=rides', shellTitle: 'My rides', browserTitle: 'Dung Beetle Phoenix · Rides · Boulder Roller' },
  { path: '/profile?tab=training', shellTitle: 'Training', browserTitle: 'Dung Beetle Phoenix · Training · Boulder Roller' },
  { path: '/climbs/climb-1', shellTitle: 'Climb', browserTitle: 'Full Stack Smoke 1776366970 · Climb · Boulder Roller', hidesWalletText: true },
  { path: '/?search=riders', shellTitle: 'Feed', browserTitle: 'Feed · Boulder Roller', hidesWalletText: true },
  { path: '/docs', shellTitle: 'Docs', browserTitle: 'Guide · Boulder Roller' },
];

const cohortParkedPageExpectations = [
  { slug: 'settings', path: '/settings', heading: 'Settings' },
  { slug: 'climbs', path: '/map', canonicalPath: '/climbs', heading: 'Climbs' },
  { slug: 'docs', path: '/docs', heading: 'Guide' },
];

const themeModes = [
  { label: 'light', darkMode: false },
  { label: 'dark', darkMode: true },
];

const eyebrowReviewRoutes = [
  { slug: 'admin', path: '/admin' },
  { slug: 'data', path: '/profile?tab=training' },
  { slug: 'docs', path: '/docs' },
  { slug: 'notifications', path: '/notifications' },
  { slug: 'portfolio', path: '/profile?tab=portfolio' },
  { slug: 'settings', path: '/settings' },
];

const eyebrowObjectReviewRoutes = [
  { slug: 'climb-record', path: '/climbs/climb-1', objectPage: 'climb' },
  { slug: 'ride-detail', path: '/activities/ride-1', objectPage: 'ride' },
];

function themedUser(darkMode: boolean, totalRides: number = rides.length) {
  return {
    ...user,
    is_dark_mode: darkMode,
    total_rides: totalRides,
    total_distance_km: 91,
    total_elevation_m: 1650,
    total_dung_earned: 245,
    current_streak: 2,
    last_activity_date: rides[0].started_at,
  };
}

function profileRides(options: RouteFixtureOptions) {
  if (options.failedUploadRides) return options.failedUploadRides;
  if (options.withRideListShapes) return rides.map((item, index) => ({
    ...item,
    ...(index === 0 ? {
      elevation_profile: [
        { distance_m: 0, elevation_m: 20 },
        { distance_m: 200, elevation_m: 80 },
        { distance_m: 500, elevation_m: 40 },
        { distance_m: 1000, elevation_m: 120 },
      ],
      counted_spans: [{ start_distance_m: 100, end_distance_m: 400 }],
    } : {}),
  }));
  if (options.withThresholdHeldRide) {
    return [ride('ride-1', 1, 'Morning Ride', 48_200, 620, 0, {
      cal_earned: null,
      rewardable_cal: null,
      tributable_cal: null,
      reward_policy: 'threshold_provisional_hold_v1',
      threshold_economy_state: 'held',
    })];
  }
  if (options.withThresholdPendingTraining) {
    return rides.map((item) => ({
      ...item,
      threshold_training_state: 'pending',
    }));
  }
  if (options.withRideLogEmptyStates) return rideLogContractRides;
  if (options.rideListTotal != null) {
    return Array.from({ length: options.rideListTotal }, (_, index) => (
      ride(
        `ride-history-${index + 1}`,
        index % 180,
        `Ride ${String(index + 1).padStart(3, '0')}`,
        20_000 + index,
        250 + (index % 500),
        index % 7 === 0 ? 42 : 0,
      )
    ));
  }
  return options.withRideMedia ? ridesWithUploadedMedia : rides;
}

interface RouteFixtureOptions {
  failedUploadRides?: Array<ReturnType<typeof ride> & { uploaded_at?: string | null }>;
  withRideListShapes?: boolean;
  darkMode: boolean;
  isAdmin?: boolean;
  withRideMedia?: boolean;
  uploadCompleteStatus?: 'completed' | 'processing';
  withRideLogEmptyStates?: boolean;
  withClimbViewSpecimen?: boolean;
  withCanonVaultCreationSpecimen?: boolean;
  canonVaultPrepareDelayMs?: number;
  pendingRewardsDelayMs?: number;
  withExactTokenSpecimen?: boolean;
  feedActivityCopies?: number;
  rideListTotal?: number;
  rideListMaxLimit?: number;
  rideListFailureStatus?: number;
  profileRideTotal?: number;
  withThresholdHeldRide?: boolean;
  withThresholdPendingTraining?: boolean;
  withTrainingFigures?: boolean;
  trainingFiguresFail?: boolean;
  trainingDelayMs?: number;
}

interface StrangerWalkRouteState {
  authenticated: boolean;
  inviteValidatedCode: string | null;
  authInviteCode: string | null;
  authWallet: string | null;
  authPrivyToken: string | null;
  uploadInitSeen: boolean;
  uploadCompleteSeen: boolean;
}

function responseFor(
  url: URL,
  method: string,
  options: RouteFixtureOptions,
  requestBody: Record<string, unknown> = {},
): unknown {
  const path = url.pathname.replace(/^\/api/, '') || '/';

  if (path === '/auth/bootstrap') {
    return {
      authenticated: true,
      invite_required: false,
      invite_validated: true,
      needs_profile_setup: false,
      auth_method_hint: 'wallet',
      user: themedUser(options.darkMode, options.profileRideTotal ?? options.rideListTotal),
    };
  }

  if (path === '/auth/onboarding/state') {
    return {
      authenticated: true,
      invite_required: false,
      invite_validated: true,
      needs_profile_setup: false,
      auth_method_hint: 'wallet',
    };
  }

  if (path === '/me' || path === '/users/me') {
    return themedUser(options.darkMode, options.profileRideTotal ?? options.rideListTotal);
  }
  if (path === '/users/me/threshold') {
    return {
      contract_version: 'threshold.v1',
      state: 'established',
      current_w: 245,
      established_at: iso(14),
      last_raised_at: null,
      pending_monday: options.withThresholdPendingTraining ? {
        watts: 251,
        effective_at: iso(-7),
      } : null,
      sealing_in_progress: false,
    };
  }
  if (path === '/auth/refresh') return { access_token: 'fixture-token' };
  if (path === '/status') return { environment: 'test', solana_stub_mode: true, version: 'fixture', balance_rollout: { enforced: true, order_valid: true, blockers: [], action_order: ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'], enabled_actions: ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'] } };
  if (path === '/privacy/settings') {
    return {
      contract_version: 'privacy.v2',
      profile_visibility: 'public',
      default_ride_visibility: 'public',
      default_map_visibility: 'hide_start_end',
      default_map_hide_start_m: 200,
      default_map_hide_end_m: 200,
      defaults_apply_to: 'future_rides',
      provider_privacy_inherited: false,
      privacy_zone_count: 1,
      privacy_zones_loaded: true,
      ride_override_mode: 'optional',
      protocol_public_fields: [],
    };
  }
  const feedActivityCopies = Math.max(1, options.feedActivityCopies ?? 1);
  const feedActivities = Array.from({ length: feedActivityCopies }, (_, copyIndex) => (
    rides.map((r, index) => ({
      id: `feed-${copyIndex}-${r.id}`,
      type: 'ride',
      title: copyIndex === 0 ? r.title : `${r.title} ${copyIndex + 1}`,
      created_at: copyIndex === 0 ? r.started_at : iso((copyIndex * rides.length) + index + 1),
      occurred_at: copyIndex === 0 ? r.started_at : iso((copyIndex * rides.length) + index + 1),
      user: { id: user.id, username: user.username, display_name: user.display_name, avatar_url: null },
      metadata: {
        distance_m: r.distance_m,
        elevation_m: r.elevation_m,
        duration_s: r.duration_s,
        cal_earned: r.cal_earned,
        kudos_count: 2,
        comment_count: 1,
        ...(copyIndex === 0 && index === 0 ? { route_preview: r.route_preview } : {}),
      },
    }))
  )).flat();

  const suggestedRiders = [
    { id: 'rider-1', username: '@rider_56bff2', display_name: 'Rider 56', mutual_followers: 0, is_following: false },
    { id: 'rider-2', username: '@rider_d3eeca', display_name: 'Rider D3', mutual_followers: 1, is_following: false },
  ];

  const popularClimbs = [
    {
      id: 'climb-1',
      name: 'Full Stack Smoke 1776366970',
      region: 'Boulder',
      elev_gain_m: 617,
      completions: 3,
      staked: '1250',
      staked_base_units: '1250000000000',
    },
    {
      id: 'climb-2',
      name: 'Full Stack Smoke 1776369548',
      region: 'Boulder',
      elev_gain_m: 909,
      completions: 2,
      staked: '0',
      staked_base_units: '0',
    },
  ];

  if (path === '/feed/home') {
    return {
      contract_version: 'feed_home.v1',
      scope: url.searchParams.get('scope') === 'following' ? 'following' : 'global',
      viewer: {
        authenticated: true,
        user_id: user.id,
        wallet: TEST_WALLET,
      },
      feed: {
        activities: feedActivities,
        has_more: false,
        next_cursor: null,
      },
      suggested_riders: suggestedRiders,
      popular_climbs: popularClimbs,
      achievements: [
        {
          id: 'ach-1',
          achievement_type: 'explorer',
          title: 'Explorer: 59 New Areas',
          description: 'Discovered 59 new areas!',
          value: 59,
          created_at: iso(49),
        },
      ],
      social_counts: {
        follower_count: 0,
        following_count: 1,
      },
      notifications: {
        unread_count: 1,
      },
    };
  }

  if (path === '/feed/global' || path === '/feed') {
    return {
      activities: feedActivities,
      has_more: false,
      next_cursor: null,
    };
  }

  if (path === '/social/suggested') {
    return {
      suggestions: suggestedRiders,
    };
  }

  if (path === '/climbs/popular') {
    return {
      climbs: popularClimbs,
    };
  }

  if (/^\/social\/followers\/[^/]+$/.test(path)) return [];
  if (/^\/social\/following\/[^/]+$/.test(path)) return [{ id: 'tim' }];
  if (/^\/social\/is-following\/[^/]+$/.test(path)) return { is_following: true };
  if (path === '/admin/check') return { is_admin: Boolean(options.isAdmin), role: options.isAdmin ? 'admin' : null };
  if (path === '/admin/platform/overview') {
    return {
      users: { total: 2, new7d: 0 },
      rides: { total: 3, thisWeek: 1, totalTss: 245, totalDistanceM: 91_000, totalElevationM: 1_650, byStatus: {} },
      vaults: { total: 2, totalCompletions: 5, totalStakedCal: 1200, uniqueStakers: 2 },
      climbs: { total: 2, scored: 2, pctScored: 100 },
      epoch: { currentEpoch: 7, storedEpoch: 7, epochNeedsTransition: false, pendingDistributions: 0 },
      supply: {
        maxSupplyBaseUnits: '1000000000000000000',
        totalMintedBaseUnits: '2400000000000',
        protocolBurnedBaseUnits: '0',
        circulatingSupplyBaseUnits: '2400000000000',
        circulatingSource: 'spl_mint_supply',
        communityMintedBaseUnits: '1200000000000',
        communityCapBaseUnits: '400000000000000000',
        treasuryMintedBaseUnits: '1200000000000',
        treasuryCapBaseUnits: '250000000000000000',
        teamMintedBaseUnits: '0',
        teamCapBaseUnits: '200000000000000000',
        investorMintedBaseUnits: '0',
        investorCapBaseUnits: '100000000000000000',
        polMintedBaseUnits: '0',
        polCapBaseUnits: '50000000000000000',
      },
      emission: { currentEpoch: 7, currentEmissionRateBps: 100, totalHalvings: 0, nextHalvingAt: null },
      controls: {
        stakingEnabled: true,
        mintingEnabled: true,
        uploadsEnabled: true,
        withdrawalsEnabled: true,
        maintenanceMode: false,
      },
      healthStatus: 'healthy',
      generatedAt: iso(0),
    };
  }
  if (path === '/admin/platform/activity-feed') return { items: [], count: 0 };
  if (path === '/admin/moderation/reports') {
    return {
      reports: [
        {
          contract_version: 'moderation.v1',
          id: 'report-1',
          reporter_id: 'reporter-user-id',
          target_type: 'user',
          target_id: 'reported-user-id',
          reason: 'spam',
          details: 'Reported rider identity issue.',
          status: 'open',
          created_at: iso(0),
          updated_at: iso(0),
          reporter: {
            id: 'reporter-user-id',
            username: 'tim',
            display_name: 'Tim Trail',
            avatar_url: null,
          },
        },
      ],
      count: 1,
    };
  }
  if (path === '/riders/search' || path === '/users/search') return { riders: [], users: [], results: [] };
  if (path === '/users/tim' || path === '/users/tim-user') return publicRider;
  if (path === '/users/other-rider') {
    return { ...publicRider, id: 'other-rider', username: 'public-rider', display_name: 'Public Rider' };
  }
  if (path === '/users/tim/profile') {
    const recentRides = {
      is_public: true,
      rides: profileRides(options).map((r) => ({
        id: r.id,
        title: r.title,
        started_at: r.started_at,
        distance_m: r.distance_m,
        elevation_gain_m: r.elevation_m,
        duration_sec: r.duration_s,
        visibility: 'public',
        route_preview: r.route_preview,
        primary_media: r.primary_media,
        media: r.media,
      })),
      count: rides.length,
      privacy: { visibility: 'public' },
    };
    const beetleCards = {
      is_public: true,
      cards: publicBeetleCards,
      count: publicBeetleCards.length,
      privacy: { visibility: 'public' },
    };
    return {
      contract_version: 'public_rider_profile.v1',
      rider: {
        id: 'tim-user',
        username: 'tim',
        display_name: 'Tim Trail',
        avatar_url: null,
        viewer_relationship: 'following',
      },
      profile: {
        ...publicRider,
        rider: { ...publicRider.rider, viewer_relationship: 'following' },
        privacy: {
          visibility: 'public',
          can_view: true,
          is_owner: false,
          is_follower: true,
          redact_gps: true,
          reason: 'public_profile',
        },
      },
      privacy: {
        visibility: 'public',
        can_view: true,
        is_owner: false,
        is_follower: true,
        redact_gps: true,
        reason: 'public_profile',
      },
      viewer_capabilities: {
        can_view: true,
        can_follow: true,
        can_share: true,
        can_report: true,
        can_open_scan: true,
        viewer_relationship: 'following',
      },
      modules: [
        { key: 'profile', state: 'present', title: 'Profile' },
        { key: 'recent_rides', state: 'present', title: 'Recent rides', count: recentRides.count },
        { key: 'beetle_cards', state: 'present', title: 'BeetleCards', count: beetleCards.count },
      ],
      follow_state: { is_following: true, is_followed_by: false, is_mutual_follow: false },
      recent_rides: recentRides,
      beetle_cards: beetleCards,
      leaderboard: null,
    };
  }
  if (path === '/users/tim/recent-rides') {
    return {
      is_public: true,
      rides: profileRides(options).map((r) => ({
        id: r.id,
        title: r.title,
        started_at: r.started_at,
        distance_m: r.distance_m,
        elevation_gain_m: r.elevation_m,
        duration_sec: r.duration_s,
        visibility: 'public',
        route_preview: r.route_preview,
        primary_media: r.primary_media,
        media: r.media,
      })),
      count: rides.length,
      privacy: { visibility: 'public' },
    };
  }
  if (path === '/users/tim/beetle-cards') {
    return {
      is_public: true,
      cards: publicBeetleCards,
      count: publicBeetleCards.length,
      privacy: { visibility: 'public' },
    };
  }
  if (path === '/users/tim/beetle-cards') {
    return {
      is_public: true,
      cards: publicBeetleCards,
      count: publicBeetleCards.length,
      privacy: { visibility: 'public' },
    };
  }
  if (path === '/search/suggestions') return { contract_version: 'search.v1', sections: [] };
  if (path === '/search') {
    return {
      contract_version: 'search.v1',
      query: url.searchParams.get('q') ?? '',
      normalized_query: (url.searchParams.get('q') ?? '').toLowerCase(),
      type: url.searchParams.get('type') ?? 'riders',
      results: [
        {
          contract_version: 'search.v1',
          id: 'search-rider-tim',
          type: 'rider',
          title: LONG_RIDER_WALLET,
          subtitle: `${LONG_RIDER_WALLET} · Boulder`,
          summary: 'Public rider profile',
          target: { type: 'rider', id: 'tim' },
          web_path: `/rider/${LONG_RIDER_WALLET}`,
          source: 'backend',
          privacy: { visibility: 'public' },
          stats: [
            { label: 'Rides', value: '12' },
            { label: 'Followers', value: '3' },
          ],
          image: null,
          score: 0.99,
          matched_fields: ['username'],
          metadata: {
            username: 'tim',
            display_name: 'Tim Trail',
            wallet: LONG_RIDER_WALLET,
            location: 'Boulder',
          },
        },
      ],
      has_more: false,
    };
  }

  if (path === '/rides') {
    if (options.rideListFailureStatus) {
      return apiError(options.rideListFailureStatus, 'Ride history is temporarily unavailable.');
    }

    const requestedLimit = Number(url.searchParams.get('limit') ?? 50);
    const requestedOffset = Number(url.searchParams.get('offset') ?? 0);
    if (options.rideListMaxLimit && requestedLimit > options.rideListMaxLimit) {
      return apiError(422, `limit must be less than or equal to ${options.rideListMaxLimit}`);
    }

    return profileRides(options).slice(requestedOffset, requestedOffset + requestedLimit);
  }
  if (path === '/rides/upload/init' && method === 'POST') {
    return {
      upload_id: 'upload-direct-1',
      signed_url: 'https://storage.test/object/upload/sign/rides/user-test-1/upload-direct-1.gpx?token=test-token',
      expires_in: 600,
    };
  }
  if (path === '/rides/upload/complete' && method === 'POST') {
    return {
      ride_id: 'ride-uploaded-1',
      status: options.uploadCompleteStatus ?? 'completed',
    };
  }
  if (path === '/rides/ride-uploaded-1') return cohortUploadedRide;
  if (path === '/rides/ride-uploaded-1/status') {
    return {
      status: 'completed',
    };
  }
  if (path === '/rides/ride-no-power/status') {
    return {
      contract_version: 'client.v1',
      truth_source: 'backend',
      ride_id: 'ride-no-power',
      status: 'finalized',
      attestation_status: 'finalized',
      ride_hash_hex: 'hash-ride-no-power',
      finalized_at: iso(1),
      has_gps: true,
      has_patterns: true,
      has_leaderboards: true,
      has_achievements: false,
      cal_earned: 96,
      dung_minted: 96,
      metrics: {
        tss: 88,
        kcals: 980,
        distance_m: 32_000,
        elevation_gain_m: 440,
        duration_sec: 5_400,
        avg_power_w: null,
        normalized_power_w: null,
      },
      input_quality: {
        status: 'clean',
        sensor_data_state: 'partial',
        gps_coverage: 1,
        elevation_coverage: 1,
        speed_coverage: 1,
        power_coverage: 0,
      },
    };
  }
  if (path === '/rides/ride-error/gps') {
    return apiError(503, 'GPS stream unavailable');
  }
  if (path === '/rides/ride-coordinate-error/gps') {
    return {
      gps_points: rideGpsPointsWithoutCoordinates,
      imported_count: rideGpsPointsWithoutCoordinates.length,
      failed_count: 0,
    };
  }
  if (path === '/rides/ride-private-route/gps') {
    return {
      gps_points: rideGpsPointsRedacted,
      imported_count: rideGpsPointsRedacted.length,
      failed_count: 0,
    };
  }
  if (/^\/rides\/[^/]+\/gps$/.test(path)) {
    return {
      gps_points: rideGpsPoints,
      imported_count: rideGpsPoints.length,
      failed_count: 0,
    };
  }
  if (/^\/rides\/[^/]+\/status$/.test(path)) {
    if (options.withThresholdHeldRide) {
      return {
        contract_version: 'client.v1',
        truth_source: 'backend',
        ride_id: 'ride-1',
        status: 'finalized',
        attestation_status: 'finalized',
        ride_hash_hex: 'hash-ride-1',
        finalized_at: iso(1),
        cal_earned: null,
        metrics: { tss: null, distance_m: 48_200, elevation_gain_m: 620, duration_sec: 5_400 },
        effort_policy: {
          effort_evidence_tier: 'power_verified',
          reward_policy: 'threshold_provisional_hold_v1',
          threshold_economy_state: 'held',
          rewardable_cal: null,
          tributable_cal: null,
        },
      };
    }
    return {
      contract_version: 'client.v1',
      truth_source: 'backend',
      ride_id: 'ride-1',
      status: 'finalized',
      attestation_status: 'finalized',
      ride_hash_hex: 'hash-ride-1',
      finalized_at: iso(1),
      has_gps: true,
      has_patterns: true,
      has_leaderboards: true,
      has_achievements: false,
      cal_earned: 96,
      dung_minted: 96,
      metrics: {
        tss: 112,
        threshold_training_state: options.withThresholdPendingTraining ? 'pending' : null,
        kcals: 1320,
        distance_m: 48_200,
        elevation_gain_m: 620,
        duration_sec: 5_400,
        avg_power_w: 216,
        normalized_power_w: 238,
      },
    };
  }
  if (/^\/rides\/[^/]+\/streams$/.test(path)) {
    const streamType = url.searchParams.get('type') || 'power';
    if (path === '/rides/ride-private-route/streams') {
      return {
        id: `private-stream-${streamType}`,
        ride_id: 'ride-private-route',
        stream_type: streamType,
        timestamps: [rideGpsPoints[0].timestamp, rideGpsPoints[1].timestamp],
        values: [998, 999],
        sample_count: 2,
        min_value: 998,
        max_value: 999,
        avg_value: 998.5,
      };
    }
    if (path === '/rides/ride-no-power/streams' && streamType === 'power') {
      return {
        id: null,
        ride_id: 'ride-no-power',
        stream_type: 'power',
        timestamps: [],
        values: [],
        sample_count: 0,
        min_value: null,
        max_value: null,
        avg_value: null,
      };
    }
    const baseValues: Record<string, number[]> = {
      power: [160, 184, 203, 232, 270, 318, 296, 260, 244, 282, 326, 301, 238, 210, 192, 176],
      heart_rate: [118, 124, 132, 141, 151, 162, 166, 160, 154, 158, 168, 171, 162, 148, 136, 128],
      cadence: [82, 84, 86, 89, 91, 92, 90, 88, 86, 90, 94, 93, 88, 84, 82, 80],
      speed: [7.2, 7.5, 7.9, 8.2, 8.5, 8.1, 7.6, 8.8, 9.2, 8.7, 8.1, 7.4, 9.5, 9.8, 9.2, 8.6],
      temperature: [16, 16, 17, 17, 18, 18, 18, 19, 19, 19, 20, 20, 19, 18, 18, 17],
    };
    const values = baseValues[streamType] ?? baseValues.power;
    return {
      id: `stream-${streamType}`,
      ride_id: 'ride-1',
      stream_type: streamType,
      timestamps: rideGpsPoints.map((point) => point.timestamp),
      values,
      sample_count: values.length,
      min_value: Math.min(...values),
      max_value: Math.max(...values),
      avg_value: values.reduce((sum, value) => sum + value, 0) / values.length,
    };
  }
  if (path === '/rides/ride-error/tiles') {
    return apiError(503, 'Tile stream unavailable');
  }
  if (/^\/rides\/[^/]+\/tiles$/.test(path)) {
    return {
      ride_id: 'ride-1',
      tile_samples: [
        { tile_id: '8928308280fffff', t: 0, elevation_m: 20, power_w: 180, hr_bpm: 142, speed_mps: 7.2 },
        { tile_id: '8928308281fffff', t: 900, elevation_m: 80, power_w: 245, hr_bpm: 156, speed_mps: 8.5 },
      ],
      total_samples: 2,
      unique_tiles: 2,
    };
  }
  if (path === '/rides/ride-error/patterns') {
    return apiError(503, 'Pattern stream unavailable');
  }
  if (path === '/rides/ride-private-route/patterns') {
    return {
      ride_id: 'ride-private-route',
      patterns: {
        climb_patterns: [
          {
            climb_id: 'climb-1',
            name: 'Full Stack Smoke 1776366970',
            road_name: 'Ellis Street',
            match_trace: { detection: { effort_bounds: [600, 1_260] } },
            vert_m: 412,
            distance_m: 3_700,
            avg_gradient_pct: 7.4,
            duration_s: 660,
            avg_speed_mps: 5.6,
            vam: 2247,
            signature_hex: 'pattern-signature-private-1',
          },
        ],
      },
      summary: '1 climb',
      total_count: 1,
    };
  }
  if (path === '/rides/ride-filtered-climbs/patterns') {
    return {
      ride_id: 'ride-filtered-climbs',
      patterns: {
        climb_patterns: [
          {
            climb_id: 'climb-without-offsets',
            name: 'Unmapped Climb',
            road_name: 'Unknown Road',
            vert_m: 90,
            distance_m: 900,
            avg_gradient_pct: 5,
            duration_s: 300,
          },
          {
            climb_id: 'climb-after-filter',
            name: 'Mapped Profile Climb',
            road_name: 'Mapped Road',
            start_offset_s: 600,
            end_offset_s: 1_260,
            vert_m: 412,
            distance_m: 3_700,
            avg_gradient_pct: 7.4,
            duration_s: 660,
            avg_speed_mps: 5.6,
            vam: 2247,
          },
        ],
      },
      summary: '2 climbs',
      total_count: 2,
    };
  }
  if (/^\/rides\/[^/]+\/patterns$/.test(path)) {
    return {
      ride_id: 'ride-1',
      patterns: {
        climb_patterns: [
          {
            climb_id: 'climb-1',
            name: 'Full Stack Smoke 1776366970',
            road_name: 'Ellis Street',
            start_offset_s: 600,
            end_offset_s: 1_260,
            vert_m: 412,
            distance_m: 3_700,
            avg_gradient_pct: 7.4,
            duration_s: 660,
            avg_speed_mps: 5.6,
            vam: 2247,
            signature_hex: 'pattern-signature-1',
            vault_match: {
              id: 'match-1',
              vault_id: 1,
              name: 'Full Stack Smoke',
              similarity: 0.96,
              is_strong_match: true,
              your_time: 610,
              your_rank: 2,
              your_best_time: 610,
              is_pr: true,
              is_new_entry: false,
              kom_time: 590,
              kom_holder: LONG_RIDER_WALLET,
              total_completions: 42,
            },
          },
        ],
        steady_pattern: {
          duration_s: 1_800,
          avg_power_w: 216,
          avg_hr_bpm: 156,
          start_time_offset_s: 1_300,
          end_time_offset_s: 3_100,
        },
        exploration_pattern: {
          new_tiles_wallet: 2,
          total_tiles: 12,
          discovery_pct: 0.17,
        },
      },
      summary: '1 climb, 1 steady block, 2 new tiles',
      total_count: 3,
    };
  }
  if (/^\/rides\/[^/]+\/interactions$/.test(path)) {
    return {
      ride_id: path.split('/')[2],
      kudos_count: 1,
      comment_count: 1,
      viewer_has_kudos: false,
      viewer_reported: false,
      comments_enabled: true,
      can_comment: true,
    };
  }
  if (/^\/rides\/[^/]+\/comments$/.test(path)) {
    return {
      comments: [
        {
          id: 'comment-1',
          user_id: 'rider-comment-tim',
          username: 'tim',
          display_name: 'Tim Trail',
          content: 'Nice climb signal.',
          created_at: iso(1),
          updated_at: iso(1),
          viewer_reported: false,
          report_status: null,
        },
      ],
    };
  }
  if (path === '/rides/ride-public') {
    return {
      ...ride('ride-public', 2, 'Public Ride', 32_000, 440, 0),
      rider_id: 'other-rider',
      is_owner: false,
    };
  }
  if (path === '/rides/ride-no-power') {
    return {
      ...ride('ride-no-power', 2, 'No Power Ride', 32_000, 440, 96),
      avg_power_w: null,
      normalized_power_w: null,
      rider_id: user.id,
      is_owner: true,
    };
  }
  if (path === '/rides/ride-error') {
    return {
      ...ride('ride-error', 2, 'Sparse Ride', 32_000, 440, 0),
      rider_id: user.id,
      is_owner: true,
    };
  }
  if (path === '/rides/ride-coordinate-error') {
    return {
      ...ride('ride-coordinate-error', 2, 'Coordinate Sparse Ride', 32_000, 440, 0),
      rider_id: user.id,
      is_owner: true,
    };
  }
  if (path === '/rides/ride-filtered-climbs') {
    return {
      ...ride('ride-filtered-climbs', 2, 'Filtered Climb Ride', 32_000, 440, 0),
      rider_id: user.id,
      is_owner: true,
    };
  }
  if (path === '/rides/ride-private-route') {
    return {
      ...ride('ride-private-route', 2, 'Private Route Ride', 32_000, 440, 0),
      rider_id: 'tim-user',
      is_owner: false,
      privacy: {
        visibility: 'public',
        can_view: true,
        is_owner: false,
        is_follower: false,
        redact_gps: true,
        protocol_public: true,
        protocol_public_fields: [],
        reason: 'public',
      },
    };
  }
  if (/^\/rides\/[^/]+$/.test(path)) {
    const rideId = path.split('/')[2];
    const visibleRides = profileRides(options);
    return visibleRides.find((item) => item.id === rideId) ?? visibleRides[0];
  }

  if (path === '/climbs/list') {
    const search = url.searchParams.get('q')?.trim().toLowerCase();
    const climbs = search
      ? canonicalClimbs.filter((climb) => (
          climb.name.toLowerCase().includes(search)
          || climb.region.toLowerCase().includes(search)
        ))
      : canonicalClimbs;
    return { climbs };
  }

  if (path === '/geocoding/search' && method === 'POST') {
    const search = typeof requestBody.query === 'string' ? requestBody.query.trim() : '';
    if (search === 'Unavailable') {
      return apiError(503, 'Location search is temporarily unavailable');
    }
    if (search === 'Nowhere') {
      return {
        contractVersion: 'geocoding.v1',
        state: 'available',
        results: [],
        attribution: {
          text: '© OpenStreetMap contributors',
          url: 'https://www.openstreetmap.org/copyright',
        },
        provider: 'nominatim',
        cached: true,
      };
    }
    return {
      contractVersion: 'geocoding.v1',
      state: 'available',
      results: [
        {
          displayName: 'Manayunk, Philadelphia, Pennsylvania, USA',
          latitude: 40.0564,
          longitude: -75.3102,
        },
      ],
      attribution: {
        text: '© OpenStreetMap contributors',
        url: 'https://www.openstreetmap.org/copyright',
      },
      provider: 'nominatim',
      cached: false,
    };
  }

  if (path === '/vaults') {
    const responseVaults = options.withExactTokenSpecimen
      ? vaults.map((item, index) => index === 0 ? {
          ...item,
          total_staked: '9007199.254740993',
          total_staked_base_units: '9007199254740993',
          total_cal_staked: '9007199.254740993',
          total_cal_staked_base_units: '9007199254740993',
        } : item)
      : vaults;
    return { vaults: responseVaults, total: vaults.length, offset: 0, limit: Number(url.searchParams.get('limit') ?? 50) };
  }
  if (path === '/vaults/stakes/me' || path === '/vaults/my/stakes') {
    return {
      stakes: [
        {
          vault_signature: 'vault-signature-1',
          vault_id: 1,
          vault_name: 'Full Stack Smoke',
          wallet: TEST_WALLET,
          cal_staked: options.withExactTokenSpecimen ? '9007199.254740993' : '1200',
          cal_staked_base_units: options.withExactTokenSpecimen ? '9007199254740993' : '1200000000000',
          lp_tokens: options.withExactTokenSpecimen ? '9007199.254740993' : '1180',
          lp_tokens_base_units: options.withExactTokenSpecimen ? '9007199254740993' : '1180000000000',
          staked_at: iso(20),
        },
      ],
    };
  }
  if (/^\/vaults\/\d+$/.test(path)) {
    const detailVault = options.withExactTokenSpecimen ? {
      ...vaults[0],
      total_staked: '9007199.254740993',
      total_staked_base_units: '9007199254740993',
      total_cal_staked: '9007199.254740993',
      total_cal_staked_base_units: '9007199254740993',
    } : vaults[0];
    return {
      ...detailVault,
      leaderboard: options.withClimbViewSpecimen
        ? [
            {
              vault_signature: 'vault-signature-1',
              rank: 1,
              wallet: LONG_RIDER_WALLET,
              best_time_seconds: 590,
              avg_power_w: 382,
              completion_id: 'completion-tim',
              achieved_at: iso(1),
            },
            {
              vault_signature: 'vault-signature-1',
              rank: 2,
              wallet: TEST_WALLET,
              best_time_seconds: 620,
              avg_power_w: 318,
              completion_id: 'completion-me',
              achieved_at: iso(2),
            },
            {
              vault_signature: 'vault-signature-1',
              rank: 3,
              wallet: 'thirdrider11111111111111111111111111111',
              best_time_seconds: 653,
              avg_power_w: 296,
              completion_id: 'completion-third',
              achieved_at: iso(3),
            },
          ]
        : [
            {
              vault_signature: 'vault-signature-1',
              rank: 1,
              wallet: LONG_RIDER_WALLET,
              best_time_seconds: 590,
              avg_power_w: 382,
              completion_id: 'completion-tim',
              achieved_at: iso(1),
            },
          ],
      total_lp_tokens: '1180',
      total_lp_tokens_base_units: '1180000000000',
      local_legend: {
        wallet: LONG_RIDER_WALLET,
        elected_epoch: 3,
        term_end_epoch: 4,
        completions_count: 8,
      },
    };
  }
  if (/^\/vaults\/\d+\/leaderboard$/.test(path)) {
    return {
      contract_version: 'client.v1',
      truth_source: 'attested',
      climb_id: 'climb-1',
      climb_name: 'Full Stack Smoke',
      vault_id: 1,
      leaderboard: [
        {
          vault_signature: 'vault-signature-1',
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          best_time_seconds: 590,
          avg_power_w: 382,
          completion_id: 'completion-tim',
          achieved_at: iso(1),
        },
        {
          vault_signature: 'vault-signature-1',
          rank: 2,
          wallet: TEST_WALLET,
          best_time_seconds: 620,
          avg_power_w: 318,
          completion_id: 'completion-you',
          achieved_at: iso(2),
        },
      ],
      entries: [
        {
          vault_signature: 'vault-signature-1',
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          best_time_seconds: 590,
          avg_power_w: 382,
          completion_id: 'completion-tim',
          achieved_at: iso(1),
        },
        {
          vault_signature: 'vault-signature-1',
          rank: 2,
          wallet: TEST_WALLET,
          best_time_seconds: 620,
          avg_power_w: 318,
          completion_id: 'completion-you',
          achieved_at: iso(2),
        },
      ],
      kom_holder: LONG_RIDER_WALLET,
      kom_time_s: 590,
    };
  }
  if (/^\/vaults\/\d+\/pending-rewards$/.test(path)) {
    const pendingVaultId = Number(path.split('/')[2]);
    if (options.withExactTokenSpecimen) {
      const isSecondVault = pendingVaultId === 2;
      return {
        vault_signature: 'vault-signature-1',
        vault_name: 'Full Stack Smoke',
        pending_rewards: [
          {
            epoch: 22,
            receipt_type: 'STAKE_CLAIMABLE',
            amount: isSecondVault ? '0.8' : '4.25',
            amount_base_units: isSecondVault ? '800000000' : '4250000000',
            rank: null,
          },
        ],
        total_pending: isSecondVault ? '0.8' : '4.25',
        total_pending_base_units: isSecondVault ? '800000000' : '4250000000',
        fee_estimate: isSecondVault ? '0.04' : '0.2125',
        fee_estimate_base_units: isSecondVault ? '40000000' : '212500000',
        net_estimate: isSecondVault ? '0.76' : '4.0375',
        net_estimate_base_units: isSecondVault ? '760000000' : '4037500000',
        harvest_fee_bps: '500',
        exit_fee_bps: '50',
        lp_tokens_base_units: isSecondVault ? '700000000000' : '1000000000000',
        withdrawal_amount_base_units: isSecondVault ? '700000000000' : '1250000000000',
        withdrawal_fee_base_units: isSecondVault ? '3500000000' : '6250000000',
        withdrawal_net_base_units: isSecondVault ? '696500000000' : '1243750000000',
      };
    }
    return {
      vault_signature: 'vault-signature-1',
      vault_name: 'Full Stack Smoke',
      pending_rewards: [],
      total_pending: '0',
      total_pending_base_units: '0',
      fee_estimate: '0',
      fee_estimate_base_units: '0',
      net_estimate: '0',
      net_estimate_base_units: '0',
      harvest_fee_bps: '500',
      exit_fee_bps: '50',
      lp_tokens_base_units: '1000000000000',
      withdrawal_amount_base_units: '1200000000000',
      withdrawal_fee_base_units: '6000000000',
      withdrawal_net_base_units: '1194000000000',
    };
  }
  if (/^\/distributions\/vault\/\d+$/.test(path)) {
    const emptyCarry = {
      record_royalty: '0',
      record_royalty_base_units: '0',
      stakers: '0',
      stakers_base_units: '0',
      local_legend: '0',
      local_legend_base_units: '0',
      pol: '0',
      pol_base_units: '0',
      treasury: '0',
      treasury_base_units: '0',
      total: '0',
      total_base_units: '0',
    };
    if (!options.withExactTokenSpecimen) {
      return {
        vault_id: 1,
        vault_signature: 'vault-signature-1',
        vault_name: 'Full Stack Smoke',
        current_carry: emptyCarry,
        distributions: [],
        total_distributed: '0',
        total_distributed_base_units: '0',
        distribution_count: 0,
      };
    }
    return {
      vault_id: 1,
      vault_signature: 'vault-signature-1',
      vault_name: 'Full Stack Smoke',
      current_carry: {
        ...emptyCarry,
        record_royalty: '0.000000001',
        record_royalty_base_units: '1',
        stakers: '0.1',
        stakers_base_units: '100000000',
        total: '0.100000001',
        total_base_units: '100000001',
      },
      distributions: [
        {
          distribution_id: 'sig-exact:0',
          epoch: 22,
          total_amount: '340',
          total_amount_base_units: '340000000000',
          leaderboard_amount: '187',
          leaderboard_amount_base_units: '187000000000',
          staker_amount: '91.8',
          staker_amount_base_units: '91800000000',
          local_legend_amount: '10.2',
          local_legend_amount_base_units: '10200000000',
          pol_amount: '17',
          pol_amount_base_units: '17000000000',
          protocol_amount: '34',
          protocol_amount_base_units: '34000000000',
          distributed_at: iso(0),
          finalized_at: iso(0),
          staker_count: 3,
          unlock_pct: 100,
          locked_staker_amount: '0',
          locked_staker_amount_base_units: '0',
          leaderboard_details: null,
          settlement_status: null,
        },
      ],
      total_distributed: '340',
      total_distributed_base_units: '340000000000',
      distribution_count: 1,
    };
  }
  if (/^\/vaults\/\d+\/my-completions$/.test(path)) {
    return {
      vault_id: 1,
      vault_name: 'Full Stack Smoke',
      efforts: [],
      total_count: 0,
      best_time_seconds: null,
      total_prs: 0,
    };
  }

  if (path === '/climbs/climb-1' || path === `/climbs/${CANON_CLIMB_ROW_ID}`) {
    const climbId = path.slice('/climbs/'.length);
    const hasVault = !options.withCanonVaultCreationSpecimen;
    return {
      contract_version: 'client.v1',
      truth_source: 'attested',
      id: climbId,
      canon_id: '22222222-2222-4222-8222-222222222222',
      version: 1,
      vault_creation: {
        state: hasVault ? 'active' : 'available',
        payment_methods: hasVault ? [] : ['dung', 'cal_usdc'],
      },
      name: options.withCanonVaultCreationSpecimen ? 'Manayunk Wall' : 'Full Stack Smoke 1776366970',
      region: options.withCanonVaultCreationSpecimen ? 'Philadelphia' : 'Boulder',
      length_m: options.withCanonVaultCreationSpecimen ? 546.66 : 3700,
      elev_gain_m: options.withCanonVaultCreationSpecimen ? 59.4 : 412,
      avg_gradient_pct: options.withCanonVaultCreationSpecimen ? 10.866 : 7.4,
      route_preview: options.withCanonVaultCreationSpecimen ? CANON_VAULT_ROUTE_PREVIEW : null,
      elevation_profile: options.withCanonVaultCreationSpecimen ? CANON_VAULT_ELEVATION_PROFILE : [],
      total_completions: 42,
      has_vault: hasVault,
      vault_id: hasVault ? 1 : null,
      vault_economy: {
        contract_version: 'client.v1',
        truth_source: 'attested',
        has_vault: hasVault,
        vault_id: hasVault ? 1 : null,
        vault_signature: hasVault ? 'vault-signature-1' : null,
        total_staked: hasVault ? '12500' : '0',
        total_staked_base_units: hasVault ? '12500000000000' : '0',
        total_cal_staked: hasVault ? '12500' : '0',
        total_cal_staked_base_units: hasVault ? '12500000000000' : '0',
        total_completions: hasVault ? 42 : 0,
      },
      local_legend: {
        contract_version: 'client.v1',
        truth_source: 'attested',
        climb_id: climbId,
        vault_id: 1,
        wallet: LONG_RIDER_WALLET,
        attempts_in_window: 8,
      },
    };
  }

  if (
    path === '/climbs/climb-1/leaderboard'
    || path === `/climbs/${CANON_CLIMB_ROW_ID}/leaderboard`
  ) {
    const climbId = path.slice('/climbs/'.length, -'/leaderboard'.length);
    const entries = options.withClimbViewSpecimen
      ? [
        {
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          best_time_seconds: 590,
          avg_power_w: 382,
        },
        {
          rank: 2,
          wallet: TEST_WALLET,
          best_time_seconds: 620,
          avg_power_w: 318,
        },
        {
          rank: 3,
          wallet: 'thirdrider11111111111111111111111111111',
          best_time_seconds: 653,
          avg_power_w: 296,
        },
      ]
      : [
        {
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          best_time_seconds: 590,
          avg_power_w: 382,
        },
      ];

    return {
      contract_version: 'client.v1',
      truth_source: 'attested',
      climb_id: climbId,
      climb_name: 'Full Stack Smoke 1776366970',
      vault_id: 1,
      entries,
      kom_holder: LONG_RIDER_WALLET,
      kom_time_s: 590,
    };
  }

  if (path === '/territory/tiles') {
    return {
      tiles: [{ tile_id: '8928308280fffff', visit_count: 3, first_visited_at: iso(30), last_visited_at: iso(1) }],
      count: 1,
    };
  }
  if (path === '/territory/stats') return { total_tiles: 1, total_visits: 3, tiles_this_week: 1, tiles_this_month: 2 };
  if (path === '/territory/heatmap') return { tiles: [{ tile_id: '8928308280fffff', visit_count: 3 }] };

  if (path === '/notifications') {
    return {
      contract_version: 'notification.v1',
      unread_count: 1,
      notifications: [
        {
          id: 'notif-legacy-event-only',
          event_type: 'ride_kudos',
          title: 'Legacy kudos row',
          message: 'Tim liked your ride.',
          actor: { id: 'tim', username: 'tim', display_name: 'Tim', wallet: 'timwallet' },
          target: { type: 'ride', id: 'ride-1' },
          metadata: { ride_id: 'ride-1' },
          read: false,
          created_at: iso(0),
          occurred_at: iso(0),
          action_url: '/activities/ride-1',
        },
      ],
    };
  }
  if (path === '/notifications/preferences') {
    return {
      email_enabled: true,
      push_enabled: false,
      in_app_enabled: true,
      new_follower: true,
      ride_kudos: true,
      vault_rewards: true,
      system_announcements: true,
    };
  }
  if (/^\/notifications\/[^/]+\/read$/.test(path) || path === '/notifications/read-all') return { status: 'ok' };

  if (path === '/portfolio/snapshot') {
    return {
      contract_version: 'portfolio_snapshot.v4',
      portfolio: {
        contract_version: 'portfolio.v5',
        dung_balance: '18.75',
        dung_balance_base_units: '18750000000',
        wallet_dung: {
          amount: '18.75',
          amount_base_units: '18750000000',
          source: 'spl_wallet_ata',
          status: 'live',
          token_account: 'wallet-dung-ata',
          slot: 456,
        },
        balance_dung: {
          amount: '7.125',
          amount_base_units: '7125000000',
          source: 'rider_balance_token_pda',
          status: 'live',
          token_account: 'balance-dung-pda',
          slot: 457,
        },
        cal_balance: '22154',
        cal_balance_base_units: '22154000000000',
        harvest_fee_bps: '500',
        exit_fee_bps: '50',
        balance_lifecycle: {
          rider_account_id: 'rider-account-1',
          protocol_wallet: TEST_WALLET,
          status: 'active',
          initialized: true,
          rider_headline: 'Boulder Roller Balance',
          rider_detail: 'Balance is ready.',
          no_prompt_execution_allowed: true,
          can_add_funds: true,
          can_withdraw_to_wallet: true,
          setup_steps: [],
          assets: [
            {
              asset: 'CAL',
              exists: true,
              balance_base_units: '12345000000',
              rider_state: 'Ready',
              mint: 'cal-mint',
              token_account: 'cal-token-account',
              source: 'rider_balance_token_pda',
              source_status: 'live',
              slot: 458,
            },
            {
              asset: 'USDC',
              exists: true,
              balance_base_units: '25000000',
              rider_state: 'Ready',
              mint: 'usdc-mint',
              token_account: 'usdc-token-account',
              source: 'rider_balance_token_pda',
              source_status: 'live',
              slot: 458,
            },
            {
              asset: 'DUNG',
              exists: true,
              balance_base_units: '7125000000',
              rider_state: 'Ready',
              mint: 'dung-mint',
              token_account: 'balance-dung-pda',
              source: 'rider_balance_token_pda',
              source_status: 'live',
              slot: 457,
            },
          ],
          blockers: [],
          source: 'rider_balance_header_pda',
          source_status: 'live',
          account: 'rider-balance-header-pda',
          slot: 458,
          projection_status: 'recorded',
        },
        staked_positions: [
          {
            id: 'position-manayunk-wall',
            climb_id: 'climb-1',
            climb_name: 'Manayunk Wall',
            vault_id: 1,
            vault_name: 'Manayunk Wall vault',
            cal_deposited: '1200',
            cal_deposited_base_units: '1200000000000',
            dung_ready: '4.25',
            dung_ready_base_units: '4250000000',
            lp_tokens: '1180',
            lp_tokens_base_units: '1180000000000',
            record_rank: 2,
            local_legend: false,
            rider_state: 'Counting',
            updated_at: iso(1),
          },
          {
            id: 'position-river-loop',
            climb_id: 'climb-2',
            climb_name: 'River Loop Kick',
            vault_id: 2,
            vault_name: 'River Loop Kick vault',
            cal_deposited: '650',
            cal_deposited_base_units: '650000000000',
            dung_ready: '0.8',
            dung_ready_base_units: '800000000',
            lp_tokens: '640',
            lp_tokens_base_units: '640000000000',
            record_rank: 9,
            local_legend: true,
            rider_state: 'Counting',
            updated_at: iso(6),
          },
        ],
        pending_claims: [
          {
            id: 'claim-manayunk-week-22',
            climb_id: 'climb-1',
            climb_name: 'Manayunk Wall',
            amount: 4.25,
            state: 'ready',
          },
        ],
        total_claims: 1,
        total_staked: '1850',
        total_staked_base_units: '1850000000000',
        weekly_yield: '5.05',
        weekly_yield_base_units: '5050000000',
        total_yield: '27.4',
        total_yield_base_units: '27400000000',
        freshness: {
          source: 'fixture',
          chain_status: 'live',
          cal_status: 'live',
          wallet_dung_status: 'live',
          balance_dung_status: 'live',
          loaded_at: iso(0),
        },
      },
      distributions: {
        distributions: [
          {
            distribution_id: 'dist-manayunk-22',
            vault_signature: 'vault-manayunk-wall-111111111111111111',
            vault_id: 1,
            vault_name: 'Manayunk Wall vault',
            climb_id: 'climb-1',
            climb_name: 'Manayunk Wall',
            epoch: 22,
            total_amount: '5.05',
            total_amount_base_units: '5050000000',
            leaderboard_amount: '3.4',
            leaderboard_amount_base_units: '3400000000',
            staker_amount: '1.05',
            staker_amount_base_units: '1050000000',
            local_legend_amount: '0.6',
            local_legend_amount_base_units: '600000000',
            pol_amount: '0',
            pol_amount_base_units: '0',
            protocol_amount: '0',
            protocol_amount_base_units: '0',
            distributed_at: iso(0),
            settlement_status: null,
            receipts: [
              { id: 'receipt-record-board-1', receipt_type: 'LEADERBOARD', amount: '3.4', amount_base_units: '3400000000', rank: 2, created_at: iso(0) },
              { id: 'receipt-backer-1', receipt_type: 'STAKE', amount: '1.05', amount_base_units: '1050000000', rank: null, created_at: iso(0) },
              { id: 'receipt-local-legend-1', receipt_type: 'LOCAL_LEGEND', amount: '0.6', amount_base_units: '600000000', rank: null, created_at: iso(0) },
            ],
          },
        ],
        receipt_count: 3,
        distribution_count: 1,
        limit: 50,
        offset: 0,
      },
      freshness: {
        source: 'fixture',
        chain_status: 'live',
        cal_status: 'live',
        wallet_dung_status: 'live',
        balance_dung_status: 'live',
        loaded_at: iso(0),
        distribution_count: 1,
        receipt_count: 3,
      },
    };
  }
  if (path === '/portfolio') return {
    contract_version: 'portfolio.v5',
    dung_balance: '0',
    dung_balance_base_units: '0',
    wallet_dung: {
      amount: '0',
      amount_base_units: '0',
      source: 'spl_wallet_ata',
      status: 'not_initialized',
      token_account: 'wallet-dung-ata',
      slot: 456,
    },
    balance_dung: {
      amount: '0',
      amount_base_units: '0',
      source: 'rider_balance_token_pda',
      status: 'not_initialized',
      token_account: 'balance-dung-pda',
      slot: 456,
    },
    cal_balance: '22154',
    cal_balance_base_units: '22154000000000',
    staked_positions: [],
    pending_claims: [],
  };
  if (path === '/cal/onchain') {
    return {
      wallet: TEST_WALLET,
      cal_balance: '22154',
      cal_balance_base_units: '22154000000000',
      total_staked: 1200,
      cal_earned_today: 96,
      total_rides: rides.length,
      total_tss: 385,
      account_exists: true,
    };
  }
  if (path === '/distributions/my') {
    return { distributions: [], receipt_count: 0, distribution_count: 0, limit: 50, offset: 0 };
  }

  // Training tab charts (power curve, riding days) landed after this fixture;
  // abstaining payloads keep the tab's background fetch from hanging the walk.
  if (path === '/analytics/power-curve') {
    if (options.trainingFiguresFail) return apiError(422, 'Power curve temporarily unavailable');
    if (options.withTrainingFigures) return {
      contractVersion: 'power_curve.v1', durationsS: [1, 5, 60, 180, 420, 900, 3600],
      bestW: [700, 600, 400, 350, 300, 270, 230], sampledRides: 2, rideCount: 2, available: true,
      threshold: { sealedW: 245, candidateW: null, anchorsW: { '180': 350, '420': 300, '900': 270 } },
    };
    return {
      contractVersion: 'power_curve.v1',
      durationsS: [],
      bestW: [],
      sampledRides: 0,
      rideCount: 0,
      available: false,
      threshold: { sealedW: null, candidateW: null, anchorsW: {} },
    };
  }
  if (path === '/analytics/riding-days') {
    if (options.trainingFiguresFail) return apiError(422, 'Riding days temporarily unavailable');
    if (options.withTrainingFigures) return {
      contractVersion: 'riding_days.v1', startDate: iso(365).slice(0, 10), endDate: iso(0).slice(0, 10),
      days: [{ date: iso(1).slice(0, 10), moving_s: 3600, ride_count: 1 }, { date: iso(0).slice(0, 10), moving_s: 5400, ride_count: 1 }],
    };
    return {
      contractVersion: 'riding_days.v1',
      startDate: iso(182).slice(0, 10),
      endDate: iso(0).slice(0, 10),
      days: [],
    };
  }
  if (path === '/analytics/fitness') {
    return {
      ctl: 48,
      atl: 54,
      tsb: -6,
      form: 'Optimal',
      date: iso(0).slice(0, 10),
      threshold_state: 'established',
      threshold_training_state: options.withThresholdPendingTraining ? 'pending' : null,
      threshold_version: options.withThresholdPendingTraining
        ? `pending:251:promotion-threshold-1`
        : `sealed:245:${iso(14)}`,
    };
  }
  if (path === '/analytics/training-load') {
    return {
      daily_loads: [
        { date: iso(6).slice(0, 10), total_tss: 80 },
        { date: iso(1).slice(0, 10), total_tss: 112 },
      ],
      total_tss: 192,
      avg_daily_tss: 96,
      threshold_state: 'established',
      threshold_training_state: options.withThresholdPendingTraining ? 'pending' : null,
      threshold_version: options.withThresholdPendingTraining
        ? `pending:251:promotion-threshold-1`
        : `sealed:245:${iso(14)}`,
    };
  }

  if (path === '/users/me/leaderboard-positions' || /^\/users\/[^/]+\/leaderboard-positions$/.test(path)) {
    return {
      wallet: TEST_WALLET,
      stats: { total_positions: 1, kom_count: 0, podium_count: 1, top10_count: 1, total_vaults_completed: 3, best_percentile: 0.08 },
      positions: [
        {
          vault_id: 1,
          vault_name: 'Full Stack Smoke',
          vault_signature: 'vault-signature-1',
          rank: 2,
          best_time_seconds: 610,
          is_kom: false,
          total_riders: 24,
          percentile: 0.08,
          achieved_at: iso(2),
        },
      ],
    };
  }
  if (path.startsWith('/leaderboard/')) {
    return {
      leaderboard_type: 'climb',
      metric: 'wkg',
      period: 'week',
      arena_id: null,
      arena_name: 'Global',
      entries: [
        {
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          username: 'tim',
          avatar_url: null,
          activity_id: 'ride-tim',
          pattern_id: 'pattern-one',
          vault_name: 'Full Stack Smoke',
          value: 5.4,
          secondary_value: 382,
          created_at: iso(1),
        },
        {
          rank: 2,
          wallet: TEST_WALLET,
          username: user.username,
          avatar_url: null,
          activity_id: 'ride-1',
          pattern_id: 'pattern-two',
          vault_name: 'Ellis Street Wall',
          value: 4.8,
          secondary_value: 360,
          created_at: iso(2),
        },
      ],
      total_count: 2,
      updated_at: iso(0),
    };
  }

  if (path === '/vaults/create/canon/prepare' && method === 'POST') {
    return {
      preparation_id: '33333333-3333-4333-8333-333333333333',
      climb_id: CANON_CLIMB_ROW_ID,
      canon_commitment_hex: `01${'22'.repeat(63)}`,
      transaction: 'AQ==',
      blockhash: TEST_WALLET,
      last_valid_block_height: 123456,
      message: 'Review and approve the prepared Vault transaction.',
      vault_id: 42,
      pda: TEST_WALLET,
    };
  }

  if (method === 'POST' || method === 'PUT' || method === 'PATCH') return { status: 'ok' };
  return undefined;
}

// The map ground's tiles, glyphs and sprite are static files under /basemap/ on the API host.
const isGroundAsset = (url: URL) => url.hostname === 'api.boulderroller.xyz' && url.pathname.startsWith('/basemap/');

async function routePortalApi(page: Page, unexpectedApiCalls: string[], options: RouteFixtureOptions) {
  const portalOrigin = new URL(process.env.BR_PLAYWRIGHT_BASE_URL ?? 'http://localhost:4173').origin;
  const handler = async (route: Route) => {
    const request = route.request();
    if (!['fetch', 'xhr'].includes(request.resourceType())) {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    if (isGroundAsset(url)) {
      await route.continue();
      return;
    }
    if (url.hostname.endsWith('privy.io')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
      return;
    }

    if (options.trainingDelayMs && url.pathname.includes('/analytics/')) {
      await new Promise((resolve) => setTimeout(resolve, options.trainingDelayMs));
    }
    const body = responseFor(url, request.method(), options, readRouteJson(route));

    if (body && typeof body === 'object' && '__api_error' in body) {
      const errorBody = body as { status: number; detail: string };
      await route.fulfill({
        status: errorBody.status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: errorBody.detail }),
      });
      return;
    }

    if (body === undefined) {
      unexpectedApiCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Unmocked API route' }) });
      return;
    }

    if (
      options.canonVaultPrepareDelayMs
      && request.method() === 'POST'
      && url.pathname.endsWith('/vaults/create/canon/prepare')
    ) {
      await new Promise((resolve) => setTimeout(resolve, options.canonVaultPrepareDelayMs));
    }
    if (
      options.pendingRewardsDelayMs
      && request.method() === 'GET'
      && /\/vaults\/\d+\/pending-rewards$/.test(url.pathname)
    ) {
      await new Promise((resolve) => setTimeout(resolve, options.pendingRewardsDelayMs));
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  };

  await page.route('**/auth/bootstrap', handler);
  await page.route('**/auth/onboarding/state', handler);
  await page.route('**/auth/refresh', handler);
  await page.route('**/me', handler);
  await page.route('**/users/me', handler);
  await page.route('http://127.0.0.1:4174/**', handler);
  await page.route('http://localhost:4174/**', handler);
  for (const apiOrigin of new Set([
    portalOrigin,
    'http://127.0.0.1:4173',
    'http://localhost:4173',
  ])) {
    await page.route(`${apiOrigin}/api/**`, handler);
  }
  await page.route('http://203.0.113.10:8080/**', handler);
  await page.route('https://api.boulderroller.xyz/**', handler);
  await page.route('http://api.boulderroller.xyz/**', handler);
  await page.route('https://api.boulderroller.org/**', handler);
  await page.route('http://api.boulderroller.org/**', handler);
  await page.route('https://explorer-api.walletconnect.com/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ listings: [] }) });
  });
  await page.route('https://auth.privy.io/api/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

function readRouteJson(route: Route): Record<string, unknown> {
  const raw = route.request().postData();
  if (!raw) return {};

  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function cohortStrangerWalkResponseFor(url: URL, method: string, state: StrangerWalkRouteState): unknown {
  const requestPath = url.pathname.replace(/^\/api/, '') || '/';

  if (requestPath === '/auth/bootstrap') {
    return {
      authenticated: state.authenticated,
      invite_required: true,
      invite_validated: state.authenticated,
      needs_profile_setup: false,
      auth_method_hint: state.authenticated ? 'privy' : null,
      user: state.authenticated ? themedUser(false) : null,
    };
  }

  if (requestPath === '/auth/onboarding/state') {
    return {
      authenticated: state.authenticated,
      invite_required: true,
      invite_validated: state.authenticated,
      needs_profile_setup: false,
      auth_method_hint: state.authenticated ? 'privy' : null,
    };
  }

  return undefined;
}

async function routeCohortStrangerWalkApi(page: Page, unexpectedApiCalls: string[], state: StrangerWalkRouteState) {
  const allowedMutationPaths = new Set([
    '/auth/invite/validate',
    '/auth/privy/verify',
    '/auth/refresh',
    '/rides/upload/init',
    '/rides/upload/complete',
  ]);
  const handler = async (route: Route) => {
    const request = route.request();
    if (!['fetch', 'xhr'].includes(request.resourceType())) {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const method = request.method();
    const requestPath = url.pathname.replace(/^\/api/, '') || '/';

    // 24xry.28: public terrain reads share the ground; never send the CARTO key.
    if (method === 'GET' && url.origin === 'https://s3.amazonaws.com' && /^\/elevation-tiles-prod\/terrarium\/\d+\/\d+\/\d+\.png$/.test(url.pathname)) {
      expect(url.searchParams.has('key')).toBe(false);
      await route.continue();
      return;
    }

    // 24xry.22: the Ride page shares the Climb page's vector basemap reads.
    if (method === 'GET' && url.protocol === 'https:' && (url.hostname === 'basemaps.cartocdn.com' || /^tiles(?:-[a-d])?\.basemaps\.cartocdn\.com$/.test(url.hostname))) {
      await route.continue();
      return;
    }

    // 9kiz8: the base map style ships with the app and its tiles, glyphs and sprite are
    // static files on the API host; none of them is an API read.
    if (method === 'GET' && (/\/carto-voyager-style(?:-[\w-]+)?\.json$/.test(url.pathname) || isGroundAsset(url))) {
      await route.continue();
      return;
    }

    if (url.hostname.endsWith('privy.io')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
      return;
    }

    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !allowedMutationPaths.has(requestPath)) {
      unexpectedApiCalls.push(`${method} ${url.origin}${url.pathname}${url.search}`);
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Unmocked mutation blocked by stranger-walk rehearsal' }),
      });
      return;
    }

    let body = cohortStrangerWalkResponseFor(url, method, state);

    if (requestPath === '/auth/invite/validate' && method === 'POST') {
      const requestBody = readRouteJson(route);
      state.inviteValidatedCode = String(requestBody.code ?? '');
      body = {
        valid: state.inviteValidatedCode === cohortInviteCode,
        message: state.inviteValidatedCode === cohortInviteCode ? 'ok' : 'invite_invalid',
        code_id: 'invite-philly-alpha-01',
      };
    }

    if (requestPath === '/auth/privy/verify' && method === 'POST') {
      const requestBody = readRouteJson(route);
      state.authInviteCode = String(requestBody.invite_code ?? requestBody.inviteCode ?? '');
      state.authWallet = String(requestBody.wallet ?? '');
      state.authPrivyToken = String(requestBody.privy_token ?? requestBody.privyToken ?? '');
      state.authenticated = state.authInviteCode === cohortInviteCode;
      body = state.authenticated
        ? {
          user_id: user.id,
          wallet: state.authWallet,
          access_token: 'fixture-access-token',
          access_expires_at: iso(-1),
          refresh_token: 'fixture-refresh-token',
          refresh_expires_at: iso(-7),
        }
        : apiError(400, 'invite_invalid');
    }

    if (requestPath === '/rides/upload/init' && method === 'POST') {
      state.uploadInitSeen = true;
    }

    if (requestPath === '/rides/upload/complete' && method === 'POST') {
      state.uploadCompleteSeen = true;
    }

    if (requestPath === '/rides/ride-uploaded-1') {
      body = cohortUploadedRide;
    }

    if (requestPath === '/rides/ride-uploaded-1/status') {
      body = {
        contract_version: 'client.v1',
        truth_source: 'backend',
        ride_id: 'ride-uploaded-1',
        status: 'finalized',
        attestation_status: 'finalized',
        ride_hash_hex: 'hash-ride-uploaded-1',
        finalized_at: iso(0),
        has_gps: true,
        has_patterns: true,
        has_leaderboards: true,
        has_achievements: false,
        cal_earned: 104,
        dung_minted: 104,
        metrics: {
          tss: 104,
          kcals: 1180,
          distance_m: 31_800,
          elevation_gain_m: 524,
          duration_sec: 4_860,
          avg_power_w: 224,
          normalized_power_w: 251,
        },
      };
    }

    if (requestPath === '/rides/ride-uploaded-1/patterns') {
      body = {
        ride_id: 'ride-uploaded-1',
        patterns: {
          climb_patterns: [
            {
              climb_id: 'climb-manayunk',
              name: 'Manayunk Wall',
              road_name: 'Leverington Avenue',
              start_offset_s: 540,
              end_offset_s: 1_140,
              vert_m: 188,
              distance_m: 2_100,
              avg_gradient_pct: 8.9,
              duration_s: 600,
              avg_speed_mps: 3.5,
              vam: 1128,
              signature_hex: 'pattern-manayunk-wall',
              vault_match: {
                id: 'match-manayunk',
                vault_id: 1,
                name: 'Manayunk Wall',
                similarity: 0.98,
                is_strong_match: true,
                your_time: 600,
                your_rank: 3,
                your_best_time: 600,
                is_pr: true,
                is_new_entry: true,
                kom_time: 552,
                kom_holder: LONG_RIDER_WALLET,
                total_completions: 27,
              },
            },
          ],
          steady_pattern: {
            duration_s: 1_640,
            avg_power_w: 224,
            avg_hr_bpm: 154,
            start_time_offset_s: 1_200,
            end_time_offset_s: 2_840,
          },
          exploration_pattern: {
            new_tiles_wallet: 1,
            total_tiles: 8,
            discovery_pct: 0.12,
          },
        },
        summary: '1 climb, 1 steady block, 1 new tile',
        total_count: 3,
      };
    }

    if (body === undefined) {
      body = responseFor(url, method, { darkMode: false, uploadCompleteStatus: 'completed' });
    }

    if (body && typeof body === 'object' && '__api_error' in body) {
      const errorBody = body as { status: number; detail: string };
      await route.fulfill({
        status: errorBody.status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: errorBody.detail }),
      });
      return;
    }

    if (body === undefined) {
      unexpectedApiCalls.push(`${method} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Unmocked API route' }) });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  };

  // Keep the mutation-shaped rehearsal fail-closed even when an external bundle
  // was compiled with an API origin that is not one of the known launch hosts.
  await page.route('**/*', handler);
  await page.route('**/auth/bootstrap', handler);
  await page.route('**/auth/onboarding/state', handler);
  await page.route('**/auth/refresh', handler);
  await page.route('**/auth/invite/validate', handler);
  await page.route('**/auth/privy/verify', handler);
  await page.route('**/me', handler);
  await page.route('**/users/me', handler);
  await page.route('http://127.0.0.1:4174/**', handler);
  await page.route('http://localhost:4174/**', handler);
  await page.route('http://127.0.0.1:4173/api/**', handler);
  await page.route('http://localhost:4173/api/**', handler);
  await page.route('http://203.0.113.10:8080/**', handler);
  await page.route('https://api.boulderroller.xyz/**', handler);
  await page.route('http://api.boulderroller.xyz/**', handler);
  await page.route('https://api.boulderroller.org/**', handler);
  await page.route('http://api.boulderroller.org/**', handler);
  await page.route('https://explorer-api.walletconnect.com/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ listings: [] }) });
  });
  await page.route('https://auth.privy.io/api/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

function isHarnessRuntimeNoise(message: string): boolean {
  return message.includes('auth.privy.io')
    || message.includes('explorer-api.walletconnect.com')
    || message.includes("reading 'ethereum'")
    || message.includes('Auth runtime failed to load')
    || (message.includes('The above error occurred') && message.includes('PrivyProvider'));
}

function eyebrowCurrentEvidencePath(fileName: string): string | null {
  const captureDir = process.env.BR_CAPTURE_EYEBROW_CURRENT_STATE_DIR;
  if (!captureDir) return null;
  fs.mkdirSync(captureDir, { recursive: true });
  return path.join(captureDir, fileName);
}

async function captureEyebrowCurrentEvidence(page: Page, fileName: string) {
  const capturePath = eyebrowCurrentEvidencePath(fileName);
  if (!capturePath) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: capturePath,
    fullPage: true,
    animations: 'disabled',
  });
}

async function installEvidenceWalletStandardWallets(page: Page) {
  const phantomIcon = new PhantomWalletAdapter().icon;
  const fixtureIcon = `data:image/png;base64,${fs.readFileSync(
    path.resolve('public/icons/icon-192.png'),
  ).toString('base64')}`;

  await page.addInitScript(({ phantomIconDataUri, fixtureIconDataUri }) => {
    try {
      localStorage.removeItem('walletName');
      localStorage.removeItem('br_authenticated');
    } catch {
      // Cross-origin auth iframes can deny storage access before our app boots.
    }

    const makeWallet = (name: string, icon: string) => {
      const eventListeners = new Set<(properties: unknown) => void>();

      return {
        version: '1.0.0',
        name,
        icon,
        chains: ['solana:mainnet'],
        accounts: [],
        features: {
          'standard:connect': {
            version: '1.0.0',
            connect: () => new Promise<never>(() => {}),
          },
          'standard:events': {
            version: '1.0.0',
            on: (_event: string, listener: (properties: unknown) => void) => {
              eventListeners.add(listener);
              return () => eventListeners.delete(listener);
            },
          },
          'solana:signTransaction': {
            version: '1.0.0',
            supportedTransactionVersions: ['legacy'],
            signTransaction: async (...inputs: unknown[]) => inputs,
          },
        },
      };
    };

    const wallets = [
      makeWallet('Phantom', phantomIconDataUri),
      makeWallet('Boulder Roller fixture wallet', fixtureIconDataUri),
    ];
    const register = (api: { register: (...walletsToRegister: unknown[]) => unknown }) => {
      api.register(...wallets);
    };

    window.addEventListener('wallet-standard:app-ready', ((event: Event) => {
      const api = (event as CustomEvent<{ register: (...walletsToRegister: unknown[]) => unknown }>).detail;
      register(api);
    }) as EventListener);

    window.dispatchEvent(new CustomEvent('wallet-standard:register-wallet', {
      detail: register,
    }));
  }, {
    phantomIconDataUri: phantomIcon,
    fixtureIconDataUri: fixtureIcon,
  });
}

async function routeEyebrowCurrentEvidenceEntry(page: Page, unexpectedApiCalls: string[]) {
  await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
  const unauthenticated = {
    authenticated: false,
    invite_required: true,
    invite_validated: false,
    needs_profile_setup: false,
    auth_method_hint: null,
    user: null,
  };

  for (const routePattern of ['**/auth/bootstrap', '**/auth/onboarding/state']) {
    await page.route(routePattern, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(unauthenticated),
      });
    });
  }
}

async function routeEyebrowPublicPreviewSpecimens(page: Page, unexpectedApiCalls: string[]) {
  await routeEyebrowCurrentEvidenceEntry(page, unexpectedApiCalls);

  const previewPolicy = (objectType: 'climb' | 'rider') => ({
    mode: 'public_preview',
    object_type: objectType,
    raw_gps_available: false,
    streams_available: false,
    tiles_available: false,
    private_ride_history_available: false,
    unreviewed_projections_available: false,
    wallet_required: false,
    login_required_for: ['full detail'],
    blocked_surfaces: ['raw GPS', 'wallet'],
  });
  const routePreview = {
    contract_version: 'route_preview.v1',
    source: 'fixture',
    points: [
      { x: 0.06, y: 0.84 },
      { x: 0.24, y: 0.7 },
      { x: 0.43, y: 0.52 },
      { x: 0.64, y: 0.31 },
      { x: 0.84, y: 0.15 },
    ],
    point_count: 5,
    bounds: null,
    place_label: 'Shawmont, Philadelphia',
    privacy: { redact_gps: false },
  };
  const recordBoard = {
    contract_version: 'record_board_preview.v1',
    climb_id: 'preview-climb',
    climb_name: 'Shawmont Rise',
    vault_id: 19,
    entries: [
      {
        rank: 1,
        best_time_seconds: 251,
        avg_power_w: 569,
        completion_id: 'preview-completion-1',
        achieved_at: iso(365),
        rider: {
          contract_version: 'public_rider_ref.v1',
          id: 'tim-user',
          username: 'tim',
          display_name: 'Tim Trail',
          is_public: true,
          identity_hidden: false,
        },
      },
    ],
    row_limit: 10,
    visible_rows: 1,
    hidden_rows: 0,
    identity_policy: {
      wallets: 'redacted',
      profile_fields: 'public_profile_only',
    },
    truth_source: 'fixture',
  };

  await page.route('**/public/previews/climbs/preview-climb*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'public_preview.v1',
        object_type: 'climb',
        id: 'preview-climb',
        canonical_path: '/climbs/preview-climb',
        title: 'Shawmont Rise',
        preview_policy: previewPolicy('climb'),
        seo: {
          title: 'Shawmont Rise · Climb · Boulder Roller',
          description: 'Public climb preview',
          canonical_path: '/climbs/preview-climb',
          robots: 'index,follow',
        },
        assets: {
          contract_version: 'public_preview.v1',
          object_type: 'climb',
          route_preview: {
            kind: 'route_preview',
            preview: routePreview,
          },
          record_board: {
            kind: 'record_board_preview',
            preview: recordBoard,
          },
        },
        freshness: {
          source: 'fixture',
          loaded_at: iso(0),
          cache_ttl_seconds: 60,
        },
        climb: {
          contract_version: 'client.v1',
          truth_source: 'fixture',
          id: 'preview-climb',
          name: 'Shawmont Rise',
          length_m: 620,
          elev_gain_m: 58,
          avg_gradient_pct: 9.4,
          category: 'Category 4',
          region: 'Philadelphia, PA',
          vault_id: 19,
          has_vault: true,
          route_preview: routePreview,
          record_board: recordBoard,
          vault_economy: {
            has_vault: true,
            vault_id: 19,
          },
        },
      }),
    });
  });

  await page.route('**/public/previews/riders/tim*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'public_preview.v1',
        object_type: 'rider',
        id: 'tim-user',
        canonical_path: '/riders/tim',
        title: 'Tim Trail',
        preview_policy: previewPolicy('rider'),
        seo: {
          title: 'Tim Trail · Rider · Boulder Roller',
          description: 'Public rider preview',
          canonical_path: '/riders/tim',
          robots: 'index,follow',
        },
        assets: {
          contract_version: 'public_preview.v1',
          object_type: 'rider',
        },
        freshness: {
          source: 'fixture',
          loaded_at: iso(0),
          cache_ttl_seconds: 60,
        },
        rider: {
          contract_version: 'public_rider_ref.v1',
          id: 'tim-user',
          username: 'tim',
          display_name: 'Tim Trail',
          is_public: true,
          identity_hidden: false,
        },
        profile: {
          id: 'tim-user',
          username: 'tim',
          display_name: 'Tim Trail',
          is_public: true,
          total_rides: 12,
          total_distance_km: 482,
          total_elevation_m: 8420,
          follower_count: 3,
          following_count: 7,
          current_streak: 4,
          longest_streak: 11,
          last_activity_date: iso(1),
        },
        recent_rides: {
          is_public: true,
          rides: [
            {
              id: 'preview-ride',
              title: 'Shawmont Morning',
              status: 'finalized',
              started_at: iso(1),
              distance_m: 31_800,
              elevation_gain_m: 524,
              duration_sec: 4860,
              visibility: 'public',
              route_preview: routePreview,
            },
          ],
          count: 1,
          privacy: { visibility: 'public' },
        },
        beetle_cards: {
          is_public: true,
          cards: [],
          count: 0,
          privacy: { visibility: 'public' },
        },
      }),
    });
  });
}

test.describe('Eyebrow current-state evidence', () => {
  test('captures other detected wallets and the pending connection card', async ({ page }) => {
    const captureDir = process.env.BR_CAPTURE_EYEBROW_CURRENT_STATE_DIR;
    test.skip(!captureDir, 'Set BR_CAPTURE_EYEBROW_CURRENT_STATE_DIR to write current-state evidence.');
    test.setTimeout(90_000);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const unexpectedApiCalls: string[] = [];
    page.on('console', (message) => {
      const text = message.text();
      if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
        consoleErrors.push(text);
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });

    await installEvidenceWalletStandardWallets(page);
    await routeEyebrowCurrentEvidenceEntry(page, unexpectedApiCalls);

    for (const viewport of [
      { label: 'desktop-1440x1000', width: 1440, height: 1000 },
      { label: 'mobile-390x844', width: 390, height: 844 },
    ]) {
      consoleErrors.length = 0;
      pageErrors.length = 0;
      unexpectedApiCalls.length = 0;
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'Use wallet instead' }).click();

      const walletSurface = page.getByRole('region', { name: 'Use your wallet' });
      await expect(walletSurface).toHaveAttribute('data-auth-step', 'select');
      await expect(walletSurface.getByRole('button', { name: /Phantom/ })).toBeVisible();
      await walletSurface.getByRole('button', { name: 'Show other detected extensions' }).click();
      const otherWallet = walletSurface.getByRole('button', { name: /Boulder Roller fixture wallet/ });
      await expect(otherWallet).toBeVisible();
      await expect(walletSurface.locator('.wallet-connect-select__group-eyebrow')).toHaveCount(0);
      await expect(walletSurface.locator('.wallet-connect-other__eyebrow')).toHaveCount(0);
      await expect(walletSurface.locator('.wallet-connect-progress-card__eyebrow')).toHaveCount(0);
      await expect(walletSurface.getByText('Detected Solana wallets', { exact: true })).toHaveCount(0);
      await expect(walletSurface.getByText('Other detected extensions', { exact: true })).toHaveCount(0);
      await expect(walletSurface.getByText('Connection', { exact: true })).toHaveCount(0);
      await page.waitForTimeout(500);
      await captureEyebrowCurrentEvidence(page, `wallet-other-detected-${viewport.label}.png`);

      await otherWallet.click();
      await expect(walletSurface).toHaveAttribute('data-auth-step', 'connecting');
      await expect(walletSurface.locator('.auth-entry-status')).toBeVisible();
      await expect(walletSurface.locator('.auth-entry-status').getByText('Approve wallet connection', { exact: true })).toBeVisible();
      await expect(walletSurface.locator('.wallet-connect-select__group-eyebrow')).toHaveCount(0);
      await expect(walletSurface.locator('.wallet-connect-other__eyebrow')).toHaveCount(0);
      await expect(walletSurface.locator('.wallet-connect-progress-card__eyebrow')).toHaveCount(0);
      await expect(walletSurface.getByText('Detected Solana wallets', { exact: true })).toHaveCount(0);
      await expect(walletSurface.getByText('Other detected extensions', { exact: true })).toHaveCount(0);
      await expect(walletSurface.getByText('Connection', { exact: true })).toHaveCount(0);
      await page.waitForTimeout(500);
      await captureEyebrowCurrentEvidence(page, `wallet-connecting-${viewport.label}.png`);
      await walletSurface.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(walletSurface).toHaveAttribute('data-auth-step', 'select');

      expect(unexpectedApiCalls, `${viewport.label} wallet evidence unexpected API calls`).toEqual([]);
      expect(pageErrors, `${viewport.label} wallet evidence page errors`).toEqual([]);
      expect(consoleErrors, `${viewport.label} wallet evidence console errors`).toEqual([]);
    }
  });

  test('captures settled public climb and rider previews without object eyebrows', async ({ page }) => {
    const captureDir = process.env.BR_CAPTURE_EYEBROW_CURRENT_STATE_DIR;
    test.skip(!captureDir, 'Set BR_CAPTURE_EYEBROW_CURRENT_STATE_DIR to write current-state evidence.');
    test.setTimeout(90_000);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const unexpectedApiCalls: string[] = [];
    page.on('console', (message) => {
      const text = message.text();
      if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
        consoleErrors.push(text);
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });
    await routeEyebrowPublicPreviewSpecimens(page, unexpectedApiCalls);

    const specimens = [
      {
        slug: 'climb',
        path: '/climbs/preview-climb',
        heading: 'Shawmont Rise',
        byline: 'Philadelphia, PA',
        supportingHeading: 'Leaderboard',
        supportingText: 'Tim Trail',
      },
      {
        slug: 'rider',
        path: '/riders/tim',
        heading: 'Tim Trail',
        byline: '@tim',
        supportingHeading: 'Recent rides',
        supportingText: 'Shawmont Morning',
      },
    ];

    for (const viewport of [
      { label: 'desktop-1440x1000', width: 1440, height: 1000 },
      { label: 'mobile-390x844', width: 390, height: 844 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const specimen of specimens) {
        consoleErrors.length = 0;
        pageErrors.length = 0;
        unexpectedApiCalls.length = 0;
        await page.goto(specimen.path, { waitUntil: 'domcontentloaded' });
        await expect(page.getByRole('heading', { level: 1, name: specimen.heading })).toBeVisible();
        await expect(page.locator('.public-preview-hero__object')).toHaveCount(0);
        const byline = page.locator(specimen.slug === 'climb' ? '.climb-place' : '.profile-ledger__meta');
        await expect(byline).toBeVisible();
        await expect(byline).toContainText(specimen.byline);
        await expect(page.getByText(specimen.supportingHeading, { exact: true })).toBeVisible();
        await expect(page.getByText(specimen.supportingText, { exact: true }).first()).toBeVisible();
        if (specimen.slug === 'rider') {
          await expect(page.locator('main').getByText('CAL', { exact: true })).toHaveCount(0);
          await expect(page.locator('main').getByText('DUNG', { exact: true })).toHaveCount(0);
        }
        await expect.poll(() => page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )).toBeLessThanOrEqual(1);
        await page.waitForTimeout(500);
        await captureEyebrowCurrentEvidence(page, `public-preview-${specimen.slug}-${viewport.label}.png`);

        expect(unexpectedApiCalls, `${viewport.label} ${specimen.path} unexpected API calls`).toEqual([]);
        expect(pageErrors, `${viewport.label} ${specimen.path} page errors`).toEqual([]);
        expect(consoleErrors, `${viewport.label} ${specimen.path} console errors`).toEqual([]);
      }
    }
  });
});

test.describe('Cohort stranger walk rehearsal', () => {
  test('rehearses invite to first counted ride without operator intervention', async ({ page }) => {
    test.setTimeout(75_000);

    const unexpectedApiCalls: string[] = [];
    const state: StrangerWalkRouteState = {
      authenticated: false,
      inviteValidatedCode: null,
      authInviteCode: null,
      authWallet: null,
      authPrivyToken: null,
      uploadInitSeen: false,
      uploadCompleteSeen: false,
    };
    const captureDir = process.env.BR_CAPTURE_STRANGER_WALK_DIR;

    await page.addInitScript(() => {
      try {
        localStorage.removeItem('br_authenticated');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        sessionStorage.clear();
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routeCohortStrangerWalkApi(page, unexpectedApiCalls, state);
    await page.route('https://storage.test/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'rides/user-test-1/upload-direct-1.gpx' }),
      });
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`/invite/${cohortInviteCode.toUpperCase()}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Start your account' })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Code' })).toHaveCount(0);
    expect(state.inviteValidatedCode).toBe(cohortInviteCode);

    await page.getByLabel('Email').fill('philly-rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();
    await expect(page.getByRole('heading', { name: 'Account sign in' })).toBeVisible();
    await expect(page.getByText('philly-rider@example.com', { exact: true })).toBeVisible();
    await page.locator('#social-login-code').fill('123456');
    await page.getByRole('button', { name: 'Verify code' }).click();

    await expect(page.locator('.portal-shell__header')).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    expect(state.authInviteCode).toBe(cohortInviteCode);
    expect(state.authWallet).toBeTruthy();
    expect(state.authPrivyToken).toBe('e2e-email-code:123456');

    await page.getByRole('button', { name: 'Upload ride' }).click();
    await expect(page.getByRole('heading', { name: 'Upload ride' })).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles({
      name: 'first-counted-ride.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>First counted ride</name></trk></gpx>'),
    });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();
    await expect(page.getByRole('dialog', { name: 'Upload ride' }).getByText('Ride saved', { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/$/);
    await page.getByRole('dialog', { name: 'Upload ride' }).getByRole('button', { name: 'Open ride', exact: true }).and(page.locator('.upload-sheet__action--commit')).click();
    await expect(page).toHaveURL(/\/activities\/ride-uploaded-1$/);
    expect(state.uploadInitSeen).toBe(true);
    expect(state.uploadCompleteSeen).toBe(true);

    await expect(page.getByRole('heading', { name: 'First Counted Ride' })).toBeVisible();
    await expect(page.locator('.ride-detail-jewelry')).toHaveCount(0);
    await expect(page.locator('.ride-page-climbs .ride-page-row')).toHaveCount(1);
    const matchedClimbCard = page.locator('.ride-page-climbs a[href="/climbs/climb-manayunk"]');
    await expect(matchedClimbCard).toContainText('Manayunk Wall');
    await expect(matchedClimbCard).toHaveAttribute('href', '/climbs/climb-manayunk');

    const openAndAssertCountedRideLog = async () => {
      await page.getByRole('link', { name: 'Verification', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Ride log', level: 1 })).toBeVisible();
      const statusProof = page.locator('.ride-detail-proof-datum').filter({ hasText: 'Status' }).first();
      await expect(statusProof).toContainText('Finalized');
      const countedCalProof = page.locator('.ride-detail-proof-datum').filter({ hasText: 'Counted CAL' }).first();
      await expect(countedCalProof).toContainText('104');
    };

    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await expect(page.locator('.ride-page-card')).toHaveCSS('opacity', '1');
      await page.screenshot({ path: path.join(captureDir, 'stranger-walk-counted-ride-desktop.png'), fullPage: true });
      await openAndAssertCountedRideLog();
      await page.screenshot({ path: path.join(captureDir, 'stranger-walk-counted-proof-desktop.png'), fullPage: true });
      await page.locator('.ride-analysis-back').click();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('heading', { name: 'First Counted Ride' })).toBeVisible();
      await expect(page.getByText('Manayunk Wall').first()).toBeVisible();
      const mobileMatchedClimbCard = page.locator('.ride-page-climbs a[href="/climbs/climb-manayunk"]');
      await expect(mobileMatchedClimbCard).toHaveAttribute('href', '/climbs/climb-manayunk');
      await expect(page.locator('.ride-page-card')).toHaveCSS('opacity', '1');
      await page.screenshot({ path: path.join(captureDir, 'stranger-walk-counted-ride-mobile.png'), fullPage: true });
      await openAndAssertCountedRideLog();
      await page.screenshot({ path: path.join(captureDir, 'stranger-walk-counted-proof-mobile.png'), fullPage: true });
    } else {
      await openAndAssertCountedRideLog();
    }

    expect(unexpectedApiCalls, 'cohort stranger walk unexpected API calls').toEqual([]);
  });

  test('rehearses parked launch pages at desktop and mobile', async ({ page }) => {
    test.setTimeout(90_000);

    const unexpectedApiCalls: string[] = [];
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const failedResponses: string[] = [];
    const captureDir = process.env.BR_CAPTURE_STRANGER_WALK_PARKED_DIR;

    page.on('console', (message) => {
      if (message.type() === 'error' && !isHarnessRuntimeNoise(message.text())) {
        consoleErrors.push(message.text());
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });
    page.on('response', (response) => {
      if (response.status() >= 400) {
        failedResponses.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
    }

    for (const viewport of [
      { label: 'desktop-1440x1000', width: 1440, height: 1000 },
      { label: 'mobile-390x844', width: 390, height: 844 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const specimen of cohortParkedPageExpectations) {
        consoleErrors.length = 0;
        pageErrors.length = 0;
        unexpectedApiCalls.length = 0;
        failedResponses.length = 0;

        await page.goto(specimen.path, { waitUntil: 'domcontentloaded' });
        if (specimen.canonicalPath) {
          await expect(page).toHaveURL(new RegExp(`${specimen.canonicalPath}$`));
        }
        await expect(page.locator('.portal-shell__header')).toBeVisible();
        const heading = page.getByRole('heading', { level: 1, name: specimen.heading });
        await expect(heading).toBeVisible();
        await expect(heading).not.toHaveCSS('color', 'rgba(0, 0, 0, 0)');
        await expect(page.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toHaveCount(0);
        await expect(page.getByText(/NaN|coming soon|not wired into this portal route/i)).toHaveCount(0);
        await expect(page.locator('.background-fetch-indicator')).toHaveCount(0);
        await expect.poll(() => page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )).toBeLessThanOrEqual(1);

        if (specimen.slug === 'climbs') {
          await expect(page.locator('.climb-discovery__map-canvas.maplibregl-map')).toHaveAttribute('data-ground-ready', 'true', { timeout: 15_000 });
        }

        if (captureDir) {
          await page.waitForTimeout(150);
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.screenshot({
            path: path.join(captureDir, `${specimen.slug}-${viewport.label}.png`),
            fullPage: true,
            animations: 'disabled',
          });
        }

        expect(unexpectedApiCalls, `${viewport.label} ${specimen.path} unexpected API calls`).toEqual([]);
        expect(pageErrors, `${viewport.label} ${specimen.path} page errors`).toEqual([]);
        expect(failedResponses, `${viewport.label} ${specimen.path} failed responses`).toEqual([]);
        expect(consoleErrors, `${viewport.label} ${specimen.path} console errors`).toEqual([]);
      }
    }
  });
});

test.describe('Exact token amount boundaries', () => {
  test('keeps atomic values exact through Portfolio actions and Vault DUNG display', async ({ page }) => {
    test.setTimeout(60_000);
    const unexpectedApiCalls: string[] = [];
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error' && !isHarnessRuntimeNoise(message.text())) {
        consoleErrors.push(message.text());
      }
    });
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before the app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      withExactTokenSpecimen: true,
      pendingRewardsDelayMs: 3_000,
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/portfolio', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Portfolio' })).toBeVisible();
    // The money room (ratified 2026-09-02): the wallet's CAL is the hero, the
    // wallet's DUNG and the CAL deposited on climbs sit beneath it, and the
    // Balance sheet lists Balance assets — never summed with the wallet.
    const summary = page.getByLabel('Portfolio summary');
    await expect(summary).toContainText('22,154');
    await expect(summary).toContainText('18.75');
    await expect(summary.getByLabel('Wallet CAL')).toBeVisible();
    await expect(summary).toContainText('Wallet DUNG');
    await expect(summary.getByLabel('Wallet snapshot')).toBeVisible();
    const balanceAssets = page.getByLabel('Balance assets');
    await expect(balanceAssets).toContainText('12.35');
    await expect(balanceAssets).toContainText('25');
    await expect(balanceAssets).toContainText('7.13');
    await expect(balanceAssets).not.toContainText('22,154');
    await expect(balanceAssets).not.toContainText('18.75');
    await expect(page.getByText('Balance snapshot', { exact: true })).toHaveCount(0);
    await expect(page.getByText(/5,050,000,000/)).toHaveCount(0);
    // Without a CollectionSnapshot, quotes still authorize Collect but cannot
    // supply a displayed total, readiness, or net receipt.
    const uncollected = page.getByLabel('Uncollected');
    await expect(uncollected.locator('.portfolio-uncollected')).toHaveCount(0);
    await expect(uncollected).not.toContainText('5.05');
    await expect(uncollected).not.toContainText('DUNG ready');
    await expect(uncollected.getByText('Collecting takes a 5% fee.')).toHaveCount(0);
    await expect(uncollected.getByText('You receive 4.8 DUNG', { exact: true })).toHaveCount(0);
    const portfolioPositions = page.locator('[data-object-layer="portfolio-positions"]');
    await expect(portfolioPositions.getByText('Exit fee')).toHaveCount(0);

    const feeCaptureDir = process.env.PORTAL_FEE_DISCLOSURE_CAPTURE_DIR;
    if (feeCaptureDir) {
      fs.mkdirSync(feeCaptureDir, { recursive: true });
      await page.screenshot({ path: path.join(feeCaptureDir, 'portfolio-fees-desktop-1440x1000.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(feeCaptureDir, 'portfolio-fees-mobile-390x844.png'), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }

    // Positions are rows that open the climb page, where Deposit and
    // Withdraw live; Collect gathers every vault with DUNG ready.
    const firstPosition = portfolioPositions.locator('[data-object-row="climb-position"]').first();
    await expect(firstPosition).toHaveAttribute('href', '/climbs/climb-1');
    await expect(firstPosition).toContainText('Manayunk Wall');
    await expect(firstPosition).toContainText('1,200 CAL');
    await expect(firstPosition).not.toContainText('4.25 DUNG ready');
    const harvestedVaults: string[] = [];
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname;
      if (request.method() === 'POST' && /\/vaults\/\d+\/harvest$/.test(pathname)) {
        harvestedVaults.push(pathname.replace(/^\/api(?=\/)/, ''));
      }
    });
    const portfolioCollectRequest = page.waitForRequest((request) => (
      request.method() === 'POST'
      && new URL(request.url()).pathname.endsWith('/vaults/2/harvest')
    ));
    await uncollected.getByRole('button', { name: 'Collect DUNG' }).click();
    await portfolioCollectRequest;
    expect(harvestedVaults).toEqual(['/vaults/1/harvest', '/vaults/2/harvest']);
    await expect(uncollected.getByRole('button', { name: 'Collect DUNG' })).toBeEnabled();

    const sourceCaptureDir = process.env.PORTAL_BALANCE_SOURCE_CAPTURE_DIR;
    if (sourceCaptureDir) {
      fs.mkdirSync(sourceCaptureDir, { recursive: true });
      await page.screenshot({ path: path.join(sourceCaptureDir, 'portfolio-desktop-1440x1000.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(sourceCaptureDir, 'portfolio-mobile-390x844.png'), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }

    // The Add funds sheet: a giant numeral and one hold capsule. The exact
    // amount survives the sheet as a base-unit string, never a float.
    await page.getByRole('button', { name: 'Add funds' }).click();
    const addFundsSheet = page.getByRole('dialog', { name: 'Add funds' });
    await addFundsSheet.getByLabel('Add funds amount').fill('9007199.254740993');
    const capsule = addFundsSheet.getByRole('button', { name: 'Hold to Add 9,007,199.25 CAL' });
    await expect(capsule).toBeEnabled();
    const prepareRequest = page.waitForRequest((request) => (
      new URL(request.url()).pathname.endsWith('/portfolio/balance/add-funds/prepare')
    ));
    const capsuleBox = await capsule.boundingBox();
    if (!capsuleBox) throw new Error('hold capsule has no box');
    await page.mouse.move(capsuleBox.x + capsuleBox.width / 2, capsuleBox.y + capsuleBox.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(900);
    await page.mouse.up();
    const request = await prepareRequest;
    const actionBody = request.postDataJSON() as Record<string, unknown>;
    expect(actionBody.amount_base_units).toBe('9007199254740993');
    expect(typeof actionBody.amount_base_units).toBe('string');

    const captureDir = process.env.PORTAL_EXACT_TOKEN_CAPTURE_DIR;
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({ path: path.join(captureDir, 'portfolio-desktop-1440x1000.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(captureDir, 'portfolio-mobile-390x844.png'), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }

    let quoteMatchesPosition = false;
    await page.route('**/vaults/1/pending-rewards', async route => {
      const quote = responseFor(new URL(route.request().url()), 'GET', { withExactTokenSpecimen: true }, {}) as Record<string, unknown>;
      await route.fulfill({ json: { ...quote, lp_tokens_base_units: quoteMatchesPosition ? '9007199254740993' : '1000000000000' } });
    });
    await page.goto('/vaults/1');
    await expect(page).toHaveURL(/\/climbs\/climb-1$/);
    await expect(page.getByLabel('Vault metrics')).toContainText('9,007,199.25 CAL');
    await expect(page.getByText(/9,007,199,254,740,993/)).toHaveCount(0);
    await page.getByRole('link', { name: 'Deposit CAL', exact: true }).click();
    const depositAmount = page.getByRole('textbox', { name: 'CAL', exact: true });
    await depositAmount.fill('100.9');
    await expect(page.getByRole('button', { name: /Hold to Deposit/ })).toBeDisabled();
    await expect(page.getByText('Use a whole CAL amount', { exact: true })).toBeVisible();
    await depositAmount.fill('99');
    await expect(page.getByRole('button', { name: /Hold to Deposit/ })).toBeDisabled();
    await depositAmount.fill('100');
    await expect(page.getByRole('button', { name: 'Hold to Deposit 100 CAL' })).toBeEnabled();
    await page.getByRole('link', { name: 'Back', exact: true }).click();
    await page.getByRole('link', { name: 'DUNG ready' }).click();
    await expect(page.getByText('4.25 DUNG', { exact: true })).toBeVisible();
    await expect(page.getByText('−0.21 DUNG', { exact: true })).toBeVisible();
    await expect(page.getByText('4.04 DUNG', { exact: true })).toBeVisible();
    await expect(page.getByText('Collecting takes a 5% fee.', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Back', exact: true }).click();
    await page.getByRole('link', { name: 'Withdraw CAL', exact: true }).click();
    await expect(page.getByRole('button', { name: /Hold to Withdraw/ })).toBeDisabled();
    quoteMatchesPosition = true;
    await page.reload();
    const withdraw = page.getByRole('button', { name: 'Hold to Withdraw 1,250 CAL' });
    await expect(withdraw).toBeEnabled();
    await expect(page.getByText('−6.25 CAL', { exact: true })).toBeVisible();
    await expect(page.getByText('1,243.75 CAL', { exact: true })).toBeVisible();
    if (feeCaptureDir) await page.screenshot({ path: path.join(feeCaptureDir, 'climb-withdraw-review.png'), fullPage: true });
    const preparation = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/vaults/1/unstake/prepare'));
    await withdraw.dispatchEvent('click', { detail: 0 });
    const body = (await preparation).postDataJSON();
    expect(body.withdraw_all).toBe(true);
    expect(body).not.toHaveProperty('lp_amount');
    expect(body).not.toHaveProperty('lp_amount_base_units');
    await page.getByRole('link', { name: 'Back', exact: true }).click();
    await page.getByRole('link', { name: 'DUNG history', exact: true }).click();
    await expect(page.getByText('340 DUNG', { exact: true })).toBeVisible();
    await expect(page.getByText(/340,000,000,000/)).toHaveCount(0);
    if (captureDir) await page.screenshot({ path: path.join(captureDir, 'climb-dung-history.png'), fullPage: true });

    expect(unexpectedApiCalls).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});

test.describe('Feed scope truth', () => {
  test('never presents retained Everyone rows as Following while that scope loads or fails', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    let markFollowingRequested: (() => void) | undefined;
    const followingRequested = new Promise<void>((resolve) => {
      markFollowingRequested = resolve;
    });
    let releaseFollowing: (() => void) | undefined;
    const followingRelease = new Promise<void>((resolve) => {
      releaseFollowing = resolve;
    });
    await page.route('**/feed/home?*', async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('scope') !== 'following') {
        await route.fallback();
        return;
      }
      markFollowingRequested?.();
      await followingRelease;
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Following feed unavailable' }),
      });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(1);
    const scope = page.getByRole('group', { name: 'Feed scope' });
    await expect(scope.getByRole('button', { name: 'Everyone', exact: true })).toHaveAttribute('aria-pressed', 'true');

    await scope.getByRole('button', { name: 'Following', exact: true }).click();
    await followingRequested;

    await expect(scope.getByRole('button', { name: 'Following', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(0);

    releaseFollowing?.();
    await expect(page.getByRole('heading', { name: 'Could not load feed' })).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('Night Ledger profile truth and keyboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
    await routePortalApi(page, [], { darkMode: true });
  });

  test('profile tabs have one tab stop and preserve focus through arrow Home End navigation', async ({ page }, testInfo) => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('/profile');
      const tabs = page.getByRole('tablist', { name: 'Profile sections' });
      await expect(tabs.getByRole('tab')).toHaveCount(4);
      await expect(tabs.locator('[tabindex="0"]')).toHaveCount(1);
      await tabs.getByRole('tab', { name: 'Overview', exact: true }).focus();
      for (const [key, selected] of [['ArrowRight', 'Rides'], ['ArrowRight', 'Training'], ['End', 'Portfolio'], ['ArrowRight', 'Overview'], ['ArrowLeft', 'Portfolio'], ['Home', 'Overview']]) {
        await page.keyboard.press(key);
        const tab = tabs.getByRole('tab', { name: selected, exact: true });
        await expect(tab).toBeFocused();
        await expect(tab).toHaveAttribute('aria-selected', 'true');
        await expect(tabs.locator('[tabindex="0"]')).toHaveCount(1);
        await expect(page.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', await tab.getAttribute('id'));
      }
      await page.screenshot({ path: testInfo.outputPath(`profile-tabs-${width}.png`), animations: 'disabled' });
    }
  });

  for (const state of ['missing', 'partial', 'unmatched', 'failed']) {
    test(`profile ${state} positions never claim a complete ridden count and can retry`, async ({ page }, testInfo) => {
      test.setTimeout(50_000);
      let recovered = false;
      let requests = 0;
      await page.route('**/users/me/leaderboard-positions', async route => {
        requests += 1;
        if (state === 'failed' && !recovered) return route.fulfill({ status: 500, json: { detail: 'Position details unavailable' } });
        const body = responseFor(new URL(route.request().url()), 'GET', { darkMode: true }) as {
          stats: { total_positions: number; top10_count: number; kom_count: number };
          positions: Array<{ vault_id: number }>;
        };
        if (!recovered) {
          body.stats = { ...body.stats, total_positions: state === 'unmatched' ? 1 : 4, top10_count: 4, kom_count: 4 };
          if (state === 'missing') body.positions = [];
          if (state === 'unmatched') body.positions[0].vault_id = 999999;
        }
        await route.fulfill({ json: body });
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto('/profile');
      await expect(page.getByText('Positions unavailable.', { exact: true })).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('.profile-ledger__ridden-count')).toHaveCount(0);
      await expect(page.locator('.profile-ground__mark')).toHaveCount(0);
      if (state !== 'failed') await expect(page.locator('.profile-ledger__trio')).toContainText('4');
      if (state === 'missing') {
        for (const width of [1440, 390]) {
          await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
          if (width === 390) await page.getByText('Positions unavailable.', { exact: true }).evaluate(el => el.scrollIntoView({ block: 'center' }));
          await page.screenshot({ path: testInfo.outputPath(`profile-unavailable-${width}.png`), animations: 'disabled' });
        }
      }
      const before = requests;
      recovered = true;
      await page.getByRole('button', { name: 'Retry positions', exact: true }).click();
      await expect.poll(() => requests).toBeGreaterThan(before);
      await expect(page.getByText('Positions unavailable.', { exact: true })).toHaveCount(0);
      await expect(page.locator('.profile-ledger__ridden-count')).toContainText('1');
      await expect(page.locator('.profile-ledger__row')).toHaveCount(1);
    });
  }

  test('a successfully empty profile can say zero climbed', async ({ page }) => {
    await page.route('**/users/me/leaderboard-positions', route => route.fulfill({ json: {
      wallet: TEST_WALLET,
      stats: { total_positions: 0, kom_count: 0, top10_count: 0, podium_count: 0, total_vaults_completed: 0 },
      positions: [],
    } }));
    await page.goto('/profile');
    await expect(page.locator('.profile-ledger__ridden-count strong')).toHaveText('0');
    await expect(page.getByText('Positions unavailable.', { exact: true })).toHaveCount(0);
  });
});

test.describe('Portal navigation topology', () => {
  test('keeps only Feed and Climbs in nav and redirects personal pages into self Profile tabs', async ({ page }) => {
    test.setTimeout(60_000);
    const unexpectedApiCalls: string[] = [];

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.setViewportSize({ width: 1440, height: 1000 });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const primaryNavigation = page.getByRole('navigation', { name: 'Primary navigation' });
    await expect(primaryNavigation.getByRole('link')).toHaveCount(2);
    await expect(primaryNavigation.getByRole('link', { name: 'Feed', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(primaryNavigation.getByRole('link', { name: 'Map', exact: true })).not.toHaveAttribute('aria-current', 'page');
    await expect(primaryNavigation.getByRole('link', { name: 'Rides', exact: true })).toHaveCount(0);
    await expect(primaryNavigation.getByRole('link', { name: 'Portfolio', exact: true })).toHaveCount(0);

    await page.getByRole('button', { name: /Open account menu for/ }).click();
    await expect(page.getByRole('menuitem', { name: 'Portfolio', exact: true })).toHaveAttribute('href', '/profile?tab=portfolio');

    const redirects = [
      { from: '/training', to: '/profile?tab=rides', tab: 'Rides', heading: 'Rides' },
      { from: '/my-activities', to: '/profile?tab=rides', tab: 'Rides', heading: 'Rides' },
      { from: '/data', to: '/profile?tab=training', tab: 'Training', heading: 'Load' },
      { from: '/portfolio', to: '/profile?tab=portfolio', tab: 'Portfolio', heading: 'Portfolio' },
    ];

    for (const redirect of redirects) {
      await page.goto(redirect.from, { waitUntil: 'domcontentloaded' });
      await expect(page).toHaveURL(redirect.to);
      await expect(page.getByRole('tab', { name: redirect.tab, exact: true })).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByRole('heading', { name: redirect.heading, exact: true }).last()).toBeVisible();
    }

    await page.goto('/profile', { waitUntil: 'domcontentloaded' });
    for (const tab of ['Overview', 'Rides', 'Training', 'Portfolio']) {
      await expect(page.getByRole('tab', { name: tab, exact: true })).toBeVisible();
    }
    await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight }));
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await page.getByRole('tab', { name: 'Training', exact: true }).click();
    await expect(page).toHaveURL('/profile?tab=training');
    await expect(page).toHaveTitle('Dung Beetle Phoenix · Training · Boulder Roller');
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

    await page.goto('/rider/tim?tab=portfolio', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('tab')).toHaveCount(1);
    await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('[data-object-page="portfolio"]')).toHaveCount(0);

    await page.goto('/find-friends', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL('/?search=riders');
    const searchDialog = page.getByRole('dialog');
    await expect(searchDialog).toBeVisible();
    await expect(searchDialog.getByRole('button', { name: 'Riders', exact: true })).toHaveClass(/search-modal-category--active/);

    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('Portal V2 route shell', () => {
  for (const themeMode of themeModes) {
    test(`renders authenticated portal routes without shell regressions in ${themeMode.label} mode`, async ({ page }) => {
      test.setTimeout(90_000);

      const consoleErrors: string[] = [];
      const pageErrors: string[] = [];
      const unexpectedApiCalls: string[] = [];

      page.on('console', (message) => {
        const text = message.text();
        if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
          consoleErrors.push(text);
        }
      });
      page.on('pageerror', (error) => {
        if (!isHarnessRuntimeNoise(error.message)) {
          pageErrors.push(error.message);
        }
      });

      await page.addInitScript(({ darkMode }: { darkMode: boolean }) => {
        try {
          localStorage.setItem('br_authenticated', 'true');
          localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
          localStorage.setItem('boulder-roller-dark-mode', darkMode ? 'true' : 'false');
          localStorage.removeItem('br_auth_handoff_pending');
        } catch {
          // Cross-origin auth iframes can deny storage access before our app boots.
        }
        (window as Window & { ethereum?: unknown }).ethereum = {
          request: async () => [],
          on: () => {},
          removeListener: () => {},
        };
      }, { darkMode: themeMode.darkMode });
      await routePortalApi(page, unexpectedApiCalls, { darkMode: themeMode.darkMode });

      for (const viewport of [
        { label: 'desktop', width: 1440, height: 1000 },
        { label: 'mobile', width: 390, height: 844 },
      ]) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });

        for (const route of routeExpectations) {
          await test.step(`${themeMode.label} ${viewport.label} ${route.path}`, async () => {
            consoleErrors.length = 0;
            pageErrors.length = 0;
            unexpectedApiCalls.length = 0;

            await page.goto(route.path, { waitUntil: 'domcontentloaded' });
            await expect(page.locator('.portal-shell__header')).toBeVisible();
            await expect(page.locator('.portal-shell__brand')).toBeVisible();
            await expect(page.locator('.portal-shell__sidebar')).toHaveCount(0);
            await expect(page.locator('.portal-shell-nav')).toHaveCount(0);
            if (await page.locator('.portal-shell__title').count()) {
              await expect(page.locator('.portal-shell__title')).toHaveText(route.shellTitle);
            }
            await expect(page).toHaveTitle(route.browserTitle);
            await expect(page.locator('[class*="tsqd-open-btn-container"]')).toHaveCount(0);
            await expect(page.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toHaveCount(0);
            await expect(page.locator(':root')).toHaveAttribute('data-portal-theme', 'ios-ledger');
            await expect(page.locator(':root')).toHaveAttribute('data-portal-color-scheme', 'dark');
            // Ledger tokens are owned by the stylesheet; nothing may re-inject
            // cobalt money or the category rainbow inline on <html>.
            await expect.poll(async () => page.evaluate(() => {
              const cs = getComputedStyle(document.documentElement);
              const read = (name: string) => cs.getPropertyValue(name).trim().toUpperCase();
              return [read('--portal-cal'), read('--portal-climb-category-hc'), read('--portal-climb-category-3')].join(' ');
            })).toBe('#F1EEE8 #F1EEE8 #4E4B46');
            expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--portal-cal'))).toBe('');

            await page.waitForTimeout(route.path === '/map' ? 500 : 150);

            await expect(page.getByText(/NaN/)).toHaveCount(0);
            await expect(page.getByText(/@@/)).toHaveCount(0);
            await expect(page.getByText(/coming soon|not wired into this portal route/i)).toHaveCount(0);
            await expect(page.locator('.background-fetch-indicator')).toHaveCount(0);
            if (route.path === '/') {
              await expect(page.getByRole('group', { name: 'Feed scope' })).toBeVisible();
              const profileName = page.getByText('Dung Beetle Phoenix');
              if (viewport.label === 'desktop') {
                await expect(profileName.first()).toBeVisible();
                await expect(page.getByRole('link', { name: /CAL .*DUNG/i })).toHaveCount(0);
                await expect(page.locator('.portal-shell-balance')).toHaveCount(0);
                const topbarBox = await page.locator('.portal-shell__topbar').boundingBox();
                const feedFrameBox = await page.locator('.feed-page .portal-frame').first().boundingBox();
                expect(topbarBox, `${themeMode.label} feed topbar rail`).not.toBeNull();
                expect(feedFrameBox, `${themeMode.label} feed frame rail`).not.toBeNull();
                if (topbarBox && feedFrameBox) {
                  expect(Math.abs(topbarBox.x - feedFrameBox.x), `${themeMode.label} feed left rail`).toBeLessThanOrEqual(8);
                  expect(
                    Math.abs((topbarBox.x + topbarBox.width) - (feedFrameBox.x + feedFrameBox.width)),
                    `${themeMode.label} feed right rail`,
                  ).toBeLessThanOrEqual(8);
                }
                await page.getByRole('button', { name: 'Open account menu' }).click();
                const accountMenu = page.getByRole('menu', { name: 'Account menu' });
                await expect(accountMenu).toBeVisible();
                await expect(accountMenu).toContainText('Dung Beetle Phoenix');
                await expect(accountMenu).toContainText('CAL');
                await expect(accountMenu).toContainText('22.2K');
                await expect(accountMenu).toContainText('DUNG');
                await expect(accountMenu).toContainText('Portfolio');
                await expect(accountMenu).not.toContainText('Wallet / Economy');
                await page.keyboard.press('Escape');
                await page.getByRole('button', { name: 'Open notifications' }).click();
                const notificationsDialog = page.getByRole('dialog', { name: 'Notifications' });
                await expect(notificationsDialog).toBeVisible();
                await expect(page.getByText('Legacy kudos row')).toBeVisible();
                await expect(notificationsDialog.locator('.portal-shell-notification').first()).toHaveAttribute('data-state', 'unread');
                await expect(notificationsDialog.locator('.portal-shell-notification__title').first()).toHaveText('Tim');
                await expect(notificationsDialog.getByRole('button', { name: 'Clear unread' })).toBeVisible();
                await page.keyboard.press('Escape');
              }
              await expect(page.getByText('Total points')).toHaveCount(0);
              const feedActor = page.locator('.feed-activity-card__user-button').first();
              // Portal pass 10: the ratified header carries the handle.
              await expect(feedActor).toHaveText('@dungbeetlephoenix');
              await expect(feedActor).toHaveAttribute('data-rider-path', '/rider/dungbeetlephoenix');
              // Ratified Feed board (2026-09-01): the viewer's own card carries one CAL
              // pair; no other card shows money; no climb names on cards.
              const ownFeedCard = page.locator('.feed-activity-card[data-own="true"]').first();
              await expect(ownFeedCard).toBeVisible();
              await expect(ownFeedCard.locator('.feed-card__cal')).toContainText('96');
              await expect(ownFeedCard.locator('.feed-card__cal')).toContainText('CAL');
              await expect(page.locator('.feed-activity-card[data-own="false"] .feed-card__cal')).toHaveCount(0);
              await expect(page.locator('.feed-activity-card__compact-token')).toHaveCount(0);
              await expect(page.locator('.feed-activity-card__view-link')).toHaveCount(0);
              if (viewport.label === 'desktop') {
                // The crown card lives in the left rail, which the shell folds away below 64rem.
                await expect(page.locator('.feed-crown')).toBeVisible();
                await expect(page.locator('.feed-crown__trio')).toContainText('Seats');
                await expect(page.locator('.feed-crown__trio')).toContainText('Crowns');
              } else {
                await expect(page.locator('.feed-crown')).toBeHidden();
              }
              await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(1);
            }
            if (route.path === '/profile?tab=rides') {
              await expect(page.getByRole('heading', { name: /^Rides/ })).toBeVisible();
              await expect(page.locator('.rides-log__row')).toHaveCount(3);
              await expect(page.getByText(/Beetle (UNAVAILABLE|Pending)/i)).toHaveCount(0);
            }
            if (route.path === '/settings') {
              await expect(page.getByRole('button', { name: /Upload photo/i })).toHaveCount(0);
              await page.locator('.settings-v2-profile-photo-section input[type="file"]').setInputFiles({
                name: 'avatar.png',
                mimeType: 'image/png',
                buffer: Buffer.from(
                  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=',
                  'base64',
                ),
              });
              const avatarCropDialog = page.getByRole('dialog', { name: 'Crop profile photo' });
              await expect(avatarCropDialog).toBeVisible();
              await expect(avatarCropDialog.locator('.settings-v2-avatar-crop-frame')).toBeVisible();
              await expect(avatarCropDialog.getByRole('slider', { name: 'Zoom' })).toBeVisible();
              await avatarCropDialog.getByRole('button', { name: 'Cancel' }).click();
              await expect(avatarCropDialog).toHaveCount(0);
            }
            if (route.path === '/?search=riders') {
              const searchDialog = page.getByRole('dialog');
              await expect(searchDialog).toBeVisible();
              await expect(searchDialog.getByRole('button', { name: 'Riders', exact: true })).toHaveClass(/search-modal-category--active/);
            }
            if (route.path === '/rider/tim') {
              await expect(page.getByRole('heading', { name: 'Tim Trail' })).toBeVisible();
              await expect(page.getByText('@tim')).toBeVisible();
              await expect(page.getByText('Public rider')).toHaveCount(0);
              await expect(page.getByText('Turns climb repeats into signal.')).toBeVisible();
              await expect(page.getByRole('button', { name: /Following|Follow/ })).toBeVisible();
              await expect(page.getByRole('button', { name: /Edit profile/i })).toHaveCount(0);
              const publicProfile = page.locator('[data-object-page="rider"]');
              await expect(publicProfile.getByText('CAL', { exact: true })).toHaveCount(0);
              await expect(publicProfile.getByText('DUNG', { exact: true })).toHaveCount(0);
            }
            if (route.path === '/profile' || route.path === '/rider/tim') {
              await expect(page.locator('[data-object-page="rider"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="rider-identity"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="rider-activity-history"]').first()).toBeVisible();
              // Profile — Ground (ratified 2026-09-02): the map is the page, the
              // ledger column floats on it, the held climb wears its rank mark.
              await expect(page.locator('.profile-ground .maplibregl-canvas')).toBeVisible();
              await expect(page.locator('.profile-ground__map')).toHaveAttribute('data-rendered-held-climbs', '1');
              await expect(page.locator('.profile-ground__label b')).toHaveCount(0);
              await expect(page.locator('.profile-ground__mark img')).toHaveCount(1);
              await expect(page.locator('.profile-ledger__trio .profile-pair')).toHaveCount(3);
              await expect(page.locator('.profile-ledger__row')).toHaveCount(1);
              await expect(page.locator('.profile-ledger__ridden-count')).toContainText('of 4 climbs ridden');
              await expect(page.locator('.profile-photos')).toHaveCount(0);
              await expect(page.locator('.profile-year')).toBeVisible();
              await expect(page.locator('.profile-recent__row')).toHaveCount(3);
              await expect(page.locator('.profile-v2-cover-strip')).toHaveCount(0);
              await expect(page.locator('.profile-v2-activity-proof')).toHaveCount(0);
              await expect(page.locator('[data-object-page="rider"]').getByText(/\bDUNG\b|\bCAL\b/)).toHaveCount(0);
              if (
                process.env.BR_CAPTURE_PROFILE_VISUALS === '1'
                && themeMode.label === 'light'
              ) {
                const routeSlug = route.path.replace(/\W+/g, '-').replace(/^-|-$/g, '');
                const viewportSlug = viewport.label === 'desktop' ? '' : `-${viewport.label}`;
                await page.screenshot({
                  path: `test-results/profile-visuals/${routeSlug}${viewportSlug}.png`,
                  fullPage: true,
                });
              }
            }
            if (route.path === '/profile' || route.path === '/rider/tim') {
              await expect(page.getByRole('tab', { name: 'Cards', exact: true })).toHaveCount(0);
              await expect(page.locator('.portal-beetle-card-display')).toHaveCount(0);
              await expect(page.getByText('climber', { exact: true })).toHaveCount(0);
              await expect(page.getByText(/Recent milestones|Recent achievements/i)).toHaveCount(0);
              if (route.path === '/rider/tim') {
                await expect(page.getByRole('tab')).toHaveCount(1);
                await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toBeVisible();
                await expect(page.getByText(WALLET_SHAPED_TEXT)).toHaveCount(0);
              } else {
                for (const tab of ['Overview', 'Rides', 'Training', 'Portfolio']) {
                  await expect(page.getByRole('tab', { name: tab, exact: true })).toBeVisible();
                }
              }
            }
            if (route.path === '/docs') {
              // The docs' contents page (2026-09-03): page-title rows that open the docs site, no copy.
              await expect(page.locator('.guide__title')).toHaveText('Guide');
              await expect(page.getByRole('link', { name: 'Glossary' })).toHaveAttribute('href', 'https://docs.boulderroller.xyz/reference/glossary');
              await expect(page.getByRole('link', { name: 'Public docs' })).toHaveAttribute('href', 'https://docs.boulderroller.xyz/');
              await expect(page.getByText('Need the longform docs?')).toHaveCount(0);
              await expect(page.getByText('Beetle ranks')).toHaveCount(0);
            }
            if (route.path === '/notifications') {
              // The consequence ledger (2026-09-03): one log, days in the rail, the rider's
              // name as the noun of a social push, the backend's title beneath it, no
              // inbox panel, no filter words, no per-row buttons; Alerts live on Settings.
              const notificationActor = page.locator('.notification-row__actor').first();
              await expect(notificationActor).toHaveText('Tim');
              await expect(notificationActor).toHaveAttribute('data-rider-path', '/rider/tim');
              await expect(page.locator('.notifications-log__title')).toHaveText('Notifications');
              const firstRow = page.locator('.notifications-log__row').first();
              await expect(firstRow).toHaveAttribute('data-state', 'unread');
              await expect(firstRow.locator('.notifications-log__sub')).toContainText('Legacy kudos row');
              // The fixture clock is frozen, so the day word is a weekday here, not Today.
              await expect(page.locator('.notifications-log__day').first()).toHaveText(/\S+/);
              await expect(page.getByRole('link', { name: 'Alerts' })).toHaveAttribute('href', '/settings?tab=alerts');
              await expect(page.getByRole('button', { name: 'Clear unread' })).toBeVisible();
              await expect(page.getByText('Inbox', { exact: true })).toHaveCount(0);
              await expect(page.getByRole('button', { name: 'Leaderboards' })).toHaveCount(0);
              await expect(page.getByRole('switch')).toHaveCount(0);
            }
            if (route.path === '/profile?tab=training') {
              // Figures on paper: Load, Consistency, Threshold, Power curve; no hero band, no dashboard.
              for (const sheet of ['Load', 'Consistency', 'Threshold', 'Power curve']) {
                await expect(page.getByRole('heading', { name: sheet, exact: true })).toBeVisible();
              }
              await expect(page.getByRole('heading', { name: 'Fitness & freshness' })).toHaveCount(0);
              await expect(page.getByText('Load trend')).toHaveCount(0);
              await expect(page.getByText('Data confidence')).toHaveCount(0);
              await expect(page.getByRole('button', { name: '26 weeks', exact: true })).toHaveAttribute('aria-pressed', 'true');
              await expect(page.getByRole('button', { name: 'Stress', exact: true })).toHaveAttribute('aria-pressed', 'true');
              await expect(page.locator('.training-load__figure svg')).toBeVisible();
              await expect(page.getByText('Form · Optimal', { exact: true })).toHaveCount(0);
              await expect(page.locator('.training-trio strong')).toHaveText(['', '', '']);
              await expect(page.getByText('derived from your rides', { exact: true })).toBeVisible();
              await expect(page.getByText('245 W', { exact: true })).toBeVisible();
              await page.getByRole('button', { name: '4 weeks', exact: true }).click();
              await expect(page).toHaveURL(/tab=training&window=4-weeks$/);
              await expect(page.locator('.training-load__figure svg')).toBeVisible();
              await page.getByRole('button', { name: '26 weeks', exact: true }).click();
              await expect(page).toHaveURL(/tab=training$/);
            }
            if (route.path === '/profile?tab=portfolio') {
              await expect(page.getByText('Positions', { exact: true })).toBeVisible();
              // Under any tab but Overview the ground drops to the 200px masthead.
              await expect(page.locator('.profile-ground--masthead')).toBeVisible();
              await expect(page.locator('.profile-masthead')).toBeVisible();
              await expect(page.locator('.profile-ledger')).toHaveCount(0);
              const portfolioPage = page.locator('[data-object-page="portfolio"]');
              await expect(portfolioPage).toBeVisible();
              await expect(portfolioPage.locator('.portal-page-hero__kicker')).toHaveCount(0);
              // 24xry.25: preserve Current truth while following the ratified eyebrow placement.
              const walletTruth = portfolioPage.getByLabel('Portfolio summary').locator('.profile-eyebrow .portfolio-sheet__meta');
              await expect(walletTruth).toHaveCount(1);
              await expect(walletTruth).toContainText('Current');
              await expect(portfolioPage.locator('.portal-page-hero__status-footer, .portal-truth-pill')).toHaveCount(0);
              await expect(portfolioPage.getByRole('button', { name: 'Add funds' })).toBeVisible();
              await expect(portfolioPage.getByRole('button', { name: 'Withdraw to wallet' })).toBeVisible();
              await expect(portfolioPage.getByText('How positions count')).toHaveCount(0);
              const positionLayer = page.locator('[data-object-layer="portfolio-positions"]');
              await expect(positionLayer).toBeVisible();
              await expect(positionLayer.locator('[data-object-row="climb-position"]')).toHaveCount(2);
              await expect(positionLayer).toContainText('Manayunk Wall');
              await expect(positionLayer).toContainText('1,200');
              await expect(portfolioPage.getByLabel('Wallet CAL', { exact: true })).toBeVisible();
              await expect(portfolioPage.getByText('Wallet DUNG', { exact: true })).toBeVisible();
              await expect(portfolioPage.getByLabel('Boulder Roller Balance', { exact: true })).toBeVisible();
              await expect(positionLayer).not.toContainText('4.25');
              await expect(positionLayer).not.toContainText('DUNG ready');
              await expect(positionLayer.getByRole('link', { name: /Manayunk Wall/ }).first()).toHaveAttribute('href', '/climbs/climb-1');
              const receiptLayer = page.locator('[data-object-layer="portfolio-receipts"]');
              await expect(receiptLayer).toBeVisible();
              await expect(receiptLayer.locator('[data-object-row="dung-receipt"]')).toHaveCount(3);
              await expect(receiptLayer).toContainText('Manayunk Wall');
              await expect(receiptLayer).toContainText('Leaderboard #2');
              await expect(receiptLayer).toContainText('+3.4 DUNG');
              await expect(receiptLayer).not.toContainText(/vault-manayunk|111111/i);
              if (
                process.env.BR_CAPTURE_PORTFOLIO_REVIEW === '1'
                && themeMode.label === 'light'
              ) {
                const captureDir = process.env.BR_CAPTURE_PORTFOLIO_REVIEW_DIR
                  ?? path.join('test-results', 'portfolio-receipts-review');
                fs.mkdirSync(captureDir, { recursive: true });
                await page.screenshot({
                  path: path.join(captureDir, `portfolio-receipts-${viewport.label}.png`),
                  fullPage: true,
                });
              }
              await expect(page.getByText('Collection fee')).toHaveCount(0);
              await expect(page.getByText('100 DUNG')).toHaveCount(0);
            }
            if (route.path === '/vaults/1') {
              await expect(page).toHaveURL(/\/climbs\/climb-1$/);
              await expect(page.locator('#climb-vault')).toBeVisible();
              await expect(page.getByRole('heading', { name: 'Your position', exact: true })).toBeVisible();
            }
            if (route.path === '/climbs/climb-1') {
              await expect(page.locator('[data-object-page="climb"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-identity"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-route-elevation"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-economy"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-record-board"]')).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-proof"]')).toHaveCount(0);
              await expect(page.getByText('Back to records')).toHaveCount(0);
              await expect(page.getByRole('link', { name: 'All climbs' }).first()).toBeVisible();
              await expect(page.locator('[data-object-layer="climb-record-board"]').getByRole('heading', { name: 'Leaderboard', exact: true })).toBeVisible();
              await expect(page.locator('.climb-detail-window-nav')).toHaveCount(0);
              await expect(page.locator('.climb-detail-window-panel')).toHaveCount(0);
              await expect(page.getByText(/Create vault/i)).toHaveCount(0);
              await expect(page.locator('[data-object-layer="climb-record-board"] [data-object-row="record-board"]')).toHaveCount(2);
            }
            if (route.path === '/climbs/climb-1' && viewport.label === 'desktop') {
              await expect(page.locator('.climb-detail-window-nav')).toHaveCount(0);
              const routeFigure = page.locator('.climb-detail-route-card__figure');
              await expect(routeFigure).toBeVisible();
              const climbHeroBox = await page.locator('[data-object-layer="climb-identity"]').boundingBox();
              const recordBoardBox = await page.locator('[data-object-layer="climb-record-board"]').boundingBox();
              expect(climbHeroBox, 'climb hero box').not.toBeNull();
              expect(recordBoardBox, 'climb record board box').not.toBeNull();
              if (climbHeroBox && recordBoardBox) {
                expect(climbHeroBox.y, 'climb identity first viewport').toBeLessThan(260);
                const emptyBand = await page.locator('.climb-empty-band').boundingBox();
                if (emptyBand) {
                  expect(emptyBand.height).toBe(185);
                  expect(recordBoardBox.y).toBeGreaterThanOrEqual(emptyBand.y + emptyBand.height);
                  expect(recordBoardBox.y - emptyBand.y - emptyBand.height).toBeLessThan(100);
                } else expect(recordBoardBox.y, 'climb record board appears in the desktop first viewport').toBeLessThan(1000);
              }
            }
            if (route.path === '/activities/ride-1') {
              await expect(page.locator('[data-object-page="ride"]')).toBeVisible();
              for (const layer of ['ride-identity','ride-route-map','ride-stats','ride-elevation-climbs']) await expect(page.locator(`[data-object-layer="${layer}"]`).first()).toBeVisible();
              await expect(page.getByRole('heading', {name:'Morning Ride'})).toBeVisible();
              await expect(page.locator('.ride-page-card .ride-page-stats dt')).toHaveText(['Distance','Elevation','Time']);
              await expect(page.locator('.ride-instruments,.ride-detail-window-nav,.ride-detail-jewelry,#ride-detail-sidebar')).toHaveCount(0);
              await expect(page.getByText('Solo ride',{exact:true})).toHaveCount(0);
              await expect(page.getByText('Ride file',{exact:true})).toHaveCount(0);
              await expect(page.locator('.ride-page-climbs a')).toContainText('Full Stack Smoke');
              await expect(page.locator('.ride-page-climbs a')).toHaveAttribute('href','/climbs/climb-1');
              await expect(page.getByRole('link',{name:'Ride analysis',exact:true})).toHaveCount(1);
              await page.getByRole('button',{name:'More ride actions'}).click();
              await expect(page.getByRole('menuitem',{name:'Copy ride link'})).toBeVisible();
              await expect(page.getByRole('menuitem',{name:'Export GPX'})).toBeVisible();
              await expect(page.getByRole('menuitem',{name:'Show ride panel'})).toHaveCount(0);
              await page.keyboard.press('Escape');
              await page.getByRole('button',{name:'Comments',exact:true}).click();
              await expect(page.locator('#ride-social').getByText('Nice climb signal.')).toBeVisible();
              await expect(page.locator('#ride-social').getByPlaceholder('Add a comment...')).toBeVisible();
              await expect(page.getByRole('dialog',{name:'Ride comments'})).toHaveCount(0);
              await expect(page.getByRole('link',{name:'Verification',exact:true})).toHaveAttribute('href','/activities/ride-1/log');
            }
            if (route.hidesWalletText) {
              await expect(page.getByText(WALLET_SHAPED_TEXT)).toHaveCount(0);
            }

            const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
            expect(overflow, `${themeMode.label} ${viewport.label} ${route.path} horizontal overflow`).toBeLessThanOrEqual(1);
            expect(unexpectedApiCalls, `${themeMode.label} ${viewport.label} ${route.path} unexpected API calls`).toEqual([]);
            expect(pageErrors, `${themeMode.label} ${viewport.label} ${route.path} page errors`).toEqual([]);
            expect(consoleErrors, `${themeMode.label} ${viewport.label} ${route.path} console errors`).toEqual([]);
          });
        }
      }
    });
  }

  test('omits frozen profile surfaces at desktop and mobile', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];

    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
      localStorage.setItem('boulder-roller-dark-mode', 'false');
      localStorage.removeItem('br_auth_handoff_pending');
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    for (const viewport of [
      { label: 'desktop', width: 1440, height: 1000 },
      { label: 'mobile', width: 390, height: 844 },
    ]) {
      unexpectedApiCalls.length = 0;
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/profile', { waitUntil: 'domcontentloaded' });

      await expect(page.getByRole('heading', { name: 'Dung Beetle Phoenix' })).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Cards', exact: true })).toHaveCount(0);
      await expect(page.locator('.portal-beetle-card-display')).toHaveCount(0);
      await expect(page.getByText('climber', { exact: true })).toHaveCount(0);
      await expect(page.getByText(/Recent milestones|Recent achievements/i)).toHaveCount(0);
      expect(unexpectedApiCalls, `${viewport.label} profile unexpected API calls`).toEqual([]);
    }
  });

  test('retires frozen pages and the provider callback at desktop and mobile', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];

    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
      localStorage.setItem('boulder-roller-dark-mode', 'false');
      localStorage.removeItem('br_auth_handoff_pending');
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    for (const viewport of [
      { label: 'desktop', width: 1440, height: 1000 },
      { label: 'mobile', width: 390, height: 844 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const retiredPath of [
        '/achievements',
        '/records',
        '/leaderboard',
        '/activities/ride-1/analyze',
        '/strava/callback?code=retired&state=retired',
      ]) {
        unexpectedApiCalls.length = 0;
        await page.goto(retiredPath, { waitUntil: 'domcontentloaded' });

        await expect(page.getByRole('heading', { name: 'Route not found' })).toBeVisible();
        await expect(page.getByRole('heading', { name: /Milestones|Rankings|Strava connected/i })).toHaveCount(0);
        await expect(page.getByText(/Connection saved|Import from Strava/i)).toHaveCount(0);
        expect(unexpectedApiCalls, `${viewport.label} ${retiredPath} unexpected API calls`).toEqual([]);
      }
    }
  });

  test('captures every former hero-eyebrow route for Tim review', async ({ page }) => {
    const afterCaptureDir = process.env.BR_CAPTURE_EYEBROW_REVIEW_DIR;
    const baselineCaptureDir = process.env.BR_CAPTURE_EYEBROW_BASELINE_DIR;
    const captureDir = baselineCaptureDir ?? afterCaptureDir;
    const isBaselineCapture = Boolean(baselineCaptureDir);
    test.skip(
      !captureDir,
      'Set BR_CAPTURE_EYEBROW_REVIEW_DIR or BR_CAPTURE_EYEBROW_BASELINE_DIR to write the review packet.',
    );
    test.setTimeout(240_000);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const unexpectedApiCalls: string[] = [];

    page.on('console', (message) => {
      const text = message.text();
      if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
        consoleErrors.push(text);
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, isAdmin: true });
    fs.mkdirSync(captureDir!, { recursive: true });

    for (const viewport of [
      { label: 'desktop-1440x1000', width: 1440, height: 1000 },
      { label: 'mobile-390x844', width: 390, height: 844 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const route of eyebrowReviewRoutes) {
        consoleErrors.length = 0;
        pageErrors.length = 0;
        unexpectedApiCalls.length = 0;

        await page.goto(route.path, { waitUntil: 'domcontentloaded' });
        await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
        if (isBaselineCapture) {
          const baselineKicker = page.locator('.portal-page-hero__kicker');
          await expect(baselineKicker).toHaveCount(1);
          await expect(baselineKicker).toBeVisible();
          await expect(baselineKicker.locator('.portal-truth-pill')).toHaveCount(1);
          await expect(baselineKicker.locator('.portal-truth-pill')).toBeVisible();
        } else {
          await expect(page.locator('.portal-page-hero__kicker')).toHaveCount(0);
          await expect(page.locator('.portal-truth-pill').first()).toBeVisible();
        }
        await page.waitForTimeout(800);
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: path.join(captureDir!, `${route.slug}-${viewport.label}.png`),
          fullPage: true,
          animations: 'disabled',
        });

        expect(unexpectedApiCalls, `${route.path} unexpected API calls`).toEqual([]);
        expect(pageErrors, `${route.path} page errors`).toEqual([]);
        expect(consoleErrors, `${route.path} console errors`).toEqual([]);
      }

      if (isBaselineCapture) continue;

      for (const route of eyebrowObjectReviewRoutes) {
        consoleErrors.length = 0;
        pageErrors.length = 0;
        unexpectedApiCalls.length = 0;

        await page.goto(route.path, { waitUntil: 'domcontentloaded' });
        await expect(page.locator(`[data-object-page="${route.objectPage}"]`)).toBeVisible();
        await expect(page.locator('.climb-detail-hero__meta')).toHaveCount(0);
        await expect(page.locator('.ride-detail-climbs-profile__eyebrow')).toHaveCount(0);
        if (route.objectPage === 'climb') {
          const climbPage = page.locator('[data-object-page="climb"]');
          const recordBoard = page.locator('[data-object-layer="climb-record-board"]');
          await expect(climbPage).toHaveAttribute('aria-busy', 'false');
          await expect(page.locator('[data-object-layer="climb-route-elevation"]')).toBeVisible();
          await expect(recordBoard.locator('.climb-detail-section-heading__truth')).toBeVisible();
          await expect(recordBoard.locator('.climb-detail-leaderboard__row--header')).toBeVisible();
          await expect(recordBoard.locator('.climb-detail-leaderboard__row:not(.climb-detail-leaderboard__row--header)').first()).toBeVisible();
        }
        await page.waitForTimeout(800);
        if (route.objectPage === 'climb') {
          await expect(page.locator('[data-object-layer="climb-record-board"]')).toHaveCSS('opacity', '1');
        }
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: path.join(captureDir!, `${route.slug}-${viewport.label}.png`),
          fullPage: true,
          animations: 'disabled',
        });

        expect(unexpectedApiCalls, `${route.path} unexpected API calls`).toEqual([]);
        expect(pageErrors, `${route.path} page errors`).toEqual([]);
        expect(consoleErrors, `${route.path} console errors`).toEqual([]);
      }
    }
  });

  test('keeps climb browsing language separate from vault compatibility', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const browseListRequests: string[] = [];
    const geocodingRequests: Array<{ path: string; body: unknown }> = [];
    const directNominatimRequests: string[] = [];
    const delayedGeocodingReleases = new Map<string, () => void>();
    const delayedGeocodingFinished = new Set<string>();
    let expectingGeocodingUnavailable = false;

    page.on('console', (message) => {
      const text = message.text();
      if (
        expectingGeocodingUnavailable
        && message.type() === 'error'
        && /Failed to load resource:.*503 \(Service Unavailable\)/.test(text)
      ) {
        return;
      }
      if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
        consoleErrors.push(text);
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });
    page.on('request', (request) => {
      const url = new URL(request.url());
      const requestPath = url.pathname.replace(/^\/api/, '') || '/';
      if (
        request.method() === 'GET'
        && ['fetch', 'xhr'].includes(request.resourceType())
        && (requestPath === '/climbs/list' || requestPath === '/vaults')
      ) {
        browseListRequests.push(`${requestPath}${url.search}`);
      }
      if (request.method() === 'POST' && requestPath === '/geocoding/search') {
        geocodingRequests.push({
          path: requestPath,
          body: request.postDataJSON(),
        });
      }
      if (url.hostname === 'nominatim.openstreetmap.org') {
        directNominatimRequests.push(`${request.method()} ${url.pathname}${url.search}`);
      }
    });

    await page.route('https://nominatim.openstreetmap.org/**', async (route) => {
      await route.fulfill({
        status: 418,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Direct provider access is forbidden.' }),
      });
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, withExactTokenSpecimen: true });
    await page.route('**/geocoding/search', async (route) => {
      const requestBody = readRouteJson(route);
      const query = typeof requestBody.query === 'string' ? requestBody.query.trim() : '';
      if (!query.startsWith('Delayed ')) {
        await route.fallback();
        return;
      }

      await new Promise<void>((resolve) => {
        delayedGeocodingReleases.set(query, resolve);
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contractVersion: 'geocoding.v1',
          state: 'available',
          results: [{
            displayName: `${query} stale result`,
            latitude: 40.0564,
            longitude: -75.3102,
          }],
          attribution: {
            text: '© OpenStreetMap contributors',
            url: 'https://www.openstreetmap.org/copyright',
          },
          provider: 'nominatim',
          cached: false,
        }),
      });
      delayedGeocodingFinished.add(query);
    });

    await page.setViewportSize({ width: 1428, height: 992 });
    await page.goto('/climbs', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Climbs' })).toBeVisible();
    await expect(page.getByText('Search public places only. Do not enter personal or confidential information.')).toBeVisible();
    const dismissStubMode = page.getByRole('button', { name: 'Dismiss stub mode banner' });
    await dismissStubMode.click();
    await expect(page.getByRole('button', { name: /All climbs/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /With vaults/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /My positions/ })).toBeVisible();
    await expect(page.getByPlaceholder('Search climbs')).toBeVisible();
    await expect(page.getByPlaceholder('Search places')).toBeVisible();
    await expect(page.getByText('Climb vaults', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Open vault', { exact: true })).toHaveCount(0);
    await expect(page.locator('.climb-discovery__map-canvas.maplibregl-map')).toBeVisible();
    await expect(page.locator('.climb-discovery-result')).toHaveCount(3);
    await expect(page.locator('.climb-discovery-marker')).toHaveCount(2);
    await expect(page.locator('.climb-discovery-route')).toHaveCount(1);
    await expect(page.locator('.climb-discovery-route[data-climb-id="climb-1"]')).toHaveCount(1);
    await expect(page.locator('.climb-discovery-route[data-climb-id="climb-2"]')).toHaveCount(0);
    await expect(page.getByText('Invalid zero-length climb')).toHaveCount(0);

    const discoveryRail = page.locator('.climb-discovery__drawer');
    const railBox = await discoveryRail.boundingBox();
    expect(railBox?.width, 'desktop index column width').toBeCloseTo(360, 0);

    const climbResult = page.locator('.climb-discovery-result', { hasText: 'Manayunk Wall' }).first();
    await expect(climbResult).toContainText('69 m');
    await expect(climbResult).toContainText('0.8 km');
    await expect(climbResult).toContainText('8.2%');
    await expect(climbResult).toHaveAttribute('href', '/climbs/climb-1');
    await expect(climbResult).toHaveAccessibleName('Open Manayunk Wall');
    await expect(climbResult).not.toContainText('Philadelphia, PA');
    await expect(climbResult).not.toContainText('Category 4');
    await expect(page.getByText('Open climb', { exact: true })).toHaveCount(0);
    // The trailing value follows the sort word; Deposited carries the vault's CAL.
    await expect(page.getByRole('button', { name: 'Elevation', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Deposited', exact: true }).click();
    await expect(page).toHaveURL(/\/climbs\?sort=deposited$/);
    await expect(climbResult).toContainText('12,345.68 CAL');
    await expect(climbResult).not.toContainText('9,007,199.25 CAL');
    await expect(page.locator('.climb-discovery-result', { hasText: 'Lemon Hill' })).toContainText('—');
    await expect(page.locator('.climb-discovery-result').first()).toContainText('Manayunk Wall');
    await page.getByRole('button', { name: 'Elevation', exact: true }).click();
    await expect(page).toHaveURL(/\/climbs$/);
    await expect(page.locator('.climb-discovery-result').first()).toContainText('Welsh Valley Road');
    await expect.poll(() => browseListRequests.some((request) => (
      request.startsWith('/climbs/list?limit=100')
    ))).toBe(true);
    expect(browseListRequests.some((request) => request.includes('bbox='))).toBe(false);
    expect(browseListRequests.some((request) => request.startsWith('/vaults'))).toBe(false);

    await page.getByRole('button', { name: /With vaults/ }).click();
    await expect(page).toHaveURL(/\/climbs\?hasVault=true$/);
    await expect(page.getByRole('button', { name: /With vaults/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.climb-discovery-result')).toHaveCount(2);
    await expect(page.getByText('Welsh Valley Road')).toHaveCount(0);
    await page.getByRole('button', { name: /All climbs/ }).click();
    await expect(page).toHaveURL(/\/climbs$/);
    await expect(page.locator('.climb-discovery-result')).toHaveCount(3);

    // Hovering a row lights the climb on the ground and shows the bottom card; the card opens the climb.
    await climbResult.hover();
    await expect(page.locator('.climb-discovery-route--hovered[data-climb-id="climb-1"]')).toHaveCount(1);
    const bottomCard = page.locator('.climbs-page__card[data-climb-id="climb-1"]');
    await expect(bottomCard).toBeVisible();
    await expect(bottomCard).toContainText('Manayunk Wall');
    await expect(bottomCard).toContainText('0.8 km · 69 m · 8.2%');
    await expect(bottomCard).toHaveAttribute('href', '/climbs/climb-1');
    await expect(page.getByText('Climb data © OpenStreetMap contributors')).toBeVisible();
    // Map interactions at the opening view: climb lines and dots hover and choose.
    await page.locator('.climb-discovery-route[data-climb-id="climb-1"]').hover({ force: true });
    await expect(page.locator('.climb-discovery-result[data-climb-id="climb-1"]')).toHaveClass(/climb-discovery-result--hovered/);
    await page.locator('.climb-discovery-route[data-climb-id="climb-1"]').click({ force: true });
    await expect(climbResult).toHaveAttribute('data-selected', 'true');
    await expect(page.locator('.climb-discovery-route--selected[data-climb-id="climb-1"]')).toHaveCount(1);
    const welshResult = page.locator('.climb-discovery-result', { hasText: 'Welsh Valley Road' }).first();
    await welshResult.hover();
    await expect(page.locator('.climb-discovery-marker--hovered[data-climb-id="climb-2"]')).toHaveCount(1);
    await page.locator('.climb-discovery-marker[data-climb-id="climb-2"]').click({ force: true });
    await expect(welshResult).toHaveAttribute('data-selected', 'true');
    await expect(climbResult).toHaveAttribute('data-selected', 'false');

    // Clicking a row chooses the climb: the ground moves to it and settles; it does not leave the page.
    await climbResult.click();
    await expect(page).toHaveURL(/\/climbs$/);
    await expect(climbResult).toHaveAttribute('data-selected', 'true');
    await expect(climbResult).toHaveAttribute('aria-current', 'true');
    await expect(welshResult).toHaveAttribute('data-selected', 'false');
    await expect(page.locator('.climb-discovery-route--selected[data-climb-id="climb-1"]')).toHaveCount(1);
    await expect(bottomCard).toBeVisible();
    await page.mouse.move(10, 10);
    await expect(bottomCard).toBeVisible();
    await page.waitForTimeout(1200);
    await expect(page.getByRole('button', { name: 'Search this area' })).toHaveCount(0);
    // A second click on the chosen row opens the climb.
    await climbResult.click();
    await expect(page).toHaveURL(/\/climbs\/climb-1$/);

    if (process.env.BR_CAPTURE_CLIMB_BROWSE_VISUALS === '1') {
      await page.screenshot({
        path: 'test-results/climb-discovery-visuals/climbs-desktop.png',
        fullPage: false,
      });
    }

    await page.setViewportSize({ width: 378, height: 818 });
    await page.goto('/climbs', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Climbs' })).toBeVisible();
    await dismissStubMode.click();
    const mobileDrawer = page.locator('.climb-discovery__drawer');
    const mobileToggle = page.getByRole('button', { name: 'Expand climb results' });
    await expect(mobileDrawer).toHaveAttribute('data-expanded', 'false');
    await expect(mobileToggle).toHaveAttribute('aria-expanded', 'false');
    const mobileDrawerBox = await mobileDrawer.boundingBox();
    expect(mobileDrawerBox).not.toBeNull();
    expect(mobileDrawerBox?.height, 'collapsed results sheet height').toBeGreaterThanOrEqual(76);
    expect(mobileDrawerBox?.height, 'collapsed results sheet height').toBeLessThanOrEqual(80);
    expect(
      (mobileDrawerBox?.y ?? 0) + (mobileDrawerBox?.height ?? 0),
      'collapsed climb drawer remains inside the mobile viewport',
    ).toBeLessThanOrEqual(818);
    if (process.env.BR_CAPTURE_CLIMB_BROWSE_VISUALS === '1') {
      await page.screenshot({
        path: 'test-results/climb-discovery-visuals/climbs-mobile-378.png',
        fullPage: false,
      });
    }
    await mobileToggle.click();
    await expect(mobileDrawer).toHaveAttribute('data-expanded', 'true');
    await expect(page.getByRole('button', { name: 'Collapse climb results' })).toHaveAttribute('aria-expanded', 'true');

    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto('/climbs', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.climb-discovery__map-canvas.maplibregl-map')).toBeVisible();
    await expect(page.getByText('Search public places only. Do not enter personal or confidential information.')).toBeVisible();
    const compactOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(compactOverflow, 'compact climbs horizontal overflow').toBeLessThanOrEqual(1);
    if (process.env.BR_CAPTURE_CLIMB_BROWSE_VISUALS === '1') {
      await page.screenshot({
        path: 'test-results/climb-discovery-visuals/climbs-mobile-320.png',
        fullPage: false,
      });
    }

    await page.setViewportSize({ width: 1428, height: 992 });
    await page.goto('/climbs', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.climb-discovery__map-canvas.maplibregl-map')).toBeVisible();

    const placeSearch = page.getByPlaceholder('Search places');
    await placeSearch.fill('Ma');
    await page.getByRole('button', { name: 'Search places' }).click();
    expect(geocodingRequests, 'short input does not call the geocoder').toEqual([]);
    await placeSearch.fill('Manayunk');
    await page.waitForTimeout(500);
    expect(geocodingRequests, 'typing does not call the geocoder').toEqual([]);
    await page.getByRole('button', { name: 'Search places' }).click();
    await expect.poll(() => geocodingRequests).toHaveLength(1);
    expect(geocodingRequests[0]).toEqual({ path: '/geocoding/search', body: { query: 'Manayunk' } });
    await expect(page.getByRole('link', { name: 'OpenStreetMap contributors' })).toHaveAttribute(
      'href',
      'https://www.openstreetmap.org/copyright',
    );
    await expect(page.getByText('Search public places only. Do not enter personal or confidential information.')).toBeVisible();
    await page.getByRole('button', { name: 'Manayunk, Philadelphia, Pennsylvania, USA' }).click();
    const searchThisArea = page.getByRole('button', { name: 'Search this area' });
    await expect(searchThisArea).toBeVisible();
    for (const width of [768, 1024, 1280, 1350]) {
      await page.setViewportSize({ width, height: 900 });
      const placeSearchBox = await page.locator('.climb-discovery__place-search').boundingBox();
      const searchAreaBox = await searchThisArea.boundingBox();
      expect(placeSearchBox, `${width}px place search bounds`).not.toBeNull();
      expect(searchAreaBox, `${width}px Search this area bounds`).not.toBeNull();
      const overlapsHorizontally = (
        (placeSearchBox?.x ?? 0) < (searchAreaBox?.x ?? 0) + (searchAreaBox?.width ?? 0)
        && (placeSearchBox?.x ?? 0) + (placeSearchBox?.width ?? 0) > (searchAreaBox?.x ?? 0)
      );
      const overlapsVertically = (
        (placeSearchBox?.y ?? 0) < (searchAreaBox?.y ?? 0) + (searchAreaBox?.height ?? 0)
        && (placeSearchBox?.y ?? 0) + (placeSearchBox?.height ?? 0) > (searchAreaBox?.y ?? 0)
      );
      expect(
        overlapsHorizontally && overlapsVertically,
        `${width}px map search controls do not overlap`,
      ).toBe(false);
    }
    await page.setViewportSize({ width: 1428, height: 992 });
    const initialAreaRequestCount = browseListRequests.filter((request) => request.includes('bbox=')).length;
    await searchThisArea.click();
    await expect.poll(() => browseListRequests.filter((request) => request.includes('bbox=')).length)
      .toBeGreaterThan(initialAreaRequestCount);

    await placeSearch.fill('Nowhere');
    await page.waitForTimeout(500);
    expect(geocodingRequests, 'typing still does not call the geocoder').toHaveLength(1);
    await page.getByRole('button', { name: 'Search places' }).click();
    await expect.poll(() => geocodingRequests).toHaveLength(2);
    await expect(page.locator('.climb-discovery__place-state')).toContainText('No places found');

    await placeSearch.fill('Unavailable');
    await page.waitForTimeout(500);
    expect(geocodingRequests, 'typing never calls the geocoder').toHaveLength(2);
    expectingGeocodingUnavailable = true;
    await page.getByRole('button', { name: 'Search places' }).click();
    await expect.poll(() => geocodingRequests).toHaveLength(3);
    await expect(page.locator('.climb-discovery__place-state')).toHaveText(
      'Place search is unavailable right now. Move the map and Search this area.',
    );
    expectingGeocodingUnavailable = false;

    await placeSearch.fill('Delayed input');
    await page.getByRole('button', { name: 'Search places' }).click();
    await expect.poll(() => delayedGeocodingReleases.has('Delayed input')).toBe(true);
    await placeSearch.fill('Edited while pending');
    delayedGeocodingReleases.get('Delayed input')?.();
    await expect.poll(() => delayedGeocodingFinished.has('Delayed input')).toBe(true);
    await expect(placeSearch).toHaveValue('Edited while pending');
    await expect(page.getByRole('button', { name: 'Delayed input stale result' })).toHaveCount(0);

    await placeSearch.fill('Delayed URL');
    await page.getByRole('button', { name: 'Search places' }).click();
    await expect.poll(() => delayedGeocodingReleases.has('Delayed URL')).toBe(true);
    await page.evaluate(() => {
      window.history.pushState({}, '', '/climbs?search=URL%20wins');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await expect(page).toHaveURL(/\/climbs\?search=URL%20wins$/);
    await expect(placeSearch).toHaveValue('URL wins');
    delayedGeocodingReleases.get('Delayed URL')?.();
    await expect.poll(() => delayedGeocodingFinished.has('Delayed URL')).toBe(true);
    await expect(page.getByRole('button', { name: 'Delayed URL stale result' })).toHaveCount(0);

    const search = page.getByPlaceholder('Search climbs');
    await search.fill('Manayunk');
    await expect(page.getByText('Welsh Valley Road')).toHaveCount(0);
    // A fresh page searches the whole canon; a bbox joins only once an area was chosen.
    await expect.poll(() => browseListRequests.some((request) => (
      request.startsWith('/climbs/list?q=Manayunk&')
      && request.includes('limit=100')
    ))).toBe(true);

    await page.goto('/map?search=Manayunk#route', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/\/climbs\?search=Manayunk#route$/);
    await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Climbs' })).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Map' })).toHaveAttribute('href', '/climbs');
    await expect(page.getByRole('link', { name: 'Map', exact: true })).toHaveAttribute('aria-current', 'page');

    await page.goto('/vaults', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/\/climbs\?hasVault=true$/);
    await expect(page.getByRole('heading', { name: 'Climbs' })).toBeVisible();
    await expect(page.getByRole('button', { name: /With vaults/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.climb-discovery-result')).toHaveCount(2);
    await expect(page.getByRole('heading', { name: 'Vaults' })).toHaveCount(0);
    await expect(page.getByPlaceholder('Search vaults')).toHaveCount(0);
    expect(browseListRequests.some((request) => request.startsWith('/vaults'))).toBe(false);

    await page.goto('/vaults/1', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/\/climbs\/climb-1$/);
    await expect(page.getByRole('heading', { name: 'Full Stack Smoke 1776366970' })).toBeVisible();
    await expect(page.locator('#climb-vault')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Your position', exact: true })).toBeVisible();
    await expect(page.getByText('Local Legend', { exact: true }).first()).toBeVisible();

    expect(unexpectedApiCalls, 'unexpected API calls').toEqual([]);
    expect(directNominatimRequests, 'reachable portal path never calls Nominatim directly').toEqual([]);
    expect(pageErrors, 'page errors').toEqual([]);
    expect(consoleErrors, 'console errors').toEqual([]);
  });

  test('uses uploaded ride media for the profile photo band', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on('console', (message) => {
      const text = message.text();
      if (message.type() === 'error' && !isHarnessRuntimeNoise(text)) {
        consoleErrors.push(text);
      }
    });
    page.on('pageerror', (error) => {
      if (!isHarnessRuntimeNoise(error.message)) {
        pageErrors.push(error.message);
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, withRideMedia: true });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile', { waitUntil: 'domcontentloaded' });

    // The photo band (ratified 2026-09-02): the rider's ride photos, eight
    // pixels apart, each opening its ride; one photo fills from the left.
    const photoBand = page.locator('.profile-photos');
    await expect(photoBand).toBeVisible();
    await expect(photoBand).toHaveAttribute('data-photo-count', '1');
    await expect(photoBand.locator('.profile-photos__tile img')).toHaveCount(1);
    await expect(photoBand.locator('.profile-photos__tile')).toHaveAccessibleName(/Morning Ride/);
    await expect(page.locator('.profile-v2-cover-strip')).toHaveCount(0);
    expect(unexpectedApiCalls, 'unexpected API calls').toEqual([]);
    expect(pageErrors, 'page errors').toEqual([]);
    expect(consoleErrors, 'console errors').toEqual([]);
  });

  test('syncs RideView point and range selection across profile, map, and telemetry', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1');
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-ready','true');
    const band=page.locator('.ride-band svg');
    await band.hover({position:{x:220,y:46}});
    await expect(page.locator('.ride-map')).toHaveAttribute('data-scrub-index',await page.locator('.ride-band').getAttribute('data-scrub-index') ?? '');
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await expect(page.locator('.ride-instrument')).toHaveCount(5);
    const speed=page.locator('.ride-instrument[data-metric="speed"]');
    await speed.hover({position:{x:900,y:40}});
    const lines=await page.locator('.ride-scrub-line').evaluateAll(els=>els.map(el=>el.getAttribute('x1')));
    expect(new Set(lines).size).toBe(1);
    await expect(page.locator('.ride-instrument[data-metric="heartRate"] .ride-instrument-readout')).toContainText('BPM');
    const chart=page.locator('.ride-instrument[data-metric="elevation"]');
    const before=await page.locator('.ride-analysis-stats').textContent() ?? '';
    await chart.dragTo(chart,{sourcePosition:{x:220,y:70},targetPosition:{x:850,y:70}});
    await expect(page.getByRole('button',{name:'Clear range'})).toBeVisible();
    await expect(page.locator('.ride-analysis-stats')).not.toHaveText(before);
    await expect(page.locator('.ride-range-fill')).toHaveCount(5);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('routes header rider search through the public rider spine', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-shell__header')).toBeVisible();
    await page.getByRole('button', { name: 'Search' }).click();
    await page.locator('.search-modal-input').fill('tim');

    const riderResult = page.locator('.search-modal-result[data-rider-path="/rider/tim"]').first();
    await expect(riderResult).toBeVisible();
    await expect(riderResult.locator('.search-modal-result__title')).toHaveText('Tim Trail');
    await expect(riderResult.locator('.search-modal-result__sub')).toHaveText('@tim · Boulder');
    await expect(page.getByRole('dialog').getByText('Proofs', { exact: true })).toHaveCount(0);
    await expect(page.getByText(WALLET_SHAPED_TEXT)).toHaveCount(0);

    await riderResult.click();
    await expect(page).toHaveURL(/\/rider\/tim$/);
    await expect(page.getByRole('heading', { name: 'Tim Trail' })).toBeVisible();
    await expect(page.getByText(WALLET_SHAPED_TEXT)).toHaveCount(0);
    expect(unexpectedApiCalls, 'header search unexpected API calls').toEqual([]);
  });

  test('routes own profile edit action into settings without a dead route', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/profile', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Dung Beetle Phoenix' })).toBeVisible();

    // Profile — Ground: your own edit action lives behind the ledger column's menu.
    await page.getByRole('button', { name: 'Open profile menu' }).click();
    await page.getByRole('menuitem', { name: /Edit profile/i }).click();

    await expect(page).toHaveURL(/\/settings(?:\?tab=profile)?$/);
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    expect(unexpectedApiCalls, 'profile edit route unexpected API calls').toEqual([]);
  });

  test('recovers once when a lazy portal route chunk goes stale', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      window.addEventListener('br:stale-chunk-recovery', () => {
        try {
          sessionStorage.setItem('br_test_stale_chunk_recovery', '1');
        } catch {
          // Storage access can be denied in hardened browser contexts.
        }
      });
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.route('**/src/pages/Settings.tsx*', async (route) => {
      await route.fulfill({
        status: 404,
        contentType: 'text/plain',
        body: 'missing Settings route module',
      });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-shell__header')).toBeVisible();

    await page.getByRole('button', { name: 'Open account menu' }).click();
    await page.getByRole('menuitem', { name: 'Settings' }).click();

    await expect.poll(async () => {
      try {
        return await page.evaluate(() => sessionStorage.getItem('br_test_stale_chunk_recovery'));
      } catch {
        return null;
      }
    }).toBe('1');
    await expect(page.getByRole('heading', { name: 'Portal update needed' })).toBeVisible();
    await expect.poll(async () => {
      try {
        return await page.evaluate(() => sessionStorage.getItem('br_chunk_reload_guard'));
      } catch {
        return null;
      }
    }).toBe('1');
    expect(unexpectedApiCalls, 'stale chunk recovery unexpected API calls').toEqual([]);
  });

  test('does not refetch short notification lists forever', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    let notificationRequests = 0;

    page.on('request', (request) => {
      if (request.method() !== 'GET') return;
      const url = new URL(request.url());
      const path = url.pathname.replace(/^\/api/, '') || '/';
      if (path === '/notifications') {
        notificationRequests += 1;
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-shell__header')).toBeVisible();
    await page.waitForTimeout(1_000);

    expect(notificationRequests).toBe(1);
    expect(unexpectedApiCalls, 'notification refetch unexpected API calls').toEqual([]);
  });

  test('uploads direct storage files as signed multipart form data', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    let storageUpload:
      | { method: string; contentType: string; xUpsert: string; body: string }
      | null = null;

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.route('https://storage.test/**', async (route) => {
      const request = route.request();
      storageUpload = {
        method: request.method(),
        contentType: request.headers()['content-type'] ?? '',
        xUpsert: request.headers()['x-upsert'] ?? '',
        body: (await request.postDataBuffer())?.toString('utf8') ?? '',
      };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'rides/user-test-1/upload-direct-1.gpx' }),
      });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Upload ride' }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('heading', { name: 'Upload ride' })).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Upload ride' })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: 'dogfood.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Dogfood</name></trk></gpx>'),
    });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();

    await expect(page.getByText('Ride saved')).toBeVisible();
    expect(storageUpload, 'storage upload request was captured').not.toBeNull();
    expect(storageUpload?.method).toBe('PUT');
    expect(storageUpload?.contentType).toContain('multipart/form-data;');
    expect(storageUpload?.xUpsert).toBe('false');
    expect(storageUpload?.body).toContain('name="file"');
    expect(storageUpload?.body).toContain('filename="dogfood.gpx"');
    expect(unexpectedApiCalls, 'upload unexpected API calls').toEqual([]);
  });

  test('keeps upload surface mounted during active transfer page clicks', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    let releaseStorage!: () => void;
    let storageStarted!: () => void;
    const storageGate = new Promise<void>((resolve) => {
      releaseStorage = resolve;
    });
    const storageStartedSignal = new Promise<void>((resolve) => {
      storageStarted = resolve;
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.route('https://storage.test/**', async (route) => {
      storageStarted();
      await storageGate;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'rides/user-test-1/upload-direct-1.gpx' }),
      });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Upload ride' }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.locator('input[type="file"]').setInputFiles({
      name: 'dogfood.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Dogfood</name></trk></gpx>'),
    });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();
    await storageStartedSignal;

    await expect(page.getByRole('heading', { name: 'Upload ride' })).toBeVisible();
    await page.mouse.click(12, 12);
    await expect(page.getByRole('heading', { name: 'Upload ride' })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);

    releaseStorage();
    await expect(page.getByText('Ride saved')).toBeVisible();
    expect(unexpectedApiCalls, 'upload page unexpected API calls').toEqual([]);
  });

  test('cancels active direct uploads through the abort endpoint', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    let releaseStorage!: () => void;
    let storageStarted!: () => void;
    let abortRequests = 0;
    const storageGate = new Promise<void>((resolve) => {
      releaseStorage = resolve;
    });
    const storageStartedSignal = new Promise<void>((resolve) => {
      storageStarted = resolve;
    });

    page.on('request', (request) => {
      const url = new URL(request.url());
      if (request.method() === 'POST' && url.pathname.endsWith('/rides/upload/abort')) {
        abortRequests += 1;
      }
    });

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.route('https://storage.test/**', async (route) => {
      storageStarted();
      await storageGate;
      try {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ Key: 'rides/user-test-1/upload-direct-1.gpx' }),
        });
      } catch {
        // The browser may abort the in-flight storage request before fulfillment.
      }
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Upload ride' }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.locator('input[type="file"]').setInputFiles({
      name: 'dogfood.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Dogfood</name></trk></gpx>'),
    });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();
    await storageStartedSignal;

    await page.getByRole('dialog', { name: 'Upload ride' }).locator('footer').getByRole('button', { name: 'Cancel' }).click();
    releaseStorage();

    await expect(page.getByRole('dialog', { name: 'Upload ride' }).getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
    await expect.poll(() => abortRequests).toBe(1);
    expect(unexpectedApiCalls, 'upload cancel unexpected API calls').toEqual([]);
  });

  test('routes moderation report riders through the public rider spine', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, isAdmin: true });

    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-page-hero__title')).toHaveText('Admin');
    await page.getByRole('button', { name: /Moderation/ }).click();

    const reportedRider = page.locator('.admin-v2-report-row__target').first();
    const reporter = page.locator('.admin-v2-report-row__reporter').first();
    await expect(reportedRider).toHaveText('Reported rider');
    await expect(reportedRider).toHaveAttribute('data-rider-path', '/rider/reported-user-id');
    await expect(reporter).toHaveText('Tim Trail');
    await expect(reporter).toHaveAttribute('data-rider-path', '/rider/tim');
    await expect(page.getByText(WALLET_SHAPED_TEXT)).toHaveCount(0);
    expect(unexpectedApiCalls, 'moderation report unexpected API calls').toEqual([]);
  });

  test('truth-gates owner actions on public ride details', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-public', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Public Ride' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Analyze' })).toHaveCount(0);
    const rideActions = page.locator('.ride-page-card');
    await rideActions.getByRole('button', { name: 'More ride actions' }).click();
    await expect(rideActions.getByRole('menuitem', { name: 'Delete ride' })).toHaveCount(0);
    await expect(rideActions.getByRole('menuitem', { name: 'Report ride' })).toBeVisible();
    expect(unexpectedApiCalls, 'public ride detail unexpected API calls').toEqual([]);
  });

  test('shows estimated power in analysis when the power stream is absent', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-no-power', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'No Power Ride' })).toBeVisible();
    await page.getByRole('link', { name: 'Ride analysis', exact: true }).click();

    await expect(page.locator('.ride-instrument-label', { hasText: /^POWER · W$/ })).toBeVisible();
    const estimate = page.locator('.ride-instrument[data-metric="power"] .estimated-value');
    await expect(estimate.locator('[aria-hidden="true"]')).toHaveText(/^≈\d[\d,]* W$/);
    await expect(estimate.locator('.sr-only')).toHaveText(/^Estimated .* watts$/);
    await expect(estimate).not.toHaveRole('img');
    await expect(estimate).toHaveCSS('text-decoration-line', 'none');
    await expect(page.locator('.ride-instrument[data-metric="power"] .estimated-value')).not.toHaveRole('button');
    await estimate.click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.ride-instrument[data-metric="power"] .ride-instrument-readout')).toBeVisible();
    expect(unexpectedApiCalls, 'no-power ride detail unexpected API calls').toEqual([]);
  });

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    test(`same effort has identical estimated power for every viewer at ${viewport.width}px`, async ({ browser, baseURL }, testInfo) => {
      test.setTimeout(120_000);
      let standard: { label: string; trace: string } | undefined;
      for (const viewer of [
        { owner: true, weight: 75 },
        { owner: true, weight: 55 },
        { owner: true, weight: 100 },
        { owner: false, weight: 55 },
        { owner: false, weight: 100 },
        { owner: false, weight: null },
      ]) {
        const context = await browser.newContext({ baseURL, viewport });
        try {
          const page = await context.newPage();
          const unexpectedApiCalls: string[] = [];
          await page.addInitScript(() => {
            localStorage.setItem('br_authenticated', 'true');
            localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
            localStorage.setItem('boulder-roller-dark-mode', 'false');
            localStorage.removeItem('br_auth_handoff_pending');
            (window as Window & { ethereum?: unknown }).ethereum = {
              request: async () => [],
              on: () => {},
              removeListener: () => {},
            };
          });
          await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
          await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            const path = url.pathname.replace(/^\/api/, '');
            if (['/auth/bootstrap', '/me', '/users/me'].includes(path)) {
              const profile = {
                ...themedUser(false),
                id: viewer.owner ? user.id : 'visitor-user',
                weight_kg: viewer.weight,
              };
              const original = responseFor(url, 'GET', { darkMode: false }) as Record<string, unknown>;
              await route.fulfill({ json: path === '/auth/bootstrap' ? { ...original, user: profile } : profile });
            } else if (path === '/rides/ride-no-power') {
              const original = responseFor(url, 'GET', { darkMode: false }) as Record<string, unknown>;
              await route.fulfill({ json: { ...original, is_owner: viewer.owner } });
            } else if (path === `/users/${user.id}`) {
              await route.fulfill({ json: {
                ...publicRider,
                id: user.id,
                wallet: user.wallet,
                username: user.username,
                display_name: user.display_name,
              } });
            } else {
              await route.fallback();
            }
          });

          await page.goto('/activities/ride-no-power', { waitUntil: 'domcontentloaded' });
          await expect(page.getByRole('heading', { name: 'No Power Ride' })).toBeVisible();
          await page.locator('.ride-page-card').getByRole('button', { name: 'More ride actions' }).click();
          await expect(page.getByRole('menuitem', { name: 'Delete ride', exact: true })).toHaveCount(viewer.owner ? 1 : 0);
          await page.keyboard.press('Escape');
          await page.getByRole('link', { name: 'Ride analysis', exact: true }).click();
          const instrument = page.locator('.ride-instrument[data-metric="power"]');
          const estimate = instrument.locator('.estimated-value');
          await expect(estimate.locator('[aria-hidden="true"]')).toHaveText(/^≈\d[\d,]* W$/);
          await expect(estimate.locator('.sr-only')).toHaveText(/^Estimated .* watts$/);
          const trace = instrument.locator('.ride-instrument-trace');
          await expect(trace).toHaveAttribute('d', /^M/);
          const actual = {
            label: (await estimate.textContent())!,
            trace: (await trace.getAttribute('d'))!,
          };
          if (!standard) standard = actual;
          expect(actual, `owner=${viewer.owner}, stored weight=${viewer.weight}`).toEqual(standard);
          expect(unexpectedApiCalls).toEqual([]);
          if (viewer.weight === 75 || (viewer.weight === 55 && !viewer.owner)) {
            await page.screenshot({
              path: testInfo.outputPath(`estimated-${viewer.owner ? 'owner' : 'visitor'}-${viewport.width}.png`),
              fullPage: true,
            });
          }
        } finally {
          await context.close();
        }
      }
    });
  }

  test('keeps measured power in analysis when the power stream exists', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await page.getByRole('link', { name: 'Ride analysis', exact: true }).click();

    await expect(page.locator('.ride-instrument-label', { hasText: /^POWER · W$/ })).toBeVisible();
    await expect(page.locator('.ride-instrument-label', { hasText: 'EST POWER' })).toHaveCount(0);
    await expect(page.locator('.ride-instrument[data-metric="power"] .ride-instrument-readout')).toBeVisible();
    expect(unexpectedApiCalls, 'measured-power ride detail unexpected API calls').toEqual([]);
  });

  test('keeps overview climb context and opens selected climb in scoped analysis', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1');
    await expect(page.locator('.ride-band')).toBeVisible();
    const climb=page.locator('.ride-page-climbs a');
    await expect(climb).toContainText('Full Stack Smoke');
    await expect(climb).toHaveAttribute('href','/climbs/climb-1');
    await expect(page.getByRole('button',{name:'Analyze selected'})).toHaveCount(0);
    await climb.click();
    await expect(page).toHaveURL(/\/climbs\/climb-1$/);
    await expect(page.getByRole('region',{name:'Climb leaderboard',exact:true})).toBeVisible();
    await page.goBack();
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await page.getByRole('button',{name:'Full Stack Smoke',exact:true}).click();
    await expect(page).toHaveURL(/\/activities\/ride-1\/climbs\/climb-1\/analysis$/);
    await expect(page.getByRole('button',{name:'Full Stack Smoke',exact:true})).toHaveAttribute('aria-pressed','true');
    await expect(page.locator('.ride-analysis-stats')).toContainText('3.7 km');
    await expect(page.locator('.ride-instrument .ride-counted-trace')).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('keeps profile climb selection aligned after unmappable patterns are filtered', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/activities/ride-filtered-climbs');
    await expect(page.locator('.ride-page-climbs a[href="/climbs/climb-without-offsets"]')).toHaveCount(1);
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    const span=page.locator('.ride-instrument[data-metric="elevation"] [data-climb-id="climb-after-filter"]');
    await expect(span).toBeVisible();
    await expect(page.locator('.ride-instrument [data-climb-id="climb-without-offsets"]')).toHaveCount(0);
    const box=await span.boundingBox();expect(box).not.toBeNull();
    await page.mouse.click(box!.x+box!.width/2,box!.y+box!.height/2);
    await expect(page).toHaveURL(/climbs\/climb-after-filter\/analysis$/);
    await expect(page.locator('.ride-analysis-scope [aria-pressed="true"]')).not.toContainText('Missing offsets');
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('links RideView climb hover across map, profile, and climb rows within 100ms', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1');
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-ready','true');
    // 24xry.22: the band scrub replaces the removed overview selection panels.
    const latency=await page.locator('.ride-band svg').evaluate(async el=>{
      const box=el.getBoundingClientRect(); const start=performance.now();
      el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:box.left+box.width*.35,clientY:box.top+40}));
      return await new Promise<number>((resolve,reject)=>{const check=()=>{const band=document.querySelector('.ride-band')?.getAttribute('data-scrub-index');const map=document.querySelector('.ride-map')?.getAttribute('data-scrub-index');if(band&&band===map&&document.querySelector('.ride-scrub line'))return resolve(performance.now()-start);if(performance.now()-start>100)return reject(Error('scrub linkage exceeded 100ms'));requestAnimationFrame(check);};check();});
    });
    expect(latency).toBeLessThan(100);
    await page.locator('.ride-band svg').hover({position:{x:220,y:40}});
    await expect(page.locator('.ride-map-scrub')).toBeVisible();
    await expect(page.locator('.ride-page-climbs a')).toHaveAttribute('href','/climbs/climb-1');
    await page.mouse.move(24,24);
    await expect(page.locator('.ride-map')).toHaveAttribute('data-scrub-index','');
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('links analysis range selection across the ride instrument', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1/analysis');
    await expect(page.getByRole('button',{name:'Whole ride',exact:true})).toHaveAttribute('aria-pressed','true');
    const before=await page.locator('.ride-analysis-stats').textContent() ?? '';
    const chart=page.locator('.ride-instrument[data-metric="power"]');
    await chart.dragTo(chart,{sourcePosition:{x:200,y:80},targetPosition:{x:850,y:80}});
    await expect(page.locator('.ride-analysis-stats')).not.toHaveText(before);
    await expect(page.locator('.ride-analysis-stats')).not.toHaveAttribute('data-range-start','');
    await expect(page.locator('.ride-range-fill')).toHaveCount(5);
    await page.getByRole('button',{name:'Clear range'}).click();
    await expect(page.locator('.ride-analysis-stats')).toHaveText(before);
    await expect(page.locator('.ride-range-fill')).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('keeps RideView navigation, actions, and route hierarchy singular', async ({ page }) => {
    test.setTimeout(45_000);

    const unexpectedApiCalls: string[] = [];
    const captureDir = process.env.BR_CAPTURE_RIDEVIEW_REFINEMENTS_DIR;
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            (window as Window & { __copiedRideUrl?: string }).__copiedRideUrl = value;
          },
        },
      });
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await expect(page.locator('.ride-map[data-route-ready="true"]')).toBeVisible();

    await expect(page.locator('.ride-detail-window-nav')).toHaveCount(0);
    await expect(page.getByText('Solo ride', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Ride file', { exact: true })).toHaveCount(0);
    await expect(page.locator('.ride-page-card dt',{hasText:/^Time$/})).toBeVisible();
    await expect(page.locator('.ride-page-avatar')).toHaveText('DP');

    const rideActions = page.locator('.ride-page-card');
    await expect(rideActions.getByRole('button',{name:'Comments',exact:true})).toBeVisible();
    await expect(page.getByRole('link',{name:'Ride analysis',exact:true})).toHaveCount(1);
    await rideActions.getByRole('button',{name:'Comments',exact:true}).click();
    await expect(page.locator('#ride-social').getByText('Nice climb signal.')).toBeVisible();
    await page.locator('#ride-social').getByPlaceholder('Add a comment...').focus();
    await expect(page.locator('#ride-social').getByPlaceholder('Add a comment...')).toBeFocused();
    await expect(page.getByRole('dialog',{name:'Ride comments'})).toHaveCount(0);

    const moreRideActions = rideActions.getByRole('button', { name: 'More ride actions' });
    await moreRideActions.click();
    await rideActions.getByRole('menuitem', { name: 'Edit privacy' }).click();
    const privacyDialog = page.getByRole('dialog', { name: 'Edit ride privacy' });
    await expect(privacyDialog).toBeVisible();
    await expect(privacyDialog.getByRole('button', { name: 'Close ride privacy' })).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(privacyDialog.getByRole('button', { name: 'Save privacy' })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(privacyDialog.getByRole('button', { name: 'Close ride privacy' })).toBeFocused();
    if (captureDir) {
      await page.screenshot({ path: path.join(captureDir, 'ride-privacy-editor-desktop.png') });
    }
    await page.keyboard.press('Escape');
    await expect(privacyDialog).toBeHidden();
    await expect(moreRideActions).toBeFocused();

    await moreRideActions.click();
    await rideActions.getByRole('menuitem', { name: 'Copy ride link' }).click();
    await expect.poll(() => page.evaluate(() => (
      (window as Window & { __copiedRideUrl?: string }).__copiedRideUrl
    ))).toMatch(/\/activities\/ride-1$/);

    const mapBox = await page.locator('.ride-page-ground').boundingBox();
    const startBox = await page.getByRole('button',{name:'Start',exact:true}).boundingBox();
    const finishBox = await page.getByRole('button',{name:'Finish',exact:true}).boundingBox();
    expect(mapBox, 'overview map box').not.toBeNull();
    expect(startBox, 'route start marker').not.toBeNull();
    expect(finishBox, 'route finish marker').not.toBeNull();
    if (mapBox && startBox && finishBox) {
      for (const endpoint of [startBox, finishBox]) {
        expect(endpoint.x - mapBox.x).toBeGreaterThanOrEqual(24);
        expect(endpoint.y - mapBox.y).toBeGreaterThanOrEqual(24);
        expect(mapBox.x + mapBox.width - endpoint.x - endpoint.width).toBeGreaterThanOrEqual(24);
        expect(mapBox.y + mapBox.height - endpoint.y - endpoint.height).toBeGreaterThanOrEqual(24);
      }
    }
    await expect(page.locator('.ride-page-climbs a')).toHaveAttribute('href','/climbs/climb-1');
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await expect(page.locator('.ride-analysis-page')).toBeVisible();
    // Previously clicked the loading frame's inert Back div; require the ratified page's real return link.
    await expect(page.locator('a.ride-analysis-back')).toHaveAttribute('href', '/activities/ride-1');
    await page.locator('a.ride-analysis-back').click();
    await page.getByRole('link',{name:'Verification',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Ride log',level:1})).toBeVisible();
    await expect(page.locator('a.ride-analysis-back')).toHaveAttribute('href', '/activities/ride-1');
    await page.locator('a.ride-analysis-back').click();
    await expect(page.getByRole('heading',{name:'Morning Ride'})).toBeVisible();

    if (captureDir) {
      await page.waitForTimeout(800);
      await page.screenshot({ path: path.join(captureDir, 'rideview-refinements-desktop.png') });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-shell-primary-nav--mobile')).toHaveCount(0);
    const menuButton = page.getByRole('button', { name: 'Open navigation' });
    await expect(menuButton).toBeVisible();
    await menuButton.click();
    const navigationDialog = page.getByRole('dialog', { name: 'Navigation' });
    await expect(navigationDialog).toBeVisible();
    for (const item of ['Feed', 'Map']) {
      await expect(navigationDialog.getByRole('link', { name: item, exact: true })).toBeVisible();
    }
    for (const item of ['Climbs', 'Rides', 'Portfolio']) {
      await expect(navigationDialog.getByRole('link', { name: item, exact: true })).toHaveCount(0);
    }
    await expect(navigationDialog.getByRole('button', { name: 'Search' })).toBeVisible();
    await expect(navigationDialog.getByRole('link', { name: 'Feed', exact: true })).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(navigationDialog.getByRole('button', { name: 'Search' })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(navigationDialog.getByRole('link', { name: 'Feed', exact: true })).toBeFocused();
    if (captureDir) {
      await page.screenshot({ path: path.join(captureDir, 'rideview-refinements-navigation.png') });
    }
    await page.getByRole('button', { name: 'Close navigation' }).click();
    await expect(navigationDialog).toBeHidden();

    if (captureDir) {
      await rideActions.getByRole('button', { name: 'More ride actions' }).click();
      await rideActions.getByRole('menuitem', { name: 'Edit privacy' }).click();
      await expect(privacyDialog).toBeVisible();
      await page.screenshot({ path: path.join(captureDir, 'ride-privacy-editor-mobile.png') });
      await privacyDialog.getByRole('button', { name: 'Close ride privacy' }).click();
      await expect(privacyDialog).toBeHidden();
    }

    const mobileWidth = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(mobileWidth.scrollWidth).toBeLessThanOrEqual(mobileWidth.viewportWidth);
    if (captureDir) {
      await expect(page.locator('.ride-map[data-route-ready="true"]')).toBeVisible();
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(captureDir, 'rideview-refinements-mobile-390.png') });
    }

    await page.setViewportSize({ width: 320, height: 720 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    const narrowWidth = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(narrowWidth.scrollWidth).toBeLessThanOrEqual(narrowWidth.viewportWidth);
    if (captureDir) {
      await expect(page.locator('.ride-map[data-route-ready="true"]')).toBeVisible();
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(captureDir, 'rideview-refinements-mobile-320.png') });
    }
    expect(unexpectedApiCalls, 'RideView singular hierarchy unexpected API calls').toEqual([]);
  });

  test('keeps privacy-redacted RideView truthful and scoped', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    const captureDir = process.env.BR_CAPTURE_RIDEVIEW_REFINEMENTS_DIR;
    let privateStreamRequests = 0;
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/rides/ride-private-route/streams') {
        privateStreamRequests += 1;
      }
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.setViewportSize({ width: 826, height: 930 });
    await page.goto('/activities/ride-private-route');
    await expect(page.getByRole('heading',{name:'Private Route Ride'})).toBeVisible();
    await expect(page.getByRole('link',{name:'Tim Trail',exact:true})).toBeVisible();
    await expect(page.locator('.ride-map canvas')).toBeVisible();
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-segments', '0');
    await expect(page.locator('.ride-map .maplibregl-marker')).toHaveCount(0);
    await expect(page.locator('.ride-page-card .ride-page-stats dt')).toHaveText(['Distance','Elevation','Time']);
    await expect(page.locator('.ride-page-climbs a')).toHaveAttribute('href','/climbs/climb-1');
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await expect(page.locator('.ride-instrument[data-metric="power"] .ride-instrument-trace')).toHaveAttribute('d','');
    await expect(page.locator('.ride-instrument[data-metric="power"] .ride-instrument-readout')).toHaveText('');
    await expect(page.locator('.ride-analysis-threshold')).toContainText('Pending');
    await page.getByRole('button',{name:'Full Stack Smoke',exact:true}).click();
    await expect(page).toHaveURL(/climbs\/climb-1\/analysis$/);
    await expect(page.locator('.ride-instrument .ride-instrument-trace')).toHaveCount(4);
    for(const line of await page.locator('.ride-instrument .ride-instrument-trace').all())await expect(line).toHaveAttribute('d','');
    expect(privateStreamRequests).toBe(0);
    await page.locator('.ride-analysis-back').click();
    await expect(page).toHaveURL(/activities\/ride-private-route$/);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('drops cached owner ride data across an authentication boundary', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    let rideDetailRequests = 0;
    let rideGpsRequests = 0;

    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.removeItem('br_auth_handoff_pending');
    });
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (path === '/rides/ride-1') rideDetailRequests += 1;
      if (path === '/rides/ride-1/gps') rideGpsRequests += 1;
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await expect.poll(() => rideDetailRequests).toBe(1);
    await expect.poll(() => rideGpsRequests).toBe(1);

    await page.evaluate(() => {
      localStorage.removeItem('br_authenticated');
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'br_authenticated',
        oldValue: 'true',
        newValue: null,
        storageArea: localStorage,
        url: window.location.href,
      }));
    });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toHaveCount(0);

    await page.evaluate(() => {
      localStorage.setItem('br_authenticated', 'true');
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'br_authenticated',
        oldValue: null,
        newValue: 'true',
        storageArea: localStorage,
        url: window.location.href,
      }));
    });

    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await expect.poll(() => rideDetailRequests).toBe(2);
    await expect.poll(() => rideGpsRequests).toBe(2);
    expect(
      unexpectedApiCalls.filter((call) => call !== 'GET /api/public/previews/activities/ride-1'),
      'auth-boundary RideView unexpected API calls',
    ).toEqual([]);
  });

  test('surfaces missing RideView telemetry and pattern contracts', async ({ page }) => {
    test.setTimeout(30_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.goto('/activities/ride-error');
    await expect(page.getByRole('heading',{name:'Sparse Ride'})).toBeVisible();
    await expect(page.locator('.ride-map canvas')).toBeVisible();
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-segments', '0');
    await expect(page.locator('.ride-map .maplibregl-marker')).toHaveCount(0);
    await expect(page.locator('.ride-page-climbs .ride-page-row')).toHaveCount(0);
    await expect(page.locator('.ride-page-card .ride-page-stats')).toBeVisible();
    await expect(page.getByText('Tile layer unavailable')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Open map layer controls'})).toHaveCount(0);
    await page.goto('/activities/ride-coordinate-error');
    await expect(page.getByRole('heading',{name:'Coordinate Sparse Ride'})).toBeVisible();
    await expect(page.locator('.ride-map canvas')).toBeVisible();
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-segments', '0');
    await expect(page.locator('.ride-map .maplibregl-marker')).toHaveCount(0);
    await expect(page.locator('.ride-band-line')).not.toHaveAttribute('d','');
    await expect(page.locator('.ride-page-climbs a')).toHaveCount(1);
    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('Night Ledger feed access', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.removeItem('br_auth_handoff_pending');
    });
  });
  test('ride links support keyboard and independent social controls', async ({ page }, testInfo) => {
    await routePortalApi(page, [], { darkMode: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('/');
      const card = page.locator('.feed-activity-card').first();
      const link = card.getByRole('link', { name: /Morning Ride/ });
      await expect(link).toHaveAttribute('href', /\/activities\//);
      await expect(link.locator('button, input, a')).toHaveCount(0);
      await link.focus();
      await expect(link).toBeFocused();
      await expect.poll(() => card.evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
      await page.screenshot({ path: testInfo.outputPath(`feed-focus-${width}.png`) });
      await card.getByRole('button', { name: 'Open ride menu' }).click();
      await expect(card.getByRole('button', { name: 'Copy link' })).toBeVisible();
      await expect(page).toHaveURL('/');
      await card.getByRole('button', { name: 'Open ride menu' }).click();
      await card.getByRole('button', { name: /comment/i }).click();
      await expect(card.locator('textarea, input')).toBeVisible();
      await expect(page).toHaveURL('/');
      const href = await link.getAttribute('href');
      await link.focus(); await page.keyboard.press('Enter');
      await expect(page).toHaveURL(href!);
    }
  });
  test('Following clears Everyone during pending empty failed and recovered requests', async ({ page }) => {
    test.setTimeout(60_000);
    await routePortalApi(page, [], { darkMode: true });
    let state = 'pending';
    let release: () => void = () => {};
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/feed/home?*', async route => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('scope') !== 'following') return route.fallback();
      if (state === 'pending') await pending;
      if (state === 'failed') return route.fulfill({ status: 500, json: { detail: 'Following unavailable' } });
      const response = responseFor(url, route.request().method(), { darkMode: true }) as { feed: { activities: Array<Record<string, unknown>> } };
      response.feed.activities = state === 'populated' ? [{ ...response.feed.activities[0], title: 'Followed ride' }] : [];
      await route.fulfill({ json: response });
    });
    await page.goto('/');
    await expect(page.locator('.feed-card__title').first()).toHaveText('Morning Ride');
    await page.getByRole('button', { name: 'Following', exact: true }).click();
    await expect(page.locator('.feed-activity-card')).toHaveCount(0);
    state = 'empty'; release();
    await expect(page.getByRole('heading', { name: 'No rides yet' })).toBeVisible();
    await page.getByRole('button', { name: 'Everyone', exact: true }).click();
    await expect(page.locator('.feed-card__title').first()).toHaveText('Morning Ride');
    state = 'failed'; await page.reload();
    await page.getByRole('button', { name: 'Following', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Could not load feed' })).toBeVisible({ timeout: 25_000 });
    await expect(page.locator('.feed-activity-card')).toHaveCount(0);
    state = 'populated';
    await page.getByRole('button', { name: 'Try again', exact: true }).click();
    await expect(page.locator('.feed-card__title')).toHaveText('Followed ride');
  });
});

test.describe('Home feed rail footer', () => {
  test('places utility links in the finite rail and collapsed account menu', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, feedActivityCopies: 5 });

    const captureDir = path.resolve(
      process.cwd(),
      '../../history/home-feed-rail-footer-2026-07-16',
    );
    fs.mkdirSync(captureDir, { recursive: true });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const rightRail = page.locator('.feed-rail').last();
    const railFooter = rightRail.locator('.feed-rail-footer');
    await expect(rightRail).toBeVisible();
    await expect(railFooter).toBeVisible();
    await expect(railFooter.getByRole('link')).toHaveCount(2);
    await expect(railFooter.getByRole('link', { name: 'Docs' })).toHaveAttribute('href', 'https://docs.boulderroller.xyz/');
    await expect(railFooter.getByRole('link', { name: 'Privacy settings' })).toHaveAttribute('href', '/settings?tab=privacy');
    await expect(railFooter.locator('.portal-panel')).toHaveCount(0);
    expect(await railFooter.evaluate((element) => getComputedStyle(element).position)).toBe('static');

    const lastDiscoveryPanelBox = await rightRail.locator('.feed-box').last().boundingBox();
    const railFooterBox = await railFooter.boundingBox();
    const feedListBox = await page.locator('.feed-virtual-list').boundingBox();
    expect(lastDiscoveryPanelBox, 'last discovery panel box').not.toBeNull();
    expect(railFooterBox, 'rail footer box').not.toBeNull();
    expect(feedListBox, 'response-backed feed list box').not.toBeNull();
    if (lastDiscoveryPanelBox && railFooterBox && feedListBox) {
      expect(railFooterBox.y).toBeGreaterThanOrEqual(lastDiscoveryPanelBox.y + lastDiscoveryPanelBox.height);
      expect(feedListBox.y + feedListBox.height).toBeGreaterThan(railFooterBox.y + railFooterBox.height);
    }

    await page.screenshot({
      path: path.join(captureDir, 'home-feed-rail-footer-desktop-1440.png'),
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.feed-rail-footer')).toBeHidden();

    await page.getByRole('button', { name: /Open account menu/i }).click();
    const accountUtilities = page.getByRole('group', { name: 'Account utilities' });
    await expect(accountUtilities).toBeVisible();
    await expect(accountUtilities.getByRole('menuitem')).toHaveCount(2);
    await expect(accountUtilities.getByRole('menuitem', { name: 'Docs' })).toHaveAttribute('href', 'https://docs.boulderroller.xyz/');
    await expect(accountUtilities.getByRole('menuitem', { name: 'Privacy settings' })).toHaveAttribute('href', '/settings?tab=privacy');

    const accountUtilitiesBox = await accountUtilities.boundingBox();
    expect(accountUtilitiesBox, 'collapsed account utility strip box').not.toBeNull();
    expect(Math.round(accountUtilitiesBox?.height ?? 0)).toBe(48);
    for (const utilityLink of await accountUtilities.getByRole('menuitem').all()) {
      const utilityLinkBox = await utilityLink.boundingBox();
      expect(utilityLinkBox, 'collapsed account utility link box').not.toBeNull();
      expect(Math.round(utilityLinkBox?.width ?? 0)).toBeGreaterThanOrEqual(44);
      expect(Math.round(utilityLinkBox?.height ?? 0)).toBeGreaterThanOrEqual(44);
    }
    await expect(page.locator('.feed-activity-card .portal-utility-links__link')).toHaveCount(0);
    await expect(page.locator('.feed-page .portal-panel .portal-account-utility-strip')).toHaveCount(0);

    await page.screenshot({
      path: path.join(captureDir, 'home-feed-account-utilities-mobile-390x844.png'),
    });

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, 'mobile Home horizontal overflow').toBeLessThanOrEqual(1);
    expect(unexpectedApiCalls, 'home feed capture unexpected API calls').toEqual([]);
  });
});

test.describe('Upload Phase C capture', () => {
  test('locks in file upload processing states', async ({ page }) => {
    test.setTimeout(45_000);

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, uploadCompleteStatus: 'processing' });
    await page.route('https://storage.test/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'rides/user-test-1/upload-direct-1.gpx' }),
      });
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/upload', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Upload ride' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Choose file' })).toBeVisible();
    await expect(page.getByRole('list', { name: 'Upload processing state' })).toHaveCount(0);
    await expect(page.getByText('Counted CAL', { exact: true })).toHaveCount(0);
    await page.waitForTimeout(350);
    await page.screenshot({ path: 'test-results/phase-c/upload-idle-full.png', fullPage: true });

    await page.locator('input[type="file"]').setInputFiles({
      name: 'dogfood.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Dogfood</name></trk></gpx>'),
    });
    await expect(page.getByText('dogfood.gpx', { exact: true })).toBeVisible();
    await page.screenshot({ path: 'test-results/phase-c/upload-selected-full.png', fullPage: true });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();
    await expect(page.locator('.upload-sheet__ladder')).toBeVisible();
    await expect(page.locator('.upload-sheet__ladder [data-state="live"]')).toContainText('Reading ride file');
    await page.screenshot({ path: 'test-results/phase-c/upload-processing-full.png', fullPage: true });

    await expect(page.getByRole('dialog', { name: 'Upload ride' }).getByText('Ride saved', { exact: true })).toBeVisible();
    await expect(page.getByText('Ride saved', { exact: true })).toBeVisible();
    await expect(page.getByRole('list', { name: 'Upload processing state' })).toHaveCount(0);
    await page.screenshot({ path: 'test-results/phase-c/upload-counted-full.png', fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/upload', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Upload ride' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Choose file' })).toBeVisible();
    await expect(page.getByText('Counted CAL', { exact: true })).toHaveCount(0);
    await page.waitForTimeout(350);
    await page.screenshot({ path: 'test-results/phase-c/upload-mobile-390.png', fullPage: true });
    await page.locator('input[type="file"]').setInputFiles({
      name: 'dogfood.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Dogfood</name></trk></gpx>'),
    });
    await expect(page.getByText('dogfood.gpx', { exact: true })).toBeVisible();
    await page.screenshot({ path: 'test-results/phase-c/upload-selected-mobile-390.png', fullPage: true });
    expect(unexpectedApiCalls, 'upload capture unexpected API calls').toEqual([]);
  });
});

test.describe('Threshold Held surfaces', () => {
  test('uses the release-aware state for the ride log and owner ride row', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
      localStorage.setItem('boulder-roller-dark-mode', 'false');
      localStorage.removeItem('br_auth_handoff_pending');
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, withThresholdHeldRide: true });

    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await page.getByRole('link', { name: 'Verification', exact: true }).click();
    await expect(page.getByText('Held — clears when your Threshold is established.')).toBeVisible();
    await expect(page.getByText('Counted CAL', { exact: true })).toHaveCount(0);
    const captureDir = process.env.BR_CAPTURE_THRESHOLD_DIR;
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({
        path: path.join(captureDir, 'threshold-held-ride-desktop.png'),
        fullPage: true,
      });
    }

    await page.goto('/my-activities', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'CAL', exact: true }).click();
    const heldResult = page.locator('.rides-log__row[data-count-state="held"] .rides-log__value');
    await expect(heldResult).toContainText('Held');
    await expect(heldResult).not.toContainText('0');
    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('Threshold pending training surfaces', () => {
  test('uses one pending denominator across Data, Profile, and Ride', async ({ page }) => {
    const captureDir = process.env.BR_CAPTURE_THRESHOLD_DIR;
    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
      localStorage.setItem('boulder-roller-dark-mode', 'false');
      localStorage.removeItem('br_auth_handoff_pending');
    });
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      withThresholdPendingTraining: true,
    });

    await page.goto('/data', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Pending', { exact: true })).toBeVisible();
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({
        path: path.join(captureDir, 'threshold-pending-data-desktop.png'),
        fullPage: true,
      });
    }

    // Profile — Ground carries no training load (ratified 2026-09-02); the
    // pending denominator lives on the rider's Training tab, the Data surface.
    await page.goto('/profile', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-object-page="rider"]')).toBeVisible();
    await expect(page.locator('[data-object-page="rider"]').getByText(/Pending/)).toHaveCount(0);
    await page.goto('/profile?tab=training', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Pending', { exact: true })).toBeVisible();

    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Training load',{exact:true})).toHaveCount(0);
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await expect(page.locator('.ride-analysis-threshold')).toHaveText('Threshold 245 W');
    await expect(page.locator('.ride-analysis-threshold')).not.toContainText('251');
    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('My Rides Phase C capture', () => {
  test('locks in ride log rows of consequence', async ({ page }) => {
    test.setTimeout(45_000);
    const artifacts = {
      full: process.env.PORTAL_MY_RIDES_FULL_SCREENSHOT ?? 'test-results/phase-c/my-rides-full.png',
      mobile: process.env.PORTAL_MY_RIDES_MOBILE_SCREENSHOT ?? 'test-results/phase-c/my-rides-mobile-390.png',
      measurements: process.env.PORTAL_MY_RIDES_MEASUREMENTS ?? 'test-results/phase-c/my-rides-measurements.json',
    };
    for (const artifactPath of Object.values(artifacts)) {
      fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
    }

    const unexpectedApiCalls: string[] = [];
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, withRideLogEmptyStates: true });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: /^Rides/ })).toHaveCount(1);
    await expect(page.getByRole('heading', { name: 'My rides' })).toHaveCount(0);
    await expect(page.locator('.portal-two-column')).toHaveCount(0);
    await expect(page.locator('.activity-matrix')).toHaveCount(0);
    await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(1);
    await expect(page.getByText('3 rides', { exact: true })).toBeVisible();

    // The log is time: three rows, the words choose the trailing value.
    const rows = page.locator('.rides-log__row');
    await expect(rows).toHaveCount(3);
    // One ride carries its cross-section, so the spine column unfolds; its counted span is stroked.
    await expect(page.locator('.rides-log--spines')).toHaveCount(1);
    await expect(page.locator('.rides-log__spine svg')).toHaveCount(1);
    await expect(page.locator('.rides-log__row', { hasText: 'Morning Ride' }).locator('.climb-shape-glyph__span')).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Distance', exact: true })).toHaveAttribute('aria-pressed', 'true');
    const waitingRow = page.locator('.rides-log__row', { hasText: 'Waiting Ride' });
    const countedRow = page.locator('.rides-log__row', { hasText: 'Morning Ride' });
    const notCountedRow = page.locator('.rides-log__row', { hasText: 'Coffee Spin' });
    await expect(waitingRow.locator('.rides-log__value')).toHaveText('—');
    await expect(countedRow.locator('.rides-log__value')).toContainText('48.2 km');
    await page.getByRole('button', { name: 'Time', exact: true }).click();
    await expect(page).toHaveURL(/tab=rides&value=time$/);
    await expect(waitingRow.locator('.rides-log__value')).toHaveText('Waiting');
    await page.getByRole('button', { name: 'CAL', exact: true }).click();
    await expect(countedRow.locator('.rides-log__value')).toHaveText('96 CAL');
    await expect(countedRow).toHaveAttribute('data-count-state', 'counted');
    await expect(waitingRow.locator('.rides-log__value')).toHaveText('Waiting');
    await expect(notCountedRow.locator('.rides-log__value')).toHaveText('Not counted');
    await expect(page.getByText('Counted CAL', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Not counted', { exact: true })).toHaveCount(1);
    await page.getByRole('button', { name: 'Distance', exact: true }).click();
    await expect(page).toHaveURL(/tab=rides$/);

    const rowHeights = await rows.evaluateAll((elements) => (
      elements.map((element) => Math.round(element.getBoundingClientRect().height))
    ));
    expect(Math.max(...rowHeights), `row heights ${rowHeights.join(', ')}`).toBeLessThanOrEqual(56);
    const valueRights = await rows.evaluateAll((elements) => (
      elements.map((row) => Math.round(row.querySelector('.rides-log__value')?.getBoundingClientRect().right ?? 0))
    ));
    expect(Math.max(...valueRights) - Math.min(...valueRights), `trailing values align ${valueRights.join(', ')}`).toBeLessThanOrEqual(1);
    // Rows sit apart by the real gap: today and yesterday stack tight; the ride five days back sits below three idle days of paper.
    const rowTops = await rows.evaluateAll((elements) => (
      elements.map((element) => Math.round(element.getBoundingClientRect().top))
    ));
    expect(rowTops[1] - rowTops[0], 'consecutive days stack tight').toBeLessThanOrEqual(57);
    expect(rowTops[2] - rowTops[1], 'three idle days open a gap').toBeGreaterThanOrEqual(56 + 3 * 14);
    expect(rowTops[2] - rowTops[1], 'the gap is clamped').toBeLessThanOrEqual(56 + 96 + 1);

    await page.waitForTimeout(350);
    await page.screenshot({ path: artifacts.full, fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: /^Rides/ })).toHaveCount(1);
    await expect(page.locator('.rides-log__row')).toHaveCount(3);
    await expect(page.getByText('Morning Ride', { exact: true })).toHaveCount(1);
    const mobileRowHeights = await page.locator('.rides-log__row').evaluateAll((elements) => (
      elements.map((element) => Math.round(element.getBoundingClientRect().height))
    ));
    expect(Math.max(...mobileRowHeights), `mobile row heights ${mobileRowHeights.join(', ')}`).toBeLessThanOrEqual(56);
    await page.waitForTimeout(350);
    await page.screenshot({ path: artifacts.mobile, fullPage: true });
    fs.writeFileSync(artifacts.measurements, `${JSON.stringify({
      desktop: {
        headingCount: 1,
        oldTwoColumnShellCount: 0,
        oldActivityMatrixCount: 0,
        rideRows: 3,
        rowHeightsPx: rowHeights,
        maxRowHeightPx: Math.max(...rowHeights),
        rowTopsPx: rowTops,
        trailingValueRightsPx: valueRights,
        factAppearsOnce: {
          MorningRide: 1,
          NotCounted: 1,
        },
      },
      mobile390: {
        headingCount: 1,
        rideRows: 3,
        rowHeightsPx: mobileRowHeights,
        maxRowHeightPx: Math.max(...mobileRowHeights),
        MorningRide: 1,
      },
    }, null, 2)}\n`);
    expect(unexpectedApiCalls, 'my rides capture unexpected API calls').toEqual([]);
  });
});

test.describe('My Rides truth contract', () => {
  async function prepareAuthenticatedRideLog(page: Page) {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before our app boots.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
  }

  async function expectMobileRideFiltersFullyVisible(
    page: Page,
    expectedParts: Array<[string]>,
  ) {
    const metrics = await page.locator('.my-activities-filter-strip').evaluate((strip) => {
      const stripRect = strip.getBoundingClientRect();
      const documentElement = document.documentElement;
      return {
        viewportWidth: documentElement.clientWidth,
        documentScrollWidth: documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
        stripClientWidth: strip.clientWidth,
        stripScrollWidth: strip.scrollWidth,
        visibleStripLeft: Math.max(0, stripRect.left),
        visibleStripRight: Math.min(documentElement.clientWidth, stripRect.right),
        items: Array.from(strip.querySelectorAll('button')).map((item) => ({
          text: item.textContent?.trim() ?? '',
          parts: Array.from(item.querySelectorAll('span')).map((part) => {
            const rect = part.getBoundingClientRect();
            const style = window.getComputedStyle(part);
            return {
              text: part.textContent?.trim() ?? '',
              left: rect.left,
              right: rect.right,
              visible: (
                rect.width > 0
                && rect.height > 0
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && Number(style.opacity) > 0
              ),
            };
          }),
        })),
      };
    });

    expect(metrics.items).toHaveLength(4);
    expect(metrics.viewportWidth).toBe(390);
    expect(metrics.items.map((item) => item.parts.map((part) => part.text))).toEqual(expectedParts);
    expect(
      metrics.documentScrollWidth,
      `document overflow: ${metrics.documentScrollWidth}px > ${metrics.viewportWidth}px`,
    ).toBeLessThanOrEqual(metrics.viewportWidth);
    expect(
      metrics.bodyScrollWidth,
      `body overflow: ${metrics.bodyScrollWidth}px > ${metrics.viewportWidth}px`,
    ).toBeLessThanOrEqual(metrics.viewportWidth);
    expect(
      metrics.stripScrollWidth,
      `filter strip overflow: ${metrics.stripScrollWidth}px > ${metrics.stripClientWidth}px`,
    ).toBeLessThanOrEqual(metrics.stripClientWidth);
    for (const item of metrics.items) {
      expect(item.parts, `${item.text} should render its label`).toHaveLength(1);
      for (const part of item.parts) {
        expect(part.visible, `${item.text} ${part.text} should be rendered visibly`).toBe(true);
        expect(
          part.left,
          `${item.text} ${part.text} starts left of the visible filter strip`,
        ).toBeGreaterThanOrEqual(metrics.visibleStripLeft);
        expect(
          part.right,
          `${item.text} ${part.text} ends right of the visible filter strip`,
        ).toBeLessThanOrEqual(metrics.visibleStripRight);
      }
    }
  }

  test('failed uploads show the upload date and failure sentence without ride figures or a Ride page link', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: true,
      profileRideTotal: 3,
      failedUploadRides: [rides[0], failedUpload, rides[2]],
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides');

    const row = page.locator('[data-ride-id="failed-upload"]');
    await expect(row.locator('time')).toHaveAttribute('datetime', failedUploadDate);
    await expect(row.locator('time')).toContainText('May 2');
    await expect(row.locator('a')).toHaveCount(0);
    await expect(page.locator('a[data-ride-id="failed-upload"]')).toHaveCount(0);
    await expect(row.locator('.rides-log__value, .rides-log__spine, svg')).toHaveCount(0);
    await expect(page.locator('.rides-log__count')).toHaveText('2 rides');
    await expect(page.locator('.rides-log__state')).toHaveCount(0);
    await expect(row).not.toContainText(/climbs|48\.2|620|96|Waiting|Not counted|—/);
    expect(UPLOAD_PROCESSING_FAILURE).toBe('Could not process this ride. Try exporting the original file again.');
    await expect(row.locator('.rides-log__failure-sentence')).toHaveText(UPLOAD_PROCESSING_FAILURE);
    expect((await row.innerText()).replace(/\s+/g, ' ').trim())
      .toBe(`Original file.gpx May 2 Upload ride ${UPLOAD_PROCESSING_FAILURE}`);
    for (const word of ['Time', 'Elevation', 'CAL', 'Distance']) {
      await page.getByRole('button', { name: word, exact: true }).click();
      await expect(row.locator('.rides-log__value')).toHaveCount(0);
    }
    expect(await page.locator('.rides-log__row').evaluateAll((rows) => rows.map((row) => row.getAttribute('data-ride-id'))))
      .toEqual(['ride-1', 'failed-upload', 'ride-3']);
    expect(unexpectedApiCalls).toEqual([]);
  });

  for (const width of [1440, 390]) {
    test(`failed uploads keep the row footprint and open the upload sheet by keyboard at ${width}px`, async ({ page }, testInfo) => {
      const unexpectedApiCalls: string[] = [];
      await prepareAuthenticatedRideLog(page);
      await routePortalApi(page, unexpectedApiCalls, {
        // Both stored preferences resolve to the portal's one current dark palette.
        darkMode: width === 390,
        profileRideTotal: 3,
        failedUploadRides: [rideLogContractRides[0], failedUpload, rides[2]],
      });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('/profile?tab=rides');
      const row = page.locator('[data-ride-id="failed-upload"]');
      const action = row.getByRole('button', { name: 'Upload ride', exact: true });
      await expect(action).toBeVisible();
      await expect(action).toHaveAccessibleDescription(/Could not process this ride/);
      await expect(row).toHaveAccessibleName('Original file.gpx');
      await expect(row).toHaveAccessibleDescription(/Could not process this ride/);
      await page.evaluate(() => document.fonts.ready);
      const ordinary = page.locator('[data-ride-id="ride-1"]');
      const ordinaryGeometry = await ordinary.boundingBox();
      const failedGeometry = await row.boundingBox();
      // Round 2 permits at most one extra text line on the phone.
      expect(failedGeometry!.height).toBeGreaterThanOrEqual(ordinaryGeometry!.height);
      expect(failedGeometry!.height).toBeLessThanOrEqual(ordinaryGeometry!.height + (width === 390 ? 16 : 0));
      expect(failedGeometry!.width).toBe(ordinaryGeometry!.width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const sentence = row.locator('.rides-log__failure-sentence');
      const titleLeft = (await ordinary.locator('.rides-log__name').boundingBox())!.x;
      expect.soft((await row.locator('.rides-log__name').boundingBox())!.x).toBe(titleLeft);
      expect.soft((await sentence.boundingBox())!.x).toBe(titleLeft);
      const nextRow = page.locator('[data-ride-id="ride-3"]');
      const nextGeometry = (await nextRow.boundingBox())!;
      const monthGap = width === 390 && await nextRow.locator('.rides-log__month').count() ? 28 : 0;
      expect.soft(nextGeometry.y - failedGeometry!.y - failedGeometry!.height).toBe(monthGap);
      const sentenceLayout = await sentence.evaluate((el) => ({
        height: el.clientHeight, scrollHeight: el.scrollHeight, width: el.clientWidth, scrollWidth: el.scrollWidth,
        color: getComputedStyle(el).color, lineHeight: parseFloat(getComputedStyle(el).lineHeight),
      }));
      expect(sentenceLayout.height).toBeLessThanOrEqual(sentenceLayout.lineHeight * (width === 390 ? 2 : 1));
      expect(sentenceLayout.scrollHeight).toBeLessThanOrEqual(sentenceLayout.height);
      expect(sentenceLayout.scrollWidth).toBeLessThanOrEqual(sentenceLayout.width);
      expect(sentenceLayout.color).toBe(await ordinary.locator('time').evaluate((el) => getComputedStyle(el).color));
      await expect(page.locator('html')).toHaveAttribute('data-portal-color-scheme', 'dark');
      const captureDir = process.env.PORTAL_FAILED_UPLOAD_CAPTURE_DIR ?? testInfo.outputDir;
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({ path: path.join(captureDir, `failed-upload-dark-${width}.png`), fullPage: true });
      // Reuse the log's existing sheet destination and return to the same page.
      await action.focus();
      await page.keyboard.press('Enter');
      const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
      await expect(sheet).toBeVisible();
      await expect(sheet.getByRole('button', { name: 'Choose file', exact: true })).toBeVisible();
      await sheet.getByRole('button', { name: 'Cancel', exact: true }).first().click();
      await expect(page).toHaveURL(/\/profile\?tab=rides$/);
      await expect(row).toBeVisible();
      expect(unexpectedApiCalls).toEqual([]);
    });
  }

  test('failed uploads remain searchable and enter type filters only with known matching values', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: true,
      profileRideTotal: 4,
      failedUploadRides: [rides[0], failedUpload, rides[2],
        ride('unknown-upload', 3, 'Unknown file.gpx', 0, 0, 0, {
          status: 'failed', uploaded_at: failedUploadDate,
          distance_m: null, elevation_m: null, cal_earned: null, dung_earned: null,
        }),
      ],
    });
    await page.goto('/profile?tab=rides');
    await expect(page.locator('.rides-log__count')).toHaveText('2 rides');
    const search = page.getByRole('searchbox', { name: 'Search rides' });
    await search.fill('file.gpx');
    await expect(page.locator('.rides-log__row')).toHaveCount(2);
    for (const filter of ['With CAL', 'Long rides', 'Climbing']) {
      await page.getByRole('button', { name: filter, exact: true }).click();
      await expect(page.locator('.rides-log__row')).toHaveCount(1);
      await expect(page.locator('[data-ride-id="failed-upload"]')).toBeVisible();
    }
    await page.getByRole('button', { name: 'All rides', exact: true }).click();
    await expect(page.locator('.rides-log__row')).toHaveCount(2);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('failed uploads without an upload date omit it and never expose placeholder dates or an empty ride shape', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: true, profileRideTotal: 1,
      failedUploadRides: [{ ...failedUpload, uploaded_at: null }],
    });
    await page.goto('/profile?tab=rides');
    const row = page.locator('[data-ride-id="failed-upload"]');
    await expect(row).toBeVisible();
    await expect(row.locator('time, .rides-log__month, .rides-log__value, .rides-log__spine')).toHaveCount(0);
    await expect(page.locator('.rides-log--spines')).toHaveCount(0);
    await expect(page.locator('.rides-log__count')).toHaveText('0 rides');
    await expect(page.getByRole('heading', { name: 'No rides yet' })).toHaveCount(0);
    await expect(row).not.toContainText('Apr');
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('failed uploads are excluded from partial and stale ride counts', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const options: RouteFixtureOptions = {
      darkMode: true, profileRideTotal: 12,
      failedUploadRides: [rides[0], failedUpload, rides[2]],
    };
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, options);
    await page.goto('/profile?tab=rides');
    await expect(page.locator('.rides-log__count')).toHaveText('2 rides');
    await expect(page.getByText('Ride history may be incomplete.', { exact: true })).toBeVisible();
    options.rideListFailureStatus = 422;
    await page.getByRole('button', { name: 'Try again', exact: true }).click();
    await expect(page.getByText('Showing 2 previously loaded rides.', { exact: false })).toBeVisible();
    await expect(page.locator('.rides-log__count')).toHaveText('2 rides');
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('keeps phone ride search operable and exposes exact ride dates', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false, withRideLogEmptyStates: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/profile?tab=rides');
    const search = page.getByRole('searchbox', { name: 'Search rides' });
    await expect(search).toBeVisible();
    await search.fill('Morning');
    await expect(page.locator('.rides-log__row')).toHaveCount(1);
    const row = page.locator('.rides-log__row');
    await expect(row).toHaveAccessibleName(/Morning Ride.*May 4, 2026/);
    await expect(row.locator('time')).toContainText('May 4');
    await search.fill('No such ride');
    await expect(page.getByRole('heading', { name: 'No matching rides' })).toBeVisible();
    await page.getByRole('button', { name: 'Clear filters' }).click();
    await expect(search).toHaveValue('');
    await expect(page.locator('.rides-log__row')).toHaveCount(3);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('reconciles a longer history without losing ride filters on retry', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const options: RouteFixtureOptions = { darkMode: false, profileRideTotal: 410, rideListTotal: 99, rideListMaxLimit: 100 };
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, options);
    await page.goto('/profile?tab=rides');
    await expect(page.locator('.rides-log__count')).toHaveText('99 rides');
    await expect(page.getByText('Ride history may be incomplete.', { exact: true })).toBeVisible();
    await page.getByRole('searchbox', { name: 'Search rides' }).fill('Ride 40');
    await page.getByRole('button', { name: 'With CAL', exact: true }).click();
    options.rideListTotal = 410;
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByText('410 rides', { exact: true })).toBeVisible();
    await expect(page.getByRole('searchbox', { name: 'Search rides' })).toHaveValue('Ride 40');
    await expect(page.getByRole('button', { name: 'With CAL', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.rides-log__row')).toHaveCount(2);
    await expect(page.getByText('Ride history may be incomplete.', { exact: true })).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('renders stored ride relief and only counted spans, then folds absent shapes', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const options: RouteFixtureOptions = { darkMode: false, withRideListShapes: true };
    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, options);
    const streams: string[] = [];
    page.on('request', (request) => {
      if (/\/rides\/[^/]+\/(streams|gps)/.test(request.url())) streams.push(request.url());
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides');
    const glyph = page.locator('.rides-log__spine svg');
    await expect(glyph).toHaveCount(1);
    await expect(glyph.locator('.climb-shape-glyph__span')).toHaveCount(1);
    await expect(glyph.locator('.climb-shape-glyph__span')).toHaveAttribute('d', /^M12\.0 .*L48\.0 /);
    await expect(glyph).toHaveAttribute('aria-hidden', 'true');
    const colors = await glyph.evaluate((svg) => Array.from(svg.querySelectorAll('path')).map((p) => getComputedStyle(p).stroke));
    expect(colors[1]).not.toBe(colors[2]);
    await page.screenshot({ path: 'test-results/ride-shape-desktop.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(glyph).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: 'test-results/ride-shape-mobile.png' });
    expect(streams).toEqual([]);
    expect(unexpectedApiCalls).toEqual([]);
    options.withRideListShapes = false;
    await page.reload();
    await expect(page.locator('.rides-log__row').first()).toBeVisible();
    await expect(page.locator('.rides-log__spine')).toHaveCount(0);
  });

  test('loads the complete ride log without exceeding the backend page limit', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];
    const rideListRequests: Array<{ limit: number; offset: number }> = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (!url.pathname.endsWith('/rides')) return;
      rideListRequests.push({
        limit: Number(url.searchParams.get('limit') ?? 50),
        offset: Number(url.searchParams.get('offset') ?? 0),
      });
    });

    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      rideListTotal: 190,
      rideListMaxLimit: 100,
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('190 rides', { exact: true })).toBeVisible();
    await expect(page.locator('.rides-log__row')).toHaveCount(190);
    await expect(page.getByText('No rides found', { exact: true })).toHaveCount(0);
    // The Rides tab owns the ride log; Profile — Ground fetches rides only
    // for its own Overview, so the log's pages are the only list requests.
    expect(rideListRequests).toEqual([
      { limit: 100, offset: 0 },
      { limit: 100, offset: 100 },
    ]);
    expect(unexpectedApiCalls).toEqual([]);

    const captureDir = process.env.PORTAL_MY_RIDES_TRUTH_CAPTURE_DIR;
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({ path: path.join(captureDir, 'loaded-desktop-1440x1000.png') });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expectMobileRideFiltersFullyVisible(page, [
      ['All rides'],
      ['With CAL'],
      ['Long rides'],
      ['Climbing'],
    ]);
    if (captureDir) {
      await page.screenshot({ path: path.join(captureDir, 'loaded-mobile-390x844.png') });
    }
  });

  test('renders a retryable unavailable state instead of a false zero', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];
    const routeOptions: RouteFixtureOptions = {
      darkMode: false,
      profileRideTotal: 190,
      rideListTotal: 190,
      rideListMaxLimit: 100,
      rideListFailureStatus: 422,
    };

    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, routeOptions);

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Ride history unavailable' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(page.getByText('No rides found', { exact: true })).toHaveCount(0);
    await expect(page.getByText('0 rides', { exact: true })).toHaveCount(0);
    await expect(page.locator('.rides-log__count')).toHaveText('—');
    expect(unexpectedApiCalls).toEqual([]);

    const captureDir = process.env.PORTAL_MY_RIDES_TRUTH_CAPTURE_DIR;
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({ path: path.join(captureDir, 'unavailable-desktop-1440x1000.png') });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expectMobileRideFiltersFullyVisible(page, [
      ['All rides'],
      ['With CAL'],
      ['Long rides'],
      ['Climbing'],
    ]);
    if (captureDir) {
      await page.screenshot({ path: path.join(captureDir, 'unavailable-mobile-390x844.png') });
    }

    routeOptions.rideListFailureStatus = undefined;
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByText('190 rides', { exact: true })).toBeVisible();
    await expect(page.locator('.rides-log__row')).toHaveCount(190);
    await expect(page.getByRole('heading', { name: 'Ride history unavailable' })).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('surfaces a mismatch instead of presenting a partial list as complete', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];

    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      profileRideTotal: 190,
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/profile?tab=rides', { waitUntil: 'domcontentloaded' });

    await expect(page.locator('.rides-log__count')).toHaveText('3 rides');
    await expect(page.getByText('Ride history may be incomplete.', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(page.locator('.rides-log__row')).toHaveCount(3);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('keeps an offline paused first load out of the empty-account state', async ({ page }) => {
    test.setTimeout(45_000);
    const unexpectedApiCalls: string[] = [];

    await prepareAuthenticatedRideLog(page);
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      profileRideTotal: 190,
      rideListTotal: 190,
      rideListMaxLimit: 100,
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('button', { name: 'Open account menu for Dung Beetle Phoenix' })).toBeVisible();
    await page.evaluate(() => {
      Object.defineProperty(window.navigator, 'onLine', {
        configurable: true,
        get: () => false,
      });
      window.dispatchEvent(new Event('offline'));
      window.history.pushState({}, '', '/profile?tab=rides');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    await expect(page).toHaveURL(/\/profile\?tab=rides$/);
    await expect(page.getByRole('heading', { name: 'Ride history unavailable' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(page.getByText('No rides yet', { exact: true })).toHaveCount(0);
    await expect(page.getByText('No rides found', { exact: true })).toHaveCount(0);
    await expect(page.getByText('0 rides', { exact: true })).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });
});

test.describe('ClimbView Phase C capture', () => {
  test('omits signed-out Vault actions and preserves the Climb destination through the access door', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const ownerReads: string[] = [];
    page.on('request', request => { if (/\/vaults\/|\/portfolio/.test(new URL(request.url()).pathname)) ownerReads.push(new URL(request.url()).pathname); });
    await routeEyebrowPublicPreviewSpecimens(page, unexpectedApiCalls);
    await page.goto('/climbs/preview-climb?climbView=history#climb-vault');
    await expect(page.getByRole('heading', { name: 'Shawmont Rise', exact: true })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Time', exact: true })).toBeChecked();
    await expect(page.getByText('All-time top 10', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Ranked by time. Names use public profiles only.', { exact: true })).toHaveCount(0);
    await expect(page.locator('.climb-metric-picker input[aria-describedby]')).toHaveCount(0);
    await expect(page.getByRole('textbox', { name: 'CAL', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Hold to/ })).toHaveCount(0);
    await expect(page.getByText(/Deposit CAL|Withdraw CAL|Your position|Your history|Local Legend/)).toHaveCount(0);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    // Previously pinned the preview overlay; lane D ratifies full-page entry and the exact stored object destination.
    await assertFullPagePublicEntry(page, '/climbs/preview-climb?climbView=history#climb-vault');
    await page.goBack();
    await expect(page).toHaveURL('/climbs/preview-climb?climbView=history#climb-vault');
    await expect(page.getByRole('heading', { name: 'Shawmont Rise', exact: true })).toBeVisible();
    expect(ownerReads).toEqual([]);
    expect(unexpectedApiCalls).toEqual([]);
  });

  for (const responseStatus of [503, 401]) test(`never repeats a collection submission after an uncertain server response (${responseStatus})`, async ({ page }) => {
    await routePortalApi(page, [], { withClimbViewSpecimen: true });
    let submissions = 0;
    await page.route('**/vaults/1/pending-rewards', route => route.fulfill({ json: { total_pending_base_units: '1000000000', fee_estimate_base_units: '50000000', net_estimate_base_units: '950000000', harvest_fee_bps: '500' } }));
    await page.route('**/vaults/1/harvest', route => { submissions++; return route.fulfill({ status: responseStatus, json: { detail: 'Submission response unavailable' } }); });
    await page.route('**/balance/operations/lookup?**', route => route.fulfill({status:404,json:{detail:'Operation not found'}}));
    await page.goto('/climbs/climb-1?climbView=collect');
    const hold = page.getByRole('button', { name: 'Hold to Collect 0.95 DUNG' });
    await expect(hold).toBeEnabled();
    await hold.dispatchEvent('click', { detail: 0 });
    await expect(page.locator('[data-operation-phase]')).toHaveAttribute('data-operation-phase', 'review');
    expect(submissions).toBe(1);
    await expect(page.getByRole('button', { name: /Hold to Collect/ })).toHaveCount(0);
  });

  test('keeps a recorded collection locked until fresh DUNG is zero and recovers without repeating it', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { withClimbViewSpecimen: true });
    let collected = false;
    let submissions = 0;
    const pending = { total_pending_base_units: '4250000000', fee_estimate_base_units: '212500000', net_estimate_base_units: '4037500000', harvest_fee_bps: '500', exit_fee_bps: '50', lp_tokens_base_units: '1180000000000' };
    await page.route('**/vaults/1/pending-rewards', (route) => route.fulfill({ json: collected ? { ...pending, total_pending_base_units: '0', fee_estimate_base_units: '0', net_estimate_base_units: '0' } : pending }));
    await page.route('**/vaults/1/harvest', async (route) => {
      submissions++;
      expect(Object.keys(route.request().postDataJSON())).toEqual(['client_request_id']);
      await route.fulfill({ json: { operation_id: 'collection-1', projection_status: 'recorded', confirmation_status: 'confirmed' } });
    });
    await page.route('**/balance/operations/collection-1', (route) => route.fulfill({ json: { operation_id: 'collection-1', action_type: 'collect_dung', reference_type: 'vault', reference_id: '1', recorded: true, read_state: 'recorded', pending: false, delayed: false, needs_review: false, rider_state: null } }));
    await page.goto('/climbs/climb-1?climbView=collect');
    const hold = page.getByRole('button', { name: 'Hold to Collect 4.04 DUNG' });
    await expect(hold).toBeEnabled();
    // Pointer release before the required hold cancels. Accessibility activation is direct.
    await hold.click();
    expect(submissions).toBe(0);
    await hold.dispatchEvent('click', { detail: 0 });
    await expect(page.locator('[data-operation-phase]')).toHaveAttribute('data-operation-phase', 'saved');
    expect(submissions).toBe(1);
    await expect(hold).toHaveCount(0);
    await page.reload();
    await expect(page.locator('[data-operation-phase]')).toHaveAttribute('data-operation-phase', 'saved');
    expect(submissions).toBe(1);
    collected = true;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.locator('[data-operation-phase]')).toHaveAttribute('data-operation-phase', 'refreshed');
    await expect(page.getByText('DUNG received in your wallet.', { exact: true })).toBeVisible();
    expect(submissions).toBe(1);
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('inspects the canon profile and switches the ranked trailing metric without moving focus or ranks', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { withClimbViewSpecimen: true });
    await page.route('**/climbs/climb-1', async (route) => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.fallback();
      const body = responseFor(new URL(route.request().url()), 'GET', { withClimbViewSpecimen: true }, {}) as Record<string, unknown>;
      await route.fulfill({ json: { ...body, route_preview: CANON_VAULT_ROUTE_PREVIEW, elevation_profile: CANON_VAULT_ELEVATION_PROFILE } });
    });
    await page.goto('/climbs/climb-1');
    const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
    const time = board.getByRole('radio', { name: 'Time', exact: true });
    const power = board.getByRole('radio', { name: 'Power', exact: true });
    await expect(time).toBeChecked();
    const rows = board.locator('[data-object-row="record-board"]');
    const order = await rows.evaluateAll((elements) => elements.map((element) => element.getAttribute('data-rank')));
    await time.focus();
    await time.press('ArrowRight');
    await expect(power).toBeChecked();
    await expect(power).toBeFocused();
    await expect(rows.first()).toContainText('382 W');
    expect(await rows.evaluateAll((elements) => elements.map((element) => element.getAttribute('data-rank')))).toEqual(order);
    await power.press('ArrowLeft');
    await expect(time).toBeChecked();
    await expect(time).toBeFocused();
    await expect(rows.first()).toContainText('9:50');
    const profile = page.getByRole('slider', { name: 'Position on elevation profile' });
    await profile.focus();
    await profile.press('End');
    await expect(profile).toHaveAttribute('aria-valuetext', /547.*59.*%/);
    const labelOverlaps = await page.locator('.climb-profile-inspection__chart svg text').evaluateAll(labels => {
      const boxes = labels.map(label => ({ text: label.textContent, rect: label.getBoundingClientRect() }));
      return boxes.flatMap((a, index) => boxes.slice(index + 1).filter(b =>
        Math.min(a.rect.right, b.rect.right) > Math.max(a.rect.left, b.rect.left)
        && Math.min(a.rect.bottom, b.rect.bottom) > Math.max(a.rect.top, b.rect.top)
      ).map(b => [a.text, b.text]));
    });
    expect(labelOverlaps, 'Profile inspection leaves the summit label readable').toEqual([]);
    await expect(page.getByLabel('Position on climb map', { exact: true })).toBeVisible();
    await profile.press('Home');
    await expect(profile).toHaveValue('0');
    await page.getByRole('button', { name: 'Expand map', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Climb map' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Expand map', exact: true })).toBeFocused();
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('offers vault creation only from a ratified climb without a vault', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const captures = {
      desktop: process.env.PORTAL_CANON_CREATE_DESKTOP_SCREENSHOT,
      desktopCreate: process.env.PORTAL_CANON_CREATE_DESKTOP_MODAL_SCREENSHOT,
      mobile: process.env.PORTAL_CANON_CREATE_MOBILE_SCREENSHOT,
      mobileDrawer: process.env.PORTAL_CANON_CREATE_MOBILE_MODAL_SCREENSHOT,
    };
    for (const capturePath of Object.values(captures)) {
      if (capturePath) fs.mkdirSync(path.dirname(capturePath), { recursive: true });
    }
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      withCanonVaultCreationSpecimen: true,
      canonVaultPrepareDelayMs: 400,
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`/climbs/${CANON_CLIMB_ROW_ID}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Manayunk Wall' })).toHaveCount(1);
    const createVaultButton = page.getByRole('button', { name: 'Create Vault' });
    await expect(createVaultButton).toBeVisible();
    await expect(page.getByText('Vault detail', { exact: true })).toHaveCount(0);
    if (captures.desktop) await page.screenshot({ path: captures.desktop, fullPage: true });

    await createVaultButton.click();
    await expect(page).toHaveURL(new RegExp(`/climbs/${CANON_CLIMB_ROW_ID}/create-vault$`));
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('[data-object-page="create-vault"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Create Vault' })).toBeVisible();
    await expect(page.locator('.create-vault-map .route-map-shell--ready')).toBeVisible();
    const desktopLayout = await page.locator('.create-vault-layout').boundingBox();
    const desktopRoute = await page.locator('.create-vault-route-column').boundingBox();
    const desktopWorkspace = await page.locator('.create-vault-workspace').boundingBox();
    expect(desktopLayout).not.toBeNull();
    expect(desktopRoute).not.toBeNull();
    expect(desktopWorkspace).not.toBeNull();
    const routeShare = desktopRoute!.width / (desktopRoute!.width + desktopWorkspace!.width);
    expect(routeShare).toBeGreaterThanOrEqual(0.55);
    expect(routeShare).toBeLessThanOrEqual(0.68);
    const createPageText = await page.locator('[data-object-page="create-vault"]').innerText();
    expect(createPageText).not.toMatch(/[0-9a-f]{8}-[0-9a-f-]{27,}/i);
    expect(createPageText).not.toMatch(/signature|centerline|geometry|canonical revision/i);
    await page.waitForTimeout(350);
    if (captures.desktopCreate) {
      await expect.poll(
        () => page.locator('.create-vault-map .leaflet-tile').evaluateAll((tiles) => (
          tiles.length > 0
          && tiles.every((tile) => {
            const image = tile as HTMLImageElement;
            return image.complete && image.naturalWidth > 0;
          })
        )),
        { timeout: 15_000 },
      ).toBe(true);
      await page.screenshot({ path: captures.desktopCreate });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(new RegExp(`/climbs/${CANON_CLIMB_ROW_ID}/create-vault$`));
    const creationDialog = page.getByRole('dialog');
    await expect(creationDialog.getByRole('heading', { name: 'Create Vault' })).toBeVisible();
    await page.waitForTimeout(350);
    if (captures.mobile) await page.screenshot({ path: captures.mobile, fullPage: true });
    if (captures.mobileDrawer) await page.screenshot({ path: captures.mobileDrawer });
    await creationDialog.getByRole('button', { name: 'Use CAL + USDC' }).click();

    const prepareRequestPromise = page.waitForRequest((request) => (
      request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/vaults/create/canon/prepare')
    ));
    await creationDialog.getByRole('button', { name: 'Create Vault' }).click();
    await expect(creationDialog.getByRole('button', { name: 'Preparing Vault' })).toBeVisible();
    const prepareRequest = await prepareRequestPromise;
    const prepareBody = prepareRequest.postDataJSON() as Record<string, unknown>;
    expect(prepareBody).toEqual({
      climb_id: CANON_CLIMB_ROW_ID,
      payment_method: 'cal_usdc',
      client_request_id: expect.any(String),
    });
    for (const clientDerivedField of ['signature_hex', 'name', 'vert_m', 'distance_m', 'avg_gradient_pct']) {
      expect(prepareBody).not.toHaveProperty(clientDerivedField);
    }
    await expect(creationDialog.getByText('Could not create Vault.')).toBeVisible();
    const retryButton = creationDialog.getByRole('button', { name: 'Try again' });
    await expect(retryButton).toBeVisible();
    const retryRequestPromise = page.waitForRequest((request) => (
      request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/vaults/create/canon/prepare')
    ));
    await retryButton.click();
    const retryRequest = await retryRequestPromise;
    expect(retryRequest.postDataJSON()).toEqual(prepareBody);
    expect(unexpectedApiCalls, 'canon vault creation specimen unexpected API calls').toEqual([]);
  });

  test('does not expose the mobile creation drawer for an unavailable climb URL', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/climbs/${CANON_CLIMB_ROW_ID}/create-vault`, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(new RegExp(`/climbs/${CANON_CLIMB_ROW_ID}$`));
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Create Vault' })).toHaveCount(0);
    expect(unexpectedApiCalls, 'unavailable canon creation route unexpected API calls').toEqual([]);
  });

  test('draws the ratified relative section as one ground and graded lines', async ({ page }) => {
    test.setTimeout(90_000);
    await routePortalApi(page, [], { withClimbViewSpecimen: true });
    await page.route('**/climbs/climb-1', route => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.fallback();
      const body = responseFor(new URL(route.request().url()), 'GET', { withClimbViewSpecimen: true }, {}) as Record<string, unknown>;
      return route.fulfill({ json: { ...body, elev_gain_m: 93, route_preview: CANON_VAULT_ROUTE_PREVIEW,
        elevation_profile: [{ distance_m: 0, elevation_m: 100 }, { distance_m: 100, elevation_m: 101 }, { distance_m: 200, elevation_m: 105 }, { distance_m: 300, elevation_m: 112 }, { distance_m: 400, elevation_m: 122 }, { distance_m: 500, elevation_m: 135 }, { distance_m: 1000, elevation_m: 193 }] } });
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/climbs/climb-1');
    const profile = page.locator('.climb-profile-inspection__chart svg');
    await expect(profile).toBeVisible();
    await expect(profile.locator('path:not([fill="none"])')).toHaveCount(1);
    await expect(profile.getByText('93 m', { exact: true })).toBeVisible();
    const lines = await profile.locator('path[fill="none"]').evaluateAll(paths => paths.map(path => ({ color: getComputedStyle(path).stroke, weight: Number(path.getAttribute('stroke-width')) })));
    expect(lines).toEqual(expect.arrayContaining([
      { color: 'rgb(78, 75, 70)', weight: 1.6 }, { color: 'rgb(106, 102, 96)', weight: 1.8 },
      { color: 'rgb(154, 148, 136)', weight: 2 }, { color: 'rgb(241, 238, 232)', weight: 2.2 },
      { color: 'rgb(241, 238, 232)', weight: 3 },
    ]));
    const scrub = page.getByRole('slider', { name: 'Position on elevation profile' });
    await scrub.focus();
    await scrub.press('End');
    await expect(scrub).toHaveAttribute('aria-valuetext', /elevation 93 m/);
    await expect(page.getByLabel('Position on climb map', { exact: true })).toBeVisible();

    // Reference-board geometry, fixture riders/positions, and live CARTO ground.
    const reference = fs.readFileSync(path.resolve('../../history/climb-room-2026-09-05/climb-room-board.html'), 'utf8');
    const boardClimb = JSON.parse(reference.match(/<script id="climb" type="application\/json">(.*?)<\/script>/s)![1]);
    const boardGround = JSON.parse(reference.match(/<script id="basemap" type="application\/json">(.*?)<\/script>/s)![1]);
    const boardRiders = [...reference.match(/const RIDERS=\[(.*?)\];/s)![1].matchAll(/\['([^']+)','([^']+)','([^']+)'\]/g)];
    await page.route('**/vaults/1/leaderboard', route => route.fulfill({ json: {
      climb_id: 'climb-1', vault_id: 1, leaderboard: boardRiders.map(([, name, time, date], index) => ({
        rank: index + 1, position: index + 1, competition_rank: index + 1,
        user_id: name === 'You' ? user.id : `reference-rider-${index}`,
        wallet: name === 'You' ? TEST_WALLET : undefined,
        username: name === 'You' ? user.username : `reference-rider-${index}`,
        display_name: name, identity_hidden: false, completion_id: `reference-result-${index}`,
        best_time_seconds: Number(time.split(':')[0]) * 60 + Number(time.split(':')[1]),
        avg_power_w: null, achieved_at: new Date(`${date}, 2026 12:00:00 UTC`).toISOString(),
      })),
    } }));
    const referenceRoute = buildCanonVaultRoutePreview(boardGround.route.map(([lon, lat]: number[]) => [lat, lon]));
    await page.route('**/climbs/climb-1', route => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.fallback();
      const body = responseFor(new URL(route.request().url()), 'GET', { withClimbViewSpecimen: true }, {}) as Record<string, unknown>;
      return route.fulfill({ json: { ...body, name: boardClimb.name, region: 'Manayunk · Philadelphia',
        length_m: boardClimb.lengthM, elev_gain_m: boardClimb.elevationM, avg_gradient_pct: boardClimb.grade,
        route_preview: referenceRoute, elevation_profile: boardClimb.profile.map(([distance_m, elevation_m]: number[]) => ({ distance_m, elevation_m })) } });
    });
    await page.route('**/vaults/1/my-completions?**', route => route.fulfill({ json: {
      vault_id: 1, vault_name: boardClimb.name, efforts: [0,1,2,3].map(index => ({ id: `reference-effort-${index}`, ride_id: `reference-ride-${index}`, time_seconds: 341 + index, avg_power_w: null, achieved_at: iso(index), is_pr: index === 0, improvement: null })), total_count: 4, best_time_seconds: 341, total_prs: 1,
    } }));
    const output = process.env.PORTAL_CLIMB_PAGE_CAPTURE_DIR;
    if (output) fs.mkdirSync(output, { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
      await page.goto('/climbs/climb-1');
      const banner = page.getByRole('button', { name: 'Dismiss stub mode banner' });
      await expect(page.getByRole('heading', { name: 'Port Royal Avenue' })).toBeVisible();
      await expect(banner).toBeVisible();
      await banner.click();
      await expect(page.locator('.climb-page-yours')).toHaveText('Your best 5:41 · 7th');
      await expect(page.locator('.climb-map')).toHaveAttribute('data-canon-ready', 'true');
      await page.waitForLoadState('networkidle');
      const seam = page.getByRole('slider', { name: 'Climb route and elevation', exact: true });
      const identity = await page.locator('.climb-page-identity').boundingBox();
      const ground = await page.locator('.climb-page-ground').boundingBox();
      expect(identity!.y).toBeGreaterThan(ground!.y);
      expect(identity!.x).toBe(width === 1440 ? 40 : 16);
      expect(identity!.width).toBe(width === 1440 ? 360 : 358);
      const glyph = await page.locator('.climb-page-glyph svg').boundingBox();
      expect([glyph!.width, glyph!.height]).toEqual([40, 20]);
      const handleSize = await page.locator('.climb-page-handle').boundingBox();
      expect([handleSize!.width, handleSize!.height]).toEqual([36, 4]);
      await expect(page.locator('.climb-result-rank img')).toHaveCount(3);
      await expect(page.locator('.climb-detail-leaderboard .climb-result-row:visible')).toHaveCount(width === 1440 ? 10 : 5);
      await expect.poll(() => page.locator('.climb-map-endpoint').evaluateAll(endpoints => {
        const card = document.querySelector('.climb-page-identity')!.getBoundingClientRect();
        return endpoints.filter(endpoint => { const r = endpoint.getBoundingClientRect(); return Math.min(card.right, r.right) > Math.max(card.left, r.left) && Math.min(card.bottom, r.bottom) > Math.max(card.top, r.top); }).length;
      }), { message: 'The route endpoints fit clear of the identity card' }).toBe(0);
      const inspect = page.getByRole('slider', { name: 'Position on elevation profile' });
      await inspect.fill(String(Math.round(boardClimb.profile[112][0])));
      // Focus follows keyboard interaction; scroll the page back to its reading frame.
      await page.evaluate(() => window.scrollTo(0, 0));
      if (output) await page.screenshot({ path: path.join(output, `climb-page-${width}-reading.png`), fullPage: width === 1440 });
      if (width === 390) {
        await page.getByRole('button', { name: 'Top 10', exact: true }).click();
        await expect(page.locator('.climb-detail-leaderboard .climb-result-row:visible')).toHaveCount(10);
        await page.locator('.climb-page-ledger-scroll').evaluate(el => { el.scrollTop = 0; });
      }
      const endpointBefore = await page.getByRole('button', { name: 'Finish of climb', exact: true }).boundingBox();
      const handle = await seam.boundingBox();
      await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2);
      await page.mouse.down();
      await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2 + 320, { steps: 12 });
      await page.mouse.up();
      await expect(seam).toHaveAttribute('aria-valuenow', width === 1440 ? '1040' : '150');
      if (width === 390) expect(await page.locator('.climb-page-sheet').evaluate(el => getComputedStyle(el).borderTopLeftRadius)).toBe('20px');
      const endpointAfter = await page.getByRole('button', { name: 'Finish of climb', exact: true }).boundingBox();
      expect(Math.abs(endpointAfter!.y - endpointBefore!.y) + Math.abs(endpointAfter!.x - endpointBefore!.x)).toBeGreaterThan(10);
      await page.waitForLoadState('networkidle');
      if (output) await page.screenshot({ path: path.join(output, `climb-page-${width}-looking-around.png`), fullPage: width === 1440 });
      // Pan the live map, then resize: the rider's chosen camera is retained.
      const canvas = page.locator('.climb-map-canvas canvas');
      const mapBox = await canvas.boundingBox();
      const panX = width === 1440 ? 800 : 180;
      const panY = mapBox!.y + (width === 1440 ? 300 : 390);
      await page.mouse.move(panX, panY); await page.mouse.down();
      await page.mouse.move(panX + 60, panY + 25, { steps: 6 }); await page.mouse.up();
      const beforePanResize = await page.getByRole('button', { name: 'Finish of climb', exact: true }).boundingBox();
      await seam.focus(); await seam.press('ArrowUp');
      const afterPanResize = await page.getByRole('button', { name: 'Finish of climb', exact: true }).boundingBox();
      expect(Math.abs(afterPanResize!.x - beforePanResize!.x)).toBeLessThan(3);
      if (width === 390) expect(Math.abs(afterPanResize!.y - beforePanResize!.y)).toBeLessThan(3);
      await seam.press('Home');
      await expect(seam).toHaveAttribute('aria-valuenow', width === 1440 ? '320' : '150');
      await seam.press('End');
      await expect(seam).toHaveAttribute('aria-valuenow', width === 1440 ? '1040' : String(Math.round((844 - 62) * .72)));
      await page.getByRole('button', { name: 'Expand map', exact: true }).click();
      await expect(page.getByRole('dialog', { name: 'Climb map' })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('button', { name: 'Expand map', exact: true })).toBeFocused();
    }
  });

  test('locks in the approved map-led Climb composition on desktop and mobile', async ({ page }) => {
    test.setTimeout(60_000);
    const unexpectedApiCalls: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', error => consoleErrors.push(error.message));
    await routePortalApi(page, unexpectedApiCalls, { withClimbViewSpecimen: true });
    await page.goto('/climbs/climb-1');
    await expect(page.locator('.climb-empty-band')).toBeVisible();
    await expect(page.locator('.climb-empty-band')).toHaveCSS('height', '185px');
    await expect(page.getByText('Profile unavailable', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('slider', { name: 'Position on elevation profile' })).toHaveCount(0);
    await page.route('**/climbs/climb-1', async (route) => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.fallback();
      const body = responseFor(new URL(route.request().url()), 'GET', { withClimbViewSpecimen: true }, {}) as Record<string, unknown>;
      await route.fulfill({ json: { ...body, route_preview: CANON_VAULT_ROUTE_PREVIEW, elevation_profile: CANON_VAULT_ELEVATION_PROFILE } });
    });
    const output = process.env.PORTAL_CLIMB_CAPTURE_DIR ?? 'test-results/climb-detail';
    fs.mkdirSync(output, { recursive: true });
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
      await page.reload();
      await expect(page.getByRole('heading', { name: 'Full Stack Smoke 1776366970' })).toHaveCount(1);
      await expect(page.getByRole('region', { name: 'Climb leaderboard', exact: true })).toHaveCount(1);
      await expect(page.getByRole('region', { name: 'Local Legend', exact: true })).toHaveCount(1);
      await expect(page.locator('[data-object-row="record-board"]')).toHaveCount(2);
      await expect(page.getByRole('link', { name: 'Your history' })).toBeVisible();
      await expect.soft(page.getByText('All-time top 10', { exact: true })).toHaveCount(0);
      await expect.soft(page.getByText('Ranked by time. Names use public profiles only.', { exact: true })).toHaveCount(0);
      await expect.soft(page.locator('#climb-vault .climb-section-heading')).toHaveText('Vault');
      await expect.soft(page.locator('.climb-metric-picker input[aria-describedby]')).toHaveCount(0);
      await expect(page.locator('.climb-map')).toHaveAttribute('data-canon-ready', 'true');
      const layout = await page.evaluate(() => {
        const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
        const board = rect('[data-object-layer="climb-record-board"]');
        const vault = rect('#climb-position');
        const boardCard = rect('.climb-detail-leaderboard');
        const vaultCard = rect('#climb-position .climb-ledger-card');
        const map = rect('.climb-map');
        const profile = document.querySelector('.climb-profile-inspection__chart svg') as SVGSVGElement;
        const bounds = profile.getBoundingClientRect();
        return { overflow: document.documentElement.scrollWidth - innerWidth, boardTop: board.top, boardRight: board.right, boardCardTop: boardCard.top, vaultCardTop: vaultCard.top, vaultTop: vault.top, vaultLeft: vault.left, mapBottom: map.bottom, profileTop: bounds.top, profileRatio: bounds.width / bounds.height, intrinsicRatio: profile.viewBox.baseVal.width / profile.viewBox.baseVal.height };
      });
      expect(layout.overflow).toBeLessThanOrEqual(1);
      if (width === 1440) expect(layout.profileTop).toBeGreaterThanOrEqual(layout.mapBottom);
      else expect(layout.profileTop).toBeLessThan(layout.mapBottom);
      expect(layout.profileRatio).toBeCloseTo(layout.intrinsicRatio, 2);
      if (width === 1440) { expect(Math.abs(layout.boardTop - layout.vaultTop)).toBeLessThan(2); expect(layout.vaultLeft).toBeGreaterThan(layout.boardRight); expect.soft(Math.abs(layout.boardCardTop - layout.vaultCardTop)).toBeLessThan(2); }
      else expect(layout.vaultTop).toBeGreaterThan(layout.boardTop);
      const targets = await page.locator('.climb-metric-picker input, .climb-navigation-row:is(a), .climb-map-controls button, .climb-map-zoom button').evaluateAll(elements => elements.filter(element => element.getClientRects().length > 0).map(element => element.getBoundingClientRect().height));
      expect(Math.min(...targets)).toBeGreaterThanOrEqual(44);
      await page.screenshot({ path: path.join(output, `signed-in-fixture-${width}.png`), fullPage: true });
    }
    await page.evaluate(() => document.documentElement.style.fontSize = '200%');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await expect(page.getByRole('radio', { name: 'Time', exact: true })).toBeVisible();
    const mapControlsOverlap = await page.evaluate(() => {
      const zoom = document.querySelector('.climb-map-zoom')!.getBoundingClientRect();
      const attribution = document.querySelector('.climb-map-attribution')!.getBoundingClientRect();
      return zoom.right > attribution.left && zoom.left < attribution.right && zoom.bottom > attribution.top && zoom.top < attribution.bottom;
    });
    expect(mapControlsOverlap, 'zoom controls and map attribution remain independently usable at 200% text').toBe(false);
    await expect.poll(() => page.locator('.climb-map').evaluate(map => {
      const chrome = Array.from(map.querySelectorAll('.climb-map-controls, .climb-map-zoom, .climb-map-attribution')).map(element => element.getBoundingClientRect());
      return Array.from(map.querySelectorAll('.climb-map-endpoint')).filter(element => {
        const endpoint = element.getBoundingClientRect();
        return chrome.some(control => Math.min(endpoint.right, control.right) > Math.max(endpoint.left, control.left)
          && Math.min(endpoint.bottom, control.bottom) > Math.max(endpoint.top, control.top));
      }).map(element => element.getAttribute('aria-label'));
    }), { timeout: 3_000, message: 'Enlarged map chrome leaves both 44px endpoint targets usable' }).toEqual([]);
    const vaultLabelsOverlap = await page.evaluate(() => {
      const labels = Array.from(document.querySelectorAll('.climb-vault-summary .climb-kv > span')).map(label => {
        const range = document.createRange();
        range.selectNodeContents(label);
        return range.getBoundingClientRect();
      });
      return labels[0].right > labels[1].left && labels[0].bottom > labels[1].top && labels[0].top < labels[1].bottom;
    });
    expect(vaultLabelsOverlap, 'Vault summary labels remain readable at 200% text').toBe(false);
    await page.screenshot({ path: path.join(output, 'signed-in-fixture-320-text-200.png'), fullPage: true });

    // Removing the normal-state label must retain useful loading/recovery states.
    let vaultState: 'opening' | 'loading' | 'unavailable' = 'opening';
    let releaseVault = () => {};
    await page.route('**/vaults/1', async route => {
      if (vaultState === 'loading') await new Promise<void>(resolve => { releaseVault = resolve; });
      await route.fulfill(vaultState === 'unavailable'
        ? { status: 503, json: { detail: 'Vault unavailable' } }
        : { json: vault(1, 'Full Stack Smoke', false) });
    });
    for (const state of ['opening', 'loading', 'unavailable'] as const) {
      vaultState = state;
      await page.reload();
      const vaultSection = page.getByRole('region', { name: 'Vault', exact: true });
      await expect(vaultSection.getByRole('heading', { name: 'Vault', exact: true })).toBeVisible();
      await page.evaluate(() => document.documentElement.style.fontSize = '200%');
      // A 503 exhausts three API retry groups (6s each) plus query backoff (1s + 2s).
      await expect(vaultSection.locator('.climb-section-heading')).toHaveText(state === 'opening' ? 'VaultInitializing' : state === 'loading' ? 'Vault' : 'Vault', { timeout: state === 'unavailable' ? 30_000 : 10_000 });
      if (state === 'loading') {
        await expect(vaultSection.locator('[data-slot]').first()).toBeVisible();
        await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-live', 'true');
      } else await expect(vaultSection).toContainText(state === 'opening' ? 'This vault is still opening.' : 'Vault unavailable', { timeout: state === 'unavailable' ? 30_000 : 10_000 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await expect(vaultSection.getByRole('link', { name: 'Deposit CAL', exact: true })).toHaveCount(0);
      await page.screenshot({ path: path.join(output, `vault-${state}-fixture-320-text-200.png`), fullPage: true });
      releaseVault();
    }
    await page.route('**/climbs/climb-1', route => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.fallback();
      return route.fulfill({ json: responseFor(new URL(route.request().url()), 'GET', { withCanonVaultCreationSpecimen: true }, {}) });
    });
    await page.reload();
    await expect(page.getByText('No vault', { exact: true })).toBeVisible();
    await page.evaluate(() => document.documentElement.style.fontSize = '200%');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await expect(page.locator('#climb-vault .climb-section-heading')).toHaveText('Vault');
    await expect(page.getByText('All-time top 10', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: path.join(output, 'no-vault-fixture-320-text-200.png'), fullPage: true });
    expect(unexpectedApiCalls).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('preserves tied seats, missing power and hidden identities, then hides the board on privacy failure', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { withClimbViewSpecimen: true });
    let failed = false;
    await page.route('**/vaults/1/leaderboard', route => route.fulfill(failed ? { status: 503, json: { detail: 'Privacy projection unavailable' } } : { json: { climb_id: 'climb-1', vault_id: 1, leaderboard: [
      { position: 2, rank: 2, competition_rank: 1, is_tied: true, tie_size: 2, identity_hidden: true, display_name: 'Must not appear', username: 'hidden', user_id: 'hidden-id', wallet: 'hidden-wallet', best_time_seconds: 590, avg_power_w: null },
      { position: 5, rank: 5, competition_rank: 5, is_tied: false, username: 'visible-rider', display_name: 'Visible rider', user_id: 'visible-id', best_time_seconds: 620, avg_power_w: null },
    ] } }));
    await page.goto('/climbs/climb-1');
    const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
    const rows = board.locator('[data-object-row="record-board"]');
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText('T-1');
    await expect(rows.first().getByRole('link')).toHaveCount(0);
    await expect(board).not.toContainText('Must not appear');
    await expect(board).not.toContainText('hidden-wallet');
    await board.getByRole('radio', { name: 'Power', exact: true }).check();
    await expect(rows.first().locator('.climb-result-value')).toHaveCount(0);
    await expect(rows.last()).toHaveAttribute('data-rank', '5');
    await expect(rows.last().getByRole('link', { name: 'Visible rider', exact: true })).toHaveAttribute('href', '/rider/visible-rider');
    failed = true;
    // A new observer on the same identity refetches the now-stale privacy projection.
    await page.getByRole('link', { name: 'All climbs', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Climbs', exact: true })).toBeVisible();
    await page.clock.install();
    await page.clock.fastForward(61_000);
    await page.goBack();
    await expect(board.getByText('Could not load leaderboard', { exact: true })).toBeVisible();
    await expect(board.locator('[data-object-row="record-board"]')).toHaveCount(0);
    expect(unexpectedApiCalls).toEqual([]);
  });

});

test.describe('Gate A capture', () => {
  test('gate a capture rideview', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'test-results/gate-a/rideview-full.png', fullPage: true });
  });

  test('approved shell and RideView masthead visual contract', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const captureDir = process.env.BR_CAPTURE_RIDEVIEW_MASTHEAD_DIR;
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    await page.setViewportSize({ width: 1440, height: 1000 });
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:width===1440?1000:844});
      await page.goto('/activities/ride-1');
      await expect(page.getByRole('heading',{name:'Morning Ride'})).toBeVisible();
      await expect(page.locator('.portal-shell__brand-mark')).toHaveText('');
      await expect(page.locator('.ride-page-avatar')).toBeVisible();
      await expect(page.locator('.ride-page-card .ride-page-stats>div')).toHaveCount(3);
      const layout=await page.evaluate(()=>{const card=document.querySelector('.ride-page-card')!.getBoundingClientRect();const rows=[...document.querySelectorAll('.ride-page-card .ride-page-stats>div')].map(el=>el.getBoundingClientRect());return {width:card.width,left:card.left,columns:new Set(rows.map(r=>Math.round(r.left))).size,rows:new Set(rows.map(r=>Math.round(r.top))).size,overflow:document.documentElement.scrollWidth-window.innerWidth};});
      expect(layout.width).toBe(width===1440?360:width-32);expect(layout.left).toBe(width===1440?40:16);
      expect(layout.columns).toBe(3);expect(layout.rows).toBe(1);expect(layout.overflow).toBeLessThanOrEqual(0);
      await expect(page.locator('.ride-page-spine')).toBeVisible({visible:width===1440});
      if(width===1440){const nav=await page.locator('.portal-shell__topbar > .portal-shell-primary-nav').boundingBox();expect(Math.abs(nav!.x+nav!.width/2-width/2)).toBeLessThanOrEqual(2);}
    }
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('gate a contract measurements', async ({ page }) => {
    test.setTimeout(45_000);
    const artifacts = {
      measurements: process.env.PORTAL_GATE_A_CONTRACT_MEASUREMENTS ?? 'test-results/gate-a/rideview-contract-measurements.json',
    };
    fs.mkdirSync(path.dirname(artifacts.measurements), { recursive: true });

    const unexpectedApiCalls: string[] = [];
    await page.setViewportSize({ width: 1440, height: 1000 });
    await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

    const measureStats = async (ridePath: string, heading: string) => {
      await page.goto(ridePath, { waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      await expect(page.locator('.ride-page-card .ride-page-stats>div')).toHaveCount(3);
      return page.evaluate(() => {
        const container = document.querySelector<HTMLElement>('.ride-page-card .ride-page-stats');
        const containerRect = container?.getBoundingClientRect();
        const stats = Array.from(document.querySelectorAll<HTMLElement>('.ride-page-card .ride-page-stats>div'));
        const firstValue = stats[0]?.querySelector<HTMLElement>('dd');
        const firstLabel = stats[0]?.querySelector<HTMLElement>('dt');
        const valueStyle = firstValue ? window.getComputedStyle(firstValue) : null;
        const labelStyle = firstLabel ? window.getComputedStyle(firstLabel) : null;

        return {
          stats: stats.map((element) => {
            const rect = element.getBoundingClientRect();
            return {
              label: element.querySelector('dt')?.textContent?.trim() ?? '',
              left: Math.round(rect.left - (containerRect?.left ?? 0)),
              top: Math.round(rect.top - (containerRect?.top ?? 0)),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            };
          }),
          valueLabelRatio: valueStyle && labelStyle
            ? Number((parseFloat(valueStyle.fontSize) / parseFloat(labelStyle.fontSize)).toFixed(2))
            : 0,
          valueFontVariantNumeric: valueStyle?.fontVariantNumeric ?? '',
        };
      });
    };

    const rideOne = await measureStats('/activities/ride-1', 'Morning Ride');
    const rideTwo = await measureStats('/activities/ride-2', 'Bridge Repeats');
    const positionDeltas = rideOne.stats.map((stat, index) => ({
      label: stat.label,
      leftDeltaPx: Math.abs(stat.left - (rideTwo.stats[index]?.left ?? stat.left)),
      topDeltaPx: Math.abs(stat.top - (rideTwo.stats[index]?.top ?? stat.top)),
      widthDeltaPx: Math.abs(stat.width - (rideTwo.stats[index]?.width ?? stat.width)),
    }));
    const maxPositionDeltaPx = Math.max(...positionDeltas.flatMap((delta) => [
      delta.leftDeltaPx,
      delta.topDeltaPx,
      delta.widthDeltaPx,
    ]));

    expect(maxPositionDeltaPx, `position deltas ${JSON.stringify(positionDeltas)}`).toBeLessThanOrEqual(1);
    expect(rideOne.valueLabelRatio, 'value:label ratio').toBe(1.5);
    expect(rideOne.valueFontVariantNumeric).toContain('tabular-nums');

    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-ready','true');
    const hoverLatencyMs=await page.locator('.ride-band svg').evaluate(async el=>{const b=el.getBoundingClientRect(),start=performance.now();el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:b.left+200,clientY:b.top+45}));return await new Promise<number>((resolve,reject)=>{const check=()=>{const i=document.querySelector('.ride-band')?.getAttribute('data-scrub-index');if(i&&document.querySelector('.ride-map')?.getAttribute('data-scrub-index')===i)return resolve(performance.now()-start);if(performance.now()-start>100)return reject(Error('scrub linkage exceeded 100ms'));requestAnimationFrame(check);};check();});});
    expect(hoverLatencyMs).toBeLessThan(100);

    fs.writeFileSync(artifacts.measurements, `${JSON.stringify({
      positionalInvariance: {
        rideOne: 'ride-1',
        rideTwo: 'ride-2',
        deltasPx: positionDeltas,
        maxDeltaPx: maxPositionDeltaPx,
      },
      recognitionTypography: {
        valueLabelRatio: rideOne.valueLabelRatio,
        valueFontVariantNumeric: rideOne.valueFontVariantNumeric,
        ratifiedRatio: 1.5,
      },
      linkedHighlighting: {
        hoverLatencyMs,
        thresholdMs: 100,
      },
    }, null, 2)}\n`);
    expect(unexpectedApiCalls, 'gate-a contract measurement unexpected API calls').toEqual([]);
  });
});

interface TypographyStyleEvidence {
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  lineHeight: string;
  letterSpacing: string;
  textTransform: string;
}

function typographyCapturePath(fileName: string): string | null {
  const captureDir = process.env.PORTAL_TYPOGRAPHY_CAPTURE_DIR;
  if (!captureDir) return null;
  fs.mkdirSync(captureDir, { recursive: true });
  return path.join(captureDir, fileName);
}

async function captureTypographyPage(page: Page, fileName: string, fullPage = true) {
  const capturePath = typographyCapturePath(fileName);
  if (!capturePath) return;
  await page.screenshot({ path: capturePath, fullPage, animations: 'disabled' });
}

async function captureTypographyLocator(locator: Locator, fileName: string) {
  const capturePath = typographyCapturePath(fileName);
  if (!capturePath) return;
  await locator.screenshot({ path: capturePath, animations: 'disabled' });
}

async function readTypographyStyle(locator: Locator): Promise<TypographyStyleEvidence> {
  return locator.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return {
      fontFamily: style.fontFamily,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      lineHeight: style.lineHeight,
      letterSpacing: style.letterSpacing,
      textTransform: style.textTransform,
    };
  });
}

function expectSansTypography(style: TypographyStyleEvidence) {
  expect(style.fontFamily).toContain('Geist');
  expect(style.fontFamily).not.toContain('Geist Mono');
}

function expectMonoTypography(style: TypographyStyleEvidence) {
  expect(style.fontFamily).toContain('Geist Mono');
}

async function routeTypographyPublicSpecimen(page: Page, unexpectedApiCalls: string[]) {
  await routePortalApi(page, unexpectedApiCalls, { darkMode: false });

  const unauthenticated = {
    authenticated: false,
    invite_required: true,
    invite_validated: false,
    needs_profile_setup: false,
    auth_method_hint: null,
  };
  for (const routePattern of ['**/auth/bootstrap', '**/auth/onboarding/state']) {
    await page.route(routePattern, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(unauthenticated),
      });
    });
  }

  await page.route('**/public/previews/rides/preview-ride*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'public_preview.v1',
        object_type: 'ride',
        id: 'preview-ride',
        canonical_path: '/rides/preview-ride',
        title: 'Shawmont Morning',
        preview_policy: {
          mode: 'public_preview',
          object_type: 'ride',
          raw_gps_available: false,
          streams_available: false,
          tiles_available: false,
          private_ride_history_available: false,
          unreviewed_projections_available: false,
          wallet_required: false,
          login_required_for: ['streams', 'private ride history'],
          blocked_surfaces: ['raw GPS', 'wallet'],
        },
        seo: {
          title: 'Shawmont Morning · Ride · Boulder Roller',
          description: 'Public ride preview',
          canonical_path: '/rides/preview-ride',
          robots: 'index,follow',
        },
        assets: {
          contract_version: 'public_preview.v1',
          object_type: 'ride',
          route_preview: {
            kind: 'route_preview',
            preview: rides[0].route_preview,
          },
        },
        freshness: {
          source: 'fixture',
          loaded_at: iso(0),
          cache_ttl_seconds: 60,
        },
        ride: {
          ...ride('preview-ride', 0, 'Shawmont Morning', 31_800, 524, 104),
          cal_earned: undefined,
          dung_earned: undefined,
          status: 'finalized',
          rider: {
            contract_version: 'public_rider_ref.v1',
            id: 'tim-user',
            username: 'tim',
            display_name: 'Tim Trail',
            is_public: true,
            identity_hidden: false,
          },
        },
      }),
    });
  });
}

async function routeTypographyAdminSpecimen(page: Page) {
  const h3Index = '85283473fffffff';
  const climb = {
    id: 'typography-climb',
    activity_id: 'ride-1',
    road_name: 'Shawmont Rise',
    vert_m: 182,
    distance_m: 1_940,
    avg_gradient_pct: 9.4,
    persistence_m: 91.4,
    significance_g: 0.732,
    significance_percentile: 98.4,
    significance_return_period: 62,
    significance_confidence_tier: 2,
    significance_bootstrapped: true,
    significance_cell_h3: h3Index,
    signature_hex: 'typography-signature',
    review_status: 'confirmed',
    reviewed_at: iso(1),
    created_at: iso(12),
  };
  const cell = {
    h3_index: h3Index,
    h3_resolution: 5,
    n_features: 48,
    k_exceedances: 18,
    threshold_m: 24.5,
    threshold_quantile: 0.8,
    gpd_xi: 0.084,
    gpd_sigma: 32.4,
    xi_ci_hi: 0.14,
    g_cap: 0.88,
    confidence_tier: 2,
    tail_diag_pass: true,
    bootstrapped_at: iso(14),
    osm_road_km: 16.2,
    parent_h3_index: null,
    n_unique_riders: 12,
    effective_n: 9.4,
    top_rider_pct: 0.18,
    diversity_tier: 2,
    n_unique_routes: 17,
  };
  const elevationSamples = Array.from({ length: 25 }, (_, index) => ({
    t: index * 10,
    elevation_m: 34 + index * 3.4 + Math.sin(index / 2) * 2,
    power_w: 248 + index * 4,
    speed_mps: 4.6 - index * 0.035,
  }));
  const fittedCurve = Array.from({ length: 24 }, (_, index) => ({
    x: 24.5 + index * 5,
    empirical_cdf: Math.min(0.98, 0.08 + index * 0.038),
    gpd_cdf: Math.min(0.985, 0.075 + index * 0.039),
  }));

  await page.route('**/admin/significance/**', async (route) => {
    const url = new URL(route.request().url());
    const requestPath = url.pathname.replace(/^\/api/, '');
    let body: unknown;

    if (requestPath === '/admin/significance/overview') {
      body = {
        terrain_cells: {
          total: 1,
          by_confidence_tier: { 2: 1 },
          by_resolution: { 5: 1 },
          diag_pass_count: 1,
          diag_fail_count: 0,
          oldest_bootstrap: iso(14),
          newest_bootstrap: iso(14),
          by_diversity_tier: { 2: 1 },
          single_rider_cells: 0,
          effective_n_stats: { min: 9.4, max: 9.4, median: 9.4 },
        },
        gpd_params: {
          xi_histogram: [{ bin: 0.08, count: 1 }],
          sigma_histogram: [{ bin: 32, count: 1 }],
          xi_stats: { min: 0.084, max: 0.084, mean: 0.084, median: 0.084 },
          sigma_stats: { min: 32.4, max: 32.4, mean: 32.4, median: 32.4 },
        },
        climb_scores: {
          total: 128,
          scored: 64,
          unscored: 18,
          g_histogram: [{ bin: 0.7, count: 14 }],
          percentile_histogram: [{ bin: 95, count: 18 }],
        },
      };
    } else if (requestPath === '/admin/significance/climbs') {
      body = { climbs: [climb], total: 1, limit: 50, offset: 0 };
    } else if (requestPath === '/admin/significance/cells') {
      body = { cells: [cell], total: 1 };
    } else if (requestPath === '/admin/significance/pipeline-stats') {
      body = {
        climbs_detected: 128,
        climbs_with_persistence: 104,
        climbs_in_terrain_cell: 82,
        climbs_scored: 64,
        climbs_unscored: 18,
        dropoffs: [
          { stage: 'persistence', from: 128, to: 104, reason: 'below persistence gate' },
          { stage: 'terrain_cell', from: 104, to: 82, reason: 'awaiting terrain cell' },
          { stage: 'scored', from: 82, to: 64, reason: 'awaiting GPD fit' },
        ],
      };
    } else if (requestPath === '/admin/significance/drift-summary') {
      body = {
        run_id: 'typography-run',
        total_cells: 1,
        drifted_cells: 0,
        stale_climbs: 0,
        drifted_cell_details: [],
        trigger_reason: null,
      };
    } else if (requestPath === '/admin/significance/climb/typography-climb/profile') {
      body = {
        climb: {
          id: climb.id,
          road_name: climb.road_name,
          vert_m: climb.vert_m,
          distance_m: climb.distance_m,
          persistence_m: climb.persistence_m,
          significance_g: climb.significance_g,
          start_offset_s: 20,
          end_offset_s: 220,
        },
        profile: {
          context_before_s: 20,
          context_after_s: 20,
          samples: elevationSamples,
          smoothed: elevationSamples.map((sample, index) => (
            sample.elevation_m - Math.cos(index / 3) * 0.6
          )),
          smoothing_window: 5,
        },
        persistence: {
          noise_gate_m: 8,
          pairs: [
            {
              birth_idx: 2,
              death_idx: 22,
              birth_elev: 40.1,
              death_elev: 112.4,
              persistence_m: 72.3,
              above_noise_gate: true,
            },
            {
              birth_idx: 8,
              death_idx: 11,
              birth_elev: 59.2,
              death_elev: 64.7,
              persistence_m: 5.5,
              above_noise_gate: false,
            },
          ],
        },
      };
    } else if (requestPath === '/admin/significance/climb/typography-climb/trace') {
      body = {
        climb,
        cell,
        trace: {
          persistence_m: 91.4,
          noise_gate_m: 8,
          passed_noise_gate: true,
          midpoint_tile: 'typography-tile',
          cell_lookup: {
            res5_parent: h3Index,
            res5_found: true,
            res4_fallback: false,
            cell_h3: h3Index,
          },
          threshold_m: 24.5,
          threshold_quantile: 0.8,
          exceedance_m: 66.9,
          gpd_xi: 0.084,
          gpd_sigma: 32.4,
          xi_ci_hi: 0.14,
          survival_point: 0.0268,
          survival_conservative: 0.0412,
          g_point: 0.784,
          g_conservative: 0.732,
          g_cap: 0.88,
          g_final: 0.732,
          diag_pass: true,
          confidence_tier: 2,
          percentile: 98.4,
          return_period: 62,
        },
      };
    } else if (requestPath === `/admin/significance/cells/${h3Index}/fit`) {
      body = {
        cell,
        persistence_values: [24.5, 31, 43, 58, 72, 91.4, 106, 128],
        threshold_m: 24.5,
        fitted_curve: fittedCurve,
        climb_positions: [
          {
            id: climb.id,
            persistence_m: climb.persistence_m,
            g_score: climb.significance_g,
            road_name: climb.road_name,
          },
        ],
      };
    }

    if (body === undefined) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `Unmocked typography admin route: ${requestPath}` }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
}

test.describe('Public preview privacy cache', () => {
  test('revalidates a public preview after it leaves the screen', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await routeTypographyPublicSpecimen(page, unexpectedApiCalls);

    await page.goto('/rides/preview-ride', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await page.locator('.public-page .portal-shell__brand').click();
    await expect(page).toHaveURL(/\/$/);
    // The URL changes before React finishes leaving the preview. Returning during
    // that transition cancels navigation instead of exercising cache remounting.
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toHaveCount(0);

    let revokedPreviewRequests = 0;
    await page.route('**/public/previews/rides/preview-ride*', async (route) => {
      revokedPreviewRequests += 1;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Preview unavailable' }),
      });
    });

    await page.goBack({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Preview unavailable', { exact: true })).toBeVisible();
    expect(revokedPreviewRequests).toBeGreaterThan(0);
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toHaveCount(0);
  });
});

test.describe('Ratified typography review evidence', () => {
  test('captures public preview roles, exact mobile reflow, text spacing, and 200 percent resize', async ({ page }) => {
    test.setTimeout(60_000);
    const unexpectedApiCalls: string[] = [];
    await routeTypographyPublicSpecimen(page, unexpectedApiCalls);

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/rides/preview-ride', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await expect(page.locator('main').getByText('CAL', { exact: true })).toHaveCount(0);
    await expect(page.locator('main').getByText('DUNG', { exact: true })).toHaveCount(0);

    const statusValue = page.locator('.ride-page-card-head b');
    const signInValue = page.locator('.ride-analysis-link button > span').last();
    const metricValue = page.locator('.ride-page-stats dd').first();
    await expect(statusValue).toBeVisible();
    await expect(signInValue).toBeVisible();
    await expect(metricValue).toBeVisible();

    const publicStyles = {
      status: await readTypographyStyle(statusValue),
      signIn: await readTypographyStyle(signInValue),
      metric: await readTypographyStyle(metricValue),
    };
    expectSansTypography(publicStyles.status);
    expectSansTypography(publicStyles.signIn);
    expectMonoTypography(publicStyles.metric);
    await captureTypographyPage(page, 'public-preview-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await captureTypographyPage(page, 'public-preview-mobile-390x844.png');

    await page.setViewportSize({ width: 720, height: 500 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureTypographyPage(page, 'public-preview-200-percent-equivalent-720x500.png');

    await page.setViewportSize({ width: 320, height: 720 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureTypographyPage(page, 'public-preview-reflow-320x720.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    await page.addStyleTag({
      content: `
        * {
          letter-spacing: 0.12em !important;
          line-height: 1.5 !important;
          word-spacing: 0.16em !important;
        }
        p {
          margin-bottom: 2em !important;
        }
      `,
    });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureTypographyPage(page, 'public-preview-wcag-text-spacing-390x844.png');

    const measurementPath = typographyCapturePath('public-preview-computed-styles.json');
    if (measurementPath) {
      fs.writeFileSync(measurementPath, `${JSON.stringify(publicStyles, null, 2)}\n`);
    }
    expect(unexpectedApiCalls, 'public typography specimen unexpected API calls').toEqual([]);
  });

  test('keeps the public preview legible with remote fonts blocked on a cold page', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await page.route('https://fonts.googleapis.com/**', (route) => route.abort());
    await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
    await routeTypographyPublicSpecimen(page, unexpectedApiCalls);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/rides/preview-ride', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Shawmont Morning' })).toBeVisible();
    const statusStyle = await readTypographyStyle(
      page.locator('.ride-page-card-head b'),
    );
    expectSansTypography(statusStyle);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureTypographyPage(page, 'public-preview-font-blocked-mobile-390x844.png');
    expect(unexpectedApiCalls, 'font-blocked public typography specimen unexpected API calls').toEqual([]);
  });

  test('captures authenticated UI, object, data, error, and admin chart typography', async ({ page }) => {
    test.setTimeout(120_000);
    const unexpectedApiCalls: string[] = [];
    const measurements: Record<string, unknown> = {};

    await page.addInitScript(() => {
      try {
        localStorage.setItem('br_authenticated', 'true');
        localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
        localStorage.setItem('boulder-roller-dark-mode', 'false');
        localStorage.removeItem('br_auth_handoff_pending');
      } catch {
        // Cross-origin auth iframes can deny storage access before app boot.
      }
      (window as Window & { ethereum?: unknown }).ethereum = {
        request: async () => [],
        on: () => {},
        removeListener: () => {},
      };
    });
    await routePortalApi(page, unexpectedApiCalls, {
      darkMode: false,
      isAdmin: true,
      withClimbViewSpecimen: true,
    });
    await routeTypographyAdminSpecimen(page);
    await page.route('**/rides/upload/init', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            error: 'duplicate_file',
            existing_ride_id: 'ride-1',
          },
        }),
      });
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-shell__header')).toBeVisible();
    const accountButton = page.getByRole('button', { name: /Open account menu for/ });
    await accountButton.click();
    const menuItem = page.locator('.portal-shell-popover__menu-item').first();
    await expect(menuItem).toBeVisible();
    const menuItemStyle = await readTypographyStyle(menuItem);
    expectSansTypography(menuItemStyle);
    expect(parseFloat(menuItemStyle.lineHeight)).toBeGreaterThanOrEqual(16);
    measurements.accountMenuItem = menuItemStyle;
    await captureTypographyPage(page, 'app-feed-account-popover-desktop-1440x1000.png');

    await accountButton.click();
    await page.getByRole('button', { name: 'Open notifications' }).click();
    const viewAll = page.locator('.portal-shell-popover__view-all');
    await expect(viewAll).toBeVisible();
    const viewAllStyle = await readTypographyStyle(viewAll);
    expectSansTypography(viewAllStyle);
    expect(parseFloat(viewAllStyle.lineHeight)).toBeGreaterThanOrEqual(16);
    measurements.notificationsViewAll = viewAllStyle;
    await captureTypographyPage(page, 'app-feed-notifications-popover-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: /Open account menu for/ }).click();
    await expect(page.locator('.portal-shell-popover--account')).toBeVisible();
    await captureTypographyPage(page, 'app-feed-account-popover-mobile-390x844.png');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/data', { waitUntil: 'domcontentloaded' });
    // Training is figures on paper (2026-09-03): its words are row labels, not body copy.
    const trainingCopy = page.locator('.training-row__label').first();
    await expect(trainingCopy).toBeVisible();
    await expect(page.locator('.ledger-slot')).toHaveCount(0);
    await expect(trainingCopy).toHaveCSS('font-family', /Geist/);
    const trainingCopyStyle = await readTypographyStyle(trainingCopy);
    expectSansTypography(trainingCopyStyle);
    expect(trainingCopyStyle.fontSize).toBe('14px');
    measurements.trainingCopy = trainingCopyStyle;
    await captureTypographyPage(page, 'data-body-copy-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.training-row__label').first()).toBeVisible();
    await captureTypographyPage(page, 'data-body-copy-mobile-390x844.png');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/climbs/climb-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Full Stack Smoke 1776366970' })).toBeVisible();
    await page.waitForTimeout(500);
    const climbCount = page.locator('.climb-result-value').first();
    const climbCountLabel = page.locator('.climb-result-rider strong').first();
    await expect(climbCount).toBeVisible();
    const climbCountStyle = await readTypographyStyle(climbCount);
    const climbCountLabelStyle = await readTypographyStyle(climbCountLabel);
    expectMonoTypography(climbCountStyle);
    expectSansTypography(climbCountLabelStyle);
    expect(climbCountStyle.fontSize).toBe('15px');
    expect(climbCountLabelStyle.fontSize).toBe('14px');
    measurements.climbCount = climbCountStyle;
    measurements.climbCountLabel = climbCountLabelStyle;
    await captureTypographyPage(page, 'climb-object-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.climb-result-value').first()).toBeVisible();
    await page.waitForTimeout(500);
    await captureTypographyPage(page, 'climb-object-mobile-390x844.png');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/activities/ride-1', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await expect(page.locator('.ride-map[data-route-ready="true"]')).toBeVisible();
    await page.waitForTimeout(1_000);
    const rideOverviewValue = page.locator('.ride-page-card .ride-page-stats dd').first();
    const rideOverviewStyle = await readTypographyStyle(rideOverviewValue);
    expectMonoTypography(rideOverviewStyle);
    measurements.ridePageMonoTrio = rideOverviewStyle;
    await captureTypographyPage(page, 'ride-page-mono-trio-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Morning Ride' })).toBeVisible();
    await expect(page.locator('.ride-map[data-route-ready="true"]')).toBeVisible();
    await page.waitForTimeout(800);
    await captureTypographyPage(page, 'ride-page-mono-trio-mobile-390x844.png');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/upload', { waitUntil: 'domcontentloaded' });
    await page.locator('input[type="file"]').setInputFiles({
      name: 'duplicate-ride.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Duplicate ride</name></trk></gpx>'),
    });
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Upload ride' }).click();
    const uploadErrorDetail = page.locator('.upload-activity-modal-error-detail');
    await expect(uploadErrorDetail).toHaveText('Open the ride already in your log.');
    const uploadErrorStyle = await readTypographyStyle(uploadErrorDetail);
    expectSansTypography(uploadErrorStyle);
    expect(uploadErrorStyle.fontSize).toBe('13px');
    expect(uploadErrorStyle.fontWeight).toBe('400');
    expect(parseFloat(uploadErrorStyle.lineHeight)).toBe(18);
    measurements.uploadErrorDetail = uploadErrorStyle;
    await captureTypographyPage(page, 'upload-error-copy-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await captureTypographyPage(page, 'upload-error-copy-mobile-390x844.png');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.portal-page-hero__title')).toHaveText('Admin');
    await page.getByRole('button', { name: /Scoring/ }).click();
    await expect(page.locator('.admin-v2-pipeline__stage')).toHaveCount(4);
    const startDelta = page.locator('.admin-v2-pipeline__stage-delta--sans');
    const numericDelta = page.locator('.admin-v2-pipeline__stage-delta--mono').first();
    const startDeltaStyle = await readTypographyStyle(startDelta);
    const numericDeltaStyle = await readTypographyStyle(numericDelta);
    expectSansTypography(startDeltaStyle);
    expectMonoTypography(numericDeltaStyle);
    measurements.pipelineStart = startDeltaStyle;
    measurements.pipelineDelta = numericDeltaStyle;
    await captureTypographyLocator(page.locator('.admin-v2-pipeline-panel'), 'admin-pipeline-desktop-1440x1000.png');

    await page.locator('.admin-v2-scoring-table__row').first().click();
    const elevationProfile = page.locator('.admin-v2-elevation-profile');
    const gpdFit = page.locator('.admin-v2-gpd-fit');
    await expect(elevationProfile).toBeVisible();
    await expect(gpdFit).toBeVisible();
    await expect(elevationProfile.locator('svg').first()).toBeVisible();
    await expect(gpdFit.locator('svg').first()).toBeVisible();
    await captureTypographyLocator(elevationProfile, 'admin-elevation-chart-desktop-1440x1000.png');
    await captureTypographyLocator(gpdFit, 'admin-gpd-chart-desktop-1440x1000.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: /Scoring/ }).click();
    await expect(page.locator('.admin-v2-pipeline__stage')).toHaveCount(4);
    await captureTypographyLocator(page.locator('.admin-v2-pipeline-panel'), 'admin-pipeline-mobile-390x844.png');
    await page.locator('.admin-v2-scoring-table__row').first().click();
    await expect(page.locator('.admin-v2-elevation-profile')).toBeVisible();
    await expect(page.locator('.admin-v2-gpd-fit')).toBeVisible();
    await captureTypographyLocator(page.locator('.admin-v2-elevation-profile'), 'admin-elevation-chart-mobile-390x844.png');
    await captureTypographyLocator(page.locator('.admin-v2-gpd-fit'), 'admin-gpd-chart-mobile-390x844.png');

    const measurementPath = typographyCapturePath('authenticated-computed-styles.json');
    if (measurementPath) {
      fs.writeFileSync(measurementPath, `${JSON.stringify(measurements, null, 2)}\n`);
    }
    expect(unexpectedApiCalls, 'authenticated typography specimen unexpected API calls').toEqual([]);
  });
});


test('Night Ledger public-place guidance stays readable above cartography', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], { darkMode: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.goto('/climbs');
    const guidance = page.getByText('Search public places only. Do not enter personal or confidential information.', { exact: true });
    await expect(guidance).toBeVisible();
    const colors = await guidance.evaluate(el => {
      const style = getComputedStyle(el);
      return { foreground: style.color, background: style.backgroundColor };
    });
    const channels = (color: string) => (color.match(/[\d.]+/g) ?? []).map(Number);
    const foreground = channels(colors.foreground);
    const background = channels(colors.background);
    expect(background[3] ?? 1, 'guidance has its own opaque background').toBe(1);
    const luminance = (rgb: number[]) => rgb.slice(0, 3).map(value => {
      const linear = value / 255;
      return linear <= 0.04045 ? linear / 12.92 : ((linear + 0.055) / 1.055) ** 2.4;
    }).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    const light = luminance(foreground); const dark = luminance(background);
    expect((Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05)).toBeGreaterThanOrEqual(4.5);
    await expect(page.getByRole('searchbox', { name: 'Search places', exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`map-guidance-${width}.png`), animations: 'disabled' });
  }
});

test.describe('Training audit recovery', () => {
  test.use({ hasTouch: true });
  test('retains last-loaded figures after a failed refresh and keeps the other read usable', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    await page.clock.install();
    await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
    const options: RouteFixtureOptions = { darkMode: true, withTrainingFigures: true };
    await routePortalApi(page, unexpectedApiCalls, options);
    await page.goto('/profile?tab=training');
    const calendar = page.locator('.training-consistency');
    const power = page.locator('.training-power');
    await expect(calendar.getByRole('slider')).toBeVisible();
    await expect(power.getByRole('slider')).toBeVisible();
    options.trainingFiguresFail = true;
    await page.clock.fastForward(61_000);
    await page.getByRole('tab', { name: 'Rides', exact: true }).click();
    await page.getByRole('tab', { name: 'Training', exact: true }).click();
    await expect(calendar.getByRole('alert')).toContainText('Last loaded');
    await expect(power.getByRole('alert')).toContainText('Last loaded');
    await expect(calendar.getByRole('slider')).toBeVisible();
    await expect(power.getByRole('slider')).toBeVisible();
    await calendar.getByRole('button', { name: 'Load', exact: true }).click();
    await expect(calendar.getByRole('alert')).toHaveCount(0);
    await expect(calendar.getByRole('slider')).toBeVisible();
    await expect(power.getByRole('alert')).toBeVisible();
    expect(unexpectedApiCalls).toEqual([]);
  });

  test('keeps pending figures truthful and offers scoped retries with keyboard values', async ({ page }) => {
    const unexpectedApiCalls: string[] = [];
    const requests: string[] = [];
    await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
    const options: RouteFixtureOptions = { darkMode: true, withTrainingFigures: true, trainingFiguresFail: true, trainingDelayMs: 600 };
    await routePortalApi(page, unexpectedApiCalls, options);
    page.on('request', request => { if (request.url().includes('/analytics/')) requests.push(new URL(request.url()).pathname); });
    await page.goto('/profile?tab=training&window=year&read=time');
    const load = page.locator('.training-load');
    const calendar = page.locator('.training-consistency');
    const power = page.locator('.training-power');
    await expect(power.locator('.training-sheet__meta [data-slot]')).toBeVisible();
    await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-live', 'true');
    await expect(page.getByText(/Upload rides with power|Upload rides with effort/)).toHaveCount(0);
    await expect(calendar.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(power.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(load.getByText('Could not load riding days.', { exact: true })).toBeVisible();
    options.trainingFiguresFail = false;
    const beforeRetry = requests.length;
    await power.getByRole('button', { name: 'Try again' }).click();
    await expect(power).toHaveAttribute('aria-busy', 'true');
    await expect(power.getByRole('status')).toHaveText('Loading');
    await expect(power.getByRole('slider', { name: 'Power curve duration' })).toBeVisible();
    expect(requests.slice(beforeRetry)).toEqual(['/api/analytics/power-curve']);
    await expect(calendar.getByRole('button', { name: 'Try again' })).toBeVisible();
    await calendar.getByRole('button', { name: 'Try again' }).click();
    const day = calendar.getByRole('slider', { name: 'Riding consistency day' });
    await expect(day).toBeVisible();
    await day.focus();
    await expect(day).toHaveAttribute('aria-valuetext', /2026-05-05.*1:30:00/);
    await day.press('ArrowLeft');
    await expect(day).toHaveAttribute('aria-valuetext', /2026-05-04.*1:00:00/);
    const duration = power.getByRole('slider', { name: 'Power curve duration' });
    await duration.focus();
    await duration.press('Home');
    await expect(duration).toHaveAttribute('aria-valuetext', /700 W/);
    await duration.press('End');
    await expect(duration).toHaveAttribute('aria-valuetext', /230 W/);
    await expect(load.getByRole('button', { name: 'Year', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(load.getByRole('button', { name: 'Time', exact: true })).toHaveAttribute('aria-pressed', 'true');
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await expect(duration).toBeVisible();
      await expect(day).toBeVisible();
      const tickBounds = await load.locator('svg text[text-anchor="middle"]').evaluateAll((ticks) => ticks.map((tick) => { const box = tick.getBoundingClientRect(); return { left: box.left, right: box.right }; }));
      for (let i = 1; i < tickBounds.length; i += 1) expect(tickBounds[i].left).toBeGreaterThanOrEqual(tickBounds[i - 1].right);
      await duration.tap({ position: { x: 90, y: 80 } });
      await expect(duration).not.toHaveAttribute('aria-valuetext', /230 W/);
      await day.tap({ position: { x: 35, y: 30 } });
      await expect(day).toHaveAttribute('aria-valuetext', /^20[0-9]{2}-[0-9]{2}-[0-9]{2} · /);
      await day.focus();
      await day.press('End');
      await expect(calendar.locator('.training-chart__readout')).toHaveText('2026-05-05 · 1:30:00 · 1 ride');
      await page.evaluate(() => window.scrollTo(0, 0));
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
      await page.screenshot({ path: `test-results/training-audit-${width}.png`, fullPage: true });
    }
    expect(unexpectedApiCalls).toEqual([]);
  });
});

// 24xry.22: the ratified overview door owns navigation into the separate instrument page.
async function routeRideServerPower(page: Page, metrics: Record<string, unknown>, unexpected: string[]) {
  const effortId = '11111111-1111-4111-8111-111111111111';
  page.on('request', request => {
    if (new URL(request.url()).pathname.includes('/climbs/efforts/')) unexpected.push(request.url());
  });
  await page.route('**/rides/ride-1/patterns', route => {
    const response = responseFor(new URL(route.request().url()), 'GET', { darkMode: false }) as {
      patterns: { climb_patterns: Array<Record<string, unknown>> };
    };
    response.patterns.climb_patterns[0].id = effortId;
    Object.assign(response.patterns.climb_patterns[0], metrics);
    return route.fulfill({ json: response });
  });
}

test('Ride page opens its own analysis page with synchronized instruments and no effort reads', async ({ page }) => {
  const unexpectedApiCalls: string[] = [];
  await page.addInitScript(() => {
    localStorage.setItem('br_authenticated', 'true');
    localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
    localStorage.setItem('boulder-roller-dark-mode', 'false');
    (window as Window & { ethereum?: unknown }).ethereum = { request: async () => [], on: () => {}, removeListener: () => {} };
  });
  await routePortalApi(page, unexpectedApiCalls, { darkMode: false });
  await routeRideServerPower(page, { power_kind: 'measured', avg_power_w: 324, w_per_kg: 4.32 }, unexpectedApiCalls);
  // The existing threshold assertion needs the current server-owned training read.
  const training = { engine_version: 2, threshold: { value: 251, estimate: true, basis: 'threshold_cp_3_7_15_v1', range: [238, 264] } };
  await page.route('**/api/rides/ride-1', route => route.fulfill({ json: ride('ride-1', 0, 'Morning Ride', 42195, 540, 88, { training_metrics: training }) }));
  await page.route('**/api/rides/ride-1/training?*', route => route.fulfill({ json: training }));
  // Overview power uses the server pattern projection; analysis still reads the stream.
  let releasePower!:()=>void;
  const powerGate=new Promise<void>(resolve=>{releasePower=resolve;});
  await page.route('**/rides/ride-1/streams?type=power', async route => { await powerGate; return route.fulfill({ json: {
    id: 'power-dense', ride_id: 'ride-1', stream_type: 'power',
    timestamps: Array.from({length:43},(_,i)=>i*30),
    values: Array.from({length:43},(_,i)=>100+i*5), sample_count:43,
  } }); });
  await page.goto('/activities/ride-1');
  await expect(page.locator('.ride-page-geography')).toBeVisible();
  await expect(page.locator('.ride-page-card')).toContainText('Morning Ride');
  await expect(page.locator('.ride-page-card')).toContainText('1 kudos');
  await expect(page.locator('.ride-page-geography .ride-instruments')).toHaveCount(0);
  await expect(page.locator('.ride-map')).toHaveAttribute('data-route-ready','true');
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  await page.locator('.ride-map canvas').evaluate(el=>el.setAttribute('data-mount-witness','rider-zoom'));
  releasePower();
  await page.getByRole('button', { name: 'Power', exact: true }).click();
  await expect(page.locator('.ride-page-row-value').first()).toContainText('⚡ 324 W');
  await expect(page.locator('.ride-page-row-value').first()).toContainText('4.32 W/kg');
  await expect(page.locator('.ride-map canvas')).toHaveAttribute('data-mount-witness','rider-zoom');
  await page.getByRole('link', { name: 'Ride analysis', exact: true }).click();
  await expect(page).toHaveURL(/\/activities\/ride-1\/analysis$/);
  await expect(page.getByRole('heading', { name: 'Ride analysis', exact: true })).toBeVisible();
  await expect(page.locator('.ride-instrument')).toHaveCount(5);
  await expect(page.getByRole('button', { name: 'Whole ride', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.ride-analysis-threshold')).toContainText('Threshold');
  expect((await page.locator('.ride-instrument').first().boundingBox())!.height).toBeCloseTo(132, 0);
  await expect(page.locator('.ride-instrument-axis [data-minor-tick]')).not.toHaveCount(0);
  const scrub = page.getByRole('slider', { name: 'Ride analysis scrub' });
  await scrub.focus();
  await page.keyboard.press('Home');
  await page.getByRole('button', { name: 'Analyze selected', exact: true }).click();
  await scrub.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.getByRole('button', { name: 'Analyze selected', exact: true }).click();
  await expect(page.locator('.ride-analysis-stats')).toHaveAttribute('data-range-start', '0');
  await expect(page.locator('.ride-analysis-stats')).toHaveAttribute('data-range-end', '2');
  await page.getByRole('button', { name: 'Clear range', exact: true }).click();
  expect(unexpectedApiCalls).toEqual([]);
});

for (const width of [1440, 390]) test(`Ride page climb estimate opens independently of its row at ${width}`, async ({ page }) => {
  const unexpected: string[] = [];
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, unexpected, { darkMode: false });
  await routeRideServerPower(page, { power_kind: 'estimated', estimated_power_w: 278, estimated_power_range_w: [250, 310] }, unexpected);
  await page.goto('/activities/ride-1');
  const ledger = page.locator('.ride-page-ledger');
  await expect(ledger.getByRole('button', { name: 'Estimated 278 watts' })).toBeVisible();
  await expect(ledger.locator('a button')).toHaveCount(0);
  await ledger.getByRole('button', { name: 'Estimated 278 watts' }).focus();
  await expect(page.getByRole('dialog', { name: 'Estimated 278 watts' })).toContainText('250–310 W');
  await expect(page).toHaveURL(/\/activities\/ride-1$/);
  await page.keyboard.press('Escape');
  if (width === 1440) {
    const band = page.locator('.ride-band-name');
    await expect(band.getByRole('button', { name: 'Estimated 278 watts' })).toBeVisible();
    await band.getByRole('button', { name: 'Estimated 278 watts' }).focus();
    await expect(page.getByRole('dialog', { name: 'Estimated 278 watts' })).toContainText('250–310 W');
    await page.keyboard.press('Escape');
  }
  expect(unexpected).toEqual([]);
});

test('Ride page social footer follows kudos and comment API results', async ({ page }) => {
  const unexpected: string[] = [], errors: string[] = [];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('br_authenticated','true'));
  await routePortalApi(page, unexpected, {});
  let kudos=false, added=false;
  await page.route('**/rides/ride-public/interactions',route=>route.fulfill({json:{ride_id:'ride-public',kudos_count:kudos?2:1,comment_count:added?2:1,viewer_has_kudos:kudos,comments_enabled:true,can_comment:true}}));
  await page.route('**/rides/ride-public/kudos',route=>{kudos=route.request().method()==='POST';return route.fulfill({json:{status:'ok'}});});
  await page.route('**/rides/ride-public/comments',route=>{
    if(route.request().method()!=='POST')return route.fallback();
    added=true;return route.fulfill({json:{id:'comment-new',user_id:'user-test-1',content:'Ride page comment fixture.',created_at:iso(1)}});
  });
  await page.route('**/rides/ride-public/comments/comment-new',route=>{added=false;return route.fulfill({json:{status:'ok'}});});
  await page.goto('/activities/ride-public');
  const footer=page.locator('.ride-page-social-footer'),kudosButton=page.locator('#ride-social button').filter({hasText:'Give kudos'});
  await expect(footer).toContainText('1 kudos');
  await kudosButton.click();
  await expect(footer).toContainText('2 kudos');
  await expect(kudosButton).toHaveAttribute('aria-pressed','true');
  await kudosButton.click();
  await expect(footer).toContainText('1 kudos');
  await expect(kudosButton).toHaveAttribute('aria-pressed','false');
  await page.getByPlaceholder('Add a comment...').fill('Ride page comment fixture.');
  await page.getByRole('button',{name:'Post comment',exact:true}).click();
  await expect(footer.getByRole('button',{name:'Comments',exact:true})).toHaveText('2');
  await page.getByRole('button',{name:'Delete comment',exact:true}).click();
  await expect(footer.getByRole('button',{name:'Comments',exact:true})).toHaveText('1');
  await expect(page.getByText('Ride page comment fixture.',{exact:true})).toHaveCount(0);
  expect(errors).toEqual([]);expect(unexpected).toEqual([]);
});

test('Ride analysis displays backend boundaries, moving clock and curve unchanged', () => {
  const read = trainingRead({movingS:0, powerCurveS:[5], powerCurveW:[260],
    powerZoneS:[1,1,0,0,0,0,0], powerZoneRangesW:[[0,145],[146,198]],
    powerZoneTotalS:2, powerZonePct:[50,50,0,0,0,0,0]});
  expect(read.moving).toBe(0);
  expect(read.zones?.ranges[1][0]).toBe(146);
  expect(read.curve).toEqual([260]);
  expect(trainingRead(null).zones).toBeNull();
});

test('Ride page validation renders and phone grip preserve the ratified split', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const fixture=JSON.parse(gunzipSync(fs.readFileSync(path.resolve('../../history/ride-room-2026-09-05/build/capture-fixture.json.gz'))).toString());
  const output=process.env.BR_CAPTURE_RIDE_PAGE_DIR ?? testInfo.outputPath('ride-page');
  fs.mkdirSync(output,{recursive:true});
  const unexpected:string[]=[],errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{localStorage.setItem('br_authenticated','true');localStorage.setItem('boulder-roller-theme-id','hoo-breddin');localStorage.setItem('boulder-roller-dark-mode','true');});
  await routePortalApi(page,unexpected,{darkMode:true});
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),pathname=url.pathname.replace(/^\/api/,'');let body:unknown;
    if(pathname==='/rides/ride-1')body=fixture.ride;
    else if(pathname==='/rides/ride-1/gps')body=fixture.gps;
    else if(pathname==='/rides/ride-1/patterns')body=fixture.patterns;
    else if(pathname==='/rides/ride-1/status')body={contract_version:'client.v1',truth_source:'backend',ride_id:'ride-1',status:'finalized',cal_earned:84,metrics:{distance_m:128730,elevation_gain_m:1013,duration_sec:18727,avg_power_w:188}};
    else if(pathname==='/rides/ride-1/streams'){const kind=url.searchParams.get('type')||'power',stream=fixture.streams[kind]??{timestamps:[],values:[]};body={...stream,id:`capture-${kind}`,ride_id:'ride-1',stream_type:kind,sample_count:stream.values.length};}
    else if(pathname==='/users/me/threshold')body={contract_version:'threshold.v1',state:'established',current_w:265};
    else if(pathname==='/status')body={environment:'test',solana_stub_mode:false,version:'fixture'};
    else return route.fallback();
    await route.fulfill({json:body});
  });
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:width===390?844:1000});
    await page.goto('/activities/ride-1');
    await expect(page.getByRole('heading',{name:'In the bag'})).toBeVisible();
    await expect(page.locator('.ride-map')).toHaveAttribute('data-route-ready','true');
    await expect(page.locator('.ride-page-card')).toContainText('128.7 km');
    await expect(page.locator('.ride-page-climbs a')).toHaveCount(3);
    await page.screenshot({path:path.join(output,`ride-page-${width}-reading.png`),fullPage:width===1440});
    const grip=page.getByRole('slider',{name:'Ride route and elevation'}),box=await grip.boundingBox();expect(box).not.toBeNull();
    await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2);await page.mouse.down();await page.mouse.move(box!.x+box!.width/2,box!.y+(width===390?320:260),{steps:12});await page.mouse.up();
    await expect(grip).toHaveAttribute('aria-valuenow',width===390?'150':/9[0-9][0-9]/);
    await page.screenshot({path:path.join(output,`ride-page-${width}-looking.png`),fullPage:width===1440});
    await grip.focus();await page.keyboard.press(width===390?'End':'Home');
    await page.getByRole('link',{name:'Ride analysis',exact:true}).click();
    await expect(page.locator('.ride-instrument')).toHaveCount(4);
    await expect(page.locator('.ride-analysis-threshold')).toHaveText('Threshold 265 W');
    await expect(page.locator('.ride-analysis-table').first().locator('tbody tr').first().locator('td').nth(1)).not.toHaveText('—');
    await page.screenshot({path:path.join(output,`ride-analysis-${width}-whole.png`),fullPage:true});
    await page.getByRole('button',{name:'Wises Mill Road',exact:true}).click();
    await expect(page.locator('.ride-analysis-stats')).toContainText('3:55');
    await expect(page.locator('.ride-instrument-axis')).toContainText('DISTANCE · M');
    await page.screenshot({path:path.join(output,`ride-analysis-${width}-wises-mill.png`),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth)).toBeLessThanOrEqual(0);
  }
  expect(errors).toEqual([]);expect(unexpected).toEqual([]);
});

test.describe('Ratified browser tab grammar', () => {
  test('titles follow loaded objects, URL pages and sheets without changing shell headings', async ({ page }) => {
    test.setTimeout(90_000);
    await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
    await routePortalApi(page, [], { darkMode: true, withCanonVaultCreationSpecimen: true });
    for (const [url, title] of [
      ['/', 'Feed'], ['/climbs', 'Map'],
      ['/climbs/climb-1', 'Manayunk Wall · Climb'],
      ['/activities/ride-1', 'Morning Ride · Ride'],
      ['/activities/ride-1/analysis', 'Morning Ride · Ride analysis'],
      ['/profile', 'Dung Beetle Phoenix · Profile'],
      ['/profile?tab=rides', 'Dung Beetle Phoenix · Rides'],
      ['/profile?tab=training', 'Dung Beetle Phoenix · Training'],
      ['/profile?tab=portfolio', 'Dung Beetle Phoenix · Portfolio'],
      ['/rider/tim', 'Tim Trail · Rider'], ['/docs', 'Guide'],
      ['/missing-page', 'Not found'], ['/?search=riders', 'Feed'],
    ]) {
      await page.goto(url);
      await expect(page).toHaveTitle(`${title} · Boulder Roller`);
    }
    await page.goto('/profile?tab=training');
    await expect(page).toHaveTitle('Dung Beetle Phoenix · Training · Boulder Roller');
    await page.getByRole('button', { name: 'Upload ride', exact: true }).first().click();
    await expect(page).toHaveTitle('Dung Beetle Phoenix · Training · Boulder Roller');
    await page.goto('/upload');
    await expect(page).toHaveTitle('Dung Beetle Phoenix · Rides · Boulder Roller');
  });

  test('preview and sign-in titles use the same grammar and head uses the source mark', async ({ page }) => {
    await routeTypographyPublicSpecimen(page, []);
    await page.goto('/rides/preview-ride');
    await expect(page).toHaveTitle('Shawmont Morning · Ride · Boulder Roller');
    await expect(page.locator('link[rel="icon"][type="image/svg+xml"]')).toHaveAttribute('href', '/favicon.svg');
    await expect(page.locator('meta[name="theme-color"]')).toHaveCount(1);
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0F0E0C');
    await page.goto('/');
    await expect(page).toHaveTitle('Sign in · Boulder Roller');
  });
});

test.describe('Portal pass chores', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
    await routePortalApi(page, [], { withTrainingFigures: true, withRideListShapes: true });
  });
  test('feed uses read-only ground', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.feed-route-band .ride-map').first()).toBeVisible();
    await expect(page.locator('.feed-route-band button')).toHaveCount(0);
    await expect(page.locator('.feed-route-band .ride-map').first()).toHaveAttribute('data-route-ready', 'true');
    await expect(page.locator('.feed-route-band .ride-map').first()).toHaveAttribute('data-ground-ready', 'true');
    await expect(page.locator('.feed-activity-card__user-button').first()).toHaveText('@dungbeetlephoenix');
    // The base style ships with the app; our basemap host serves the tiles, glyphs and sprite.
    await page.route(/^https:\/\/api\.boulderroller\.xyz\/basemap\//, route => route.fulfill({ status: 503, body: '' }));
    await page.reload();
    await expect(page.locator('.feed-route-band .ride-map').first()).toBeVisible();
    await expect(page.locator('.feed-route-band .ride-map-canvas').first()).toHaveCSS('opacity', '0');
  });
  test('own profile carries social counts', async ({ page }) => {
    await page.goto('/profile');
    await expect(page.locator('.profile-ledger__follows')).toHaveText('0 followers · 1 following');
    await page.route('**/social/followers/**', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
    await page.reload();
    await expect(page.locator('.profile-ledger__trio')).toBeVisible();
    // The shared owner viewer contract retains the row; absent counts do not become zero.
    await expect(page.locator('.profile-ledger__social')).toBeVisible();
    await expect(page.locator('.profile-ledger__follows')).toHaveCount(0);
  });
  test('phone consistency fits the latest weeks', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/profile?tab=training');
    const calendar = page.getByRole('slider', { name: 'Riding consistency day' });
    await expect(calendar).toBeVisible();
    await expect.poll(() => calendar.evaluate(el => el.getBoundingClientRect().width <= el.parentElement!.clientWidth)).toBe(true);
    await expect(calendar.locator('rect')).toHaveCount(26 * 7);
    await calendar.focus(); await calendar.press('End');
    await expect(calendar).toHaveAttribute('aria-valuetext', /2026-05-05/);
  });
  test('settings profile rows', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Home base/ })).toBeVisible();
    await expect(page.getByRole('textbox', { name: /Bio/ })).toHaveCSS('resize', 'none');
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Portal Pass Rider');
    expect(await page.getByRole('button', { name: 'Change photo', exact: true }).evaluate(el => getComputedStyle(el).color)).not.toBe(await page.getByRole('button', { name: 'Save', exact: true }).evaluate(el => getComputedStyle(el).color));
    const searches: unknown[] = [];
    page.on('request', request => { if (request.url().endsWith('/geocoding/search')) searches.push(request.postDataJSON()); });
    await page.getByRole('button', { name: /^Home base/ }).click();
    expect(searches).toEqual([]);
    await page.getByRole('textbox', { name: 'Search places', exact: true }).fill('Ma');
    await expect(page.getByRole('button', { name: 'Search places', exact: true })).toBeDisabled();
    await page.getByRole('textbox', { name: 'Search places', exact: true }).fill('Manayunk');
    await page.getByRole('button', { name: 'Search places', exact: true }).click();
    await page.getByRole('button', { name: 'Manayunk, Philadelphia, Pennsylvania, USA', exact: true }).click();
    await expect(page.getByRole('button', { name: /^Home base/ })).toContainText('Manayunk');
    await expect(page.getByRole('button', { name: /^Home base/ })).toBeFocused();
    expect(searches).toEqual([{ query: 'Manayunk' }]);
    const saved = page.waitForRequest(request => request.method() === 'PUT' && request.url().endsWith('/users/me'));
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    expect((await saved).postDataJSON()).toMatchObject({ display_name: 'Portal Pass Rider', location: 'Manayunk, Philadelphia, Pennsylvania, USA' });
  });
  test('map resize stays silent and attribution clears zoom', async ({ page }) => {
    await page.goto('/climbs');
    const attribution = page.locator('.climb-discovery-map-attribution');
    await expect(attribution).toBeVisible();
    const zoom = page.locator('.maplibregl-ctrl-zoom-in');
    await expect(zoom).toBeVisible();
    expect((await attribution.boundingBox())!.x + (await attribution.boundingBox())!.width).toBeLessThan((await zoom.boundingBox())!.x);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    await expect(page.getByRole('button', { name: 'Search this area', exact: true })).toBeHidden();
    await page.setViewportSize({ width: 1440, height: 1000 });
    const map = await page.locator('.maplibregl-canvas').boundingBox();
    await page.mouse.move(map!.x + map!.width * 0.75, map!.y + 200);
    await page.mouse.down();
    await page.mouse.move(map!.x + map!.width * 0.75 - 150, map!.y + 240, { steps: 12 });
    await page.mouse.up();
    await expect(page.getByRole('button', { name: 'Search this area', exact: true })).toBeVisible();
  });
  test('ride refit and absent tribute', async ({ page }) => {
    await page.goto('/activities/ride-1');
    await expect(page.getByRole('button', { name: 'Fit ride in map' }).locator('.lucide-expand')).toBeVisible();
    await expect(page.locator('.ride-page-kv').filter({ hasText: 'CAL tribute' })).toContainText('—');
    await page.setViewportSize({ width: 390, height: 844 });
    const grip = page.getByRole('slider', { name: 'Ride route and elevation' });
    await grip.focus(); await grip.press('End');
    await expect(page.getByRole('button', { name: 'Fit ride in map' })).toBeHidden();
    await expect(page.locator('.ride-map-attribution')).toBeVisible();
    await expect(page.locator('.ride-map-endpoint span').first()).toBeHidden();
    await grip.press('Home');
    await expect(page.locator('.ride-map-north')).toBeVisible();
  });
});

test('Portal pass rides search reaches the value edge', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], { withRideListShapes: true });
  await page.goto('/profile?tab=rides');
  await expect(page.getByRole('searchbox', { name: 'Search rides' })).toHaveCSS('text-align', 'right');
  const input = await page.getByRole('searchbox', { name: 'Search rides' }).boundingBox();
  const last = await page.locator('.rides-log__values button').last().boundingBox();
  expect(Math.abs(input!.x + input!.width - last!.x - last!.width)).toBeLessThanOrEqual(1);
});


test('Portal pass Portfolio truth appears once in each eyebrow', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], {});
  await page.goto('/profile?tab=portfolio');
  const wallet = page.getByLabel('Portfolio summary').locator('.profile-eyebrow');
  const positions = page.getByRole('region', { name: 'Positions', exact: true }).locator('.profile-eyebrow');
  await expect(wallet).toHaveText('Wallet · Current');
  await expect(positions).toHaveText('Positions · Current');
  await expect(wallet.locator('.portfolio-sheet__meta')).toHaveCount(1);
  await expect(positions.locator('.portfolio-sheet__meta')).toHaveCount(1);
  await expect(wallet.locator('.portfolio-sheet__meta')).toHaveCSS('text-transform', 'none');
  await expect(page.locator('.portfolio-page .portal-page-hero__status-footer, .portfolio-page .portal-truth-pill')).toHaveCount(0);
  await page.route('**/portfolio/snapshot?*', route => {
    const snapshot = responseFor(new URL(route.request().url()), 'GET', {}) as { freshness: { chain_status: string } };
    snapshot.freshness.chain_status = 'unavailable';
    return route.fulfill({ json: snapshot });
  });
  await page.reload();
  await expect(wallet).toHaveText('Wallet · Last loaded');
  await expect(positions).toHaveText('Positions · Current');
});

// 24xry.24: local fixture evidence, never production/rider proof.
test.describe('ratified page state evidence', () => {
  const pageCases = [
    { name: 'feed', route: '/', anatomy: '.feed-page', async: true },
    { name: 'map', route: '/climbs', anatomy: '.climbs-page__column', async: true },
    { name: 'climb', route: '/climbs/climb-1', anatomy: '.climb-page-ground', async: true },
    { name: 'ride', route: '/activities/ride-1', anatomy: '.ride-page-ground', async: true },
    { name: 'analysis', route: '/activities/ride-1/analysis', anatomy: '.ride-analysis-page', async: true },
    { name: 'profile', route: '/profile', anatomy: '.profile-ground', async: true },
    { name: 'rides', route: '/profile?tab=rides', anatomy: '.profile-ground', async: true },
    { name: 'training', route: '/profile?tab=training', anatomy: '.profile-ground', async: true },
    { name: 'portfolio', route: '/profile?tab=portfolio', anatomy: '.profile-ground', async: true },
    { name: 'settings', route: '/settings?tab=privacy', anatomy: '.settings-page', async: true },
    { name: 'notifications', route: '/notifications', anatomy: '.notifications-page', async: true },
    { name: 'guide', route: '/docs', anatomy: 'main', async: false },
    { name: 'search', route: '/?search=riders', anatomy: '.search-sheet', async: true },
    { name: 'upload', route: '/upload', anatomy: '.upload-sheet', async: true },
  ];
  for (const pageCase of pageCases) test(`${pageCase.name}: anatomy, slots, empty, failure and retained offline frames`, async ({ page }, testInfo) => {
    test.setTimeout(150_000);
    const output = process.env.BR_STATES_CAPTURE_DIR || testInfo.outputPath('states');
    fs.mkdirSync(output, { recursive: true });
    const errors: string[] = [];
    page.on('pageerror', error => { errors.push(error.message); console.error('Page runtime:', error.stack); });
    await page.addInitScript(() => { localStorage.setItem('br_authenticated', 'true'); localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin'); localStorage.setItem('boulder-roller-dark-mode', 'false'); });
    const options: RouteFixtureOptions = { darkMode: false, withTrainingFigures: true, withClimbViewSpecimen: true };
    await routePortalApi(page, [], options);
    let mode: 'loading' | 'settled' | 'empty' | 'failure' | 'not-found' = 'loading';
    let heldFeedRequests = 0;
    let heldLeaderboardRequests = 0;
    let release!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (pageCase.name === 'ride' && /\/src\/pages\/RideViewCore\.tsx$/.test(url.pathname) && mode === 'loading') await held;
      if (!['fetch', 'xhr'].includes(request.resourceType()) || !/\/api\/|api\.boulderroller/.test(url.href) || isGroundAsset(url) || /\/auth\/|\/me$|\/users\/me$/.test(url.pathname)) return route.fallback();
      if (mode === 'loading') {
        if (/\/feed\/home$/.test(url.pathname)) heldFeedRequests += 1;
        if (url.pathname.endsWith('/users/me/leaderboard-positions')) heldLeaderboardRequests += 1;
        await held;
      }
      if (mode === 'failure') return route.fulfill({ status: 500, json: { detail: 'server_error' } });
      if (mode === 'empty') {
        const fixture = responseFor(url, request.method(), /\/rides\/[^/]+$/.test(url.pathname) ? { ...options, rideListTotal: undefined } : options);
        if (fixture != null) {
          const empty = (value: unknown, key = ''): unknown => {
            if (Array.isArray(value)) return ['activities', 'rides', 'entries', 'leaderboard', 'notifications', 'stakes', 'positions', 'groups', 'receipts', 'efforts', 'distributions', 'achievements'].includes(key) ? [] : value.map(v => empty(v));
            if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, empty(v, k)]));
            if (['total', 'total_count', 'total_rides', 'totalCount', 'totalRides', 'unread_count', 'top10_count', 'kom_count'].includes(key)) return 0;
            if (key.endsWith('_base_units') || ['cal_balance', 'dung_balance', 'amount'].includes(key)) return '0';
            return value;
          };
          return route.fulfill({ json: empty(fixture) });
        }
      }
      return route.fallback();
    });
    const capture = async (state: string) => {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
        await page.waitForTimeout(400);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), `${pageCase.name}/${state}/${width} horizontal overflow`).toBeLessThanOrEqual(1);
        await page.screenshot({ path: path.join(output, `${pageCase.name}-${state}-${width}.png`) });
      }
    };
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(pageCase.route, { waitUntil: 'commit' });
    await page.waitForTimeout(1400);
    await expect(page.locator('.portal-shell__header').first()).toBeVisible();
    await expect(page.locator(pageCase.anatomy).first()).toBeVisible();
    if (pageCase.async) {
      await expect(page.locator('.ledger-slot').first()).toBeVisible();
      await expect(page.locator('.shell-live-rule').first()).toHaveAttribute('data-live', 'true');
    }
    if (pageCase.name === 'feed') {
      // Previously checked only a generic slot; the ratified feed still renders ten SlotRows while its home read is held.
      await expect.poll(() => heldFeedRequests).toBeGreaterThan(0);
      await expect(page.locator('.feed-page .ledger-slot-row')).toHaveCount(10);
      await expect(page.locator('.feed-page .ledger-slot-row .ledger-slot[data-slot=number]')).toHaveCount(10);
      await expect(page.getByText('No rides yet', { exact: true })).toHaveCount(0);
      // Loading rule 5 forbids absent dashes while the Seats/Crowns authority read is held.
      await expect.poll(() => heldLeaderboardRequests).toBeGreaterThan(0);
      await expect(page.locator('.feed-crown__trio .ledger-slot[data-slot=number]')).toHaveCount(2);
    }
    await expect(page.locator('.route-transition-skeleton, .loading-skeleton-feed-item, .section-loading-state, .lucide-loader-circle')).toHaveCount(0);
    await capture('loading');
    mode = 'settled'; release();
    await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 45_000 });
    await expect(page.locator('.shell-live-rule').first()).toHaveAttribute('data-live', 'false', { timeout: 40_000 });
    // The ratified feed band loads a map module after its data; retain a rendered map, not an unfinished import.
    if (pageCase.name === 'feed') await expect(page.locator('.feed-route-band .maplibregl-canvas').first()).toBeVisible();
    await page.context().setOffline(true);
    await expect(page.locator('.offline-pinned-row')).toHaveCount(1);
    await expect(page.locator('.shell-live-rule').first()).toHaveAttribute('data-offline', 'true');
    await expect(page.locator('.retained-page-content')).toHaveCSS('opacity', '0.55');
    await capture('offline');
    await page.context().setOffline(false);
    mode = 'empty'; options.rideListTotal = 0; options.profileRideTotal = 0; options.withTrainingFigures = false;
    await page.goto(pageCase.route);
    await expect(page.locator('.retained-page')).toBeVisible();
    await expect(page.locator('.app-boot-screen')).toHaveCount(0);
    await expect(page.locator('.shell-live-rule').first()).toHaveAttribute('data-live', 'false', { timeout: 40_000 });
    await expect(page.locator(pageCase.anatomy).first()).toBeVisible();
    await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 45_000 });
    await capture('empty');
    mode = 'failure';
    await page.goto(pageCase.route);
    await expect(page.locator('.retained-page')).toBeVisible();
    await expect(page.locator('.app-boot-screen')).toHaveCount(0);
    await expect(page.locator('.shell-live-rule').first()).toHaveAttribute('data-live', 'false', { timeout: 45_000 });
    await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 45_000 });
    await capture('failure');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('br:session-expired', { detail: { reason: 'token_expired' } })));
    await expect(page.getByRole('dialog', { name: 'Sign in', exact: true })).toBeVisible();
    await expect(page.getByText('Session has expired. Please sign in again.', { exact: true })).toBeVisible();
    await capture('session-expired');
    expect(errors).toEqual([]);
  });
});

async function assertFullPagePublicEntry(page: Page, destination: string) {
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('region', { name: 'Account entry', exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Email', exact: true })).toBeFocused();
  await expect(page.locator('.public-page, .sign-in-dialog-overlay, [role="dialog"]')).toHaveCount(0);
  expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBe(destination);
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('button', { name: 'Send code', exact: true })).toBeVisible();
}

test.describe('public state evidence', () => {
  for (const specimen of [
    { name: 'public-climb', route: '/climbs/preview-climb', anatomy: '.climb-page-ground' },
    { name: 'public-rider', route: '/riders/tim', anatomy: '.profile-ground' },
    { name: 'public-ride', route: '/rides/preview-ride', anatomy: '.ride-page-ground' },
  ]) test(`${specimen.name}: loading, empty, failure, offline and door`, async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    const out = process.env.BR_STATES_CAPTURE_DIR || testInfo.outputPath('states'); fs.mkdirSync(out, { recursive: true });
    if (specimen.name === 'public-ride') await routeTypographyPublicSpecimen(page, []);
    else await routeEyebrowPublicPreviewSpecimens(page, []);
    let previewFixture: Record<string, unknown> | null = null;
    // Capture the initial fixture once, before navigation can discard a response body.
    const previewResponse = page.waitForResponse(response => response.url().includes('/public/previews/') && response.status() === 200, { timeout: 60_000 });
    let mode: 'loading' | 'settled' | 'empty' | 'failure' | 'not-found' = 'loading';
    let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/public/previews/**', async route => {
      if (mode === 'loading') await held;
      if (mode === 'empty') {
        const empty = (value: unknown, key = ''): unknown => {
          if (['route_preview', 'elevation_profile'].includes(key)) return null;
          if (Array.isArray(value)) return ['entries', 'rides', 'positions', 'media', 'climbs'].includes(key) ? [] : value.map(v => empty(v));
          if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, empty(v, k)]));
          if (['total', 'total_rides', 'ride_count', 'top10_count', 'kom_count'].includes(key)) return 0;
          return value;
        };
        return route.fulfill({ json: empty(previewFixture) });
      }
      if (mode === 'failure') return route.fulfill({ status: 500, json: { detail: 'Preview unavailable' } });
      if (mode === 'not-found') return route.fulfill({ status: 404, json: { detail: 'not_found' } });
      return route.fallback();
    });
    const capture = async (state: string) => {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 }); await page.waitForTimeout(400);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await page.screenshot({ path: path.join(out, `${specimen.name}-${state}-${width}.png`) });
      }
    };
    await page.goto(specimen.route, { waitUntil: 'commit' }); await page.waitForTimeout(1400);
    await expect(page.locator(specimen.anatomy)).toBeVisible();
    await expect(page.locator('.ledger-slot').first()).toBeVisible();
    await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-live', 'true');
    await capture('loading'); mode = 'settled'; release();
    previewFixture = await (await previewResponse).json();
    await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 30_000 });
    await expect(page.locator(specimen.anatomy)).toBeVisible();
    await capture('settled');
    await page.context().setOffline(true);
    await expect(page.locator('.offline-pinned-row')).toHaveCount(1);
    await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-offline', 'true');
    await expect(page.locator('.retained-page-content')).toHaveCSS('opacity', '0.55');
    await capture('offline'); await page.context().setOffline(false);
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    // Previously pinned the three public-page dialogs; lane D replaces them with full-page entry and browser Back.
    await assertFullPagePublicEntry(page, specimen.route);
    await capture('door');
    await page.goBack();
    await expect(page).toHaveURL(specimen.route);
    await expect(page.locator(specimen.anatomy)).toBeVisible();
    mode = 'empty'; await page.goto(specimen.route);
    await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 30_000 });
    await expect(page.locator(specimen.anatomy)).toBeVisible(); await expect(page.locator('.ledger-slot')).toHaveCount(0, { timeout: 45_000 });
    if (specimen.name === 'public-rider') {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await expect(page.locator('.profile-ground canvas')).toBeVisible();
      expect((await page.locator('.profile-ground canvas').boundingBox())!.height).toBeGreaterThan(400);
      await expect(page.locator('.profile-ground .maplibregl-marker')).toHaveCount(0);
    }
    await capture('empty');
    mode = 'failure'; await page.goto(specimen.route);
    await expect(page.locator('.ledger-state-row')).toContainText('Preview unavailable', { timeout: 40_000 });
    await expect(page.locator(specimen.anatomy)).toBeVisible();
    await expect(page.locator('.ledger-slot')).toHaveCount(0); await capture('failure');
    mode = 'not-found'; await page.goto(specimen.route);
    await expect(page.locator('.failure-sheet')).toHaveCount(1, { timeout: 30_000 });
    await expect(page.locator('.portal-shell__header')).toHaveCount(1);
    await expect(page.locator('.ledger-slot')).toHaveCount(0); await capture('not-found');
  });
});

test('state timing: live rule waits 160ms, keeps 420ms, and reduced motion removes travel', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], {});
  await page.goto('/');
  await expect(page.locator('.feed-card__title').first()).toBeVisible();
  const rule = page.locator('.shell-live-rule');
  await expect(rule).toHaveAttribute('data-live', 'false');
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/feed/home?*', async route => {
    if (new URL(route.request().url()).searchParams.get('scope') === 'following') await held;
    return route.fallback();
  });
  const clockStart = new Date('2026-09-07T12:00:00Z');
  await page.clock.install({ time: clockStart });
  await page.clock.pauseAt(new Date(clockStart.getTime() + 10_000));
  await page.getByRole('button', { name: 'Following', exact: true }).click();
  await page.clock.runFor(159);
  await expect(rule).toHaveAttribute('data-live', 'false');
  await page.clock.runFor(1);
  await expect(rule).toHaveAttribute('data-live', 'true');
  await expect(rule).toHaveCSS('height', '2px');
  await expect(rule).toHaveCSS('bottom', '0px');
  const arrived = page.waitForResponse(response => response.url().includes('/feed/home?') && response.url().includes('following'));
  release(); await arrived;
  await page.clock.runFor(419);
  await expect(rule).toHaveAttribute('data-live', 'true');
  await page.clock.runFor(1);
  await expect(rule).toHaveAttribute('data-live', 'false');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await page.evaluate(() => ['--t-state', '--t-arrive', '--t-settle'].map(name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()))).toEqual(['0ms', '0ms', '0ms']);
});

test('state recovery: unknown route retains one shell and one sheet', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], {});
  await page.goto('/missing-page');
  await expect(page.locator('.portal-shell__header')).toHaveCount(1);
  await expect(page.locator('.failure-paper .failure-sheet')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Rides', exact: true }).last()).toHaveAttribute('href', '/profile?tab=rides');
  const out = process.env.BR_STATES_CAPTURE_DIR || testInfo.outputPath('states'); fs.mkdirSync(out, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.screenshot({ path: path.join(out, `route-not-found-${width}.png`) });
  }
});

test('state recovery: boot slots and crash sheet use the shared species', async ({ page }, testInfo) => {
  const out = process.env.BR_STATES_CAPTURE_DIR || testInfo.outputPath('states'); fs.mkdirSync(out, { recursive: true });
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await routePortalApi(page, [], {});
  let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/src/AuthenticatedApp.tsx*', async route => { await held; return route.fallback(); });
  await page.goto('/', { waitUntil: 'commit' });
  await expect(page.locator('.app-boot-screen .ledger-slot')).toBeVisible();
  await expect(page.locator('.app-boot-screen .shell-live-rule')).toHaveAttribute('data-live', 'true');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.screenshot({ path: path.join(out, `boot-loading-${width}.png`) });
  }
  release();
  await expect(page.locator('.feed-card__title').first()).toBeVisible();
  await page.route('**/src/pages/Settings.tsx*', route => route.fulfill({ contentType: 'application/javascript', body: 'export default function Settings() { throw new Error("Local crash fixture"); }' }));
  await page.goto('/settings');
  await expect(page.locator('.failure-sheet')).toHaveCount(1);
  await expect(page.locator('.portal-shell__header')).toHaveCount(1);
  await expect(page.locator('.failure-sheet .ledger-slot')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.screenshot({ path: path.join(out, `crash-failure-${width}.png`) });
  }
});

test('Balance rollout closed withdrawal deep link has no confirmation', async ({ page }) => {
  await routePortalApi(page, [], { withClimbViewSpecimen: true });
  await page.route('**/status', route => route.fulfill({ json: {} }));
  await page.goto('/climbs/climb-1?climbView=withdraw');
  await expect(page.getByText('Not open yet', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Hold to Withdraw/ })).toHaveCount(0);
});

for (const state of ['enabled', 'disabled', 'loading', 'error'] as const) {
  for (const width of [1440, 390]) test(`Balance rollout Vault ${state} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await routePortalApi(page, [], { withClimbViewSpecimen: true });
    const actions = ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'];
    await page.route('**/status', async route => {
      if (state === 'loading') return;
      if (state === 'error') return route.fulfill({ status: 503, json: {} });
      return route.fulfill({ json: { balanceRollout: { enforced: true, orderValid: true, blockers: [], actionOrder: actions, enabledActions: state === 'enabled' ? actions : actions.slice(0, 2) } } });
    });
    await page.goto('/climbs/climb-1?climbView=vault');
    const position = page.getByRole('region', { name: 'Your position', exact: true });
    await expect(position).toContainText('1,200 CAL');
    await expect(position.getByRole('link', { name: 'Deposit CAL', exact: true })).toBeVisible();
    if (state === 'enabled') await expect(position.getByRole('link', { name: 'Withdraw CAL', exact: true })).toBeVisible();
    else {
      await expect(position.getByRole('link', { name: 'Withdraw CAL', exact: true })).toHaveCount(0);
      await expect(position.getByRole('button', { name: 'Withdraw CAL Not open yet', exact: true })).toBeDisabled();
      const contrast = await position.locator('.climb-action-row:disabled').evaluate(row => {
        const luminance = (css: string) => css.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        const ink = luminance(getComputedStyle(row).color);
        const ground = luminance(getComputedStyle(row.closest('.climb-ledger-card')!).backgroundColor);
        return (Math.max(ink, ground) + .05) / (Math.min(ink, ground) + .05);
      });
      expect(contrast).toBeGreaterThanOrEqual(4.5);
    }
    if (state === 'enabled' || state === 'disabled') {
      await page.evaluate(() => document.fonts.ready);
      if (width === 390) await position.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.resolve(__dirname, `../../../history/balance-rollout-th6fs/vault-${state}-${width}.png`), fullPage: width === 1440 });
    }
    await page.goto('/climbs/climb-1?climbView=withdraw');
    if (state === 'enabled') await expect(page.getByRole('button', { name: /Hold to Withdraw/ })).toBeVisible();
    else {
      await expect(page.getByText('Not open yet', { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: /Hold to Withdraw/ })).toHaveCount(0);
    }
  });
}

test('Training v2 frozen reads render on desktop and phone', async ({page}, testInfo) => {
  test.setTimeout(90_000);
  const errors:string[]=[], unexpected:string[]=[];
  page.on('pageerror', e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('br_authenticated','true'));
  await routePortalApi(page,unexpected,{withTrainingFigures:true});
  const threshold={value:251,estimate:true,basis:'threshold_cp_3_7_15_v1',range:[238,264]};
  let snapshotEstimate = true;
  const captureDir = process.env.BR_ESTIMATE_MARK_RENDER_DIR;
  if (captureDir) fs.mkdirSync(captureDir, {recursive:true});
  const renderPath = (name: string) => captureDir ? path.join(captureDir, name) : testInfo.outputPath(name);
  const metadata={threshold_state:'estimated',threshold_training_state:null,threshold_version:'training.v2',
    training_available:true,training_threshold:threshold,estimate:true,basis:'stored_ride_loads'};
  const fitness={ctl:42,atl:58,tsb:-16,form:'Optimal',date:iso(0).slice(0,10),...metadata};
  const load={daily_loads:[{date:iso(0).slice(0,10),total_tss:81}],total_tss:81,avg_daily_tss:81/28,...metadata};
  const metrics={engine_version:2,elapsed_s:5400,recording_s:5300,moving_s:3210,load:81,load_estimate:true,
    threshold,estimates:{load:{value:81,estimate:true,basis:'power'}},avg_power_w:211,max_power_w:590,
    avg_speed_mps:6,max_speed_mps:12,avg_cadence_rpm:87,max_cadence_rpm:104,distance_m:42195,elevation_gain_m:540,
    power_curve_s:[5,60,180,420,900],power_curve_w:[590,380,350,293,270],
    power_zone_s:[600,1600,800,210,0,0,0],power_zone_ranges_w:[[0,138],[139,188],[189,225],[226,263],[264,301],[302,376],[377,null]],
    power_zone_total_s:3210,power_zone_pct:[18.69,49.84,24.92,6.54,0,0,0]};
  await page.route('**/api/analytics/power-curve*',r=>r.fulfill({json:{contractVersion:'power_curve.v1',
    durationsS:[5,60,180,420,900],bestW:[590,380,350,293,270],sampledRides:1,rideCount:1,available:true,
    threshold:{sealedW:null,candidateW:null,estimate:threshold,anchorsW:{'180':350,'420':293,'900':270}}}}));
  await page.route('**/api/analytics/fitness*',r=>r.fulfill({json:fitness}));
  await page.route('**/api/analytics/training-load*',r=>r.fulfill({json:{...load,snapshot:{revision:'synthetic-v2',
    as_of:iso(0),initialization:'initializing',estimate:snapshotEstimate,basis:'stored_ride_loads',
    coverage:{completeness:'partial',population:'1 / 3 rides',observed_count:1,expected_count:3,pending_count:1,unavailable_count:1},
    fitness_metrics:fitness,training_load:load}}}));
  await page.route('**/api/rides/ride-1',r=>r.fulfill({json:ride('ride-1',0,'Morning Ride',42195,540,88,{training_metrics:metrics})}));
  await page.route('**/api/rides/ride-1/patterns',r=>r.fulfill({json:{patterns:{climb_patterns:[{id:'climb-training',climb_id:'climb-1',
    name:'Full Stack Smoke',distance_m:2400,vert_m:192,avg_gradient_pct:8,duration_s:600,
    start_offset_s:0,end_offset_s:600,avg_power_w:244,w_per_kg:3.3,category:'3'}]}}}));
  let spanCalls=0;
  await page.route('**/api/rides/ride-1/training?*',r=>{spanCalls++;return r.fulfill({json:{...metrics,moving_s:137,elapsed_s:170,avg_power_w:244}});});
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    await page.goto('/data');
    // Tim's written stored_ride_loads pair makes each trio value open its card.
    const trio = page.locator('.training-trio');
    await expect(trio.getByRole('button')).toHaveCount(3);
    const fitness = trio.getByRole('button', {name:'Estimated 42', exact:true});
    await expect(fitness).toHaveText('≈42');
    await expect(trio.getByRole('button', {name:'Estimated 58', exact:true})).toHaveText('≈58');
    await expect(trio.getByRole('button', {name:'Estimated -16', exact:true})).toHaveText('≈-16');
    const numberStyle = await page.locator('.training-trio strong').first().evaluate(element => {
      const style = getComputedStyle(element);
      return {fontSize: style.fontSize};
    });
    await expect(fitness).toHaveCSS('font-size', numberStyle.fontSize);
    await fitness.click();
    const trioCard = page.getByRole('dialog', {name:'Estimated 42', exact:true});
    await expect(trioCard).toBeVisible();
    for (const line of estimateCopy.stored_ride_loads) await expect(trioCard).toContainText(line);
    await expect(trioCard).not.toContainText(/TIM:|stored_ride_loads/);
    await page.keyboard.press('Escape');
    await expect(trioCard).toHaveCount(0);
    if (width === 1440) {
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({path:renderPath('portal-no-range-1440.png')});
    }
    await expect(page.locator('.training-trio')).toContainText('Optimal');
    await expect(page.locator('.training-load__snapshot')).toHaveAttribute('data-completeness','partial');
    await expect(page.locator('.training-load__snapshot')).toContainText('1 / 3 rides');
    await expect(page.locator('.training-threshold').getByRole('button', {name:'Estimated 251 watts', exact:true})).toHaveText('≈251 W');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const trainingValue = page.locator('.training-threshold').getByRole('button', {name:'Estimated 251 watts',exact:true});
    await trainingValue.scrollIntoViewIfNeeded();
    expect(await trainingValue.evaluate(element => {
      const style = getComputedStyle(element);
      return [style.textDecorationLine, style.textDecorationStyle, style.textDecorationThickness];
    })).toEqual(['underline','dotted','1px']);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({path:renderPath(`training-${width}-closed.png`)});
    await trainingValue.click();
    const trainingCard = page.getByRole('dialog', {name:'Estimated 251 watts',exact:true});
    await expect(trainingCard).toBeVisible();
    await expect(trainingCard).toContainText('238–264 W');
    await expect(trainingCard).not.toContainText(/TIM:|threshold_cp/);
    const trainingBounds = (await trainingCard.boundingBox())!;
    expect(trainingBounds.x).toBeGreaterThanOrEqual(0);
    expect(trainingBounds.x + trainingBounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:renderPath(`training-${width}-open.png`)});
    await page.keyboard.press('Escape');
    await expect(trainingCard).toHaveCount(0);
    await page.goto('/activities/ride-1');
    await page.getByRole('group',{name:'Climb values'}).getByRole('button',{name:'Power',exact:true}).click();
    await expect(page.locator('.ride-page-climbs')).toContainText('244 W');
    await page.goto('/activities/ride-1/analysis');
    await expect(page.getByRole('heading',{name:'Ride analysis',exact:true})).toBeVisible();
    await expect(page.locator('.ride-metrics')).toContainText('53:30');
    await expect(page.locator('.ride-analysis-threshold').getByRole('button', {name:'Estimated 251 watts', exact:true})).toHaveText('≈251 W');
    await expect(page.locator('.ride-zones')).toContainText('139');
    const rideValue = page.locator('.ride-analysis-threshold').getByRole('button', {name:'Estimated 251 watts',exact:true});
    await rideValue.scrollIntoViewIfNeeded();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({path:renderPath(`ride-analysis-${width}-closed.png`)});
    await rideValue.click();
    const rideCard = page.getByRole('dialog', {name:'Estimated 251 watts',exact:true});
    await expect(rideCard).toBeVisible();
    await expect(rideCard).toContainText('238–264 W');
    const rideBounds = (await rideCard.boundingBox())!;
    expect(rideBounds.x).toBeGreaterThanOrEqual(0);
    expect(rideBounds.x + rideBounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:renderPath(`ride-analysis-${width}-open.png`)});
    await page.keyboard.press('Escape');
    await expect(rideCard).toHaveCount(0);
  }
  const chart=page.locator('.ride-instrument').first();
  await chart.scrollIntoViewIfNeeded();
  const bounds=await chart.boundingBox();
  expect(bounds).not.toBeNull();
  const callsBeforeDrag=spanCalls;
  await page.mouse.move(bounds!.x+bounds!.width*.2,bounds!.y+20);
  await page.mouse.down();
  await page.mouse.move(bounds!.x+bounds!.width*.8,bounds!.y+20,{steps:12});
  await expect(chart).toBeVisible();
  expect(spanCalls).toBe(callsBeforeDrag);
  await page.mouse.up();
  await expect.poll(()=>spanCalls).toBe(callsBeforeDrag+1);
  const scopeButtons=page.getByRole('group',{name:'Ride analysis scope'}).getByRole('button');
  expect(await scopeButtons.count()).toBeGreaterThan(1);
  {
    await scopeButtons.nth(1).click();
    await expect.poll(()=>spanCalls).toBeGreaterThan(0);
    await expect(page.locator('.ride-metrics')).toContainText('244');
  }
  snapshotEstimate = false;
  await page.goto('/data');
  await expect(page.locator('.training-trio strong')).toHaveText(['42','58','-16']);
  await expect(page.locator('.training-trio button')).toHaveCount(0);
  await expect(page.locator('.training-threshold button')).toHaveText('≈251 W');
  expect(errors).toEqual([]);
  expect(unexpected).toEqual([]);
});
