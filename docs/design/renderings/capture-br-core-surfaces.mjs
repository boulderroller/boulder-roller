import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '../../..');
const portalDir = path.join(repoRoot, 'web/portal');
const outputDir = process.env.CAPTURE_OUTPUT_DIR
  ? path.resolve(repoRoot, process.env.CAPTURE_OUTPUT_DIR)
  : path.join(__dirname, 'current-captures/2026-05-12');
const capturePort = process.env.CAPTURE_PORT ?? '5173';
const baseUrl = `http://127.0.0.1:${capturePort}`;
const requireFromPortal = createRequire(path.join(portalDir, 'package.json'));
const { chromium } = requireFromPortal('playwright');

const NOW = new Date('2026-05-12T15:00:00Z');
const TEST_WALLET = '11111111111111111111111111111111';
const LONG_RIDER_WALLET = 'timwallet1111111111111111111111111111111';

function iso(daysAgo = 0) {
  return new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();
}

function isoOffset(daysAgo = 0, offsetS = 0) {
  return new Date(Date.parse(iso(daysAgo)) + offsetS * 1000).toISOString();
}

const user = {
  id: 'user-test-1',
  wallet: TEST_WALLET,
  username: 'dungbeetlephoenix',
  display_name: 'Dung Beetle Phoenix',
  beetle_id: 'BR-1542',
  beetle_number: 1542,
  bio: 'Portal V2 dogfood rider.',
  ftp_w: 265,
  weight_kg: 74,
  rider_type: 'puncheur',
  avatar_url: null,
  theme_id: 'hoo-breddin',
  is_dark_mode: false,
  is_public: true,
  created_at: iso(150),
  last_active_at: iso(0),
  total_rides: 3,
  total_distance_km: 91,
  total_elevation_m: 1650,
  total_dung_earned: 245,
  total_tss: 385,
  total_kcals: 3810,
  total_duration_sec: 13_200,
  current_streak: 2,
  longest_streak: 7,
  last_activity_date: iso(1),
};

function ride(id, daysAgo, title, distanceM = 42_195, elevationM = 540, calEarned = 88) {
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
    is_owner: true,
  };
}

const rides = [
  ride('ride-1', 1, 'Morning Ride', 48_200, 620, 96),
  ride('ride-2', 6, 'Bridge Repeats', 26_300, 910, 121),
  ride('ride-3', 18, 'Recovery Spin', 17_400, 120, 28),
];

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
  total_elevation_m: 8420,
  total_dung_earned: 1776,
  total_duration_sec: 42_600,
  follower_count: 3,
  following_count: 7,
  current_streak: 4,
  longest_streak: 11,
  last_activity_date: iso(1),
};

