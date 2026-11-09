import { fixtureTransaction } from "./data";
import type { TransactionResponse, TransactionReceipt } from "@/types";
export const receiptKinds = [
  "attestation",
  "settlement",
  "deposit",
  "withdrawal",
  "registration",
  "legend",
  "collection",
] as const;
export const fixtureSignatures = receiptKinds.map((_, i) =>
  "ABCDEFG"[i].repeat(88),
);
export function transactionFixture(
  signature: string,
): TransactionResponse | undefined {
  const index = fixtureSignatures.indexOf(signature);
  if (index < 0) return undefined;
  const kind = receiptKinds[index],
    wallet = "H".repeat(32),
    climb = {
      id: "00000000-0000-4000-8000-000000000007",
      name: "Wises Mill Road",
    };
  const fields: TransactionReceipt["fields"] =
    kind === "attestation"
      ? {
          time_s: 235,
          previous_best_s: 242,
          ride_hash: "a".repeat(64),
          completed: "2026-09-06T09:07:00Z",
          week: 142,
        }
      : kind === "settlement"
        ? {
            week: 141,
            dung: "5050000000",
            week_starts_at: "2026-08-24",
            week_ends_at: "2026-08-30",
            positions_paid: 4,
            completions: 17,
          }
        : kind === "deposit" || kind === "withdrawal"
          ? { cal: "250000000000", rank: 2, since: "2026-06-02T00:00:00Z" }
          : kind === "registration"
            ? {
                canon_version: 3,
                point_count: 192,
                climb_account: "J".repeat(32),
                vault_account: "K".repeat(32),
                week: 142,
              }
            : kind === "legend"
              ? { completions: 17, week: 142 }
              : { dung: "1000000000" };
  return {
    ...fixtureTransaction,
    signature,
    status: "success",
    slot: 482749614,
    block_time: "2026-09-06T09:07:31Z",
    fee_lamports: "20000",
    instructions: [
      {
        instruction_index: 0,
        name: kind,
        args: { ...fields },
        accounts: { rider: wallet, climb: "J".repeat(32) },
      },
    ],
    events: [],
    receipt: {
      kind,
      climb,
      rider: { wallet, handle: "@tim" },
      fields,
      program: "P".repeat(32),
      accounts: [
        { role: "Rider", pubkey: wallet },
        { role: "Climb", pubkey: "J".repeat(32) },
        { role: "Ride proof", pubkey: "M".repeat(32) },
      ],
      paid:
        kind === "settlement"
          ? [
              { wallet, rank: 1, dung: "3400000000" },
              { wallet: "N".repeat(32), rank: 2, dung: "1050000000" },
              { wallet: "Q".repeat(32), rank: 3, dung: "350000000" },
              { wallet: "R".repeat(32), rank: 4, dung: "250000000" },
            ]
          : undefined,
      logs: ["Program log: " + kind],
    },
  };
}
