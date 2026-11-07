/** Explicit board fixture; never a failed-live fallback. Every rider/value is simulated. */
import canon from "./climb-canon.json";
import { fixtureClimbWithVault } from "./data";
import type { ClimbResponse } from "@/types";
const wallets = Array.from({ length: 10 }, (_, i) =>
  "ABCDEFGHJK"[i].repeat(32),
);
const signatures = Array.from(
  { length: 43 },
  (_, i) =>
    "ABCDEFGHJKLMNPQRSTUVWXYZ"[i % 23].repeat(87) +
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"[Math.floor(i / 23)],
);
export const fixtureClimbRoom: ClimbResponse = {
  ...fixtureClimbWithVault,
  climb: {
    ...fixtureClimbWithVault.climb,
    id: "00000000-0000-4000-8000-000000000007",
    name: canon.name,
    length_m: canon.length_m,
    elev_gain_m: canon.elev_gain_m,
    avg_gradient_pct: canon.avg_gradient_pct,
    canonical_profile: canon.canonical_profile,
  },
  geometry: { type: "LineString", coordinates: canon.geometry.coordinates },
  place: "Manayunk · Philadelphia",
  registration: {
    climb_account: "M".repeat(32),
    vault_account: "N".repeat(32),
    signature: "P".repeat(88),
    week: 12,
    climb_number: 7,
    canon_version: 3,
    point_count: 192,
  },
  deposited: "12740000000000",
  leaderboard_pool: "3340000000000",
  completion_count: 43,
  position_count: 4,
  settlement_count: 12,
  positions: [6200, 4100, 1240, 1200].map((cal, i) => ({
    wallet: wallets[i],
    cal: String(cal * 1e9),
    rank: i < 3 ? i + 1 : undefined,
    since: ["2026-04-15", "2026-05-03", "2026-06-02", "2026-08-09"][i],
  })),
  room_leaderboard: [294, 310, 322, 329, 333, 338, 341, 347, 352, 363].map(
    (time_s, i) => ({
      wallet: wallets[i],
      handle:
        i === 6
          ? undefined
          : [
              "@marcus",
              "@priya",
              "@jordan",
              "@elena",
              "@dev",
              "@sam",
              "",
              "@nia",
              "@tomas",
              "@hana",
            ][i],
      rank: i + 1,
      position: i + 1,
      time_s,
      date: [
        "2026-08-22",
        "2026-07-03",
        "2026-08-30",
        "2026-06-14",
        "2026-08-09",
        "2026-05-27",
        "2026-08-17",
        "2026-07-21",
        "2026-08-02",
        "2026-06-30",
      ][i],
    }),
  ),
  room_legend: { wallet: wallets[2], handle: "@jordan", completions: 18 },
  completions: Array.from({ length: 43 }, (_, i) => ({
    wallet: wallets[i % 10],
    handle: ["@tim", "@dungbeetlephoenix", "@priya"][i % 3],
    signature: signatures[i],
    event_index: i,
    date: new Date(Date.UTC(2026, 8, 6 - i)).toISOString(),
    time_s: [338, 364, 352][i % 3],
  })),
  settlements: Array.from({ length: 12 }, (_, i) => ({
    week: 141 - i,
    date: new Date(Date.UTC(2026, 7, 30 - i * 7)).toISOString(),
    dung: String([505, 490, 472][i % 3] * 1e7),
    signature: signatures[i],
    event_index: i,
  })),
  indexed: { slot: 399999999, at: "2026-09-08T12:00:00Z", age_seconds: 180 },
};