function vault(id, name, active = true) {
  return {
    id,
    signature_hex: `vault-signature-${id}`,
    signature_hash_hex: `vault-hash-${id}`,
    name,
    vert_m: 412 + id,
    distance_m: 3700 + id * 150,
    avg_gradient_pct: 7.4 + id * 0.1,
    total_completions: 42 + id,
    total_staked: 12_500 + id * 240,
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

function apiError(status, detail) {
  return { __api_error: true, status, detail };
}

function responseFor(url, method) {
  const pathName = url.pathname.replace(/^\/api/, '') || '/';

  if (pathName === '/auth/bootstrap') {
    return {
      authenticated: true,
      invite_required: false,
      invite_validated: true,
      needs_profile_setup: false,
      auth_method_hint: 'wallet',
      user,
    };
  }

  if (pathName === '/auth/onboarding/state') {
    return {
      authenticated: true,
      invite_required: false,
      invite_validated: true,
      needs_profile_setup: false,
      auth_method_hint: 'wallet',
    };
  }

  if (pathName === '/me' || pathName === '/users/me') return user;
  if (pathName === '/auth/refresh') return { access_token: 'fixture-token' };
  if (pathName === '/status') return { environment: 'test', solana_stub_mode: true, version: 'fixture' };
  if (pathName === '/strava/connection') return { connected: false };

  if (pathName === '/feed/global' || pathName === '/feed') {
    return {
      activities: rides.map((r) => ({
        id: `feed-${r.id}`,
        type: 'ride',
        title: r.title,
        created_at: r.started_at,
        occurred_at: r.started_at,
        user: { id: user.id, username: user.username, display_name: user.display_name, avatar_url: null },
        metadata: {
          distance_m: r.distance_m,
          elevation_m: r.elevation_m,
          duration_s: r.duration_s,
          cal_earned: r.cal_earned,
          kudos_count: 2,
          comment_count: 1,
        },
      })),
      has_more: false,
      next_cursor: null,
    };
  }

  if (pathName === '/social/suggested') {
    return {
      suggestions: [
        { id: 'rider-1', username: '@rider_56bff2', display_name: 'Rider 56', mutual_followers: 0, is_following: false },
        { id: 'rider-2', username: '@rider_d3eeca', display_name: 'Rider D3', mutual_followers: 1, is_following: false },
      ],
    };
  }

  if (pathName === '/climbs/popular') {
    return {
      climbs: [
        { id: 'climb-1', name: 'Full Stack Smoke 1776366970', location: 'Boulder', pot: 617, attempts: 3, completions: 3 },
        { id: 'climb-2', name: 'Full Stack Smoke 1776369548', location: 'Boulder', pot: 909, attempts: 2, completions: 2 },
      ],
    };
  }

  if (/^\/social\/followers\/[^/]+$/.test(pathName)) return [];
  if (/^\/social\/following\/[^/]+$/.test(pathName)) return [{ id: 'tim' }];
  if (/^\/social\/is-following\/[^/]+$/.test(pathName)) return { is_following: true };
  if (pathName === '/admin/check') return { is_admin: false, role: null };
  if (pathName === '/users/tim' || pathName === `/users/${LONG_RIDER_WALLET}`) return publicRider;

  if (pathName === '/rides') return rides;
  if (/^\/rides\/[^/]+\/gps$/.test(pathName)) {
    return {
      gps_points: [
        { sequence_num: 0, latitude: 39.9500, longitude: -75.1600, timestamp: isoOffset(1, 0), elevation_m: 20, distance_m: 0 },
        { sequence_num: 1, latitude: 39.9518, longitude: -75.1608, timestamp: isoOffset(1, 300), elevation_m: 34, distance_m: 1450 },
        { sequence_num: 2, latitude: 39.9531, longitude: -75.1622, timestamp: isoOffset(1, 600), elevation_m: 52, distance_m: 3200 },
        { sequence_num: 3, latitude: 39.9552, longitude: -75.1642, timestamp: isoOffset(1, 800), elevation_m: 142, distance_m: 4500 },
        { sequence_num: 4, latitude: 39.9582, longitude: -75.1667, timestamp: isoOffset(1, 1000), elevation_m: 286, distance_m: 5650 },
        { sequence_num: 5, latitude: 39.9610, longitude: -75.1684, timestamp: isoOffset(1, 1260), elevation_m: 464, distance_m: 6900 },
        { sequence_num: 6, latitude: 39.9626, longitude: -75.1670, timestamp: isoOffset(1, 2000), elevation_m: 500, distance_m: 11200 },
        { sequence_num: 7, latitude: 39.9601, longitude: -75.1630, timestamp: isoOffset(1, 3600), elevation_m: 556, distance_m: 28400 },
        { sequence_num: 8, latitude: 39.9550, longitude: -75.1650, timestamp: isoOffset(1, 5400), elevation_m: 620, distance_m: 48200 },
      ],
      imported_count: 9,
      failed_count: 0,
    };
  }
  if (/^\/rides\/[^/]+\/status$/.test(pathName)) {
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
        kcals: 1320,
        distance_m: 48_200,
        elevation_gain_m: 620,
        duration_sec: 5_400,
        avg_power_w: 216,
        normalized_power_w: 238,
      },
    };
  }
  if (/^\/rides\/[^/]+\/streams$/.test(pathName)) {
    const streamType = url.searchParams.get('type') || 'power';
    const baseValues = {
      power: [180, 245, 320],
      heart_rate: [142, 156, 164],
      cadence: [86, 90, 92],
      speed: [7.2, 8.5, 9.1],
    };
    const values = baseValues[streamType] ?? baseValues.power;
    return {
      id: `stream-${streamType}`,
      ride_id: 'ride-1',
      stream_type: streamType,
      timestamps: [iso(1), iso(1), iso(1)],
      values,
      sample_count: values.length,
      min_value: Math.min(...values),
      max_value: Math.max(...values),
      avg_value: values.reduce((sum, value) => sum + value, 0) / values.length,
    };
  }
  if (/^\/rides\/[^/]+\/tiles$/.test(pathName)) {
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
  if (/^\/rides\/[^/]+\/patterns$/.test(pathName)) {
    return {
      ride_id: 'ride-1',
      patterns: {
        climb_patterns: [
          {
            name: 'Spring Garden Pitch',
            road_name: 'Spring Garden Street',
            start_offset_s: 260,
            end_offset_s: 900,
            vert_m: 128,
            distance_m: 2100,
            avg_gradient_pct: 6.1,
            duration_s: 360,
            avg_speed_mps: 5.8,
            vam: 1280,
            signature_hex: 'pattern-signature-0',
          },
          {
            name: 'Full Stack Smoke 1776366970',
            road_name: 'Ellis Street',
            start_offset_s: 600,
            end_offset_s: 1260,
            vert_m: 412,
            distance_m: 3700,
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
              kom_holder: 'Local rider',
              total_completions: 42,
            },
          },
          {
            name: 'Vine Street Ramp',
            road_name: 'Vine Street',
            start_offset_s: 980,
            end_offset_s: 1620,
            vert_m: 86,
            distance_m: 1600,
            avg_gradient_pct: 5.4,
            duration_s: 260,
            avg_speed_mps: 6.2,
            vam: 1191,
            signature_hex: 'pattern-signature-2',
          },
          {
            name: 'Callowhill Step',
            road_name: 'Callowhill Street',
            start_offset_s: 1240,
            end_offset_s: 2250,
            vert_m: 144,
            distance_m: 2500,
            avg_gradient_pct: 5.8,
            duration_s: 470,
            avg_speed_mps: 5.3,
            vam: 1103,
            signature_hex: 'pattern-signature-3',
          },
          {
            name: 'North Broad Lift',
            road_name: 'North Broad Street',
            start_offset_s: 1680,
            end_offset_s: 3320,
            vert_m: 218,
            distance_m: 5100,
            avg_gradient_pct: 4.3,
            duration_s: 820,
            avg_speed_mps: 6.2,
            vam: 957,
            signature_hex: 'pattern-signature-4',
          },
          {
            name: 'Market Street Roller',
            road_name: 'Market Street',
            start_offset_s: 2450,
            end_offset_s: 3100,
            vert_m: 58,
            distance_m: 1400,
            avg_gradient_pct: 4.1,
            duration_s: 210,
            avg_speed_mps: 6.7,
            vam: 994,
            signature_hex: 'pattern-signature-5',
          },
          {
            name: 'Schuylkill Return',
            road_name: 'Schuylkill River Trail',
            start_offset_s: 3720,
            end_offset_s: 4860,
            vert_m: 76,
            distance_m: 2900,
            avg_gradient_pct: 2.6,
            duration_s: 520,
            avg_speed_mps: 5.6,
            vam: 526,
            signature_hex: 'pattern-signature-6',
          },
        ],
        steady_pattern: {
          duration_s: 1800,
          avg_power_w: 216,
          avg_hr_bpm: 156,
          start_time_offset_s: 1300,
          end_time_offset_s: 3100,
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
  if (/^\/rides\/[^/]+\/interactions$/.test(pathName)) {
    return {
      ride_id: pathName.split('/')[2],
      kudos_count: 1,
      comment_count: 1,
      viewer_has_kudos: false,
      viewer_reported: false,
      comments_enabled: true,
      can_comment: true,
    };
  }
  if (/^\/rides\/[^/]+\/comments$/.test(pathName)) {
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
  if (/^\/rides\/[^/]+$/.test(pathName)) return rides[0];

  if (pathName === '/climbs/climb-1') {
    return {
      contract_version: 'client.v1',
      truth_source: 'attested',
      id: 'climb-1',
      name: 'Full Stack Smoke 1776366970',
      region: 'Boulder',
      length_m: 3700,
      elev_gain_m: 412,
      avg_gradient_pct: 7.4,
      total_completions: 42,
      has_vault: true,
      vault_id: 1,
      vault_economy: {
        contract_version: 'client.v1',
        truth_source: 'attested',
        has_vault: true,
        vault_id: 1,
        vault_signature: 'vault-signature-1',
        total_staked: 12_500,
        total_completions: 42,
      },
      local_legend: {
        contract_version: 'client.v1',
        truth_source: 'attested',
        climb_id: 'climb-1',
        vault_id: 1,
        wallet: LONG_RIDER_WALLET,
        attempts_in_window: 8,
      },
    };
  }

  if (pathName === '/climbs/climb-1/leaderboard') {
    return {
      contract_version: 'client.v1',
      truth_source: 'attested',
      climb_id: 'climb-1',
      climb_name: 'Full Stack Smoke 1776366970',
      vault_id: 1,
      epoch_number: 7,
      total: 2,
      entries: [
        {
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          best_time_seconds: 590,
          avg_power_w: 382,
        },
        {
          rank: 2,
          wallet: TEST_WALLET,
          best_time_seconds: 610,
          avg_power_w: 360,
        },
      ],
      kom_holder: LONG_RIDER_WALLET,
      kom_time_s: 590,
    };
  }

  if (pathName === '/vaults') {
    return { vaults, total: vaults.length, offset: 0, limit: Number(url.searchParams.get('limit') ?? 50) };
  }
  if (pathName === '/vaults/stakes/me' || pathName === '/vaults/my/stakes') {
    return {
      stakes: [
        {
          vault_signature: 'vault-signature-1',
          vault_id: 1,
          vault_name: 'Full Stack Smoke',
          wallet: TEST_WALLET,
          cal_staked: 1200,
          lp_tokens: 1180,
          staked_at: iso(20),
        },
      ],
    };
  }
  if (/^\/vaults\/\d+\/leaderboard$/.test(pathName)) {
    return {
      vault_id: 1,
      vault_name: 'Full Stack Smoke',
      leaderboard: [
        {
          vault_signature: 'vault-signature-1',
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          user_id: publicRider.id,
          username: publicRider.username,
          display_name: publicRider.display_name,
          avatar_url: publicRider.avatar_url,
          best_time_seconds: 590,
          avg_power_w: 382,
          completion_id: 'completion-tim',
          achieved_at: iso(1),
        },
        {
          vault_signature: 'vault-signature-1',
          rank: 2,
          wallet: TEST_WALLET,
          user_id: user.id,
          username: user.username,
          display_name: user.display_name,
          avatar_url: user.avatar_url,
          best_time_seconds: 610,
          avg_power_w: 360,
          completion_id: 'completion-test',
          achieved_at: iso(1),
        },
        {
          vault_signature: 'vault-signature-1',
          rank: 3,
          wallet: 'thirdwallet111111111111111111111111111111',
          user_id: 'rider-3',
          username: 'maya.montgomery',
          display_name: 'Maya Montgomery',
          avatar_url: null,
          best_time_seconds: 628,
          avg_power_w: 344,
          completion_id: 'completion-third',
          achieved_at: iso(3),
        },
      ],
      kom_holder: LONG_RIDER_WALLET,
      kom_time_s: 590,
    };
  }
  if (/^\/vaults\/\d+$/.test(pathName)) {
    return {
      ...vaults[0],
      leaderboard: [
        {
          vault_signature: 'vault-signature-1',
          rank: 1,
          wallet: LONG_RIDER_WALLET,
          user_id: publicRider.id,
          username: publicRider.username,
          display_name: publicRider.display_name,
          avatar_url: publicRider.avatar_url,
          best_time_seconds: 590,
          avg_power_w: 382,
          completion_id: 'completion-tim',
          achieved_at: iso(1),
        },
      ],
      total_lp_tokens: 1180,
      local_legend: {
        wallet: LONG_RIDER_WALLET,
        elected_epoch: 3,
        term_end_epoch: 4,
        completions_count: 8,
      },
    };
  }
  if (/^\/vaults\/\d+\/pending-rewards$/.test(pathName)) {
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
    };
  }
  if (/^\/vaults\/\d+\/my-completions$/.test(pathName)) {
    return {
      vault_id: 1,
      vault_name: 'Full Stack Smoke',
      efforts: [],
      total_count: 0,
      best_time_seconds: null,
      total_prs: 0,
    };
  }

  if (pathName === '/users/me/achievements') {
    return {
      achievements: [
        { id: 'ach-1', name: 'Explorer: 59 New Areas', description: 'Discovered 59 new areas.', unlocked_at: iso(49), progress: 59, target: 59 },
      ],
    };
  }
  if (pathName === '/users/me/leaderboard-positions') {
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

  if (pathName === '/beetles/my-cards') return [];
  if (pathName === '/beetles/levels') return { max_level: 6, upgrade_costs: [], level_names: ['Scout', 'Roller'] };
  if (pathName === '/notifications') return { contract_version: 'notification.v1', unread_count: 0, notifications: [] };
  if (pathName === '/notifications/preferences') return {
    email_enabled: true,
    push_enabled: false,
    in_app_enabled: true,
    new_follower: true,
    ride_kudos: true,
    vault_rewards: true,
    system_announcements: true,
  };
  if (pathName === '/portfolio') return {
    dung_balance: '0',
    dung_balance_base_units: '0',
    cal_balance: '22154',
    cal_balance_base_units: '22154000000000',
    staked_positions: [],
    pending_claims: [],
  };
  if (pathName === '/cal/onchain') return {
    wallet: TEST_WALLET,
    cal_balance: '22154',
    cal_balance_base_units: '22154000000000',
    total_staked: 1200,
    cal_earned_today: 96,
    total_rides: rides.length,
    total_tss: 385,
    account_exists: true,
  };
  if (pathName === '/distributions/my') return { distributions: [], receipt_count: 0, distribution_count: 0, limit: 50, offset: 0 };
  if (method === 'POST' || method === 'PUT' || method === 'PATCH') return { status: 'ok' };

  return undefined;
}

async function waitForServer(url, timeoutMs = 120_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return true;
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function ensureServer() {
  if (await waitForServer(baseUrl, 1000)) return null;

  const proc = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', capturePort], {
    cwd: portalDir,
    env: { ...process.env, VITE_API_URL: '/api' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let log = '';
  proc.stdout.on('data', (chunk) => {
    log += chunk.toString();
  });
  proc.stderr.on('data', (chunk) => {
    log += chunk.toString();
  });

  if (!(await waitForServer(baseUrl))) {
    proc.kill('SIGTERM');
    throw new Error(`Portal dev server did not start.\n${log}`);
  }

  return proc;
}

async function routeApi(page, unexpectedApiCalls) {
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isApiHost = [
      '127.0.0.1',
      'localhost',
      'api.boulderroller.xyz',
      'api.boulderroller.org',
    ].includes(url.hostname);
    const isApiRequest = url.pathname.startsWith('/api')
      || ['fetch', 'xhr'].includes(request.resourceType())
      || (isApiHost && url.port === '4174');

    if (url.hostname.endsWith('privy.io') || url.hostname.includes('walletconnect.com')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
      return;
    }

    if (!isApiRequest) {
      await route.continue();
      return;
    }

    const body = responseFor(url, request.method());
    if (body && typeof body === 'object' && '__api_error' in body) {
      await route.fulfill({
        status: body.status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: body.detail }),
      });
      return;
    }

    if (body === undefined) {
      unexpectedApiCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Unmocked API route' }) });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function initPage(page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('br_authenticated', 'true');
      localStorage.setItem('boulder-roller-theme-id', 'hoo-breddin');
      localStorage.setItem('boulder-roller-dark-mode', 'false');
      localStorage.removeItem('br_auth_handoff_pending');
      localStorage.setItem('br_setup_banner_dismissed', 'true');
    } catch {
      // Cross-origin auth frames can deny storage before boot.
    }
    window.ethereum = {
      request: async () => [],
      on: () => {},
      removeListener: () => {},
    };
  });
}

async function openRoute(page, routePath, viewport) {
  await page.setViewportSize(viewport);
  await page.goto(`${baseUrl}${routePath}`, { waitUntil: 'domcontentloaded' });
  await page.locator('.portal-shell__header').waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(250);
}

async function saveViewport(page, name) {
  const file = path.join(outputDir, name);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

async function saveLocator(page, selector, name) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: 'visible', timeout: 10_000 });
  const file = path.join(outputDir, name);
  await locator.screenshot({ path: file });
  return file;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const server = await ensureServer();
  const browser = await chromium.launch();
  const unexpectedApiCalls = [];
  const captures = [];

  try {
    const page = await browser.newPage();
    await initPage(page);
    await routeApi(page, unexpectedApiCalls);

    const desktop = { width: 1440, height: 1000 };
    const mobile = { width: 390, height: 844 };

    await openRoute(page, '/', desktop);
    captures.push({
      name: 'FeedView',
      status: 'current capture',
      source: 'web/portal/src/components/feed/ActivityFeed.tsx',
      file: await saveViewport(page, '01-desktop-feedview.png'),
    });
    await page.addStyleTag({
      content: `
        .portal-shell__header,
        .stub-mode-banner,
        .portal-shell__sidebar {
          visibility: hidden !important;
        }
      `,
    });
    await page.waitForTimeout(100);
    captures.push({
      name: 'FeedView item',
      status: 'current isolated component capture',
      source: 'web/portal/src/components/feed/ActivityFeedItem.tsx',
      file: await saveLocator(page, '.feed-activity-card', '02-desktop-feedview-item.png'),
    });

    await openRoute(page, '/activities/ride-1', desktop);
    captures.push({
      name: 'RideView',
      status: 'current capture',
      source: 'web/portal/src/pages/RideView.tsx',
      file: await saveViewport(page, '03-desktop-rideview.png'),
    });
    await page.getByRole('button', { name: /Show More/i }).click();
    await page.waitForTimeout(600);
    captures.push({
      name: 'RideView expanded stats',
      status: 'current capture',
      source: 'web/portal/src/pages/RideView.tsx',
      file: await saveViewport(page, '04-desktop-rideview-stats-expanded.png'),
    });
    await page.getByRole('button', { name: /Show Less/i }).click();
    await page.waitForTimeout(100);
    await page.getByRole('button', { name: /Select Full Stack Smoke/i }).click();
    await page.waitForTimeout(150);
    captures.push({
      name: 'Climb table current expanded card',
      status: 'current capture; this is not a separate popout',
      source: 'web/portal/src/components/ride/ClimbsTable.tsx',
      file: await saveLocator(page, '.ride-detail-climbs-panel', '05-desktop-climb-table-current.png'),
    });
    const sidebarToggle = page.locator('button[aria-controls="ride-detail-sidebar"]');
    if (await sidebarToggle.count()) {
      await sidebarToggle.click();
      await page.locator('#ride-detail-sidebar').waitFor({ state: 'visible', timeout: 10_000 });
      captures.push({
        name: 'RideView vault/economy side panel',
        status: 'current capture',
        source: 'web/portal/src/components/ride/VaultPanel.tsx',
        file: await saveLocator(page, '#ride-detail-sidebar', '06-desktop-rideview-vault-panel.png'),
      });
    }

    await openRoute(page, '/climbs/climb-1', desktop);
    captures.push({
      name: 'ClimbView',
      status: 'current capture',
      source: 'web/portal/src/pages/ClimbView.tsx',
      file: await saveViewport(page, '07-desktop-climbview.png'),
    });
    captures.push({
      name: 'ClimbView record/economy module',
      status: 'current capture; compact module, not a popout',
      source: 'web/portal/src/pages/ClimbView.tsx',
      file: await saveLocator(page, '.climb-detail-protocol-grid', '08-desktop-climbview-record-economy-module.png'),
    });

    await openRoute(page, '/vaults/1', desktop);
    captures.push({
      name: 'VaultView current economy reference',
      status: 'current capture; reference only for unbuilt econ popout',
      source: 'web/portal/src/pages/VaultView.tsx',
      file: await saveViewport(page, '09-desktop-vaultview-economy-reference.png'),
    });

    await openRoute(page, '/rider/tim', desktop);
    captures.push({
      name: 'RiderView',
      status: 'current capture',
      source: 'web/portal/src/pages/Profile.tsx',
      file: await saveViewport(page, '10-desktop-riderview.png'),
    });

    await openRoute(page, '/activities/ride-1', mobile);
    captures.push({
      name: 'Mobile-width RideView',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/pages/RideView.tsx',
      file: await saveViewport(page, '11-responsive-mobile-rideview.png'),
    });
    await page.getByRole('button', { name: /Show More/i }).click();
    await page.waitForTimeout(600);
    captures.push({
      name: 'Mobile-width RideView expanded stats',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/pages/RideView.tsx',
      file: await saveViewport(page, '12-responsive-mobile-rideview-stats-expanded.png'),
    });
    await page.getByRole('button', { name: /Show Less/i }).click();
    await page.waitForTimeout(100);
    await page.locator('.ride-detail-climbs-panel').scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);
    await page.getByRole('button', { name: /Select Full Stack Smoke/i }).click();
    await page.waitForTimeout(150);
    captures.push({
      name: 'Mobile-width climb table current expanded card',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/components/ride/ClimbsTable.tsx',
      file: await saveLocator(page, '.ride-detail-climbs-panel', '13-responsive-mobile-climb-table-current.png'),
    });
    await page.locator('.ride-detail-mobile-vaults').scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);
    captures.push({
      name: 'Mobile-width climb economy current panel',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/components/ride/VaultPanel.tsx',
      file: await saveViewport(page, '14-responsive-mobile-climb-econ-current.png'),
    });

    await openRoute(page, '/climbs/climb-1', mobile);
    captures.push({
      name: 'Mobile-width ClimbView',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/pages/ClimbView.tsx',
      file: await saveViewport(page, '15-responsive-mobile-climbview.png'),
    });

    await openRoute(page, '/profile', mobile);
    captures.push({
      name: 'Mobile-width ProfileView',
      status: 'responsive portal capture; not native app capture',
      source: 'web/portal/src/pages/Profile.tsx',
      file: await saveViewport(page, '16-responsive-mobile-profileview.png'),
    });

    captures.push({
      name: 'Native mobile requested views',
      status: 'not captured',
      source: 'mobile/src/screens/RideDetailScreen.tsx, mobile/src/screens/ClimbDetailScreen.tsx, mobile/src/screens/ProfileScreen.tsx',
      note: 'The booted simulator is currently at the unauthenticated LoginScreen. Do not treat responsive portal captures as native app truth.',
    });
    captures.push({
      name: 'Desktop/mobile climb econ popout',
      status: 'unbuilt gap',
      note: 'No current popout exists. Use current ClimbView, RideView VaultPanel, and VaultView captures as constraints before proposing a primitive.',
    });

    const manifest = {
      generatedAt: new Date().toISOString(),
      fixtureBoundary: 'Screens are current portal code using API-contract fixture data from the route-shell test shape. UI is current; fixture values are not live or final product data.',
      unexpectedApiCalls,
      captures: captures.map((capture) => ({
        ...capture,
        file: capture.file ? path.relative(repoRoot, capture.file) : undefined,
      })),
    };

    await writeFile(path.join(outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

    if (unexpectedApiCalls.length > 0) {
      throw new Error(`Unexpected API calls during capture:\n${unexpectedApiCalls.join('\n')}`);
    }

    console.log(`Wrote ${captures.filter((capture) => capture.file).length} captures to ${path.relative(repoRoot, outputDir)}`);
  } finally {
    await browser.close();
    if (server) server.kill('SIGTERM');
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
