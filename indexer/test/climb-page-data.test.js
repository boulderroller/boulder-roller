const test = require("node:test");
const assert = require("node:assert/strict");
const {
  handleApiRequest,
  setApiRuntimeForTests,
  resetApiRuntimeForTests,
} = require("../dist/api");
test.afterEach(resetApiRuntimeForTests);
test("Climb page data keeps canon geometry and abstains from every unindexed ledger figure", async () => {
  setApiRuntimeForTests({
    query: async (sql) => ({
      rows: sql.includes("climb-page-data:identity")
        ? [
            {
              geometry: {
                type: "LineString",
                coordinates: [
                  [-75, 40],
                  [-75.01, 40.01],
                ],
              },
            },
          ]
        : sql.includes("WHERE canon.id =")
          ? [
              {
                id: "00000000-0000-4000-8000-000000000007",
                display_name: "Port Royal Avenue",
                version: 3,
                status: "ratified",
                canonical_profile: [],
              },
            ]
          : [],
    }),
  });
  const res = {
    writeHead(status) {
      this.status = status;
    },
    end(body) {
      this.body = JSON.parse(body);
    },
  };
  await handleApiRequest(
    {
      url: "/v1/climbs/00000000-0000-4000-8000-000000000007",
      method: "GET",
      headers: {},
    },
    res,
  );
  assert.equal(res.status, 200);
  assert.equal(res.body.geometry.type, "LineString");
  for (const key of [
    "positions",
    "completions",
    "settlements",
    "room_leaderboard",
  ])
    assert.deepEqual(res.body[key], []);
  assert.deepEqual(res.body.registration, {});
  for (const key of [
    "deposited",
    "leaderboard_pool",
    "completion_count",
    "position_count",
    "settlement_count",
    "indexed",
  ])
    assert.equal(res.body[key], undefined);
});
const {
  buildClimbPageData,
  readPublicBoard,
  publicHandle,
} = require("../dist/climb-page-data");
const wallet = "A".repeat(32),
  privateWallet = "B".repeat(32),
  sig = "C".repeat(88),
  climbAccount = "D".repeat(32),
  vaultAccount = "E".repeat(32);
