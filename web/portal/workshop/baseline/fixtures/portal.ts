// Exact fixture definitions from e2e/portal-v2-routes.spec.ts at a63ffc77f9638b78d3a404be2575aaa7ddd9c145 (lines 8-2268).
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
  { slug: 'analyze', path: '/activities/ride-1/analyze' },
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

export interface RouteFixtureOptions {
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

export function responseFor(
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
  if (path === '/status') return { environment: 'test', solana_stub_mode: true, version: 'fixture' };
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
        rider: { ...((publicRider as typeof publicRider & {rider?: object}).rider), viewer_relationship: 'following' },
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

  // Generic write success removed at the fixture boundary; unspecified mutations are unavailable.
  return undefined;
}


export {user,publicRider,rides,NOW,TEST_WALLET};
