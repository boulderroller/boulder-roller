/**
 * API Client Tests
 *
 * Tests the core request pipeline: auth headers, case conversion,
 * error classification, 401 handling, and token lifecycle.
 *
 * Uses jest.fn() mocks on global.fetch instead of MSW, because
 * MSW v2.7+ uses ESM-only internals incompatible with jest-expo's
 * CJS transform.
 *
 * The API client reads access tokens from Zustand's authStore,
 * so we set auth state directly on the store in tests.
 */

import { api, ApiError } from '../api';
import { useAuthStore } from '../../stores/authStore';

const API_URL = 'http://localhost:8080';

// ---------------------------------------------------------------------------
// Fetch mock helpers
// ---------------------------------------------------------------------------

const originalFetch = global.fetch;

/** Create a mock Response that behaves like a real fetch Response */
function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 204 ? 'No Content' : 'OK',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: jest.fn().mockResolvedValue(body),
    text: jest.fn().mockResolvedValue(JSON.stringify(body)),
    clone: jest.fn(),
  } as unknown as Response;
}

function textResponse(text: string, status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'Error',
    headers: new Headers({ 'content-type': 'text/plain' }),
    json: jest.fn().mockRejectedValue(new Error('not json')),
    text: jest.fn().mockResolvedValue(text),
    clone: jest.fn(),
  } as unknown as Response;
}

function emptyResponse(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 204 ? 'No Content' : 'Error',
    headers: new Headers(),
    json: jest.fn().mockRejectedValue(new Error('no body')),
    text: jest.fn().mockResolvedValue(''),
    clone: jest.fn(),
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// Default response data (mirrors old MSW handlers)
// ---------------------------------------------------------------------------

const DEFAULT_USER = {
  wallet: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
  username: 'testrider',
  display_name: 'TestRider',
  bio: null,
  avatar_url: null,
  is_public: true,
  created_at: '2026-01-01T00:00:00Z',
  total_points: 12500,
  total_rides: 42,
  total_tss: 8400,
  level: 3,
};

const DEFAULT_RIDES = [
  {
    id: 'ride-001',
    activity_id: 'act-001',
    started_at: '2026-03-27T14:30:00Z',
    duration_sec: 3600,
    distance_m: 42000,
    elevation_gain_m: 650,
    tss: 120,
    np: 220,
    avg_power_w: 195,
    source: 'native',
  },
];

const DEFAULT_CLIMBS = {
  climbs: [
    {
      id: '142',
      name: 'Manayunk Wall',
      length_m: 950,
      elev_gain_m: 85,
      avg_gradient_pct: 8.9,
      region: 'Philadelphia',
      vault_id: 142,
      vault_signature: 'ab'.repeat(64),
      has_vault: true,
      total_staked: '5000',
      total_staked_base_units: '5000000000000',
      total_cal_staked: '5000',
      total_cal_staked_base_units: '5000000000000',
      total_completions: 12,
    },
  ],
};

const DEFAULT_SEARCH = {
  contract_version: 'search.v1',
  query: 'manayunk',
  normalized_query: 'manayunk',
  type: 'all',
  has_more: false,
  results: [
    {
      contract_version: 'search.v1',
      id: 'climb:142',
      type: 'climb',
      title: 'Manayunk Wall',
      subtitle: 'Climb · Philadelphia',
      target: { type: 'climb', id: '142' },
      web_path: '/climbs/142',
      source: 'backend',
      privacy: null,
      stats: [{ label: 'Grade', value: '8.9%' }],
      score: 90,
      matched_fields: ['name'],
      scan_state: 'recorded',
      scan_targets: [],
      metadata: {},
    },
  ],
};

const DEFAULT_SEARCH_SUGGESTIONS = {
  contract_version: 'search.v1',
  sections: [
    {
      id: 'popular_climbs',
      title: 'Popular climbs',
      results: DEFAULT_SEARCH.results,
    },
  ],
};

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest.fn();
  global.fetch = fetchMock;
});

afterEach(() => {
  global.fetch = originalFetch;
  // Reset auth store to unauthenticated state
  useAuthStore.getState().setUnauthenticated();
});