const fresh = {
  account_slot: 400,
  tx_slot: 399,
  last_account_sync_at: "2026-09-08T12:00:00Z",
  last_tx_sync_at: "2026-09-08T12:00:00Z",
};
const climb = {
  id: "00000000-0000-4000-8000-000000000007",
  canonical_profile: [
    { dist_m: 0, elev_m: 10 },
    { dist_m: 100, elev_m: 20 },
  ],
};
async function projected(overrides = {}) {
  const sqls = [];
  const query = async (sql) => {
    sqls.push(sql);
    let rows = [];
    if (sql.includes("climb-page-data:identity"))
      rows = [
        {
          pda: climbAccount,
          canon_version: 3,
          registered_at: "2026-09-01T12:00:00Z",
          chain_slot: 380,
        },
      ];
    if (sql.includes("climb-page-data:registration"))
      rows = [{ tx_signature: sig, fields: { timestamp: 1788264000 } }];
    if (sql.includes("climb-page-data:clock"))
      rows = [
        {
          settlement_clock_version: 2,
          settlement_clock_v2_starts_at: 1786968000,
          chain_slot: 390,
        },
      ];
    if (sql.includes("climb-page-data:positions"))
      rows = [
        {
          user_pubkey: wallet,
          cal_staked: "1000000000",
          staked_at: 1788264000,
          chain_slot: 390,
        },
        {
          user_pubkey: privateWallet,
          cal_staked: "2000000000",
          chain_slot: 390,
        },
      ];
    if (sql.includes("climb-page-data:handles"))
      rows = [
        {
          wallet,
          username: "tim",
          is_public: true,
          moderation_state: "visible",
        },
        {
          wallet: privateWallet,
          username: "private",
          is_public: false,
          moderation_state: "visible",
        },
      ];
    if (sql.includes("climb-page-data:completions"))
      rows = [
        {
          tx_signature: sig,
          event_index: 1,
          fields: { rider: wallet, time_s: 338, completed_at: 1788264000 },
        },
        { tx_signature: sig, event_index: 2, fields: { rider: privateWallet } },
      ];
    if (sql.includes("climb-page-data:settlements"))
      rows = [
        {
          tx_signature: sig,
          event_index: 3,
          epoch: 139,
          total_distributed: "5050000000",
          block_time: 1788264000,
        },
      ];
    return { rows };
  };
  const vault = {
    leaderboard: [
      {
        user: wallet,
        time_s: 338,
        position: 2,
        rank: 1,
        recorded_at: 1788264000,
      },
    ],
    id: 7,
    pda: vaultAccount,
    total_cal_staked: "12740000000000",
    carry_record_royalty: "1000000000",
    legend: {
      holder: wallet,
      is_active: true,
      term_start_epoch: 100,
      term_end_epoch: 101,
      completions_at_election: 18,
    },
    ...overrides,
  };
  const pageData = await buildClimbPageData(query, climb, vault, fresh, async () => [
    { wallet, position: 2, competition_rank: 1, best_time_seconds: 338 },
  ]);
  return { pageData, sqls };
}
test("uses the attested vault numeral independently of partial position indexing", async () => {
  const { pageData } = await projected();
  assert.equal(pageData.deposited, "12740000000000");
  assert.equal(pageData.positions.length, 2);
});
test("preserves competition rank and abstains from unprojected Leaderboard pool and expired Legend", async () => {
  const { pageData } = await projected();
  assert.equal(pageData.room_leaderboard[0].rank, 1);
  assert.equal(pageData.room_leaderboard[0].position, 2);
  assert.equal(pageData.positions[0].rank, 1);
  assert.equal(pageData.leaderboard_pool, undefined);
  assert.equal(pageData.room_legend, undefined);
});
test("links indexed events and accounts, admits only public handles, and keeps absent values absent", async () => {
  const { pageData, sqls } = await projected();
  assert.equal(pageData.positions[0].handle, "@tim");
  assert.equal(pageData.positions[1].handle, undefined);
  assert.equal(pageData.completions[1].time_s, undefined);
  assert.equal(pageData.completions[1].date, undefined);
  assert.equal(pageData.settlements[0].signature, sig);
  assert.equal(pageData.registration.climb_account, climbAccount);
  assert.equal(pageData.registration.vault_account, vaultAccount);
  assert.equal(pageData.registration.signature, sig);
  assert.equal(pageData.registration.canon_version, 3);
  assert.equal(pageData.registration.climb_number, undefined);
  assert.equal(pageData.registration.point_count, 2);
  assert.ok(
    sqls
      .find((s) => s.includes("climb-page-data:completions"))
      .includes("a.finalized IS TRUE"),
  );
  for (const kind of [
    "positions",
    "completions",
    "settlements",
    "registration",
  ])
    assert.ok(
      sqls
        .find((s) => s.includes(`climb-page-data:${kind}`))
        .includes("successor_handoff_slot"),
    );
});
test("public leaderboard fails closed and never fills a hidden rank gap", async () => {
  const fetcher = async () => ({
    ok: true,
    json: async () => ({
      climb_id: climb.id,
      vault_id: 7,
      entries: [
        { wallet, position: 3, competition_rank: 3, best_time_seconds: 338 },
      ],
    }),
  });
  assert.equal((await readPublicBoard(climb.id, 7, fetcher))[0].position, 3);
  assert.deepEqual(await readPublicBoard(climb.id, 8, fetcher), []);
  assert.deepEqual(
    await readPublicBoard(climb.id, 7, async () => {
      throw Error("private projection unavailable");
    }),
    [],
  );
  assert.equal(
    publicHandle({
      username: "hidden",
      is_public: false,
      moderation_state: "visible",
    }),
    undefined,
  );
});

test("dates enrich only an exact privacy-approved indexed seat", async () => {
  const { pageData } = await projected();
  assert.equal(pageData.room_leaderboard[0].date, "2026-09-01T12:00:00.000Z");
  const { pageData: mismatch } = await projected({
    leaderboard: [
      {
        user: wallet,
        time_s: 338,
        position: 3,
        rank: 1,
        recorded_at: 1788264000,
      },
    ],
  });
  assert.equal(mismatch.room_leaderboard[0].date, undefined);
  const { pageData: duplicate } = await projected({
    leaderboard: [
      {
        user: wallet,
        time_s: 338,
        position: 2,
        rank: 1,
        recorded_at: 1788264000,
      },
      {
        user: wallet,
        time_s: 338,
        position: 2,
        rank: 1,
        recorded_at: 1788264000,
      },
    ],
  });
  assert.equal(duplicate.room_leaderboard[0].date, undefined);
});
