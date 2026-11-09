import canon from "./observatory-canon.json";
import { fixtureAccount } from "./data";
import type { AccountResponse, AccountPageData, GroundClimb } from "@/types";
const climbs = canon
  .slice(0, 5)
  .map((c, i) => ({
    ...c,
    attested: true,
    deposited: i < 2 ? String([6200, 1240][i] * 1e9) : undefined,
  }));
const ref = (i: number) => ({ id: climbs[i].id, name: climbs[i].name });
export const fixtureAccountPageData: AccountPageData = {
  handle: "@tim",
  since_week: 12,
  since_date: "2026-04-15",
  rides_attested: 12,
  seats: 1,
  crowns: 1,
  attested_climbs: 5,
  canon_count: canon.length,
  ground: [...climbs, ...canon.slice(5).map(c=>({...c,deposited:undefined,registered:false}))] as GroundClimb[],
  positions: [0, 1].map((i) => ({
    climb: ref(i),
    rank: i + 1,
    since: ["2026-04-15", "2026-06-02"][i],
    cal: String([6200, 1240][i] * 1e9),
  })),
  balances: [
    { account: "B".repeat(32), symbol: "CAL", amount: "22154000000000" },
    { account: "C".repeat(32), symbol: "DUNG", amount: "18750000000" },
  ],
  completions: Array.from({ length: 12 }, (_, i) => ({
    climb: ref(i % 5),
    signature: "D".repeat(87) + String((i % 9) + 1),
    event_index: i,
    time_s: [235, 610, 82][i % 3],
    date: "2026-09-06",
  })),
  completion_count: 12,
  settlements: Array.from({ length: 24 }, (_, i) => ({
    climb: ref(i % 2),
    signature: "E".repeat(87) + String((i % 9) + 1),
    event_index: i,
    week: 141 - Math.floor(i / 2),
    date: "2026-08-30",
    rank: (i % 2) + 1,
    dung: String([3.4, 1.05][i % 2] * 1e9),
  })),
  settlement_count: 24,
  activity: [],
};
fixtureAccountPageData.activity = [
  {
    tx_signature: "F".repeat(88),
    event_index: 0,
    event_name: "CalStaked",
    fields: { amount: "250000000000" },
    slot: 1,
    block_time: "2026-09-06",
    kind: "deposit",
    signature: "F".repeat(88),
    object: { ...ref(1), type: "climb" },
    value: { amount: "250000000000", unit: "CAL" },
  },
];
export const accountFixture = (wallet: string): AccountResponse => ({
  ...fixtureAccount,
  pubkey: wallet,
  room: {
    ...fixtureAccountPageData,
    handle: wallet.startsWith("A") ? "@tim" : undefined,
  },
});
