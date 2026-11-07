const test = require("node:test");
const assert = require("node:assert/strict");
const {
  handleApiRequest,
  setApiRuntimeForTests,
  resetApiRuntimeForTests,
} = require("../dist/api.js");
test.afterEach(resetApiRuntimeForTests);
test("observatory adds a whole-canon room and never fabricates unindexed figures", async () => {
  setApiRuntimeForTests({
    query: async (sql) => {
      if (sql.includes("observatory:ground"))
        return {
          rows: [
            {
              id: "canon",
              display_name: "Lemon Hill",
              geometry: {
                type: "LineString",
                coordinates: [
                  [-75, 40],
                  [-75.01, 40.01],
                ],
              },
              length_m: 600,
              vert_m: 30,
              avg_gradient_pct: 5,
              climb_pda: null,
              vault_id: null,
            },
          ],
        };
      return { rows: [] };
    },
  });
  const res = {
    writeHead(code) {
      this.status = code;
    },
    end(body) {
      this.body = JSON.parse(body);
    },
  };
  await handleApiRequest(
    { url: "/v1/observatory", method: "GET", headers: {} },
    res,
  );
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.week, {});
  assert.equal(res.body.climbs.length, 1);
  assert.equal(res.body.climbs[0].registered, undefined);
  assert.equal(res.body.climbs[0].deposited, undefined);
  assert.equal(res.body.indexed, undefined);
});

const {
  projectRoomEvent,
  projectWeekClock,
  projectIndexed,
  projectGround,
} = require("../dist/observatory.js");
test("Local Legend trailing count uses the real winner_completions payload", () => {
  const row = projectRoomEvent(
    {
      event_name: "LocalLegendElected",
      tx_signature: "sig",
      fields: { winner: "rider", winner_completions: 8 },
    },
    [],
  );
  assert.deepEqual(row.value, { amount: 8, unit: "rides" });
});
test("retired climb settlement keeps its resolved object outside the current ground", () => {
  const row = projectRoomEvent(
    {
      event_name: "EpochRewardsDistributed",
      tx_signature: "sig",
      climb_id: "retired-id",
      climb_name: "Retired Hill",
      fields: { epoch: 139, total_distributed: "1234567890123456789" },
    },
    [],
  );
  assert.deepEqual(row.object, {
    id: "retired-id",
    name: "Retired Hill",
    type: "climb",
  });
  assert.deepEqual(row.value, { amount: "1234567890123456789", unit: "DUNG" });
});

test("indexed Week clock preserves immutable boundary, transition, and grace", () => {
  const config = {
    chain_slot: 100,
    settlement_clock_version: 2,
    settlement_clock_v2_starts_at: 1704110400,
  };
  const week = projectWeekClock(config, "2026-09-07T15:15:06Z");
  assert.equal(week.epoch, 140);
  assert.equal(
    new Date(week.ends_at * 1000).toISOString(),
    "2026-09-14T12:00:00.000Z",
  );
  assert.equal(
    new Date(week.finalizes_at * 1000).toISOString(),
    "2026-09-15T12:00:00.000Z",
  );
  assert.deepEqual(projectWeekClock(undefined, "2026-09-07T15:15:06Z"), {});
  assert.deepEqual(
    projectWeekClock(
      { ...config, settlement_clock_version: 1 },
      "2026-09-07T15:15:06Z",
    ),
    {},
  );
  assert.deepEqual(
    projectWeekClock(
      { ...config, settlement_clock_v2_starts_at: 1704110401 },
      "2026-09-07T15:15:06Z",
    ),
    {},
  );
  const transition = projectWeekClock(
    { ...config, settlement_clock_v2_starts_at: 1704110400 + 100 * 604800 },
    new Date((1704110400 + 100 * 604800 - 1) * 1000).toISOString(),
  );
  assert.equal(transition.epoch, 100);
  assert.equal(transition.ends_at - transition.starts_at, 694800);
});
test("a missing checkpoint never certifies registration or deposited CAL", () => {
  const row = {
    id: "x",
    display_name: "Hill",
    climb_pda: "pda",
    vault_id: 1,
    total_cal_staked: "1234567890123456789",
    total_completions: "9",
  };
  assert.equal(projectGround(row, false).deposited, undefined);
  assert.equal(projectGround(row, false).registered, undefined);
  assert.equal(projectGround(row, true).deposited, "1234567890123456789");
  assert.equal(
    projectGround({ ...row, vault_id: null }, true).deposited,
    undefined,
  );
  assert.equal(projectIndexed({ account_slot: 200, tx_slot: 0 }), undefined);
  const stamp = projectIndexed({
    account_slot: 200,
    tx_slot: 100,
    last_account_sync_at: "2026-09-07T12:00:00Z",
    last_tx_sync_at: "2026-09-07T13:00:00Z",
  });
  assert.equal(stamp.slot, 100);
  assert.equal(stamp.at, "2026-09-07T12:00:00.000Z");
});
test("room API keeps atomic custody totals separate, uses real clock, and paginates", async () => {
  const observed = [];
  setApiRuntimeForTests({
    query: async (sql, params) => {
      observed.push({ sql, params });
      if (sql.includes("indexer_sync_state"))
        return {
          rows: [
            {
              last_account_slot: 200,
              last_tx_slot: 190,
              last_account_sync_at: "2026-09-07T15:00:00Z",
              last_tx_sync_at: "2026-09-07T16:00:00Z",
            },
          ],
        };
      if (sql.includes("observatory:clock"))
        return {
          rows: [
            {
              chain_slot: 150,
              settlement_clock_version: 2,
              settlement_clock_v2_starts_at: 1704110400,
            },
          ],
        };
      if (sql.includes("observatory:week"))
        return {
          rows: [
            { rides_attested: "4", dung_distributed: "1234567890123456789" },
          ],
        };
      if (sql.includes("COUNT(*) AS total")) return { rows: [{ total: "57" }] };
      if (sql.includes("AS total_riders"))
        return {
          rows: [
            { total_riders: "2", total_cal_staked: "9999999999999999999" },
          ],
        };
      if (sql.includes("FROM indexed_events"))
        return {
          rows: Array.from({ length: 20 }, (_, i) => ({
            tx_signature: "sig" + i,
            event_index: 0,
            event_name: "CalStaked",
            fields: { staker: "rider", amount: "1000000000" },
          })),
        };
      return { rows: [] };
    },
  });
  const res = {
    writeHead(code) {
      this.status = code;
    },
    end(body) {
      this.body = JSON.parse(body);
    },
  };
  await handleApiRequest(
    { url: "/v1/observatory?events_offset=20", method: "GET", headers: {} },
    res,
  );
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.week, {
    climbs_registered: 57,
    cal_deposited: "9999999999999999999",
    riders: 2,
    epoch: 140,
    settles_at: "2026-09-15T12:00:00.000Z",
    rides_attested: 4,
    dung_distributed: "1234567890123456789",
  });
  assert.equal(res.body.events_next_offset, 40);
  assert.deepEqual(
    observed.find((q) => q.sql.includes("observatory:week")).params,
    [140, 139],
  );
  assert.deepEqual(
    observed.find((q) => q.sql.includes("FROM indexed_events")).params,
    [20],
  );
});