/** Helper: put the auth store into authenticated state */
function authenticateStore(accessToken = 'test-token') {
  useAuthStore.getState().setAuthenticated({
    accessToken,
    tokenExpiresAt: Date.now() + 3600_000,
    wallet: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
    authMethod: 'privy',
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('APIClient', () => {
  describe('request headers', () => {
    test('sends Authorization header when authenticated', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      authenticateStore('my-token');
      await api.getMe();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      expect(init.headers['Authorization']).toBe('Bearer my-token');
    });

    test('does not send Authorization header for skipAuth endpoints', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok' }));

      authenticateStore('my-token');
      await api.healthCheck();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      // healthCheck passes skipAuth=true, so no auth header
      expect(init.headers['Authorization']).toBeUndefined();
    });
  });

  describe('auth payloads', () => {
    test('checks invite codes without wallet-side consumption fields', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ valid: true, message: 'ok' }));

      await api.validateInviteCode('ALPHA-RIDE');

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/auth/invite/validate`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ code: 'ALPHA-RIDE' }),
        }),
      );
    });

    test('requests wallet nonces with device binding', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        nonce: 'nonce-value',
        message: 'Sign this Boulder Roller login message',
        expires_at: '2026-04-22T12:00:00Z',
      }));

      await api.getNonce(
        'NonceWallet111111111111111111111111111111',
        '4a28af7e-8f7f-4d89-a95e-bcfdc164cb16',
      );

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/auth/nonce`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            wallet: 'NonceWallet111111111111111111111111111111',
            device_id: '4a28af7e-8f7f-4d89-a95e-bcfdc164cb16',
          }),
        }),
      );
    });

    test('sends invite code during Privy signup exchange when available', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        access_token: 'access.jwt',
        refresh_token: 'refresh.jwt',
        token_type: 'bearer',
        expires_in: 3600,
        wallet: 'InviteWallet111111111111111111111111111111',
      }));

      await api.verifyPrivyToken(
        'InviteWallet111111111111111111111111111111',
        'privy-token',
        'device-id',
        'ALPHA-RIDE',
      );

      const [, init] = fetchMock.mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({
        wallet: 'InviteWallet111111111111111111111111111111',
        privy_token: 'privy-token',
        device_id: 'device-id',
        invite_code: 'ALPHA-RIDE',
      });
    });

    test('omits invite code during returning-user Privy exchange', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        access_token: 'access.jwt',
        refresh_token: 'refresh.jwt',
        token_type: 'bearer',
        expires_in: 3600,
        wallet: 'ReturnWallet11111111111111111111111111111',
      }));

      await api.verifyPrivyToken(
        'ReturnWallet11111111111111111111111111111',
        'privy-token',
        'device-id',
      );

      const [, init] = fetchMock.mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({
        wallet: 'ReturnWallet11111111111111111111111111111',
        privy_token: 'privy-token',
        device_id: 'device-id',
      });
    });
  });

  describe('case conversion', () => {
    test('converts snake_case response to camelCase', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      authenticateStore();
      const user = await api.getMe();
      // Handler returns display_name, total_points, etc.
      // Client should convert to displayName, totalPoints
      expect(user).toHaveProperty('displayName');
      expect(user).toHaveProperty('totalPoints');
      expect(user).not.toHaveProperty('display_name');
      expect(user).not.toHaveProperty('total_points');
    });

    test('converts array responses correctly', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_RIDES));

      authenticateStore();
      const rides = await api.getRides();
      expect(Array.isArray(rides)).toBe(true);
      expect(rides.length).toBe(1);
      expect(rides[0]).toHaveProperty('activityId');
      expect(rides[0]).toHaveProperty('startedAt');
      expect(rides[0]).toHaveProperty('durationSec');
      expect(rides[0]).not.toHaveProperty('activity_id');
    });
  });

  describe('error handling', () => {
    test('throws ApiError with type=network_error on fetch failure', async () => {
      fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      try {
        await api.healthCheck();
        fail('Expected ApiError to be thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).type).toBe('network_error');
        expect((err as ApiError).retryable).toBe(true);
      }
    });

    test('throws ApiError with type=session_expired on 401', async () => {
      fetchMock.mockResolvedValueOnce(emptyResponse(401));

      authenticateStore('expired-token');

      try {
        await api.getMe();
        fail('Expected ApiError to be thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).type).toBe('session_expired');
        expect((err as ApiError).statusCode).toBe(401);
      }

      // Auth store should be cleared after 401
      expect(useAuthStore.getState().status).toBe('unauthenticated');
    });

    test('throws ApiError with type=server_error on 500', async () => {
      fetchMock.mockResolvedValueOnce(textResponse('Internal Server Error', 500));

      authenticateStore();
      try {
        await api.getRides();
        fail('Expected ApiError to be thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).type).toBe('server_error');
        expect((err as ApiError).retryable).toBe(true);
        expect((err as ApiError).statusCode).toBe(500);
      }
    });

    test('throws ApiError with type=unknown on 400', async () => {
      fetchMock.mockResolvedValueOnce(textResponse('Bad Request', 400));

      authenticateStore();
      try {
        await api.getRides();
        fail('Expected ApiError to be thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).type).toBe('unknown');
        expect((err as ApiError).retryable).toBe(false);
        expect((err as ApiError).statusCode).toBe(400);
      }
    });

    test('handles 204 No Content response', async () => {
      fetchMock.mockResolvedValueOnce(emptyResponse(204));

      authenticateStore();
      // Should not throw
      await api.logout(null, 'test-device-id');
    });
  });

  describe('data fetching', () => {
    test('fetches rides list', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_RIDES));

      authenticateStore();
      const rides = await api.getRides();
      expect(rides).toHaveLength(1);
      expect(rides[0].id).toBe('ride-001');
      expect(rides[0].distanceM).toBe(42000);
      expect(rides[0].tss).toBe(120);
    });

    test('fetches climbs list from canonical endpoint', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_CLIMBS));

      authenticateStore();
      const climbs = await api.getClimbs();
      expect(climbs).toHaveLength(1);
      expect(climbs[0].name).toBe('Manayunk Wall');
      expect(climbs[0].elevGainM).toBe(85);
      expect(climbs[0].avgGradientPct).toBe(8.9);
      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/climbs/list?limit=20`);
    });

    test('fetches canonical search results', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_SEARCH));

      authenticateStore();
      const response = await api.search({ q: 'manayunk', type: 'climbs', limit: 5 });

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/search?q=manayunk&type=climbs&limit=5`);
      expect(response.contractVersion).toBe('search.v1');
      expect(response.results[0].webPath).toBe('/climbs/142');
      expect(response.results[0].matchedFields).toEqual(['name']);
      expect(response.results[0].scanState).toBe('recorded');
    });

    test('fetches canonical search suggestions', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_SEARCH_SUGGESTIONS));

      authenticateStore();
      const response = await api.getSearchSuggestions({ limit: 4 });

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/search/suggestions?limit=4`);
      expect(response.contractVersion).toBe('search.v1');
      expect(response.sections[0].id).toBe('popular_climbs');
      expect(response.sections[0].results[0].webPath).toBe('/climbs/142');
    });

    test('keeps getVaults compatibility on canonical climb endpoint', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_CLIMBS));

      authenticateStore();
      const climbs = await api.getVaults();
      expect(climbs).toHaveLength(1);
      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/climbs/list?limit=20`);
    });

    test('fetches user profile', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      authenticateStore();
      const user = await api.getMe();
      expect(user.wallet).toBe('3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu');
      expect(user.username).toBe('testrider');
      expect(user.displayName).toBe('TestRider');
      expect(user.level).toBe(3);
    });

    test('maps release-aware Held and pending training state from ride status', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        ride_id: 'ride-1',
        status: 'completed',
        error_message: null,
        effort_policy: {
          reward_policy: 'threshold_provisional_hold_v1',
          threshold_economy_state: 'held',
        },
        metrics: {
          tss: 64,
          threshold_training_state: 'pending',
        },
      }));

      authenticateStore();
      const status = await api.getRideStatus('ride-1');

      expect(status.effortPolicy?.thresholdEconomyState).toBe('held');
      expect(status.metrics?.thresholdTrainingState).toBe('pending');
    });

    test('never sends a legacy manual Threshold field through profile updates', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      authenticateStore();
      await api.updateProfile({
        displayName: 'Tim',
        ftp_w: 320,
      } as unknown as Parameters<typeof api.updateProfile>[0]);

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/users/me`,
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ display_name: 'Tim' }),
        }),
      );
    });

    test('sends the live units alias instead of the retired client key', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      authenticateStore();
      await api.updateProfile({ unitPreference: 'imperial' });

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/users/me`,
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ units: 'imperial' }),
        }),
      );
    });

    test('uploads a profile avatar through the signed storage flow', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({
          upload_id: 'avatar-upload-1',
          signed_url: 'https://storage.example/avatar-upload',
          expires_in: 3600,
        }))
        .mockResolvedValueOnce(emptyResponse(200))
        .mockResolvedValueOnce(jsonResponse({
          ...DEFAULT_USER,
          avatar_url: 'https://storage.example/avatar-read',
        }));

      authenticateStore();
      const user = await api.uploadAvatar({
        uri: 'file:///tmp/avatar.jpg',
        name: 'avatar.jpg',
        mimeType: 'image/jpeg',
        size: 1024,
      });

      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/users/me/avatar/init`);
      expect(fetchMock.mock.calls[0][1].body).toBe(JSON.stringify({
        file_name: 'avatar.jpg',
        mime_type: 'image/jpeg',
        file_size: 1024,
      }));
      expect(fetchMock.mock.calls[1][0]).toBe('https://storage.example/avatar-upload');
      expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
        method: 'PUT',
        headers: { 'x-upsert': 'false' },
      }));
      expect(fetchMock.mock.calls[2][0]).toBe(`${API_URL}/users/me/avatar/complete`);
      expect(fetchMock.mock.calls[2][1].body).toBe(JSON.stringify({ upload_id: 'avatar-upload-1' }));
      expect(user.avatarUrl).toBe('https://storage.example/avatar-read');
    });

    test('deletes the current profile avatar', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        ...DEFAULT_USER,
        avatar_url: null,
      }));

      authenticateStore();
      const user = await api.deleteAvatar();

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/users/me/avatar`,
        expect.objectContaining({ method: 'DELETE' }),
      );
      expect(user.avatarUrl).toBeNull();
    });

    test('fetches public rider profile without auth', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(DEFAULT_USER));

      const user = await api.getUser('testrider');

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/users/testrider`);
      expect(user.username).toBe('testrider');
      expect(user.displayName).toBe('TestRider');
    });

    test('fetches public rider social modules without auth', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({
          is_public: true,
          rides: [
            {
              id: 'ride-001',
              title: 'Hill Work',
              started_at: '2026-04-29T10:00:00Z',
              distance_m: 18000,
              elevation_gain_m: 620,
            },
          ],
          count: 1,
        }))
        .mockResolvedValueOnce(jsonResponse({
          is_public: true,
          cards: [
            {
              id: 'card-1',
              wallet: DEFAULT_USER.wallet,
              card_type: 'CLIMB',
              scope_id: 'scope-1',
              scope_name: 'Manayunk Wall',
              score: 420,
              level: 3,
              patterns_scored: 12,
              created_at: '2026-04-24T00:00:00Z',
              updated_at: '2026-04-24T00:00:00Z',
            },
          ],
          count: 1,
        }));

      const rides = await api.getPublicRiderRecentRides('testrider', 5);
      const cards = await api.getPublicRiderBeetleCards('testrider');

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/users/testrider/recent-rides?limit=5`);
      expect(fetchMock.mock.calls[1][0]).toBe(`${API_URL}/users/testrider/beetle-cards`);
      expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
      expect(rides.isPublic).toBe(true);
      expect(rides.rides[0].startedAt).toBe('2026-04-29T10:00:00Z');
      expect(cards.cards[0].cardType).toBe('CLIMB');
    });

    test('fetches public rider profile bootstrap without auth', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        contract_version: 'public_rider_profile.v1',
        rider: {
          contract_version: 'public_rider_ref.v1',
          id: 'user-1',
          username: 'testrider',
          display_name: 'TestRider',
          avatar_url: null,
          is_public: true,
          viewer_relationship: 'none',
        },
        profile: DEFAULT_USER,
        privacy: { visibility: 'public', can_view: true, is_owner: false, is_follower: false, redact_gps: false, protocol_public: false, protocol_public_fields: [], reason: 'public' },
        viewer_capabilities: {
          contract_version: 'viewer_capabilities.v1',
          can_view: true,
          can_follow: false,
          can_kudos: false,
          can_comment: false,
          can_report: false,
          can_share: true,
          can_edit: false,
          can_open_proof: false,
          can_open_scan: true,
          viewer_relationship: 'none',
        },
        modules: [
          { contract_version: 'public_profile_module.v1', id: 'recent_rides', state: 'empty', title: 'Recent rides', count: 0 },
        ],
        follow_state: null,
        recent_rides: { is_public: true, rides: [], count: 0 },
        beetle_cards: { is_public: true, cards: [], count: 0 },
        leaderboard: null,
      }));

      const response = await api.getPublicRiderProfile('testrider', 5);

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/users/testrider/profile?limit=5`);
      expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
      expect(response.contractVersion).toBe('public_rider_profile.v1');
      expect(response.rider?.username).toBe('testrider');
      expect(response.rider).not.toHaveProperty('wallet');
      expect(response.viewerCapabilities.canShare).toBe(true);
      expect(response.viewerCapabilities.canOpenScan).toBe(true);
      expect(response.modules?.[0].state).toBe('empty');
    });

    test('fetches follow state and owner BeetleCards', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({
          is_following: true,
          is_followed_by: false,
          is_mutual_follow: false,
        }))
        .mockResolvedValueOnce(jsonResponse([
          {
            id: 'card-1',
            wallet: DEFAULT_USER.wallet,
            card_type: 'CLIMB',
            scope_id: 'scope-1',
            scope_name: 'Manayunk Wall',
            score: 420,
            level: 3,
            patterns_scored: 12,
            created_at: '2026-04-24T00:00:00Z',
            updated_at: '2026-04-24T00:00:00Z',
          },
        ]));

      authenticateStore();
      const follow = await api.getFollowState('user-1');
      const cards = await api.getMyBeetleCards();

      expect(follow.isFollowing).toBe(true);
      expect(cards[0].cardType).toBe('CLIMB');
      expect(cards[0].patternsScored).toBe(12);
    });

    test('reports social content with backend casing', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        id: 'report-1',
        reporter_id: 'viewer-1',
        target_type: 'comment',
        target_id: 'comment-1',
        target: {
          contract_version: 'target_action.v1',
          type: 'comment',
          id: 'comment-1',
        },
        primary_action: 'open_comment',
        viewer_capabilities: {
          contract_version: 'viewer_capabilities.v1',
          can_view: true,
          can_report: false,
        },
        reason: 'spam',
        details: 'Looks automated',
        status: 'open',
        created_at: '2026-04-29T12:00:00Z',
      }));

      authenticateStore();
      const report = await api.reportSocialContent('comment', 'comment-1', 'spam', 'Looks automated');

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/social/reports`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            target_type: 'comment',
            target_id: 'comment-1',
            reason: 'spam',
            details: 'Looks automated',
          }),
        }),
      );
      expect(report.targetType).toBe('comment');
      expect(report.target?.type).toBe('comment');
      expect(report.primaryAction).toBe('open_comment');
      expect(report.reporterId).toBe('viewer-1');
    });

    test('reads ride interaction report state', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        ride_id: 'ride-1',
        kudos_count: 2,
        comment_count: 3,
        viewer_has_kudos: true,
        viewer_reported: true,
        report_status: 'open',
        comments_enabled: true,
        can_comment: true,
      }));

      authenticateStore();
      const interactions = await api.getRideInteractions('ride-1');

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/rides/ride-1/interactions`,
        expect.objectContaining({ method: 'GET' }),
      );
      expect(interactions.viewerReported).toBe(true);
      expect(interactions.reportStatus).toBe('open');
      expect(interactions.kudosCount).toBe(2);
    });

    test('reads ride comments with report state', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        comments: [
          {
            id: 'comment-1',
            user_id: 'user-1',
            target_type: 'ride',
            target_id: 'ride-1',
            display_name: 'Rider',
            author: {
              contract_version: 'public_rider_ref.v1',
              id: 'user-1',
              username: 'rider',
              display_name: 'Rider',
              avatar_url: null,
              is_public: true,
              viewer_relationship: 'none',
            },
            content: 'Nice climb',
            created_at: '2026-04-29T12:00:00Z',
            viewer_reported: true,
            report_status: 'open',
          },
        ],
      }));

      authenticateStore();
      const response = await api.getRideComments('ride-1');

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/rides/ride-1/comments`,
        expect.objectContaining({ method: 'GET' }),
      );
      expect(response.comments[0].viewerReported).toBe(true);
      expect(response.comments[0].reportStatus).toBe('open');
      expect(response.comments[0].displayName).toBe('Rider');
      expect(response.comments[0].author?.displayName).toBe('Rider');
      expect(response.comments[0].author).not.toHaveProperty('wallet');
    });

    test('updates ride settings with backend casing', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        status: 'updated',
        ride_id: 'ride-1',
      }));

      authenticateStore();
      const response = await api.updateRide('ride-1', {
        visibility: 'followers',
        commentsEnabled: false,
      });

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/rides/ride-1`,
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({
            visibility: 'followers',
            comments_enabled: false,
          }),
        }),
      );
      expect(response.rideId).toBe('ride-1');
    });

    test('queues ride reprocessing for retryable backend failures', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({
        status: 'reprocessing',
        ride_id: 'ride-1',
        message: 'Ride queued for reprocessing',
      }));

      authenticateStore();
      const response = await api.reprocessRide('ride-1');

      expect(fetchMock).toHaveBeenCalledWith(
        `${API_URL}/rides/ride-1/reprocess`,
        expect.objectContaining({ method: 'POST' }),
      );
      expect(response.rideId).toBe('ride-1');
      expect(response.status).toBe('reprocessing');
    });

    test('writes kudos and comment lifecycle endpoints', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ status: 'kudos_given' }))
        .mockResolvedValueOnce(jsonResponse({ status: 'kudos_removed' }))
        .mockResolvedValueOnce(jsonResponse({
          id: 'comment-1',
          user_id: 'user-1',
          target_type: 'ride',
          target_id: 'ride-1',
          content: 'Updated',
          created_at: '2026-04-29T12:00:00Z',
        }))
        .mockResolvedValueOnce(jsonResponse({
          status: 'comment_deleted',
          comment_id: 'comment-1',
        }));

      authenticateStore();
      await api.giveRideKudos('ride-1');
      await api.removeRideKudos('ride-1');
      const comment = await api.updateRideComment('ride-1', 'comment-1', 'Updated');
      const deleted = await api.deleteRideComment('ride-1', 'comment-1');

      expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/rides/ride-1/kudos`);
      expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: 'POST' }));
      expect(fetchMock.mock.calls[1][0]).toBe(`${API_URL}/rides/ride-1/kudos`);
      expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: 'DELETE' }));
      expect(fetchMock.mock.calls[2][0]).toBe(`${API_URL}/rides/ride-1/comments/comment-1`);
      expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ content: 'Updated' }),
      }));
      expect(fetchMock.mock.calls[3][0]).toBe(`${API_URL}/rides/ride-1/comments/comment-1`);
      expect(fetchMock.mock.calls[3][1]).toEqual(expect.objectContaining({ method: 'DELETE' }));
      expect(comment.content).toBe('Updated');
      expect(deleted.commentId).toBe('comment-1');
    });
  });
});
