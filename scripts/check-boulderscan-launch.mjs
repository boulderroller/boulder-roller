#!/usr/bin/env node

import dns from 'node:dns/promises';
import tls from 'node:tls';

const DEFAULT_API_URL = 'http://localhost:3001';
const DEFAULT_FRONTEND_URL = 'http://localhost:3004';
const DEFAULT_MAX_LAG_SLOTS = 150;
const REQUEST_TIMEOUT_MS = 10_000;

function readEnv(name, fallback = '') {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : fallback;
}

function normalizeBaseUrl(value) {
  return value.replace(/\/$/, '');
}

function parseUrl(value) {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isPublicHttpsUrl(value) {
  const parsed = parseUrl(value);
  if (!parsed || parsed.protocol !== 'https:') return false;
  return !['localhost', '127.0.0.1', '::1'].includes(parsed.hostname);
}

function parseBooleanEnv(value) {
  return ['1', 'true', 'yes'].includes(String(value || '').trim().toLowerCase());
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function request(url, expectedType = 'json', options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const headers = {
      ...(expectedType === 'html' ? { Accept: 'text/html' } : { Accept: 'application/json' }),
      ...(options.headers || {}),
    };
    const response = await fetch(url, {
      method: options.method || 'GET',
      headers,
      signal: controller.signal,
    });
    const contentType = response.headers.get('content-type') || '';
    const payload =
      expectedType === 'html' ? await response.text() : await response.json().catch(() => null);
    return { response, contentType, payload };
  } finally {
    clearTimeout(timer);
  }
}

async function checkDns(label, baseUrl) {
  const parsed = parseUrl(baseUrl);
  assert(parsed, `${label}: expected a valid URL`);
  const addresses = await dns.lookup(parsed.hostname, { all: true });
  assert(addresses.length > 0, `${label}: DNS lookup returned no addresses`);
  console.log(`PASS ${label}`);
}

function checkTls(label, baseUrl) {
  const parsed = parseUrl(baseUrl);
  assert(parsed, `${label}: expected a valid URL`);

  return new Promise((resolve, reject) => {
    const socket = tls.connect(
      {
        host: parsed.hostname,
        port: Number(parsed.port || 443),
        servername: parsed.hostname,
        rejectUnauthorized: true,
      },
      () => {
        const cert = socket.getPeerCertificate();
        socket.end();
        assert(cert && cert.valid_to, `${label}: missing peer certificate`);
        assert(new Date(cert.valid_to).getTime() > Date.now(), `${label}: certificate is expired`);
        console.log(`PASS ${label}`);
        resolve();
      }
    );

    socket.setTimeout(REQUEST_TIMEOUT_MS, () => {
      socket.destroy();
      reject(new Error(`${label}: TLS handshake timed out`));
    });
    socket.on('error', (error) => reject(new Error(`${label}: ${error.message}`)));
  });
}

async function checkJson(label, url, { expectStatus = 200, expectStatuses, validate }) {
  const { response, payload } = await request(url, 'json');
  const allowedStatuses = expectStatuses ?? [expectStatus];
  assert(
    allowedStatuses.includes(response.status),
    `${label}: expected HTTP ${allowedStatuses.join(' or ')}, got ${response.status}`
  );
  if (validate) {
    validate(payload);
  }
  console.log(`PASS ${label}`);
}

async function checkHtml(label, url) {
  const { response, contentType, payload } = await request(url, 'html');
  assert(response.ok, `${label}: expected 2xx, got ${response.status}`);
  assert(contentType.includes('text/html'), `${label}: expected HTML content-type, got ${contentType}`);
  assert(
    typeof payload === 'string' &&
      (payload.includes('BoulderScan') || payload.includes('<div id="root"')),
    `${label}: expected BoulderScan HTML shell`
  );
  console.log(`PASS ${label}`);
}

function requireCorsOrigin(headers, expectedOrigin, label) {
  const allowOrigin = headers.get('access-control-allow-origin');
  assert(
    allowOrigin === expectedOrigin || allowOrigin === '*',
    `${label}: expected Access-Control-Allow-Origin ${expectedOrigin} or *, got ${allowOrigin || 'missing'}`
  );
}

async function checkCors(apiBase, frontendBase) {
  const frontendUrl = parseUrl(frontendBase);
  assert(frontendUrl, 'cors: expected a valid frontend URL');
  const origin = frontendUrl.origin;

  const get = await request(`${apiBase}/v1/observatory`, 'json', {
    headers: { Origin: origin },
  });
  assert(get.response.ok, `cors GET: expected 2xx, got ${get.response.status}`);
  requireCorsOrigin(get.response.headers, origin, 'cors GET');

  const preflight = await request(`${apiBase}/v1/observatory`, 'json', {
    method: 'OPTIONS',
    headers: {
      Origin: origin,
      'Access-Control-Request-Method': 'GET',
    },
  });
  assert(
    preflight.response.status === 204 || preflight.response.status === 200,
    `cors preflight: expected 204 or 200, got ${preflight.response.status}`
  );
  requireCorsOrigin(preflight.response.headers, origin, 'cors preflight');
  const methods = preflight.response.headers.get('access-control-allow-methods') || '';
  assert(methods.includes('GET'), `cors preflight: expected GET in allowed methods, got ${methods}`);
  console.log('PASS cors');
}

function requireKeys(payload, keys, label) {
  assert(payload && typeof payload === 'object', `${label}: expected JSON object`);
  for (const key of keys) {
    assert(key in payload, `${label}: missing key "${key}"`);
  }
}

function requireVaultRewardShape(payload, label) {
  requireKeys(payload, ['vault'], label);
  requireKeys(
    payload.vault,
    [
      'pending_rewards',
      'pending_rewards_next_week',
      'open_settlement_week',
      'carry_record_royalty',
      'carry_stakers',
      'carry_local_legend',
      'carry_pol',
      'carry_treasury',
      'total_cal_staked',
    ],
    `${label} vault`
  );
}

function requireFreshnessShape(payload, label) {
  requireKeys(payload, ['freshness'], label);
  requireKeys(
    payload.freshness,
    [
      'contract_version',
      'source',
      'status',
      'read_model',
      'tables',
      'account_slot',
      'tx_slot',
      'max_observed_slot',
      'loaded_at',
    ],
    `${label} freshness`
  );
  assert(
    payload.freshness.contract_version === 'scan_freshness.v1',
    `${label} freshness: expected scan_freshness.v1`
  );
  assert(payload.freshness.source === 'indexer', `${label} freshness: expected indexer source`);
  assert(
    ['live', 'catching_up', 'stale', 'unknown'].includes(payload.freshness.status),
    `${label} freshness: unexpected status ${payload.freshness.status}`
  );
  assert(Array.isArray(payload.freshness.tables), `${label} freshness: tables must be an array`);
}

function firstClimbFromList(payload) {
  const climbs = Array.isArray(payload?.climbs) ? payload.climbs : [];
  return climbs.find((climb) => climb && climb.id !== undefined && climb.id !== null) ?? null;
}

async function main() {
  const apiBase = normalizeBaseUrl(readEnv('BOULDERSCAN_API_URL', DEFAULT_API_URL));
  const frontendBase = normalizeBaseUrl(readEnv('BOULDERSCAN_FRONTEND_URL', DEFAULT_FRONTEND_URL));
  const configuredClimbId = readEnv('BOULDERSCAN_CLIMB_ID');
  const configuredVaultId = readEnv('BOULDERSCAN_VAULT_ID');
  let climbId = configuredClimbId;
  let vaultId = configuredVaultId;
  const knownSignature = readEnv('BOULDERSCAN_TX_SIGNATURE');
  const knownAccount = readEnv('BOULDERSCAN_ACCOUNT_PUBKEY');
  const skipFrontend = parseBooleanEnv(readEnv('BOULDERSCAN_SKIP_FRONTEND'));
  const allowStaleIndexer = parseBooleanEnv(readEnv('BOULDERSCAN_ALLOW_STALE_INDEXER'));
  const maxLagSlots = parsePositiveInt(
    readEnv('BOULDERSCAN_MAX_LAG_SLOTS'),
    DEFAULT_MAX_LAG_SLOTS
  );

  if (isPublicHttpsUrl(apiBase)) {
    await checkDns('api dns', apiBase);
    await checkTls('api tls', apiBase);
  }

  if (!skipFrontend && isPublicHttpsUrl(frontendBase)) {
    await checkDns('frontend dns', frontendBase);
    await checkTls('frontend tls', frontendBase);
  }

  console.log(`Checking API at ${apiBase}`);
  await checkJson('health', `${apiBase}/health`, {
    expectStatuses: [200, 503],
    validate(payload) {
      requireKeys(
        payload,
        [
          'status',
          'service',
          'lag_slots',
          'account_lag_slots',
          'tx_lag_slots',
          'last_indexed_slot',
          'last_account_slot',
          'last_tx_slot',
          'stream_connected',
          'timestamp',
        ],
        'health'
      );
      assert(payload.status === 'ok' || payload.status === 'lagging', 'health: unexpected status');
      assert(
        payload.lag_slots !== null && payload.lag_slots !== undefined && payload.lag_slots !== '',
        'health: lag_slots must be present'
      );
      const lagSlots = Number(payload.lag_slots);
      assert(Number.isFinite(lagSlots), 'health: lag_slots must be numeric');
      if (!allowStaleIndexer) {
        assert(
          payload.status === 'ok',
          `health: stale indexer (status ${payload.status}; max ${lagSlots.toLocaleString()} slots, account ${payload.account_lag_slots}, tx ${payload.tx_lag_slots}, threshold ${maxLagSlots.toLocaleString()})`
        );
      }
    },
  });

  await checkJson('status', `${apiBase}/status`, {
    validate(payload) {
      requireKeys(payload, ['status', 'mode', 'sync', 'counts', 'timestamp'], 'status');
      assert(payload.status === 'ok', 'status: expected ok');
    },
  });

  await checkJson('observatory', `${apiBase}/v1/observatory`, {
    validate(payload) {
      requireKeys(
        payload,
        [
          'vault_count',
          'total_riders',
          'total_completions',
          'total_cal_staked',
          'supply',
          'recent_events',
          'top_vaults',
        ],
        'observatory'
      );
      assert(Array.isArray(payload.top_vaults), 'observatory: top_vaults must be an array');
      requireFreshnessShape(payload, 'observatory');
    },
  });

  await checkJson('climb list', `${apiBase}/v1/climbs?limit=1`, {
    validate(payload) {
      requireKeys(
        payload,
        ['climbs', 'total'],
        'climb list'
      );
      assert(Array.isArray(payload.climbs), 'climb list: climbs must be an array');
      const firstClimb = firstClimbFromList(payload);
      if (!configuredClimbId && firstClimb) {
        climbId = String(firstClimb.id);
        console.log(`INFO using climb id ${climbId} from canonical climb list`);
      }
      if (
        !configuredVaultId
        && firstClimb?.has_vault
        && firstClimb.vault_id !== null
        && firstClimb.vault_id !== undefined
      ) {
        vaultId = String(firstClimb.vault_id);
      }
      requireFreshnessShape(payload, 'climb list');
    },
  });

  if (climbId) {
    await checkJson('climb detail', `${apiBase}/v1/climbs/${climbId}`, {
      validate(payload) {
        requireKeys(
          payload,
          ['climb', 'vault', 'leaderboard', 'local_legend', 'recent_events', 'distribution_history'],
          'climb detail'
        );
        if (payload.vault !== null) {
          requireVaultRewardShape(payload, 'climb detail');
        }
        requireFreshnessShape(payload, 'climb detail');
      },
    });
  } else {
    console.log('PASS clean-slate climb state (no ratified V4-B Climb indexed yet)');
  }

  if (vaultId) {
    await checkJson('legacy vault detail', `${apiBase}/v1/vaults/${vaultId}`, {
      validate(payload) {
        requireKeys(
          payload,
          ['vault', 'leaderboard', 'local_legend', 'recent_events', 'distribution_history'],
          'legacy vault detail'
        );
        requireVaultRewardShape(payload, 'legacy vault detail');
        requireFreshnessShape(payload, 'legacy vault detail');
      },
    });
  } else {
    console.log('SKIP legacy vault detail (no active V4-B Vault; set BOULDERSCAN_VAULT_ID)');
  }

  await checkJson('bad account request', `${apiBase}/v1/accounts/not-a-pubkey`, {
    expectStatus: 400,
    validate(payload) {
      requireKeys(payload, ['error'], 'bad account request');
    },
  });

  await checkJson(
    'missing climb',
    `${apiBase}/v1/climbs/00000000-0000-4000-8000-000000000000`,
    {
      expectStatus: 404,
      validate(payload) {
        requireKeys(payload, ['error'], 'missing climb');
      },
    }
  );

  if (knownSignature) {
    await checkJson('transaction detail', `${apiBase}/v1/transactions/${knownSignature}`, {
      validate(payload) {
        requireKeys(
          payload,
          ['signature', 'instructions', 'events', 'status', 'token_flows'],
          'transaction detail'
        );
        assert(Array.isArray(payload.token_flows), 'transaction detail: token_flows must be an array');
        requireFreshnessShape(payload, 'transaction detail');
      },
    });
  } else {
    console.log('SKIP transaction detail (set BOULDERSCAN_TX_SIGNATURE)');
  }

  if (knownAccount) {
    await checkJson('account detail', `${apiBase}/v1/accounts/${knownAccount}`, {
      validate(payload) {
        requireKeys(
          payload,
          ['pubkey', 'user_state', 'beetle_cards', 'active_stakes', 'recent_events', 'spl_balances'],
          'account detail'
        );
      },
    });
  } else {
    console.log('SKIP account detail (set BOULDERSCAN_ACCOUNT_PUBKEY)');
  }

  if (!skipFrontend) {
    console.log(`Checking frontend at ${frontendBase}`);
    await checkHtml('observatory route', `${frontendBase}/`);
    if (climbId) {
      await checkHtml('climb route', `${frontendBase}/climb/${climbId}`);
    } else {
      console.log('SKIP climb route (clean-slate V4-B registry)');
    }
    if (vaultId) {
      await checkHtml('legacy vault route', `${frontendBase}/vault/${vaultId}`);
    } else {
      console.log('SKIP legacy vault route (no active V4-B Vault)');
    }
    await checkJson('frontend api facade', `${frontendBase}/api/health`, {
      expectStatuses: [200, 503],
      validate(payload) {
        requireKeys(payload, ['status', 'service', 'lag_slots', 'timestamp'], 'frontend api facade');
      },
    });

    if (isPublicHttpsUrl(apiBase) && isPublicHttpsUrl(frontendBase)) {
      await checkCors(apiBase, frontendBase);
    }

    if (knownSignature) {
      await checkHtml('transaction route', `${frontendBase}/tx/${knownSignature}`);
    } else {
      console.log('SKIP transaction route (set BOULDERSCAN_TX_SIGNATURE)');
    }

    if (knownAccount) {
      await checkHtml('account route', `${frontendBase}/account/${knownAccount}`);
    } else {
      console.log('SKIP account route (set BOULDERSCAN_ACCOUNT_PUBKEY)');
    }
  } else {
    console.log('SKIP frontend route checks');
  }

  console.log('BoulderScan launch checks passed');
}

main().catch((error) => {
  console.error(`FAIL ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
